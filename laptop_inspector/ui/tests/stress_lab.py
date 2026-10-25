"""Stress lab: run the CPU and GPU load tests by hand, one at a time.

The scan runs both automatically, but a buyer who is haggling wants to watch:
"it throttles" is a claim, a clock trace falling from 3.1 GHz to 2.2 GHz while
you watch is evidence. So each test gets its own button, its own duration, its
own live trace, and its own result that feeds back into the score.

Neither test blocks the interface - each runs on its own QThread and reports
samples back through signals.
"""

from __future__ import annotations

import threading
from collections import deque
from typing import Any, Deque, Dict, List, Optional

from PySide6.QtCore import QObject, QPointF, Qt, QThread, Signal, Slot
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QDialog, QFrame, QHBoxLayout, QLabel,
                               QPushButton, QSizePolicy, QSpinBox,
                               QVBoxLayout, QWidget)

from ...engine import d3d11, loadgen, powershell
from .. import theme

CPU_COLOUR = "#F59E0B"
GPU_COLOUR = "#22D3EE"


# --------------------------------------------------------------------- workers
class CpuWorker(QObject):
    sample = Signal(dict)
    done = Signal(dict)

    def __init__(self, duration: float, workers: int) -> None:
        super().__init__()
        self.duration = duration
        self.workers = workers
        self._stop = threading.Event()

    def stop(self) -> None:
        self._stop.set()

    @Slot()
    def run(self) -> None:
        try:
            result = loadgen.run_thermal_probe(
                duration=self.duration,
                workers=self.workers,
                idle_seconds=1.5,
                on_sample=self._on_sample,
                stop=self._stop,
            )
            data = result.to_dict()
            # One reading straight after the load. It can only under-report the
            # peak, so it never invents a thermal fault.
            try:
                data["temps_c"] = powershell.collect_thermal_zones() or []
            except Exception:
                data["temps_c"] = []
            self.done.emit(data)
        except Exception as exc:
            self.done.emit({"samples": 0, "error": f"{type(exc).__name__}: {exc}"})

    def _on_sample(self, sample, phase: str, fraction: float) -> None:
        self.sample.emit({
            "phase": phase,
            "mhz": sample.actual_mhz,
            "util": sample.util,
            "throughput": sample.throughput,
            "fraction": fraction,
        })


class GpuWorker(QObject):
    tick = Signal(dict)
    done = Signal(dict)

    def __init__(self, duration: float) -> None:
        super().__init__()
        self.duration = duration
        self._stop = threading.Event()
        self._last_clears = 0
        self._last_elapsed = 0.0

    def stop(self) -> None:
        self._stop.set()

    @Slot()
    def run(self) -> None:
        try:
            result = d3d11.stress(self.duration, progress=self._progress,
                                  stop=self._stop)
            self.done.emit(result)
        except Exception as exc:
            self.done.emit({"available": False,
                            "error": f"{type(exc).__name__}: {exc}"})

    def _progress(self, frames: int, elapsed: float, rate: int) -> None:
        delta_t = elapsed - self._last_elapsed
        if delta_t < 0.15:
            return
        instant = int((frames - self._last_clears) / delta_t)
        self._last_clears, self._last_elapsed = frames, elapsed
        self.tick.emit({"frames": frames, "elapsed": elapsed, "rate": instant,
                        "fraction": min(1.0, elapsed / self.duration)})


# ----------------------------------------------------------------------- chart
class LiveChart(QWidget):
    """Rolling line chart. Shows nothing rather than a flat line before data."""

    def __init__(self, colour: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(64)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._values: Deque[float] = deque(maxlen=150)
        self._colour = QColor(colour)
        self._empty_text = "not running"

    def clear(self, text: str = "not running") -> None:
        self._values.clear()
        self._empty_text = text
        self.update()

    def push(self, value: Optional[float]) -> None:
        if value is None:
            return
        self._values.append(float(value))
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        w, h = self.width(), self.height()
        painter.fillRect(0, 0, w, h, QColor("#0B0F15"))

        painter.setPen(QPen(QColor("#1B2430"), 1))
        painter.drawLine(0, h - 1, w, h - 1)

        if len(self._values) < 2:
            painter.setFont(QFont("Segoe UI", 8))
            painter.setPen(QPen(QColor("#4A5563")))
            painter.drawText(self.rect(), Qt.AlignCenter, self._empty_text)
            painter.end()
            return

        values = list(self._values)
        lo, hi = min(values), max(values)
        if hi - lo < 1e-6:
            lo, hi = lo - 1, hi + 1
        pad = (hi - lo) * 0.15
        lo -= pad
        hi += pad

        step = w / max(1, len(values) - 1)

        def y_of(v: float) -> float:
            return h - 6 - (v - lo) / (hi - lo) * (h - 12)

        path = QPainterPath()
        path.moveTo(0, y_of(values[0]))
        for i, v in enumerate(values[1:], 1):
            path.lineTo(i * step, y_of(v))

        fill = QPainterPath(path)
        fill.lineTo(w, h)
        fill.lineTo(0, h)
        fill.closeSubpath()

        grad = QColor(self._colour)
        grad.setAlpha(40)
        painter.setPen(Qt.NoPen)
        painter.setBrush(grad)
        painter.drawPath(fill)

        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(self._colour, 1.6))
        painter.drawPath(path)

        painter.setBrush(self._colour)
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(QPointF((len(values) - 1) * step,
                                    y_of(values[-1])), 2.5, 2.5)
        painter.end()


# ------------------------------------------------------------------- stat box
class StatBox(QWidget):
    def __init__(self, label: str, value: str = "--",
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(1)
        self.kicker = QLabel(label.upper())
        self.kicker.setStyleSheet("font-size: 11px; font-weight:800;"
                                  " color:#8593A6; letter-spacing:0.7px;")
        self.value = QLabel(value)
        self.value.setStyleSheet("font-size: 15.5px; font-weight:700; color:#E7EEF7;")
        box.addWidget(self.kicker)
        box.addWidget(self.value)

    def set(self, value: str, colour: str = "#E7EEF7") -> None:
        self.value.setText(value)
        self.value.setStyleSheet(f"font-size: 15.5px; font-weight:700; color:{colour};")


def _short(n: int) -> str:
    """350,004 does not fit next to the unit label; 350k does."""
    if n >= 10000:
        return f"{n / 1000:.0f}k"
    return f"{n:,}"


class StressPanel(QFrame):
    """One test: headline number, trace, stats, run controls."""

    def __init__(self, title: str, blurb: str, colour: str, unit: str,
                 default_seconds: int, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("Card")
        self._unit = unit
        box = QVBoxLayout(self)
        box.setContentsMargins(16, 12, 16, 14)
        box.setSpacing(8)

        head = QHBoxLayout()
        name = QLabel(title)
        name.setStyleSheet("font-size: 16px; font-weight:800; color:#FFFFFF;")
        head.addWidget(name)
        head.addStretch(1)
        self.state = QLabel("idle")
        self.state.setObjectName("BadgeDark")
        self.state.setStyleSheet("font-size: 12.5px; font-weight:800; padding:2px 7px;")
        self.state.setFixedHeight(18)
        self.state.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        head.addWidget(self.state, 0, Qt.AlignTop)
        box.addLayout(head)

        note = QLabel(blurb)
        note.setWordWrap(True)
        note.setStyleSheet("color:#BCC8D6; font-size: 13.5px;")
        note.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        box.addWidget(note)

        big = QHBoxLayout()
        self.headline = QLabel("--")
        self.headline.setStyleSheet(f"font-size: 34px; font-weight:800; color:{colour};")
        big.addWidget(self.headline, 0, Qt.AlignBottom)
        self.headline_unit = QLabel(unit)
        self.headline_unit.setStyleSheet("font-size: 14.5px; color:#8593A6;")
        big.addWidget(self.headline_unit, 0, Qt.AlignBottom)
        big.addStretch(1)
        box.addLayout(big)

        self.sub = QLabel("")
        self.sub.setStyleSheet("font-size: 13px; color:#93A1B4;")
        self.sub.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        box.addWidget(self.sub)


        self.chart = LiveChart(colour)
        box.addWidget(self.chart)

        grid = QHBoxLayout()
        grid.setSpacing(14)
        self.stats: Dict[str, StatBox] = {}
        for key, label in self._stat_labels():
            stat = StatBox(label)
            stat.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
            self.stats[key] = stat
            grid.addWidget(stat, 1)
        box.addLayout(grid)

        controls = QHBoxLayout()
        controls.setSpacing(8)
        self.seconds = QSpinBox()
        self.seconds.setRange(5, 180)
        self.seconds.setValue(default_seconds)
        self.seconds.setSuffix(" s")
        self.seconds.setFixedWidth(78)
        self.run_btn = QPushButton("Run")
        self.run_btn.setStyleSheet("background:#2563EB; color:white;"
                                   " font-weight:700; padding:6px 14px;"
                                   " border-radius:4px; font-size: 14.5px;")
        self.stop_btn = QPushButton("Stop")
        self.stop_btn.setObjectName("Ghost")
        self.stop_btn.setEnabled(False)
        controls.addWidget(QLabel("Duration"))
        controls.addWidget(self.seconds)
        controls.addWidget(self.run_btn)
        controls.addWidget(self.stop_btn)
        controls.addStretch(1)
        box.addLayout(controls)

        self._thread: Optional[QThread] = None
        self._worker: Optional[QObject] = None

    def _stat_labels(self):
        return [("nominal", "nominal"), ("peak", "peak"), ("sustained", "sustained"),
                ("sag", "sag"), ("util", "cpu"), ("temp", "temp")]

    # ---- helpers
    def set_state(self, text: str, badge: str) -> None:
        self.state.setText(text)
        self.state.setObjectName(badge)
        self.state.style().unpolish(self.state)
        self.state.style().polish(self.state)

    def set_running(self, running: bool) -> None:
        self.run_btn.setEnabled(not running)
        self.stop_btn.setEnabled(running)
        self.seconds.setEnabled(not running)
        if running:
            self.chart.clear("measuring…")
            self.headline.setText("--")

    def start_thread(self, worker: QObject) -> None:
        self._thread = QThread(self)
        self._worker = worker
        worker.moveToThread(self._thread)
        self._thread.started.connect(worker.run)
        self._thread.start()

    def stop_thread(self) -> None:
        if self._worker is not None and hasattr(self._worker, "stop"):
            self._worker.stop()

    def teardown(self) -> None:
        if self._thread is not None:
            self._thread.quit()
            self._thread.wait(4000)
            self._thread = None
            self._worker = None


class CpuPanel(StressPanel):
    def _stat_labels(self):
        return [("nominal", "nominal"), ("peak", "peak"), ("sustained", "sustained"),
                ("sag", "sag"), ("util", "cpu load"), ("temp", "temp")]


class GpuPanel(StressPanel):
    def _stat_labels(self):
        return [("level", "feature level"), ("elapsed", "elapsed"),
                ("frames", "frames"), ("result", "result")]


# ---------------------------------------------------------------------- dialog
class StressLabDialog(QDialog):
    """Both tests, side by side, independently runnable."""

    def __init__(self, thermal_data: Optional[Dict[str, Any]] = None,
                 gpu_stress: Optional[Dict[str, Any]] = None,
                 parent: Optional[QDialog] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Stress lab")
        self.resize(880, 620)
        self.setStyleSheet(theme.STYLESHEET)

        self.cpu_result: Optional[Dict[str, Any]] = None
        self.gpu_result: Optional[Dict[str, Any]] = None
        # Prefilled results must not be re-applied; only a fresh run counts.
        self.cpu_ran = False
        self.gpu_ran = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(10)

        head = QHBoxLayout()
        title = QLabel("Stress lab")
        title.setStyleSheet("font-size: 23.5px; font-weight:700;")
        head.addWidget(title)
        head.addStretch(1)
        hint = QLabel("Each test runs on its own. Results rescore the report.")
        hint.setStyleSheet("color:#8593A6; font-size: 14.5px;")
        head.addWidget(hint)
        layout.addLayout(head)

        row = QHBoxLayout()
        row.setSpacing(12)

        self.cpu = CpuPanel(
            "CPU stress", "Loads every core and records the real clock, the CPU "
            "utilisation and the work actually delivered.", CPU_COLOUR, "MHz", 20)
        self.cpu.run_btn.clicked.connect(self._run_cpu)
        self.cpu.stop_btn.clicked.connect(self.cpu.stop_thread)
        row.addWidget(self.cpu, 1)

        self.gpu = GpuPanel(
            "GPU stress", "Renders shaded frames on the discrete GPU and watches "
            "for a driver reset while it happens.", GPU_COLOUR,
            "frames/s", 15)
        self.gpu.run_btn.clicked.connect(self._run_gpu)
        self.gpu.stop_btn.clicked.connect(self.gpu.stop_thread)
        row.addWidget(self.gpu, 1)

        layout.addLayout(row, 1)

        footer = QHBoxLayout()
        close = QPushButton("Close and apply")
        close.setStyleSheet("background:#2563EB; color:white; font-weight:700;"
                            " padding:8px 18px; border-radius:5px;")
        close.clicked.connect(self.accept)
        footer.addStretch(1)
        footer.addWidget(close)
        layout.addLayout(footer)

        self._prefill(thermal_data, gpu_stress)

    # ---- previous results, so reopening shows the last run
    def _prefill(self, thermal_data: Optional[Dict[str, Any]],
                 gpu_stress: Optional[Dict[str, Any]]) -> None:
        if thermal_data:
            self.cpu_result = thermal_data
            self._show_cpu(thermal_data)
            self.cpu.set_state("last run", "BadgeDark")
        if gpu_stress:
            self.gpu_result = gpu_stress
            self._show_gpu(gpu_stress)
            self.gpu.set_state("last run", "BadgeDark")

    # ---- CPU
    def _run_cpu(self) -> None:
        self._live_peak = 0.0
        self.cpu.set_running(True)
        self.cpu.set_state("running", "BadgeAmber")
        worker = CpuWorker(float(self.cpu.seconds.value()), 0)
        worker.sample.connect(self._on_cpu_sample)
        worker.done.connect(self._on_cpu_done)
        self.cpu.start_thread(worker)

    @Slot(dict)
    def _on_cpu_sample(self, sample: Dict[str, Any]) -> None:
        mhz = sample.get("mhz")
        if mhz:
            self.cpu.headline.setText(f"{mhz:.0f}")
            # Only the loaded phase is plotted: including the idle baseline
            # squashes the sag into a flat line.
            if sample.get("phase") == "load":
                self.cpu.chart.push(mhz)
            self._live_peak = max(self._live_peak, mhz)
            self.cpu.stats["peak"].set(f"{self._live_peak:.0f} MHz")
        if sample.get("util") is not None:
            # PDH "processor utility" is scaled by frequency and legitimately
            # exceeds 100 under turbo; the bar means "busy", so clamp it.
            self.cpu.stats["util"].set(f"{min(100.0, sample['util']):.0f}%")
        if sample.get("phase") == "idle":
            self.cpu.set_state("baseline", "BadgeDark")

    @Slot(dict)
    def _on_cpu_done(self, data: Dict[str, Any]) -> None:
        self.cpu.teardown()
        self.cpu.set_running(False)
        self.cpu_result = data
        self.cpu_ran = True
        self._show_cpu(data)
        if data.get("samples"):
            self.cpu.set_state("done", "BadgeGreen")
        else:
            self.cpu.set_state("no data", "BadgeRed")

    def _show_cpu(self, data: Dict[str, Any]) -> None:
        peak = data.get("peak_mhz")
        sustained = data.get("sustained_mhz")
        nominal = data.get("nominal_mhz")
        sag = data.get("sag_ratio")
        if peak:
            self.cpu.headline.setText(f"{peak:.0f}")
        self.cpu.stats["nominal"].set(f"{nominal} MHz" if nominal else "--")
        self.cpu.stats["peak"].set(f"{peak:.0f} MHz" if peak else "--")
        self.cpu.stats["sustained"].set(
            f"{sustained:.0f} MHz" if sustained else "--")
        if sag:
            colour = ("#2ECC71" if sag >= 0.90 else "#F59E0B" if sag >= 0.78
                      else "#EF4444")
            self.cpu.stats["sag"].set(f"{sag * 100:.0f}% of peak", colour)
        util = data.get("mean_util")
        # mean_util is already a percentage (PDH utility counter), not a
        # fraction - multiplying it again produced "11727%".
        self.cpu.stats["util"].set(
            f"{min(100.0, util):.0f}%" if util else "--")
        temps = data.get("temps_c") or []
        self.cpu.stats["temp"].set(f"{max(temps):.0f} C" if temps else "no sensor")
        series = [p["mhz"] for p in (data.get("series") or []) if p.get("mhz")]
        if series:
            self.cpu.chart.clear()
            for value in series:
                self.cpu.chart.push(value)

    # ---- GPU
    def _run_gpu(self) -> None:
        self.gpu.set_running(True)
        self.gpu.set_state("running", "BadgeAmber")
        worker = GpuWorker(float(self.gpu.seconds.value()))
        worker.tick.connect(self._on_gpu_tick)
        worker.done.connect(self._on_gpu_done)
        self.gpu.start_thread(worker)

    @Slot(dict)
    def _on_gpu_tick(self, tick: Dict[str, Any]) -> None:
        rate = tick.get("rate") or 0
        self.gpu.headline.setText(_short(rate))
        self.gpu.chart.push(rate)
        self.gpu.stats["elapsed"].set(f"{tick.get('elapsed', 0):.1f} s")
        self.gpu.stats["frames"].set(f"{tick.get('frames', 0):,}")

    @Slot(dict)
    def _on_gpu_done(self, data: Dict[str, Any]) -> None:
        self.gpu.teardown()
        self.gpu.set_running(False)
        self.gpu_result = data
        self.gpu_ran = True
        self._show_gpu(data)
        if data.get("device_removed"):
            self.gpu.set_state("driver reset", "BadgeRed")
        elif data.get("available") and not data.get("inconclusive"):
            self.gpu.set_state("done", "BadgeGreen")
        else:
            self.gpu.set_state("inconclusive", "BadgeAmber")

    def _show_gpu(self, data: Dict[str, Any]) -> None:
        rate = data.get("frames_per_sec") or 0
        if rate:
            self.gpu.headline.setText(_short(rate))
        adapter = data.get("adapter") or "default adapter"
        level = data.get("feature_level") or "?"
        self.gpu.sub.setText(f"{adapter}  ·  feature level {level}")
        self.gpu.stats["level"].set(str(data.get("feature_level") or "--"))
        self.gpu.stats["elapsed"].set(f"{data.get('seconds', 0):.1f} s")
        self.gpu.stats["frames"].set(f"{data.get('frames', 0):,}")
        if data.get("device_removed"):
            self.gpu.stats["result"].set("driver reset", "#EF4444")
        elif data.get("inconclusive"):
            self.gpu.stats["result"].set("inconclusive", "#F59E0B")
        elif data.get("available"):
            self.gpu.stats["result"].set("stable", "#2ECC71")
        else:
            self.gpu.stats["result"].set("unavailable", "#EF4444")

    # ---- lifecycle
    def closeEvent(self, event) -> None:  # noqa: N802
        self.cpu.stop_thread()
        self.gpu.stop_thread()
        self.cpu.teardown()
        self.gpu.teardown()
        super().closeEvent(event)
