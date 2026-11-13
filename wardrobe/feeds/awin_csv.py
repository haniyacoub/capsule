"""Awin's standard CSV feed: the columns a "Create-a-Feed" download gives, for stores that have not
moved to the Google format.

Where the column names come from:

    Awin's feed column guide (a PDF dated 27 Oct 2017, the newest column list that was found):
        https://cdn.document360.io/ec9ead62-8ecc-46ef-aac7-9b0a9081b40b/Images/Documentation/PM-FeedColumnDescriptions(1).pdf
    Awin's product feed questions and Create-a-Feed pages:
        https://help.awin.com/docs/de/product-feed-faqs   (24 Sep 2026)
        https://help.awin.com/developers/docs/downloading-feeds-using-create-a-feed.md

The guide groups the fashion columns under "Fashion"; a download names them "Fashion:size" and so
on. Names marked "unsure" below were not confirmed in those pages: check them against the first real
file, and change them here, in this one place.
"""
from __future__ import annotations

from pathlib import Path

from . import rows


def read(path: Path) -> rows.Result:
    return rows.collect(rows.delimited(path), product)


def product(record: dict) -> dict:
    get = record.get
    return rows.product(
        product_id=get("aw_product_id") or get("merchant_product_id"),   # Awin's id for it, else the store's
        group_id=get("parent_product_id"),               # unsure: the column for the sizes and colours of one garment
        name=get("product_name"),
        brand=get("brand_name"),
        category=get("merchant_category") or get("category_name"),       # the store's own words, else Awin's
        gender=get("Fashion:suitable_for"),              # "Male", "Unisex", ...
        colour=get("colour"),
        material=get("Fashion:material"),
        price=get("search_price"),                       # the price it sells for now
        sale_price=None,                                 # the older prices (rrp_price, product_price_old) are not read:
                                                         # only the current price is shown until the lawyer has answered
        currency=get("currency"),
        sizes=get("Fashion:size"),                       # "S,M,L"
        size_stock=rows.size_stock(get("size_stock_status")),   # "S:available|M:out of stock", "seldom used" says the guide
        available=rows.in_stock(get("in_stock"), get("stock_quantity")),   # 1 or 0, and a count
        image_url=get("merchant_image_url") or get("large_image") or get("aw_image_url"),   # as given, unchanged
        buy_link=get("aw_deep_link"),                    # the tracked link (merchant_deep_link is the untracked page)
        feed_updated_at=get("last_updated"),
    )
