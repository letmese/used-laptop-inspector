"""Is Bing's RSS endpoint usable for used prices?"""

import re
import sys
import urllib.parse

sys.path.insert(0, ".")

from laptop_inspector.engine import market

QUERIES = [
    'ThinkPad W520 used price',
    '"ThinkPad W520" price Rs',
    'ThinkPad W520 second hand price Pakistan',
]

for query in QUERIES:
    url = ("https://www.bing.com/search?format=rss&count=20&q="
           + urllib.parse.quote(query))
    try:
        page = market._fetch(url, 15)
    except Exception as exc:
        print(f"{query!r}: fetch failed {type(exc).__name__}")
        continue

    items = re.findall(r"(?is)<item>(.*?)</item>", page)
    print(f"\n=== {query!r}  items={len(items)}  bytes={len(page)}")
    for item in items[:4]:
        title = re.search(r"(?is)<title>(.*?)</title>", item)
        desc = re.search(r"(?is)<description>(.*?)</description>", item)
        text = market._plain((title.group(1) if title else "")
                             + " " + (desc.group(1) if desc else ""))
        print(f"   - {text[:170]}")
        prices = market.prices_in(text)
        if prices:
            print(f"     prices: {prices}")
