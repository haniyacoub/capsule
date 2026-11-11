"""Which products on a category page fit a slot.

A slot is a garment type in a colour, plus optional keywords ("merino",
"oxford"). A category page lists everything of that type. This module picks
the few that fit: right colour, not a patterned or multipack item, keyword
matches first, then cheapest first.
"""
from __future__ import annotations

import re

from .. import colours

# For jeans the stores say "blau" or "dunkelblau"; in the capsule that is indigo.
_DENIM_BLUES = {"indigo", "navy", "blue"}
CLOSE = 22   # how different two colours of one family may look and still count as "close"


def text_of(item: dict) -> str:
    return f"{item.get('name', '')} {item.get('slug', '')}".lower()


def colour_level(slot: dict, name: str | None, hex_: str | None, skip_words: tuple | list = ()) -> int:
    """2 = the slot's colour, 1 = a close shade of it, 0 = a different colour.

    The store's own colour name decides when it is one we know ("Marineblau");
    the swatch decides only for names we don't ("Mole", "Tobacco"). A "colour"
    that is really a pattern ("Gestreift") never matches.
    """
    want = slot["colour"]
    name = (name or "").strip()
    if any(word.strip() in name.lower() for word in skip_words):
        return 0
    parts = [p for p in re.split(r"\s*(?:/|&|\+|\bund\b|\band\b)\s*", name) if p.strip()]
    keys = {colours.find(p) for p in parts} - {None}
    if len(keys) > 1:
        return 0                                    # two-colour item ("Schwarz / Weiß", "Weiß & Navyblau")
    if " - " in name and slot["category"] != "jeans":
        return 0                                    # "Weiß - Rote Kontrastkanten", "Schwarz - Rückenprint"
    key = colours.find(name)
    measured = False
    if key is None:
        key, off = colours.nearest(hex_)
        if key is None or off > 20:
            return 0
        measured = off > 12                         # a loose swatch match is never "exact"
    if slot["category"] == "jeans" and want in _DENIM_BLUES and key in _DENIM_BLUES:
        return 2
    if key == want:
        return 1 if measured else 2
    a, b = colours.get(key), colours.get(want)
    return 1 if a.family == b.family and colours.distance(a.hex, b.hex) <= CLOSE else 0


def keyword_hits(keywords: str, text: str, vocabulary: dict) -> int:
    """How many of the slot's keywords the product name satisfies."""
    hits = 0
    for word in re.split(r"[\s,;]+", (keywords or "").lower()):
        if word and any(variant in text for variant in vocabulary.get(word, [word])):
            hits += 1
    return hits


def fits_type(item: dict, rules: dict, slot: dict, skip_words: list[str]) -> bool:
    """The include/exclude words for this garment type, and no patterns or multipacks."""
    text = text_of(item)
    include, exclude = rules.get("include", []), rules.get("exclude", [])
    if include and not any(word in text for word in include):
        return False
    if any(word in text for word in exclude):
        return False
    asked = f"{slot.get('keywords', '')} {slot.get('name', '')}".lower()
    if any(word.strip() in asked for word in skip_words):
        return True                 # the slot itself asks for a pattern ("striped"): don't filter
    return not any(word in text for word in skip_words)


def best_colour(item: dict, slot: dict, skip_words: tuple | list = ()) -> tuple[int, dict]:
    """(match level, the colour of this product that matches best)."""
    options = item.get("colours") or [{"name": item.get("colour", ""), "hex": item.get("colour_hex")}]
    scored = [(colour_level(slot, c.get("name"), c.get("hex"), skip_words), c) for c in options]
    return max(scored, key=lambda pair: pair[0])


def shortlist(items: list[dict], slot: dict, rules: dict, settings: dict) -> list[tuple[dict, dict]]:
    """The products that fit the slot, best first, as (product, matching colour)."""
    vocabulary = settings.get("keyword_words", {})
    skip_words = settings.get("skip_words", [])
    ranked = []
    for item in items:
        if not item.get("in_stock", True) or not fits_type(item, rules, slot, skip_words):
            continue
        level, colour = best_colour(item, slot, skip_words)
        if level:
            hits = keyword_hits(slot.get("keywords", ""), text_of(item), vocabulary)
            ranked.append(((-level, -hits, item["price"]), item, colour))
    ranked.sort(key=lambda entry: entry[0])
    return [(item, colour) for _, item, colour in ranked]
