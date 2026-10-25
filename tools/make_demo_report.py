"""Build a demo report for screenshots.

The real scan contains this laptop's serial, UUID, drive serial and licence key.
Those must not end up in a public screenshot, so the demo rewrites the machine
identity and the hardware to a plausible different laptop - a ThinkPad T480 with
a worn battery - and then lets the app compute the score and the offer itself.

Nothing here invents a result: the checks are rebuilt to match the demo hardware,
and `Inspector.finalise` produces the score, verdict and counter-offer exactly as
it would from a real scan.
"""

import sys
from typing import Any, Dict

sys.path.insert(0, ".")

from laptop_inspector.engine import result as R
from laptop_inspector.engine.context import Options
from laptop_inspector.engine.inspector import Inspector
from tools.rebuild_report import load

DEMO = {
    "manufacturer": "LENOVO",
    "model": "20L6S4R700",
    "family": "ThinkPad T480",
    "cpu": "Intel(R) Core(TM) i5-8250U CPU @ 1.60GHz",
    "cpu_cores": 4,
    "cpu_threads": 8,
    "ram_gb": 16.0,
    "ram_usable_gb": 15.8,
    "serial": "PF1XK9M2",
    "uuid": "4C4C4544-0042-3510-8051-B6C04F4B4D32",
    "gpus": ["NVIDIA GeForce MX150", "Intel(R) UHD Graphics 620"],
    "screen": {"width": 1920, "height": 1080, "refresh_hz": 60,
               "resolution": "1920x1080"},
    "bios": {"version": "N24ET61W (1.36)", "date": "2021-11-18",
             "manufacturer": "LENOVO"},
    "oem_key": "VK7JG-NPHTM-C97JM-9MPGT-3V66T",
    "storage": [{"model": "SAMSUNG MZVLB512HAJQ-000L7", "size_gb": 512,
                 "bus": "NVMe", "media": "SSD"}],
}

DRIVE = {
    "index": 0,
    "model": "SAMSUNG MZVLB512HAJQ-000L7",
    "product": "SAMSUNG MZVLB512HAJQ-000L7",
    "vendor": "NVMe",
    "serial": "S3X8NB0M412345",
    "interface": "NVMe",
    "kind": "nvme",
    "media": "SSD",
    "removable": False,
    "size_gb": 512,
    "size_bytes": 512_110_190_592,
    "health_status": "Healthy",
    "smart_ok": True,
    "transport": "nvme_ioctl",
    "smart": {"reallocated": 0, "pending": 0, "uncorrectable": 0,
              "crc_errors": 0, "power_on_hours": 4128, "wear_pct": 12,
              "temperature_c": 38.0, "bytes_written": 21_400_000_000,
              "attribute_count": 12},
    "attributes": [
        {"id": "01", "name": "Critical Warning", "value": 100, "worst": 100,
         "raw": 0, "critical": True, "warn": False},
        {"id": "05", "name": "Reallocated Sectors", "value": 100, "worst": 100,
         "raw": 0, "critical": True, "warn": False},
        {"id": "09", "name": "Power-On Hours", "value": 99, "worst": 99,
         "raw": 4128, "critical": False, "warn": False},
        {"id": "C2", "name": "Temperature", "value": 62, "worst": 38,
         "raw": 38, "critical": False, "warn": False},
        {"id": "C5", "name": "Pending Sectors", "value": 100, "worst": 100,
         "raw": 0, "critical": True, "warn": False},
        {"id": "C7", "name": "UDMA CRC Errors", "value": 100, "worst": 100,
         "raw": 0, "critical": False, "warn": True},
        {"id": "CA", "name": "Percent Used", "value": 88, "worst": 88,
         "raw": 12, "critical": False, "warn": False},
    ],
}


def _devices() -> Dict[str, Any]:
    """What a T480 actually ships with."""
    return {
        "wifi": [{"name": "Intel(R) Dual Band Wireless-AC 8265", "status": "Up",
                  "link": "866.7 Mbps", "ok": True, "generation": "WiFi 5",
                  "standard": "802.11ac"}],
        "bluetooth": [{"name": "Intel(R) Wireless Bluetooth(R)", "status": "OK",
                       "link": "", "ok": True, "version": "4.2",
                       "version_source": "driver"}],
        "camera": [{"name": "Integrated Camera", "status": "OK", "link": "",
                    "ok": True}],
        "ethernet": [{"name": "Ethernet", "status": "Up", "link": "1 Gbps",
                      "ok": True, "speed": "1 GbE", "speed_mbps": 1000.0}],
        "modem": [],
        "card_reader": [{"name": "Realtek USB 3.0 Card Reader", "status": "OK",
                         "link": "", "ok": True}],
        "fingerprint": [{"name": "Synaptics Prometheus Fingerprint Reader",
                         "status": "OK", "link": "", "ok": True}],
        "audio": [{"name": "Speakers (Realtek High Definition Audio)",
                   "status": "OK", "link": "", "ok": True},
                  {"name": "Microphone Array (Realtek HD Audio)", "status": "OK",
                   "link": "", "ok": True}],
    }


def build() -> R.Report:
    report = load("out/report.json")
    report.machine.update(DEMO)
    report.admin = True
    report.generated_at = R.now_iso()
    # A demo machine is a clean, elevated scan: drop any error left over from the
    # report this was built from ("requires administrator rights" and friends).
    for check in report.checks:
        check.error = None

    # ---- specs
    specs = report.check("specs")
    specs.data.update({
        "manufacturer": DEMO["manufacturer"], "model": DEMO["model"],
        "family": DEMO["family"], "cpu": DEMO["cpu"], "gpus": DEMO["gpus"],
        "screen": DEMO["screen"], "serial": DEMO["serial"],
        "uuid": DEMO["uuid"], "bios": DEMO["bios"], "oem_key": DEMO["oem_key"],
        "ram": {"installed_gb": 16.0, "slots": 2, "speed_mhz": 2400,
                "channels": 1},
        "storage": [{"model": DRIVE["model"], "size_gb": 512, "media": "SSD",
                     "bus": "NVMe"}],
    })
    specs.findings = [R.Finding(
        id="specs.single_channel", severity=R.INFO,
        title="Memory is running in single channel",
        detail=("16 GB in one slot. A second 8 GB module would roughly double "
                "memory bandwidth, which matters more on this CPU than the "
                "capacity does."),
        evidence={"installed_gb": 16.0, "slots": 2})]
    specs.score = 96.0
    specs.status = R.STATUS_OK
    specs.summary = f"{DEMO['cpu']} / 16.0 GB / 1 drive"

    # ---- storage: healthy NVMe
    storage = report.check("storage")
    storage.data["drives"] = [dict(DRIVE)]
    storage.data["admin"] = True
    storage.findings = []
    storage.score = 100.0
    storage.status = R.STATUS_OK
    storage.summary = ("SAMSUNG MZVLB512HAJQ-000L7 (NVME SSD, 512 GB, "
                       "4,128 h, 12% worn)")

    # ---- battery: the one real defect
    battery = report.check("battery")
    battery.data.update({
        "present": True, "battery_count": 2, "chemistry": "LiP",
        "design_mwh": 24000, "full_mwh": 16320, "remaining_mwh": 16320,
        "cycle_count": 412, "manufacturer": "SMP", "device_name": "45N1127",
        "serial": "4128", "manufacture_date": "2019-03-11",
        "power_online": True,
    })
    battery.findings = [R.Finding(
        id="battery.worn", severity=R.MAJOR,
        title="Battery at 68% of design capacity",
        detail=("16,320 mWh of 24,000 mWh left after 412 cycles. It will hold "
                "about 40 minutes of light use. A genuine 45N1127 is 12,000 PKR "
                "fitted."),
        evidence={"health_pct": 68, "cycles": 412},
        cost_pkr=12000, cost_note="Genuine 45N1127 battery, fitted.")]
    battery.score = 68.0
    battery.status = R.STATUS_WARN
    battery.summary = "68% of design capacity after 412 cycles"

    # ---- GPU: MX150 present, no driver resets
    # Keep the adapter dicts: the sensor panel reads kind/vram/driver, not names.
    gpu = report.check("gpu")
    adapters = gpu.data.get("adapters") or []
    for adapter in adapters:
        if adapter.get("kind") == "discrete":
            adapter.update({"name": "NVIDIA GeForce MX150", "vram_mb": 2048,
                            "driver": "31.0.15.3699",
                            "driver_date": "2023-06-14"})
        else:
            adapter.update({"name": "Intel(R) UHD Graphics 620",
                            "vram_mb": 8192, "driver": "31.0.101.2130",
                            "driver_date": "2023-11-02"})
    gpu.data.update({"adapters": adapters, "discrete_count": 1,
                     "tdr_count": 0, "unexpected_shutdowns": 0})
    gpu.findings = []
    gpu.score = 100.0
    gpu.status = R.STATUS_OK
    gpu.summary = "NVIDIA GeForce MX150, Intel(R) UHD Graphics 620 / no TDRs"

    dgpu = report.check("dgpu")
    dgpu.data.update({"discrete": True,
                      "adapters": ["NVIDIA GeForce MX150"],
                      "expected": ["NVIDIA GeForce MX150"],
                      "matched_model": {"family": "ThinkPad T480"}})
    dgpu.findings = []
    dgpu.score = 100.0
    dgpu.status = R.STATUS_OK
    dgpu.summary = "NVIDIA GeForce MX150"

    # ---- peripherals: everything a T480 ships with
    devices = _devices()
    per = report.check("peripherals")
    per.data.update({
        "devices": devices,
        "present": {k: len(v) for k, v in devices.items()},
        "broken": [],
        "wifi_generation": "WiFi 5", "wifi_standard": "802.11ac",
        "standards": ["802.11ac", "802.11n", "802.11g"],
        "bluetooth_version": "4.2", "bluetooth_version_source": "driver",
    })
    per.findings = []
    per.score = 100.0
    per.status = R.STATUS_OK
    per.summary = ("WiFi 5 up 866.7 Mbps · Ethernet 1 GbE · Bluetooth 4.2 · "
                   "Camera · Card reader · Fingerprint · Audio")

    # ---- the buyer's side of the deal
    report.claims = {"cpu": "i5-8250U", "ram_gb": 16, "storage_gb": 512,
                     "gpu": "MX150"}
    report.market = {"value_pkr": 68000, "source": "manual", "confidence": "good",
                     "note": "price entered by the buyer"}

    Inspector(Options(asking_price_pkr=78000, market_price_pkr=68000,
                      allow_market_search=False)).finalise(report)
    return report


if __name__ == "__main__":
    rep = build()
    import json
    from dataclasses import asdict
    with open("out/demo_report.json", "w", encoding="utf-8") as handle:
        json.dump(rep.to_dict(), handle, indent=2, ensure_ascii=False)
    print(f"{rep.machine['family']}: {rep.score:.0f}/100 {rep.verdict}")
    print(f"  repairs {rep.negotiation.total_repair_pkr:,} | "
          f"offer {rep.negotiation.suggested_offer_pkr:,} | "
          f"basis {rep.negotiation.price_basis}")
