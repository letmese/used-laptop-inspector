# Scoring rubric

Everything on this page is tunable, and everything is in one place:
`laptop_inspector/scoring/rubric.py` for weights and thresholds,
`laptop_inspector/data/costs_pkr.json` for money.

## Weights

| Check | Weight | Why |
|---|---:|---|
| Storage health | 25 | A failing drive means the machine is unusable today. SMART is also the thing sellers hide. |
| Battery | 20 | Most lied-about part, and the most predictable repair cost. |
| Specs & authenticity | 20 | Covers "is this the machine you were sold" - and lying is disqualifying. |
| Thermals | 15 | A clogged heatsink is common, cheap to fix, and destroys sustained performance. |
| GPU sanity | 10 | Driver resets are rarer but fatal when present. |
| Discrete GPU presence | 10 | Detects the BIOS-disabled dGPU, which is invisible to every other tool. |
| Radios & peripherals | 8 | WiFi, Bluetooth, camera, Ethernet, modem, card reader, fingerprint, audio. Only devices that are **present and broken** cost points — absence is reported, never scored. |
| Screen, keyboard & ports | 12 | v2, interactive. Only counts when the buyer actually ran the tests. |

**Unavailable checks leave the denominator.** If storage cannot be read, the
remaining weights are renormalised over 75 instead of scoring the machine 0 for a
check that never ran. A report full of zeroes for missing data is worse than a
report that says "not available".

## Sub-scores

Each check starts at 100 and subtracts. The penalty table per severity is in the
check module, because the shape of the deduction is check-specific:

| Check | Deductions |
|---|---|
| Specs | critical -45, major -18, warn -7 |
| Battery | `100 - wear% x 1.6`, then -20 for >800 cycles, -8 for >400 |
| Storage | pending -100, realloc >50 -85, wear >90% -80, uncorrectable -40, wear >80% -40, SMART unreadable -> 45 |
| Thermal | mapped from `sustained / peak`: >=0.90 -> 100, 0.85 -> 92, 0.78 -> 80, 0.70 -> 62, 0.60 -> 40, else 18 |
| GPU | TDRs >=10 -55, >=3 -30, >=1 -12, device-removed -60, PnP error -30 |
| dGPU | present 100, absent-but-optional 70, absent-but-standard 45, was-there-and-gone 25 |

Storage takes the **worst** drive score, not the average. One failing drive in a
two-drive machine is the whole story.

## Interactive tests (v2)

Screen, keyboard and port results are scored like any other finding: major -22,
warn -12, informational 0. If the buyer skips all three the check reports
`unavailable` and leaves the denominator, so a machine is never penalised for
tests that were never run.

The costs are what make these worth doing: a backlight bleed is an 18,000 PKR
panel, two dead keys a 5,000 PKR keyboard assembly, a dead USB port 3,500 PKR.
They land in the counter-offer exactly like a failing drive.

## Verdict

```
blockers = findings with blocking=True

if blockers:                          WALK AWAY
elif score < 55:                      WALK AWAY
elif score >= 80 and no major:        BUY
elif score >= 80 and majors:          NEGOTIATE
else:                                 NEGOTIATE
```

Then a money override: if the repair total exceeds 45% of the asking price, the
verdict becomes WALK AWAY regardless of score. At that point the "discount" is
most of the machine's value, and the seller will not go there.

### What counts as blocking

- Sectors pending reallocation, uncorrectable errors, >50 reallocated sectors,
  SSD past 90% endurance, NVMe critical warning
- Display driver reset under load, or the stress worker crashing
- 10+ TDRs in 180 days
- Seller lied about CPU, RAM size, or drive type (SATA sold as NVMe, HDD sold as SSD)

Deliberately **not** blocking: worn battery, missing dGPU, throttling, no OEM
key, mechanical drive. Those are priced, not refused.

## Negotiation

```
total   = sum of cost_pkr across all findings (deduplicated by title)
buffer  = total x 10%            (risk_buffer_pct)
offer   = asking - total - buffer
ceiling = asking - total
```

The buffer exists because the scan cannot see everything - a machine with a dead
battery and a hot drive usually has one more thing wrong with it.

Costs are in `data/costs_pkr.json`. They are Lahore used-parts prices as of late
2026 and they are the numbers that land in the counter-offer, so keep them
current. Changing one number changes every report.

## Tuning

- **Weights** -> `rubric.WEIGHTS`. They are renormalised, so they do not have to
  sum to 100, but keeping them summing to 100 makes the PDF table readable.
- **Thresholds** -> `rubric.BUY_THRESHOLD`, `rubric.NEGOTIATE_THRESHOLD`.
- **Walk-away discount** -> `costs_pkr.json` -> `negotiation.walk_away_discount_pct`.
- **Risk buffer** -> `negotiation.risk_buffer_pct`.
- **Model database** -> `data/models.json`. `dgpu_standard: true` means every SKU
  shipped with a discrete GPU, so its absence is a hard finding rather than a
  possible factory variant. Getting this flag wrong is the difference between a
  warning and a 22,000 PKR deduction.
