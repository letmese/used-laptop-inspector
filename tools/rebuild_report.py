"""Rebuild a Report object from saved JSON and re-render the PDF.

Lets me iterate on report layout without re-running an elevated scan.
"""
import json
import sys

sys.path.insert(0, r"G:\AntigravityProjects\used-laptop-inspector")
from laptop_inspector.engine import result as R
from laptop_inspector.report import pdf_report, html_report


def load(path):
    d = json.load(open(path, encoding="utf-8"))
    report = R.Report(
        machine=d["machine"], score=d["score"], verdict=d["verdict"],
        verdict_reasons=d["verdict_reasons"], claims=d.get("claims") or {},
        generated_at=d["generated_at"], tool_version=d["tool_version"],
        schema_version=d["schema_version"], duration_s=d.get("duration_s", 0),
        admin=d.get("admin", False), extras=d.get("extras") or {},
        market=d.get("market") or {},
    )
    for c in d["checks"]:
        check = R.CheckResult(
            key=c["key"], label=c["label"], status=c["status"], score=c["score"],
            weight=c["weight"], summary=c.get("summary", ""), data=c.get("data") or {},
            duration_s=c.get("duration_s", 0), error=c.get("error"))
        for f in c["findings"]:
            check.findings.append(R.Finding(
                id=f["id"], severity=f["severity"], title=f["title"],
                detail=f.get("detail", ""), evidence=f.get("evidence") or {},
                cost_pkr=f.get("cost_pkr"), cost_note=f.get("cost_note", ""),
                blocking=f.get("blocking", False)))
        report.checks.append(check)
    n = d["negotiation"]
    # Every field, not just the ones that existed when this helper was written:
    # a partial rebuild silently drops the market basis and the offer stops
    # explaining itself.
    report.negotiation = R.Negotiation(
        asking_price_pkr=n.get("asking_price_pkr"), items=n.get("items") or [],
        total_repair_pkr=n.get("total_repair_pkr", 0),
        suggested_offer_pkr=n.get("suggested_offer_pkr"),
        max_offer_pkr=n.get("max_offer_pkr"), discount_pct=n.get("discount_pct"),
        advice=n.get("advice", ""), walk_away=n.get("walk_away", False),
        market_price_pkr=n.get("market_price_pkr"),
        fair_value_pkr=n.get("fair_value_pkr"),
        price_basis=n.get("price_basis", ""),
        market_source=n.get("market_source", ""),
        market_note=n.get("market_note", ""))
    return report


if __name__ == "__main__":
    rep = load("out/report.json")
    pdf_report.build(rep, "out/report.pdf")
    html_report.write(rep, "out/report.html")
    print("rebuilt pdf/html from json:", rep.verdict, rep.score)
