"""Radios and peripherals: WiFi, Bluetooth, camera, Ethernet, modem, readers.

These are the parts a seller forgets to mention and a buyer forgets to look at.
They are also the parts Windows is happy to enumerate while they do not actually
work, so this check separates three states that get confused constantly:

* **absent** - the machine never had it. Not a defect, and never scored.
* **present and healthy** - the driver loaded and the device reports OK.
* **present and broken** - a PnP problem, an error status, or a radio switched
  off. That is a real defect and it is scored.

What this does *not* do is prove data flows. A WiFi link cannot be proven without
a network to join, and capturing a camera frame needs Media Foundation. The
report says "present and healthy", not "tested", and the detail text says so.
"""

from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Optional, Tuple

from .. import result as R
from ..context import Context, cost_of

KEY = "peripherals"
LABEL = "Radios & peripherals"

# (key, human name, cost if it has to be replaced, repair note)
CATEGORIES: List[Tuple[str, str, int, str]] = [
    ("wifi", "WiFi", 2500, "Mini PCIe / M.2 WiFi card."),
    ("bluetooth", "Bluetooth", 1500, "Often a combo card with the WiFi module."),
    ("camera", "Camera", 4500, "Webcam module and cable."),
    ("ethernet", "Ethernet", 3500, "NIC or its magnetics."),
    ("modem", "Modem", 0, ""),
    ("card_reader", "Card reader", 2500, "Reader daughterboard."),
    ("fingerprint", "Fingerprint reader", 3500, "Reader module."),
    ("audio", "Audio", 2500, "Jack, speaker or codec."),
]

GOOD_STATUS = ("ok", "", "unknown", "error-free")

# Highest amendment the driver claims. 802.11w is management-frame protection,
# not a generation, and 802.11a/b/g are not called "WiFi 1/2/3" by anyone, so
# only the four that get marketed are named.
WIFI_GENERATIONS = [
    ("802.11be", "WiFi 7"),
    ("802.11ax", "WiFi 6"),
    ("802.11ac", "WiFi 5"),
    ("802.11n", "WiFi 4"),
]

# Bluetooth spec version per controller family, for stacks that do not expose
# DEVPKEY_Bluetooth_Radio_Version. Published by the vendors; a machine whose
# chip is not listed reports no version rather than a guess.
BT_MODEL_VERSIONS = [
    ("ax211", "5.3"), ("ax210", "5.2"), ("ax201", "5.1"), ("ax200", "5.1"),
    ("9462", "5.1"), ("9560", "5.1"), ("9260", "5.1"),
    ("8265", "4.2"), ("8260", "4.2"), ("7265", "4.2"), ("3165", "4.2"),
    ("7260", "4.0"), ("bcm20702", "4.0"), ("bcm2045", "2.1"),
    ("qca6174", "4.1"), ("rtl8822", "4.2"), ("rtl8821", "4.2"),
    ("rtl8761", "5.0"), ("rtl8852", "5.2"),
]


def wifi_generation(standards: Any) -> Tuple[str, str]:
    """(label, token) for the best amendment the driver reports."""
    present = {str(s).strip().lower() for s in (standards or [])}
    for token, label in WIFI_GENERATIONS:
        if token in present:
            return label, token
    return "", ""


def bluetooth_version(devices: List[Dict[str, Any]]) -> Tuple[str, str]:
    """(version, where it came from) - 'driver', 'model', or neither."""
    for device in devices:
        reported = str(device.get("version") or "").strip()
        if reported and any(ch.isdigit() for ch in reported):
            return reported, "driver"
    for device in devices:
        name = str(device.get("name") or "").lower()
        for token, version in BT_MODEL_VERSIONS:
            if token in name:
                return version, "model"
    return "", ""


SPEED_PATTERN = re.compile(r"([0-9.]+)\s*(Mbps|Gbps)", re.IGNORECASE)


def _max_speed_mbps(values: Any) -> float:
    """Best speed in a driver's '10 Mbps | 100 Mbps | 1.0 Gbps' capability list."""
    best = 0.0
    for part in str(values or "").split("|"):
        match = SPEED_PATTERN.search(part)
        if not match:
            continue
        value = float(match.group(1))
        if match.group(2).lower() == "gbps":
            value *= 1000
        best = max(best, value)
    return best


def ethernet_label(mbps: float) -> str:
    if mbps >= 10000:
        return "10 GbE"
    if mbps >= 5000:
        return "5 GbE"
    if mbps >= 2500:
        return "2.5 GbE"
    if mbps >= 1000:
        return "1 GbE"
    if mbps >= 100:
        return "100 Mbps"
    if mbps >= 10:
        return "10 Mbps"
    return ""


def ethernet_speed(adapter: Dict[str, Any]) -> Tuple[str, float]:
    """(label, mbps) for what the wired port can do, not what it is doing now.

    A NIC with no cable in reports 0 bps, so the negotiated link says nothing
    about the port. The driver's speed/duplex capability list does.
    """
    mbps = _max_speed_mbps(adapter.get("speed_valid"))
    if mbps:
        return ethernet_label(mbps), mbps

    text = f"{adapter.get('description') or ''} {adapter.get('name') or ''}".lower()
    if "10 gigabit" in text or "10gbe" in text:
        return "10 GbE", 10000
    if "2.5gbe" in text or "2.5 gbe" in text:
        return "2.5 GbE", 2500
    if "gigabit" in text or "gbe" in text:
        return "1 GbE", 1000
    if "fast ethernet" in text:
        return "100 Mbps", 100
    return "", 0


def _list(value: Any) -> List[Dict[str, Any]]:
    """ConvertTo-Json collapses a one-element array into an object, and an empty
    one into something with no name at all."""
    if isinstance(value, list):
        items = [v for v in value if isinstance(v, dict)]
    elif isinstance(value, dict):
        items = [value]
    else:
        items = []
    return [i for i in items if str(i.get("name") or "").strip()]


# Windows keeps a record of hardware it can no longer see. Those are not
# defects - the dGPU check treats phantoms as evidence, but here they are just
# stale entries that would invent faults on every machine.
PHANTOM = "CM_PROB_PHANTOM"

# Adapters that are not real hardware. They report 802.3 like a NIC does.
VIRTUAL_WORDS = ("tap-", "wintun", "npcap", "loopback", "vpn", "virtual",
                 "hyper-v", "vmware", "virtualbox", "miniport", "teredo",
                 "isatap", "bluetooth pan")

# Get-NetAdapter statuses. Up and Disconnected are both healthy: an unplugged
# cable is not a broken port.
ADAPTER_BAD = ("disabled", "not present", "error", "unknown", "not operational")


def _devices(value: Any) -> List[Dict[str, Any]]:
    """Named, non-phantom devices only."""
    return [d for d in _list(value)
            if str(d.get("problem") or "") != PHANTOM]


def _healthy(device: Dict[str, Any]) -> bool:
    status = str(device.get("status") or "").strip().lower()
    problem = str(device.get("problem") or "").strip()
    if problem and problem not in ("CM_PROB_NONE", "0", "None"):
        return False
    return status in GOOD_STATUS


def _adapter_healthy(adapter: Dict[str, Any]) -> bool:
    return str(adapter.get("status") or "").strip().lower() not in ADAPTER_BAD


def _is_virtual(adapter: Dict[str, Any]) -> bool:
    text = f"{adapter.get('description') or ''} {adapter.get('name') or ''}".lower()
    return any(word in text for word in VIRTUAL_WORDS)


def _is_wifi(adapter: Dict[str, Any]) -> bool:
    physical = str(adapter.get("physical") or "")
    description = str(adapter.get("description") or "").lower()
    if _is_virtual(adapter):
        return False
    return "802.11" in physical or "wireless" in description or "wi-fi" in description


def _is_ethernet(adapter: Dict[str, Any]) -> bool:
    return str(adapter.get("physical") or "") == "802.3" and not _is_virtual(adapter)


def run(ctx: Context) -> R.CheckResult:
    check = R.CheckResult(key=KEY, label=LABEL)
    findings: List[R.Finding] = []

    data = ctx.peripherals or {}
    adapters = [a for a in _list(data.get("adapters"))
                if str(a.get("status") or "").strip().lower() != "not present"]

    wifi = [a for a in adapters if _is_wifi(a)]
    ethernet = [a for a in adapters if _is_ethernet(a)]

    groups: Dict[str, List[Dict[str, Any]]] = {
        "wifi": wifi,
        "bluetooth": _devices(data.get("bluetooth")),
        "camera": _devices(data.get("camera")),
        "ethernet": ethernet,
        "modem": _devices(data.get("modem")),
        "card_reader": _devices(data.get("sdhost")) + _devices(data.get("smartcard")),
        "fingerprint": _devices(data.get("biometric")),
        "audio": _devices(data.get("audio")),
    }

    if not adapters and not any(groups.values()):
        check.status = R.STATUS_UNAVAILABLE
        check.score = 0.0
        if os.environ.get("ULI_PE") == "1":
            # WinPE only enumerates devices whose drivers are in the image, so an
            # empty result here says nothing about the machine. Say that, rather
            # than implying the hardware is missing.
            check.summary = "Not visible in this boot environment"
            check.error = ("WinPE enumerates only devices with drivers present in "
                           "the image - absence here is not evidence of absence")
        else:
            check.summary = "No radio or peripheral data"
            check.error = "Device enumeration returned nothing"
        return check

    present: Dict[str, int] = {}
    broken: List[Tuple[str, Dict[str, Any]]] = []

    for key, _label, _cost, _note in CATEGORIES:
        devices = groups.get(key) or []
        present[key] = len(devices)
        for device in devices:
            # Network adapters report Up/Disconnected, not PnP's OK/Error.
            ok = (_adapter_healthy(device) if key in ("wifi", "ethernet")
                  else _healthy(device))
            if not ok:
                broken.append((key, device))

    # ---- devices that are there but not working
    seen_categories = set()
    for key, device in broken:
        label = next((c[1] for c in CATEGORIES if c[0] == key), key)
        cost = next((c[2] for c in CATEGORIES if c[0] == key), 0)
        note = next((c[3] for c in CATEGORIES if c[0] == key), "")
        first_of_kind = key not in seen_categories
        seen_categories.add(key)
        findings.append(R.Finding(
            id=f"peripherals.{key}_error",
            severity=R.MAJOR if first_of_kind else R.INFO,
            title=f"{label} is present but not working",
            detail=(f"{device.get('name')} reports status "
                    f"'{device.get('status') or '?'}'"
                    + (f", problem {device.get('problem')}"
                       if device.get("problem") else "")
                    + ". The hardware is there; the driver or the device itself "
                      "is not."),
            evidence={"device": device.get("name"),
                      "status": device.get("status"),
                      "problem": device.get("problem")},
            cost_pkr=cost or None,
            cost_note=note))

    # ---- WiFi: present but switched off is the classic "it's broken, bhai"
    for adapter in wifi:
        status = str(adapter.get("status") or "").lower()
        if status in ("disabled", "not present"):
            findings.append(R.Finding(
                id="peripherals.wifi_disabled", severity=R.MAJOR,
                title=f"WiFi adapter is {status}",
                detail=("The radio is off. On this generation of ThinkPad that is "
                        "usually the hardware switch on the front edge or a BIOS "
                        "setting - check both before believing the card is dead."),
                evidence={"adapter": adapter.get("name"), "status": status},
                cost_pkr=cost_of("wifi_card", 2500),
                cost_note="Only if the switch and BIOS are not the cause."))

    # ---- what is simply not there. Never scored: absence is not a defect.
    for key in ("wifi", "bluetooth", "camera"):
        if present.get(key):
            continue
        label = next((c[1] for c in CATEGORIES if c[0] == key), key)
        findings.append(R.Finding(
            id=f"peripherals.no_{key}", severity=R.INFO,
            title=f"No {label} enumerated",
            detail=(f"Windows reports no {label} device on this machine. Many "
                    "configurations shipped without one, so this is not scored - "
                    "but if the seller advertised it, it is missing."),
            evidence={"present": False}))

    # ---- Ethernet without a cable is not a fault
    if ethernet and not any(str(a.get("status") or "").lower() == "up"
                            for a in ethernet):
        findings.append(R.Finding(
            id="peripherals.ethernet_no_link", severity=R.INFO,
            title="Ethernet adapter has no link",
            detail=("The adapter is present but no cable is connected, so the "
                    "port itself is untested. Plug one in and rescan to prove it."),
            evidence={"adapters": [a.get("name") for a in ethernet]}))

    # ---- score: only things that are present and broken cost points
    score = 100.0
    score -= 25.0 * len(seen_categories)
    if any(f.id == "peripherals.wifi_disabled" for f in findings):
        score -= 10.0
    check.score = max(0.0, score)

    # ---- which generation of each radio is fitted
    wifi_label, wifi_token = wifi_generation(data.get("standards"))
    bt_version, bt_source = bluetooth_version(groups["bluetooth"])

    # ---- summary: what is here, at a glance
    bits = []
    if wifi:
        link = wifi[0].get("link") or ""
        status = str(wifi[0].get("status") or "")
        label = wifi_label or "WiFi"
        bits.append(f"{label} {status.lower() or 'present'}"
                    + (f" {link}" if link and status.lower() == "up" else ""))
    if ethernet:
        eth_label, _eth_mbps = ethernet_speed(ethernet[0])
        up = [a for a in ethernet if str(a.get("status") or "").lower() == "up"]
        state = f"up {ethernet[0].get('link')}" if up else "no link"
        bits.append(" ".join(x for x in ("Ethernet", eth_label, state) if x))
    for key, label, _cost, _note in CATEGORIES:
        if key in ("wifi", "ethernet"):
            continue
        if present.get(key):
            bits.append(f"BT {bt_version}" if key == "bluetooth" and bt_version
                        else label)
    if not bits:
        bits.append("no radios or peripherals")
    check.summary = " · ".join(bits)

    # What is actually fitted, so the UI can show the hardware rather than only
    # the complaints about it - including which generation of radio it is.
    devices_out: Dict[str, List[Dict[str, Any]]] = {}
    for key, items in groups.items():
        rows = []
        for device in items:
            row = {
                "name": device.get("name"),
                "status": device.get("status") or "",
                "link": device.get("link") or "",
                "ok": (_adapter_healthy(device) if key in ("wifi", "ethernet")
                       else _healthy(device)),
            }
            if key == "wifi":
                row["generation"] = wifi_label
                row["standard"] = wifi_token
            if key == "ethernet":
                label, mbps = ethernet_speed(device)
                row["speed"] = label
                row["speed_mbps"] = mbps
            if key == "bluetooth":
                row["version"] = bt_version
                row["version_source"] = bt_source
            rows.append(row)
        devices_out[key] = rows

    check.data = {
        "present": present,
        "wifi": wifi,
        "ethernet": ethernet,
        "broken": [{"category": k, "device": d.get("name"),
                    "status": d.get("status"), "problem": d.get("problem")}
                   for k, d in broken],
        "adapters": adapters,
        "standards": data.get("standards") or [],
        "wifi_generation": wifi_label,
        "wifi_standard": wifi_token,
        "bluetooth_version": bt_version,
        "bluetooth_version_source": bt_source,
        "devices": devices_out,
    }
    check.findings = findings
    has_major = any(f.severity in (R.MAJOR, R.CRITICAL) for f in findings)
    check.status = R.STATUS_WARN if has_major else R.STATUS_OK
    return check
