# Stitch prompt

Paste each block into Google Stitch. Prompt 1 is the screen that matters; the
others are optional variations.

---

## Prompt 1 — main results screen (paste this)

```
Design a desktop app screen for "Used Laptop Inspector", a Windows diagnostic tool
used by buyers at a used-laptop market in Pakistan. Someone has 10 minutes at a
counter to decide whether to buy a second-hand laptop, so the screen must answer
one question instantly: BUY, NEGOTIATE, or WALK AWAY.

Product context: the app scans a laptop (CPU, RAM, drive SMART health, battery
wear, thermals, GPU) and produces a score out of 100, a verdict, and a
counter-offer in PKR. The killer feature is negotiation math: every defect has a
repair cost, and the app tells you what to offer.

Layout, top to bottom:

1. TOP BAR (64px tall, dark). Left: a small shield app icon and the product name
   in small caps letterspaced type. Next to it the detected machine in bold:
   "Lenovo ThinkPad W520". Right side: a ghost "Claims" button, a "Fast" toggle,
   a primary blue "Run scan" button, and an "Export" dropdown.

2. HERO BAND (about 140px). This is the emotional centre of the screen.
   - Far left: a circular score ring, 116px, showing "73" in the middle and
     "OF 100" beneath it. The ring arc is amber.
   - Middle: the verdict in huge type, "NEGOTIATE", in amber, with one or two
     short reason lines in grey beneath it.
   - Right: three small stat blocks side by side, each a tiny letterspaced
     caption above a bold number: "REPAIR EXPOSURE 25,100 PKR",
     "SUGGESTED OFFER 57,390 PKR", "FINDINGS 11".
   - The whole band has a very subtle horizontal gradient tinted with the verdict
     colour, fading into the dark background. Amber glow on the left only.

3. MAIN BODY, two columns split roughly 320px / rest.
   LEFT RAIL, a vertical list of seven rows: "Verdict & negotiation",
   "Specs & authenticity", "Battery", "Storage health", "Thermals & throttling",
   "GPU sanity", "Discrete GPU presence". Each row has the check name on the
   left, a score number on the right coloured green/amber/red, a one-line grey
   summary underneath, and a thin 3px progress bar at the bottom. The selected
   row has a soft lighter background and a 3px vertical accent bar on its left
   edge. No borders between rows, just generous spacing.

   RIGHT PANE, a stack of cards with 10px radius:
   - Card "WHAT IT COSTS TO PUT RIGHT": a two-column list of defects and their
     cost in PKR, right-aligned bold numbers. A divider, then "Total repair
     exposure 25,100 PKR". Another divider, then the counter-offer line in
     bright green: "Asking 85,000 PKR   Offer 57,390 PKR   Ceiling 59,900 PKR",
     followed by two lines of grey explanatory text.
   - Card "SCORE BREAKDOWN": a clean table with columns CHECK / SCORE / WEIGHT /
     STATUS. Scores coloured by health, status as small letterspaced labels.

4. FOOTER (36px): a thin progress bar and a small status line
   "Scan complete in 32s".

Style:
- Dark theme, near-black background (#080B10), cards one step lighter (#0F141B),
  hairline borders (#212C39) rather than heavy strokes.
- One structural accent: a confident blue (#4C9AFF) for the primary action.
- Semantic colour only where it means something: green #2ECC71 healthy,
  amber #FFB02E caution, red #FF5C5C failure.
- Typography: Segoe UI Variable / Inter. Big verdict at 30px bold, check names
  13px semibold, body 12.5px, captions 10px uppercase with 1.5px letter spacing.
- Numbers use tabular figures. Money always ends in "PKR".
- Dense but breathable: 8px spacing rhythm, 10px card radius, no drop shadows,
  no gradients except the hero tint.
- Feels like a professional instrument, not a consumer app. Think a mechanic's
  diagnostic tablet, not a fitness tracker.
```

---

## Prompt 2 — empty state

```
Design the empty state of the same desktop app, "Used Laptop Inspector", dark
theme. No scan has run yet.

A single centred card, 520px wide, on a near-black background: the shield app
icon at 64px, a heading "Ready to inspect", one short grey sentence explaining
that one scan reads firmware, battery, drive SMART counters and thermals, then a
primary blue "Run scan" button centred beneath it.

Top bar is present but the machine name reads "No machine scanned". The hero band
shows an empty score ring with "--" in the middle, the word "No scan yet" in dim
grey, and three stat blocks reading "--". The left rail shows all seven checks
with "--" scores and grey placeholder summaries.

Keep the same dark palette, blue accent, and typographic scale as the results
screen. The mood is calm and ready, not empty or broken.
```

---

## Prompt 3 — finding detail state

```
Design the detail pane of the same app, dark theme, showing a single check's
results: "Storage health", score 0, status FAIL.

At the top a compact header card: check name in 17px semibold, a one-line grey
summary listing the drives, and the score "0" in red at 34px on the right.

Below it, a stack of finding cards. Each card is a rounded panel with a 3px
vertical colour strip on its left edge indicating severity. Inside: the finding
title in semibold, a red "BLOCKING" pill badge where applicable, a severity label
in small letterspaced caps on the right, a two-line explanation in grey, a line
of monospace evidence such as
"pending_sectors=24, power_on_hours=36768", and the repair cost
"9,000 PKR" in bold.

Then a section "EVIDENCE": a two-column key/value table in a panel, monospace
values, listing per-drive SMART numbers - power-on hours, reallocated sectors,
pending sectors, temperature.

Colour code: red for the failing drive's findings, amber for warnings, blue for
informational. Same typography and spacing rhythm as the main screen.
```

---

## Prompt 4 — app icon

```
Design a flat app icon for "Used Laptop Inspector", a Windows diagnostic tool
that protects people buying second-hand laptops.

Square icon with rounded corners (22% radius), on a deep charcoal-to-black
vertical gradient. Centred: a clean white shield outline with a flat top and a
tapered point at the bottom. Across the shield runs a bold horizontal amber band,
like a scanner sweep. Below the band, a small amber check mark.

Must stay readable at 16x16 pixels: thick strokes, no fine detail, no text, no
perspective. Flat vector style, two colours plus the background. The amber is
#FFB02E, the shield near-white #E8EEF7.
```

---

## Notes for using the output

- Ask Stitch for **desktop 1440x940** frames, not mobile.
- If it returns light-mode designs, restate: "dark theme only, near-black
  #080B10 background".
- The screen it will get wrong is the hero band — it tends to make the verdict
  small and the stats big. Insist the verdict word is the largest thing on screen
  after the score number.
- Once you have a design you like, send me the screenshot and I'll implement it
  against the existing `ui/theme.py` and `ui/main_window.py` structure.
