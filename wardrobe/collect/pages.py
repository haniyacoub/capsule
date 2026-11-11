"""Small helpers for reading what a store page carries inside its own HTML."""
from __future__ import annotations

import json
import re
from urllib.parse import parse_qs, urlsplit

_SMALL_WORDS = {"aus", "mit", "und", "in", "im", "für", "von", "zum", "zur", "am", "an", "auf",
                "der", "die", "das", "dem", "den", "of", "and", "with"}


def next_data(html: str) -> dict:
    """The JSON a Next.js page embeds (COS and Weekday). {} if there is none."""
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, flags=re.S)
    if not m:
        return {}
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError:
        return {}


def zara_payload(html: str) -> dict:
    """The object Zara assigns to window.zara.viewPayload. {} if there is none."""
    at = html.find("window.zara.viewPayload")
    start = html.find("{", at) if at >= 0 else -1
    if start < 0:
        return {}
    try:
        payload, _ = json.JSONDecoder().raw_decode(html[start:])
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def blocks(html: str) -> list[dict]:
    """The page-building blocks of a COS or Weekday page."""
    found = next_data(html).get("props", {}).get("pageProps", {}).get("blocks", [])
    return [b for b in found if isinstance(b, dict)]


def next_page_url(html: str, url: str) -> str | None:
    """The address of the next page of a category, if the page links to one."""
    parts = urlsplit(url)
    current = int(parse_qs(parts.query).get("page", ["1"])[0])
    if not re.search(rf'href="[^"]*[?&](?:amp;)?page={current + 1}(?!\d)', html):
        return None
    return f"{parts.scheme}://{parts.netloc}{parts.path}?page={current + 1}"


def _capitalise(word: str) -> str:
    return "-".join(part[:1].upper() + part[1:] for part in word.split("-"))


def tidy_name(name: str) -> str:
    """'PULLOVER AUS MERINOWOLLE' -> 'Pullover aus Merinowolle'. Mixed-case names are left alone."""
    name = " ".join(str(name or "").split())
    letters = [ch for ch in name if ch.isalpha()]
    if not letters or sum(ch.isupper() for ch in letters) / len(letters) < 0.7:
        return name
    words = name.lower().split(" ")
    return " ".join(w if (i and w in _SMALL_WORDS) else _capitalise(w) for i, w in enumerate(words))


def fit_from(text: str) -> str:
    """The cut a name or description announces: oversized, slim, relaxed, or regular."""
    t = (text or "").lower()
    if re.search(r"oversize|baggy|extra weit", t):
        return "oversized"
    if re.search(r"\bslim|schmal|skinny|tailliert|muscle fit|figurbetont", t):
        return "slim"
    if re.search(r"relax|locker|lässig|boxy|loose|\bweit|wide", t):
        return "relaxed"
    return "regular"


def sized_image(url: str | None, width: int = 640) -> str:
    """A reasonably small version of an H&M-group image (their servers resize on request)."""
    if not url:
        return ""
    return url if "imwidth=" in url else f"{url}{'&' if '?' in url else '?'}imwidth={width}"
