"""JSON output - the contract with the Android companion app.

Field names are frozen by schema/report.schema.json. Bump SCHEMA_VERSION in
laptop_inspector/__init__.py for anything breaking.
"""

from __future__ import annotations

import json
from typing import Any, Dict

from ..engine import result as R


def build(report: R.Report) -> Dict[str, Any]:
    return report.to_dict()


def write(report: R.Report, path: str, indent: int = 2) -> str:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(build(report), fh, indent=indent, ensure_ascii=False)
    return path
