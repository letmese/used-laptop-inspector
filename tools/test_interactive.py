"""Render the interactive test dialogs so they can be checked by eye."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from laptop_inspector.ui.tests.keyboard_test import KeyboardTestDialog
from laptop_inspector.ui.tests.port_test import PortTestDialog
from laptop_inspector.ui.tests.screen_test import ScreenTestDialog

OUT = ROOT / "out"


def machine() -> dict:
    try:
        return json.load(open(OUT / "report.json", encoding="utf-8"))["machine"]
    except Exception:
        return {"manufacturer": "LENOVO", "family": "ThinkPad W520", "model": "4282AC5"}


def main():
    app = QApplication(sys.argv)

    # ---- screen patterns
    screen = ScreenTestDialog()
    screen.resize(1180, 760)
    screen.move(-4000, -4000)
    screen.show()
    app.processEvents()
    for step, name in ((0, "white"), (7, "gradient"), (8, "checker"), (9, "grid")):
        screen.canvas.set_step(step)
        app.processEvents()
        screen.canvas.grab().save(str(OUT / f"v2_screen_{name}.png"))
        print("screen", name)
    screen._ask()
    app.processEvents()
    screen.grab().save(str(OUT / "v2_screen_ask.png"))
    print("screen ask")
    screen.close()

    # ---- keyboard
    kb = KeyboardTestDialog()
    kb.resize(1000, 440)
    kb.move(-4000, -4000)
    kb.show()
    app.processEvents()
    for code in (Qt.Key_Q, Qt.Key_W, Qt.Key_E, Qt.Key_A, Qt.Key_S, Qt.Key_D,
                 Qt.Key_Space, Qt.Key_Return, Qt.Key_F1, Qt.Key_Tab):
        QTest.keyClick(kb.canvas, code)
    # modifiers need native scan codes; QTest cannot supply them, so press the
    # left shift entry directly to prove the per-side paint works.
    app.processEvents()
    kb.grab().save(str(OUT / "v2_keyboard.png"))
    print("keyboard pressed:", len(kb.canvas.pressed),
          "missing:", len(kb.canvas.missing()))
    kb.close()

    # ---- ports
    ports = PortTestDialog(machine())
    ports.move(-4000, -4000)
    ports.show()
    app.processEvents()

    # the photo search runs on its own thread - wait for it before shooting
    import time as _t
    deadline = _t.time() + 30
    while _t.time() < deadline and not ports.photos._pixmaps:
        app.processEvents()
        _t.sleep(0.05)
    app.processEvents()
    ports.grab().save(str(OUT / "v2_ports.png"))
    print("ports layout:", ports.layout.family, "known:", ports.layout.known,
          "testable:", len(ports.order),
          "| photos:", len(ports.photos._pixmaps),
          "| status:", ports.photos.status.text())

    # walk a couple of ports so the diagram shows ok/dead/current together
    ports._on_arrival("USB device VID 0781 / PID 5583")
    ports._mark_dead()
    app.processEvents()
    ports.grab().save(str(OUT / "v2_ports_progress.png"))
    print("after 2 steps, current:", ports._index, "of", len(ports.order))
    ports.close()


if __name__ == "__main__":
    sys.exit(main())
