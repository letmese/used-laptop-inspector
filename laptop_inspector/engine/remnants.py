"""Evidence that a discrete GPU existed on this machine and no longer enumerates.

This is the hard part of the dGPU check, and it is the scam the brief calls out:
a faulty Quadro is switched off in BIOS, Windows never sees it, the seller says
"that model never had one", and the buyer has no way to argue.

Four independent traces, cheapest first:

  * `HKLM\\SYSTEM\\CurrentControlSet\\Enum\\PCI\\VEN_10DE*` - every PCI device the
    OS has ever enumerated. Survives the device being disabled in BIOS, because
    the key is written the first time Windows saw it.
  * The display class key `...\\Control\\Class\\{4d36e968-...}` - one subkey per
    display adapter that was ever installed, with its DriverDesc.
  * Driver packages in `DriverStore\\FileRepository` (nv*.inf, amd*.inf).
  * Leftover vendor directories and services.

None of these require the device to be present right now.
"""

from __future__ import annotations

import os
import winreg
from typing import Any, Dict, List

DISPLAY_CLASS_GUID = "{4d36e968-e325-11ce-bfc1-08002be10318}"
PCI_ENUM = r"SYSTEM\CurrentControlSet\Enum\PCI"

VENDORS = {
    "10DE": "NVIDIA",
    "1002": "AMD",
    "8086": "Intel",
    "8087": "Intel",
}

DRIVER_STORE = os.path.join(
    os.environ.get("SystemRoot", r"C:\Windows"),
    "System32", "DriverStore", "FileRepository")


def _subkeys(root, path: str) -> List[str]:
    try:
        with winreg.OpenKey(root, path) as key:
            count = winreg.QueryInfoKey(key)[0]
            return [winreg.EnumKey(key, i) for i in range(count)]
    except OSError:
        return []


def _value(root, path: str, name: str) -> Any:
    try:
        with winreg.OpenKey(root, path) as key:
            return winreg.QueryValueEx(key, name)[0]
    except OSError:
        return None


def pci_devices() -> Dict[str, List[Dict[str, Any]]]:
    """PCI vendor -> device keys seen by this Windows install, ever."""
    found: Dict[str, List[Dict[str, Any]]] = {}
    for entry in _subkeys(winreg.HKEY_LOCAL_MACHINE, PCI_ENUM):
        if not entry.startswith("VEN_"):
            continue
        vendor = entry[4:8]
        if vendor not in VENDORS:
            continue
        devices = []
        base = f"{PCI_ENUM}\\{entry}"
        for dev in _subkeys(winreg.HKEY_LOCAL_MACHINE, base)[:12]:
            desc = _value(winreg.HKEY_LOCAL_MACHINE, f"{base}\\{dev}", "DeviceDesc")
            if isinstance(desc, str) and ";" in desc:
                desc = desc.split(";")[-1]
            devices.append({"device": dev, "desc": desc or ""})
        found.setdefault(vendor, []).extend(devices)
    return found


def display_class_adapters() -> List[Dict[str, Any]]:
    """Adapters that were installed at some point, per the display class key."""
    base = rf"SYSTEM\CurrentControlSet\Control\Class\{DISPLAY_CLASS_GUID}"
    out = []
    for sub in _subkeys(winreg.HKEY_LOCAL_MACHINE, base):
        if not sub.isdigit():
            continue
        desc = _value(winreg.HKEY_LOCAL_MACHINE, f"{base}\\{sub}", "DriverDesc")
        matching = _value(winreg.HKEY_LOCAL_MACHINE, f"{base}\\{sub}",
                          "MatchingDeviceId")
        if desc:
            out.append({"slot": sub, "desc": str(desc),
                        "matching_id": str(matching or "")})
    return out


def driver_store_packages(prefixes: tuple) -> List[str]:
    hits: List[str] = []
    try:
        with os.scandir(DRIVER_STORE) as it:
            for entry in it:
                low = entry.name.lower()
                if low.startswith(prefixes):
                    hits.append(entry.name)
                    if len(hits) >= 40:
                        break
    except OSError:
        pass
    return hits


def vendor_traces() -> Dict[str, Any]:
    traces: Dict[str, Any] = {}

    # ---- NVIDIA
    nv_service = _value(winreg.HKEY_LOCAL_MACHINE,
                        r"SYSTEM\CurrentControlSet\Services\nvlddmkm", "ImagePath")
    nv_reg = bool(_subkeys(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\NVIDIA Corporation"))
    nv_prog = os.path.isdir(r"C:\Program Files\NVIDIA Corporation")
    nv_store = driver_store_packages(("nv", "nvlddmkm"))
    traces["nvidia"] = {
        "service": bool(nv_service),
        "registry": nv_reg,
        "program_files": nv_prog,
        "driverstore": nv_store[:10],
        "driverstore_count": len(nv_store),
        "present": any([nv_service, nv_reg, nv_prog, bool(nv_store)]),
    }

    # ---- AMD
    amd_service = (_value(winreg.HKEY_LOCAL_MACHINE,
                          r"SYSTEM\CurrentControlSet\Services\amdkmdag", "ImagePath")
                   or _value(winreg.HKEY_LOCAL_MACHINE,
                             r"SYSTEM\CurrentControlSet\Services\amdkmdap", "ImagePath"))
    amd_reg = bool(_subkeys(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\AMD"))
    amd_prog = (os.path.isdir(r"C:\Program Files\AMD")
                or os.path.isdir(r"C:\Program Files\AMD\\CNext"))
    amd_store = driver_store_packages(("amdkmd", "u0", "c0"))
    traces["amd"] = {
        "service": bool(amd_service),
        "registry": amd_reg,
        "program_files": amd_prog,
        "driverstore": amd_store[:10],
        "driverstore_count": len(amd_store),
        "present": any([amd_service, amd_reg, amd_prog, bool(amd_store)]),
    }
    return traces


def collect() -> Dict[str, Any]:
    pci = pci_devices()
    return {
        "pci_vendors": {v: len(devs) for v, devs in pci.items()},
        "pci_devices": {v: devs[:8] for v, devs in pci.items()},
        "display_class": display_class_adapters(),
        "traces": vendor_traces(),
    }
