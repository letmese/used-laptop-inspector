"""Negotiation math - the reason this tool is worth paying for.

Every defect that has a repair cost in PKR becomes a line item. The buyer reads
the counter-offer out loud, with the evidence attached, and the seller either
moves or does not.

**The offer is not derived from the asking price.** It used to be:

    offer = asking - repairs

which meant a seller asking 80,000 was offered 38,750 for a machine that got
18,750 at 60,000 - the same defects, a higher offer, purely for asking more.
That is backwards. The offer now comes from what the machine is worth:

    fair value = market price - repair cost
    offer      = fair value, less a little room to negotiate

The asking price is only used to judge the deal: is it above fair value (push
back), or already below it (pay it and stop arguing).

When no market price is known, the old asking-anchored maths runs, and the
advice says so out loud rather than hiding the flaw.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..engine import result as R
from ..engine.context import load_json


def _config() -> Dict[str, Any]:
    cfg = load_json("costs_pkr.json").get("negotiation") or {}
    return {
        "risk_buffer_pct": float(cfg.get("risk_buffer_pct", 10)),
        "walk_away_discount_pct": float(cfg.get("walk_away_discount_pct", 45)),
        # How far under fair value to open. The buyer needs somewhere to go.
        "opening_margin_pct": float(cfg.get("opening_margin_pct", 6)),
        # Above this share of the machine's value, the repairs make it a parts
        # machine. Quoting a token offer at that point is worse than useless.
        "write_off_repair_share": float(cfg.get("write_off_repair_share", 0.6)),
    }


def build(checks: List[R.CheckResult],
          asking_price: Optional[int],
          market: Optional[Dict[str, Any]] = None) -> R.Negotiation:
    cfg = _config()
    items: List[Dict[str, Any]] = []

    upgrades: List[Dict[str, Any]] = []
    for check in checks:
        for f in check.findings:
            if not f.cost_pkr or f.cost_pkr <= 0:
                continue
            if getattr(f, "upgrade", False):
                # Worth doing, but the machine is not broken. Charging it as a
                # repair both inflates the total and invites paying twice when
                # the same drive also has SMART faults.
                upgrades.append({"title": f.title, "cost_pkr": int(f.cost_pkr),
                                 "note": f.cost_note or ""})
                continue
            items.append({
                "check": check.key,
                "check_label": check.label,
                "title": f.title,
                "reason": f.cost_note or f.detail or "",
                "severity": f.severity,
                "blocking": f.blocking,
                "cost_pkr": int(f.cost_pkr),
            })

    # one line item per distinct defect; keep the most expensive if duplicated
    seen: Dict[str, Dict[str, Any]] = {}
    for item in items:
        key = item["title"].lower()
        if key not in seen or item["cost_pkr"] > seen[key]["cost_pkr"]:
            seen[key] = item
    items = sorted(seen.values(), key=lambda i: -i["cost_pkr"])

    total = sum(i["cost_pkr"] for i in items)
    neg = R.Negotiation(items=items, total_repair_pkr=total,
                        asking_price_pkr=asking_price)
    neg.upgrades = upgrades
    upgrade_note = ""
    if upgrades:
        extra = sum(u["cost_pkr"] for u in upgrades)
        upgrade_note = (f" Separately, {extra:,} PKR of optional upgrades are worth "
                        f"doing ({upgrades[0]['title'].rstrip('.')}) - that is your "
                        f"choice, not the seller's fault, and it is not in the "
                        f"figures above.")

    market = market or {}
    market_value = market.get("value_pkr")
    if market_value:
        neg.market_price_pkr = int(market_value)
        neg.market_source = market.get("source") or ""
        neg.market_note = market.get("note") or ""
        neg.fair_value_pkr = max(0, int(market_value) - total)

    blockers = [i for i in items if i["blocking"]]
    top = items[:3]
    examples = "; ".join(f"{i['title'].rstrip('.')} - about {i['cost_pkr']:,} PKR"
                         for i in top)

    # ---------------------------------------------------------------- priced
    if neg.fair_value_pkr is not None:
        fair = neg.fair_value_pkr
        neg.price_basis = "market"

        repair_share = (total / neg.market_price_pkr
                        if neg.market_price_pkr else 0.0)
        if repair_share >= cfg["write_off_repair_share"]:
            neg.walk_away = True
            neg.walk_away_reason = (f"repairs cost {repair_share:.0%} of its value")
            neg.suggested_offer_pkr = 0
            neg.max_offer_pkr = 0
            neg.discount_pct = None
            neg.advice = (
                f"Do not buy it. The defects cost {total:,} PKR against a machine "
                f"worth about {neg.market_price_pkr:,} - that is "
                f"{repair_share:.0%} of its value in repairs ({examples}). At that "
                f"ratio it is a parts machine, not something to resell. There is no "
                f"offer to make."
            )
            return neg

        if blockers:
            neg.walk_away = True
            neg.walk_away_reason = "blocking defect"
            neg.suggested_offer_pkr = 0
            neg.max_offer_pkr = 0
            neg.advice = (
                f"Walk away. {examples}. These are not bargaining points - they "
                f"are repairs the seller should have done before listing it. "
                f"Even at the {neg.market_price_pkr:,} PKR this model goes for, "
                f"it is not worth buying in this state."
            )
            return neg

        if asking_price:
            if asking_price <= fair:
                # Already cheaper than it is worth. Do not invent a discount.
                neg.suggested_offer_pkr = int(asking_price)
                neg.max_offer_pkr = int(asking_price)
                neg.discount_pct = 0.0
                neg.advice = (
                    f"Good buy. It is worth about {fair:,} PKR once the "
                    f"{total:,} PKR of defects are paid for, and the seller is "
                    f"asking {asking_price:,}. Pay it before someone else does."
                    + upgrade_note
                )
                return neg

            opening = int(fair * (1 - cfg["opening_margin_pct"] / 100.0))
            neg.suggested_offer_pkr = max(0, min(opening, int(asking_price)))
            neg.max_offer_pkr = int(fair)
            neg.discount_pct = round((asking_price - fair) / asking_price * 100.0, 1)

            gap_pct = (asking_price - fair) / max(1, asking_price) * 100.0
            if gap_pct >= cfg["walk_away_discount_pct"]:
                neg.walk_away = True
                neg.walk_away_reason = f"asking {gap_pct:.0f}% above value"
                neg.advice = (
                    f"Walk away unless it drops a long way. This model sells for "
                    f"about {neg.market_price_pkr:,} PKR, the defects cost "
                    f"{total:,} PKR ({examples}), so it is worth {fair:,} in this "
                    f"state - and the seller wants {asking_price:,}. That gap is "
                    f"{gap_pct:.0f}% of the price." + upgrade_note
                )
            else:
                neg.advice = (
                    f"Offer {neg.suggested_offer_pkr:,} PKR. This model goes for "
                    f"about {neg.market_price_pkr:,} PKR used; the defects cost "
                    f"{total:,} PKR to fix ({examples}), so it is worth {fair:,} "
                    f"as it stands. Anything up to {fair:,} is defensible - above "
                    f"that you are paying to fix someone else's problem."
                    + upgrade_note
                )
            return neg

        # no asking price, but we know what it is worth
        opening = int(fair * (1 - cfg["opening_margin_pct"] / 100.0))
        neg.suggested_offer_pkr = max(0, opening)
        neg.max_offer_pkr = int(fair)
        neg.advice = (
            f"It is worth about {fair:,} PKR in this state: "
            f"{neg.market_price_pkr:,} for the model, less {total:,} of repairs "
            f"({examples}). Offer {neg.suggested_offer_pkr:,} and do not go past "
            f"{fair:,}." + upgrade_note
        )
        neg.walk_away = bool(blockers)
        return neg

    # -------------------------------------------------- no market value known
    neg.price_basis = "asking" if asking_price else ""
    neg.market_note = (market.get("note")
                       or "no market price for this model was found or entered")

    if not items:
        neg.advice = ("Nothing to deduct. Pay the asking price, or a little under "
                      "it for the usual wear.")
        if asking_price:
            neg.suggested_offer_pkr = int(asking_price * 0.95)
            neg.max_offer_pkr = int(asking_price * 0.98)
        return neg

    if blockers:
        neg.walk_away_reason = "blocking defect"

    if asking_price:
        buffer = int(total * cfg["risk_buffer_pct"] / 100.0)
        neg.suggested_offer_pkr = max(0, int(asking_price - total - buffer))
        neg.max_offer_pkr = max(0, int(asking_price - total))
        neg.discount_pct = round(total / asking_price * 100.0, 1)
        neg.walk_away = bool(blockers) or neg.discount_pct >= cfg["walk_away_discount_pct"]
    else:
        neg.walk_away = bool(blockers)

    if blockers:
        neg.advice = (
            f"Walk away. {examples}. These are not bargaining points - they are "
            f"repairs the seller should have done before listing it."
        )
    elif asking_price:
        neg.advice = (
            f"Offer {neg.suggested_offer_pkr:,} PKR - the asking price less "
            f"{total:,} PKR of defects ({examples}) and a "
            f"{cfg['risk_buffer_pct']:.0f}% buffer. Up to {neg.max_offer_pkr:,} is "
            f"defensible. Set a market price for this model to price it on what it "
            f"is worth instead of what the seller asks."
        )
    else:
        neg.advice = (
            f"Deduct {total:,} PKR from the asking price. Breakdown: {examples}. "
            f"If the seller will not move, the repairs are yours to pay for."
        )
    return neg
