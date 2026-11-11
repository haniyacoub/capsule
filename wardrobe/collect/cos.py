"""COS: reading a category page.

COS category pages embed their product list as JSON (the page is built with
Next.js). Each entry is one product in one colour, with name, price, colour,
pictures and link. Sizes and fabric are only on the product page, which COS
does not serve to automated browsers — so they are simply not collected.
"""
from __future__ import annotations

import re

from . import pages

KEY = "cos"
LISTING_GIVES = "name, price, colour and picture — fabric is estimated from the name and size stock is unknown"


def parse_listing(html: str, base: str) -> list[dict]:
    block = next((b for b in pages.blocks(html) if b.get("component") == "category-page-block"), None)
    if not block:
        return []
    links = {slug: href for href, slug in re.findall(r'href="([^"]*/product/([^"/?#]+))"', html)}
    items = []
    for it in (block.get("initialResult") or {}).get("items", []):
        slug, sku = it.get("uri"), str(it.get("sku") or it.get("id") or "")
        if not slug or not sku or it.get("priceAsNumber") is None:
            continue
        href = links.get(slug) or f"/de-de/{it.get('categoryUri', 'men')}/product/{slug}"
        images = it.get("images") or []
        still = next((i for i in images if "StillLife" in str(i.get("imageType"))), None)
        picture = (still or it.get("primaryImage") or (images[0] if images else {})).get("src")
        price, before = float(it["priceAsNumber"]), it.get("priceBeforeDiscountAsNumber")
        items.append({
            "store": KEY,
            "sku": sku,
            "name": pages.tidy_name(it.get("name", "")),
            "slug": slug,
            "price": price,
            "price_before": float(before) if before and float(before) > price else None,
            "colour": pages.tidy_name(it.get("variantName", "")),
            "colour_hex": it.get("var_colour_details_desc") or None,   # COS gives the real shade
            "url": href if href.startswith("http") else base + href,
            "image_url": pages.sized_image(picture),
            "sizes_all": [],            # not on the category page
            "sizes_in_stock": [],
            "in_stock": bool(it.get("totalStock", 1)) and not it.get("isComingSoon"),
        })
    return items
