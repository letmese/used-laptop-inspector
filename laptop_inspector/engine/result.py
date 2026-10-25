"""Result data model.

Everything the engine produces is a plain dataclass so it can be serialised to
JSON without dragging in pydantic. The Android companion app consumes the JSON,
so keep the field names stable.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional

# severity ladder, ordered
INFO = "info"
WARN = "warn"
MAJOR = "major"
CRITICAL = "critical"

SEVERITY_ORDER = {INFO: 0, WARN: 1, MAJOR: 2, CRITICAL: 3}

# check status
STATUS_OK = "ok"
STATUS_WARN = "warn"
STATUS_FAIL = "fail"
STATUS_UNAVAILABLE = "unavailable"
STATUS_ERROR = "error"


@dataclass
class Finding:
    """A single piece of evidence-backed bad news.

    `evidence` holds the numbers that produced the finding. The report always
    shows them - a bare score is worthless to a buyer at the counter.
    """

    id: str
    severity: str
    title: str
    detail: str = ""
    evidence: Dict[str, Any] = field(default_factory=dict)
    cost_pkr: Optional[int] = None
    cost_note: str = ""
    blocking: bool = False
    # Money worth spending, but not a defect: an SSD swap on a working HDD.
    # Kept out of the repair total so it cannot shrink the counter-offer as if
    # the machine were broken.
    upgrade: bool = False
    """True means 'do not buy this machine at any price' - a drive failing right
    now, a driver that resets under load, or a seller who lied about the specs.
    A worn battery is expensive but not blocking."""

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        return d


@dataclass
class CheckResult:
    key: str
    label: str
    status: str = STATUS_OK
    score: float = 100.0
    weight: float = 0.0
    summary: str = ""
    findings: List[Finding] = field(default_factory=list)
    data: Dict[str, Any] = field(default_factory=dict)
    duration_s: float = 0.0
    error: Optional[str] = None

    @property
    def scored(self) -> bool:
        """Checks that could not run must not drag the score around."""
        return self.status not in (STATUS_UNAVAILABLE, STATUS_ERROR)

    def worst_severity(self) -> str:
        sev = INFO
        for f in self.findings:
            if SEVERITY_ORDER.get(f.severity, 0) > SEVERITY_ORDER.get(sev, 0):
                sev = f.severity
        return sev

    def add(self, finding: Finding) -> None:
        self.findings.append(finding)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "status": self.status,
            "score": round(self.score, 1),
            "weight": self.weight,
            "summary": self.summary,
            "duration_s": round(self.duration_s, 2),
            "error": self.error,
            "findings": [f.to_dict() for f in self.findings],
            "data": self.data,
        }


@dataclass
class Negotiation:
    """The reason this tool is worth money."""

    asking_price_pkr: Optional[int] = None
    items: List[Dict[str, Any]] = field(default_factory=list)
    total_repair_pkr: int = 0
    suggested_offer_pkr: Optional[int] = None
    max_offer_pkr: Optional[int] = None
    discount_pct: Optional[float] = None
    advice: str = ""
    walk_away: bool = False
    walk_away_reason: str = ""

    # What the machine is worth before repairs, and what it is worth in its
    # current state. Without these the offer can only be derived from the
    # asking price, which rewards a seller for asking more.
    market_price_pkr: Optional[int] = None
    fair_value_pkr: Optional[int] = None
    price_basis: str = ""          # "market", "asking" or ""
    market_source: str = ""        # "manual", "stored", "search"
    market_note: str = ""
    upgrades: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Report:
    machine: Dict[str, Any] = field(default_factory=dict)
    checks: List[CheckResult] = field(default_factory=list)
    score: float = 0.0
    verdict: str = "NEGOTIATE"
    verdict_reasons: List[str] = field(default_factory=list)
    negotiation: Negotiation = field(default_factory=Negotiation)
    extras: Dict[str, Any] = field(default_factory=dict)
    claims: Dict[str, Any] = field(default_factory=dict)
    # Resolved once per scan, never inside finalise(): that runs on every
    # keystroke when the buyer edits the asking price.
    market: Dict[str, Any] = field(default_factory=dict)
    generated_at: str = ""
    tool_version: str = ""
    schema_version: str = ""
    duration_s: float = 0.0
    admin: bool = False
    platform: str = "windows"

    def check(self, key: str) -> Optional[CheckResult]:
        for c in self.checks:
            if c.key == key:
                return c
        return None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "tool_version": self.tool_version,
            "generated_at": self.generated_at,
            "platform": self.platform,
            "admin": self.admin,
            "duration_s": round(self.duration_s, 2),
            "machine": self.machine,
            "claims": self.claims,
            "score": round(self.score, 1),
            "verdict": self.verdict,
            "verdict_reasons": self.verdict_reasons,
            "checks": [c.to_dict() for c in self.checks],
            "negotiation": self.negotiation.to_dict(),
            "market": self.market,
            "extras": self.extras,
        }


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")
