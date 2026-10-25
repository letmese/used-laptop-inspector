"""GUI entry point - and the frozen entry point for the packaged exe.

    python main.py            # GUI
    python main.py --cli ...  # headless, same engine (this is the WinPE path)

No multiprocessing is used anywhere now: the CPU load runs on threads inside a
GIL-releasing hash loop, so a frozen build does not need freeze_support() and
never re-extracts its own bundle to start a worker.
"""

from __future__ import annotations

import sys


def main() -> int:
    if "--cli" in sys.argv:
        from laptop_inspector.cli import main as cli_main
        argv = [a for a in sys.argv[1:] if a != "--cli"]
        return cli_main(argv)

    from PySide6.QtCore import Qt
    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication

    from laptop_inspector.ui.icon import asset_path
    from laptop_inspector.ui.main_window import MainWindow

    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    app.setApplicationName("Used Laptop Inspector")
    app.setApplicationDisplayName("Used Laptop Inspector")
    app.setOrganizationName("Antigravity")
    app.setWindowIcon(QIcon(asset_path("icon.ico")))

    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
