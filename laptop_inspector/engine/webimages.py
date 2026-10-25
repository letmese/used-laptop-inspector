"""Find reference photographs of a laptop's ports on the web.

The port *order* comes from `data/port_layouts.json`, which is sourced and
tested. This module is the other half: at test time it takes the detected model,
searches the web for pictures of that machine, and returns them so the buyer can
see what the real thing looks like.

Two providers, in order:

1. **Wikimedia Commons** - licensed, attributed, no key. Preferred because the
   licence and author can be shown next to the photo.
2. **Bing image search** - much broader coverage, which is what actually finds a
   photo of a specific laptop's left edge. Results are arbitrary web images, so
   they are shown as "reference, unverified" with the source host, never as an
   authoritative diagram.

Everything here fails soft. No network, a timeout, a bad response - the caller
gets an empty list and the drawn layout carries the test on its own.

Nothing in this module knows about Qt, so it can be exercised headlessly.
"""

from __future__ import annotations

import hashlib
import html
import json
import os
import re
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

USER_AGENT = ("UsedLaptopInspector/2.2 (Windows hardware diagnostic tool; "
              "offline-first, online lookup is opt-in)")

COMMONS_API = "https://commons.wikimedia.org/w/api.php"
BING_IMAGES = "https://www.bing.com/images/search"

CACHE_TTL = 24 * 3600          # a day; port layouts do not change
MAX_BYTES = 6 * 1024 * 1024
MAX_RESULTS = 6

# Words that suggest a photo is of a port edge rather than a hero shot.
SIDE_WORDS = ("left", "right", "side", "port", "ports", "interface",
              "connector", "rear", "back", "io", "i/o")
# Words that suggest a photo will not help.
JUNK_WORDS = ("logo", "sticker", "icon", "wallpaper", "driver", "manual",
              "schematic", "teardown-only")

LICENCE_OK = ("cc0", "public domain", "cc by", "cc-by", "attribution")


@dataclass
class Photo:
    url: str                  # the image to download
    page: str = ""            # human page for attribution
    title: str = ""
    width: int = 0
    height: int = 0
    licence: str = ""
    author: str = ""
    provider: str = ""

    @property
    def host(self) -> str:
        try:
            return urllib.parse.urlparse(self.page or self.url).netloc
        except Exception:
            return ""

    @property
    def side(self) -> str:
        """Which edge the photo probably shows, from its title or file name."""
        hay = f"{self.title} {self.url}".lower()
        # Word boundaries matter: "backnumber" in a URL is not a rear view.
        for side, pattern in (("left", r"\bleft\b"),
                              ("right", r"\bright\b"),
                              ("rear", r"\b(rear|back|backside)\b")):
            if re.search(pattern, hay):
                return side
        return ""

    def credit(self) -> str:
        bits = []
        if self.author:
            bits.append(self.author)
        if self.licence:
            bits.append(self.licence)
        bits.append("Wikimedia Commons" if self.provider == "commons" else self.host)
        return " · ".join(b for b in bits if b)

    def score(self, query: str) -> int:
        """How likely this is to show a port edge of the right machine."""
        hay = f"{self.title} {self.url} {self.page}".lower()
        points = 0
        for word in SIDE_WORDS:
            if word in hay:
                points += 3
        for token in re.findall(r"[a-z0-9]+", query.lower()):
            if len(token) > 2 and token in hay:
                points += 2
        for word in JUNK_WORDS:
            if word in hay:
                points -= 6
        # Port photos are usually wider than they are tall.
        if self.width and self.height:
            ratio = self.width / max(1, self.height)
            if 1.2 <= ratio <= 2.4:
                points += 2
            elif ratio < 0.9:
                points -= 3
        return points


# --------------------------------------------------------------------- plumbing
def _cache_dir() -> str:
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    path = os.path.join(base, "UsedLaptopInspector", "webcache")
    try:
        os.makedirs(path, exist_ok=True)
    except Exception:
        return ""
    return path


def _cache_get(key: str) -> Optional[Any]:
    path = os.path.join(_cache_dir(), f"{key}.json")
    try:
        if time.time() - os.path.getmtime(path) > CACHE_TTL:
            return None
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except Exception:
        return None


def _cache_put(key: str, payload: Any) -> None:
    path = os.path.join(_cache_dir(), f"{key}.json")
    try:
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle)
    except Exception:
        pass


def _get(url: str, timeout: float) -> Optional[bytes]:
    try:
        request = urllib.request.Request(url, headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/json,text/html,image/*,*/*",
        })
        with urllib.request.urlopen(request, timeout=timeout) as response:
            if response.status != 200:
                return None
            length = int(response.headers.get("Content-Length") or 0)
            if length > MAX_BYTES:
                return None
            return response.read(MAX_BYTES)
    except Exception:
        return None


def _strip_html(value: Any) -> str:
    text = re.sub(r"<[^>]+>", "", str(value or ""))
    return html.unescape(text).strip()[:80]


# --------------------------------------------------------------------- providers
def _commons(query: str, limit: int, timeout: float) -> List[Photo]:
    params = {
        "action": "query", "format": "json", "generator": "search",
        "gsrsearch": query, "gsrnamespace": "6", "gsrlimit": str(limit * 3),
        "prop": "imageinfo", "iiprop": "url|size|mime|extmetadata",
        "iiurlwidth": "900",
    }
    raw = _get(f"{COMMONS_API}?{urllib.parse.urlencode(params)}", timeout)
    if not raw:
        return []
    try:
        data = json.loads(raw.decode("utf-8", "replace"))
    except Exception:
        return []

    photos: List[Photo] = []
    pages = ((data.get("query") or {}).get("pages") or {})
    for page in pages.values():
        info = (page.get("imageinfo") or [{}])[0]
        if info.get("mime") not in ("image/jpeg", "image/png"):
            continue
        meta = info.get("extmetadata") or {}
        licence = _strip_html((meta.get("LicenseShortName") or {}).get("value"))
        # Only show images that are free to display.
        if licence and not any(word in licence.lower() for word in LICENCE_OK):
            continue
        photos.append(Photo(
            url=str(info.get("thumburl") or info.get("url") or ""),
            page=str(info.get("descriptionurl") or ""),
            title=str(page.get("title") or "").replace("File:", ""),
            width=int(info.get("thumbwidth") or info.get("width") or 0),
            height=int(info.get("thumbheight") or info.get("height") or 0),
            licence=licence,
            author=_strip_html((meta.get("Artist") or {}).get("value")),
            provider="commons",
        ))
    return [p for p in photos if p.url]


_BING_ITEM = re.compile(r'm="(\{[^"]*?\})"', re.S)


def _bing(query: str, limit: int, timeout: float) -> List[Photo]:
    """Bing's image results embed a JSON blob per result in an `m` attribute."""
    search = f'"{query}" laptop ports left right side'
    url = f"{BING_IMAGES}?{urllib.parse.urlencode({'q': search, 'form': 'HDRSC2'})}"
    raw = _get(url, timeout)
    if not raw:
        return []

    photos: List[Photo] = []
    seen = set()
    for match in _BING_ITEM.finditer(raw.decode("utf-8", "replace")):
        try:
            item = json.loads(html.unescape(match.group(1)))
        except Exception:
            continue
        media = item.get("murl") or ""
        page = item.get("purl") or ""
        if not media.lower().startswith(("http://", "https://")):
            continue
        if media.lower().endswith((".svg", ".gif", ".webp")):
            continue
        key = media.split("?")[0]
        if key in seen:
            continue
        seen.add(key)
        photos.append(Photo(
            url=media,
            page=page,
            title=str(item.get("t") or ""),
            provider="bing",
        ))
        if len(photos) >= limit * 3:
            break
    return photos


CORP_SUFFIXES = (" Inc.", " Inc", " Corp.", " Corp", " Ltd.", " Ltd", " Co.",
                 " Company", " GmbH", " Technologies")


def model_query(machine: Optional[Dict[str, Any]] = None,
                family: str = "") -> str:
    """The best search string for this machine, or "" if there is nothing useful.

    The layout family is ideal when we know the model. When we do not, the family
    is literally "Generic laptop" - searching that returns photographs of random
    laptops, which is worse than showing nothing. So fall back to what the
    machine reports about itself.
    """
    family = (family or "").strip()
    if family and "generic" not in family.lower():
        return family

    data = machine or {}
    reported = str(data.get("family") or "").strip()
    if reported and "generic" not in reported.lower():
        return reported

    model = str(data.get("model") or "").strip()
    if not model:
        return ""
    maker = str(data.get("manufacturer") or "").strip().title()
    for suffix in CORP_SUFFIXES:
        if maker.endswith(suffix):
            maker = maker[: -len(suffix)].strip()
    return f"{maker} {model}".strip()


# ------------------------------------------------------------------------ public
def search(model: str, limit: int = MAX_RESULTS, timeout: float = 5.0,
           allow_bing: bool = True) -> List[Photo]:
    """Photos of `model`, best first. Never raises; empty list means nothing found."""
    query = (model or "").strip()
    if not query:
        return []

    key = hashlib.sha1(f"v2|{query}|{limit}|{allow_bing}".encode("utf-8")).hexdigest()
    cached = _cache_get(key)
    if isinstance(cached, list):
        return [Photo(**item) for item in cached if isinstance(item, dict)]

    found: List[Photo] = []
    try:
        found.extend(_commons(query, limit, timeout))
    except Exception:
        pass
    if len(found) < limit and allow_bing:
        try:
            found.extend(_bing(query, limit, timeout))
        except Exception:
            pass

    # Drop images that clearly are not about this machine. Matching on the
    # brand alone let W540 and W550s photos through, so the model number is what
    # has to match - it is the only distinctive token in "ThinkPad W520".
    tokens = [t for t in re.findall(r"[a-z0-9]+", query.lower()) if len(t) > 2]
    required = [t for t in tokens if any(c.isdigit() for c in t)] or tokens
    relevant = []
    for photo in found:
        hay = f"{photo.title} {photo.url} {photo.page}".lower()
        if required and not any(t in hay for t in required):
            continue
        relevant.append(photo)

    relevant.sort(key=lambda p: p.score(query), reverse=True)
    chosen = relevant[:limit]

    if chosen:
        _cache_put(key, [p.__dict__ for p in chosen])
    return chosen


def download(photo: Photo, timeout: float = 8.0) -> Optional[bytes]:
    """Fetch one image, capped in size. Cached on disk by URL."""
    key = "img_" + hashlib.sha1(photo.url.encode("utf-8")).hexdigest()
    directory = _cache_dir()
    path = os.path.join(directory, key + ".bin")
    try:
        if os.path.exists(path) and os.path.getsize(path) > 1024:
            with open(path, "rb") as handle:
                return handle.read()
    except Exception:
        pass

    raw = _get(photo.url, timeout)
    if not raw or len(raw) < 1024:
        return None
    try:
        with open(path, "wb") as handle:
            handle.write(raw)
    except Exception:
        pass
    return raw


def clear_cache() -> None:
    directory = _cache_dir()
    for name in os.listdir(directory) if os.path.isdir(directory) else []:
        try:
            os.remove(os.path.join(directory, name))
        except Exception:
            pass
