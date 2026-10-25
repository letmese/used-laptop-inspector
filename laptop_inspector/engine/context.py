"""Shared state passed to every check."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")


@dataclass
class Options:
    thermal_seconds: float = 45.0
    gpu_seconds: float = 12.0
    skip_thermal: bool = False
    skip_gpu_load: bool = False
    fast: bool = False                      # halves the load tests
    claims: Dict[str, Any] = field(default_factory=dict)
    asking_price_pkr: Optional[int] = None
    # What this model sells for used. Without it the offer can only be derived
    # from the asking price, which rewards a seller for asking more.
    market_price_pkr: Optional[int] = None
    allow_market_search: bool = True
    cpu_workers: Optional[int] = None

    def effective_thermal(self) -> float:
        return 15.0 if self.fast else self.thermal_seconds

    def effective_gpu(self) -> float:
        return 4.0 if self.fast else self.gpu_seconds


@dataclass
class Context:
    options: Options = field(default_factory=Options)
    facts: Dict[str, Any] = field(default_factory=dict)
    battery_xml: Dict[str, Any] = field(default_factory=dict)
    events: Dict[str, Any] = field(default_factory=dict)
    license: Dict[str, Any] = field(default_factory=dict)
    temps: List[float] = field(default_factory=list)
    peripherals: Dict[str, Any] = field(default_factory=dict)
    on_progress: Optional[Callable[[str, float, str], None]] = None
    log: List[str] = field(default_factory=list)
    _span: Optional[tuple] = None

    def note(self, message: str) -> None:
        self.log.append(message)

    def begin_check(self, key: str, base: float, span: float) -> None:
        """Checks report 0..1 internally; the orchestrator owns the overall scale."""
        self._span = (key, base, span)

    def progress(self, check_key: str, fraction: float, text: str = "") -> None:
        if not self.on_progress:
            return
        value = max(0.0, min(1.0, fraction))
        if self._span and self._span[0] == check_key:
            _, base, span = self._span
            value = base + value * span
        try:
            self.on_progress(check_key, value, text)
        except Exception:
            pass


_cache: Dict[str, Any] = {}


def load_json(name: str) -> Dict[str, Any]:
    if name in _cache:
        return _cache[name]
    path = os.path.join(DATA_DIR, name)
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except Exception:
        data = {}
    _cache[name] = data
    return data


def costs() -> Dict[str, int]:
    raw = load_json("costs_pkr.json")
    return {k: int(v) for k, v in (raw.get("items") or {}).items()}


def cost_of(key: str, default: int = 0) -> int:
    return costs().get(key, default)


def storage_cost(size_bytes: int, is_nvme: bool) -> int:
    """Pick the replacement cost that matches capacity and interface."""
    gb = size_bytes / (1000 ** 3)
    table = costs()
    if is_nvme:
        if gb >= 900:
            return table.get("ssd_nvme_1tb", 15000)
        if gb >= 450:
            return table.get("ssd_nvme_512", 9000)
        return table.get("ssd_nvme_256", 6000)
    if gb >= 900:
        return table.get("ssd_sata_1tb", 13000)
    if gb >= 450:
        return table.get("ssd_sata_512", 8000)
    return table.get("ssd_sata_256", 5000)
