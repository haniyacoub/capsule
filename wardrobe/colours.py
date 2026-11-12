"""Colour vocabulary: English names plus the German names the stores use, a
swatch colour, and the two facts the outfit rules need — the colour family
and whether the colour behaves as a neutral."""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Colour:
    key: str
    label: str
    hex: str
    family: str
    neutral: bool
    aliases: tuple[str, ...] = ()


_ALL = [
    Colour("white", "White", "#f5f4f0", "white", True,
           ("weiß", "weiss", "optical white", "bright white", "reinweiß")),
    Colour("ecru", "Ecru", "#e8e0cd", "white", True,
           ("off white", "offwhite", "cream", "creme", "cremefarben", "cremeweiß", "cremeweiss",
            "naturweiß", "natur", "wollweiß", "ivory", "elfenbein")),
    Colour("light-grey", "Light grey", "#c8c8c5", "grey", True,
           ("light gray", "hellgrau", "perlgrau", "eisgrau", "light grey melange", "hellgrau meliert")),
    Colour("grey", "Grey", "#8d8f92", "grey", True,
           ("gray", "grau", "mittelgrau", "graumeliert", "grey melange", "grey marl", "grau meliert")),
    Colour("charcoal", "Charcoal", "#3c3e42", "grey", True,
           ("anthrazit", "anthrazitgrau", "anthracite", "dunkelgrau", "dark grey", "dark gray", "graphit",
            "graphite", "marengo",
            "charcoal melange", "dark grey melange", "dunkelgrau meliert")),
    Colour("black", "Black", "#1b1b1c", "black", True, ("schwarz",)),
    Colour("navy", "Navy", "#1f2a44", "navy", True,
           ("marineblau", "marine", "dunkelblau", "dark blue", "dark navy", "navy blue",
            "dunkles marineblau", "nachtblau", "midnight blue", "midnight", "tintenblau")),
    Colour("indigo", "Indigo", "#2c4166", "denim", True,
           ("indigoblau", "indigo blue", "dark indigo", "dark denim", "denimblau", "jeansblau", "raw denim")),
    Colour("blue", "Blue", "#3f63a8", "blue", False,
           ("blau", "royalblau", "kobaltblau", "mittelblau", "mid blue", "washed blue", "verwaschenes blau")),
    Colour("light-blue", "Light blue", "#b9cce4", "blue", True,
           ("hellblau", "himmelblau", "sky blue", "pale blue", "light denim")),
    Colour("stone", "Stone", "#cdc4b2", "beige", True,
           ("stein", "steingrau", "sand", "sandfarben", "greige", "kitt", "putty",
            "helles taupe", "light taupe", "helles graubraun")),
    Colour("beige", "Beige", "#d5c19e", "beige", True,
           ("hellbeige", "light beige", "sandbeige", "biscuit", "oatmeal", "hafer")),
    Colour("taupe", "Taupe", "#6f695c", "beige", True,
           ("taupegrau", "mole", "mushroom", "graubraun", "gedecktes taupe", "dunkles taupe", "dark taupe")),
    Colour("camel", "Camel", "#b78855", "brown", True,
           ("kamel", "tan", "cognac", "hellbraun", "tabak", "tobacco", "karamell", "caramel", "toffee")),
    Colour("brown", "Brown", "#6a4933", "brown", True,
           ("braun", "mittelbraun", "schokobraun", "mocha", "mokka", "coffee", "kaffee", "nerzfarben",
            "mink", "walnuss", "haselnuss", "chestnut", "kastanie", "braun meliert")),
    Colour("dark-brown", "Dark brown", "#3d2a21", "brown", True,
           ("dunkelbraun", "espresso", "chocolate", "schokolade", "schokoladenbraun")),
    Colour("olive", "Olive", "#5b603d", "green", False,
           ("oliv", "olivgrün", "olive green", "khaki", "khakigrün", "khaki green", "dark khaki",
            "dunkles khaki", "army green", "military", "moosgrün")),
    Colour("green", "Forest green", "#2f4a3a", "green", False,
           ("forest", "dark green", "bottle green", "dunkelgrün", "grün", "tannengrün", "flaschengrün")),
    Colour("teal", "Teal", "#1f5a5e", "teal", False,
           ("petrol", "türkis", "turquoise", "dark turquoise", "dunkeltürkis")),
    Colour("burgundy", "Burgundy", "#5e1f2b", "red", False,
           ("bordeaux", "bordeauxrot", "weinrot", "burgunderrot", "wine red", "wine", "oxblood",
            "maroon", "dunkelrot")),
    Colour("rust", "Rust", "#a4502a", "orange", False,
           ("rost", "rostrot", "terracotta", "terrakotta", "orange", "ziegel", "brick", "kupfer", "copper")),
    Colour("red", "Red", "#b3261e", "red", False, ("rot",)),
    Colour("mustard", "Mustard", "#c69a2e", "yellow", False, ("senf", "senfgelb", "yellow", "gelb")),
    Colour("pink", "Pink", "#e3a7b5", "pink", False, ("rosa", "altrosa", "rose", "dusty pink")),
    Colour("purple", "Purple", "#5b3f73", "purple", False,
           ("lila", "violett", "violet", "dunkelviolett", "aubergine", "mauve", "flieder", "lilac",
            "plum", "pflaume")),
]

COLOURS: dict[str, Colour] = {c.key: c for c in _ALL}
UNKNOWN = Colour("unknown", "Unknown", "#b8b6b0", "unknown", True)

# Longest alias first, so "dark brown" wins over "brown" and "hellgrau" over "grau".
_INDEX = sorted(
    {(alias, c.key) for c in _ALL
     for alias in (c.key.replace("-", " "), c.label.lower(), *c.aliases)},
    key=lambda pair: (-len(pair[0]), pair[0]),
)
# German compounds the alias list doesn't spell out ("moosgrün", "taubenblau").
_STEMS = [("grün", "green"), ("blau", "blue"), ("grau", "grey"), ("braun", "brown"),
          ("weiß", "white"), ("weiss", "white"), ("schwarz", "black"), ("beige", "beige")]


def get(key: str | None) -> Colour:
    return COLOURS.get(key or "", UNKNOWN)


def find(text: str | None) -> str | None:
    """Colour key mentioned in free text (English or German), or None."""
    if not text:
        return None
    t = text.lower().replace("-", " ").replace("é", "e")
    for alias, key in _INDEX:
        if re.search(rf"(?<![a-zäöüß]){re.escape(alias)}(?![a-zäöüß])", t):
            return key
    for stem, key in _STEMS:
        if stem in t:
            return key
    return None


def parse_list(text: str | None) -> tuple[list[str], list[str]]:
    """'navy, grey and olive' -> (['navy', 'grey', 'olive'], unrecognised words)."""
    keys: list[str] = []
    unknown: list[str] = []
    for part in re.split(r"[,;/\n]|\band\b|\bund\b", text or ""):
        part = part.strip()
        if not part:
            continue
        key = find(part)
        if key is None:
            unknown.append(part)
        elif key not in keys:
            keys.append(key)
    return keys, unknown


def _rgb(hex_: str) -> tuple[int, int, int]:
    h = hex_.lstrip("#")
    if len(h) == 3:
        h = "".join(ch * 2 for ch in h)
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def is_hex(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(r"#?[0-9a-fA-F]{6}", value) is not None


def lightness(hex_: str) -> float:
    """Perceived lightness 0 (black) … 100 (white)."""
    r, g, b = _rgb(hex_)
    return (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255 * 100


def shade(hex_: str, amount: float) -> str:
    """Lighten (amount > 0) or darken (amount < 0) a colour; amount in -1 … 1."""
    out = []
    for ch in _rgb(hex_):
        target = 255 if amount > 0 else 0
        out.append(round(ch + (target - ch) * abs(amount)))
    return "#{:02x}{:02x}{:02x}".format(*out)


def _lab(hex_: str) -> tuple[float, float, float]:
    """CIE Lab coordinates: distances here match how different two colours look."""
    def linear(ch: int) -> float:
        v = ch / 255
        return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4

    r, g, b = (linear(ch) for ch in _rgb(hex_))
    x = (0.4124 * r + 0.3576 * g + 0.1805 * b) / 0.95047
    y = 0.2126 * r + 0.7152 * g + 0.0722 * b
    z = (0.0193 * r + 0.1192 * g + 0.9505 * b) / 1.08883

    def f(t: float) -> float:
        return t ** (1 / 3) if t > 0.008856 else 7.787 * t + 16 / 116

    fx, fy, fz = f(x), f(y), f(z)
    return 116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)


def distance(hex_a: str, hex_b: str) -> float:
    """How different two colours look (0 = identical, about 100 = black vs white)."""
    a, b = _lab(hex_a), _lab(hex_b)
    return sum((p - q) ** 2 for p, q in zip(a, b)) ** 0.5


def nearest(hex_: str | None) -> tuple[str | None, float]:
    """The colour in the table closest to a swatch: (key, distance)."""
    if not hex_ or not is_hex(hex_):
        return None, 999.0
    best = min(_ALL, key=lambda c: distance(hex_, c.hex))
    return best.key, distance(hex_, best.hex)


def contrast(hex_a: str, hex_b: str) -> float:
    """How well text in one colour reads on the other: the WCAG contrast ratio, from 1 (the
    same colour) to 21 (black on white). Small text needs at least 4.5 (WCAG 2.2 AA)."""
    def luminance(hex_: str) -> float:
        r, g, b = (v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4
                   for v in (ch / 255 for ch in _rgb(hex_)))
        return 0.2126 * r + 0.7152 * g + 0.0722 * b

    high, low = sorted((luminance(hex_a), luminance(hex_b)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def ink_on(hex_: str) -> str:
    """Readable text colour on top of a swatch (the colour's name, when a product photo is
    missing): Capsule's ink or white, whichever reads better. On a few middle greys and browns
    neither reaches 4.5:1, and pure black always does there."""
    best = max(("#1b1b1a", "#ffffff"), key=lambda ink: contrast(hex_, ink))
    return best if contrast(hex_, best) >= 4.5 else "#000000"
