"""GPU sanity: adapter state, driver crash history, and a real load test.

The event log is the highest-value part. A machine whose display driver has
recovered from ten TDRs will look perfectly fine on the desktop and fail the
moment the buyer asks it to do something.
"""

from __future__ import annotations

from typing import Any, Dict, List

from .. import result as R
from .. import d3d11, util
from ..context import Context, cost_of

KEY = "gpu"
LABEL = "GPU sanity"


STRESS_FINDING_IDS = {"gpu.device_removed", "gpu.stress_inconclusive",
                      "gpu.stress_unavailable", "gpu.low_throughput",
                      "gpu.stress_crashed"}


def _stress_findings(stress: Dict[str, Any]):
    """Findings and score penalty for one load-test result.

    Shared by the scan and by a load test the buyer ran by hand, so both are
    judged by exactly the same rules.
    """
    findings: List[R.Finding] = []
    penalty = 0

    if stress.get("device_removed"):
        findings.append(R.Finding(
            id="gpu.device_removed", severity=R.CRITICAL,
            title="Display driver reset during the load test",
            detail=("The GPU was pushed and the driver fell over. This is the same "
                    "failure the buyer would hit in a game or a CAD session."),
            evidence={"hresult": stress.get("hresult"),
                      "seconds": stress.get("seconds")},
            cost_pkr=cost_of("gpu_reflow", 12000),
            cost_note="GPU reflow or board replacement.",
            blocking=True))
        penalty += 60
    elif stress.get("crashed"):
        findings.append(R.Finding(
            id="gpu.stress_crashed", severity=R.CRITICAL,
            title="GPU stress test took the process down",
            detail=(f"The stress worker died with exit code {stress.get('exitcode')} "
                    "without reporting. A driver that kills its host process is a "
                    "driver that will kill the buyer's session."),
            evidence={"exitcode": stress.get("exitcode")},
            cost_pkr=cost_of("gpu_reflow", 12000),
            cost_note="Board-level GPU fault.",
            blocking=True))
        penalty += 50
    elif stress.get("inconclusive"):
        findings.append(R.Finding(
            id="gpu.stress_inconclusive", severity=R.INFO,
            title="GPU load test was inconclusive",
            detail=(f"{stress.get('error')}. The probe could not drive the adapter, "
                    "so this says nothing about the hardware either way."),
            evidence={"error": stress.get("error"),
                      "hresult": stress.get("hresult")}))
    elif not stress.get("available") and not stress.get("skipped"):
        findings.append(R.Finding(
            id="gpu.stress_unavailable", severity=R.INFO,
            title="GPU load test could not run",
            detail=stress.get("error") or "D3D11 device creation failed.",
            evidence={"error": stress.get("error")}))
    elif stress.get("available"):
        # Shaded frames per second. A software device manages a few dozen at
        # 720p where hardware manages hundreds or thousands.
        rate = stress.get("frames_per_sec") or 0
        mode = stress.get("mode") or "?"
        if rate and rate < 100:
            findings.append(R.Finding(
                id="gpu.low_throughput", severity=R.WARN,
                title=f"GPU rendered only {rate:,} frames/sec at 720p",
                detail=("Far below what a hardware device manages, which usually "
                        "means the adapter is falling back to software rendering."),
                evidence={"frames_per_sec": rate, "mode": mode,
                          "adapter": stress.get("adapter"),
                          "feature_level": stress.get("feature_level")}))
            penalty += 10
    return findings, penalty


def apply_stress(check: R.CheckResult, stress: Dict[str, Any]) -> R.CheckResult:
    """Replace the load-test result on an existing check and rescore it.

    The stress test is the last scoring step in `run`, so the base score is the
    current one plus whatever the previous stress result took off.
    """
    old_penalty = int((check.data or {}).get("stress_penalty") or 0)
    base = min(100.0, float(check.score) + old_penalty)

    findings = [f for f in check.findings if f.id not in STRESS_FINDING_IDS]
    new_findings, penalty = _stress_findings(stress or {})
    findings.extend(new_findings)

    check.findings = findings
    check.data["stress"] = stress
    check.data["stress_penalty"] = penalty
    check.score = max(0.0, base - penalty)

    has_critical = any(f.severity == R.CRITICAL for f in findings)
    has_warn = any(f.severity in (R.WARN, R.MAJOR) for f in findings)
    check.status = (R.STATUS_FAIL if has_critical
                    else R.STATUS_WARN if has_warn else R.STATUS_OK)
    return check


def run(ctx: Context) -> R.CheckResult:
    check = R.CheckResult(key=KEY, label=LABEL)
    findings: List[R.Finding] = []

    adapters: List[Dict[str, Any]] = []
    for g in util.as_list(ctx.facts.get("gpus")):
        name = util.short_gpu(g.get("name") or "")
        adapters.append({
            "name": name,
            "kind": util.classify_gpu(name),
            "vram_mb": int(g["vram"] / (1024 * 1024)) if g.get("vram") else None,
            "driver": g.get("driver_ver"),
            "driver_date": util.fmt_date(g.get("driver_date")),
            "error_code": g.get("error_code"),
            "status": g.get("status"),
            "resolution": (f"{g.get('width')}x{g.get('height')}"
                           if g.get("width") else ""),
            "refresh_hz": g.get("refresh"),
        })

    pnp = []
    for d in util.as_list(ctx.facts.get("pnp_display")):
        problem = str(d.get("problem") or "")
        pnp.append({
            "name": d.get("name"),
            "status": d.get("status"),
            "problem": problem,
            # A phantom device is one Windows remembers but cannot see on the bus.
            # That is the disabled-dGPU signature, and it belongs to the dGPU
            # check - not here, where it would double-count the same defect.
            "phantom": problem == "CM_PROB_PHANTOM",
            "instance": d.get("instance"),
        })
    live_pnp = [d for d in pnp if not d["phantom"]]

    score = 100.0
    real = [a for a in adapters if a["kind"] != "virtual"]

    if not real:
        check.status = R.STATUS_UNAVAILABLE
        check.score = 0.0
        check.summary = "No display adapter enumerated"
        check.findings = [R.Finding(
            id="gpu.none", severity=R.CRITICAL,
            title="No display adapter found",
            detail="Windows sees no working graphics device at all.",
            evidence={"adapters": adapters})]
        check.status = R.STATUS_FAIL
        return check

    # ---- adapter error states
    for a in real:
        code = a.get("error_code")
        if isinstance(code, int) and code != 0:
            findings.append(R.Finding(
                id=f"gpu.error_{a['name'][:20]}", severity=R.MAJOR,
                title=f"{a['name']} reports a device problem (code {code})",
                detail="The adapter is present but not working correctly.",
                evidence={"adapter": a["name"], "config_manager_error": code},
                cost_pkr=cost_of("gpu_reflow", 12000),
                cost_note="Board-level GPU repair, if it is repairable at all."))
            score -= 35
        if a.get("driver_date"):
            try:
                year = int(a["driver_date"][:4])
                if year and year <= 2019:
                    findings.append(R.Finding(
                        id=f"gpu.old_driver_{a['name'][:20]}", severity=R.INFO,
                        title=f"{a['name']} driver is from {year}",
                        detail="Old drivers hide known stability fixes. Not a defect.",
                        evidence={"driver_date": a["driver_date"],
                                  "driver": a.get("driver")}))
            except ValueError:
                pass

    for d in live_pnp:
        status = (d.get("status") or "").lower()
        if status in ("error", "degraded") and d.get("name"):
            if util.classify_gpu(d["name"]) == "discrete":
                findings.append(R.Finding(
                    id="gpu.pnp_error", severity=R.MAJOR,
                    title=f"Discrete GPU is present but not working: {d['name']}",
                    detail=f"PnP status '{d.get('status')}', problem code {d.get('problem')}.",
                    evidence=d,
                    cost_pkr=cost_of("gpu_reflow", 12000),
                    cost_note="Board-level repair."))
                score -= 30

    phantoms = [d for d in pnp
                if d["phantom"] and util.classify_gpu(d["name"] or "") == "discrete"]
    if phantoms:
        findings.append(R.Finding(
            id="gpu.phantom_registered", severity=R.INFO,
            title=f"{phantoms[0]['name']} is registered but not on the bus",
            detail=("Windows carries a device record from when this adapter was last "
                    "working. The discrete GPU check interprets what that means."),
            evidence={"devices": [p["name"] for p in phantoms]}))

    # ---- TDR history
    events = ctx.events or {}
    tdr_count = int(events.get("tdr_count") or 0)
    ev_list = events.get("events") or []
    shutdowns = int(events.get("unexpected_shutdowns") or 0)

    if tdr_count >= 10:
        findings.append(R.Finding(
            id="gpu.tdr_critical", severity=R.CRITICAL,
            title=f"{tdr_count} display driver resets in the last 180 days",
            detail=("The GPU or its driver is crashing repeatedly. Expect freezes and "
                    "black screens under load. This is the failure that a seller hides "
                    "by reinstalling Windows."),
            evidence={"tdr_count": tdr_count,
                      "recent": [e.get("time") for e in ev_list[:5]]},
            cost_pkr=cost_of("gpu_reflow", 12000),
            cost_note="GPU reflow or board replacement.",
            blocking=True))
        score -= 55
    elif tdr_count >= 3:
        findings.append(R.Finding(
            id="gpu.tdr_major", severity=R.MAJOR,
            title=f"{tdr_count} display driver resets in the last 180 days",
            detail="Enough to be a pattern rather than a one-off.",
            evidence={"tdr_count": tdr_count,
                      "recent": [e.get("time") for e in ev_list[:5]]},
            cost_pkr=cost_of("gpu_reflow", 12000),
            cost_note="Budget for GPU repair."))
        score -= 30
    elif tdr_count >= 1:
        findings.append(R.Finding(
            id="gpu.tdr_warn", severity=R.WARN,
            title=f"{tdr_count} display driver reset(s) in the last 180 days",
            detail="Could be a driver bug rather than hardware. Watch for repeats.",
            evidence={"tdr_count": tdr_count,
                      "recent": [e.get("time") for e in ev_list[:5]]}))
        score -= 12

    # ---- load test
    stress: Dict[str, Any] = {}
    if ctx.options.skip_gpu_load:
        stress = {"skipped": True}
    else:
        ctx.progress(KEY, 0.3, "Stressing the GPU")
        stress = d3d11.stress_isolated(ctx.options.effective_gpu())
        ctx.progress(KEY, 0.95, "GPU load complete")

    stress_findings, stress_penalty = _stress_findings(stress)
    findings.extend(stress_findings)
    score -= stress_penalty

    check.data = {
        "adapters": adapters,
        "pnp_display": pnp,
        "pnp_phantom": [p["name"] for p in phantoms],
        "tdr_count": tdr_count,
        "tdr_events": ev_list[:10],
        "unexpected_shutdowns": shutdowns,
        "stress": stress,
        "stress_penalty": stress_penalty,
        "discrete_count": len([a for a in real if a["kind"] == "discrete"]),
    }
    check.findings = findings
    check.score = max(0.0, min(100.0, score))
    has_critical = any(f.severity == R.CRITICAL for f in findings)
    has_warn = any(f.severity in (R.WARN, R.MAJOR) for f in findings)
    check.status = (R.STATUS_FAIL if has_critical
                    else R.STATUS_WARN if has_warn else R.STATUS_OK)
    names = ", ".join(a["name"] for a in real[:3])
    tdr_note = f" / {tdr_count} TDR(s)" if tdr_count else " / no TDRs"
    stressed = (stress or {}).get("adapter")
    # Name the adapter the load actually ran on: on Optimus the default device
    # is the iGPU, and stressing the wrong chip is worse than not stressing at all.
    if stressed and stressed not in names:
        names = f"{names} (load on {stressed})"
    check.summary = f"{names}{tdr_note}"
    return check
