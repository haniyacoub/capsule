"""Tradedoubler's Products API, as JSON: the whole feed of one store (its `productsUnlimited` download).

Each mapping line below ends with the tag of the public documentation its field name comes from:

    [TD]      Tradedoubler's public developer documentation:
                  https://dev.tradedoubler.com/products/publisher
              which lists for each product its name, brand, ean, sku, productImage (url, width,
              height), size, groupingId, `fields` (the store's own extra fields: colour is the
              documentation's example), and per offer the tracked productUrl, sourceProductUrl,
              price and priceHistory, availability, inStock (a count), deliveryTime and modified.
    unsure    where exactly the field sits in the JSON, or what a store calls its own field, was
              not confirmed in that page: check it against the first real file, and change it
              here, in this one place.

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
        product_id=(offer.get("sourceProductId")     # [TD] unsure: the store's own id on the offer (the
                                                     #      page names sourceProductUrl)
                    or identifiers.get("sku")        # [TD] sku; unsure: that it sits under "identifiers"
                    or record.get("sku")),           # [TD] sku
        group_id=record.get("groupingId"),           # [TD] groupingId
        name=record.get("name"),                     # [TD] name
        brand=record.get("brand"),                   # [TD] brand
        category=categories[0] if categories else None,      # [TD] unsure: not in its list, a guess: the first
                                                             #      of the product's "categories", by "name"
        gender=fields.get("gender"),                 # [TD] a store field; unsure: that a store calls it "gender"
        colour=fields.get("colour") or fields.get("color"),  # [TD] a store field, the page's own example;
                                                             #      unsure: its exact name
        material=fields.get("material"),             # [TD] a store field; unsure: that a store calls it "material"
        price=_current_price(offer),                 # [TD] priceHistory, else price; unsure: their shape,
                                                     #      taken to be {"value": "49.95", "currency": "EUR"}.
                                                     #      Only the price it sells for now is read, so no sale
                                                     #      dates either; unsure: whether an offer carries any
        sizes=record.get("size") or fields.get("size"),      # [TD] size; unsure: on the product or a store field
        available=rows.in_stock(offer.get("availability"),   # [TD] availability, in words
                                offer.get("inStock")),       # [TD] inStock, a count
        image_url=image.get("url") if isinstance(image, dict) else image,   # [TD] productImage's url, unchanged
        buy_link=offer.get("productUrl"),            # [TD] productUrl, the tracked link
        feed_updated_at=offer.get("modified"),       # [TD] modified; unsure: milliseconds since 1970, as read here
    )


def _current_price(offer: dict):
    """The newest entry of the price history, else the offer's plain price."""
    history = [h for h in offer.get("priceHistory") or [] if isinstance(h, dict) and h.get("price") is not None]
    if history:
        return max(history, key=lambda h: rows.parse_time(h.get("date")) or "")["price"]
    return offer.get("price")
