"""Zara: reading a category page and a product page.

Both carry their data as one JSON object (`window.zara.viewPayload`). The
category page lists products with name, price and the colours they come in;
the product page adds, per colour, the sizes in stock, pictures, and the
fabric composition.
"""
from __future__ import annotations

from . import pages

KEY = "zara"
LISTING_GIVES = "name, price and colours"
IN_STOCK = {"in_stock", "low_on_stock"}

# Parts of a garment that are not its main fabric, in the words Zara uses.
_SECONDARY_PARTS = ("futter", "füll", "sohle", "besatz", "wattierung", "polster", "kapuze")


def _picture(xmedia: list[dict], width: int = 600) -> str:
    """Prefer the plain product shot over the model photos."""
    shots = [x for x in xmedia or [] if x.get("type") == "image" and x.get("url")]
    plain = next((x for x in shots if x.get("kind") == "plain"), None)
    chosen = plain or (shots[0] if shots else None)
    return chosen["url"].replace("{width}", str(width)) if chosen else ""


def product_url(base: str, seo: dict) -> str:
    return f"{base}/de/de/{seo.get('keyword', 'p')}-p{seo.get('seoProductId', '')}.html"


def parse_listing(html: str, base: str) -> list[dict]:
    payload = pages.zara_payload(html)
    items = []
    for group in payload.get("productGroups", []):
        for element in group.get("elements", []):
            for p in element.get("commercialComponents", []):
                seo = p.get("seo") or {}
                if p.get("type") != "Product" or not seo.get("seoProductId") or not p.get("price"):
                    continue
                shown = ((p.get("detail") or {}).get("colors") or [{}])[0]
                colours = [{"name": c.get("colorName", ""), "hex": c.get("hexColor")}
                           for c in p.get("availableColors") or []]
                if not colours and shown.get("name"):
                    colours = [{"name": shown["name"], "hex": None}]
                items.append({
                    "store": KEY,
                    "sku": seo["seoProductId"],
                    "name": pages.tidy_name(p.get("name", "")),
                    "slug": seo.get("keyword", ""),
                    "price": p["price"] / 100,
                    "price_before": None,
                    "colour": shown.get("name", ""),
                    "colour_hex": None,
                    "colours": colours,
                    "url": product_url(base, seo),
                    "image_url": _picture(shown.get("xmedia")),
                    "sizes_all": [],
                    "sizes_in_stock": [],
                    "in_stock": p.get("availability") in IN_STOCK,
                })
    return items


def _composition(detail: dict) -> str:
    """'Aussen: 100% wolle; Futter: 100% polyester' — main fabric first."""
    chunks = []
    for part in (detail.get("detailedComposition") or {}).get("parts", []):
        components = part.get("components") or []
        if not components:      # some garments list areas (body, sleeves) instead
            components = next((a.get("components") for a in part.get("areas") or [] if a.get("components")), [])
        listed = ", ".join(f"{c.get('percentage', '')} {c.get('material', '')}".strip() for c in components)
        if listed:
            label = str(part.get("description") or "").capitalize()
            secondary = any(word in label.lower() for word in _SECONDARY_PARTS)
            chunks.append((secondary, f"{label}: {listed}" if label else listed))
    return "; ".join(text for _, text in sorted(chunks, key=lambda c: c[0]))


def parse_product(html: str, base: str) -> dict | None:
    """Everything the product page says, with one entry per colour. None if it isn't a product page."""
    product = pages.zara_payload(html).get("product")
    if not product:
        return None
    detail, seo = product.get("detail") or {}, product.get("seo") or {}
    colours = []
    for c in detail.get("colors") or []:
        sizes = c.get("sizes") or []
        price = c.get("price") or next((s.get("price") for s in sizes if s.get("price")), None)
        colours.append({
            "id": str(c.get("id", "")),
            "product_id": c.get("productId"),
            "name": c.get("name", ""),
            "hex": c.get("hexCode"),
            "price": price / 100 if price else None,
            "sizes_all": [s.get("name", "") for s in sizes if s.get("name")],
            "sizes_in_stock": [s["name"] for s in sizes if s.get("name") and s.get("availability") in IN_STOCK],
            "image_url": _picture(c.get("xmedia") or c.get("mainImgs")),
            "description": " ".join(str(c.get("description") or "").split()),
        })
    return {
        "sku": seo.get("seoProductId", ""),
        "name": pages.tidy_name(product.get("name", "")),
        "slug": seo.get("keyword", ""),
        "url": product_url(base, seo),
        "composition_text": _composition(detail),
        "colours": colours,
    }
