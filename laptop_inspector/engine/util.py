"""Small parsing and classification helpers shared by the checks."""

from __future__ import annotations

import datetime as _dt
import re
from typing import Any, Dict, List, Optional

_WMI_DATE = re.compile(r"/Date\((-?\d+)([+-]\d{4})?\)/")


def parse_wmi_date(value: Any) -> Optional[_dt.datetime]:
    """CIM datetimes arrive as '/Date(1528934400000)/' through ConvertTo-Json."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        try:
            return _dt.datetime.fromtimestamp(float(value) / 1000.0)
        except Exception:
            return None
    text = str(value).strip()
    m = _WMI_DATE.search(text)
    if m:
        try:
            return _dt.datetime.fromtimestamp(int(m.group(1)) / 1000.0)
        except Exception:
            return None
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y%m%d%H%M%S.000000+000"):
        try:
            return _dt.datetime.strptime(text[:19], fmt)
        except Exception:
            continue
    try:
        return _dt.datetime.fromisoformat(text.replace("Z", "+00:00")).replace(tzinfo=None)
    except Exception:
        return None


def fmt_date(value: Any) -> str:
    d = parse_wmi_date(value)
    return d.strftime("%Y-%m-%d") if d else ""


def human_bytes(size: Any) -> str:
    try:
        n = float(size)
    except (TypeError, ValueError):
        return ""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1000 or unit == "TB":
            return f"{n:.0f} {unit}" if unit in ("B", "KB") else f"{n:.1f} {unit}"
        n /= 1000.0
    return f"{n:.1f} TB"


def gb(size_bytes: Any) -> Optional[float]:
    """GiB - correct for RAM, where 12 GB really is 12 x 1024^3."""
    try:
        return round(float(size_bytes) / (1024 ** 3), 1)
    except (TypeError, ValueError):
        return None


def gb_decimal(size_bytes: Any) -> Optional[float]:
    """Decimal GB - correct for drives, where a 256 GB SSD is 256e9 bytes."""
    try:
        return round(float(size_bytes) / 1e9)
    except (TypeError, ValueError):
        return None


# --------------------------------------------------------------------------
# GPU classification
# --------------------------------------------------------------------------
_INTEGRATED_MARKERS = (
    "intel", "hd graphics", "uhd graphics", "iris", "radeon graphics",
    "vega 8", "vega 11", "radeon(tm) graphics", "microsoft basic display",
    "microsoft remote display", "parsec", "virtual", "displaylink",
)
_DISCRETE_MARKERS = (
    "nvidia", "geforce", "quadro", "rtx", "gtx", "mx1", "mx2", "mx3", "mx4",
    "mx5", "radeon pro", "radeon rx", "firepro", "arc a", "arc pro",
)


def classify_gpu(name: str) -> str:
    """'integrated' | 'discrete' | 'virtual' | 'unknown'."""
    low = (name or "").lower()
    if any(k in low for k in ("microsoft basic", "microsoft remote", "virtual",
                              "displaylink", "parsec", "meta virtual")):
        return "virtual"
    # NVIDIA / explicit discrete names win over the Intel prefix rule
    if any(k in low for k in _DISCRETE_MARKERS):
        # "Intel Iris Xe MAX" style hybrid naming is rare; treat vendor Intel as iGPU
        if low.startswith("intel") and "arc" not in low:
            return "integrated"
        return "discrete"
    if any(k in low for k in _INTEGRATED_MARKERS):
        return "integrated"
    return "unknown"


def short_gpu(name: str) -> str:
    return re.sub(r"\s+", " ", (name or "").replace("(R)", "").replace("(TM)", "")).strip()


# --------------------------------------------------------------------------
# SMBIOS enums
# --------------------------------------------------------------------------
MEMORY_TYPES = {
    20: "DDR", 21: "DDR2", 22: "DDR2 FB-DIMM", 24: "DDR3", 26: "DDR4",
    27: "LPDDR", 28: "LPDDR2", 29: "LPDDR3", 30: "LPDDR4", 34: "DDR5",
    35: "LPDDR5",
}
FORM_FACTORS = {
    8: "DIMM", 12: "SODIMM", 13: "SRIMM", 0: "Unknown",
}
BUS_TYPES = {
    0: "unknown", 3: "ATA", 7: "USB", 8: "RAID", 10: "SAS", 11: "SATA",
    12: "SD", 13: "eMMC", 14: "virtual", 16: "Storage Spaces", 17: "NVMe",
    18: "SCM", 19: "UFS",
}
MEDIA_TYPES = {0: "unspecified", 3: "HDD", 4: "SSD", 5: "SCM"}


def memory_type_name(code: Any) -> str:
    try:
        return MEMORY_TYPES.get(int(code), "")
    except (TypeError, ValueError):
        return ""


def bus_type_name(code: Any) -> str:
    try:
        return BUS_TYPES.get(int(code), f"bus {code}")
    except (TypeError, ValueError):
        return "unknown"


def media_type_name(code: Any) -> str:
    try:
        return MEDIA_TYPES.get(int(code), "unknown")
    except (TypeError, ValueError):
        return "unknown"


PLACEHOLDER_SERIALS = {
    "", "0", "none", "default string", "to be filled by o.e.m.",
    "to be filled by oem", "system serial number", "not applicable",
    "not available", "invalid", "unknown", "0123456789",
}


def is_placeholder(value: Any) -> bool:
    if value is None:
        return True
    return str(value).strip().lower() in PLACEHOLDER_SERIALS


def as_list(value: Any) -> List[Dict[str, Any]]:
    if value is None:
        return []
    if isinstance(value, list):
        return [v for v in value if isinstance(v, dict)]
    if isinstance(value, dict):
        return [value]
    return []
