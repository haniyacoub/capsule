"""Pull&Bear: reading a category page.

Pull&Bear's category page builds its list in the browser, from the store's own product data that the page fetches as
it loads and as it is scrolled (browser.Session.fetch_listing keeps those answers). Each product there holds its
colours, and each colour its sizes, each size with its price in cents and whether it can be bought, its fibres with
their shares and its pictures. So every colour is kept as a product of its own, with its sizes in stock and its
fabric as the store's label states it. The generic listing reader does not read this shape (a price per colour and
size, in cents), hence this reader of its own.

One article can come several times, under a product number of each of its bundles: it is one product per link and
colour (sku_of), so it is kept once.
"""
from __future__ import annotations

from typing import Any

from .. import composition
from . import pages

KEY = "pull-and-bear"
LISTING_GIVES = "name, price, colour, picture, sizes in stock and fabric"
NEEDS_FETCHED = True        # its products are in the JSON the page fetched, not in its HTML (readers.read_page)


def _cents(value: Any) -> float | None:
    try:
        amount = int(str(value).strip()) / 100
    except (TypeError, ValueError):
        return None
    return amount if 0 < amount < 10_000 else None


def _fabric(colour: dict) -> str:
    """'95% Baumwolle, 5% Elasthan' from [{"part": "1", "composition": [{"name": "baumwolle", "percentage": "95"}, …]}]."""
    parts = []
    for part in colour.get("composition") or []:
        for fibre in (part.get("composition") or []) if isinstance(part, dict) else []:
            if isinstance(fibre, dict) and fibre.get("name") and str(fibre.get("percentage", "")).isdigit():
                parts.append(f"{fibre['percentage']}% {str(fibre['name']).capitalize()}")
    return ", ".join(parts)


def _picture(detail: dict, colour_id: str) -> str:
    for media_set in detail.get("xmedia") or []:
        if not isinstance(media_set, dict) or media_set.get("path") != f"/{colour_id}":
            continue
        for item in media_set.get("xmediaItems") or []:
            for media in item.get("medias") or []:
                url = (media.get("extraInfo") or {}).get("deliveryUrl")
                if url:
                    return str(url)
    return ""


def sku_of(address: str, colour_id: str) -> str:
    """One colour of one article: the article's reference at the end of its link ("…-tshirt-l0001" is "l0001") and
    the colour's number. Pull&Bear lists one article under several product numbers (one for each of its bundles),
    so the link, not the product number, says which article it is: the same link and colour are one product."""
    reference = str(address).split("?")[0].rstrip("/").rsplit("/", 1)[-1].rsplit("-", 1)[-1]
    return f"{reference or address}-{colour_id}"


def _bundles(node: Any):
    """Every product of Pull&Bear's product data, wherever an answer holds it."""
    stack = [node]
    while stack:
        found = stack.pop()
        if isinstance(found, dict):
            if isinstance(found.get("bundleProductSummaries"), list) and found.get("name"):
                yield found
                continue
            stack += [v for v in found.values() if isinstance(v, (dict, list))]
        elif isinstance(found, list):
            stack += [v for v in found if isinstance(v, (dict, list))]


def parse_listing(html: str, base: str, fetched: list | tuple = (), store: str = KEY) -> list[dict]:
    items: dict[str, dict] = {}
    for answer in fetched:
        for bundle in _bundles(answer):
            for summary in bundle["bundleProductSummaries"]:
                detail = summary.get("detail") or {} if isinstance(summary, dict) else {}
                address = summary.get("productUrl") or bundle.get("productUrl")
                for colour in detail.get("colors") or []:
                    colour_id = str(colour.get("id") or "")
                    sizes = [s for s in colour.get("sizes") or [] if isinstance(s, dict)]
                    prices = [p for p in (_cents(s.get("price")) for s in sizes) if p]
                    if not colour_id or not prices or not address:
                        continue
                    price = min(prices)
                    before = max([p for p in (_cents(s.get("oldPrice")) for s in sizes) if p] or [0])
                    sku = sku_of(str(address), colour_id)
                    # (each size once: a colour can list a size more than once)
                    named = [s for s in sizes if s.get("name")]
                    every = list(dict.fromkeys(str(s["name"]) for s in named))
                    stocked = list(dict.fromkeys(str(s["name"]) for s in named if s.get("isBuyable")))
                    items.setdefault(sku, {
                        "store": store, "sku": sku, "name": pages.tidy_name(str(bundle["name"])),
                        "slug": str(address), "price": price, "price_before": before if before > price else None,
                        "colour": str(colour.get("name") or ""), "colour_hex": None,
                        "url": f"{base}/de/{address}?cS={colour_id}", "image_url": _picture(detail, colour_id),
                        "sizes_all": every, "sizes_in_stock": stocked,
                        "in_stock": any(s.get("isBuyable") for s in sizes),
                        "composition_text": composition.stated(_fabric(colour)), "fabric_words": "",
                    })
    return list(items.values())
