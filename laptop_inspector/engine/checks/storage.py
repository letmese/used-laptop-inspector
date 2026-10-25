"""Storage health via native SMART.

ATA drives: DeviceIoControl(SMART_RCV_DRIVE_DATA) -> the 30-entry attribute table.
NVMe drives: IOCTL_STORAGE_QUERY_PROPERTY -> the NVMe SMART/Health log.

The check treats "SMART is unreadable" as a finding in its own right. A wiped or
disabled SMART table is a red flag, not a gap in the data - it is one of the
cheapest things a seller can do to hide a dying drive.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from .. import result as R
from .. import util, winapi
from ..context import Context, cost_of, storage_cost

KEY = "storage"
LABEL = "Storage health"

# ATA attribute IDs
A_REALLOCATED = 5
A_POWER_ON_HOURS = 9
A_REPORTED_UNCORRECT = 187
A_CRC_ERRORS = 199
A_PENDING = 197
A_OFFLINE_UNCORRECT = 198
A_TEMPERATURE = 194
A_SSD_LIFE_LEFT = 231
A_WEAR_LEVELING = 233
A_PERCENT_LIFETIME = 202
A_LBAS_WRITTEN = 241

# Names for the attributes we surface in the UI. Anything not listed is shown by
# its numeric ID rather than guessed at.
SMART_NAMES = {
    1: "Raw Read Error Rate", 2: "Throughput Performance", 3: "Spin-Up Time",
    4: "Start/Stop Count", 5: "Reallocated Sectors", 7: "Seek Error Rate",
    8: "Seek Time Performance", 9: "Power-On Hours", 10: "Spin Retry Count",
    11: "Recalibration Retries", 12: "Power Cycle Count",
    13: "Soft Read Error Rate", 160: "Uncorrectable Errors",
    161: "Valid Spare Blocks", 163: "Valid Spare Blocks", 165: "Max PE Cycles",
    166: "Min Erase Count", 167: "Avg Erase Count", 168: "Max Erase Count",
    170: "Available Reserved Space", 171: "Program Fail Count",
    172: "Erase Fail Count", 173: "Wear Leveling Count", 174: "Unexpected Power Loss",
    175: "Power Loss Protection Failure", 177: "Wear Range Delta",
    179: "Used Reserved Block Count", 181: "Program Fail Count",
    182: "Erase Fail Count", 184: "End-to-End Error", 187: "Reported Uncorrectable",
    188: "Command Timeout", 190: "Airflow Temperature", 191: "Shock Sensor",
    192: "Power-Off Retract Count", 193: "Load Cycle Count", 194: "Temperature",
    195: "Hardware ECC Recovered", 196: "Reallocation Events",
    197: "Current Pending Sectors", 198: "Offline Uncorrectable",
    199: "UDMA CRC Errors", 202: "Percent Lifetime Remaining",
    220: "Disk Shift", 222: "Loaded Hours", 223: "Load Retry Count",
    224: "Load Friction", 226: "Load-in Time", 231: "SSD Life Left",
    233: "Media Wearout Indicator", 240: "Head Flying Hours",
    241: "LBAs Written", 242: "LBAs Read",
}

# Attributes whose raw value being non-zero means the drive is in trouble.
CRITICAL_ATTRS = {5, 197, 198, 187}

# Non-zero is a caution rather than a failure: interface errors, timeouts.
WARN_ATTRS = {199, 188}


def _temp_from_attr(attr: Optional[Dict[str, Any]]) -> Optional[float]:
    if not attr:
        return None
    raw = attr.get("raw_low32") or 0
    low = raw & 0xFF
    if 0 < low < 120:
        return float(low)
    whole = attr.get("raw") or 0
    if 0 < whole < 120:
        return float(whole)
    return None


def _ata_health(attrs: Dict[int, Dict[str, Any]]) -> Dict[str, Any]:
    def raw(attr_id: int) -> Optional[int]:
        a = attrs.get(attr_id)
        return a.get("raw") if a else None

    def val(attr_id: int) -> Optional[int]:
        a = attrs.get(attr_id)
        return a.get("value") if a else None

    hours = raw(A_POWER_ON_HOURS)
    # some firmware stores hours in the low 4 bytes only
    if hours and hours > 0xFFFFFFFF:
        hours = attrs[A_POWER_ON_HOURS].get("raw_low32")

    wear_pct = None
    for attr_id in (A_SSD_LIFE_LEFT, A_PERCENT_LIFETIME):
        v = val(attr_id)
        if v is not None and 0 < v <= 100:
            wear_pct = max(0, 100 - v)
            break
    if wear_pct is None:
        v = val(A_WEAR_LEVELING)
        if v is not None and 0 < v <= 100:
            wear_pct = max(0, 100 - v)

    lbas = raw(A_LBAS_WRITTEN)
    bytes_written = None
    if lbas:
        # 512-byte sectors, 48-bit counter
        bytes_written = lbas * 512

    return {
        "reallocated": raw(A_REALLOCATED),
        "pending": raw(A_PENDING),
        "uncorrectable": raw(A_OFFLINE_UNCORRECT),
        "reported_uncorrect": raw(A_REPORTED_UNCORRECT),
        "crc_errors": raw(A_CRC_ERRORS),
        "power_on_hours": hours,
        "wear_pct": wear_pct,
        "temperature_c": _temp_from_attr(attrs.get(A_TEMPERATURE)),
        "bytes_written": bytes_written,
        "attribute_count": len(attrs),
    }


def _nvme_health(log: Dict[str, Any]) -> Dict[str, Any]:
    if not log:
        return {}
    return {
        "wear_pct": log.get("percentage_used"),
        "power_on_hours": log.get("power_on_hours"),
        "temperature_c": log.get("temperature_c"),
        "bytes_written": log.get("bytes_written"),
        "media_errors": log.get("media_errors"),
        "unsafe_shutdowns": log.get("unsafe_shutdowns"),
        "available_spare": log.get("available_spare_pct"),
        "spare_threshold": log.get("spare_threshold_pct"),
        "critical_warning": log.get("critical_warning"),
        "power_cycles": log.get("power_cycles"),
    }


def _scan_drives(ctx: Context) -> List[Dict[str, Any]]:
    facts = ctx.facts
    msft = {}
    for d in util.as_list(facts.get("physical_disks")):
        try:
            msft[int(d.get("device_id") or -1)] = d
        except (TypeError, ValueError):
            pass

    drives: List[Dict[str, Any]] = []
    for index in winapi.list_physical_drives():
        entry: Dict[str, Any] = {"index": index, "smart_ok": False,
                                 "interface": "unknown", "kind": "unknown"}
        handle = winapi.open_drive(index, write=True)
        if not handle:
            handle = winapi.open_drive(index, write=False)
        if not handle:
            drives.append({**entry, "error": "cannot open device (needs admin)"})
            continue
        try:
            desc = winapi.storage_descriptor(handle)
            length = winapi.disk_length(handle)
            bus = util.bus_type_name(desc.get("bus_type"))
            entry["interface"] = bus
            entry["size_bytes"] = length
            entry["size_gb"] = util.gb_decimal(length)
            entry["vendor"] = desc.get("vendor", "")
            entry["product"] = desc.get("product", "")
            entry["serial"] = desc.get("serial", "")
            entry["removable"] = desc.get("removable", False)

            info = msft.get(index) or {}
            # StorageDeviceProperty is refused on some stacks, so fall back to
            # what the storage provider already told us about this disk.
            if entry["interface"] == "unknown" and info.get("bus") is not None:
                entry["interface"] = util.bus_type_name(info.get("bus"))
            entry["model"] = (info.get("friendly") or desc.get("product") or "").strip()
            entry["media"] = util.media_type_name(info.get("media"))
            entry["health_status"] = info.get("health")
            if info.get("serial"):
                entry["serial"] = info.get("serial")

            if bus.lower() == "usb" or entry.get("removable"):
                entry["kind"] = "usb"
                drives.append(entry)
                continue

            # ---- NVMe first (an NVMe drive will not answer ATA SMART)
            nvme_raw = winapi.nvme_smart_log(handle)
            nvme = winapi.parse_nvme_smart(nvme_raw)
            if nvme:
                entry["kind"] = "nvme"
                entry["smart_ok"] = True
                entry["transport"] = "nvme_ioctl"
                entry["smart"] = _nvme_health(nvme)
                entry["smart_raw"] = nvme
                entry["attributes"] = [
                    {"id": "NVMe", "name": label, "value": nvme.get(key),
                     "worst": None, "raw": nvme.get(key),
                     "critical": key in ("media_errors", "critical_warning")}
                    for key, label in (
                        ("percentage_used", "Percentage Used"),
                        ("available_spare_pct", "Available Spare"),
                        ("media_errors", "Media Errors"),
                        ("unsafe_shutdowns", "Unsafe Shutdowns"),
                        ("power_on_hours", "Power-On Hours"),
                        ("power_cycles", "Power Cycles"),
                    )
                ]
            else:
                identify = winapi.parse_identify(winapi.ata_identify(handle))
                if identify.get("model") and not entry.get("model"):
                    entry["model"] = identify["model"]
                if identify.get("serial") and not entry.get("serial"):
                    entry["serial"] = identify["serial"]
                if identify.get("rotation_rate") is not None:
                    entry["media"] = "HDD" if identify["rotation_rate"] else "SSD"

                block, transport = winapi.smart_block(handle)
                attrs = winapi.parse_smart_attributes(block)
                if attrs:
                    entry["kind"] = "ata"
                    entry["smart_ok"] = True
                    entry["transport"] = transport
                    entry["smart"] = _ata_health(attrs)
                    entry["attributes"] = [
                        {
                            "id": f"{attr_id:02X}",
                            "name": SMART_NAMES.get(attr_id, f"Attribute {attr_id}"),
                            "value": data["value"],
                            "worst": data["worst"],
                            "raw": data["raw"],
                            "critical": attr_id in CRITICAL_ATTRS,
                            "warn": attr_id in WARN_ATTRS,
                        }
                        for attr_id, data in sorted(attrs.items())
                    ]
                else:
                    entry["kind"] = "ata" if bus.lower() in ("sata", "ata") else bus.lower()
                    entry["transport"] = "none"
                    entry["smart_error"] = (
                        "no SMART transport answered (SMART IOCTL and "
                        "PREDICT_FAILURE both refused)")
        except Exception as exc:
            entry["error"] = f"{type(exc).__name__}: {exc}"
        finally:
            winapi.close_drive(handle)
        drives.append(entry)
    return drives


def _evaluate(drive: Dict[str, Any], ctx: Context,
              findings: List[R.Finding]) -> float:
    """Returns this drive's health score 0-100."""
    label = drive.get("model") or f"Disk {drive.get('index')}"
    size_gb = drive.get("size_gb") or 0
    is_nvme = (drive.get("interface") or "").lower() == "nvme"
    replace_cost = storage_cost(int(drive.get("size_bytes") or size_gb * 1e9), is_nvme)
    smart = drive.get("smart") or {}
    score = 100.0

    def add(fid: str, sev: str, title: str, detail: str = "",
            evidence: Optional[Dict[str, Any]] = None,
            cost: Optional[int] = None, note: str = "",
            blocking: bool = False) -> None:
        findings.append(R.Finding(
            id=fid, severity=sev, title=title, detail=detail,
            evidence=evidence or {}, cost_pkr=cost, cost_note=note,
            blocking=blocking))

    if not drive.get("smart_ok"):
        add(f"storage.smart_unreadable.{drive.get('index')}", R.MAJOR,
            f"{label}: SMART data is not readable",
            ("The drive answered no SMART request. On a used machine this is either a "
             "drive in RAID/Intel RST mode, a USB bridge, or - the case that matters - "
             "a drive whose SMART table was wiped or disabled to hide wear."),
            {"index": drive.get("index"), "interface": drive.get("interface"),
             "error": drive.get("smart_error") or drive.get("error")},
            cost=replace_cost,
            note="Assume the worst until SMART can be read another way.")
        return 45.0

    hours = smart.get("power_on_hours")
    if isinstance(hours, int) and hours > 0:
        years = hours / 8760.0
        if hours >= 40000:
            add(f"storage.hours.{drive.get('index')}", R.WARN,
                f"{label}: {hours:,} power-on hours ({years:.1f} years)",
                "Heavily used. Not fatal, but every component around it is old too.",
                {"power_on_hours": hours})
            score -= 12
        elif hours >= 20000:
            add(f"storage.hours_info.{drive.get('index')}", R.INFO,
                f"{label}: {hours:,} power-on hours ({years:.1f} years)",
                evidence={"power_on_hours": hours})

    # ---- wiped SMART detector
    bios_date = util.parse_wmi_date((ctx.facts.get("bios") or {}).get("release_date"))
    if isinstance(hours, int) and bios_date:
        machine_years = (datetime.now() - bios_date).days / 365.25
        if machine_years >= 3 and hours < 100:
            add(f"storage.smart_wiped.{drive.get('index')}", R.MAJOR,
                f"{label}: only {hours} power-on hours on a {machine_years:.0f}-year-old machine",
                ("Physically impossible unless the counter was reset. A drive with "
                 "a reset SMART table is a drive with something to hide."),
                {"power_on_hours": hours, "machine_age_years": round(machine_years, 1),
                 "bios_date": util.fmt_date(bios_date)},
                cost=replace_cost,
                note="Treat the drive as unverified.")

    realloc = smart.get("reallocated")
    if realloc:
        if realloc > 50:
            add(f"storage.realloc_critical.{drive.get('index')}", R.CRITICAL,
                f"{label}: {realloc:,} reallocated sectors",
                ("The drive has exhausted its spare sector pool. Failure is a matter "
                 "of time, and the data on it is already partly at risk."),
                {"reallocated_sectors": realloc},
                cost=replace_cost, note="Replace before putting anything on it.",
                blocking=True)
            score -= 85
        elif realloc > 8:
            add(f"storage.realloc_major.{drive.get('index')}", R.MAJOR,
                f"{label}: {realloc:,} reallocated sectors",
                "Sectors have been remapped. The drive is on a downward slope.",
                {"reallocated_sectors": realloc},
                cost=replace_cost, note="Budget for a replacement.")
            score -= 45
        else:
            add(f"storage.realloc_warn.{drive.get('index')}", R.WARN,
                f"{label}: {realloc} reallocated sector(s)",
                "A handful is normal on a drive this age, but it is not zero.",
                {"reallocated_sectors": realloc})
            score -= 15

    pending = smart.get("pending")
    if pending:
        add(f"storage.pending.{drive.get('index')}", R.CRITICAL,
            f"{label}: {pending:,} sectors pending reallocation",
            ("Pending sectors are reads that failed and are waiting to be remapped. "
             "This is the signature of a drive that is failing right now, not a drive "
             "that has aged."),
            {"pending_sectors": pending},
            cost=replace_cost, note="Do not buy this drive as your only storage.",
            blocking=True)
        score -= 100

    uncorrect = smart.get("uncorrectable") or smart.get("media_errors")
    if uncorrect:
        add(f"storage.uncorrectable.{drive.get('index')}", R.MAJOR,
            f"{label}: {uncorrect:,} uncorrectable errors",
            "Data was lost on read. Anything already on the drive is suspect.",
            {"uncorrectable": uncorrect},
            cost=replace_cost, note="Replace.", blocking=True)
        score -= 40

    wear = smart.get("wear_pct")
    if isinstance(wear, (int, float)) and wear >= 0:
        if wear >= 90:
            add(f"storage.wear_critical.{drive.get('index')}", R.CRITICAL,
                f"{label}: {wear:g}% of write endurance consumed",
                ("Almost no spare blocks left. The drive will go read-only or die "
                 "without much warning."),
                {"wear_pct": wear, "bytes_written": smart.get("bytes_written")},
                cost=replace_cost, note="Replace.", blocking=True)
            score -= 80
        elif wear >= 80:
            add(f"storage.wear_high.{drive.get('index')}", R.MAJOR,
                f"{label}: {wear:g}% of write endurance consumed",
                evidence={"wear_pct": wear},
                cost=int(replace_cost * 0.8),
                note="Plan a replacement within the year.")
            score -= 40
        elif wear >= 60:
            add(f"storage.wear_moderate.{drive.get('index')}", R.WARN,
                f"{label}: {wear:g}% of write endurance consumed",
                evidence={"wear_pct": wear})
            score -= 15

    temp = smart.get("temperature_c")
    if isinstance(temp, (int, float)) and temp >= 55:
        add(f"storage.temp.{drive.get('index')}", R.WARN,
            f"{label}: {temp:g} C",
            "Running hot. Check airflow and the drive bay.",
            {"temperature_c": temp})
        score -= 8

    crc = smart.get("crc_errors")
    if isinstance(crc, int) and crc >= 100:
        add(f"storage.crc.{drive.get('index')}", R.WARN,
            f"{label}: {crc:,} interface CRC errors",
            ("The drive and the controller disagree on the wire. Usually a bad "
             "SATA cable or a marginal connector, sometimes the drive's own "
             "controller. Cheap to fix, worth naming."),
            {"crc_errors": crc},
            cost=1500,
            note="SATA cable / reseat.")
        score -= 10

    if smart.get("wear_pct") is None and (drive.get("media") or "").upper() == "SSD":
        add(f"storage.no_wear.{drive.get('index')}", R.INFO,
            f"{label}: controller does not report endurance",
            ("This SSD exposes no life-left attribute, so wear cannot be measured "
             "from SMART. Judge it on power-on hours and host writes instead."),
            {"power_on_hours": smart.get("power_on_hours"),
             "bytes_written": smart.get("bytes_written")})

    if smart.get("critical_warning"):
        add(f"storage.nvme_warning.{drive.get('index')}", R.CRITICAL,
            f"{label}: NVMe critical warning flag set (0x{smart['critical_warning']:02X})",
            "The controller is reporting a reliability failure.",
            {"critical_warning": smart["critical_warning"]},
            cost=replace_cost, note="Replace.", blocking=True)
        score -= 70

    spare = smart.get("available_spare")
    threshold = smart.get("spare_threshold")
    if isinstance(spare, int) and isinstance(threshold, int) and spare < threshold:
        add(f"storage.spare.{drive.get('index')}", R.MAJOR,
            f"{label}: available spare {spare}% below threshold {threshold}%",
            "The controller has burned through its reserve blocks.",
            {"available_spare_pct": spare, "spare_threshold_pct": threshold},
            cost=replace_cost, note="Replace.")
        score -= 35

    return max(0.0, score)


def run(ctx: Context) -> R.CheckResult:
    check = R.CheckResult(key=KEY, label=LABEL)
    findings: List[R.Finding] = []
    drives = _scan_drives(ctx)
    check.data = {"drives": drives, "admin": winapi.is_admin()}

    usable = [d for d in drives if d.get("kind") != "usb"]
    if not usable:
        check.status = R.STATUS_UNAVAILABLE
        check.summary = "No internal drive could be opened"
        if not winapi.is_admin():
            check.error = "Requires administrator rights"
            findings.append(R.Finding(
                id="storage.no_admin", severity=R.MAJOR,
                title="Storage health needs administrator rights",
                detail=("Opening a physical drive requires elevation. Run the inspector "
                        "as administrator or SMART cannot be read at all."),
                evidence={"admin": False}))
        check.findings = findings
        check.score = 0.0
        return check

    scores = []
    for drive in usable:
        scores.append(_evaluate(drive, ctx, findings))

    check.findings = findings
    check.score = min(scores) if scores else 0.0
    has_critical = any(f.severity == R.CRITICAL for f in findings)
    has_warn = any(f.severity in (R.WARN, R.MAJOR) for f in findings)
    check.status = (R.STATUS_FAIL if has_critical
                    else R.STATUS_WARN if has_warn else R.STATUS_OK)

    # One clause per drive, with the media type spelled out: an SSD and an HDD
    # in the same sentence is how the two got confused in the UI.
    parts = []
    for d in usable:
        label = d.get("model") or f"Disk {d.get('index')}"
        kind = (d.get("interface") or "").upper()
        media = str(d.get("media") or "").upper()
        bits = [f"{kind} {media}".strip(), f"{d.get('size_gb') or '?'} GB"]
        smart = d.get("smart") or {}
        hours = smart.get("power_on_hours")
        if hours:
            bits.append(f"{hours:,} h")
        if smart.get("reallocated"):
            bits.append(f"{smart['reallocated']:,} reallocated")
        if smart.get("pending"):
            bits.append(f"{smart['pending']:,} pending")
        if smart.get("crc_errors"):
            bits.append(f"{smart['crc_errors']:,} CRC")
        if not d.get("smart_ok"):
            bits.append("SMART unreadable")
        parts.append(f"{label} ({', '.join(bits)})")
    check.summary = "; ".join(parts) if parts else "No drives"
    return check
