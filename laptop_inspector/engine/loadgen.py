"""CPU load generation and thermal measurement.

Load comes from threads running a GIL-releasing C call (`hashlib.sha256` on a
multi-megabyte buffer), not from child processes.

That is deliberate. The previous version spawned worker processes, which meant a
frozen exe had to re-extract its entire 47 MB bundle once per worker, and
`multiprocessing` from a Qt thread could hang a later scan outright. Threads
start in microseconds, behave identically frozen or not, and still drive every
core to 100 % because the hash runs with the GIL released.

Two independent throttle signals, because either one alone lies:

1. Actual frequency from PDH (`% Processor Performance` x nominal). The only API
   that reflects turbo - WMI and NtPowerInformation both report the nominal clock
   on this hardware.
2. Delivered throughput: hashes completed per second. A thermally saturated
   machine does less work per second even if it still reports a high clock.
"""

from __future__ import annotations

import ctypes
import hashlib
import os
import statistics
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from . import perf, winapi

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

BUFFER_MB = 2


class FILETIME(ctypes.Structure):
    _fields_ = [("dwLowDateTime", ctypes.c_ulong),
                ("dwHighDateTime", ctypes.c_ulong)]


def cpu_utilization() -> Optional[float]:
    def snap():
        idle, kern, user = FILETIME(), FILETIME(), FILETIME()
        if not kernel32.GetSystemTimes(
                ctypes.byref(idle), ctypes.byref(kern), ctypes.byref(user)):
            return None
        to_int = lambda ft: (ft.dwHighDateTime << 32) | ft.dwLowDateTime
        return to_int(kern) + to_int(user), to_int(idle)

    a = snap()
    if not a:
        return None
    time.sleep(0.12)
    b = snap()
    if not b:
        return None
    dt = b[0] - a[0]
    if dt <= 0:
        return None
    return max(0.0, min(1.0, 1.0 - (b[1] - a[1]) / dt))


class LoadBank:
    """A pool of threads burning CPU with the GIL released."""

    def __init__(self, threads: int, buffer_bytes: int = BUFFER_MB * 1024 * 1024):
        self.buffer = os.urandom(buffer_bytes)
        self._stop = threading.Event()
        self._counts = [0] * threads
        self._threads = [
            threading.Thread(target=self._burn, args=(i,), daemon=True)
            for i in range(threads)
        ]

    def _burn(self, index: int) -> None:
        buf = self.buffer
        n = 0
        while not self._stop.is_set():
            hashlib.sha256(buf).digest()
            n += 1
        self._counts[index] = n

    def start(self) -> None:
        for thread in self._threads:
            thread.start()

    def stop(self) -> None:
        self._stop.set()
        for thread in self._threads:
            thread.join(timeout=2.0)

    @property
    def total(self) -> int:
        return sum(self._counts)


@dataclass
class Sample:
    t: float
    actual_mhz: Optional[float] = None
    perf_pct: Optional[float] = None
    util: Optional[float] = None
    throughput: Optional[float] = None
    temp_c: Optional[float] = None


@dataclass
class ThermalRun:
    nominal_mhz: int = 0
    workers: int = 0
    idle: List[Sample] = field(default_factory=list)
    loaded: List[Sample] = field(default_factory=list)
    temps_c: List[float] = field(default_factory=list)
    degraded: bool = False
    error: Optional[str] = None
    duration_s: float = 0.0

    # ---- derived
    def _mean(self, values: List[Optional[float]]) -> Optional[float]:
        clean = [v for v in values if v]
        return statistics.mean(clean) if clean else None

    @property
    def idle_mhz(self) -> Optional[float]:
        return self._mean([s.actual_mhz for s in self.idle])

    @property
    def peak_mhz(self) -> Optional[float]:
        return max([s.actual_mhz for s in self.loaded if s.actual_mhz] or [0]) or None

    @property
    def sustained_mhz(self) -> Optional[float]:
        """Mean over the last 40 % of the load window - steady state."""
        if not self.loaded:
            return None
        tail = self.loaded[int(len(self.loaded) * 0.6):]
        return self._mean([s.actual_mhz for s in tail])

    @property
    def sag_ratio(self) -> Optional[float]:
        """Sustained clock against the peak it managed. <0.8 is real throttling."""
        if not self.peak_mhz or not self.sustained_mhz:
            return None
        return self.sustained_mhz / self.peak_mhz

    @property
    def throttle_ratio(self) -> Optional[float]:
        if not self.nominal_mhz or not self.sustained_mhz:
            return None
        return self.sustained_mhz / float(self.nominal_mhz)

    @property
    def throughput_decay(self) -> Optional[float]:
        """Last third against the best third of delivered work."""
        values = [s.throughput for s in self.loaded if s.throughput]
        if len(values) < 6:
            return None
        third = max(1, len(values) // 3)
        start = max(values[:third])
        end = statistics.mean(values[-third:])
        if not start:
            return None
        return end / start

    @property
    def mean_util(self) -> Optional[float]:
        return self._mean([s.util for s in self.loaded])

    def series(self, max_points: int = 120) -> List[Dict[str, Any]]:
        """Downsampled clock trace, for plotting. Relative seconds from load start."""
        if not self.loaded:
            return []
        step = max(1, len(self.loaded) // max_points)
        t0 = self.loaded[0].t
        return [
            {
                "t": round(s.t - t0, 2),
                "mhz": round(s.actual_mhz) if s.actual_mhz else None,
                "util": round(s.util) if s.util is not None else None,
            }
            for s in self.loaded[::step]
        ]

    def to_dict(self) -> Dict[str, Any]:
        def r(v, n=1):
            return round(v, n) if v is not None else None

        return {
            "nominal_mhz": self.nominal_mhz,
            "idle_mhz": r(self.idle_mhz),
            "peak_mhz": r(self.peak_mhz),
            "sustained_mhz": r(self.sustained_mhz),
            "sag_ratio": r(self.sag_ratio, 3),
            "throttle_ratio": r(self.throttle_ratio, 3),
            "throughput_decay": r(self.throughput_decay, 3),
            "mean_util": r(self.mean_util, 3),
            "temps_c": self.temps_c,
            "workers": self.workers,
            "duration_s": r(self.duration_s),
            "degraded": self.degraded,
            "error": self.error,
            "samples": len(self.loaded),
            "series": self.series(),
        }


def run_thermal_probe(duration: float = 45.0,
                      workers: Optional[int] = None,
                      idle_seconds: float = 3.0,
                      progress: Optional[Callable[[float], None]] = None,
                      temps_fn: Optional[Callable[[], List[float]]] = None,
                      on_sample: Optional[Callable[[Sample, str, float], None]] = None,
                      stop: Optional[threading.Event] = None) -> ThermalRun:
    """Load every core and record what the CPU does under it.

    `on_sample` is called for each reading with the phase ("idle"/"load") and the
    fraction of the run completed, so a UI can plot the trace while it happens
    instead of waiting for the summary. `stop` lets the caller cut the run short
    without losing the samples already taken.
    """
    run = ThermalRun()
    started = time.time()
    sampler = perf.PdhSampler()
    bank: Optional[LoadBank] = None
    try:
        cpu_count = os.cpu_count() or 4
        run.workers = workers or cpu_count
        run.nominal_mhz = int(sampler.read().get("nominal_mhz") or 0)
        if not run.nominal_mhz:
            clocks = winapi.processor_clocks()
            if clocks:
                run.nominal_mhz = max(c["max_mhz"] for c in clocks)

        # ---- idle baseline
        deadline = time.time() + idle_seconds
        while time.time() < deadline:
            reading = sampler.read()
            sample = Sample(
                t=reading["t"], actual_mhz=reading["actual_mhz"],
                perf_pct=reading["perf_pct"], util=reading["utility_pct"])
            run.idle.append(sample)
            if on_sample:
                on_sample(sample, "idle", 0.0)
            time.sleep(0.6)

        # ---- loaded phase
        bank = LoadBank(run.workers)
        bank.start()
        start = time.time()
        last_total = bank.total
        last_t = start
        while True:
            elapsed = time.time() - start
            if elapsed >= duration:
                break
            if stop is not None and stop.is_set():
                run.error = "stopped by the operator"
                break
            reading = sampler.read()
            now = time.time()
            current = bank.total
            dt = now - last_t
            throughput = (current - last_total) / dt if dt > 0.05 else None
            sample = Sample(
                t=now, actual_mhz=reading["actual_mhz"],
                perf_pct=reading["perf_pct"], util=reading["utility_pct"],
                throughput=throughput)
            run.loaded.append(sample)
            last_total, last_t = current, now
            if progress:
                progress(min(1.0, elapsed / duration))
            if on_sample:
                on_sample(sample, "load", min(1.0, elapsed / duration))
            if temps_fn and int(elapsed) % 10 == 0:
                try:
                    found = temps_fn()
                    if found:
                        run.temps_c.extend(found)
                except Exception:
                    pass
            time.sleep(max(0.0, 1.0 - (time.time() - now)))
    except Exception as exc:
        run.error = f"{type(exc).__name__}: {exc}"
        run.degraded = True
    finally:
        if bank is not None:
            bank.stop()
        sampler.close()
        run.duration_s = time.time() - started
    return run
