"""Render the current UI with real fonts so it can actually be reviewed.

Run on the real Qt platform (not offscreen - that loads zero fonts and every
glyph becomes a box), with the window parked off-screen so it does not steal
focus.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from tools.rebuild_report import load
from laptop_inspector.ui.main_window import MainWindow

OUT = ROOT / "out"


def main():
    app = QApplication(sys.argv)
    win = MainWindow()
    # The window schedules a real scan 100 ms after construction. Rendering from
    # a saved report must not start one: it takes a minute and would replace the
    # report we are about to draw.
    win.start_scan = lambda *a, **k: None
    win.resize(1600, 1000)
    win.move(-4000, -4000)
    win.show()

    # Optional path: lets the marketing screenshots render from the demo report
    # instead of whatever machine was last scanned on this box.
    source = sys.argv[1] if len(sys.argv) > 1 else str(OUT / "report.json")
    report = load(source)

    def shot(name):
        win.grab().save(str(OUT / name))
        print("saved", name)

    def step1():
        # Pin the market price so any reprice stays offline.
        market = (report.negotiation.market_price_pkr or 0)
        if market:
            win.market.setValue(market)
        win.on_report(report)
        QTimer.singleShot(900, lambda: (shot("rev_verdict.png"), step2()))

    def step2():
        for key in ("storage", "battery", "thermal", "dgpu"):
            try:
                win.select_rail_item(key)
            except Exception as exc:
                print("select failed", key, exc)
                continue
            app.processEvents()
        win.select_rail_item("storage")
        QTimer.singleShot(900, lambda: (shot("rev_storage.png"), step3()))

    def step3():
        win.select_rail_item("thermal")
        QTimer.singleShot(900, lambda: (shot("rev_thermal.png"), step4()))

    def step4():
        win.select_rail_item("interactive")
        QTimer.singleShot(900, lambda: (shot("rev_interactive.png"), step5()))

    def step5():
        win.select_rail_item("peripherals")
        QTimer.singleShot(900, lambda: (shot("rev_peripherals.png"), app.quit()))

    QTimer.singleShot(400, step1)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
