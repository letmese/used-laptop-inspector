"""Specs verification - what the machine actually is, versus what was claimed.

The seller's claim is the thing being tested. If nothing was claimed, the check
still runs: it validates internal consistency (serial present, BIOS date sane,
OEM key present for the era, RAM actually dual-channel, storage really NVMe).
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from .. import result as R
from .. import util, winapi
from ..context import Context

KEY = "specs"
LABEL = "Specs & authenticity"


def _collect(ctx: Context) -> Dict[str, Any]:
    f = ctx.facts
    system = f.get("system") or {}
    cpu = f.get("cpu") or {}
    bios = f.get("bios") or {}
    board = f.get("board") or {}
    product = f.get("product") or {}
    os_info = f.get("os") or {}

    modules = util.as_list(f.get("memory_modules"))
    mem_slots = (f.get("memory_array") or {}).get("slots")

    installed = 0
    for m in modules:
        try:
            installed += int(m.get("capacity") or 0)
        except (TypeError, ValueError):
            pass

    disks = []
    for d in util.as_list(f.get("physical_disks")):
        disks.append({
            "model": (d.get("friendly") or "").strip(),
            "size": d.get("size"),
            "size_gb": util.gb_decimal(d.get("size")),
            "media": util.media_type_name(d.get("media")),
            "bus": util.bus_type_name(d.get("bus")),
            "serial": (d.get("serial") or "").strip(),
            "health": d.get("health"),
        })
    if not disks:
        for d in util.as_list(f.get("disk_drives")):
            disks.append({
                "model": (d.get("model") or "").strip(),
                "size": d.get("size"),
                "size_gb": util.gb_decimal(d.get("size")),
                "media": (d.get("media") or "").strip(),
                "bus": (d.get("interface") or "").strip(),
                "serial": (d.get("serial") or "").strip(),
                "health": None,
            })

    gpus = []
    width = height = refresh = 0
    for g in util.as_list(f.get("gpus")):
        name = util.short_gpu(g.get("name") or "")
        gpus.append({
            "name": name,
            "kind": util.classify_gpu(name),
            "vram": g.get("vram"),
            "driver": g.get("driver_ver"),
            "driver_date": util.fmt_date(g.get("driver_date")),
            "error_code": g.get("error_code"),
            "status": g.get("status"),
        })
        for key, target in (("width", "w"), ("height", "h"), ("refresh", "r")):
            try:
                val = int(g.get(key) or 0)
            except (TypeError, ValueError):
                val = 0
            if target == "w":
                width = max(width, val)
            elif target == "h":
                height = max(height, val)
            else:
                refresh = max(refresh, val)

    msdm_raw = winapi.read_acpi_table(b"MSDM")
    oem_key = winapi.parse_msdm_key(msdm_raw)
    slic = winapi.read_acpi_table(b"SLIC") is not None

    return {
        "manufacturer": (system.get("manufacturer") or "").strip(),
        "model": (system.get("model") or "").strip(),
        "family": (system.get("system_family") or "").strip(),
        "product_version": (product.get("version") or "").strip(),
        "cpu": {
            "name": (cpu.get("name") or "").strip(),
            "cores": cpu.get("cores"),
            "threads": cpu.get("threads"),
            "max_mhz": cpu.get("max_mhz"),
            "l3_kb": cpu.get("l3"),
            "description": cpu.get("description"),
        },
        "ram": {
            "installed_gb": round(installed / (1024 ** 3), 1) if installed else None,
            "usable_gb": util.gb(system.get("total_ram")),
            "modules": [
                {
                    "bank": m.get("bank"),
                    "gb": round(int(m.get("capacity") or 0) / (1024 ** 3), 1),
                    "speed": m.get("speed"),
                    "configured": m.get("configured"),
                    "manufacturer": (m.get("manufacturer") or "").strip(),
                    "part": (m.get("part") or "").strip(),
                    "type": util.memory_type_name(m.get("memory_type")),
                }
                for m in modules
            ],
            "slots": mem_slots,
            "used": len(modules),
        },
        "storage": disks,
        "gpus": gpus,
        "screen": {
            "width": width or None,
            "height": height or None,
            "refresh_hz": refresh or None,
            "resolution": f"{width}x{height}" if width and height else "",
        },
        "bios": {
            "version": (bios.get("version") or "").strip(),
            "date": util.fmt_date(bios.get("release_date")),
            "manufacturer": (bios.get("manufacturer") or "").strip(),
        },
        "serial": (bios.get("serial") or "").strip(),
        "board_serial": (board.get("serial") or "").strip(),
        "uuid": (product.get("uuid") or "").strip(),
        "os": {
            "caption": (os_info.get("caption") or "").strip(),
            "build": os_info.get("build"),
            "arch": os_info.get("arch"),
            "install_date": util.fmt_date(os_info.get("install_date")),
            "serial": os_info.get("serial"),
        },
        "oem_key": oem_key,
        "has_slic": slic,
    }


# --------------------------------------------------------------------------
# claim matching
# --------------------------------------------------------------------------
def _num(text: str) -> Optional[float]:
    m = re.search(r"(\d+(?:\.\d+)?)", str(text or ""))
    return float(m.group(1)) if m else None


def _check_claims(claims: Dict[str, Any], data: Dict[str, Any]) -> List[R.Finding]:
    findings: List[R.Finding] = []
    cpu_name = data["cpu"]["name"].lower()
    gpu_names = " ".join(g["name"] for g in data["gpus"]).lower()
    total_gb = data["ram"]["installed_gb"] or data["ram"]["usable_gb"] or 0
    max_disk = max([d["size_gb"] or 0 for d in data["storage"]] or [0])
    buses = {d["bus"].lower() for d in data["storage"]}
    medias = {d["media"].lower() for d in data["storage"]}

    def add(cid: str, sev: str, title: str, detail: str, evidence: Dict[str, Any],
            blocking: bool = False):
        findings.append(R.Finding(
            id=cid, severity=sev, title=title, detail=detail, evidence=evidence,
            blocking=blocking))

    claim_cpu = str(claims.get("cpu") or "").strip()
    if claim_cpu:
        token = claim_cpu.lower().replace("core", "").strip()
        ok = token in cpu_name or cpu_name in token
        if not ok:
            add("claim.cpu", R.CRITICAL,
                f"CPU claim is false: sold as {claim_cpu}",
                "The CPU reported by firmware does not contain the claimed model.",
                {"claimed": claim_cpu, "actual": data["cpu"]["name"]},
                blocking=True)

    claim_ram = claims.get("ram_gb")
    if claim_ram:
        want = _num(claim_ram)
        if want and total_gb and total_gb + 0.6 < want:
            add("claim.ram", R.CRITICAL,
                f"RAM claim is false: sold as {want:g} GB",
                f"Only {total_gb:g} GB of physical memory is installed.",
                {"claimed_gb": want, "actual_gb": total_gb,
                 "modules": len(data["ram"]["modules"])},
                blocking=True)

    claim_disk = claims.get("storage_gb")
    if claim_disk:
        want = _num(claim_disk)
        if want and max_disk and max_disk < want * 0.9:
            add("claim.storage", R.MAJOR,
                f"Storage claim is short: sold as {want:g} GB",
                f"Largest drive is {max_disk:g} GB.",
                {"claimed_gb": want, "actual_gb": max_disk})

    claim_type = str(claims.get("storage_type") or "").strip().lower()
    if claim_type:
        if "nvme" in claim_type and "nvme" not in buses:
            add("claim.storage_type", R.CRITICAL,
                "Sold as NVMe, no NVMe drive present",
                "The drive is not on an NVMe bus. A SATA SSD or HDD is fitted.",
                {"claimed": claim_type, "buses": sorted(buses), "media": sorted(medias)},
                blocking=True)
        elif "ssd" in claim_type and "ssd" not in medias and "hdd" in medias:
            add("claim.storage_type", R.CRITICAL,
                "Sold as SSD, a mechanical drive is fitted",
                "Windows reports the boot drive media type as HDD.",
                {"claimed": claim_type, "media": sorted(medias)},
                blocking=True)
        elif "hdd" in claim_type and "hdd" not in medias:
            add("claim.storage_type", R.INFO,
                "Sold as HDD, an SSD is fitted",
                "Not a problem - the machine is better than advertised.",
                {"claimed": claim_type, "media": sorted(medias)})

    claim_gpu = str(claims.get("gpu") or "").strip()
    if claim_gpu:
        token = claim_gpu.lower()
        if token not in gpu_names:
            add("claim.gpu", R.MAJOR,
                f"GPU claim not matched: {claim_gpu}",
                "No enumerated adapter matches the claimed GPU.",
                {"claimed": claim_gpu, "actual": [g["name"] for g in data["gpus"]]})

    claim_screen = str(claims.get("screen") or "").strip().lower()
    if claim_screen:
        actual = (data["screen"]["resolution"] or "").lower()
        want = re.sub(r"\s", "", claim_screen)
        if actual and want and want != actual:
            add("claim.screen", R.MAJOR,
                f"Screen claim is false: sold as {claim_screen}",
                f"Reported resolution is {actual}.",
                {"claimed": claim_screen, "actual": actual})

    return findings


def run(ctx: Context) -> R.CheckResult:
    check = R.CheckResult(key=KEY, label=LABEL)
    data = _collect(ctx)
    check.data = data
    score = 100.0

    findings = _check_claims(ctx.options.claims or {}, data)

    # ---- serial sanity: a missing serial usually means a replaced board
    if util.is_placeholder(data["serial"]):
        findings.append(R.Finding(
            id="specs.serial_missing", severity=R.MAJOR,
            title="System serial number is blank or a placeholder",
            detail=("OEM machines carry a serial in BIOS. A blank or 'Default string' "
                    "serial is the usual signature of a replaced or reflashed board."),
            evidence={"serial": data["serial"], "board_serial": data["board_serial"]},
            cost_pkr=0,
            cost_note="Not a repair cost - a reason to demand provenance."))
    elif util.is_placeholder(data["board_serial"]):
        findings.append(R.Finding(
            id="specs.board_serial_missing", severity=R.WARN,
            title="Motherboard serial is a placeholder",
            evidence={"board_serial": data["board_serial"]}))

    # ---- OEM key
    bios_year = 0
    if data["bios"]["date"]:
        try:
            bios_year = int(data["bios"]["date"][:4])
        except ValueError:
            bios_year = 0
    win8_era = bios_year >= 2012
    if not data["oem_key"]:
        if win8_era and not data["has_slic"]:
            findings.append(R.Finding(
                id="specs.no_oem_key", severity=R.WARN,
                title="No OEM Windows key in firmware (MSDM absent)",
                detail=("Windows 8 and later machines embed the key in the ACPI MSDM "
                        "table. Its absence on a 2012+ machine means either a "
                        "non-OEM install, a board swap, or a reflashed BIOS."),
                evidence={"bios_date": data["bios"]["date"],
                          "msdm_present": False, "slic_present": data["has_slic"]},
                cost_pkr=12000,
                cost_note="Cost of a genuine Windows licence if activation fails."))
        else:
            findings.append(R.Finding(
                id="specs.no_oem_key_legacy", severity=R.INFO,
                title="No MSDM key - expected on a pre-Windows 8 machine",
                detail=("This machine predates MSDM. Windows 7-era OEM activation "
                        "used the SLIC table instead."),
                evidence={"bios_date": data["bios"]["date"],
                          "slic_present": data["has_slic"]}))

    # ---- RAM consistency
    mods = data["ram"]["modules"]
    if len(mods) >= 2:
        speeds = {m["speed"] for m in mods if m["speed"]}
        if len(speeds) > 1:
            findings.append(R.Finding(
                id="specs.mixed_ram_speed", severity=R.WARN,
                title="Mixed RAM speeds",
                detail="Modules run at the speed of the slowest stick.",
                evidence={"speeds": sorted(speeds)}))
        makers = {m["manufacturer"].lower() for m in mods if m["manufacturer"]}
        if len(makers) > 1:
            findings.append(R.Finding(
                id="specs.mixed_ram_brand", severity=R.INFO,
                title="Mixed RAM brands",
                detail="Normal in the used market, but check for stability.",
                evidence={"brands": sorted(makers)}))
    if data["ram"]["slots"] and data["ram"]["used"] == 1 and data["ram"]["slots"] >= 2:
        findings.append(R.Finding(
            id="specs.single_channel", severity=R.WARN,
            title="Only one RAM slot populated",
            detail=("Single-channel memory costs 10-25% in memory-bound work. "
                    "Adding a matched stick is cheap and doubles bandwidth."),
            evidence={"slots": data["ram"]["slots"], "used": data["ram"]["used"]},
            cost_pkr=0,
            cost_note="Upgrade, not a defect - use it to argue the price down."))

    # ---- storage interface sanity vs era
    for d in data["storage"]:
        if d["media"] == "HDD" and (d["size_gb"] or 0) > 0:
            findings.append(R.Finding(
                id=f"specs.hdd_{d['serial'][:8]}", severity=R.WARN,
                title=f"Mechanical drive fitted: {d['model']}",
                detail=("An HDD in a laptop this age is either original and worn, "
                        "or a cheap replacement. Budget for an SSD."),
                evidence={"model": d["model"], "size_gb": d["size_gb"]},
                cost_pkr=8000,
                cost_note="512 GB SATA SSD + cloning.",
                upgrade=True))

    # ---- screen
    if not data["screen"]["resolution"]:
        findings.append(R.Finding(
            id="specs.no_screen_info", severity=R.INFO,
            title="Display resolution unavailable",
            detail="The graphics driver did not report a mode. Check the panel by eye.",
            evidence={}))

    # ---- windows install recency
    if data["os"]["install_date"]:
        from datetime import datetime
        try:
            installed = datetime.strptime(data["os"]["install_date"], "%Y-%m-%d")
            age_days = (datetime.now() - installed).days
            if age_days <= 14:
                findings.append(R.Finding(
                    id="specs.fresh_windows", severity=R.INFO,
                    title=f"Windows was installed {age_days} day(s) ago",
                    detail=("A fresh install is normal for resale, but it also wipes "
                            "the event log and SMART history. Treat this machine's "
                            "clean bill of health with suspicion."),
                    evidence={"install_date": data["os"]["install_date"],
                              "age_days": age_days}))
        except ValueError:
            pass

    # ---- scoring
    for f in findings:
        if f.severity == R.CRITICAL:
            score -= 45
        elif f.severity == R.MAJOR:
            score -= 18
        elif f.severity == R.WARN:
            score -= 7
    score = max(0.0, min(100.0, score))

    check.findings = findings
    check.score = score
    check.status = (R.STATUS_FAIL if any(f.severity == R.CRITICAL for f in findings)
                    else R.STATUS_WARN if findings else R.STATUS_OK)
    cpu = data["cpu"]["name"] or "unknown CPU"
    ram = data["ram"]["installed_gb"] or data["ram"]["usable_gb"] or "?"
    check.summary = f"{cpu} / {ram} GB / {len(data['storage'])} drive(s)"
    return check
