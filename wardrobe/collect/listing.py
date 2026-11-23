"""The generic listing reader: the products on any store's category page.

For the stores without a reader of their own (COS and Weekday have theirs: cos.py, weekday.py). It is handed the
page's HTML and the JSON the page fetched while it loaded (browser.Session.fetch_listing), and looks for the products
in four places, in this order:

  1. schema.org data: <script type="application/ld+json"> with an ItemList of Products, or Products, with offers
  2. microdata: elements marked itemtype="…schema.org/Product", with itemprop="name", "price" and so on
  3. the JSON the page carries: Next.js data (__NEXT_DATA__, and the streamed "flight" data of newer Next.js pages),
     React Router's streamed data, <script type="application/json">, objects a script assigns
     (window.__STATE__ = {…}), and objects written into the tiles themselves (data-article="{…}")
  4. the JSON the page fetched while it loaded

What a later place says about a product an earlier place found fills in what that one left out (its colour, sizes,
fabric). A later place adds products of its own when the earlier ones found none, or when its objects are of the
same kind as theirs (more of the same grid, loaded as the page was scrolled).

In any JSON it looks for product-like objects: a name, a price, and a link or a picture. Of the lists of them it
keeps the grid (the longest list, and lists nearly as long), not the carousels beside it ("You may also like").
A product the page shows in several colours, each with an article number of its own (H&M's swatches, Foot Locker's
variants), is kept once per colour.

    parse_listing(html, base, fetched, store) -> [{"store", "sku", "name", "slug", "price", "price_before",
        "colour", "colour_hex", "url", "image_url", "sizes_all", "sizes_in_stock", "in_stock",
        "composition_text" (where the page gives the fibres with their shares), "fabric_words" (where it only names
        them)}, …]

Only what the pages say is kept; a key is empty when they do not say it. Nothing is requested here.
"""
from __future__ import annotations

import html as html_lib
import json
import math
import re
import sys
from html.parser import HTMLParser
from typing import Any
from urllib.parse import unquote, urljoin, urlsplit

from .. import colours, composition, menswear
from ..feeds.rows import parse_price
from . import generic, pages

LISTING_GIVES = "name, price, colour and picture where the page gives them"

NAME_KEYS = ("name", "productName", "title", "displayName", "product_name", "productTitle", "nameEn")
SKU_KEYS = ("sku", "articleCode", "articleId", "articleNumber", "productCode", "productId", "styleColor",
            "productID", "code", "id", "handle", "baseProduct", "reference")
PRICE_KEYS = ("price", "salePrice", "currentPrice", "finalPrice", "sellingPrice", "priceValue", "prices",
              "priceRange", "pricing", "offers", "priceInfo", "detail")
BEFORE_KEYS = ("originalPrice", "regularPrice", "listPrice", "priceBefore", "wasPrice", "oldPrice", "strikePrice",
               "strikeThroughPrice", "compareAtPrice", "priceBeforeDiscount", "crossedOutPrice", "initialPrice",
               "compareAtPriceRange", "rrp", "originalFormattedPrice")      # (OLYMP: its sale price's "was")
COLOUR_KEYS = ("colour", "color", "colorName", "colourName", "colorDescription", "colourDescription", "variantName",
               "colorLabel", "colourLabel", "mainColor", "colorDisplayName")
HEX_KEYS = ("colorCode", "colourCode", "hex", "colorHex", "hexCode", "colors")
URL_KEYS = ("url", "pdpUrl", "productUrl", "link", "href", "uri", "canonicalUrl", "productLink", "pdpLink", "seoUrl",
            "path")
IMAGE_KEYS = ("image", "imageUrl", "productImage", "images", "media", "picture", "thumbnail", "img", "mainImage",
              "primaryImage", "imageSrc", "thumbnailUrl", "modelImage", "featuredImage", "xmedia", "prvMainImages")
SIZE_KEYS = ("sizes", "sizeVariants", "availableSizes")
MATERIAL_KEYS = ("material", "composition", "fabric", "materials", "materialComposition", "fabricComposition")
STOCK_KEYS = ("availability", "inStock", "available", "availableForSale", "isAvailable", "sellable", "soldOut",
              "isSoldOut", "outOfStock")
VARIANT_KEYS = ("swatches", "variantOptions", "colorVariants", "colourVariants", "colours", "variants", "articles",
                "colorSiblingProducts", "otherColorsFromSolr", "otherColors")

_SOLD_OUT_WORDS = ("outofstock", "soldout", "out_of_stock", "sold_out", "notavailable", "unavailable")


# ── small readers of values ──────────────────────────────────────────────────

def _unwrap(value: Any) -> Any:
    """{"value": x} (a Shopify detail), {"name": x}, or a list's first item, as the plain value inside."""
    for _ in range(4):
        if isinstance(value, dict):
            inner = next((value[k] for k in ("value", "name", "label", "text") if k in value), None)
            if inner is None:
                return value
            value = inner
        elif isinstance(value, list) and value and not isinstance(value[0], (dict, list)):
            value = value[0]
        else:
            return value
    return value


def _text(value: Any, longest: int = 200) -> str:
    value = _unwrap(value)
    if isinstance(value, (str, int)) and not isinstance(value, bool):
        words = " ".join(str(value).split())
        return words if 0 < len(words) <= longest else ""
    return ""


def _money(value: Any, depth: int = 0) -> float | None:
    """A price in euros from a number, a text ("19,99 €") or an object holding one; the lowest of a list."""
    if depth > 4 or value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value) if math.isfinite(value) and 0 < value < 100_000 else None
    if isinstance(value, str):
        amount, money = parse_price(value)
        return amount if amount is not None and 0 < amount < 100_000 and money in (None, "EUR") else None
    if isinstance(value, dict):
        if "centAmount" in value:
            cents = _money(value["centAmount"], depth + 1)
            return round(cents / 100, 2) if cents else None
        for key in ("value", "amount", "current", "sale", "salePrice", "price", "priceAsNumber", "minPrice", "lowPrice",
                    "minVariantPrice", "raw", "number", "selling", "finalPrice"):
            if key in value:
                found = _money(value[key], depth + 1)
                if found is not None:
                    return found
        return None
    if isinstance(value, list):
        amounts = [m for m in (_money(v, depth + 1) for v in value) if m is not None]
        return min(amounts) if amounts else None
    return None


def _highest(value: Any) -> float | None:
    """The highest price in a list of prices ({"price": 7.99, "priceType": "whitePrice"}, …): the price before a sale."""
    if isinstance(value, list):
        found = [m for m in (_money(v) for v in value) if m is not None]
        return max(found) if len(found) > 1 else None
    return None


def _first(d: dict, keys: tuple[str, ...]) -> Any:
    return next((d[k] for k in keys if k in d and d[k] not in (None, "", [], {})), None)


def _absolute(url: str, base: str) -> str:
    url = (url or "").strip()
    if not url or url.startswith(("data:", "javascript:", "#")):
        return ""
    if url.startswith("//"):
        return "https:" + url
    return urljoin(base.rstrip("/") + "/", url)


def _same_site(url: str, base: str) -> bool:
    host, home = urlsplit(url).netloc.lower(), urlsplit(base).netloc.lower()
    root = ".".join(home.split(".")[-2:])
    return bool(host) and (host == home or host.endswith("." + root) or host == root)


def _image(value: Any, base: str, depth: int = 0) -> str:
    """The first picture address in a value: a text, a list of them, or objects with url / src."""
    if depth > 4 or value is None:
        return ""
    if isinstance(value, str):
        text = value.strip()
        if re.match(r"^(https?:)?//", text) or (text.startswith("/") and re.search(r"\.(jpe?g|png|webp|avif)", text, re.I)):
            return _absolute(text, base)
        return ""
    if isinstance(value, dict):
        for key in ("url", "src", "href", "imageUrl", "image", "large", "medium", "originalSrc", "transformedSrc", "value"):
            if key in value:
                found = _image(value[key], base, depth + 1)
                if found:
                    return found
        return ""
    if isinstance(value, list):
        for v in value:
            found = _image(v, base, depth + 1)
            if found:
                return found
    return ""


def _colour(value: str) -> str:
    """A colour as the store names it, with Foot Locker's way of naming the colours of a shoe or a shirt read as
    such: "Black-Black" is black, "Black-White" black and white ("Black / White"), and "Black-Glacier Silv" black
    with something else ("Black - Glacier Silv"): no plain piece's colour matches either (matching.colour_level)."""
    value = " ".join((value or "").split())
    if "-" in value and " " not in value.split("-")[0] and colours.find(value.split("-")[0]) is not None:
        parts = list(dict.fromkeys(p.strip() for p in value.split("-") if p.strip()))
        known = {colours.find(p) for p in parts}
        if len(parts) == 1 or known == {colours.find(parts[0])} and None not in known:
            return parts[0]
        return (" / " if None not in known else " - ").join(parts)
    return value


_MODEL_CODE = re.compile(r"\s+(?=[A-Za-z0-9./-]*\d)[A-Za-z0-9./-]{5,}$")


def _name(name: str) -> str:
    """A product's name as people read it: in ordinary letters where the store writes it in capitals (pages.tidy_name),
    and without the article code some stores put at its end ("NORDFADEN T-Shirt NF4711/02" is "Nordfaden T-Shirt")."""
    return pages.tidy_name(_MODEL_CODE.sub("", " ".join(name.split())))


def _colour_named(text: str) -> str:
    """The one colour word a text names, as it is written there; "" for none, or for more than one."""
    found: dict[str, str] = {}
    for word in re.findall(r"[^\W\d_]+", text or ""):
        key = colours.find(word)
        if key:
            found.setdefault(key, word)
    return next(iter(found.values())) if len(found) == 1 else ""


def link_colour(name: str, url: str, listed: str) -> str:
    """The colour to keep for a product: the listing's (`listed`), unless its own link names it more exactly.
      * A link that names the colour in a segment of its own, just before the product's number
        ("…/Kent/Bordeaux/p/1234/"): where that segment is one colour Stilsmith knows ("Bordeaux", "Off-White"), it
        is kept over the listing's broader word ("Rot", "White"), which is the colour family the store files it
        under. A segment that names two colours ("Schwarz-Braun") or none known leaves the listing's.
      * A link that is the product's name, then its colour, then a number ("…/p/l-s-nordfaden-shirt-salt-4711" for
        "L/S Nordfaden Shirt"): the words between are the colour as the store names it ("Salt"), where the listing
        gives none and they name at most one colour Stilsmith knows."""
    path = unquote(urlsplit(url).path) if url else ""
    own = re.search(r"/([^/]+)/p/[^/]+/?$", path)
    if own:
        segment = own.group(1).replace("_", " ")
        keys = {colours.find(word) for word in re.split(r"[\s-]+", segment) if word} - {None}
        if colours.find(segment) is not None and len(keys) <= 1:
            return segment
    if not listed and name:
        last = path.rstrip("/").rsplit("/", 1)[-1].lower()
        stem = re.sub(r"[^a-z0-9äöüß]+", "-", name.lower()).strip("-")
        if stem and last.startswith(stem + "-"):
            rest = re.sub(r"(-\d+)+$", "", last[len(stem) + 1:])
            words = [word for word in rest.split("-") if word]
            # (two colours Stilsmith knows, "black-white" or "blue-stone-washed", are not one: no colour is said)
            if words and not re.search(r"\d", rest) and len({colours.find(w) for w in words} - {None}) <= 1:
                return " ".join(word.capitalize() for word in words)
    return listed


def _hex(value: Any) -> str | None:
    text = _text(value, 9).lstrip("#")
    return f"#{text.upper()}" if re.fullmatch(r"[0-9a-fA-F]{6}", text) else None


def _in_stock(d: dict) -> bool | None:
    for key in STOCK_KEYS:
        if key not in d:
            continue
        value = d[key]
        if isinstance(value, dict):
            value = value.get("stockState", value.get("status", value.get("value")))
        if isinstance(value, bool):
            return not value if key in ("soldOut", "isSoldOut", "outOfStock") else value
        if isinstance(value, str):
            flat = value.lower().replace(" ", "").rsplit("/", 1)[-1]
            return not any(word in flat for word in _SOLD_OUT_WORDS)
    return None


def _sizes(d: dict) -> tuple[list[str], list[str]]:
    """(every size the page names, those it says are in stock): only what it says."""
    found = _first(d, SIZE_KEYS)
    if not isinstance(found, list):
        return [], []
    every, stocked = [], []
    for s in found:
        if isinstance(s, str):
            every.append(s)
            continue
        if not isinstance(s, dict):
            continue
        label = _text(_first(s, ("label", "name", "size", "value", "displayName", "sizeName", "title")), 12)
        if not label:
            continue
        every.append(label)
        stock = _first(s, ("inStock", "available", "isAvailable", "stock", "quantity", "availability"))
        if isinstance(stock, bool) and stock or isinstance(stock, (int, float)) and not isinstance(stock, bool) \
                and stock > 0 or isinstance(stock, str) and "instock" in stock.lower().replace("_", ""):
            stocked.append(label)
    return every, stocked


def _nested(d: dict, depth: int = 2):
    """(key, value) of an object and of the objects inside it, a few levels deep."""
    for key, value in d.items():
        yield key, value
        if depth and isinstance(value, dict):
            yield from _nested(value, depth - 1)


def _fibre_words(text: str) -> str:
    """The words of a text that name a fibre ("Baumwolljersey" in "Ein weißes T-Shirt aus Baumwolljersey"): what a
    listing says of a product's fabric when it gives no shares."""
    found = [w.strip(".,;:()") for w in (text or "").split() if composition.guess(w.strip(".,;:()"))[0]]
    return " ".join(dict.fromkeys(found))[:80]


def _sku_from(url: str) -> str:
    """An article number from a product link: its last long run of digits, else its last part."""
    path = urlsplit(url).path.rstrip("/")
    digits = re.findall(r"\d{5,}", path)
    if digits:
        return digits[-1]
    last = path.rsplit("/", 1)[-1]
    return re.sub(r"\.\w+$", "", last)


_SIZE_CODE = re.compile(r"\d{2,4}|\d?X{0,3}[SML]")       # "L", "XXL", "3XL", "38" (a collar), "3130" (31/30)


def article(sku: str, url: str) -> str:
    """The article number a product keeps from one collection to the next: its own, unless that is the number its link
    names followed by a size, which a listing gives when it shows the product in one of its sizes ("4711L" or
    "47113130" for the link ".../p/4711/"): then the link's number, whatever size happens to be shown."""
    number = _sku_from(url) if url else ""
    if number.isdigit() and sku.startswith(number) and _SIZE_CODE.fullmatch(sku[len(number):]):
        return number
    return sku


def _slug(url: str) -> str:
    return re.sub(r"\.\w+$", "", urlsplit(url).path.rstrip("/").rsplit("/", 1)[-1])


def _fabric(text: str) -> tuple[str, str]:
    """(the fibres with their shares, or ""; the fabric named without them, or ""): from a material line."""
    text = " ".join((text or "").split())[:300]
    if not text:
        return "", ""
    if composition.stated(text):
        return composition.stated(text), ""
    named, _ = composition.guess(text)
    return "", (text[:80] if named else "")


# ── product-like objects in JSON ─────────────────────────────────────────────

def _productish(d: dict) -> bool:
    """A name, a price, and a link, a picture or an article number."""
    if not any(_text(d.get(k)) for k in NAME_KEYS):
        return False
    if all(_money(d[k]) is None for k in PRICE_KEYS if k in d):
        return False
    return any(k in d for k in URL_KEYS + IMAGE_KEYS + SKU_KEYS)


def _groups(tree: Any) -> list[list[dict]]:
    """The product-like objects of a JSON tree, grouped by the list that holds them, in the page's order. A product's
    own colours and sizes are not looked into here (_variants reads them)."""
    groups: dict[int, list[dict]] = {}
    seen: set[int] = set()
    stack: list[tuple[Any, int | None]] = [(tree, None)]
    while stack:
        node, holder = stack.pop()
        if id(node) in seen:
            continue
        seen.add(id(node))
        if isinstance(node, dict):
            if _productish(node):
                groups.setdefault(holder if holder is not None else id(node), []).append(node)
                continue
            stack += [(v, None) for v in reversed(list(node.values())) if isinstance(v, (dict, list))]
        elif isinstance(node, list):
            stack += [(v, id(node)) for v in reversed(node) if isinstance(v, (dict, list))]
    return list(groups.values())


def _grid(groups: list[list[dict]]) -> list[list[dict]]:
    """The grid: the longest list of products, and the lists nearly as long (the same products under another name,
    or the grid in parts); never the short lists beside it."""
    if not groups:
        return []
    longest = max(len(g) for g in groups)
    if longest < 3:
        return [g for g in groups if len(g) == longest]
    return [g for g in groups if len(g) >= max(3, longest // 2)]


def _from_object(d: dict, base: str) -> dict | None:
    """One product from a product-like object, in the reader's shape (see the top of this file), or None."""
    name = next((t for t in (_text(d.get(k)) for k in NAME_KEYS) if t), "")
    price = next((m for m in (_money(d.get(k)) for k in PRICE_KEYS if k in d) if m is not None), None)
    if not name or price is None:
        return None
    before = next((m for m in (_money(d.get(k)) for k in BEFORE_KEYS if k in d) if m is not None), None) \
        or _highest(d.get("prices"))
    raw_url = _text(_first(d, URL_KEYS), 600)
    url = _absolute(raw_url, base) if raw_url and not raw_url.startswith("http") or _same_site(raw_url, base) else ""
    sku = _text(_first(d, SKU_KEYS), 80).rsplit("/", 1)[-1] or (_sku_from(url) if url else "")
    colour = _text(_first(d, COLOUR_KEYS), 60)
    if not colour:          # Foot Locker: {"baseOptions": [{"selected": {"style": "Black-White"}}]}
        options = d.get("baseOptions")
        if isinstance(options, list) and options and isinstance(options[0], dict):
            colour = _text((options[0].get("selected") or {}).get("style"), 60)
    colour = link_colour(name, url, colour)
    if not colour:          # the colour its name or its link names ("…-hemd-uni-weiss-12345", "…/Kent/Marine/p/1234…")
        colour = _colour_named(name) or _colour_named(re.sub(r"[/_-]", " ", urlsplit(url).path) if url else "")
    every, stocked = _sizes(d)
    material = _text(_first(d, MATERIAL_KEYS), 300)
    fabric, words = _fabric(material)
    if not fabric and not words:        # H&M names the fabric only in its pictures' descriptions
        words = _fibre_words(" ".join(_text(v, 400) for k, v in _nested(d) if k.lower().endswith("alt")
                                      or k.lower().endswith("alttext")))
    ids = [t.lower() for t in (_text(d.get(k), 80).rsplit("/", 1)[-1] for k in SKU_KEYS + ("productTitleSlug",))
           if len(t) >= 4]
    return {
        "_ids": list(dict.fromkeys(ids)),
        "brand": _text(d.get("brandName") or d.get("brand"), 60),       # H&M also sells COS's and others' here
        "sku": sku, "name": _name(name), "slug": _slug(url) if url else "", "price": round(price, 2),
        "price_before": round(before, 2) if before and before > price else None,
        "colour": _colour(colour), "colour_hex": _hex(_first(d, HEX_KEYS)),
        "url": url, "image_url": _image(_first(d, IMAGE_KEYS), base),
        "sizes_all": every, "sizes_in_stock": stocked, "in_stock": _in_stock(d),
        "composition_text": fabric, "fabric_words": words,
    }


def _variants(d: dict, item: dict, base: str) -> list[dict]:
    """The product in its other colours, where the page gives each its own article number: H&M's swatches, Foot
    Locker's variant options. A colour without a number of its own is not a product of its own. Only what the page
    says of that colour itself is kept: a colour shown only as a swatch, without a price of its own, gets no price
    (the pool leaves it out: its price can differ from the first colour's), and one without a picture of its own no
    picture, never the first colour's."""
    out = []
    for key in VARIANT_KEYS:
        found = d.get(key)
        if isinstance(found, dict):
            found = found.get("nodes") or (found.get("references") or {}).get("nodes")
        if not isinstance(found, list):
            continue
        for v in found:
            if not isinstance(v, dict):
                continue
            sku = _text(_first(v, SKU_KEYS), 80).rsplit("/", 1)[-1]
            colour = _text(_first(v, COLOUR_KEYS), 60)
            if not sku or not colour:
                continue
            if sku == item["sku"] or (item["url"] and f"/{sku}/" in item["url"]):
                # the product itself, in its own colour (OLYMP lists it among its colours): what it says of it counts
                item["colour"] = item["colour"] or _colour(colour)
                item["colour_hex"] = item["colour_hex"] or _hex(_first(v, HEX_KEYS))
                item["image_url"] = item["image_url"] or _image(_first(v, IMAGE_KEYS), base)
                continue
            raw = _text(_first(v, URL_KEYS), 600)
            url = _absolute(raw, base) if raw else (item["url"].replace(item["sku"], sku) if item["url"] and
                                                    item["sku"] in item["url"] else "")
            price = _money(_first(v, PRICE_KEYS))
            before = next((m for m in (_money(v.get(k)) for k in BEFORE_KEYS if k in v) if m is not None), None)
            if isinstance(v.get("price"), dict):
                before = before or _money(v["price"].get("listPrice"))
                price = _money(v["price"].get("salePrice")) or price
            image = item["image_url"].replace(item["sku"], sku) if item["sku"] and item["sku"] in item["image_url"] \
                else _image(_first(v, IMAGE_KEYS), base)
            every, stocked = _sizes(v)
            out.append({**item, "_ids": [sku.lower()], "sku": sku, "url": url, "slug": _slug(url) if url else "",
                        "colour": link_colour(item["name"], url, _colour(colour)),
                        "variant_of": "" if url else item["sku"],      # its link is its first colour's, once known
                        "colour_hex": _hex(_first(v, HEX_KEYS)), "price": round(price, 2) if price else None,
                        "price_before": round(before, 2) if before and price and before > price else None,
                        "image_url": image, "sizes_all": every, "sizes_in_stock": stocked,
                        "in_stock": _in_stock(v) if _in_stock(v) is not None else item["in_stock"]})
    return out


def _from_json(trees: list, base: str) -> tuple[list[dict], set[frozenset]]:
    """The products in some JSON trees (the grid of all of them together), and the kinds of objects they were read
    from."""
    items, kinds = [], set()
    for group in _grid([g for tree in trees for g in _groups(tree)]):
        for d in group:
            item = _from_object(d, base)
            if item:
                items.append(item)
                items += _variants(d, item, base)
                kinds.add(frozenset(d))
    return items, kinds


# ── the JSON a page carries ──────────────────────────────────────────────────

_SCRIPT = re.compile(r"<script([^>]*)>(.*?)</script>", re.S | re.I)


def _flight(html: str) -> list:
    """The JSON of a newer Next.js page's streamed "flight" data (self.__next_f.push([1, "…"]))."""
    parts = re.findall(r'self\.__next_f\.push\(\[1,\s*("(?:[^"\\]|\\.)*")\]\)', html)
    if not parts:
        return []
    try:
        text = "".join(json.loads(p) for p in parts)
    except ValueError:
        return []
    out = []
    for line in text.split("\n"):
        m = re.match(r"^[0-9a-zA-Z]+:(?:T[0-9a-f]+,)?([\[{].*)$", line)
        if m:
            try:
                out.append(json.loads(m.group(1)))
            except ValueError:
                continue
    return out


def _turbo(html: str) -> list:
    """React Router's streamed page data (window.__reactRouterContext.streamController.enqueue("…")): a flat list in
    which objects refer to other entries by their place, decoded back into plain objects."""
    parts = re.findall(r'streamController\.enqueue\(("(?:[^"\\]|\\.)*")\)', html)
    if not parts:
        return []
    try:
        lines = [line for line in "".join(json.loads(p) for p in parts).split("\n") if line]
        flat = json.loads(lines[0])
    except (ValueError, IndexError):
        return []
    if not isinstance(flat, list):
        return []
    promised: dict[int, int] = {}
    for line in lines[1:]:
        m = re.match(r"^P(\d+):(.*)$", line)
        if m:
            try:
                more = json.loads(m.group(2))
            except ValueError:
                continue
            if isinstance(more, list):
                promised[int(m.group(1))] = len(flat)
                flat.extend(more)
    made: dict[int, Any] = {}

    def build(i: Any) -> Any:
        if not isinstance(i, int) or isinstance(i, bool) or i < 0 or i >= len(flat):
            return None
        if i in made:
            return made[i]
        value = flat[i]
        if isinstance(value, dict):
            obj: dict = {}
            made[i] = obj
            for k, v in value.items():
                if k.startswith("_") and k[1:].isdigit() and int(k[1:]) < len(flat):
                    obj[str(flat[int(k[1:])])] = build(v)
            return obj
        if isinstance(value, list):
            if value and isinstance(value[0], str) and len(value[0]) == 1 and value[0].isupper():
                made[i] = build(promised[value[1]]) if value[0] == "P" and len(value) > 1 and value[1] in promised else None
                return made[i]
            arr: list = []
            made[i] = arr
            arr.extend(build(v) for v in value)
            return arr
        made[i] = value
        return value

    depth = sys.getrecursionlimit()
    sys.setrecursionlimit(max(depth, 20_000))
    try:
        return [build(0)]
    except RecursionError:
        return []
    finally:
        sys.setrecursionlimit(depth)


def _scripts(html: str) -> list:
    """Every other JSON a page carries: <script type="application/json"> (Next.js' __NEXT_DATA__ among them), and
    the objects written inside other scripts (window.__STATE__ = {…}), each found by reading JSON from where an
    object starts."""
    out = []
    decoder = json.JSONDecoder()
    for attrs, body in _SCRIPT.findall(html):
        kind = attrs.lower()
        if "ld+json" in kind or "__next_f" in body[:40] or "streamController" in body[:200]:
            continue
        if "application/json" in kind:
            try:
                out.append(json.loads(body))
            except ValueError:
                pass
            continue
        i = 0
        while len(body) > 400:
            start = body.find('{"', i)
            if start < 0:
                break
            try:
                obj, end = decoder.raw_decode(body, start)
            except ValueError:
                i = start + 2
                continue
            if end - start > 400:
                out.append(obj)
            i = end
    return out


_DATA_ATTRIBUTE = re.compile(r'\sdata-[\w-]+="(\{[^"]{20,}\})"')


def _attributes(html: str) -> list:
    """Objects a page writes into its elements' data- attributes (data-article='{"id": …, "name": …, "price": …}'),
    each given the first link and picture that follow it inside its tile, as one list (the grid)."""
    found = list(_DATA_ATTRIBUTE.finditer(html))
    out = []
    for n, m in enumerate(found):
        try:
            obj = json.loads(html_lib.unescape(m.group(1)))
        except ValueError:
            continue
        if not isinstance(obj, dict):
            continue
        end = found[n + 1].start() if n + 1 < len(found) else m.end() + 6000
        # its own element (<a href="…" data-article="…">) and what follows it, up to the next such object
        tile = html[max(html.rfind("<", 0, m.start()), m.start() - 2000):m.start()] + html[m.end():min(end, m.end() + 6000)]
        href = re.search(r'<a\b[^>]*?\bhref="([^"#]+)"', tile)
        img = re.search(r'<img\b[^>]*?\b(?:src|data-src)="([^"]+)"', tile)
        if href and not any(k in obj for k in URL_KEYS):
            obj["url"] = html_lib.unescape(href.group(1))
        if img and not any(k in obj for k in IMAGE_KEYS):
            obj["image"] = html_lib.unescape(img.group(1))
        out.append(obj)
    return [out] if out else []


# ── schema.org data and microdata ────────────────────────────────────────────

def _schema(html: str, base: str) -> list[dict]:
    """Products from the page's schema.org blocks: a Product with a name and an offer."""
    page = generic._Page()
    try:
        page.feed(html)
        page.close()
    except Exception:  # noqa: BLE001 — what was read so far is kept
        pass
    things: list[dict] = []
    for block in page.data:
        try:
            things += list(generic._things(json.loads(block)))
        except ValueError:
            continue
    items = []
    for thing in things:
        if not generic._is(thing, "Product") or not thing.get("offers"):
            continue
        amount, money = generic._offer_price(thing["offers"])
        name = generic._word(thing.get("name"))
        url = _absolute(generic._word(thing.get("url")) or "", base)
        if amount is None or money not in (None, "EUR") or not name or not url:
            continue
        offers = list(generic._things(thing["offers"]))
        fabric, words = _fabric(generic._word(thing.get("material")))
        items.append({
            "sku": generic._word(thing.get("sku")) or generic._word(thing.get("productID")) or _sku_from(url),
            "name": _name(name), "slug": _slug(url), "price": round(amount, 2), "price_before": None,
            "colour": _colour(generic._word(thing.get("color"))), "colour_hex": None, "url": url,
            "image_url": _image(thing.get("image"), base), "sizes_all": [], "sizes_in_stock": [],
            "in_stock": _in_stock(next((o for o in offers if "availability" in o), {})),
            "composition_text": fabric, "fabric_words": words,
        })
    return items


class _Microdata(HTMLParser):
    """The Products marked up as microdata: each one's itemprop values, and the first picture and link inside it."""

    VOID = {"meta", "link", "img", "br", "hr", "input", "source", "area", "base", "col", "embed", "param", "track", "wbr"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.products: list[dict] = []
        self._open: list[tuple[str, dict | None]] = []     # each open element, with the item it starts (if any)
        self._items: list[dict] = []                         # the items we are inside, innermost last
        self._text_for: tuple[dict, str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = {k: v or "" for k, v in attrs}
        started: dict[str, Any] | None = None
        if "itemscope" in a:
            started = {"type": a.get("itemtype", ""), "props": {}, "img": "", "alt": "", "href": ""}
            if "itemprop" in a and self._items:
                self._items[-1]["props"].setdefault(a["itemprop"], started)
            elif started["type"].rstrip("/").endswith("schema.org/Product"):
                self.products.append(started)
        elif "itemprop" in a and self._items:
            value = a.get("content") or a.get("href") or a.get("src")
            if value:
                self._items[-1]["props"].setdefault(a["itemprop"], value)
            elif tag not in self.VOID:
                self._text_for = (self._items[-1], a["itemprop"])
        for item in [i for i in reversed(self._items) if i["type"].rstrip("/").endswith("schema.org/Product")][:1]:
            if tag == "img" and not item["img"]:
                item["img"], item["alt"] = a.get("src") or a.get("data-src", ""), a.get("alt", "")
            if tag == "a" and not item["href"]:
                item["href"] = a.get("href", "")
        if started is not None:
            self._items.append(started)
        if tag not in self.VOID:
            self._open.append((tag, started))

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag not in self.VOID and self._open and self._open[-1][0] == tag:
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        if not any(t == tag for t, _ in self._open):
            return
        while self._open:
            t, started = self._open.pop()
            if started is not None and self._items and self._items[-1] is started:
                self._items.pop()
            if t == tag:
                break
        self._text_for = None

    def handle_data(self, data: str) -> None:
        if self._text_for and data.strip():
            item, prop = self._text_for
            item["props"].setdefault(prop, " ".join(data.split()))
            self._text_for = None


def _microdata(html: str, base: str) -> list[dict]:
    """Products from microdata: name, article number, price, link and picture; the colour and the fabric from the
    picture's description where it names them ("T-Shirt, Baumwolle, hellblau meliert")."""
    reader = _Microdata()
    try:
        reader.feed(html)
        reader.close()
    except Exception:  # noqa: BLE001
        pass
    items = []
    for found in reader.products:
        props = found["props"]
        offers = props.get("offers") if isinstance(props.get("offers"), dict) else {"props": {}}
        offer = offers["props"]
        name = props.get("name") if isinstance(props.get("name"), str) else ""
        amount = _money(offer.get("price") if isinstance(offer.get("price"), str) else None)
        if not name or amount is None or offer.get("priceCurrency", "EUR") not in ("EUR", ""):
            continue
        url = _absolute(str(offer.get("url") or props.get("url") or found["href"] or ""), base)
        if not url:
            continue
        alt = " ".join(found["alt"].split())
        parts = [p.strip() for p in alt.split(",") if p.strip()]
        colour = next((p for p in reversed(parts) if colours.find(p)), "")
        fabric, words = _fabric(next((p for p in parts if composition.guess(p)[0]), ""))
        availability = str(offer.get("availability") or "")
        image = props.get("image") if isinstance(props.get("image"), str) else found["img"]
        items.append({
            "sku": str(props.get("sku") if isinstance(props.get("sku"), str) else "") or _sku_from(url),
            "name": _name(name), "slug": _slug(url), "price": round(amount, 2), "price_before": None,
            "colour": colour, "colour_hex": None, "url": url, "image_url": _absolute(str(image or ""), base),
            "sizes_all": [], "sizes_in_stock": [],
            "in_stock": _in_stock({"availability": availability}) if availability else None,
            "composition_text": fabric, "fabric_words": words,
        })
    return items


# ── putting it together ──────────────────────────────────────────────────────

def _links_and_pictures(html: str) -> tuple[list[str], list[str]]:
    hrefs = re.findall(r'<a\b[^>]*?\bhref="([^"#]+)"', html)
    srcs = re.findall(r'<img\b[^>]*?\b(?:src|data-src)="([^"]+)"', html)
    # A srcset lists sizes ("…/a.jpg 375w, …/a.jpg 750w"): its first address
    srcs += [re.split(r",\s+", found)[0].split(" ")[0] for found in re.findall(r'\bsrcset="([^"]+)"', html)]
    return hrefs, srcs


def _fill(item: dict, base: str, hrefs: list[str], srcs: list[str]) -> None:
    """A product's link and picture from the page's own links and pictures, by its article number (or another of
    its names: Suitsupply's "handle"), where the data did not give them."""
    ids = [i for i in [item.get("sku", "").lower(), *item.get("_ids", [])] if len(i) >= 4]
    if not ids:
        return
    if not item.get("url"):
        href = next((h for i in ids for h in hrefs if i in h.lower()), "")
        item["url"] = _absolute(href, base) if href else ""
        item["slug"] = _slug(item["url"]) if item["url"] else ""
    if not item.get("image_url"):
        src = next((s for i in ids for s in srcs if i in s.lower()), "")
        item["image_url"] = _absolute(src, base) if src else ""


def _picture_host(item: dict, base: str, srcs: list[str]) -> None:
    """A picture the data gave by its path only ("/medias/…jpeg") is looked for among the page's own pictures, which
    may come from another of the store's hosts (OLYMP's come from api.olymp.com): that address is used."""
    url = item.get("image_url") or ""
    if not url.startswith(base.rstrip("/") + "/"):
        return
    path = urlsplit(url).path
    found = next((src for src in srcs if urlsplit(src).netloc and urlsplit(src).path == path), "")
    if found:
        item["image_url"] = _absolute(html_lib.unescape(found), base)


def _merge(into: dict[str, dict], index: dict[str, str], item: dict, add: bool) -> None:
    """Fill in what `into` already holds of this product from `item`, or add it (when `add`)."""
    key = (item["sku"] and index.get("sku " + item["sku"])) or (item["url"] and index.get("url " + item["url"]))
    if not key:
        if not add or not (item["sku"] or item["url"]):
            return
        key = item["sku"] or item["url"]
        into[key] = dict(item)
        for name in ("sku", "url"):
            if item[name]:
                index[f"{name} {item[name]}"] = key
        return
    held = into[key]
    for field, value in item.items():
        if value not in (None, "", []) and held.get(field) in (None, "", []):
            held[field] = value


def parse_listing(html: str, base: str, fetched: list | tuple = (), store: str = "") -> list[dict]:
    """The products on a category page (see the top of this file), each with `store` set to `store`."""
    products: dict[str, dict] = {}
    index: dict[str, str] = {}
    sources = [_schema(html, base), _microdata(html, base)]
    carried, kinds = _from_json([*_flight(html), *_turbo(html), *_scripts(html), *_attributes(html)], base)
    sources.append(carried)
    for found in sources:
        for item in found:
            _merge(products, index, item, add=True)
    if fetched:
        more, more_kinds = _from_json(list(fetched), base)
        alike = not products or any(len(a & b) >= 0.6 * max(len(a), len(b)) for a in kinds for b in more_kinds)
        for item in more:
            _merge(products, index, item, add=alike)
    hrefs, srcs = _links_and_pictures(html)
    for item in products.values():
        _fill(item, base, hrefs, srcs)
        _picture_host(item, base, srcs)
    by_sku = {item["sku"]: item for item in products.values() if item.get("sku")}
    out = []
    for item in products.values():
        first = by_sku.get(item.pop("variant_of", "") or "")
        if first is not None and not item.get("url") and first.get("url") and first["sku"] in first["url"]:
            item["url"] = first["url"].replace(first["sku"], item["sku"])
            item["slug"] = _slug(item["url"])
        if not item.get("url") or not item.get("sku") or not _same_site(item["url"], base):
            continue
        if menswear.link_not_for_men(item["url"]):
            continue                    # a women's or children's product beside the men's grid
        item.pop("_ids", None)
        if item.get("image_url", "").startswith("http://"):
            item["image_url"] = "https://" + item["image_url"][len("http://"):]
        out.append({**item, "store": store})
    return out
