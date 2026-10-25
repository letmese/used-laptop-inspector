"""Run both stress tests through the real dialog, then rescore a real report.

This is the end-to-end check: the dialog drives the engine on worker threads,
the results come back as dicts, and thermal.from_probe / gpu.apply_stress turn
them into findings that change the score and the counter-offer.
"""

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtWidgets import QApplication

from laptop_inspector.engine.checks import gpu as gpu_check
from laptop_inspector.engine.checks import thermal as thermal_check
from laptop_inspector.engine.inspector import Inspector
from laptop_inspector.engine.context import Options
from laptop_inspector.report import pdf_report
from laptop_inspector.ui.tests.stress_lab import StressLabDialog

OUT = ROOT / "out"


def pump(app, seconds, until=None):
    end = time.time() + seconds
    while time.time() < end:
        app.processEvents()
        if until is not None and until():
            return True
        time.sleep(0.02)
    return until() if until else True


def main():
    app = QApplication(sys.argv)
    dialog = StressLabDialog()
    dialog.move(-4000, -4000)
    dialog.show()
    app.processEvents()

    # ---- CPU
    dialog.cpu.seconds.setValue(8)
    dialog._run_cpu()
    pump(app, 4.0)
    dialog.grab().save(str(OUT / "v2_stress_cpu_running.png"))
    ok = pump(app, 60, until=lambda: dialog.cpu_ran)
    print("CPU finished:", ok)
    cpu = dialog.cpu_result or {}
    print("  peak:", cpu.get("peak_mhz"), "sustained:", cpu.get("sustained_mhz"),
          "sag:", cpu.get("sag_ratio"), "util:", cpu.get("mean_util"),
          "temps:", cpu.get("temps_c"), "samples:", cpu.get("samples"))
    dialog.grab().save(str(OUT / "v2_stress_cpu_done.png"))

    # ---- GPU
    dialog.gpu.seconds.setValue(8)
    dialog._run_gpu()
    pump(app, 4.0)
    dialog.grab().save(str(OUT / "v2_stress_gpu_running.png"))
    ok = pump(app, 60, until=lambda: dialog.gpu_ran)
    print("GPU finished:", ok)
    gpu = dialog.gpu_result or {}
    print("  adapter:", gpu.get("adapter"), "mode:", gpu.get("mode"),
          "fps:", gpu.get("frames_per_sec"), "level:", gpu.get("feature_level"),
          "context:", gpu.get("context_type"), "error:", gpu.get("error"))
    dialog.grab().save(str(OUT / "v2_stress_done.png"))
    dialog.close()

    # ---- fold into a real report
    report = None
    try:
        from tools.rebuild_report import load
        report = load(str(OUT / "report.json"))
    except Exception as exc:
        print("no report to rescore:", exc)

    if report is not None:
        before = (report.score, report.verdict,
                  report.negotiation.total_repair_pkr)
        thermal = report.check("thermal")
        print("\nbefore:", before)
        print("  thermal summary:", thermal.summary if thermal else None)
        print("  gpu stress:", ((report.check("gpu").data or {}).get("stress") or {}).get("error"))

        if cpu:
            rebuilt = thermal_check.from_probe(cpu)
            report.checks = [c for c in report.checks if c.key != "thermal"] + [rebuilt]
            print("\nafter CPU re-run:", rebuilt.status, round(rebuilt.score, 1),
                  "|", rebuilt.summary)
            for f in rebuilt.findings:
                print("   ", f.severity, "|", f.title)
        if gpu:
            gpu_check.apply_stress(report.check("gpu"), gpu)
            chk = report.check("gpu")
            print("after GPU re-run:", chk.status, round(chk.score, 1))
            for f in chk.findings:
                print("   ", f.severity, "|", f.title)

        Inspector(Options(asking_price_pkr=85000)).finalise(report)
        print("\nafter:", (report.score, report.verdict,
                           report.negotiation.total_repair_pkr))
        pdf_report.build(report, str(OUT / "v2_report.pdf"))


if __name__ == "__main__":
    sys.exit(main())
