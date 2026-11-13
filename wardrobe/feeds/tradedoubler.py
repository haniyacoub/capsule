"""Tradedoubler's Products API, as JSON: the whole feed of one store (its `productsUnlimited` download).

Where the field names come from: Tradedoubler's public developer documentation,
    https://dev.tradedoubler.com/products/publisher
which lists for each product its name, brand, productImage (url, width, height), size, groupingId,
`fields` (the store's own extra fields: colour is the documentation's example), and per offer the
tracked productUrl, price and priceHistory, availability, inStock (a count) and modified.

Unsure: exactly where `size` and the price sit. This reads `size` on the product and, failing that,
a store field called "size"; the price from the newest entry of the offer's priceHistory and, failing
that, the offer's own `price`. The id is the offer's sourceProductId (the store's own id), else the
product's sku. Check these against the first real file, and change them here, in this one place.
When a product has several offers, the first is used: a store's own feed has one.
"""
from __future__ import annotations

import json
from pathlib import Path

from . import rows


def read(path: Path) -> rows.Result:
    with rows.open_text(path) as f:
        data = json.load(f)
    products = data.get("products") if isinstance(data, dict) else data
    return rows.collect((p if isinstance(p, dict) else None for p in products or []), product)


def product(record: dict) -> dict:
    offers = [o for o in record.get("offers") or [] if isinstance(o, dict)]
    offer = offers[0] if offers else {}
    fields = {str(f.get("name", "")).strip().lower(): f.get("value")
              for f in record.get("fields") or [] if isinstance(f, dict)}
    image = record.get("productImage")
    identifiers = record.get("identifiers")
    identifiers = identifiers if isinstance(identifiers, dict) else {}
    categories = [c.get("name") for c in record.get("categories") or [] if isinstance(c, dict)]
    return rows.product(
        product_id=offer.get("sourceProductId") or identifiers.get("sku") or record.get("sku"),
        group_id=record.get("groupingId"),
        name=record.get("name"),
        brand=record.get("brand"),
        category=categories[0] if categories else None,
        gender=fields.get("gender"),
        colour=fields.get("colour") or fields.get("color"),
        material=fields.get("material"),
        price=_current_price(offer),                     # {"value": "49.95", "currency": "EUR"}
        sizes=record.get("size") or fields.get("size"),
        available=rows.in_stock(offer.get("availability"), offer.get("inStock")),   # words, then the count
        image_url=image.get("url") if isinstance(image, dict) else image,          # as given, unchanged
        buy_link=offer.get("productUrl"),                # the tracked link
        feed_updated_at=offer.get("modified"),           # milliseconds since 1970
    )


def _current_price(offer: dict):
    """The newest entry of the price history, else the offer's plain price."""
    history = [h for h in offer.get("priceHistory") or [] if isinstance(h, dict) and h.get("price") is not None]
    if history:
        return max(history, key=lambda h: rows.parse_time(h.get("date")) or "")["price"]
    return offer.get("price")
