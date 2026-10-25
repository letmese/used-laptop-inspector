"""The orchestrator. No UI, no Qt, no globals.

    from laptop_inspector.engine.inspector import Inspector
    report = Inspector().run()

Everything the GUI and the CLI do goes through this.
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Dict, List, Optional

from .. import SCHEMA_VERSION, TOOL_NAME, __version__
from ..scoring import negotiation, rubric
from . import market as market_lookup, webimages
from . import powershell, result as R, util, winapi
from .checks import (battery, dgpu_presence, gpu, peripherals, specs, storage,
                     thermal)
from .context import Context, Options

CHECK_MODULES = [specs, battery, storage, thermal, gpu, dgpu_presence,
                 peripherals]


class Inspector:
    def __init__(self, options: Optional[Options] = None,
                 progress: Optional[Callable[[str, float, str], None]] = None) -> None:
        self.options = options or Options()
        self.progress = progress

    # ------------------------------------------------------------------
    def _collect(self, ctx: Context) -> None:
        """One parallel sweep for the slow collectors.

        Each of these is a separate `powershell.exe` spawn (~1-7 s on old
        hardware), so they run concurrently rather than back to back.
        """
        jobs = {
            "facts": lambda: powershell.collect_facts(),
            "battery": lambda: powershell.battery_report_xml(),
            "events": lambda: powershell.collect_tdr_events(),
            "license": lambda: powershell.collect_license(),
            "temps": lambda: powershell.collect_thermal_zones(),
            "peripherals": lambda: powershell.collect_peripherals(),
        }
        results: Dict[str, Any] = {}
        with ThreadPoolExecutor(max_workers=6) as pool:
            futures = {name: pool.submit(fn) for name, fn in jobs.items()}
            for name, fut in futures.items():
                try:
                    results[name] = fut.result(timeout=90)
                except Exception as exc:
                    results[name] = None
                    ctx.note(f"{name} collector failed: {exc}")

        ctx.facts = results.get("facts") or {}
        ctx.battery_xml = results.get("battery") or {}
        ctx.events = results.get("events") or {}
        ctx.license = results.get("license") or {}
        ctx.temps = results.get("temps") or []
        ctx.peripherals = results.get("peripherals") or {}
        if not ctx.facts:
            ctx.note("WMI facts could not be read - the report will be thin")

    # ------------------------------------------------------------------
    def _machine(self, ctx: Context, checks: List[R.CheckResult]) -> Dict[str, Any]:
        spec = next((c for c in checks if c.key == "specs"), None)
        data = (spec.data if spec else {}) or {}
        return {
            "manufacturer": data.get("manufacturer", ""),
            "model": data.get("model", ""),
            "family": data.get("family", ""),
            "cpu": (data.get("cpu") or {}).get("name", ""),
            "cpu_cores": (data.get("cpu") or {}).get("cores"),
            "cpu_threads": (data.get("cpu") or {}).get("threads"),
            "ram_gb": (data.get("ram") or {}).get("installed_gb"),
            "ram_usable_gb": (data.get("ram") or {}).get("usable_gb"),
            "storage": [
                {"model": d.get("model"), "size_gb": d.get("size_gb"),
                 "bus": d.get("bus"), "media": d.get("media")}
                for d in (data.get("storage") or [])
            ],
            "gpus": [g.get("name") for g in (data.get("gpus") or [])],
            "screen": data.get("screen") or {},
            "bios": data.get("bios") or {},
            "serial": data.get("serial", ""),
            "oem_key": data.get("oem_key"),
            "os": data.get("os") or {},
        }

    # ------------------------------------------------------------------
    def run(self) -> R.Report:
        started = time.time()
        ctx = Context(options=self.options, on_progress=self.progress)
        ctx.progress("collect", 0.02, "Reading firmware and WMI")

        self._collect(ctx)
        ctx.progress("collect", 0.12, "Facts collected")

        checks: List[R.CheckResult] = []
        for index, module in enumerate(CHECK_MODULES):
            base = 0.12 + (index / len(CHECK_MODULES)) * 0.82
            span = 0.82 / len(CHECK_MODULES)
            ctx.begin_check(module.KEY, base, span)
            ctx.progress(module.KEY, 0.0, module.LABEL)
            t0 = time.time()
            try:
                check = module.run(ctx)
            except Exception as exc:
                check = R.CheckResult(
                    key=module.KEY, label=module.LABEL,
                    status=R.STATUS_ERROR, score=0.0,
                    error=f"{type(exc).__name__}: {exc}",
                    summary="Check failed to run")
                ctx.note(f"{module.KEY} raised {type(exc).__name__}: {exc}")
            check.duration_s = time.time() - t0
            checks.append(check)
            ctx.progress(module.KEY, 1.0, check.summary)

        report = R.Report(
            machine=self._machine(ctx, checks),
            checks=checks,
            score=0.0,
            verdict="NEGOTIATE",
            verdict_reasons=[],
            negotiation=R.Negotiation(),
            claims=dict(self.options.claims or {}),
            generated_at=R.now_iso(),
            tool_version=__version__,
            schema_version=SCHEMA_VERSION,
            duration_s=time.time() - started,
            admin=winapi.is_admin(),
        )
        report.extras = {
            "license": ctx.license or {},
            "collector_log": ctx.log,
            "tool_name": TOOL_NAME,
            "checks_run": [c.key for c in checks],
        }
        # What the model sells for used. Resolved here, once, because finalise()
        # runs again every time the buyer edits a price and must not hit the web.
        ctx.progress("market", 0.0, "Checking used prices")
        model_name = webimages.model_query(report.machine, "")
        report.market = market_lookup.resolve(
            model_name,
            manual_pkr=self.options.market_price_pkr,
            allow_search=self.options.allow_market_search,
        ).to_dict()
        self.finalise(report)
        ctx.progress("done", 1.0, "Report ready")
        return report

    def finalise(self, report: R.Report) -> R.Report:
        """Recompute weights, score, verdict and negotiation from the checks.

        Called after the scan, and again whenever the buyer adds the interactive
        results - the score has to reflect the evidence that exists right now.
        """
        checks = report.checks
        rubric.apply_weights(checks)
        score, breakdown = rubric.weighted_score(checks)
        verdict, reasons = rubric.verdict_for(score, checks)

        # What to search for: the same model string the photo lookup uses, so
        # the two cannot disagree about what machine this is.
        model_name = webimages.model_query(report.machine, "")
        market = dict(report.market or {})
        if self.options.market_price_pkr:
            # A price the buyer typed is authoritative and costs nothing to read.
            market = market_lookup.resolve(
                model_name, manual_pkr=self.options.market_price_pkr,
                allow_search=False).to_dict()
        neg = negotiation.build(checks, self.options.asking_price_pkr, market)
        # The money is the tie-breaker: if the repairs are worth more than the
        # discount can absorb, the verdict has to say so.
        if neg.walk_away and verdict != "WALK AWAY":
            verdict = "WALK AWAY"
            if self.options.asking_price_pkr:
                reasons.append(
                    f"Repairs of {neg.total_repair_pkr:,} PKR against a "
                    f"{self.options.asking_price_pkr:,} PKR asking price - "
                    f"{neg.discount_pct:.0f}% of the value. Not a negotiation.")

        report.score = score
        report.verdict = verdict
        report.verdict_reasons = reasons
        report.negotiation = neg
        report.extras["score_breakdown"] = breakdown
        return report


def quick_scan(options: Optional[Options] = None) -> R.Report:
    opts = options or Options(fast=True)
    opts.fast = True
    return Inspector(opts).run()
