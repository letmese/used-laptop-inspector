"""End-to-end: does running an interactive test change the score and the money?"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from tools.rebuild_report import load
from laptop_inspector.ui.main_window import MainWindow

app = QApplication(sys.argv)
win = MainWindow()
win.resize(1440, 940)
win.move(-4000, -4000)
win.show()

report = load(str(ROOT / "out" / "report.json"))


def before():
    win.on_report(report)
    print(f"BEFORE  score={report.score:.1f} verdict={report.verdict} "
          f"repairs={report.negotiation.total_repair_pkr}")
    QTimer.singleShot(300, simulate)


def simulate():
    # stand in for the buyer completing two of the three tests
    win.interactive_results = {
        "screen": {"run": True, "issues": ["backlight bleed"], "resolution": "1920x1080"},
        "keyboard": {"run": True, "pressed": ["A"] * 70, "missing": ["F1", "F2"],
                     "expected": 74},
    }
    win._apply_interactive()
    QTimer.singleShot(400, after)


def after():
    r = win.report
    print(f"AFTER   score={r.score:.1f} verdict={r.verdict} "
          f"repairs={r.negotiation.total_repair_pkr}")
    keys = [c.key for c in r.checks]
    print("checks:", keys)
    print("interactive weight applied:",
          [b for b in r.extras["score_breakdown"] if b["key"] == "interactive"])
    win.select_rail_item("interactive")
    QTimer.singleShot(500, shot)


def shot():
    win.grab().save(str(ROOT / "out" / "v2_panel.png"))
    print("saved v2_panel.png")
    app.quit()


QTimer.singleShot(300, before)
sys.exit(app.exec())
