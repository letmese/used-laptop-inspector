"""Does the rewritten UI still run a full scan end to end?"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from laptop_inspector.ui.main_window import MainWindow

app = QApplication(sys.argv)
win = MainWindow()
win.resize(1440, 940)
win.move(-4000, -4000)
win.show()

state = {"done": False}


def on_report(r):
    state["done"] = True
    print("SCAN OK ->", r.verdict, round(r.score, 1),
          "| repairs", r.negotiation.total_repair_pkr)
    win.grab().save(str(ROOT / "out" / "rev_live_scan.png"))
    print("saved rev_live_scan.png")
    app.quit()


def on_fail(msg):
    print("SCAN FAILED:", msg[-800:])
    app.quit()


def go():
    win.fast_mode.setChecked(True)
    win.start_scan()
    QTimer.singleShot(300, hook)


def hook():
    w = win.worker
    if w is None:
        print("no worker created")
        app.quit()
        return
    w.finished_report.connect(on_report)
    w.failed.connect(on_fail)
    QTimer.singleShot(150000, lambda: (print("TIMEOUT done=", state["done"]), app.quit()))


QTimer.singleShot(400, go)
sys.exit(app.exec())
