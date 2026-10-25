"""PDH counter access - the only reliable way to see actual CPU frequency.

`CallNtPowerInformation(ProcessorInformation)` and `Win32_Processor.CurrentClockSpeed`
both report the *nominal* clock on a lot of hardware (verified on the W520: 2301 MHz
at idle, 2301 MHz under load, which would make a throttle detector blind).

`\\Processor Information(_Total)\\% Processor Performance` reports actual frequency as
a percentage of nominal, turbo included, so real MHz = nominal * pct / 100.
"""

from __future__ import annotations

import ctypes
import time
from ctypes import wintypes
from typing import Dict, List, Optional

pdh = ctypes.WinDLL("pdh")

PDH_FMT_DOUBLE = 0x00000200
PDH_FMT_NOCAP100 = 0x00008000

PATH_PERF = r"\Processor Information(_Total)\% Processor Performance"
PATH_FREQ = r"\Processor Information(_Total)\Processor Frequency"
PATH_UTILITY = r"\Processor Information(_Total)\% Processor Utility"
PATH_TIME = r"\Processor Information(_Total)\% Processor Time"

pdh.PdhOpenQueryW.restype = ctypes.c_long
pdh.PdhAddEnglishCounterW.restype = ctypes.c_long
pdh.PdhCollectQueryData.restype = ctypes.c_long
pdh.PdhGetFormattedCounterValue.restype = ctypes.c_long


class PDH_FMT_COUNTERVALUE(ctypes.Structure):
    _fields_ = [("CStatus", wintypes.DWORD), ("doubleValue", ctypes.c_double)]


class PdhSampler:
    """Sample a fixed set of processor counters. Close it or leak handles."""

    def __init__(self) -> None:
        self._query = wintypes.HANDLE()
        self._counters: Dict[str, wintypes.HANDLE] = {}
        self._ok = False
        try:
            if pdh.PdhOpenQueryW(None, 0, ctypes.byref(self._query)) != 0:
                return
            for name, path in (("perf", PATH_PERF), ("freq", PATH_FREQ),
                               ("utility", PATH_UTILITY), ("time", PATH_TIME)):
                handle = wintypes.HANDLE()
                if pdh.PdhAddEnglishCounterW(
                        self._query, path, 0, ctypes.byref(handle)) == 0:
                    self._counters[name] = handle
            self._ok = "perf" in self._counters and "freq" in self._counters
            self.collect()
        except Exception:
            self._ok = False

    @property
    def available(self) -> bool:
        return self._ok

    def collect(self) -> bool:
        try:
            return pdh.PdhCollectQueryData(self._query) == 0
        except Exception:
            return False

    def _value(self, name: str) -> Optional[float]:
        handle = self._counters.get(name)
        if not handle:
            return None
        val = PDH_FMT_COUNTERVALUE()
        status = pdh.PdhGetFormattedCounterValue(
            handle, PDH_FMT_DOUBLE | PDH_FMT_NOCAP100, None, ctypes.byref(val))
        if status != 0 or val.CStatus != 0:
            return None
        return float(val.doubleValue)

    def read(self) -> Dict[str, Optional[float]]:
        self.collect()
        perf = self._value("perf")
        nominal = self._value("freq")
        actual = None
        if perf is not None and nominal:
            actual = nominal * perf / 100.0
        return {
            "perf_pct": perf,
            "nominal_mhz": nominal,
            "actual_mhz": actual,
            "utility_pct": self._value("utility"),
            "time_pct": self._value("time"),
            "t": time.time(),
        }

    def close(self) -> None:
        try:
            if self._query:
                pdh.PdhCloseQuery(self._query)
        except Exception:
            pass
        self._query = wintypes.HANDLE()
        self._counters.clear()
        self._ok = False

    def __enter__(self) -> "PdhSampler":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


def probe() -> Dict[str, Optional[float]]:
    with PdhSampler() as s:
        if not s.available:
            return {}
        s.collect()
        time.sleep(1.1)
        return s.read()
