"""Interactive tests: screen, keyboard, ports.

These cannot be measured by an API. A stuck pixel is only visible to the buyer;
a dead key is only dead when you press it. So this check records what the buyer
observed, and converts it into the same kind of finding the automatic checks
produce - with a severity and a repair cost, so it lands in the counter-offer.

It is deliberately optional. If the buyer skips it, the check reports
`unavailable` and drops out of the weighted score rather than pretending the
hardware passed.
"""

from __future__ import annotations

from typing import Any, Dict, List

from .. import result as R
from ..context import cost_of

KEY = "interactive"
LABEL = "Screen, keyboard & ports"


def _screen(results: Dict[str, Any], findings: List[R.Finding], cost: List[int]) -> int:
    screen = results.get("screen") or {}
    if not screen.get("run"):
        return 0
    issues = [str(i) for i in (screen.get("issues") or [])]
    if not issues:
        findings.append(R.Finding(
            id="interactive.screen_ok", severity=R.INFO,
            title="Screen: no defects reported",
            detail="Solid colours, gradients and the checkerboard were shown and "
                   "nothing was flagged.",
            evidence={"resolution": screen.get("resolution") or "?",
                      "seconds": screen.get("seconds")}))
        return 0

    severity = R.MAJOR if any(
        word in " ".join(issues).lower()
        for word in ("crack", "line", "bleed", "uniform", "backlight")) else R.WARN
    findings.append(R.Finding(
        id="interactive.screen_issues", severity=severity,
        title=f"Screen: {', '.join(issues)}",
        detail=("Reported during the fullscreen pixel test. Stuck pixels and "
                "backlight bleed are permanent; a panel replacement is the only fix."),
        evidence={"issues": "; ".join(issues),
                  "resolution": screen.get("resolution") or "?"},
        cost_pkr=cost_of("screen_panel_15", 18000),
        cost_note="Panel replacement, parts and labour."))
    cost.append(cost_of("screen_panel_15", 18000))
    return 2


def _keyboard(results: Dict[str, Any], findings: List[R.Finding], cost: List[int]) -> int:
    keyboard = results.get("keyboard") or {}
    if not keyboard.get("run"):
        return 0
    missing = [str(k) for k in (keyboard.get("missing") or [])]
    pressed = keyboard.get("pressed") or []
    if not missing:
        findings.append(R.Finding(
            id="interactive.keyboard_ok", severity=R.INFO,
            title=f"Keyboard: all {len(pressed)} keys registered",
            evidence={"keys_pressed": len(pressed)}))
        return 0

    severity = R.MAJOR if len(missing) > 6 else R.WARN
    findings.append(R.Finding(
        id="interactive.keyboard_dead", severity=severity,
        title=f"Keyboard: {len(missing)} key(s) did not register",
        detail=("Keys pressed during the matrix test produced no event. A dead key "
                "is usually the membrane or the ribbon connector, not the keycap."),
        evidence={"missing": ", ".join(missing[:12]),
                  "keys_pressed": len(pressed)},
        cost_pkr=cost_of("keyboard", 5000),
        cost_note="Keyboard assembly replacement."))
    cost.append(cost_of("keyboard", 5000))
    return 2 if severity == R.MAJOR else 1


def _ports(results: Dict[str, Any], findings: List[R.Finding], cost: List[int]) -> int:
    ports = results.get("ports") or {}
    if not ports.get("run"):
        return 0
    penalty = 0

    failed = [str(p) for p in (ports.get("failed") or [])]
    tested = int(ports.get("ports_tested") or 0)
    if failed:
        findings.append(R.Finding(
            id="interactive.usb_ports", severity=R.MAJOR,
            title=f"USB: {len(failed)} port(s) did not respond",
            detail=("A device was plugged into these ports and Windows never saw it. "
                    "Often the port's power switch or a cracked solder joint."),
            evidence={"failed_ports": ", ".join(failed[:6]),
                      "ports_tested": tested},
            cost_pkr=cost_of("dc_jack_repair", 3500),
            cost_note="Port / daughterboard repair."))
        cost.append(cost_of("dc_jack_repair", 3500))
        penalty += 2
    elif tested:
        findings.append(R.Finding(
            id="interactive.usb_ok", severity=R.INFO,
            title=f"USB: {tested} port(s) responded",
            evidence={"ports_tested": tested}))

    audio = ports.get("audio") or {}
    if audio.get("run"):
        dead = [side for side in ("left", "right") if not audio.get(side)]
        if dead:
            findings.append(R.Finding(
                id="interactive.audio_channel", severity=R.MAJOR,
                title=f"Audio: {' and '.join(dead)} channel silent",
                detail=("A tone was played in each channel separately. One channel "
                        "producing nothing points at the jack, the speaker, or the "
                        "codec - not the driver."),
                evidence={"silent_channels": ", ".join(dead)},
                cost_pkr=2500,
                cost_note="Jack or speaker repair."))
            cost.append(2500)
            penalty += 2
        else:
            findings.append(R.Finding(
                id="interactive.audio_ok", severity=R.INFO,
                title="Audio: both channels produced sound",
                evidence={"left": True, "right": True}))

    return penalty


def build_check(results: Dict[str, Any]) -> R.CheckResult:
    """Turn a session of interactive test results into a scored check."""
    check = R.CheckResult(key=KEY, label=LABEL)
    findings: List[R.Finding] = []
    costs: List[int] = []

    ran = [name for name in ("screen", "keyboard", "ports")
           if (results.get(name) or {}).get("run")]

    penalty = 0
    _screen(results, findings, costs)
    _keyboard(results, findings, costs)
    _ports(results, findings, costs)

    check.data = {
        "results": results,
        "tests_run": ran,
    }
    check.findings = findings

    if not ran:
        check.status = R.STATUS_UNAVAILABLE
        check.score = 0.0
        check.summary = "Not run"
        check.data["skipped"] = True
        return check

    for finding in findings:
        if finding.severity == R.MAJOR:
            penalty += 22
        elif finding.severity == R.WARN:
            penalty += 12
    check.score = max(0.0, 100.0 - penalty)

    issues = [f for f in findings if f.severity in (R.MAJOR, R.WARN)]
    check.status = R.STATUS_WARN if issues else R.STATUS_OK
    check.summary = (f"{len(ran)} test(s) run, {len(issues)} issue(s)"
                     if issues else f"{len(ran)} test(s) run, all clear")
    return check
