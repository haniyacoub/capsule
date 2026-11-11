"""Weekday: reading a category page.

Weekday's category pages embed their product list as JSON, one entry per
product and colour, and — unlike COS — include which sizes are in stock.
Fabric is only on the product page, which Weekday does not serve to automated
browsers, so it is not collected.
"""
from __future__ import annotations

from . import pages

KEY = "weekday"
LISTING_GIVES = "name, price, colour, picture and size stock — fabric is estimated from the name"


def parse_listing(html: str, base: str) -> list[dict]:
    block = next((b for b in pages.blocks(html) if b.get("component") == "product-listing"), None)
    if not block:
        return []
    items = []
    for p in (block.get("listingPageData") or {}).get("products", []):
        pricing = p.get("pricing") or {}
        sku, path = str(p.get("sku") or ""), p.get("url") or ""
        if not sku or not path or pricing.get("priceAsNumber") is None:
            continue
        images = (p.get("media") or {}).get("images") or []
        still = next((i for i in images if "StillLife" in str(i.get("assetType"))), None)
        hero = next((i for i in images if i.get("isHero")), images[0] if images else {})
        price, before = float(pricing["priceAsNumber"]), pricing.get("priceBeforeDiscountAsNumber")
        sizes = p.get("sizeVariants") or []
        items.append({
            "store": KEY,
            "sku": sku,
            "name": pages.tidy_name(p.get("name", "")),
            "slug": path.rstrip("/").rsplit("/", 1)[-1],
            "price": price,
            "price_before": float(before) if pricing.get("isOnSale") and before and float(before) > price else None,
            "colour": p.get("variantName", ""),
            "colour_hex": None,         # Weekday's swatch is a generic colour, not the real shade
            "url": base + path.rstrip("/") + "/",
            "image_url": pages.sized_image((still or hero).get("url")),
            "sizes_all": [s.get("label", "") for s in sizes if s.get("label")],
            "sizes_in_stock": [s["label"] for s in sizes if s.get("label") and s.get("inStock") == "yes"],
            "in_stock": bool(p.get("available", True)) and not p.get("comingSoon"),
        })
    return items
