"""What is this model actually worth on the used market?

The counter-offer must not be derived from the seller's asking price. If it is,
a seller who asks more gets offered more for the same defective machine - the
exact inversion this module exists to fix.

So the offer is built from **market value minus repair cost**, and the asking
price is only used to judge whether the deal is good. Market value comes from:

1. A price the buyer typed in (authoritative - they know their local market).
2. A web search for used listings of this model, median of the prices found.
3. Nothing. In that case the report says the offer is anchored to the asking
   price, because it has no independent value to work from.

Searches are cached for a week, so a shop testing five identical laptops asks the
web once.
"""

from __future__ import annotations

import hashlib
import html
import json
import os
import re
import statistics
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

SEARCH = "https://html.duckduckgo.com/html/"
CACHE_TTL = 7 * 24 * 3600
MAX_BYTES = 400_000

# A used laptop in PKR. Outside this range the number is something else - a
# storage size, a phone number, a year.
MIN_PRICE = 5_000
MAX_PRICE = 3_000_000

# Currency markers, and the range each implies. The tool prices in PKR, so a
# bare "$" figure is converted only if a rate is supplied.
PKR_MARKERS = ("pkr", "rs", "rs.", "₨", "rupees", "rupee", "/-")

# The trailing currency marker is a lookahead, not consumed: without that,
# "ThinkPad W520 Rs 29,000" matches "520 Rs" as a price and swallows the "Rs",
# so the real figure is never seen.
MONEY = re.compile(
    r"(?:PKR|Rs\.?|₨)\s*([0-9][0-9,]{2,})"
    r"|([0-9][0-9,]{2,})(?=\s*(?:PKR|Rs\.?|/-))",
    re.IGNORECASE)


@dataclass
class MarketPrice:
    value_pkr: Optional[int] = None
    low_pkr: Optional[int] = None
    high_pkr: Optional[int] = None
    samples: List[int] = field(default_factory=list)
    source: str = ""              # "manual", "search", or ""
    confidence: str = "none"      # "good", "thin", "none"
    note: str = ""

    @property
    def known(self) -> bool:
        return bool(self.value_pkr)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "value_pkr": self.value_pkr, "low_pkr": self.low_pkr,
            "high_pkr": self.high_pkr, "samples": self.samples,
            "source": self.source, "confidence": self.confidence,
            "note": self.note,
        }


def _cache_dir() -> str:
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    path = os.path.join(base, "UsedLaptopInspector", "webcache")
    try:
        os.makedirs(path, exist_ok=True)
    except Exception:
        return ""
    return path


def _cached(key: str) -> Optional[Dict[str, Any]]:
    path = os.path.join(_cache_dir(), f"mkt_{key}.json")
    try:
        if time.time() - os.path.getmtime(path) > CACHE_TTL:
            return None
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except Exception:
        return None


def _store(key: str, payload: Dict[str, Any]) -> None:
    path = os.path.join(_cache_dir(), f"mkt_{key}.json")
    try:
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle)
    except Exception:
        pass


def _fetch(url: str, timeout: float) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read(MAX_BYTES).decode("utf-8", "replace")


def _plain(page: str) -> str:
    page = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", page)
    page = re.sub(r"(?s)<[^>]+>", " ", page)
    return re.sub(r"\s+", " ", html.unescape(page))


def prices_in(text: str) -> List[int]:
    """Every plausible PKR figure in a block of text."""
    found: List[int] = []
    for match in MONEY.finditer(text):
        raw = (match.group(1) or match.group(2) or "").replace(",", "")
        try:
            value = int(raw)
        except ValueError:
            continue
        if MIN_PRICE <= value <= MAX_PRICE:
            found.append(value)
    return found


def search(model: str, timeout: float = 12.0) -> MarketPrice:
    """Median of used prices found for this model. Never raises."""
    query_model = (model or "").strip()
    if not query_model:
        return MarketPrice(note="no model name to search for")

    key = hashlib.sha1(f"mkt1|{query_model}".encode("utf-8")).hexdigest()
    cached = _cached(key)
    if isinstance(cached, dict):
        return MarketPrice(**{k: cached.get(k) for k in
                              ("value_pkr", "low_pkr", "high_pkr", "samples",
                               "source", "confidence", "note")})

    # Two phrasings: one finds marketplace listings, the other finds review
    # sites that quote a street price.
    queries = [
        f'"{query_model}" used price',
        f"{query_model} price Rs Pakistan",
    ]
    # The distinctive token - "w520" in "ThinkPad W520" - is what has to appear
    # near a figure. Matching on "thinkpad" alone would accept any ThinkPad price.
    tokens = [t for t in re.findall(r"[a-z0-9]+", query_model.lower()) if len(t) > 2]
    anchors = [t for t in tokens if any(c.isdigit() for c in t)] or tokens

    samples: List[int] = []
    for query in queries:
        url = SEARCH + "?" + urllib.parse.urlencode({"q": query})
        try:
            page = _fetch(url, timeout)
        except Exception:
            continue
        # Only keep figures whose surrounding text mentions the model, so a
        # stray "Rs 5,000" for a battery does not become the laptop's value.
        body = _plain(page)
        for match in MONEY.finditer(body):
            # Search snippets put the model in the title and the price in the
            # body, so the window has to be wide enough to span both.
            window = body[max(0, match.start() - 500):match.end() + 80].lower()
            if anchors and not any(token in window for token in anchors):
                continue
            raw = (match.group(1) or match.group(2) or "").replace(",", "")
            try:
                value = int(raw)
            except ValueError:
                continue
            if MIN_PRICE <= value <= MAX_PRICE:
                samples.append(value)

    if not samples:
        # Never cache a miss: a blocked request or a flaky page would poison the
        # answer for a week, and the next scan would keep reporting "unknown".
        return MarketPrice(note="no used prices found for this model")

    samples.sort()
    median = int(statistics.median(samples))
    # Drop the extremes so one optimistic listing does not set the price.
    trimmed = samples[1:-1] if len(samples) >= 4 else samples
    value = int(statistics.median(trimmed)) if trimmed else median

    result = MarketPrice(
        value_pkr=value,
        low_pkr=min(samples),
        high_pkr=max(samples),
        samples=samples[:12],
        source="search",
        confidence="good" if len(samples) >= 3 else "thin",
        note=f"median of {len(samples)} listing(s) found online",
    )
    _store(key, result.to_dict())
    return result


def _key(model: str) -> str:
    return re.sub(r"\s+", " ", (model or "").strip().lower())


def _remember_path() -> str:
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    folder = os.path.join(base, "UsedLaptopInspector")
    try:
        os.makedirs(folder, exist_ok=True)
    except Exception:
        return ""
    return os.path.join(folder, "market_prices.json")


def remembered(model: str) -> Optional[int]:
    """A price the buyer set for this model before, on this machine."""
    path = _remember_path()
    if not path:
        return None
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
        value = data.get(_key(model))
        return int(value) if value else None
    except Exception:
        return None


def remember(model: str, value_pkr: Optional[int]) -> None:
    path = _remember_path()
    if not path or not model:
        return
    try:
        data = {}
        if os.path.exists(path):
            with open(path, encoding="utf-8") as handle:
                data = json.load(handle) or {}
        if value_pkr and value_pkr > 0:
            data[_key(model)] = int(value_pkr)
        else:
            data.pop(_key(model), None)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, ensure_ascii=False)
    except Exception:
        pass


def resolve(model: str, manual_pkr: Optional[int] = None,
            allow_search: bool = True) -> MarketPrice:
    """Manual entry beats a remembered price, which beats the web.

    A buyer who tests the same model every week should only have to state the
    market value once, so anything found or entered is remembered per model.
    """
    if manual_pkr and manual_pkr > 0:
        remember(model, manual_pkr)
        return MarketPrice(value_pkr=int(manual_pkr), source="manual",
                           confidence="good",
                           note="price entered by the buyer")

    stored = remembered(model)
    if stored:
        return MarketPrice(value_pkr=stored, source="stored", confidence="good",
                           note="price remembered from a previous scan of this model")

    if not allow_search:
        return MarketPrice(note="online lookup disabled")

    found = search(model)
    if found.known:
        remember(model, found.value_pkr)
    return found
