"""Entry point for the bootable WinPE build.

Same engine as the desktop app, but with no GUI, no Qt, and no dependency on the
machine's installed Windows. That last part is the point: when you boot your own
image, the seller's Windows - its drivers, its tampered SMART tools, its rootkits
- is not running, so it cannot lie to the scan.

What it can still get wrong, honestly:
  * SMBIOS and ACPI come from the firmware. A seller who reflashes the BIOS can
    still change what the machine says it is.
  * The GPU load test needs D3D11, which WinPE does not have. It is skipped and
    the report says so rather than pretending.
  * PnP enumeration in WinPE sees only devices with drivers present in the image,
    so the peripherals check is reported as "not visible in this environment"
    instead of claiming hardware is missing.
"""

from __future__ import annotations

import os
import sys
import time
import traceback
from typing import Any

from laptop_inspector import TOOL_NAME, __version__
from laptop_inspector.engine.context import Options
from laptop_inspector.engine.inspector import Inspector
from laptop_inspector.report import html_report, json_report, pdf_report


def _root() -> str:
    """The folder the exe was launched from - the USB stick, normally."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.getcwd()


def _progress(stage: str, fraction: float, message: str) -> None:
    bar = "#" * int(max(0.0, min(1.0, fraction)) * 28)
    print(f"\r  [{bar:<28}] {message[:52]:<52}", end="", flush=True)


def _say(text: str = "") -> None:
    print("\r" + " " * 84 + "\r" + text, flush=True)


def main() -> int:
    root = _root()
    stamp = time.strftime("%Y%m%d-%H%M%S")
    out_dir = os.path.join(root, "reports")
    try:
        os.makedirs(out_dir, exist_ok=True)
    except OSError:
        out_dir = os.environ.get("TEMP") or root

    print()
    print(f"  {TOOL_NAME} {__version__} - boot environment scan")
    print(f"  writing to {out_dir}")
    print()

    # No network in WinPE by default, and no D3D11 to stress the GPU with.
    options = Options(skip_gpu_load=True, allow_market_search=False)

    started = time.time()
    try:
        report = Inspector(options, progress=_progress).run()
    except Exception:
        _say("The scan failed:")
        print(traceback.format_exc())
        return 2

    _say("")
    elapsed = time.time() - started

    model = (report.machine.get("family") or report.machine.get("model")
             or "Unknown machine")
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in model)[:40]
    base = os.path.join(out_dir, f"{safe}_{stamp}")

    written = []
    for suffix, writer in ((".json", json_report.write),
                           (".html", html_report.write),
                           (".pdf", pdf_report.build)):
        path = base + suffix
        try:
            writer(report, path)
            written.append(path)
        except Exception as exc:
            print(f"  could not write {suffix}: {exc}")

    print(f"  {model}")
    print(f"  score {report.score:.0f}/100 - {report.verdict}")
    neg = report.negotiation
    if neg.suggested_offer_pkr is not None:
        print(f"  offer {neg.suggested_offer_pkr:,} PKR "
              f"(ceiling {neg.max_offer_pkr:,})")
    elif neg.walk_away:
        print(f"  do not buy - {neg.walk_away_reason or 'blocking defect'}")
    print(f"  repairs {neg.total_repair_pkr:,} PKR over {len(neg.items)} item(s)")
    print()
    for path in written:
        print(f"  {path}")
    print(f"  finished in {elapsed:.0f}s")
    print()

    # WinPE drops to a command prompt when this returns, so pause by default.
    if os.environ.get("ULI_NO_PAUSE") != "1":
        try:
            input("  Press Enter to close.")
        except (EOFError, KeyboardInterrupt):
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
