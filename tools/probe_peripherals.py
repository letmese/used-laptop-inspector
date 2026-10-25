"""Probe the radio / peripheral collector and run the check against it."""

import sys
import time

sys.path.insert(0, ".")

from laptop_inspector.engine import powershell as ps
from laptop_inspector.engine.checks import peripherals
from laptop_inspector.engine.context import Context

t0 = time.time()
data = ps.collect_peripherals()
print(f"collector: {time.time() - t0:.1f}s")

ctx = Context()
ctx.peripherals = data

check = peripherals.run(ctx)
print(f"  status : {check.status}")
print(f"  score  : {check.score}")
print(f"  summary: {check.summary}")
print(f"  present: {check.data.get('present')}")
for finding in check.findings:
    print(f"    [{finding.severity:>8}] {finding.title}")
    if finding.cost_pkr:
        print(f"               cost {finding.cost_pkr:,} PKR")

empty = peripherals.run(Context())
print(f"\nempty -> status={empty.status} score={empty.score} "
      f"summary={empty.summary!r}")
