"""Google Shopping format, as JSON Lines (Awin's product API) or as CSV or TSV (Webgains and others).

One mapping serves all three: the field names are the same, only the file around them differs.
Where the field names come from:

    Google's product data specification, which both networks follow:
        https://support.google.com/merchants/answer/7052112
    Awin's Google-format feeds and their JSON Lines download (aw_deep_link is Awin's tracked link):
        https://help.awin.com/developers/docs/enhanced-feeds-publisher-faq.md   (8 Dec 2025)
        https://help.awin.com/apidocs/retail-publisher-productapidocumentation-1.md   (8 Sep 2026)
    Webgains' feeds, in Google's format as CSV, XML or TSV:
        https://knowledgehub.webgains.com/home/product-feeds-for-publishers

Unsure: how Awin's JSON Lines writes a price (the pages read list the field, not its shape). The
price reader takes "39.95 EUR", a plain number, and {"value": ..., "currency": ...} alike.
"""
from __future__ import annotations

from pathlib import Path

from . import rows


def read(path: Path) -> rows.Result:
    records = rows.json_lines(path) if rows.starts_with_brace(path) else rows.delimited(path)
    return rows.collect(records, product)


def product(record: dict) -> dict:
    # Some feeds write the names as in Google's XML ("g:id"); the name after the prefix is the same.
    f = {str(name).strip().lower().removeprefix("g:"): value for name, value in record.items() if name}
    return rows.product(
        product_id=f.get("id"),                         # id: one size and colour of a garment
        group_id=f.get("item_group_id"),                # item_group_id: shared by its other sizes and colours
        name=f.get("title"),                            # title
        brand=f.get("brand"),                           # brand
        category=f.get("product_type") or f.get("google_product_category"),   # the store's own words first
        gender=f.get("gender"),                         # gender: male | female | unisex
        colour=f.get("color"),                          # color, the store's words
        material=f.get("material"),                     # material, the store's words
        price=f.get("price"),                           # price: the regular price, "39.95 EUR"
        sale_price=f.get("sale_price"),                 # sale_price: the reduced price, when there is one
        sizes=f.get("size"),                            # size: this row's size (each size is its own row)
        available=rows.in_stock(f.get("availability")),  # availability: in_stock | out_of_stock | preorder | backorder
        image_url=f.get("image_link"),                  # image_link: the photo, used exactly as given
        buy_link=f.get("aw_deep_link") or f.get("link"),  # Awin's tracked link, else the feed's link as given
        feed_updated_at=None,                           # the format has no time per product: the feed's own is used
    )
