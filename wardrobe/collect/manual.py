"""Manual import: you paste a product link, the tool takes what the link says.

The page itself is never opened: COS and Weekday refuse automated browsers on
product pages, and a server never opens a store's page at all. The tool takes
what the link says (store, product name, colour, article number) and, if that
article was seen on a category page during a refresh, copies its name, price,
colour and picture. Whatever is still missing you type in on the piece's page.

Only links to stores customers are offered are taken (programmes.py): a link
to a store without a partner programme, such as Zara, is refused.

What happened to each link is said to the customer after the product's name
("Added “X”: only the link could be read …") or after the link itself ("Not
added: “link” is not a COS or Weekday link."), so the notes below read on from those.
"""
from __future__ import annotations

import hashlib
import re
from urllib.parse import urlsplit

from .. import catalog, programmes
from . import load_settings, pages


def hosts() -> dict[str, str]:
    """{'cos.com': 'cos', 'weekday.com': 'weekday'}: the web addresses of the stores customers are offered,
    from each store's `base` in config/stores.toml."""
    cfg = load_settings()
    out = {}
    for key in programmes.offered():
        host = urlsplit(str(cfg.get(key, {}).get("base", ""))).netloc.lower().removeprefix("www.")
        if host:
            out[host] = key
    return out


def store_of(url: str) -> str | None:
    parts = urlsplit(url.strip())
    if parts.scheme not in ("http", "https"):
        return None
    host = parts.netloc.lower().split(":")[0]
    return next((key for domain, key in hosts().items() if host == domain or host.endswith("." + domain)), None)


def _from_link_alone(url: str, store: str, slot: dict, known: list[dict]) -> tuple[dict, str]:
    """What a link says by itself, plus anything a refresh already saw for that article."""
    slug = urlsplit(url).path.rstrip("/").rsplit("/", 1)[-1]
    slug = re.sub(r"\.html$", "", slug)
    number = re.search(r"(\d{7,13})$", slug) or re.search(r"p(\d{8})", slug)
    sku = number.group(1) if number else hashlib.sha1(url.encode(), usedforsecurity=False).hexdigest()[:10]
    seen = next((c for c in known if c.get("store") == store and c.get("id") == f"{store}-{sku}"), None)
    if seen:
        cand = {k: v for k, v in seen.items() if k != "manual"}
        cand.update(slot_id=slot["id"], source="manual", url=url, collected_at=catalog.now_iso())
        return cand, "its name, price, colour and picture were already in Capsule's product list"

    # The article number is not part of the name: COS ends a link "…-black-4100000902", Zara "…-p01234567"
    # (without the "-p" too, the name of "stiefel-aus-leder-p01234567" would be "Stiefel aus leder p").
    words = re.sub(r"(?:-p)?-?\d{7,13}$", "", slug).replace("-", " ").strip()
    cand = {
        "id": f"{store}-{sku}", "slot_id": slot["id"], "store": store,
        "name": words[:1].upper() + words[1:] if words else "Product", "slug": slug,
        "price": 0.0, "currency": "EUR", "colour": "", "colour_hex": None,
        "composition_text": "", "fit": pages.fit_from(words), "description": "",
        "sizes_all": [], "sizes_in_stock": [], "url": url, "image_url": "",
        "source": "manual", "collected_at": catalog.now_iso(),
    }
    return cand, "only the link could be read — add the price, fabric and sizes under “Add details”"


def from_urls(urls: list[str], slot: dict) -> list[tuple[str, dict | None, str]]:
    """One (link, candidate or None, what happened) per pasted link. No page is ever opened."""
    known = catalog.load().get("candidates", [])
    stores = programmes.names(hosts().values(), last="or")
    results: list[tuple[str, dict | None, str]] = []
    for url in urls:
        store = store_of(url)
        if store is None:
            results.append((url, None, f"is not a {stores} link"))
            continue
        stub, note = _from_link_alone(url, store, slot, known)
        results.append((url, stub, note))
    return results
