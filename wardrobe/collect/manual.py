"""Manual import: you paste a product link, the tool extracts what it can.

  * Zara serves product pages to the collector's browser, so a Zara link is
    opened once and read in full (fabric, sizes, price, picture).
  * COS and Weekday refuse automated browsers on product pages. Their links
    are not opened at all. The tool takes what the link itself says (store,
    product name, colour, article number) and, if that article was seen on a
    category page during a refresh, copies its name, price, colour and picture.
    Whatever is still missing you can type in on the slot page.
"""
from __future__ import annotations

import hashlib
import re
from urllib.parse import parse_qs, urlsplit

from .. import catalog
from . import ADAPTERS, load_settings, pages, zara_candidate
from .browser import Session

HOSTS = {"cos.com": "cos", "weekday.com": "weekday", "zara.com": "zara"}


def store_of(url: str) -> str | None:
    parts = urlsplit(url.strip())
    if parts.scheme not in ("http", "https"):
        return None
    host = parts.netloc.lower().split(":")[0]
    return next((key for domain, key in HOSTS.items() if host == domain or host.endswith("." + domain)), None)


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
        return cand, "taken from the last refresh (name, price, colour, picture)"

    words = re.sub(r"-?\d{7,13}$", "", slug).replace("-", " ").strip()
    cand = {
        "id": f"{store}-{sku}", "slot_id": slot["id"], "store": store,
        "name": words[:1].upper() + words[1:] if words else "Product", "slug": slug,
        "price": 0.0, "currency": "EUR", "colour": "", "colour_hex": None,
        "composition_text": "", "fit": pages.fit_from(words), "description": "",
        "sizes_all": [], "sizes_in_stock": [], "url": url, "image_url": "",
        "source": "manual", "collected_at": catalog.now_iso(),
    }
    return cand, "only the link could be read — add the price, fabric and sizes under “Add details”"


def from_urls(urls: list[str], slot: dict, allow_fetch: bool = True) -> list[tuple[str, dict | None, str]]:
    """One (link, candidate or None, what happened) per pasted link.

    With `allow_fetch` off (the public service) no page is ever opened: every
    link is treated like a COS or Weekday link.
    """
    cfg = load_settings()
    known = catalog.load().get("candidates", [])
    results: list[tuple[str, dict | None, str]] = []
    session: Session | None = None
    try:
        for url in urls:
            store = store_of(url)
            if store is None:
                results.append((url, None, "not a COS, Weekday or Zara link"))
                continue
            store_cfg, adapter = cfg[store], ADAPTERS[store]
            if not allow_fetch or not store_cfg.get("product_pages") or not hasattr(adapter, "parse_product"):
                stub, note = _from_link_alone(url, store, slot, known)
                results.append((url, stub, note))
                continue
            try:
                session = session or Session(cfg.get("collector", {}), log=lambda *_: None)
                clean = url.split("?")[0]
                detail = adapter.parse_product(session.fetch(store, store_cfg["base"], clean), store_cfg["base"])
                colour_id = parse_qs(urlsplit(url).query).get("v1", [None])[0]   # the colour the link points at
                read: dict | None = None
                if detail:
                    item = {"store": store, "sku": detail["sku"], "name": detail["name"],
                            "slug": detail["slug"], "price": 0.0, "url": clean}
                    read = zara_candidate(item, detail, slot, catalog.now_iso(),
                                          product_id=colour_id, any_colour=True)
                if read:
                    read["source"] = "manual"
                    results.append((url, read, "read from the product page"))
                else:
                    results.append((url, None, "that page is not a product page"))
            except Exception as problem:  # noqa: BLE001 — refused, browser busy or missing, page gone…
                stub, note = _from_link_alone(url, store, slot, known)
                reason = (str(problem).splitlines() or [type(problem).__name__])[0][:120]
                results.append((url, stub, f"the page could not be opened ({reason}); {note}"))
    finally:
        if session:
            session.close()
    return results
