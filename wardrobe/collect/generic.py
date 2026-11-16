"""The generic reader: what any store's product page says about its product, read from the page's HTML.

For the stores that have no reader of their own (Tom Tailor, OTTO, Hirmer, Breuninger, Blue Tomato, Bergfreunde and
whichever store comes next). It never opens a page: it is handed the HTML as text. Stilsmith itself never fetches a
store's page, so the HTML is the page as the customer saved it from his own browser ("Save page as") and sent
along with the product's link (collect/manual.py). The tests use invented pages only (tests/fixtures/pages/).

Most stores describe a product inside its page in the same two public ways, made for search engines:

    schema.org data    <script type="application/ld+json"> with a "Product" (name, color, material, offers with
                       price and priceCurrency, audience.suggestedGender) and a "BreadcrumbList" (Herren > Hemden)
    Open Graph tags    <meta property="og:title">, <meta property="product:price:amount"> and so on

    read(html) -> {"name": "Oxford-Hemd", "price": 49.99, "currency": "EUR", "colour": "Hellblau",
                   "material": "100% Baumwolle", "gender": "male", "breadcrumbs": ["Herren", "Hemden"],
                   "address": "https://www.example.com/p/oxford-hemd-123"}

Only what the page says is returned; a key is missing when the page does not say it. The photo and the
description are not read: showing a store's photo or text needs that store's licence, and a pasted link has none.
"""
from __future__ import annotations

import json
import math
from html.parser import HTMLParser
from typing import Any

from ..feeds.rows import parse_price

class _Page(HTMLParser):
    """Collects the parts of a page that describe its product: the schema.org blocks, the meta tags, the title,
    the address the page gives for itself, and the words of a breadcrumb trail written as plain HTML."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.data: list[str] = []           # the text of each <script type="application/ld+json">
        self.meta: dict[str, str] = {}
        self.title = ""
        self.address = ""
        self.trail: list[str] = []          # the links' words inside an element marked as breadcrumbs
        self._script = self._in_title = False
        self._crumb_depth = 0               # how deep inside the breadcrumb element we are (0: outside)
        self._crumb_tag = ""
        self._crumb_text: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = {name: value or "" for name, value in attrs}
        if tag == "script" and a.get("type", "").strip().lower() == "application/ld+json":
            self._script = True
            self.data.append("")
        elif tag == "title" and not self.title:
            self._in_title = True
        elif tag == "meta" and (a.get("property") or a.get("name")) and "content" in a:
            self.meta.setdefault((a.get("property") or a.get("name") or "").strip().lower(), a["content"].strip())
        elif tag == "link" and a.get("rel", "").strip().lower() == "canonical":
            self.address = self.address or a.get("href", "").strip()
        marked = " ".join((a.get("class", ""), a.get("id", ""), a.get("aria-label", ""), a.get("itemtype", ""))).lower()
        if self._crumb_depth:
            if tag == self._crumb_tag:
                self._crumb_depth += 1
            if tag in ("a", "li") and self._crumb_text is None:
                self._crumb_text = []
        elif "breadcrumb" in marked and tag in ("nav", "ol", "ul", "div"):
            self._crumb_depth, self._crumb_tag = 1, tag

    def handle_endtag(self, tag: str) -> None:
        if tag == "script":
            self._script = False
        elif tag == "title":
            self._in_title = False
        if self._crumb_depth:
            if tag in ("a", "li") and self._crumb_text is not None:
                words = " ".join(" ".join(self._crumb_text).split())
                if words and words not in self.trail:
                    self.trail.append(words)
                self._crumb_text = None
            if tag == self._crumb_tag:
                self._crumb_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._script:
            self.data[-1] += data
        elif self._in_title:
            self.title += data
        elif self._crumb_text is not None:
            self._crumb_text.append(data)


def _things(node: Any):
    """Every schema.org object in a block: the block itself, the members of a list or an "@graph", and what they hold."""
    if isinstance(node, list):
        for item in node:
            yield from _things(item)
    elif isinstance(node, dict):
        yield node
        for value in node.values():
            if isinstance(value, (dict, list)):
                yield from _things(value)


def _is(thing: dict, *kinds: str) -> bool:
    kind = thing.get("@type")
    return any(k in kinds for k in (kind if isinstance(kind, list) else [kind]))


def _word(value: Any) -> str:
    """A value as one line of text: a plain string, or the "name" of an object ({"@type": "Brand", "name": "X"})."""
    if isinstance(value, dict):
        value = value.get("name")
    if isinstance(value, list):
        value = value[0] if value else None
    return " ".join(str(value).split()) if isinstance(value, (str, int, float)) and not isinstance(value, bool) else ""


def _offer_price(offers: Any) -> tuple[float | None, str | None]:
    """The price a product sells for: its offer's price, or the lowest of several (each size may be its own offer)."""
    found: list[tuple[float, str | None]] = []
    for offer in _things(offers):
        if not _is(offer, "Offer", "AggregateOffer"):
            continue
        amount, money = parse_price(offer.get("price", offer.get("lowPrice")), _word(offer.get("priceCurrency")) or None)
        if amount is not None and math.isfinite(amount) and 0 < amount <= 100_000:
            found.append((amount, money))
    return min(found, key=lambda pair: pair[0]) if found else (None, None)


def _crumbs(thing: dict) -> list[str]:
    """['Herren', 'Hemden'] from a schema.org BreadcrumbList, in its own order."""
    items = [i for i in thing.get("itemListElement") or [] if isinstance(i, dict)]
    try:
        items.sort(key=lambda i: float(i.get("position", 0)))
    except (TypeError, ValueError):
        pass
    names = [_word(i.get("name")) or _word(i.get("item")) for i in items]
    return [name for name in names if name]


def read(html: str) -> dict:
    """What a product page says about its product (see the top of this file). {} for a page that says nothing."""
    page = _Page()
    try:
        page.feed(html)
        page.close()
    except Exception:  # noqa: BLE001 - a page too broken to read says nothing more; what was read so far is kept
        pass
    things: list[dict] = []
    for block in page.data:
        try:
            things += list(_things(json.loads(block)))
        except ValueError:
            continue                    # one block that is not JSON costs only that block
    product = next((t for t in things if _is(t, "Product", "ProductGroup")), {})
    out: dict[str, Any] = {}

    name = _word(product.get("name")) or page.meta.get("og:title", "") or " ".join(page.title.split())
    if name:
        out["name"] = name[:200]
    amount, money = _offer_price(product.get("offers"))
    if amount is None:
        amount, money = parse_price(page.meta.get("product:price:amount") or page.meta.get("og:price:amount"),
                                    page.meta.get("product:price:currency") or page.meta.get("og:price:currency"))
        if amount is not None and not (math.isfinite(amount) and 0 < amount <= 100_000):
            amount = None
    if amount is not None:
        out["price"], out["currency"] = round(amount, 2), money or "EUR"
    for key, value in (("colour", _word(product.get("color")) or page.meta.get("product:color", "")),
                       ("material", _word(product.get("material")) or page.meta.get("product:material", "")),
                       ("category", _word(product.get("category")) or page.meta.get("product:category", ""))):
        if value:
            out[key] = value[:200]
    audience = product.get("audience")
    gender = (_word(audience.get("suggestedGender")) if isinstance(audience, dict) else "") \
        or page.meta.get("product:gender", "")
    if gender:
        out["gender"] = gender[:40]
    trail = next((crumbs for crumbs in (_crumbs(t) for t in things if _is(t, "BreadcrumbList")) if crumbs), page.trail)
    if trail:
        out["breadcrumbs"] = [crumb[:80] for crumb in trail[:12]]
    address = page.address or page.meta.get("og:url", "") or _word(product.get("url"))
    if address:
        out["address"] = address[:500]
    return out
