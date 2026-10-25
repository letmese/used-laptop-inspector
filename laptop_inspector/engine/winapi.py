"""Native Windows access layer - pure ctypes, no third-party binaries.

Covers the four things WMI cannot give us:
  * ATA SMART via DeviceIoControl(SMART_RCV_DRIVE_DATA)
  * NVMe SMART/Health log via IOCTL_STORAGE_QUERY_PROPERTY
  * ACPI MSDM table (the OEM Windows key burned into firmware)
  * Per-core clock speed via CallNtPowerInformation (cheap, no WMI polling)

Design rule: every function here returns None instead of raising when the
platform, the driver or the permissions refuse. A 2013 laptop with no NVMe must
still produce a report.
"""

from __future__ import annotations

import ctypes
import os
import re
from ctypes import wintypes
from typing import Any, Dict, List, Optional

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
powrprof = ctypes.WinDLL("powrprof", use_last_error=True)

GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
FILE_SHARE_READ = 0x00000001
FILE_SHARE_WRITE = 0x00000002
OPEN_EXISTING = 3
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

SMART_RCV_DRIVE_DATA = 0x0007C088
IOCTL_STORAGE_QUERY_PROPERTY = 0x002D1400
IOCTL_DISK_GET_LENGTH_INFO = 0x0007405C
IOCTL_STORAGE_PREDICT_FAILURE = 0x002D1100

# STORAGE_PROPERTY_ID
StorageDeviceProperty = 0
StorageAdapterProperty = 1
StorageDeviceProtocolSpecificProperty = 49
StorageAdapterProtocolSpecificProperty = 50

# STORAGE_PROTOCOL_TYPE
ProtocolTypeNvme = 3
NVMeDataTypeSmartData = 0x02

ATA_SMART_READ_DATA = 0xD0
ATA_IDENTIFY = 0xEC


# --------------------------------------------------------------------------
# structs
# --------------------------------------------------------------------------
class IDEREGS(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
        ("bFeaturesReg", ctypes.c_ubyte),
        ("bSectorCountReg", ctypes.c_ubyte),
        ("bSectorNumberReg", ctypes.c_ubyte),
        ("bCylLowReg", ctypes.c_ubyte),
        ("bCylHighReg", ctypes.c_ubyte),
        ("bDriveHeadReg", ctypes.c_ubyte),
        ("bCommandReg", ctypes.c_ubyte),
        ("bReserved", ctypes.c_ubyte),
    ]


class SENDCMDINPARAMS(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
        ("cBufferSize", wintypes.DWORD),
        ("irDriveRegs", IDEREGS),
        ("bDriveNumber", ctypes.c_ubyte),
        ("bReserved", ctypes.c_ubyte * 3),
        ("dwReserved", wintypes.DWORD * 4),
        ("bBuffer", ctypes.c_ubyte * 1),
    ]


class DRIVERSTATUS(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
        ("bDriverError", ctypes.c_ubyte),
        ("bIDEError", ctypes.c_ubyte),
        ("bReserved", ctypes.c_ubyte * 2),
        ("dwReserved", wintypes.DWORD * 2),
    ]


class SENDCMDOUTPARAMS(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
        ("cBufferSize", wintypes.DWORD),
        ("DriverStatus", DRIVERSTATUS),
        ("bBuffer", ctypes.c_ubyte * 1),
    ]


class PROCESSOR_POWER_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("Number", wintypes.ULONG),
        ("MaxMhz", wintypes.ULONG),
        ("CurrentMhz", wintypes.ULONG),
        ("MhzLimit", wintypes.ULONG),
        ("MaxIdleState", wintypes.ULONG),
        ("CurrentIdleState", wintypes.ULONG),
    ]


class SYSTEM_POWER_STATUS(ctypes.Structure):
    _fields_ = [
        ("ACLineStatus", ctypes.c_ubyte),
        ("BatteryFlag", ctypes.c_ubyte),
        ("BatteryLifePercent", ctypes.c_ubyte),
        ("SystemStatusFlag", ctypes.c_ubyte),
        ("BatteryLifeTime", wintypes.DWORD),
        ("BatteryFullLifeTime", wintypes.DWORD),
    ]


kernel32.CreateFileW.restype = wintypes.HANDLE
kernel32.CreateFileW.argtypes = [
    wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
    wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
]
kernel32.DeviceIoControl.restype = wintypes.BOOL
kernel32.DeviceIoControl.argtypes = [
    wintypes.HANDLE, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD,
    ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p,
]
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def open_drive(index: int, write: bool = True) -> Optional[int]:
    access = GENERIC_READ | (GENERIC_WRITE if write else 0)
    path = f"\\\\.\\PhysicalDrive{index}"
    handle = kernel32.CreateFileW(
        path, access, FILE_SHARE_READ | FILE_SHARE_WRITE,
        None, OPEN_EXISTING, 0, None,
    )
    if not handle or handle == INVALID_HANDLE_VALUE:
        return None
    return handle


def close_drive(handle: Optional[int]) -> None:
    if handle and handle != INVALID_HANDLE_VALUE:
        try:
            kernel32.CloseHandle(handle)
        except Exception:
            pass


def _ioctl(handle: int, code: int, in_buf: Any, in_size: int,
           out_size: int) -> Optional[bytes]:
    out = ctypes.create_string_buffer(out_size)
    returned = wintypes.DWORD(0)
    ok = kernel32.DeviceIoControl(
        handle, code, in_buf, in_size, out, out_size,
        ctypes.byref(returned), None,
    )
    if not ok:
        return None
    return out.raw[: returned.value]


def list_physical_drives() -> List[int]:
    """Probe PhysicalDrive0..15 by opening each - cheaper than SetupAPI."""
    found = []
    for i in range(16):
        h = open_drive(i, write=False)
        if h:
            found.append(i)
            close_drive(h)
    return found


def disk_length(handle: int) -> Optional[int]:
    raw = _ioctl(handle, IOCTL_DISK_GET_LENGTH_INFO, None, 0, 8)
    if not raw or len(raw) < 8:
        return None
    return int.from_bytes(raw[:8], "little")


# --------------------------------------------------------------------------
# ATA SMART
# --------------------------------------------------------------------------
def _ata_command(handle: int, command: int, features: int = 0,
                 sector_count: int = 1, cyl_low: int = 0x4F,
                 cyl_high: int = 0xC2) -> Optional[bytes]:
    size = ctypes.sizeof(SENDCMDINPARAMS) + 512
    buf = ctypes.create_string_buffer(size)
    params = ctypes.cast(buf, ctypes.POINTER(SENDCMDINPARAMS)).contents
    params.cBufferSize = 512
    params.irDriveRegs.bFeaturesReg = features
    params.irDriveRegs.bSectorCountReg = sector_count
    params.irDriveRegs.bSectorNumberReg = 1
    params.irDriveRegs.bCylLowReg = cyl_low
    params.irDriveRegs.bCylHighReg = cyl_high
    params.irDriveRegs.bDriveHeadReg = 0xA0
    params.irDriveRegs.bCommandReg = command
    params.bDriveNumber = 0

    out = _ioctl(handle, SMART_RCV_DRIVE_DATA, buf,
                 ctypes.sizeof(SENDCMDINPARAMS), 512 + 32)
    if not out or len(out) < 32:
        return None
    payload = out[16:]
    if len(payload) < 512:
        return None
    if not any(payload[:64]):
        return None
    return payload[:512]


def ata_smart_read(handle: int) -> Optional[bytes]:
    return _ata_command(handle, ATA_SMART_READ_DATA, features=ATA_SMART_READ_DATA)


def predict_failure_smart(handle: int) -> Optional[bytes]:
    """Read the SMART data block through IOCTL_STORAGE_PREDICT_FAILURE.

    This is the path that actually works. On Windows 11 `SMART_RCV_DRIVE_DATA`
    returns ERROR_ACCESS_DENIED (5) even for an elevated process with a write
    handle - verified on the W520, both drives, every struct-size variant.
    PREDICT_FAILURE is permitted and returns STORAGE_PREDICT_FAILURE:

        DWORD PredictFailure;
        BYTE  VendorSpecific[512];   <- the standard SMART data block

    So attribute parsing is identical; only the transport differs.
    """
    raw = _ioctl(handle, IOCTL_STORAGE_PREDICT_FAILURE, None, 0, 528)
    if not raw or len(raw) < 4 + 362:
        return None
    block = raw[4:4 + 512]
    # A drive that answers with an empty block has nothing to say.
    if not any(block[2:362]):
        return None
    return block


def smart_block(handle: int) -> tuple:
    """Try every transport, cheapest first. Returns (block, transport_name)."""
    nvme = nvme_smart_log(handle)
    if nvme:
        return nvme, "nvme"
    block = ata_smart_read(handle)
    if block and any(block[2:362]):
        return block, "smart_ioctl"
    block = predict_failure_smart(handle)
    if block:
        return block, "predict_failure"
    return None, "none"


def ata_identify(handle: int) -> Optional[bytes]:
    return _ata_command(handle, ATA_IDENTIFY, features=0,
                        cyl_low=0, cyl_high=0)


def _ata_string(raw: bytes) -> str:
    """IDENTIFY strings are word-swapped."""
    try:
        swapped = bytearray(raw)
        for i in range(0, len(swapped) - 1, 2):
            swapped[i], swapped[i + 1] = swapped[i + 1], swapped[i]
        return swapped.decode("ascii", "ignore").strip("\x00 ").strip()
    except Exception:
        return ""


def parse_identify(raw: Optional[bytes]) -> Dict[str, Any]:
    if not raw or len(raw) < 512:
        return {}
    return {
        "model": _ata_string(raw[54:94]),
        "serial": _ata_string(raw[20:40]),
        "firmware": _ata_string(raw[46:54]),
        "rotation_rate": int.from_bytes(raw[217:219], "little"),
    }


def parse_smart_attributes(raw: Optional[bytes]) -> Dict[int, Dict[str, Any]]:
    """30 x 12-byte attribute entries starting at offset 2."""
    attrs: Dict[int, Dict[str, Any]] = {}
    if not raw or len(raw) < 362:
        return attrs
    for i in range(30):
        off = 2 + i * 12
        entry = raw[off: off + 12]
        if len(entry) < 12:
            break
        attr_id = entry[0]
        if attr_id == 0:
            continue
        raw6 = entry[5:11]
        attrs[attr_id] = {
            "id": attr_id,
            "value": entry[3],
            "worst": entry[4],
            "threshold": 0,
            "raw": int.from_bytes(raw6, "little"),
            "raw_low32": int.from_bytes(raw6[:4], "little"),
            "raw_hex": raw6.hex(),
        }
    return attrs


# --------------------------------------------------------------------------
# NVMe SMART
# --------------------------------------------------------------------------
def nvme_smart_log(handle: int) -> Optional[bytes]:
    for prop_id in (StorageDeviceProtocolSpecificProperty,
                    StorageAdapterProtocolSpecificProperty):
        query = (
            prop_id.to_bytes(4, "little")          # PropertyId
            + (0).to_bytes(4, "little")            # QueryType = Standard
            + ProtocolTypeNvme.to_bytes(4, "little")
            + NVMeDataTypeSmartData.to_bytes(4, "little")
            + (0).to_bytes(4, "little")            # RequestValue
            + (0).to_bytes(4, "little")            # RequestSubValue
            + (40).to_bytes(4, "little")           # ProtocolDataOffset
            + (512).to_bytes(4, "little")          # ProtocolDataLength
            + (0).to_bytes(4, "little")            # FixedProtocolReturnData
            + (0).to_bytes(4, "little") * 3        # SubValue2..4
        )
        raw = _ioctl(handle, IOCTL_STORAGE_QUERY_PROPERTY,
                     query, len(query), 4096)
        if raw and len(raw) >= 48 + 64:
            data = raw[48:]
            # a log of all zeros means the driver handed back nothing useful
            if any(data[:64]):
                return data
    return None


def parse_nvme_smart(data: Optional[bytes]) -> Dict[str, Any]:
    if not data or len(data) < 191:
        return {}

    def u128(off: int) -> int:
        return int.from_bytes(data[off: off + 16], "little")

    temp_k = int.from_bytes(data[1:3], "little")
    return {
        "critical_warning": data[0],
        "temperature_c": round(temp_k - 273.15, 1) if temp_k else None,
        "available_spare_pct": data[3],
        "spare_threshold_pct": data[4],
        "percentage_used": data[5],
        "data_units_read": u128(23),
        "data_units_written": u128(39),
        "bytes_written": u128(39) * 512000,
        "bytes_read": u128(23) * 512000,
        "power_cycles": u128(103),
        "power_on_hours": u128(119),
        "unsafe_shutdowns": u128(135),
        "media_errors": u128(151),
        "error_log_entries": u128(167),
        "warning_temp_minutes": int.from_bytes(data[183:187], "little"),
        "critical_temp_minutes": int.from_bytes(data[187:191], "little"),
    }


# --------------------------------------------------------------------------
# storage descriptor (works in WinPE where MSFT_PhysicalDisk may be absent)
# --------------------------------------------------------------------------
def storage_descriptor(handle: int) -> Dict[str, Any]:
    query = (0).to_bytes(4, "little") + (0).to_bytes(4, "little")
    raw = _ioctl(handle, IOCTL_STORAGE_QUERY_PROPERTY, query, len(query), 1024)
    if not raw or len(raw) < 36:
        return {}
    try:
        vendor_off = int.from_bytes(raw[12:16], "little")
        product_off = int.from_bytes(raw[16:20], "little")
        rev_off = int.from_bytes(raw[20:24], "little")
        serial_off = int.from_bytes(raw[24:28], "little")
        bus_type = int.from_bytes(raw[28:32], "little")
        removable = raw[10]

        def cstr(off: int) -> str:
            if not off or off >= len(raw):
                return ""
            end = raw.find(b"\x00", off)
            if end < 0:
                end = len(raw)
            return raw[off:end].decode("ascii", "ignore").strip()

        return {
            "vendor": cstr(vendor_off),
            "product": cstr(product_off),
            "revision": cstr(rev_off),
            "serial": cstr(serial_off),
            "bus_type": bus_type,
            "removable": bool(removable),
        }
    except Exception:
        return {}


# --------------------------------------------------------------------------
# ACPI tables (MSDM -> OEM Windows key)
# --------------------------------------------------------------------------
def _acpi_table_ids() -> List[int]:
    size = kernel32.EnumSystemFirmwareTables(0x41435049, None, 0)
    if not size:
        return []
    buf = ctypes.create_string_buffer(size)
    if not kernel32.EnumSystemFirmwareTables(0x41435049, buf, size):
        return []
    return [int.from_bytes(buf.raw[i:i + 4], "little") for i in range(0, size, 4)]


def read_acpi_table(signature: bytes = b"MSDM") -> Optional[bytes]:
    try:
        for table_id in _acpi_table_ids():
            raw = None
            size = kernel32.GetSystemFirmwareTable(0x41435049, table_id, None, 0)
            if not size:
                continue
            buf = ctypes.create_string_buffer(size)
            if not kernel32.GetSystemFirmwareTable(0x41435049, table_id, buf, size):
                continue
            raw = buf.raw[:size]
            if raw[:4] == signature:
                return raw
        # fall back to a direct request by signature
        table_id = int.from_bytes(signature, "little")
        size = kernel32.GetSystemFirmwareTable(0x41435049, table_id, None, 0)
        if size:
            buf = ctypes.create_string_buffer(size)
            if kernel32.GetSystemFirmwareTable(0x41435049, table_id, buf, size):
                raw = buf.raw[:size]
                if raw[:4] == signature:
                    return raw
    except Exception:
        pass
    return None


_PRODUCT_KEY = re.compile(r"[A-Z0-9]{5}(?:-[A-Z0-9]{5}){4}")
_DASHLESS_KEY = re.compile(r"[A-Z0-9]{25}")


def parse_msdm_key(raw: Optional[bytes]) -> Optional[str]:
    """Scan instead of trusting a fixed offset - table revisions differ."""
    if not raw or len(raw) < 56:
        return None
    body = raw[36:]
    text = "".join(chr(c) if 32 < c < 127 else "-" for c in body).upper()
    m = _PRODUCT_KEY.search(text)
    if m:
        return m.group(0)
    # Stored as 25 contiguous alphanumerics. Match a contiguous run rather than
    # stripping separators - otherwise OEMID and padding get glued onto the key.
    m = _DASHLESS_KEY.search(text)
    if m:
        key = m.group(0)
        return "-".join(key[i:i + 5] for i in range(0, 25, 5))
    return None


# --------------------------------------------------------------------------
# clock sampling
# --------------------------------------------------------------------------
def processor_clocks() -> List[Dict[str, int]]:
    """Per-logical-core MHz. Cheap enough to call once a second."""
    count = os.cpu_count() or 1
    size = ctypes.sizeof(PROCESSOR_POWER_INFORMATION) * count
    buf = ctypes.create_string_buffer(size)
    status = powrprof.CallNtPowerInformation(
        11, None, 0, buf, size)  # ProcessorInformation
    if status != 0:
        return []
    arr = ctypes.cast(
        buf, ctypes.POINTER(PROCESSOR_POWER_INFORMATION * count)).contents
    return [
        {
            "number": arr[i].Number,
            "max_mhz": arr[i].MaxMhz,
            "current_mhz": arr[i].CurrentMhz,
            "limit_mhz": arr[i].MhzLimit,
        }
        for i in range(count)
    ]


def power_status() -> Dict[str, Any]:
    st = SYSTEM_POWER_STATUS()
    if not kernel32.GetSystemPowerStatus(ctypes.byref(st)):
        return {}
    return {
        "ac_online": st.ACLineStatus == 1,
        "on_battery": st.ACLineStatus == 0,
        "battery_percent": st.BatteryLifePercent,
    }
