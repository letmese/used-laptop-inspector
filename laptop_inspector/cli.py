"""Headless entry point.

    python -m laptop_inspector.cli
    python -m laptop_inspector.cli --asking 85000 --claim cpu=i7-2820QM --claim ram=16GB
    python -m laptop_inspector.cli --fast --json out.json --pdf out.pdf

This is the path that will run from WinPE later: it imports nothing from PySide6.
"""

from __future__ import annotations

import argparse
import ctypes
import os
import sys
import time
from typing import Any, Dict, List, Optional

from . import TOOL_NAME, __version__
from .engine import winapi
from .engine.context import Options
from .engine.inspector import Inspector
from .report import html_report, json_report, pdf_report


def _parse_claims(pairs: Optional[List[str]]) -> Dict[str, Any]:
    claims: Dict[str, Any] = {}
    for item in pairs or []:
        if "=" not in item:
            continue
        key, value = item.split("=", 1)
        key = key.strip().lower()
        value = value.strip()
        if key in ("ram_gb", "storage_gb"):
            try:
                claims[key] = float(value)
                continue
            except ValueError:
                pass
        claims[key] = value
    return claims


def elevate() -> bool:
    """Relaunch self elevated. Returns True if a new process was started."""
    if winapi.is_admin():
        return False
    try:
        params = " ".join(f'"{a}"' for a in sys.argv[1:])
        if getattr(sys, "frozen", False):
            exe, args = sys.executable, params
        else:
            exe = sys.executable
            args = f'"{os.path.abspath(sys.argv[0])}" {params}'
        rc = ctypes.windll.shell32.ShellExecuteW(
            None, "runas", exe, args, None, 1)
        return rc > 32
    except Exception:
        return False


def _progress(key: str, fraction: float, text: str) -> None:
    width = 28
    filled = int(width * fraction)
    bar = "#" * filled + "-" * (width - filled)
    sys.stdout.write(f"\r  [{bar}] {fraction * 100:3.0f}%  {text[:52]:<52}")
    sys.stdout.flush()


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="laptop-inspector",
        description=f"{TOOL_NAME} v{__version__} - score a used laptop before you buy it.")
    parser.add_argument("--json", metavar="PATH", help="write the JSON result")
    parser.add_argument("--pdf", metavar="PATH", help="write the one-page PDF report")
    parser.add_argument("--html", metavar="PATH", help="write a standalone HTML report")
    parser.add_argument("--asking", type=int, metavar="PKR",
                        help="seller's asking price, for the counter-offer")
    parser.add_argument("--market", type=int, metavar="PKR",
                        help="used-market price for this model. The offer is "
                             "built from this, not from the asking price")
    parser.add_argument("--no-market-search", action="store_true",
                        help="do not look up a used price online")
    parser.add_argument("--claim", action="append", metavar="KEY=VALUE",
                        help="what the seller claimed: cpu=, ram_gb=, storage_gb=, "
                             "storage_type=, gpu=, screen=")
    parser.add_argument("--thermal-seconds", type=float, default=45.0,
                        help="length of the CPU load test (default 45)")
    parser.add_argument("--gpu-seconds", type=float, default=12.0,
                        help="length of the GPU load test (default 12)")
    parser.add_argument("--fast", action="store_true",
                        help="short load tests, for a quick pass at the counter")
    parser.add_argument("--no-thermal", action="store_true", help="skip the CPU load test")
    parser.add_argument("--no-gpu-load", action="store_true", help="skip the GPU stress")
    parser.add_argument("--elevate", action="store_true",
                        help="relaunch as administrator (required for SMART)")
    parser.add_argument("--quiet", action="store_true", help="no progress output")
    args = parser.parse_args(argv)

    if args.elevate and not winapi.is_admin():
        if elevate():
            print("Relaunched elevated. Complete the UAC prompt.")
            return 0
        print("Elevation was refused; continuing without SMART access.")

    options = Options(
        thermal_seconds=args.thermal_seconds,
        gpu_seconds=args.gpu_seconds,
        skip_thermal=args.no_thermal,
        skip_gpu_load=args.no_gpu_load,
        fast=args.fast,
        claims=_parse_claims(args.claim),
        asking_price_pkr=args.asking,
        market_price_pkr=args.market,
        allow_market_search=not args.no_market_search,
    )

    print(f"{TOOL_NAME} v{__version__}")
    if not winapi.is_admin():
        print("  ! not elevated - SMART and NVMe health will be unavailable")
        print("    re-run with --elevate for a complete scan\n")
    else:
        print()

    started = time.time()
    inspector = Inspector(options, progress=None if args.quiet else _progress)
    report = inspector.run()
    if not args.quiet:
        sys.stdout.write("\r" + " " * 100 + "\r")

    print(f"\n  {report.machine.get('family') or report.machine.get('model')}")
    print(f"  {report.machine.get('cpu')}  |  {report.machine.get('ram_gb')} GB")
    print()
    for check in report.checks:
        bar = "#" * int(check.score / 5) + "." * (20 - int(check.score / 5))
        print(f"  {check.label:<24} {bar} {check.score:5.1f}  {check.summary[:44]}")
    print()
    print(f"  SCORE   {report.score:.0f}/100")
    print(f"  VERDICT {report.verdict}")
    for reason in report.verdict_reasons:
        print(f"          {reason}")
    print()
    neg = report.negotiation
    if neg.items:
        print(f"  Repair exposure {neg.total_repair_pkr:,} PKR")
        for item in neg.items[:5]:
            print(f"    - {item['title'][:60]:<60} {item['cost_pkr']:>8,}")
        if neg.suggested_offer_pkr is not None:
            print(f"  Suggested offer {neg.suggested_offer_pkr:,} PKR "
                  f"(ceiling {neg.max_offer_pkr:,})")
    print(f"\n  {neg.advice}")

    written = []
    for path, writer in ((args.json, json_report.write),
                         (args.html, html_report.write),
                         (args.pdf, pdf_report.build)):
        if not path:
            continue
        parent = os.path.dirname(os.path.abspath(path))
        try:
            os.makedirs(parent, exist_ok=True)
        except OSError:
            pass
        written.append(writer(report, path))
    if written:
        print("\n  Written:")
        for path in written:
            print(f"    {path}")
    print(f"\n  Completed in {time.time() - started:.1f}s")
    return 0 if report.verdict != "WALK AWAY" else 2


if __name__ == "__main__":
    raise SystemExit(main())
