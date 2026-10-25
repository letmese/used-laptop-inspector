"""Which laptop is this, and where are its ports?

The port test is only useful if it tells the buyer *where* to plug the device.
"Port 3" means nothing; "USB 2.0, left side, third from the front" does.

The layout comes from `data/port_layouts.json`, matched against the same
manufacturer/model/family strings the dGPU check uses. When the family is not in
the table the generic layout is used and the UI says so, because inventing a
specific layout for an unknown chassis would be worse than admitting the gap.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ...engine.context import load_json

# Only these can be exercised by plugging a USB device in. Audio jacks are in
# the layout for context but are tested by the tone section, not by plugging a
# stick into them. Everything else is drawn so the picture matches the machine.
TESTABLE_KINDS = {"usb-a", "usb-c"}

SIDE_ORDER = {"left": 0, "right": 1, "rear": 2}

SIDE_WORD = {"left": "left side", "right": "right side", "rear": "rear"}

# Sides are listed and drawn rear to front, so position 1 is nearest the hinge.


@dataclass
class Port:
    label: str
    kind: str
    side: str
    index: int = 0            # position within its own side, 0 = closest to the front
    status: str = "pending"   # pending | current | ok | dead | skipped

    @property
    def testable(self) -> bool:
        return self.kind in TESTABLE_KINDS

    @property
    def where(self) -> str:
        return SIDE_WORD.get(self.side, self.side)


@dataclass
class Layout:
    family: str
    known: bool
    source: str = ""
    ports: List[Port] = field(default_factory=list)

    @property
    def testable(self) -> List[Port]:
        return [p for p in self.ports if p.testable]


def _haystack(machine: Dict[str, Any]) -> str:
    parts = [
        machine.get("manufacturer"),
        machine.get("model"),
        machine.get("family"),
        (machine.get("system") or {}).get("product_name"),
        (machine.get("bios") or {}).get("manufacturer"),
    ]
    return " ".join(str(p) for p in parts if p)


def _build(entry: Dict[str, Any], known: bool) -> Layout:
    ports: List[Port] = []
    counters: Dict[str, int] = {}
    for raw in entry.get("ports") or []:
        side = str(raw.get("side") or "left")
        position = counters.get(side, 0)
        counters[side] = position + 1
        ports.append(Port(label=str(raw.get("label") or "Port"),
                          kind=str(raw.get("kind") or "usb-a"),
                          side=side, index=position))
    ports.sort(key=lambda p: (SIDE_ORDER.get(p.side, 9), p.index))
    return Layout(family=str(entry.get("family") or "This machine"),
                  known=known,
                  source=str(entry.get("source") or ""),
                  ports=ports)


def lookup(machine: Optional[Dict[str, Any]]) -> Layout:
    """Best layout for this machine. Never raises, always returns something."""
    db = load_json("port_layouts.json")
    layouts = db.get("layouts") or []
    hay = _haystack(machine or {})

    if hay:
        best: Optional[Dict[str, Any]] = None
        best_len = 0
        for entry in layouts:
            for pattern in entry.get("match") or []:
                try:
                    if re.search(pattern, hay, re.IGNORECASE):
                        # Most specific pattern wins, same rule as the dGPU table.
                        if len(pattern) > best_len:
                            best, best_len = entry, len(pattern)
                        break
                except re.error:
                    continue
        if best is not None:
            return _build(best, known=True)

    for entry in layouts:
        if entry.get("id") == "generic":
            return _build(entry, known=False)
    return Layout(family="This machine", known=False, source="none")
