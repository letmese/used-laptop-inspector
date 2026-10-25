"""Runs the engine on a worker thread so the UI stays responsive."""

from __future__ import annotations

import traceback
from typing import Optional

from PySide6.QtCore import QThread, Signal

from ..engine import result as R
from ..engine.context import Options
from ..engine.inspector import Inspector


class InspectionWorker(QThread):
    progress = Signal(str, float, str)
    finished_report = Signal(object)
    failed = Signal(str)

    def __init__(self, options: Options, parent=None) -> None:
        super().__init__(parent)
        self.options = options
        self._report: Optional[R.Report] = None

    def run(self) -> None:  # noqa: D102
        try:
            inspector = Inspector(self.options, progress=self._on_progress)
            report = inspector.run()
            self._report = report
            self.finished_report.emit(report)
        except Exception:
            self.failed.emit(traceback.format_exc())

    def _on_progress(self, key: str, fraction: float, text: str) -> None:
        self.progress.emit(key, fraction, text)
