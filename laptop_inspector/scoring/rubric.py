"""Scoring rubric.

Weights are here so they can be tuned in one place. They sum to 100, but the
score is always renormalised over the checks that actually ran, so a machine
where the battery cannot be read is not punished for a check that could not
execute - it is judged on the evidence that exists.

The score alone never decides the verdict. A machine can score 70 and still be a
walk-away (a drive failing right now), or score 88 and still need negotiating
(one worn battery). So:

    verdict = f(score, blocking findings, major findings)
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from ..engine import result as R

WEIGHTS: Dict[str, float] = {
    "storage": 25.0,
    "battery": 20.0,
    "specs": 20.0,
    "thermal": 15.0,
    "gpu": 10.0,
    "dgpu": 10.0,
    # v2: only counts when the buyer actually ran the interactive tests.
    # Skipped -> unavailable -> drops out of the denominator.
    "interactive": 12.0,
    # Presence and driver state of the radios and peripherals. Absent devices are
    # never scored, so this only costs points when something is there and broken.
    "peripherals": 8.0,
}

CHECK_ORDER: List[str] = ["specs", "battery", "storage", "thermal", "gpu",
                          "dgpu", "peripherals", "interactive"]

BUY_THRESHOLD = 80.0
NEGOTIATE_THRESHOLD = 55.0


def weight_of(key: str) -> float:
    return WEIGHTS.get(key, 0.0)


def apply_weights(checks: List[R.CheckResult]) -> List[R.CheckResult]:
    for check in checks:
        check.weight = weight_of(check.key)
    return checks


def weighted_score(checks: List[R.CheckResult]) -> Tuple[float, List[Dict[str, Any]]]:
    """Renormalise over the checks that produced a usable score."""
    breakdown: List[Dict[str, Any]] = []
    total_weight = 0.0
    accum = 0.0
    for check in checks:
        effective = check.weight if check.scored else 0.0
        total_weight += effective
        accum += check.score * effective
        breakdown.append({
            "key": check.key,
            "label": check.label,
            "score": round(check.score, 1),
            "weight": check.weight,
            "effective_weight": round(effective, 1),
            "status": check.status,
        })
    score = accum / total_weight if total_weight else 0.0
    for item in breakdown:
        item["contribution"] = round(
            item["score"] * item["effective_weight"] / total_weight, 2
        ) if total_weight else 0.0
    return round(score, 1), breakdown


def verdict_for(score: float, checks: List[R.CheckResult]) -> Tuple[str, List[str]]:
    blockers: List[str] = []
    majors: List[str] = []
    for check in checks:
        for f in check.findings:
            if f.blocking:
                blockers.append(f.title)
            elif f.severity == R.MAJOR:
                majors.append(f.title)

    reasons: List[str] = []
    if blockers:
        reasons.append(f"{len(blockers)} blocking defect(s): " + "; ".join(blockers[:3]))
        return "WALK AWAY", reasons
    if score < NEGOTIATE_THRESHOLD:
        reasons.append(f"Score {score:.0f}/100 - too much wrong with it")
        return "WALK AWAY", reasons
    if score >= BUY_THRESHOLD and not majors:
        reasons.append(f"Score {score:.0f}/100 with no major defects")
        return "BUY", reasons
    if score >= BUY_THRESHOLD and majors:
        reasons.append(f"Score {score:.0f}/100 but {len(majors)} major defect(s): "
                       + "; ".join(majors[:2]))
        return "NEGOTIATE", reasons
    reasons.append(f"Score {score:.0f}/100 - worth buying at the right price")
    if majors:
        reasons.append(f"{len(majors)} major defect(s): " + "; ".join(majors[:2]))
    return "NEGOTIATE", reasons


def verdict_colour(verdict: str) -> str:
    return {"BUY": "#1f9d55", "NEGOTIATE": "#c98a00",
            "WALK AWAY": "#c62828"}.get(verdict, "#555555")
