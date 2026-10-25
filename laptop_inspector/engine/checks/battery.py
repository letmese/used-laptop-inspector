"""Battery - the single most lied-about part in the used market.

Three sources, in order of trust:
  1. `powercfg /batteryreport /xml` - design capacity, full-charge capacity and
     cycle count in one place, straight from the ACPI battery driver.
  2. `root\\wmi` BatteryStaticData / BatteryFullChargedCapacity / BatteryCycleCount.
  3. Win32_Battery - last resort, often empty.

A battery that enumerates but reports zero capacity is a failed cell, not
missing data. That distinction matters: one is a 15,000 PKR deduction, the other
is "the driver is not loaded".
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from .. import result as R
from .. import util
from ..context import Context, cost_of

KEY = "battery"
LABEL = "Battery"


def _decode_pack_date(value: Any) -> Optional[str]:
    """BatteryStaticData.ManufactureDate is a packed 16-bit date."""
    try:
        raw = int(value)
    except (TypeError, ValueError):
        return None
    if raw <= 0:
        return None
    year = 1980 + ((raw >> 9) & 0x7F)
    month = (raw >> 5) & 0x0F
    day = raw & 0x1F
    if not (1 <= month <= 12 and 1 <= day <= 31 and 1990 <= year <= 2100):
        return None
    return f"{year:04d}-{month:02d}-{day:02d}"


def _first(items: List[Dict[str, Any]], *keys: str) -> Any:
    for item in items:
        for key in keys:
            val = item.get(key)
            if val not in (None, "", 0):
                return val
    return None


def _gather(ctx: Context) -> Dict[str, Any]:
    f = ctx.facts
    xml = ctx.battery_xml or {}
    xml_bats = [b for b in (xml.get("batteries") or []) if isinstance(b, dict)]
    static = util.as_list(f.get("battery_static"))
    full = util.as_list(f.get("battery_full"))
    cycles = util.as_list(f.get("battery_cycles"))
    wb = util.as_list(f.get("batteries"))
    status = util.as_list(f.get("battery_status"))

    design = _first(xml_bats, "design_capacity") or _first(static, "designed_capacity")
    full_cap = (_first(xml_bats, "full_charge_capacity")
                or _first(full, "full")
                or _first(static, "full_capacity"))
    cycle_count = _first(xml_bats, "cycle_count") or _first(cycles, "cycles")

    try:
        design = int(design) if design else None
    except (TypeError, ValueError):
        design = None
    try:
        full_cap = int(full_cap) if full_cap else None
    except (TypeError, ValueError):
        full_cap = None
    try:
        cycle_count = int(cycle_count) if cycle_count is not None else None
    except (TypeError, ValueError):
        cycle_count = None

    manufacturer = (_first(xml_bats, "manufacturer")
                    or _first(static, "manufacturer") or "")
    device_name = (_first(static, "device_name")
                   or _first(wb, "name") or "")
    serial = _first(xml_bats, "serial") or _first(static, "serial") or ""
    chemistry = _first(xml_bats, "chemistry") or _first(static, "chemistry") or ""
    mfg = _decode_pack_date(_first(static, "manufacture_date"))

    return {
        "present": bool(wb or static or xml_bats),
        "design_mwh": design,
        "full_mwh": full_cap,
        "cycle_count": cycle_count,
        "manufacturer": str(manufacturer).strip(),
        "device_name": str(device_name).strip(),
        "serial": str(serial).strip(),
        "chemistry": str(chemistry).strip(),
        "manufacture_date": mfg,
        "battery_count": len(wb) or len(xml_bats),
        "sources": {
            "powercfg": bool(xml_bats),
            "root_wmi": bool(static or full),
            "win32_battery": bool(wb),
        },
        "power_online": (_first(status, "power_online")
                         if status else None),
        "remaining_mwh": _first(status, "remaining") if status else None,
    }


def run(ctx: Context) -> R.CheckResult:
    check = R.CheckResult(key=KEY, label=LABEL)
    data = _gather(ctx)
    check.data = data
    findings: List[R.Finding] = []
    battery_cost = cost_of("battery_replacement", 15000)
    score = 100.0

    if not data["present"]:
        check.status = R.STATUS_UNAVAILABLE
        check.score = 0.0
        check.summary = "No battery enumerated"
        check.findings = [R.Finding(
            id="battery.absent", severity=R.CRITICAL,
            title="No battery detected",
            detail=("Windows sees no battery at all. Either it has been removed, the "
                    "pack is dead to the point of not enumerating, or the ACPI "
                    "battery device is broken."),
            evidence=data["sources"],
            cost_pkr=battery_cost,
            cost_note="Replacement pack, fitted.")]
        check.status = R.STATUS_FAIL
        return check

    design = data["design_mwh"]
    full = data["full_mwh"]

    # ---- enumerates but reports nothing: dead cell or missing driver
    if not design and not full:
        findings.append(R.Finding(
            id="battery.no_capacity_data", severity=R.MAJOR,
            title="Battery enumerated but reports no capacity",
            detail=("The pack identifies itself but design and full-charge capacity are "
                    "both absent. On most machines this means the cells are dead, or "
                    "the OEM power-management driver is not installed."),
            evidence={"design_mwh": design, "full_mwh": full,
                      "device": data["device_name"],
                      "sources": data["sources"]},
            cost_pkr=battery_cost,
            cost_note="Assume replacement until proven otherwise."))
        score = 20.0
        check.status = R.STATUS_FAIL
        check.summary = "Capacity unreadable - treat as dead"
        check.findings = findings
        check.score = score
        return check

    if full == 0:
        findings.append(R.Finding(
            id="battery.zero_capacity", severity=R.CRITICAL,
            title="Battery reports 0 mWh full-charge capacity",
            detail=("The pack is present and talks to Windows, but stores nothing. "
                    "This machine runs on AC only - unplug it and it dies instantly."),
            evidence={"design_mwh": design, "full_mwh": 0,
                      "device": data["device_name"]},
            cost_pkr=battery_cost,
            cost_note="Replacement pack, fitted."))
        check.findings = findings
        check.score = 0.0
        check.status = R.STATUS_FAIL
        check.summary = "Dead cell - 0 mWh"
        return check

    # ---- wear
    wear = None
    if design and full:
        wear = max(0.0, min(1.0, 1.0 - (full / float(design))))
    health_pct = round((1.0 - wear) * 100, 1) if wear is not None else None

    if wear is not None:
        if wear >= 0.50:
            findings.append(R.Finding(
                id="battery.wear_critical", severity=R.CRITICAL,
                title=f"Battery at {health_pct:g}% of design capacity",
                detail=(f"Design {design} mWh, currently holds {full} mWh. Below 50% the "
                        "pack will not survive a power cut and often shuts down early."),
                evidence={"design_mwh": design, "full_mwh": full,
                          "wear_pct": round(wear * 100, 1)},
                cost_pkr=battery_cost,
                cost_note="Replacement pack, fitted."))
        elif wear >= 0.30:
            findings.append(R.Finding(
                id="battery.wear_high", severity=R.MAJOR,
                title=f"Battery at {health_pct:g}% of design capacity",
                detail=(f"Design {design} mWh, holds {full} mWh. Expect roughly "
                        f"{max(1, round(health_pct / 100 * 4))} hours of real use."),
                evidence={"design_mwh": design, "full_mwh": full,
                          "wear_pct": round(wear * 100, 1)},
                cost_pkr=int(battery_cost * 0.8),
                cost_note="Negotiate the pack; it will need replacing within a year."))
        elif wear >= 0.20:
            findings.append(R.Finding(
                id="battery.wear_moderate", severity=R.WARN,
                title=f"Battery at {health_pct:g}% of design capacity",
                detail=f"Design {design} mWh, holds {full} mWh. Normal for the age.",
                evidence={"design_mwh": design, "full_mwh": full,
                          "wear_pct": round(wear * 100, 1)},
                cost_pkr=int(battery_cost * 0.5),
                cost_note="Wear allowance."))
        elif wear >= 0.10:
            findings.append(R.Finding(
                id="battery.wear_low", severity=R.INFO,
                title=f"Battery at {health_pct:g}% of design capacity",
                evidence={"design_mwh": design, "full_mwh": full,
                          "wear_pct": round(wear * 100, 1)}))

        score = 100.0 - (wear * 100 * 1.6)
    else:
        findings.append(R.Finding(
            id="battery.partial_data", severity=R.WARN,
            title="Battery wear cannot be computed",
            detail="Only one of design capacity / full-charge capacity was readable.",
            evidence={"design_mwh": design, "full_mwh": full}))
        score = 60.0

    # ---- cycles
    cycles = data["cycle_count"]
    if cycles:
        if cycles >= 800:
            findings.append(R.Finding(
                id="battery.cycles_critical", severity=R.MAJOR,
                title=f"{cycles} charge cycles",
                detail="Well past the 300-500 cycles a lithium pack is rated for.",
                evidence={"cycle_count": cycles},
                cost_pkr=int(battery_cost * 0.7),
                cost_note="Pack is near end of life."))
            score -= 20
        elif cycles >= 400:
            findings.append(R.Finding(
                id="battery.cycles_high", severity=R.WARN,
                title=f"{cycles} charge cycles",
                evidence={"cycle_count": cycles}))
            score -= 8

    # ---- third-party pack
    maker = data["manufacturer"].lower()
    if maker in ("", "oem", "generic", "unknown", "not available", "none"):
        findings.append(R.Finding(
            id="battery.third_party", severity=R.WARN,
            title="Battery is probably not an OEM pack",
            detail=("No manufacturer name reported. Aftermarket packs routinely "
                    "misreport capacity, so the wear figure above may be optimistic."),
            evidence={"manufacturer": data["manufacturer"],
                      "device": data["device_name"]}))

    # ---- power-loss history: the strongest corroboration of a dead pack
    shutdowns = int((ctx.events or {}).get("unexpected_shutdowns") or 0)
    if shutdowns >= 3:
        findings.append(R.Finding(
            id="battery.unexpected_shutdowns", severity=R.WARN,
            title=f"{shutdowns} unexpected shutdown(s) in the last 180 days",
            detail=("Kernel-power events with no clean shutdown. On a laptop this "
                    "usually means it loses power the moment the charger is pulled, "
                    "which is what a pack with no capacity left looks like."),
            evidence={"unexpected_shutdowns": shutdowns}))

    # ---- replaced pack detection
    bios_date = util.parse_wmi_date((ctx.facts.get("bios") or {}).get("release_date"))
    mfg_date = util.parse_wmi_date(data["manufacture_date"])
    if bios_date and mfg_date and mfg_date.year > bios_date.year + 1:
        findings.append(R.Finding(
            id="battery.replaced", severity=R.INFO,
            title=f"Battery was manufactured in {mfg_date.year}, after the laptop",
            detail="The pack has been replaced at least once. Judge it on the wear "
                   "figure, not on the machine's age.",
            evidence={"battery_mfg": data["manufacture_date"],
                      "bios_date": util.fmt_date(bios_date)}))

    # ---- design capacity sanity (a 2011 workstation pack is ~90 Wh)
    if design and design < 20000:
        findings.append(R.Finding(
            id="battery.small_design", severity=R.WARN,
            title=f"Design capacity only {design} mWh",
            detail="Unusually small for a laptop of this class - often a cheap "
                   "aftermarket pack with inflated labelling.",
            evidence={"design_mwh": design}))

    score = max(0.0, min(100.0, score))
    check.findings = findings
    check.score = score
    check.status = (R.STATUS_FAIL if any(f.severity == R.CRITICAL for f in findings)
                    else R.STATUS_WARN if any(f.severity in (R.WARN, R.MAJOR)
                                              for f in findings)
                    else R.STATUS_OK)
    if health_pct is not None:
        check.summary = (f"{health_pct:g}% health "
                         f"({full}/{design} mWh"
                         + (f", {cycles} cycles" if cycles else "") + ")")
    else:
        check.summary = "Partial battery data"
    return check
