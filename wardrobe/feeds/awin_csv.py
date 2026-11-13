"""Awin's standard CSV feed: the columns a "Create-a-Feed" download gives, for stores that have not
moved to the Google format.

Each mapping line below ends with the tag of the public documentation its column name comes from:

    [Guide]   Awin's feed column guide, a PDF dated 27 Oct 2017 (the newest column list that was found):
                  https://cdn.document360.io/ec9ead62-8ecc-46ef-aac7-9b0a9081b40b/Images/Documentation/PM-FeedColumnDescriptions(1).pdf
    [FAQ]     Awin's product feed questions, which name the fields every feed must have in words
              (product ID, name, price, image URL, URL, merchant category, description):
                  https://help.awin.com/docs/de/product-feed-faqs   (24 Sep 2026)
    [Images]  Awin's resized copies of the photos, whose addresses must not be changed:
                  https://help.awin.com/developers/docs/awin-resize-and-caching-service.md
    unsure    the column name was not confirmed in those pages: check it against the first real
              file, and change it here, in this one place.

The guide puts suitable_for, size and material in a "Fashion" group. This reads them as
"Fashion:size" and so on, the way a Create-a-Feed download is expected to name them (unsure):
    https://help.awin.com/developers/docs/downloading-feeds-using-create-a-feed.md
"""
from __future__ import annotations

from pathlib import Path

from . import rows


def read(path: Path) -> rows.Result:
    return rows.collect(rows.delimited(path), product)


def product(record: dict) -> dict:
    get = record.get
    return rows.product(
        product_id=(get("aw_product_id")         # [Guide] [FAQ] Awin's id for it; unsure: the name
                    or get("merchant_product_id")),   # [Guide] the store's own id; unsure: the name
        group_id=get("parent_product_id"),       # [Guide] unsure: the column for the sizes and colours of one garment
        name=get("product_name"),                # [Guide] [FAQ] unsure: the name
        brand=get("brand_name"),                 # [Guide] unsure: the name
        category=(get("merchant_category")       # [Guide] [FAQ] the store's own words; unsure: the name
                  or get("category_name")),      # [Guide] Awin's own category; unsure: the name
        gender=get("Fashion:suitable_for"),      # [Guide] suitable_for: "Male", "Unisex", ...; unsure: "Fashion:"
        colour=get("colour"),                    # [Guide] colour
        material=get("Fashion:material"),        # [Guide] material; unsure: "Fashion:"
        price=get("search_price"),               # [Guide] search_price: the price it sells for now
        sale_price=None,                         # [Guide] rrp_price, a "was" price, is not read: only the
                                                 #         current price is shown until the lawyer has answered
        currency=get("currency"),                # [Guide] unsure: the name. Without one, euros are assumed
        sizes=get("Fashion:size"),               # [Guide] size: "S,M,L"; unsure: "Fashion:"
        size_stock=rows.size_stock(get("size_stock_status")),   # [Guide] "S:available|M:out of stock",
                                                                #         marked "Seldom used" in the guide
        available=rows.in_stock(get("in_stock"),          # [Guide] in_stock: 1 or 0
                                get("stock_quantity")),   # [Guide] stock_quantity: a count
        image_url=(get("merchant_image_url")     # [Guide] the store's photo, as given, unchanged
                   or get("large_image")         # [Guide] a larger photo, as given
                   or get("aw_image_url")),      # [Images] Awin's resized copy, its address unchanged
        buy_link=get("aw_deep_link"),            # [Guide] the tracked link (the untracked deep link is not used)
        feed_updated_at=get("last_updated"),     # [Guide] last_updated
    )
