"""Thermal behaviour and throttling.

The verdict comes from two signals that have to agree:
  * actual clock sag under sustained all-core load (PDH), and
  * delivered throughput decay from the load workers.

A clogged heatsink shows up as a clock that starts high and cannot hold, plus
falling throughput. A healthy machine holds its turbo or settles just under it.

Scoring is separated from collection so the same rules can be applied to a run
the buyer started by hand from the stress lab, not just the one the scan did.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .. import result as R
from .. import loadgen
from ..context import Context, cost_of

KEY = "thermal"
LABEL = "Thermals & throttling"


class ProbeView:
    """A probe result rebuilt from its serialised form.

    Only the derived numbers matter to the scorer, so re-running the rules after
    an interactive test does not need the original sample list.
    """

    def __init__(self, data: Dict[str, Any]) -> None:
        self.nominal_mhz = int(data.get("nominal_mhz") or 0)
        self.peak_mhz = data.get("peak_mhz")
        self.sustained_mhz = data.get("sustained_mhz")
        self.throughput_decay = data.get("throughput_decay")
        self.mean_util = data.get("mean_util")
        self.workers = int(data.get("workers") or 0)
        self.degraded = bool(data.get("degraded"))
        self.error = data.get("error")
        self.loaded = bool(data.get("samples"))


def _ratio_score(ratio: float) -> float:
    if ratio >= 0.90:
        return 100.0
    if ratio >= 0.85:
        return 92.0
    if ratio >= 0.78:
        return 80.0
    if ratio >= 0.70:
        return 62.0
    if ratio >= 0.60:
        return 40.0
    return 18.0


def _evaluate(probe, temps: List[float], data: Dict[str, Any]) -> R.CheckResult:
    check = R.CheckResult(key=KEY, label=LABEL)
    findings: List[R.Finding] = []
    check.data = data

    if not probe.loaded:
        check.status = R.STATUS_UNAVAILABLE
        check.summary = "Load test produced no samples"
        check.error = probe.error or "no clock samples"
        return check

    sag = None
    if probe.peak_mhz and probe.sustained_mhz:
        sag = probe.sustained_mhz / probe.peak_mhz
    decay = probe.throughput_decay
    util = probe.mean_util

    data["sag_ratio"] = round(sag, 3) if sag else None

    # ---- did the load actually apply?
    if util is not None and util < 45:
        findings.append(R.Finding(
            id="thermal.low_load", severity=R.INFO,
            title=f"Load test only reached {util:.0f}% CPU",
            detail=("Something else was running, or the machine is power-limited on "
                    "battery. Throttle figures are unreliable."),
            evidence={"mean_util_pct": round(util, 1),
                      "workers": probe.workers}))
        check.status = R.STATUS_WARN
        check.summary = f"Load only {util:.0f}% - inconclusive"
        check.findings = findings
        check.score = 60.0
        return check

    if probe.degraded and probe.error:
        findings.append(R.Finding(
            id="thermal.degraded", severity=R.INFO,
            title="Load test ran in degraded mode",
            detail=probe.error,
            evidence={"error": probe.error}))

    # ---- sag
    if sag is not None:
        if sag < 0.65:
            findings.append(R.Finding(
                id="thermal.throttle_critical", severity=R.CRITICAL,
                title=f"Severe throttling: clock falls to {sag * 100:.0f}% of peak",
                detail=(f"Peaks at {probe.peak_mhz:.0f} MHz, settles at "
                        f"{probe.sustained_mhz:.0f} MHz under sustained load. "
                        "That is the signature of a clogged heatsink, dried thermal "
                        "paste, or a dead fan."),
                evidence={"peak_mhz": round(probe.peak_mhz),
                          "sustained_mhz": round(probe.sustained_mhz),
                          "nominal_mhz": probe.nominal_mhz,
                          "sag_ratio": round(sag, 3),
                          "mean_util_pct": round(util or 0, 1)},
                cost_pkr=cost_of("thermal_service", 3500)
                          + cost_of("fan_replacement", 6000),
                cost_note="Full teardown, heatsink clean, repaste, fan if seized."))
        elif sag < 0.78:
            findings.append(R.Finding(
                id="thermal.throttle_major", severity=R.MAJOR,
                title=f"Throttling under load: clock settles at {sag * 100:.0f}% of peak",
                detail=(f"{probe.peak_mhz:.0f} MHz peak, "
                        f"{probe.sustained_mhz:.0f} MHz sustained. Loses a fifth of "
                        "its performance within a minute - felt as stutter in sustained work."),
                evidence={"peak_mhz": round(probe.peak_mhz),
                          "sustained_mhz": round(probe.sustained_mhz),
                          "sag_ratio": round(sag, 3)},
                cost_pkr=cost_of("thermal_service", 3500),
                cost_note="Heatsink clean and repaste."))
        elif sag < 0.85:
            findings.append(R.Finding(
                id="thermal.throttle_mild", severity=R.WARN,
                title=f"Mild throttling: clock settles at {sag * 100:.0f}% of peak",
                detail="Within normal range for a thin laptop, worth a repaste on a workstation.",
                evidence={"peak_mhz": round(probe.peak_mhz),
                          "sustained_mhz": round(probe.sustained_mhz),
                          "sag_ratio": round(sag, 3)},
                cost_pkr=int(cost_of("thermal_service", 3500) * 0.6),
                cost_note="Optional service."))

    # ---- throughput decay
    if decay is not None and decay < 0.80:
        sev = R.MAJOR if decay < 0.70 else R.WARN
        findings.append(R.Finding(
            id="thermal.throughput_decay", severity=sev,
            title=f"Delivered performance fell {100 - decay * 100:.0f}% during the test",
            detail=("The workers completed steadily less work each second. Even if the "
                    "clock looks respectable, the machine is not delivering it."),
            evidence={"throughput_decay": round(decay, 3)},
            cost_pkr=0 if sev == R.WARN else cost_of("thermal_service", 3500),
            cost_note="" if sev == R.WARN else "Heatsink service."))

    # ---- temperature, if the platform exposes it
    temps = [t for t in (temps or []) if isinstance(t, (int, float))]
    if temps:
        peak = max(temps)
        data["peak_temp_c"] = peak
        if peak >= 95:
            findings.append(R.Finding(
                id="thermal.temp_critical", severity=R.CRITICAL,
                title=f"CPU reported {peak:.0f} C under load",
                detail="At or near the shutdown threshold. Cooling is not working.",
                evidence={"peak_temp_c": peak},
                cost_pkr=cost_of("thermal_service", 3500)
                          + cost_of("fan_replacement", 6000),
                cost_note="Heatsink clean, repaste, fan."))
        elif peak >= 88:
            findings.append(R.Finding(
                id="thermal.temp_high", severity=R.MAJOR,
                title=f"CPU reported {peak:.0f} C under load",
                evidence={"peak_temp_c": peak},
                cost_pkr=cost_of("thermal_service", 3500),
                cost_note="Heatsink clean and repaste."))
    else:
        findings.append(R.Finding(
            id="thermal.no_sensor", severity=R.INFO,
            title="No ACPI thermal zone exposed",
            detail=("This platform does not report temperature through WMI, so the "
                    "verdict rests on clock sag and delivered throughput only."),
            evidence={}))

    # ---- score
    scores = []
    if sag is not None:
        scores.append(_ratio_score(sag))
    if decay is not None:
        scores.append(_ratio_score(decay))
    check.score = min(scores) if scores else 70.0
    if temps:
        peak = max(temps)
        if peak >= 95:
            check.score = min(check.score, 20)
        elif peak >= 88:
            check.score = min(check.score, 55)

    check.findings = findings
    has_critical = any(f.severity == R.CRITICAL for f in findings)
    has_warn = any(f.severity in (R.WARN, R.MAJOR) for f in findings)
    check.status = (R.STATUS_FAIL if has_critical
                    else R.STATUS_WARN if has_warn else R.STATUS_OK)

    bits = []
    if probe.peak_mhz:
        bits.append(f"peak {probe.peak_mhz:.0f} MHz")
    if probe.sustained_mhz:
        bits.append(f"sustained {probe.sustained_mhz:.0f} MHz")
    if sag is not None:
        bits.append(f"{sag * 100:.0f}% of peak")
    if temps:
        bits.append(f"{max(temps):.0f} C")
    check.summary = ", ".join(bits) or "Load test complete"
    return check


def from_probe(data: Dict[str, Any]) -> R.CheckResult:
    """Rescore a probe that was run outside the scan (the stress lab)."""
    payload = dict(data or {})
    return _evaluate(ProbeView(payload), payload.get("temps_c") or [], payload)


def run(ctx: Context) -> R.CheckResult:
    check = R.CheckResult(key=KEY, label=LABEL)

    if ctx.options.skip_thermal:
        check.status = R.STATUS_UNAVAILABLE
        check.score = 0.0
        check.summary = "Skipped by request"
        return check

    duration = ctx.options.effective_thermal()
    ctx.progress(KEY, 0.02, f"Loading all cores for {int(duration)} s")

    run_result = loadgen.run_thermal_probe(
        duration=duration,
        workers=ctx.options.cpu_workers,
        idle_seconds=3.0,
        progress=lambda f: ctx.progress(KEY, 0.05 + f * 0.9,
                                        f"Under load {int(f * 100)}%"),
        temps_fn=lambda: ctx.temps,
    )
    data = run_result.to_dict()
    data["idle_temps_c"] = ctx.temps[:6]
    return _evaluate(run_result, ctx.temps, data)
