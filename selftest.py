"""Self-test: validates the binary parsers against synthetic buffers.

The SMART and NVMe paths need administrator rights to run for real, which makes
them the hardest part of this tool to regression-test. So the parsers are tested
against buffers built byte by byte from the published layouts - if the offsets
drift, this fails.

    python selftest.py

No hardware, no admin, no network.
"""

from __future__ import annotations

import struct
import sys

sys.path.insert(0, ".")

from laptop_inspector.engine import result as R, util, winapi  # noqa: E402
from laptop_inspector.scoring import negotiation, rubric  # noqa: E402

PASS = 0
FAIL = 0


def check(name: str, condition: bool, detail: str = "") -> None:
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  ok    {name}")
    else:
        FAIL += 1
        print(f"  FAIL  {name}   {detail}")


# --------------------------------------------------------------------------
def build_ata_smart(attributes) -> bytes:
    """30 x 12-byte entries at offset 2: id, flags(2), value, worst, raw(6)."""
    buf = bytearray(512)
    buf[0:2] = (0x01, 0x00)
    for index, (attr_id, value, raw) in enumerate(attributes):
        off = 2 + index * 12
        buf[off] = attr_id
        struct.pack_into("<H", buf, off + 1, 0x0032)
        buf[off + 3] = value
        buf[off + 4] = value
        buf[off + 5: off + 11] = int(raw).to_bytes(6, "little")
    return bytes(buf)


def build_nvme_smart(percentage_used=14, temp_c=41, hours=1234,
                     written_units=500, media_errors=0,
                     critical_warning=0) -> bytes:
    buf = bytearray(512)
    buf[0] = critical_warning
    struct.pack_into("<H", buf, 1, int((temp_c + 273.15)))
    buf[3] = 100
    buf[4] = 10
    buf[5] = percentage_used
    buf[23:39] = (written_units * 2).to_bytes(16, "little")
    buf[39:55] = written_units.to_bytes(16, "little")
    buf[119:135] = hours.to_bytes(16, "little")
    buf[151:167] = media_errors.to_bytes(16, "little")
    return bytes(buf)


def build_msdm(key="VK7JG-NPHTM-C97JM-9MPGT-3V66T") -> bytes:
    buf = bytearray(80)
    buf[0:4] = b"MSDM"
    struct.pack_into("<I", buf, 4, len(buf))
    buf[10:16] = b"LENOVO"
    struct.pack_into("<I", buf, 36, 1)
    struct.pack_into("<I", buf, 40, 0)
    struct.pack_into("<I", buf, 44, 0)
    raw_key = key.replace("-", "").encode("ascii")[:25]
    buf[48:48 + len(raw_key)] = raw_key
    return bytes(buf)


def test_smart() -> None:
    print("\nATA SMART parsing")
    buf = build_ata_smart([
        (5, 100, 12),        # reallocated sectors
        (9, 99, 20000),      # power-on hours
        (194, 62, 38),       # temperature
        (197, 100, 0),       # pending
        (198, 100, 0),       # offline uncorrectable
        (231, 87, 0),        # SSD life left
        (241, 99, 40_000_000),  # LBAs written
    ])
    attrs = winapi.parse_smart_attributes(buf)
    check("seven attributes parsed", len(attrs) == 7, str(len(attrs)))
    check("attribute 5 id", attrs[5]["id"] == 5)
    check("attribute 5 raw = 12", attrs[5]["raw"] == 12, str(attrs[5]["raw"]))
    check("attribute 9 raw = 20000", attrs[9]["raw"] == 20000)
    check("attribute 194 raw = 38", attrs[194]["raw"] == 38)
    check("attribute 231 value = 87", attrs[231]["value"] == 87)
    check("48-bit raw survives",
          attrs[241]["raw"] == 40_000_000, str(attrs[241]["raw"]))

    # the storage check's interpretation layer
    from laptop_inspector.engine.checks import storage as storage_check
    health = storage_check._ata_health(attrs)
    check("reallocated read", health["reallocated"] == 12)
    check("power-on hours read", health["power_on_hours"] == 20000)
    check("temperature read", health["temperature_c"] == 38.0,
          str(health["temperature_c"]))
    check("SSD wear inverted from life-left", health["wear_pct"] == 13,
          str(health["wear_pct"]))
    check("bytes written from LBAs",
          health["bytes_written"] == 40_000_000 * 512)

    empty = winapi.parse_smart_attributes(bytes(512))
    check("all-zero table yields nothing", empty == {})


def test_nvme() -> None:
    print("\nNVMe SMART parsing")
    buf = build_nvme_smart(percentage_used=14, temp_c=41, hours=1234,
                           written_units=500)
    log = winapi.parse_nvme_smart(buf)
    check("percentage used = 14", log["percentage_used"] == 14,
          str(log.get("percentage_used")))
    check("temperature = 41 C", abs((log["temperature_c"] or 0) - 41) < 0.6,
          str(log.get("temperature_c")))
    check("power-on hours = 1234", log["power_on_hours"] == 1234,
          str(log.get("power_on_hours")))
    check("data units written = 500", log["data_units_written"] == 500)
    check("bytes written scales by 512000",
          log["bytes_written"] == 500 * 512000, str(log.get("bytes_written")))
    check("available spare = 100", log["available_spare_pct"] == 100)
    check("critical warning clear", log["critical_warning"] == 0)

    bad = winapi.parse_nvme_smart(build_nvme_smart(critical_warning=0x04))
    check("critical warning bit surfaces", bad["critical_warning"] == 0x04)
    check("short buffer rejected", winapi.parse_nvme_smart(b"\x00" * 40) == {})


def test_msdm() -> None:
    print("\nMSDM / OEM key parsing")
    raw = build_msdm("VK7JG-NPHTM-C97JM-9MPGT-3V66T")
    key = winapi.parse_msdm_key(raw)
    check("key recovered", key == "VK7JG-NPHTM-C97JM-9MPGT-3V66T", str(key))
    check("missing table returns None", winapi.parse_msdm_key(None) is None)
    check("truncated table returns None",
          winapi.parse_msdm_key(b"MSDM" + bytes(20)) is None)

    # a table that stores the key already dashed must not double up
    dashed = bytearray(build_msdm())
    dashed[48:77] = b"VK7JG-NPHTM-C97JM-9MPGT-3V66T"
    check("dashed key handled",
          winapi.parse_msdm_key(bytes(dashed)) == "VK7JG-NPHTM-C97JM-9MPGT-3V66T",
          str(winapi.parse_msdm_key(bytes(dashed))))


def test_identify() -> None:
    print("\nATA IDENTIFY parsing (word-swapped strings)")
    raw = bytearray(512)

    def put(text: str, start: int, words: int) -> None:
        chunk = text.ljust(words * 2).encode("ascii")[:words * 2]
        swapped = bytearray(chunk)
        for i in range(0, len(swapped) - 1, 2):
            swapped[i], swapped[i + 1] = swapped[i + 1], swapped[i]
        raw[start:start + len(swapped)] = swapped

    put("Samsung SSD 860", 54, 20)
    put("S3Z8NB0K123456", 20, 10)
    put("RVT04B6Q", 46, 4)
    struct.pack_into("<H", raw, 217, 0)
    info = winapi.parse_identify(bytes(raw))
    check("model unswapped", info["model"].startswith("Samsung SSD 860"),
          info["model"])
    check("serial unswapped", info["serial"].startswith("S3Z8NB0K"),
          info["serial"])
    check("rotation rate 0 means SSD", info["rotation_rate"] == 0)


def test_util() -> None:
    print("\nHelpers")
    check("wmi date parsed",
          util.fmt_date("/Date(1528934400000)/") == "2018-06-14",
          util.fmt_date("/Date(1528934400000)/"))
    check("null date is empty", util.fmt_date(None) == "")
    check("placeholder serial detected", util.is_placeholder("Default string"))
    check("real serial accepted", not util.is_placeholder("R9HVG07"))
    check("nvidia classified discrete",
          util.classify_gpu("NVIDIA Quadro 2000M") == "discrete")
    check("intel classified integrated",
          util.classify_gpu("Intel(R) HD Graphics 3000") == "integrated")
    check("virtual adapter excluded",
          util.classify_gpu("Microsoft Basic Display Adapter") == "virtual")
    check("decimal GB for drives", util.gb_decimal(256060514304) == 256,
          str(util.gb_decimal(256060514304)))
    check("binary GB for RAM", util.gb(12646203392) == 11.8,
          str(util.gb(12646203392)))


def test_scoring() -> None:
    print("\nScoring and verdict")
    good = [R.CheckResult(key="storage", label="Storage", score=100, weight=25),
            R.CheckResult(key="battery", label="Battery", score=100, weight=20),
            R.CheckResult(key="specs", label="Specs", score=100, weight=20),
            R.CheckResult(key="thermal", label="Thermal", score=100, weight=15),
            R.CheckResult(key="gpu", label="GPU", score=100, weight=10),
            R.CheckResult(key="dgpu", label="dGPU", score=100, weight=10)]
    score, _ = rubric.weighted_score(good)
    check("perfect machine scores 100", score == 100.0, str(score))
    verdict, _ = rubric.verdict_for(score, good)
    check("perfect machine is BUY", verdict == "BUY", verdict)

    # an unavailable check must drop out of the denominator, not score zero
    partial = [R.CheckResult(key="storage", label="Storage", score=0, weight=25,
                             status=R.STATUS_UNAVAILABLE),
               R.CheckResult(key="battery", label="Battery", score=80, weight=20),
               R.CheckResult(key="specs", label="Specs", score=80, weight=20)]
    score, _ = rubric.weighted_score(partial)
    check("unavailable check excluded from weighting", score == 80.0, str(score))

    blocker = [R.CheckResult(key="storage", label="Storage", score=90, weight=25,
                             findings=[R.Finding(id="x", severity=R.CRITICAL,
                                                 title="Drive failing",
                                                 blocking=True)])]
    verdict, reasons = rubric.verdict_for(90.0, blocker)
    check("blocking finding forces WALK AWAY", verdict == "WALK AWAY", verdict)

    major = [R.CheckResult(key="battery", label="Battery", score=88, weight=20,
                           findings=[R.Finding(id="y", severity=R.MAJOR,
                                               title="Battery worn")])]
    verdict, _ = rubric.verdict_for(88.0, major)
    check("major finding caps at NEGOTIATE", verdict == "NEGOTIATE", verdict)


def test_negotiation() -> None:
    print("\nNegotiation math")
    checks = [R.CheckResult(
        key="battery", label="Battery", score=40,
        findings=[R.Finding(id="b", severity=R.MAJOR, title="Battery at 61%",
                            cost_pkr=15000, cost_note="replacement")]),
        R.CheckResult(
            key="storage", label="Storage", score=60,
            findings=[R.Finding(id="s", severity=R.WARN, title="Drive wear",
                                cost_pkr=9000)])]
    neg = negotiation.build(checks, 100000)
    check("line items collected", len(neg.items) == 2, str(len(neg.items)))
    check("total is 24000", neg.total_repair_pkr == 24000,
          str(neg.total_repair_pkr))
    check("buffer applied (10%)", neg.suggested_offer_pkr == 100000 - 24000 - 2400,
          str(neg.suggested_offer_pkr))
    check("ceiling is asking minus repairs", neg.max_offer_pkr == 76000,
          str(neg.max_offer_pkr))
    check("discount pct computed", neg.discount_pct == 24.0, str(neg.discount_pct))
    check("24% is negotiable, not walk-away", not neg.walk_away)

    heavy = [R.CheckResult(
        key="storage", label="Storage", score=10,
        findings=[R.Finding(id="s", severity=R.CRITICAL, title="Drive failing",
                            cost_pkr=60000, blocking=True)])]
    neg = negotiation.build(heavy, 80000)
    check("blocking defect forces walk away", neg.walk_away)

    no_price = negotiation.build(checks, None)
    check("no asking price still totals repairs", no_price.total_repair_pkr == 24000)
    check("no asking price gives no offer", no_price.suggested_offer_pkr is None)


def test_models() -> None:
    print("\nModel database")
    db = __import__("laptop_inspector.engine.context", fromlist=["load_json"]).load_json(
        "models.json")
    models = db.get("models") or []
    check("database has 50+ models", len(models) >= 50, str(len(models)))
    ids = [m["id"] for m in models]
    check("ids unique", len(ids) == len(set(ids)))
    bad = [m["id"] for m in models if not m.get("match")]
    check("every model has match patterns", not bad, str(bad))
    import re
    broken = []
    for m in models:
        for pattern in m["match"]:
            try:
                re.compile(pattern, re.IGNORECASE)
            except re.error:
                broken.append(m["id"])
    check("all patterns compile", not broken, str(broken))

    # the W520 must match on the machine-type code, which is what WMI reports
    def matches(needle: str) -> bool:
        for m in models:
            for pattern in m["match"]:
                if re.search(pattern, needle, re.IGNORECASE):
                    return True
        return False

    check("W520 matches on family string",
          matches("LENOVO 4282AC5 ThinkPad W520"))
    check("W520 matches on bare machine type", matches("4282AC5"))
    check("unknown model does not match", not matches("Some Other Laptop 9000"))


def test_storage_evaluate() -> None:
    """Exercise the storage scoring with synthetic drives.

    This is the check that cannot run without admin, so its logic - including
    every finding branch - is driven directly here instead.
    """
    print("\nStorage evaluation")
    from laptop_inspector.engine.checks import storage as storage_check
    from laptop_inspector.engine.context import Context

    ctx = Context()
    ctx.facts = {"bios": {"release_date": "/Date(1300000000000)/"}}  # 2011

    def drive(index, smart, size_gb=256, interface="SATA", ok=True):
        return {
            "index": index, "model": f"TEST-{index}", "size_gb": size_gb,
            "size_bytes": int(size_gb * 1e9), "interface": interface,
            "media": "SSD", "smart_ok": ok, "smart": smart,
        }

    # healthy
    findings = []
    score = storage_check._evaluate(
        drive(0, {"power_on_hours": 3000, "reallocated": 0, "pending": 0,
                  "uncorrectable": 0, "wear_pct": 8, "temperature_c": 36}), ctx,
        findings)
    check("healthy drive scores 100", score == 100.0, str(score))
    check("healthy drive raises nothing", not findings, str([f.id for f in findings]))

    # pending sectors - the blocking case
    findings = []
    score = storage_check._evaluate(
        drive(0, {"power_on_hours": 36000, "pending": 24, "reallocated": 0,
                  "uncorrectable": 0}), ctx, findings)
    ids = [f.id for f in findings]
    check("pending sectors detected", any("pending" in i for i in ids), str(ids))
    check("pending sectors are blocking",
          any(f.blocking for f in findings))
    check("pending sectors force a low score", score <= 20, str(score))

    # endurance exhausted
    findings = []
    score = storage_check._evaluate(
        drive(0, {"power_on_hours": 9000, "wear_pct": 94}), ctx, findings)
    check("wear above 90 is critical",
          any(f.severity == R.CRITICAL for f in findings))
    check("wear above 90 is blocking", any(f.blocking for f in findings))

    # SMART wiped on an old machine
    findings = []
    storage_check._evaluate(
        drive(0, {"power_on_hours": 12, "reallocated": 0}), ctx, findings)
    check("implausible low hours flagged",
          any("smart_wiped" in f.id for f in findings),
          str([f.id for f in findings]))

    # unreadable SMART
    findings = []
    score = storage_check._evaluate(
        drive(0, {}, ok=False), ctx, findings)
    check("unreadable SMART is a finding",
          any("smart_unreadable" in f.id for f in findings))
    check("unreadable SMART scores 45", score == 45.0, str(score))

    # interface CRC errors - also proves every keyword in this branch is valid
    findings = []
    storage_check._evaluate(
        drive(0, {"power_on_hours": 3619, "crc_errors": 740,
                  "temperature_c": 36}), ctx, findings)
    crc = [f for f in findings if "crc" in f.id]
    check("interface CRC errors flagged", bool(crc), str([f.id for f in findings]))
    check("CRC finding carries a cost", bool(crc and crc[0].cost_pkr))

    # an SSD that reports no endurance attribute should say so, not stay silent
    findings = []
    storage_check._evaluate(
        drive(0, {"power_on_hours": 3619}), ctx, findings)
    check("missing endurance attribute is reported",
          any("no_wear" in f.id for f in findings),
          str([f.id for f in findings]))


def test_interactive() -> None:
    """v2 interactive results: skipped, clean, and defective."""
    print("\nInteractive tests (v2)")
    from laptop_inspector.engine.checks import interactive

    skipped = interactive.build_check({})
    check("skipped test reports unavailable",
          skipped.status == R.STATUS_UNAVAILABLE, skipped.status)
    check("skipped test is not scored", not skipped.scored)

    clean = interactive.build_check({
        "screen": {"run": True, "issues": []},
        "keyboard": {"run": True, "pressed": ["A"] * 74, "missing": [], "expected": 74},
        "ports": {"run": True, "ports_tested": 3, "failed": [],
                  "audio": {"run": True, "left": True, "right": True}},
    })
    check("clean run scores 100", clean.score == 100.0, str(clean.score))
    check("clean run is ok", clean.status == R.STATUS_OK, clean.status)

    bad = interactive.build_check({
        "screen": {"run": True, "issues": ["backlight bleed"]},
        "keyboard": {"run": True, "pressed": ["A"], "missing": ["F1", "F2"]},
        "ports": {"run": True, "ports_tested": 2, "failed": ["port 2"],
                  "audio": {"run": True, "left": True, "right": False}},
    })
    titles = " | ".join(f.title for f in bad.findings)
    check("screen issue reported", "backlight bleed" in titles, titles)
    check("dead keys reported", "2 key(s)" in titles, titles)
    check("dead port reported", "port(s) did not respond" in titles, titles)
    check("silent audio channel reported", "right channel silent" in titles, titles)
    check("defects reduce the score", bad.score < 60, str(bad.score))
    check("every defect carries a cost",
          all(f.cost_pkr for f in bad.findings
              if f.severity in (R.MAJOR, R.WARN)),
          str([(f.title, f.cost_pkr) for f in bad.findings]))


def test_stress_rescore() -> None:
    """A hand-run load test must rescore exactly like the scan does."""
    print("\nStress lab rescoring")
    from laptop_inspector.engine.checks import gpu as gpu_check
    from laptop_inspector.engine.checks import thermal as thermal_check

    healthy = {
        "nominal_mhz": 2300, "peak_mhz": 3000.0, "sustained_mhz": 2940.0,
        "throughput_decay": 0.98, "mean_util": 99.0, "workers": 8,
        "degraded": False, "error": None, "samples": 30, "temps_c": [70.0],
        "series": [],
    }
    ok = thermal_check.from_probe(healthy)
    check("healthy probe scores high", ok.score >= 90, str(ok.score))
    check("healthy probe is ok", ok.status == R.STATUS_OK, ok.status)

    throttled = dict(healthy, sustained_mhz=1500.0, peak_mhz=3000.0,
                     throughput_decay=0.6)
    bad = thermal_check.from_probe(throttled)
    check("throttled probe scores low", bad.score < 60, str(bad.score))
    check("throttled probe fails", bad.status == R.STATUS_FAIL, bad.status)
    check("throttling carries a repair cost",
          any(f.cost_pkr for f in bad.findings), str(bad.findings))

    empty = thermal_check.from_probe({"samples": 0, "error": "stopped"})
    check("empty probe is unavailable", empty.status == R.STATUS_UNAVAILABLE,
          empty.status)

    # GPU: the stress penalty must be replaced, not stacked
    base = R.CheckResult(key="gpu", label="GPU sanity", score=100.0, status=R.STATUS_OK)
    base.findings = []
    base.data = {"stress_penalty": 0}
    gpu_check.apply_stress(base, {"available": True, "clears_per_sec": 400000})
    check("healthy stress keeps the score", base.score == 100.0, str(base.score))

    reset = {"available": True, "device_removed": True, "hresult": -2005270523}
    gpu_check.apply_stress(base, reset)
    check("driver reset costs 60 points", base.score == 40.0, str(base.score))
    check("driver reset is blocking",
          any(f.blocking for f in base.findings), str(base.findings))

    # re-applying must not deduct twice
    gpu_check.apply_stress(base, reset)
    check("re-applying the same result does not double-penalise",
          base.score == 40.0, str(base.score))

    gpu_check.apply_stress(base, {"available": True, "clears_per_sec": 400000})
    check("a clean re-run restores the score", base.score == 100.0, str(base.score))
    check("stale stress findings are removed",
          not any("reset" in f.title.lower() for f in base.findings),
          str([f.title for f in base.findings]))


def test_port_layout() -> None:
    """The port test tells the buyer where to plug in, so the lookup matters."""
    print("\nPort layout lookup")
    from laptop_inspector.ui.tests.port_map import lookup
    from laptop_inspector.ui.tests.port_test import _describe, _device_key

    w520 = lookup({"manufacturer": "LENOVO", "family": "ThinkPad W520",
                   "model": "4282AC5"})
    check("W520 is recognised", w520.known, w520.family)
    check("W520 has testable USB ports", len(w520.testable) >= 3,
          str([p.label for p in w520.testable]))
    check("audio is not walked as a USB port",
          all(p.kind != "audio" for p in w520.testable),
          str([p.kind for p in w520.testable]))
    check("ports carry a side and a position",
          all(p.side in ("left", "right", "rear") for p in w520.ports),
          str([(p.label, p.side) for p in w520.ports]))
    check("first testable port is on the left side",
          w520.testable[0].side == "left", w520.testable[0].side)

    # The layout is the part that was wrong before, so pin the documented order.
    left = [p.label for p in w520.ports if p.side == "left"]
    right = [p.label for p in w520.ports if p.side == "right"]
    rear = [p.label for p in w520.ports if p.side == "rear"]
    check("left side order (rear to front)",
          left == ["DisplayPort", "VGA", "USB 3.0", "USB 3.0",
                   "USB 2.0 / eSATA", "FireWire 400", "WiFi switch"], str(left))
    check("right side order (rear to front)",
          right == ["Kensington lock", "Ethernet", "DVD drive",
                    "Headphone / mic", "Card reader", "ExpressCard/34"], str(right))
    check("rear order", rear[:3] == ["Power", "Modem", "USB 2.0 (powered)"],
          str(rear))
    check("USB 3.0 is on the left, not the right",
          any("USB 3.0" in p for p in left) and not any("USB 3.0" in p for p in right),
          f"left={left} right={right}")
    check("Ethernet is on the right, not the rear",
          "Ethernet" in right and "Ethernet" not in rear,
          f"right={right} rear={rear}")
    check("audio jack is on the right", "Headphone / mic" in right, str(right))
    check("layout carries its source", bool(w520.source), w520.source)

    unknown = lookup({"manufacturer": "ACME", "family": "Notebook 9000"})
    check("unknown model falls back", not unknown.known, unknown.family)
    check("fallback still has ports", len(unknown.testable) >= 2,
          str(len(unknown.testable)))

    check("empty machine does not crash", lookup({}) is not None)
    check("none machine does not crash", lookup(None) is not None)

    path = (r"\\?\USB#VID_0781&PID_5583#4C5300#{guid}")
    check("device path is readable", "0781" in _describe(path), _describe(path))
    check("key is stable for the same path",
          _device_key(path) == _device_key(path), _device_key(path))
    check("same model, different serial -> different keys",
          _device_key(path) != _device_key(path.replace("4C5300", "4C5301")),
          _device_key(path))
    check("different devices have different keys",
          _device_key(path) != _device_key(path.replace("0781", "046D")),
          _device_key(path))


def test_keyboard_sides() -> None:
    """Qt collapses left and right modifiers; the scan code is the only side."""
    print("\nKeyboard modifier sides")
    from laptop_inspector.ui.tests.keyboard_test import (_side_from_scan,
                                                         VK_LSHIFT, VK_RSHIFT,
                                                         VK_LCONTROL, VK_RCONTROL,
                                                         VK_LMENU, VK_RMENU,
                                                         ALL_KEYS)
    check("left shift", _side_from_scan(0x2A) == VK_LSHIFT)
    check("right shift", _side_from_scan(0x36) == VK_RSHIFT)
    check("left ctrl", _side_from_scan(0x1D) == VK_LCONTROL)
    check("right ctrl (E0 prefixed)", _side_from_scan(0xE01D) == VK_RCONTROL)
    check("left alt", _side_from_scan(0x38) == VK_LMENU)
    check("right alt (E0 prefixed)", _side_from_scan(0xE038) == VK_RMENU)
    check("unknown scan code", _side_from_scan(0x99) is None)

    idents = [k.ident for k in ALL_KEYS]
    check("every key has a unique identity", len(idents) == len(set(idents)),
          str(len(idents) - len(set(idents))) + " duplicates")
    names = [k.name for k in ALL_KEYS]
    check("left and right shift are distinct", "Left Shift" in names
          and "Right Shift" in names, str([n for n in names if "Shift" in n]))
    check("Tab is observable", "Tab" in names)
    check("Space is observable and labelled", "Space" in names)
    check("Fn is excluded", not any(k.label == "Fn" for k in ALL_KEYS
                                    if k.observable))


def test_webimages() -> None:
    """The photo lookup, tested without touching the network."""
    print("\nWeb photo lookup")
    import json as _json
    from laptop_inspector.engine import webimages

    commons_payload = {
        "query": {"pages": {
            "11": {
                "title": "File:W520 left side.jpg",
                "imageinfo": [{
                    "mime": "image/jpeg", "width": 3264, "height": 2448,
                    "url": "https://upload.wikimedia.org/x/W520_left_side.jpg",
                    "thumburl": "https://upload.wikimedia.org/x/800px-W520_left_side.jpg",
                    "thumbwidth": 800, "thumbheight": 600,
                    "descriptionurl": "https://commons.wikimedia.org/wiki/File:W520_left_side.jpg",
                    "extmetadata": {
                        "LicenseShortName": {"value": "CC BY-SA 3.0"},
                        "Artist": {"value": "<a href='#'>A Person</a>"},
                    },
                }],
            },
            "12": {
                "title": "File:Logo.png",
                "imageinfo": [{
                    "mime": "image/png", "width": 200, "height": 200,
                    "url": "https://upload.wikimedia.org/x/Logo.png",
                    "thumburl": "https://upload.wikimedia.org/x/200px-Logo.png",
                    "descriptionurl": "https://commons.wikimedia.org/wiki/File:Logo.png",
                    "extmetadata": {
                        "LicenseShortName": {"value": "All rights reserved"},
                    },
                }],
            },
        }}
    }
    bing_html = (
        '<a class="iusc" m="{&quot;murl&quot;:&quot;https://cdn.example.com/'
        'w520-right-ports.jpg&quot;,&quot;purl&quot;:&quot;https://example.com/'
        'review&quot;,&quot;t&quot;:&quot;W520 right side ports&quot;}"></a>'
        '<a class="iusc" m="{&quot;murl&quot;:&quot;https://cdn.example.com/'
        'x240-left.jpg&quot;,&quot;purl&quot;:&quot;https://example.com/x240'
        '&quot;,&quot;t&quot;:&quot;X240 left&quot;}"></a>'
    )

    calls = []

    def fake_get(url, timeout):
        calls.append(url)
        if "commons.wikimedia.org" in url:
            return _json.dumps(commons_payload).encode()
        if "bing.com" in url:
            return bing_html.encode()
        return None

    original_get = webimages._get
    original_cache = webimages._cache_get, webimages._cache_put
    webimages._get = fake_get
    webimages._cache_get = lambda key: None
    webimages._cache_put = lambda key, payload: None
    try:
        commons = webimages._commons("ThinkPad W520", 3, 1.0)
        check("commons result parsed", len(commons) == 1, str(len(commons)))
        check("commons licence read", commons[0].licence == "CC BY-SA 3.0",
              commons[0].licence)
        check("html stripped from author", commons[0].author == "A Person",
              commons[0].author)
        check("non-free image filtered out", len(commons) == 1, str(len(commons)))
        check("side detected from filename", commons[0].side == "left",
              commons[0].side)

        bing = webimages._bing("ThinkPad W520", 3, 1.0)
        check("bing results parsed", len(bing) == 2, str(len(bing)))
        check("bing media url extracted",
              bing[0].url.startswith("https://cdn.example.com/"), bing[0].url)

        results = webimages.search("ThinkPad W520", limit=4)
        urls = [r.url for r in results]
        check("search merges providers", len(results) >= 2, str(urls))
        check("wrong model filtered out",
              not any("x240" in u for u in urls), str(urls))
        check("port photo ranked first",
              "w520" in urls[0].lower(), urls[0] if urls else "none")

        # a URL containing "backnumber" is not a rear view
        probe = webimages.Photo(url="http://x/thinkpad_w520_port.jpg",
                                title="ThinkPad W520")
        check("word boundary respected", probe.side == "", probe.side)

        webimages._get = lambda url, timeout: None
        check("network failure returns empty", webimages.search("Nope 9000") == [])

        # what gets sent over the wire
        q = webimages.model_query
        check("known model uses the layout family",
              q({"family": "ThinkPad W520"}, "ThinkPad W520") == "ThinkPad W520",
              q({"family": "ThinkPad W520"}, "ThinkPad W520"))
        check("unknown model uses the reported family",
              q({"family": "EliteBook 840 G3"}, "Generic laptop") == "EliteBook 840 G3",
              q({"family": "EliteBook 840 G3"}, "Generic laptop"))
        check("no family falls back to maker and model",
              q({"manufacturer": "Dell Inc.", "model": "Latitude E7470"},
                "Generic laptop") == "Dell Latitude E7470",
              q({"manufacturer": "Dell Inc.", "model": "Latitude E7470"},
                "Generic laptop"))
        check("generic family is never searched for",
              "generic" not in q({"manufacturer": "", "model": ""},
                                 "Generic laptop").lower(),
              q({"manufacturer": "", "model": ""}, "Generic laptop"))
        check("nothing identified means no query",
              q({}, "Generic laptop") == "", repr(q({}, "Generic laptop")))
        check("nothing at all does not crash", q(None, "") == "")
    finally:
        webimages._get = original_get
        webimages._cache_get, webimages._cache_put = original_cache


def test_gpu_adapter_choice() -> None:
    """The GPU test must hammer the discrete card, not the iGPU."""
    print("\nGPU adapter selection")
    from laptop_inspector.engine import d3d11

    intel = {"name": "Intel(R) HD Graphics 3000", "vendor_id": 0x8086,
             "vendor": "Intel", "vram_mb": 32, "software": False}
    nvidia = {"name": "NVIDIA Quadro 2000M", "vendor_id": 0x10DE,
              "vendor": "NVIDIA", "vram_mb": 2000, "software": False}
    amd = {"name": "AMD Radeon HD 7690M", "vendor_id": 0x1002,
           "vendor": "AMD", "vram_mb": 1024, "software": False}
    warp = {"name": "Microsoft Basic Render Driver", "vendor_id": 0x1414,
            "vendor": "Microsoft", "vram_mb": 0, "software": True}

    original = d3d11.adapters
    try:
        d3d11.adapters = lambda: [intel, nvidia, warp]
        _, picked = d3d11._best_adapter()
        check("discrete NVIDIA beats Intel iGPU",
              picked and picked["name"].startswith("NVIDIA"),
              str(picked and picked["name"]))

        d3d11.adapters = lambda: [intel, amd, nvidia]
        _, picked = d3d11._best_adapter()
        check("NVIDIA beats a weaker AMD card",
              picked and picked["name"].startswith("NVIDIA"),
              str(picked and picked["name"]))

        d3d11.adapters = lambda: [intel]
        _, picked = d3d11._best_adapter()
        check("iGPU only falls back to it",
              picked and picked["name"].startswith("Intel"),
              str(picked and picked["name"]))

        d3d11.adapters = lambda: [warp]
        ptr, picked = d3d11._best_adapter()
        check("software renderer is never stressed", ptr is None,
              str(picked and picked["name"]))

        d3d11.adapters = lambda: []
        ptr, picked = d3d11._best_adapter()
        check("no adapters does not crash", ptr is None and picked is None)
    finally:
        d3d11.adapters = original

    # These slots come from ID3D11DeviceContextVtbl in the mingw-w64 d3d11.h.
    # Three earlier values were wrong and produced a fake result, so they are
    # pinned: 50 ClearRenderTargetView, 44 RSSetViewports, 33 OMSetRenderTargets,
    # 13 Draw, 112 GetType (which stress() uses to validate itself).
    check("clear uses ClearRenderTargetView slot 50",
          d3d11.CONTEXT_CLEAR_RTV == 50, str(d3d11.CONTEXT_CLEAR_RTV))
    check("viewport slot is 44",
          d3d11.CONTEXT_RS_SET_VIEWPORTS == 44,
          str(d3d11.CONTEXT_RS_SET_VIEWPORTS))
    check("render-target slot is 33",
          d3d11.CONTEXT_OM_SET_RT == 33, str(d3d11.CONTEXT_OM_SET_RT))
    check("draw slot is 13", d3d11.CONTEXT_DRAW == 13, str(d3d11.CONTEXT_DRAW))
    check("GetType slot is 112",
          d3d11.CONTEXT_GET_TYPE == 112, str(d3d11.CONTEXT_GET_TYPE))
    check("removed-reason slot is 39",
          d3d11.DEVICE_REMOVED_REASON == 39, str(d3d11.DEVICE_REMOVED_REASON))


def test_peripherals() -> None:
    """Radios and peripherals: absence is not a defect, phantoms are not devices."""
    print("\nRadios & peripherals")
    from laptop_inspector.engine.checks import peripherals
    from laptop_inspector.engine.context import Context

    def ctx_with(**data):
        ctx = Context()
        ctx.peripherals = data
        return ctx

    adapter = lambda desc, physical, status: {
        "name": desc, "description": desc, "status": status,
        "physical": physical, "link": "1 Gbps"}

    healthy = ctx_with(
        adapters=[adapter("Intel Centrino Ultimate-N 6300", "Native 802.11", "Up"),
                  adapter("Intel 82579LM Gigabit", "802.3", "Disconnected")],
        bluetooth=[{"name": "BCM20702", "status": "OK", "problem": "CM_PROB_NONE"}],
        camera=[{"name": "Integrated Camera", "status": "OK", "problem": "CM_PROB_NONE"}],
        audio=[{"name": "Speakers", "status": "OK", "problem": "CM_PROB_NONE"}],
    )
    good = peripherals.run(healthy)
    check("healthy machine scores 100", good.score == 100.0, str(good.score))
    check("healthy machine is ok", good.status == R.STATUS_OK, good.status)
    check("no major findings when nothing is broken",
          not [f for f in good.findings if f.severity == R.MAJOR],
          str([f.title for f in good.findings]))
    check("summary names the wifi link", "WiFi" in good.summary, good.summary)

    # a phantom is Windows remembering hardware that is gone, not a fault
    phantom = ctx_with(
        adapters=[adapter("Intel Centrino", "Native 802.11", "Up")],
        sdhost=[{"name": "SD Host Controller", "status": "Unknown",
                 "problem": "CM_PROB_PHANTOM"}],
    )
    p_result = peripherals.run(phantom)
    check("phantom device is not counted as present",
          (p_result.data.get("present") or {}).get("card_reader") == 0,
          str(p_result.data.get("present")))
    check("phantom device is not a defect", p_result.score == 100.0,
          str(p_result.score))

    # a real problem on a present device is scored
    broken = ctx_with(
        adapters=[adapter("Intel Centrino", "Native 802.11", "Up")],
        camera=[{"name": "Integrated Camera", "status": "Error",
                 "problem": "CM_PROB_FAILED_START"}],
    )
    b_result = peripherals.run(broken)
    check("broken camera is a major finding",
          any(f.severity == R.MAJOR and "Camera" in f.title
              for f in b_result.findings),
          str([f.title for f in b_result.findings]))
    check("broken camera carries a repair cost",
          any(f.cost_pkr for f in b_result.findings
              if f.severity == R.MAJOR),
          str([(f.title, f.cost_pkr) for f in b_result.findings]))
    check("broken camera reduces the score", b_result.score < 100.0,
          str(b_result.score))

    # a radio switched off is the classic "it's broken, bhai"
    off = ctx_with(adapters=[adapter("Intel Centrino", "Native 802.11", "Disabled")])
    o_result = peripherals.run(off)
    check("disabled wifi is a major finding",
          any(f.id == "peripherals.wifi_disabled" for f in o_result.findings),
          str([f.id for f in o_result.findings]))

    # absent hardware is reported, never scored
    bare = ctx_with(adapters=[adapter("Intel 82579LM", "802.3", "Up")])
    r_bare = peripherals.run(bare)
    check("missing bluetooth is informational only",
          any(f.id == "peripherals.no_bluetooth" and f.severity == R.INFO
              for f in r_bare.findings),
          str([(f.id, f.severity) for f in r_bare.findings]))
    check("missing hardware does not cost points", r_bare.score == 100.0,
          str(r_bare.score))

    # virtual adapters are not NICs
    virtual = ctx_with(
        adapters=[adapter("TAP-Windows Adapter V9", "802.3", "Disconnected"),
                  adapter("Intel 82579LM Gigabit", "802.3", "Up")],
    )
    v_result = peripherals.run(virtual)
    check("virtual adapters are ignored",
          (v_result.data.get("present") or {}).get("ethernet") == 1,
          str(v_result.data.get("present")))

    # --- which generation of radio is it
    check("802.11n is WiFi 4",
          peripherals.wifi_generation(["802.11a", "802.11b", "802.11g",
                                       "802.11n"]) == ("WiFi 4", "802.11n"))
    check("802.11ac is WiFi 5",
          peripherals.wifi_generation(["802.11ac"])[0] == "WiFi 5")
    check("the best amendment wins",
          peripherals.wifi_generation(["802.11n", "802.11ax"])[0] == "WiFi 6",
          str(peripherals.wifi_generation(["802.11n", "802.11ax"])))
    check("802.11be is WiFi 7",
          peripherals.wifi_generation(["802.11be"])[0] == "WiFi 7")
    check("802.11w is not a generation",
          peripherals.wifi_generation(["802.11w"])[0] == "",
          str(peripherals.wifi_generation(["802.11w"])))
    check("no standards means no claim",
          peripherals.wifi_generation([])[0] == "")

    check("bluetooth version from the driver wins",
          peripherals.bluetooth_version([{"name": "Whatever", "version": "5.2"}])
          == ("5.2", "driver"))
    check("bluetooth version falls back to the chip model",
          peripherals.bluetooth_version([{"name": "Intel(R) Wireless "
                                                  "Bluetooth(R) AX200"}])
          == ("5.1", "model"))
    check("an unknown chip gets no invented version",
          peripherals.bluetooth_version([{"name": "Mystery Radio"}]) == ("", ""))

    check("ethernet capability comes from the driver's list",
          peripherals.ethernet_speed({"speed_valid":
                                      "10 Mbps Full Duplex | 100 Mbps Full Duplex | "
                                      "1.0 Gbps Full Duplex"}) == ("1 GbE", 1000.0),
          str(peripherals.ethernet_speed({"speed_valid": "1.0 Gbps Full Duplex"})))
    check("2.5G is reported as 2.5 GbE",
          peripherals.ethernet_speed({"speed_valid": "2.5 Gbps Full Duplex"})[0]
          == "2.5 GbE")
    check("100 Mbps port is not called gigabit",
          peripherals.ethernet_speed({"speed_valid": "100 Mbps Full Duplex"})[0]
          == "100 Mbps")
    check("falls back to the controller name",
          peripherals.ethernet_speed({"description": "Realtek PCIe GbE Family "
                                                    "Controller"})[0] == "1 GbE")
    check("unknown port makes no claim",
          peripherals.ethernet_speed({"description": "Mystery NIC"})[0] == "")

    # and the generation reaches the check data the UI reads
    gen = ctx_with(adapters=[adapter("Intel Centrino", "Native 802.11", "Up")])
    gen.peripherals["standards"] = ["802.11n", "802.11ac"]
    g_result = peripherals.run(gen)
    check("generation is in the check data",
          g_result.data.get("wifi_generation") == "WiFi 5",
          str(g_result.data.get("wifi_generation")))
    check("generation reaches the device row",
          (g_result.data.get("devices") or {}).get("wifi", [{}])[0]
          .get("generation") == "WiFi 5",
          str(g_result.data.get("devices")))
    check("generation appears in the summary",
          "WiFi 5" in g_result.summary, g_result.summary)

    # no data at all must not read as a healthy machine
    nothing = peripherals.run(Context())
    check("no data is unavailable, not healthy",
          nothing.status == R.STATUS_UNAVAILABLE and not nothing.scored,
          f"{nothing.status} {nothing.score}")


def test_market_pricing() -> None:
    """The offer must come from what the machine is worth, not what is asked."""
    print("\nMarket pricing")
    from laptop_inspector.engine import market
    from laptop_inspector.scoring import negotiation

    def defect(cost: int, title: str = "Battery at 61%",
               blocking: bool = False) -> R.CheckResult:
        check = R.CheckResult(key="battery", label="Battery")
        finding = R.Finding(id="b", severity=R.MAJOR, title=title,
                            cost_pkr=cost, blocking=blocking)
        check.findings = [finding]
        return check

    # distinct titles: the negotiation deduplicates by title, so two "Battery"
    # defects would collapse into one line item and halve the repair total
    checks = [defect(15000, "Battery at 61%"),
              defect(8000, "Drive has reallocated sectors")]
    market_45 = {"value_pkr": 45000, "source": "manual", "note": "entered"}

    cheap_ask = negotiation.build(checks, 60000, market_45)
    dear_ask = negotiation.build(checks, 80000, market_45)

    # the bug Boss reported: same defects, higher ask, higher offer
    check("offer does not move when the asking price moves",
          cheap_ask.suggested_offer_pkr == dear_ask.suggested_offer_pkr,
          f"60k -> {cheap_ask.suggested_offer_pkr}, "
          f"80k -> {dear_ask.suggested_offer_pkr}")
    check("ceiling does not move either",
          cheap_ask.max_offer_pkr == dear_ask.max_offer_pkr,
          f"{cheap_ask.max_offer_pkr} vs {dear_ask.max_offer_pkr}")
    check("fair value is market minus repairs",
          cheap_ask.fair_value_pkr == 22000, str(cheap_ask.fair_value_pkr))
    check("offer is under fair value, not over",
          cheap_ask.suggested_offer_pkr < cheap_ask.fair_value_pkr,
          f"{cheap_ask.suggested_offer_pkr} vs {cheap_ask.fair_value_pkr}")
    check("ceiling never exceeds fair value",
          cheap_ask.max_offer_pkr <= cheap_ask.fair_value_pkr,
          str(cheap_ask.max_offer_pkr))
    check("basis is recorded as market",
          cheap_ask.price_basis == "market", cheap_ask.price_basis)

    # a price already below what it is worth is a good buy, not a haggle
    bargain = negotiation.build(checks, 18000, market_45)
    check("below fair value, pay what is asked",
          bargain.suggested_offer_pkr == 18000, str(bargain.suggested_offer_pkr))
    check("bargain advice says so", "Good buy" in bargain.advice, bargain.advice[:60])

    # a blocking defect is not a discount
    blocked = negotiation.build([defect(15000, "Drive is failing",
                                        blocking=True)], 60000, market_45)
    check("blocking defect walks away", blocked.walk_away)
    check("blocking defect offers nothing", blocked.suggested_offer_pkr == 0,
          str(blocked.suggested_offer_pkr))

    # without a market value the old maths runs and says so
    blind = negotiation.build(checks, 60000, None)
    check("no market falls back to asking", blind.price_basis == "asking",
          blind.price_basis)
    check("the fallback admits the flaw",
          "market price" in blind.advice.lower(), blind.advice[:120])

    # an upgrade is not a repair: it must not shrink the offer
    upgraded = R.CheckResult(key="specs", label="Specs")
    upgraded.findings = [R.Finding(id="h", severity=R.WARN,
                                   title="Mechanical drive fitted",
                                   cost_pkr=8000, upgrade=True)]
    with_upgrade = negotiation.build(checks + [upgraded], 60000, market_45)
    check("an SSD upgrade is not counted as a repair",
          with_upgrade.total_repair_pkr == cheap_ask.total_repair_pkr,
          f"{with_upgrade.total_repair_pkr} vs {cheap_ask.total_repair_pkr}")
    check("the upgrade is still reported",
          len(with_upgrade.upgrades) == 1, str(with_upgrade.upgrades))
    check("the upgrade is named in the advice",
          "optional upgrade" in with_upgrade.advice.lower(),
          with_upgrade.advice[-120:])

    # repairs that eat the machine are a write-off, not a small offer
    wreck = negotiation.build([defect(42500, "Everything is broken")], 60000,
                              market_45)
    check("repairs over 60% of value is a write-off", wreck.walk_away)
    check("a write-off has no offer to make",
          wreck.suggested_offer_pkr == 0, str(wreck.suggested_offer_pkr))
    check("the write-off says why",
          "of its value" in wreck.walk_away_reason, wreck.walk_away_reason)

    # just under the line it is still a hard negotiation
    near = negotiation.build([defect(20000, "Big but fixable")], 60000, market_45)
    check("below the write-off line an offer still exists",
          near.suggested_offer_pkr > 0, str(near.suggested_offer_pkr))

    # --- the lookup itself
    original = market.search
    calls = []
    try:
        market.search = lambda model, timeout=12.0: (
            calls.append(model) or market.MarketPrice(value_pkr=41000,
                                                      source="search"))

        check("manual entry beats the web",
              market.resolve("Test Model X", manual_pkr=50000,
                             allow_search=True).value_pkr == 50000)
        check("manual entry is remembered",
              market.remembered("Test Model X") == 50000,
              str(market.remembered("Test Model X")))

        market.remember("Remembered Model", 33000)
        before = len(calls)
        result = market.resolve("Remembered Model", allow_search=True)
        check("a remembered price is used without searching",
              result.value_pkr == 33000 and result.source == "stored",
              f"{result.value_pkr} {result.source}")
        check("no search happened for a remembered model",
              len(calls) == before, str(calls))

        check("search is used when nothing is known",
              market.resolve("Fresh Model Y", allow_search=True).value_pkr == 41000)

        market.search = lambda model, timeout=12.0: market.MarketPrice(
            note="nothing found")
        miss = market.resolve("Missing Model Z", allow_search=True)
        check("a miss reports unknown", miss.value_pkr is None)
        check("a miss is not remembered",
              market.remembered("Missing Model Z") is None)
    finally:
        market.search = original

    # --- price parsing
    check("PKR prefix parsed", market.prices_in("Lenovo W520 Rs 29,000") == [29000])
    check("PKR suffix parsed", market.prices_in("35,000 PKR for it") == [35000])
    check("a year is not a price", market.prices_in("built in 2011") == [])
    check("absurd values rejected", market.prices_in("Rs 9") == [])


def test_headless_isolation() -> None:
    """The WinPE build depends on the engine importing no GUI toolkit."""
    print("\nHeadless / WinPE isolation")
    import pathlib

    import ast

    root = pathlib.Path(__file__).parent / "laptop_inspector"
    offenders = []
    for path in list(root.rglob("*.py")):
        if "ui" in path.parts:
            continue
        # Parse rather than grep: cli.py's docstring says "imports nothing from
        # PySide6", and a substring search flags the promise as the violation.
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            for name in names:
                if name.startswith(("PySide6", "PyQt", "tkinter")):
                    offenders.append(f"{path.relative_to(root)}: {name}")

    check("engine, scoring and report import no Qt",
          not offenders, "; ".join(offenders))

    # the CLI is the WinPE entry point and must stay importable without a display
    from laptop_inspector import cli
    check("cli imports without Qt", hasattr(cli, "main"))

    spec = (pathlib.Path(__file__).parent / "build_pe.spec").read_text(encoding="utf-8")
    check("the PE spec excludes Qt", "PySide6" in spec and "excludes" in spec)
    check("the PE spec builds a console app", "console=True" in spec)


def main() -> int:
    print("Used Laptop Inspector - self test")
    test_smart()
    test_nvme()
    test_msdm()
    test_identify()
    test_util()
    test_scoring()
    test_negotiation()
    test_models()
    test_storage_evaluate()
    test_interactive()
    test_stress_rescore()
    test_port_layout()
    test_keyboard_sides()
    test_webimages()
    test_gpu_adapter_choice()
    test_peripherals()
    test_market_pricing()
    test_headless_isolation()
    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
