"""Standalone HTML report - the one you send to someone.

Self-contained: no external CSS, no fonts, no scripts. Opens on any phone, which
matters because the buyer is standing in Hall Road holding one.
"""

from __future__ import annotations

import html
from typing import Any, Dict, List

from ..engine import result as R
from ..scoring import rubric

SEV_COLOUR = {
    R.CRITICAL: "#c62828",
    R.MAJOR: "#d1690a",
    R.WARN: "#b8860b",
    R.INFO: "#1f5f9e",
}


def _esc(value: Any) -> str:
    return html.escape(str(value if value is not None else ""))


def _pkr(value: Any) -> str:
    if value in (None, ""):
        return "-"
    try:
        return f"{int(value):,} PKR"
    except (TypeError, ValueError):
        return "-"


def build(report: R.Report) -> str:
    m = report.machine
    colour = rubric.verdict_colour(report.verdict)
    neg = report.negotiation

    def check_rows() -> str:
        out: List[str] = []
        for check in report.checks:
            pct = max(0.0, min(100.0, check.score))
            bar = "#1f9d55" if pct >= 80 else "#c98a00" if pct >= 55 else "#c62828"
            measured = check.scored and check.weight > 0
            score_cell = f"{pct:.0f}" if measured else "-"
            width = f"{pct:.0f}%" if measured else "0%"
            out.append(f"""
      <tr>
        <td class="lbl">{_esc(check.label)}</td>
        <td class="num">{score_cell}</td>
        <td class="bar"><div class="track"><div class="fill" style="width:{width};background:{bar}"></div></div></td>
        <td class="status s-{_esc(check.status)}">{_esc(check.status.upper())}</td>
        <td class="sum">{_esc(check.summary)}</td>
      </tr>""")
        return "".join(out)

    def finding_rows() -> str:
        rows: List[str] = []
        order = {R.CRITICAL: 0, R.MAJOR: 1, R.WARN: 2, R.INFO: 3}
        items = [(c, f) for c in report.checks for f in c.findings]
        items.sort(key=lambda p: order.get(p[1].severity, 9))
        for check, f in items:
            colour_ = SEV_COLOUR.get(f.severity, "#666")
            evidence = ", ".join(f"{k}: {v}" for k, v in list(f.evidence.items())[:4]
                                 if not isinstance(v, (dict, list)))
            cost = (f'<span class="cost">{_pkr(f.cost_pkr)}</span>'
                    if f.cost_pkr else "")
            block = ('<span class="blocking">BLOCKING</span>'
                     if f.blocking else "")
            rows.append(f"""
      <div class="finding">
        <div class="fhead">
          <span class="dot" style="background:{colour_}"></span>
          <span class="ftitle">{_esc(f.title)}</span>
          {block}
          <span class="fsev" style="color:{colour_}">{_esc(f.severity.upper())}</span>
          {cost}
        </div>
        <div class="fdetail">{_esc(f.detail)}</div>
        <div class="fev">{_esc(evidence)}</div>
      </div>""")
        return "".join(rows)

    def cost_rows() -> str:
        if not neg.items:
            return '<tr><td colspan="2">No repairable defects found.</td></tr>'
        return "".join(
            f"<tr><td>{_esc(i['title'])}</td><td class='num'>{_pkr(i['cost_pkr'])}</td></tr>"
            for i in neg.items)

    basis = ""
    if neg.price_basis == "market" and neg.market_price_pkr:
        basis = (f"market {_pkr(neg.market_price_pkr)} - repairs "
                 f"{_pkr(neg.total_repair_pkr)}")
    if neg.suggested_offer_pkr is not None:
        asking = (f"<span>Asking {_pkr(neg.asking_price_pkr)}</span>"
                  if neg.asking_price_pkr else "")
        offer = (f"<div class='offer'>{asking}"
                 f"<strong>Offer {_pkr(neg.suggested_offer_pkr)}</strong>"
                 f"<span>ceiling {_pkr(neg.max_offer_pkr)}</span>"
                 + (f"<em>{basis}</em>" if basis else "")
                 + "</div>")
    elif neg.asking_price_pkr:
        offer = f"<div class='offer'><strong>Walk away</strong></div>"
    else:
        offer = (f"<div class='offer'><strong>Deduct "
                 f"{_pkr(neg.total_repair_pkr)} from the price</strong></div>")

    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Used Laptop Inspector - {_esc(m.get('family') or m.get('model'))}</title>
<style>
  :root {{ color-scheme: light; }}
  * {{ box-sizing: border-box; }}
  body {{ margin:0; background:#eef0f3; font:14px/1.45 -apple-system,"Segoe UI",Roboto,sans-serif; color:#1a1f26; }}
  .page {{ max-width: 880px; margin: 0 auto; background:#fff; }}
  header {{ background:#111a24; color:#fff; padding:22px 26px; display:flex; gap:18px; align-items:center; flex-wrap:wrap; }}
  .brand {{ flex:1 1 320px; min-width:240px; }}
  .kicker {{ font-size:11px; letter-spacing:.14em; color:#7f8fa3; text-transform:uppercase; }}
  h1 {{ font-size:22px; margin:4px 0 6px; }}
  .sub {{ color:#9fb0c3; font-size:12.5px; }}
  .badge {{ border-radius:6px; padding:14px 18px; text-align:center; min-width:150px; }}
  .badge .v {{ font-size:19px; font-weight:700; letter-spacing:.02em; }}
  .badge .s {{ font-size:13px; opacity:.92; }}
  .reasons {{ padding:14px 26px; background:#f7f8fa; border-bottom:1px solid #e3e6ea; font-size:13px; color:#333c47; }}
  section {{ padding:18px 26px; border-bottom:1px solid #e9ecef; }}
  h2 {{ font-size:11px; letter-spacing:.12em; text-transform:uppercase; color:#111a24; margin:0 0 12px; }}
  table {{ width:100%; border-collapse:collapse; font-size:13px; }}
  th {{ text-align:left; font-size:10.5px; letter-spacing:.08em; color:#6b7684; text-transform:uppercase; padding-bottom:6px; }}
  td {{ padding:6px 0; border-bottom:1px solid #f0f2f4; vertical-align:middle; }}
  td.num {{ text-align:right; font-variant-numeric:tabular-nums; white-space:nowrap; }}
  .track {{ height:7px; background:#e7eaee; border-radius:4px; overflow:hidden; }}
  .fill {{ height:100%; }}
  .status {{ font-size:10px; letter-spacing:.06em; color:#6b7684; }}
  .s-fail {{ color:#c62828; }} .s-warn {{ color:#b8860b; }} .s-ok {{ color:#1f9d55; }}
  .sum {{ color:#5d6773; font-size:12px; }}
  .finding {{ padding:9px 0; border-bottom:1px solid #f0f2f4; }}
  .fhead {{ display:flex; align-items:baseline; gap:8px; flex-wrap:wrap; }}
  .dot {{ width:8px; height:8px; border-radius:50%; display:inline-block; }}
  .ftitle {{ font-weight:600; }}
  .fsev {{ font-size:10px; letter-spacing:.08em; margin-left:auto; }}
  .cost {{ font-size:12px; color:#111; font-weight:600; }}
  .blocking {{ font-size:9.5px; background:#c62828; color:#fff; padding:1px 6px; border-radius:3px; letter-spacing:.06em; }}
  .fdetail {{ color:#4a5461; font-size:12.5px; margin:3px 0 2px 16px; }}
  .fev {{ color:#8b95a1; font-size:11.5px; margin-left:16px; font-family:ui-monospace,Menlo,monospace; }}
  .offer {{ margin-top:12px; background:#f7f8fa; border:1px solid #dfe3e8; border-radius:6px; padding:12px 14px; display:flex; gap:16px; align-items:center; flex-wrap:wrap; }}
  .offer strong {{ font-size:17px; }}
  .offer span {{ color:#6b7684; font-size:12px; }}
  footer {{ padding:14px 26px 24px; color:#8b95a1; font-size:11.5px; }}
  @media print {{ body {{ background:#fff; }} .page {{ max-width:none; }} }}
</style></head>
<body><div class="page">
<header>
  <div class="brand">
    <div class="kicker">Used Laptop Inspector</div>
    <h1>{_esc(m.get('family') or m.get('model') or 'Unknown machine')}</h1>
    <div class="sub">{_esc(m.get('cpu'))} &middot; {_esc(m.get('ram_gb'))} GB &middot;
      {_esc(', '.join(m.get('gpus') or []))}</div>
    <div class="sub">Serial {_esc(m.get('serial'))} &middot; BIOS {_esc((m.get('bios') or {}).get('version'))}</div>
  </div>
  <div class="badge" style="background:{colour}">
    <div class="v">{_esc(report.verdict)}</div>
    <div class="s">{report.score:.0f} / 100</div>
  </div>
</header>
<div class="reasons">{'<br>'.join('- ' + _esc(r) for r in report.verdict_reasons)}</div>
<section><h2>Score breakdown</h2><table>
  <tr><th>Check</th><th style="text-align:right">Score</th><th></th><th></th><th>Detail</th></tr>
  {check_rows()}
</table></section>
<section><h2>What it costs to put right</h2>
<table>{cost_rows()}</table>
{offer}
<div style="margin-top:10px;color:#4a5461;font-size:12.5px">{_esc(neg.advice)}</div>
</section>
<section><h2>Findings</h2>{finding_rows() or '<div class="fdetail">None.</div>'}</section>
<footer>Generated {_esc(report.generated_at[:19])} &middot; v{_esc(report.tool_version)}
 &middot; offline, no telemetry &middot; every score is backed by the evidence above.</footer>
</div></body></html>"""


def write(report: R.Report, path: str) -> str:
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(build(report))
    return path
