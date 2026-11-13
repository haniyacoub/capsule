"""Google Shopping format, as JSON Lines (Awin's product API) or as CSV or TSV (Webgains and others).

One mapping serves all three: the field names are the same, only the file around them differs.
Each mapping line below ends with the tag of the public documentation its field name comes from:

    [Google]    Google's product data specification, which both networks follow:
                    https://support.google.com/merchants/answer/7052112
    [Awin]      Awin's columns for its Google-format feeds (aw_deep_link is Awin's tracked link),
                and its JSON Lines download:
                    https://help.awin.com/developers/docs/enhanced-feeds-publisher-faq.md   (8 Dec 2025)
                    https://help.awin.com/apidocs/retail-publisher-productapidocumentation-1.md   (8 Sep 2026)
    [Webgains]  Webgains' feeds, in Google's format as CSV, XML or TSV:
                    https://knowledgehub.webgains.com/home/product-feeds-for-publishers
    unsure      the name, or what it holds, was not confirmed in those pages: check it against the
                first real file, and change it here, in this one place.
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
        product_id=f.get("id"),                 # [Google] [Webgains] id: one size and colour of a garment
        group_id=f.get("item_group_id"),        # [Google] [Awin] item_group_id: shared by its other sizes and colours
        name=f.get("title"),                    # [Google] [Webgains] title
        brand=f.get("brand"),                   # [Google] [Webgains] brand
        category=(f.get("product_type")         # [Google] product_type, the store's own words; unsure: not in
                                                #          [Awin]'s or [Webgains]' lists
                  or f.get("google_product_category")),   # [Google] [Webgains] google_product_category
        gender=f.get("gender"),                 # [Google] [Awin] gender: male | female | unisex
        colour=f.get("color"),                  # [Google] [Awin] color, the store's words
        material=f.get("material"),             # [Google] [Awin] material, the store's words
        price=f.get("price"),                   # [Google] [Awin] [Webgains] price: the regular price, "39.95 EUR";
                                                #          unsure: how Awin's JSON Lines writes it (the
                                                #          price reader takes text, a number or {"value", "currency"})
        sale_price=f.get("sale_price"),         # [Google] [Awin] [Webgains] sale_price: the reduced price, if any
        sizes=f.get("size"),                    # [Google] [Awin] [Webgains] size: this row's size (each size is its own row)
        available=rows.in_stock(f.get("availability")),  # [Google] [Awin] [Webgains] availability:
                                                         #          in_stock | out_of_stock | preorder | backorder
        image_url=f.get("image_link"),          # [Google] [Awin] [Webgains] image_link: the photo, used exactly as given
        buy_link=(f.get("aw_deep_link")         # [Awin] aw_deep_link: Awin's tracked link
                  or f.get("link")),            # [Google] [Webgains] link; unsure: whether Webgains' link is already
                                                #          its tracked link, as a buy link must be
        feed_updated_at=None,                   # [Google] no time per product in the format: the feed's own is used
    )
