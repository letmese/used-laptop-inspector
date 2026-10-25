"""The missing-dGPU check.

The scam: the machine shipped with a Quadro or GeForce, the card or its power
rail failed, and the seller switched it off in BIOS. Windows enumerates only the
integrated GPU, every diagnostic tool agrees there is one GPU, and the buyer is
told "that model never came with one".

Model database gives the expectation. Registry and DriverStore traces give the
history. When the expectation and the traces both say a dGPU should be there and
nothing enumerates, that is not a mystery - it is a repair the buyer is about to
inherit.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from .. import result as R
from .. import remnants, util
from ..context import Context, cost_of, load_json

KEY = "dgpu"
LABEL = "Discrete GPU presence"


def _haystack(ctx: Context) -> str:
    f = ctx.facts
    parts = [
        (f.get("system") or {}).get("model"),
        (f.get("system") or {}).get("system_family"),
        (f.get("system") or {}).get("sku"),
        (f.get("product") or {}).get("version"),
        (f.get("product") or {}).get("name"),
    ]
    return " ".join(str(p) for p in parts if p).strip()


def match_model(ctx: Context) -> Optional[Dict[str, Any]]:
    hay = _haystack(ctx)
    if not hay:
        return None
    db = load_json("models.json")
    best = None
    best_len = 0
    for entry in db.get("models") or []:
        for pattern in entry.get("match") or []:
            try:
                if re.search(pattern, hay, re.IGNORECASE):
                    # prefer the most specific (longest literal) pattern
                    if len(pattern) > best_len:
                        best, best_len = entry, len(pattern)
                    break
            except re.error:
                continue
    return best


def run(ctx: Context) -> R.CheckResult:
    check = R.CheckResult(key=KEY, label=LABEL)
    findings: List[R.Finding] = []

    adapters = []
    for g in util.as_list(ctx.facts.get("gpus")):
        name = util.short_gpu(g.get("name") or "")
        adapters.append({"name": name, "kind": util.classify_gpu(name)})
    discrete = [a for a in adapters if a["kind"] == "discrete"]

    # A phantom device is the single cleanest proof: Windows has a driver record
    # for a card it can no longer see on the PCI bus.
    phantoms = []
    for d in util.as_list(ctx.facts.get("pnp_display")):
        if str(d.get("problem") or "") == "CM_PROB_PHANTOM":
            name = d.get("name") or ""
            if util.classify_gpu(name) == "discrete":
                phantoms.append({"name": name, "instance": d.get("instance")})

    model = match_model(ctx)
    traces = remnants.collect()
    check.data = {
        "matched_model": model,
        "adapters": adapters,
        "discrete": [a["name"] for a in discrete],
        "traces": traces,
        "model_db_size": len(load_json("models.json").get("models") or []),
    }

    if not model:
        check.status = R.STATUS_UNAVAILABLE
        check.score = 0.0
        check.summary = "Model not in the database"
        check.findings = [R.Finding(
            id="dgpu.unknown_model", severity=R.INFO,
            title="This model is not in the GPU database",
            detail=("Without a factory spec for this model there is nothing to compare "
                    "against. Add it to data/models.json once you know what it should have."),
            evidence={"detected": _haystack(ctx)})]
        return check

    expected: List[str] = list(model.get("dgpu") or [])
    check.data["expected"] = expected

    if discrete:
        # a dGPU is present - verify it looks like the right one
        names = " ".join(a["name"] for a in discrete).lower()
        matched_expected = [e for e in expected if e.lower().split()[-1] in names]
        check.status = R.STATUS_OK
        check.score = 100.0
        check.summary = ", ".join(a["name"] for a in discrete)
        if expected and not matched_expected:
            findings.append(R.Finding(
                id="dgpu.unexpected_model", severity=R.WARN,
                title="Discrete GPU present but not one this model shipped with",
                detail=(f"Factory options for {model['family']}: {', '.join(expected)}. "
                        "A different card suggests a board swap or a modified machine."),
                evidence={"present": [a["name"] for a in discrete],
                          "expected": expected}))
            check.score = 78.0
            check.status = R.STATUS_WARN
        else:
            findings.append(R.Finding(
                id="dgpu.present", severity=R.INFO,
                title=f"Discrete GPU present: {', '.join(a['name'] for a in discrete)}",
                evidence={"expected": expected}))
        check.findings = findings
        return check

    # ---- no dGPU enumerates. Was there ever one?
    if not expected:
        check.status = R.STATUS_OK
        check.score = 100.0
        check.summary = f"{model['family']} never shipped with a dGPU"
        check.findings = [R.Finding(
            id="dgpu.not_applicable", severity=R.INFO,
            title=f"{model['family']} has no factory dGPU option",
            detail="Nothing missing. This SKU is integrated-graphics only.",
            evidence={"model": model["family"]})]
        return check

    nvidia = traces.get("traces", {}).get("nvidia", {})
    amd = traces.get("traces", {}).get("amd", {})
    pci_vendors = traces.get("pci_vendors") or {}
    class_entries = traces.get("display_class") or []

    nv_pci = int(pci_vendors.get("10DE") or 0)
    amd_pci = int(pci_vendors.get("1002") or 0)
    class_gpu = [
        c for c in class_entries
        if any(k in (c.get("desc") or "").lower()
               for k in ("nvidia", "geforce", "quadro", "radeon", "firepro"))
    ]

    evidence = {
        "model": model["family"],
        "factory_options": expected,
        "dgpu_standard": model.get("dgpu_standard"),
        "enumerated": [a["name"] for a in adapters],
        "phantom_devices": [p["name"] for p in phantoms],
        "pci_nvidia_devices": nv_pci,
        "pci_amd_devices": amd_pci,
        "display_class_entries": [c["desc"] for c in class_gpu][:6],
        "nvidia_traces": nvidia,
        "amd_traces": amd,
    }
    check.data["phantom_devices"] = [p["name"] for p in phantoms]

    had_one = (nv_pci > 0 or amd_pci > 0 or bool(class_gpu) or bool(phantoms)
               or nvidia.get("present") or amd.get("present"))

    if had_one:
        if phantoms:
            proof = (f"Windows still holds a phantom device record for "
                     f"{phantoms[0]['name']} - a card it can no longer see on the "
                     f"PCI bus. ")
        else:
            proof = ("Windows still carries driver and registry traces of a discrete "
                     "GPU that is no longer visible. ")
        findings.append(R.Finding(
            id="dgpu.removed", severity=R.CRITICAL,
            title="dGPU was present on this machine and no longer enumerates",
            detail=(f"{model['family']} shipped with {', '.join(expected)}. " + proof +
                    "It has been disabled in BIOS or has failed. This is the standard "
                    "way to hide a dead graphics card before selling."),
            evidence=evidence,
            cost_pkr=cost_of("gpu_replacement_mainboard", 22000),
            cost_note=("A dGPU that has been disabled is usually a dead MXM card or a "
                       "failed power rail. Treat it as gone and price the machine as "
                       "integrated-graphics only.")))
        score = 25.0
        status = R.STATUS_FAIL
    elif model.get("dgpu_standard"):
        findings.append(R.Finding(
            id="dgpu.missing_standard", severity=R.MAJOR,
            title=f"No discrete GPU, but every {model['family']} shipped with one",
            detail=("No dGPU enumerates and no driver traces remain. Either the Windows "
                    "install is fresh enough to have erased the history, or the board "
                    "has been swapped. Ask for the original invoice."),
            evidence=evidence,
            cost_pkr=cost_of("gpu_replacement_mainboard", 22000),
            cost_note="Price it as a machine missing its advertised GPU."))
        score = 45.0
        status = R.STATUS_WARN
    else:
        findings.append(R.Finding(
            id="dgpu.missing_optional", severity=R.WARN,
            title=f"No discrete GPU, but {model['family']} offered one",
            detail=("This SKU may genuinely be the integrated-only variant, and a fresh "
                    "Windows install leaves no trace of a card that was never there. "
                    "Ask the seller to show the original config sticker."),
            evidence=evidence,
            cost_pkr=int(cost_of("gpu_replacement_mainboard", 22000) * 0.5),
            cost_note="Discount for the missing card, not a repair."))
        score = 70.0
        status = R.STATUS_WARN

    check.findings = findings
    check.score = score
    check.status = status
    check.summary = (f"{model['family']}: expected {expected[0]}"
                     + (f" (+{len(expected) - 1})" if len(expected) > 1 else "")
                     + ", none present")
    return check
