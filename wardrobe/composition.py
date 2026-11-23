"""Turns a store's composition text into fibres.

    parse("80 % Wolle, 20 % Polyamid")  ->  [("wool", 80.0), ("polyamide", 20.0)]

Handles German and English names, either order ("Baumwolle 100%"), and
multi-part labels — only the main fabric counts, not lining or soles. The
shares never add up to more than 100.
"""
from __future__ import annotations

import math
import re

# name fragment -> canonical fibre key (the keys used in config/scoring.toml)
_ALIASES = {
    "bio-baumwolle": "organic_cotton", "bio baumwolle": "organic_cotton",
    "biobaumwolle": "organic_cotton", "organic cotton": "organic_cotton",
    "baumwolle": "cotton", "cotton": "cotton",
    "merinowolle": "merino", "merino": "merino",
    "kaschmir": "cashmere", "cashmere": "cashmere",
    "alpaka": "alpaca", "alpaca": "alpaca",
    "mohair": "mohair",
    "schurwolle": "wool", "lammwolle": "wool", "lambswool": "wool", "wolle": "wool", "wool": "wool",
    "leinen": "linen", "linen": "linen", "flachs": "linen",
    "seide": "silk", "silk": "silk",
    "hanf": "hemp", "hemp": "hemp",
    "polyester": "polyester",
    "polyamid": "polyamide", "nylon": "polyamide",
    "elasthan": "elastane", "elastan": "elastane", "spandex": "elastane", "lycra": "elastane",
    "polyacryl": "acrylic", "acryl": "acrylic", "acrylic": "acrylic",
    "viskose": "viscose", "viscose": "viscose", "rayon": "viscose",
    "acetat": "viscose", "acetate": "viscose",      # the same family of regenerated fibres
    "lyocell": "lyocell", "tencel": "lyocell",
    "modal": "modal", "cupro": "cupro",
    "polyurethan": "polyurethane",
    "veloursleder": "suede", "wildleder": "suede", "suede": "suede",
    "leder": "leather", "leather": "leather",
    "gummi": "rubber", "kautschuk": "rubber", "rubber": "rubber",
}
_ALIAS_ORDER = sorted(_ALIASES, key=len, reverse=True)  # longest first

_GERMAN = {
    "organic_cotton": "Bio-Baumwolle", "cotton": "Baumwolle", "merino": "Merinowolle",
    "cashmere": "Kaschmir", "alpaca": "Alpaka", "mohair": "Mohair", "wool": "Wolle",
    "linen": "Leinen", "silk": "Seide", "hemp": "Hanf", "polyester": "Polyester",
    "polyamide": "Polyamid", "elastane": "Elasthan", "acrylic": "Polyacryl",
    "viscose": "Viskose", "lyocell": "Lyocell", "modal": "Modal", "cupro": "Cupro",
    "polyurethane": "Polyurethan", "suede": "Veloursleder", "leather": "Leder",
    "rubber": "Gummi", "other": "Sonstige Fasern",
}

# Sections of a label that are not the main fabric. A shoe's label starts with its upper
# ("Schnitt: 100% Kuhleder") and lists the tongue ("Zunge", "Lasche") after it with a 100% of its
# own, so the tongue ends the main fabric just as the lining does.
_SECONDARY = re.compile(
    r"\b(innenfutter|futter|lining|sohle|laufsohle|innensohle|sole|füllung|filling|"
    r"wattierung|padding|besatz|trim|rippe|rib|bündchen|taschenfutter|zunge|lasche|tongue)\b",
    re.IGNORECASE,
)
_PCT = re.compile(r"(\d+(?:[.,]\d+)?)\s*%")


# A fibre's name made into a word saying what was done to the cloth ("gummierte": rubberised, "gewachst" is no fibre
# either): not the fibre itself. "100% gummierte" cut from a sentence names no fibre.
_TREATED = re.compile(r"i?ert")


def _fibre_key(name: str) -> str:
    n = name.lower()
    for alias in _ALIAS_ORDER:
        at = n.find(alias)
        while at != -1:
            if not _TREATED.match(n, at + len(alias)):
                return _ALIASES[alias]
            at = n.find(alias, at + 1)
    return "other"


def _main(text: str) -> str:
    """The main fabric's part of a label: what comes before "Futter: …" (the lining) and the like."""
    m = _SECONDARY.search(text)
    if m and _PCT.search(text[: m.start()]):
        return text[: m.start()]  # keep only what comes before "Futter: …"
    return text


def _totals(main: str) -> list[tuple[str, float]]:
    """The fibres of `main` as the label gives them, (key, percent), largest share first, never scaled."""
    totals: dict[str, float] = {}
    for token in re.split(r"[,;·•|\n]|\band\b|\bund\b", main):
        m = _PCT.search(token)
        if not m:
            continue
        pct = float(m.group(1).replace(",", "."))
        name = (token[: m.start()] + " " + token[m.end():]).strip(" :-–")
        if ":" in name:  # "Obermaterial: Wolle" -> "Wolle"
            name = name.split(":")[-1]
        key = _fibre_key(name)
        totals[key] = totals.get(key, 0.0) + pct
    return sorted(totals.items(), key=lambda kv: -kv[1])


_PAIRED = re.compile(r"(\d{1,3})\s*/\s*(\d{1,3})\s*%\s*([A-Za-zÄÖÜäöüß]+)\s*/\s*([A-Za-zÄÖÜäöüß]+)")
_SHARE_FIRST = re.compile(r"(?:[^\W\d_]+\s*:\s*)?\d{1,3}(?:[.,]\d+)?\s*%")         # "89% …", "Obermaterial: 70% …"
_NEXT_SHARE = re.compile(r"(?<=[^\W\d_])(?<!\bund)(?<!\band)\s+(?=\d{1,3}(?:[.,]\d+)?\s*%)")   # "… Baumwolle| 9% …"


def stated(text: str | None) -> str:
    """A store's words about a product's fibres as a label states them, or "" when they are not that: the fibres
    known here must add up to at least 90% ("100% aus" or "30% Polyamid, 10% Kaschmir" are pieces of a sentence,
    not a label). "80/20% Lambswool/Nylon" is read as "80% Lambswool, 20% Nylon", "54% Leinen/ 44% Baumwolle" as
    "54% Leinen, 44% Baumwolle", and a label that gives each share before its fibre without commas ("89% Baumwolle
    9% Viskose 2% Elastan") as "89% Baumwolle, 9% Viskose, 2% Elastan"."""
    words = " ".join(str(text or "").split())[:300]
    words = _PAIRED.sub(lambda m: f"{m[1]}% {m[3]}, {m[2]}% {m[4]}", words)
    words = re.sub(r"\s*/\s*(?=\d)", ", ", words)          # "54% Leinen/ 44% Baumwolle/ 2% Elasthan"
    if _SHARE_FIRST.match(words):          # (never "Baumwolle 98% Elasthan 2%", whose shares follow their fibres)
        words = _NEXT_SHARE.sub(", ", words)
    known = sum(share for fibre, share in parse(words) if fibre != "other")
    return words if known >= 90 else ""


def parse(text: str | None) -> list[tuple[str, float]]:
    """Main-fabric fibres as (key, percent), largest share first. [] if unknown."""
    if not text:
        return []
    comp = _totals(_main(text))
    if math.fsum(pct for _, pct in comp) > 100:
        comp = _scaled_to_100(comp)
    return comp


# Parts of a garment a label can give a fabric each ("Vorderteil: 100 % Baumwolle; Rückenteil: 100 % Polyester"),
# in the words the fabric line says them.
_PARTS = {"vorderteil": "front", "rückenteil": "back", "front": "front", "back": "back", "ärmel": "sleeves",
          "sleeves": "sleeves", "körper": "body", "body": "body", "außen": "body", "aussen": "body",
          "oben": "top", "unten": "bottom", "oberteil": "top", "unterteil": "bottom", "kragen": "collar",
          "collar": "collar", "einsatz": "panels", "einsätze": "panels"}
_PART = re.compile(r"\b(" + "|".join(sorted(_PARTS, key=len, reverse=True)) + r")\b\s*:", re.IGNORECASE)


def _fibres_said(comp: list[tuple[str, float]]) -> str:
    return ", ".join(f"{pct:g}% {'other fibres' if key == 'other' else label(key)}" for key, pct in comp)


def as_labelled(text: str | None) -> str:
    """The fabric line for a label whose shares add up to more than 100, which parse() scales back for the score:
    said as the label gives it, never as the scaled shares (a 50/50 the store never wrote). "" for any other label.

    "Vorderteil: 100 % Baumwolle; Rückenteil: 100 % Polyester"  ->  "front 100% cotton, back 100% polyester"
    "Außen: 70 % Wolle, 30 % Polyamid; Ärmel: 100 % Wolle"      ->  "body 70% wool, 30% polyamide; sleeves 100% wool"
    "51 % Baumwolle, 50 % Polyester" (a store's own rounding)    ->  "51% cotton, 50% polyester"
    "100 % Baumwolle; 100 % Polyester" (parts it does not name)  ->  "mixed (see the label)"
    """
    if not text:
        return ""
    main = _main(text)
    comp = _totals(main)
    total = math.fsum(pct for _, pct in comp)
    if total <= 100:
        return ""
    pieces = _PART.split(main)                  # [before the first part, part, its fibres, part, its fibres, …]
    parts = [(_PARTS[pieces[i].lower()], _totals(pieces[i + 1])) for i in range(1, len(pieces) - 1, 2)]
    if (len(parts) >= 2 and not _totals(pieces[0]) and all(fibres for _, fibres in parts)
            and all(math.fsum(pct for _, pct in fibres) <= 100 for _, fibres in parts)):
        between = ", " if all(len(fibres) == 1 for _, fibres in parts) else "; "
        return between.join(f"{part} {_fibres_said(fibres)}" for part, fibres in parts)
    if total <= 102:                             # a store's own rounding: its figures, as it wrote them
        return _fibres_said(comp)
    return "mixed (see the label)"


def _scaled_to_100(comp: list[tuple[str, float]]) -> list[tuple[str, float]]:
    """Shares that add up to more than 100, scaled back to exactly 100 in whole percents.

    It happens when a label names two parts of a garment in a way this parser does not
    recognise (each with its own 100%), or when a store rounds its figures up. Each share is
    rounded down, and the percents still missing go to the shares that lost most in the
    rounding, so together they make exactly 100: "51 % Baumwolle, 50 % Polyester" becomes
    50 + 50, and "Vorderteil: 100 % Baumwolle; Rückenteil: 100 % Polyester" becomes 50 + 50.
    """
    total = math.fsum(pct for _, pct in comp)
    exact = [pct * 100 / total for _, pct in comp]
    whole = [math.floor(share) for share in exact]
    lost_most = sorted(range(len(comp)), key=lambda i: whole[i] - exact[i])
    for i in lost_most[: 100 - sum(whole)]:
        whole[i] += 1
    return sorted(((key, float(share)) for (key, _), share in zip(comp, whole)), key=lambda kv: -kv[1])


def label(key: str) -> str:
    return key.replace("_", " ")


def describe(comp: list[tuple[str, float]]) -> str:
    """'80% wool · 20% polyamide' — the short form shown in lists."""
    if not comp:
        return "composition not listed"
    return " · ".join(f"{pct:g}% {label(key)}" for key, pct in comp)


def in_words(comp: list[tuple[str, float]], source: str, how: str = "", typical_for: str = "") -> str:
    """The fabric in plain words, saying no more than its source does (the words after "Fabric: " on every page).

    source "listed", the label:       "80% wool, 20% polyamide", or "50% wool (the rest not stated)"
    source "name", the product's name (`how`, a key of GUESSED): "pure cashmere", "wool blend (the mix is not
                                      stated)", "some wool (how much is not stated)", "cotton (how much is not stated)"
    source "assumed", the garment's type (`typical_for`, its plural): "not stated (jeans are usually 99% cotton,
                                      1% elastane)"
    nothing at all:                   "not stated"
    A name's shares are the score's assumption, not the store's: they are never shown as figures.
    """
    if not comp:
        return "not stated"
    if source == "listed":
        said = ", ".join(f"{pct:g}% {'other fibres' if key == 'other' else label(key)}" for key, pct in comp)
        return said if math.fsum(pct for _, pct in comp) >= 99.5 else f"{said} (the rest not stated)"
    if source == "assumed":
        usual = ", ".join(f"{pct:g}% {label(key)}" for key, pct in comp)
        return f"not stated ({typical_for} are usually {usual})" if typical_for else "not stated"
    # "Lederoptik", "Kunstleder": the name says faux leather, which the score counts as polyurethane.
    named = ["faux leather" if key == "polyurethane" else label(key) for key, _ in comp if key != "other"]
    fibres = " and ".join([", ".join(named[:-1]), named[-1]] if len(named) > 1 else named)
    if how == "pure":
        return f"pure {fibres}" if len(named) == 1 else fibres
    if how == "blend":
        return f"{fibres} blend (the mix is not stated)"
    if how == "trace":
        return f"some {fibres} (how much is not stated)"
    return f"{fibres} (how much is not stated)"


def to_german(comp: list[tuple[str, float]]) -> str:
    """The way a German store page would print it (used by the demo data)."""
    return ", ".join(f"{pct:g} % {_GERMAN.get(key, key)}" for key, pct in comp)


# ── Estimating from the product name ─────────────────────────────────────────
# Some stores won't show their product pages to an automated browser, so the
# exact composition can't be collected there. The name usually says what the
# garment is mostly made of ("Pullover aus Merinowolle", "Wollmix"), which is
# enough for a rough score until the real composition is typed in.

# Fibre words as they appear inside names, most specific first. Each match is
# removed from the text before the next pattern runs, so "Baumwolle" is not
# also counted as "Wolle" and "Merinowolle" not as merino + wool.
_NAME_FIBRES = [
    (r"kunstleder|lederoptik|lederimitat|faux[\s-]leather", "polyurethane"),
    (r"veloursleder|wildleder|suede", "suede"),
    (r"leder|leather", "leather"),
    (r"kaschmir|cashmere", "cashmere"),
    (r"merino(?:[\s-]*woll\w*|[\s-]*wool)?", "merino"),
    (r"alpaka|alpaca", "alpaca"),
    (r"mohair", "mohair"),
    (r"bio[\s-]?baumwoll\w*|organic[\s-]cotton", "organic_cotton"),
    (r"baumwoll\w*|cotton|denim", "cotton"),
    (r"\w*woll\w*|\w*wool\w*", "wool"),
    (r"leinen|linen", "linen"),
    (r"seide|silk", "silk"),
    (r"lyocell|tencel", "lyocell"),
    (r"viskose|viscose", "viscose"),
    (r"polyester", "polyester"),
    (r"nylon|polyamid\w*", "polyamide"),
]
_SAYS_PURE = re.compile(r"100\s*%|\brein(?:e[mnrs]?)?\b|\bpure\b")
_SAYS_TRACE = re.compile(r"anteil|\b(?:mit|und)\s+(?:wolle|kaschmir|seide|leinen|alpaka|mohair)\b")
_SAYS_BLEND = re.compile(r"mix|misch|blend")


# How a name speaks of its fibres (what guess() returns as its second value), in the words "How it's rated" uses.
GUESSED = {"pure": "the name says it is pure", "trace": "the name says it contains some",
           "blend": "the name says it is a blend", "plain": "the name mentions it"}


def guess(name: str | None, shares: dict | None = None) -> tuple[list[tuple[str, float]], str]:
    """A rough composition read off a product name: (fibres, how the name speaks of them: a key of GUESSED).

    `shares` are the percentages to assume, from [fabric.name_guess] in
    config/scoring.toml. Returns ([], "") when the name mentions no fibre.
    """
    shares = shares or {}
    original = (name or "").lower().replace("-", " ")
    text = original
    found: list[str] = []
    for pattern, fibre in _NAME_FIBRES:
        if re.search(pattern, text):
            text = re.sub(pattern, " ", text)
            if fibre not in found:
                found.append(fibre)
    if not found:
        return [], ""
    if "suede" in found and "leather" in found:   # suede is leather: "Veloursleder", with "leather" in the slug
        found.remove("leather")

    if _SAYS_PURE.search(original):
        named, how = float(shares.get("pure_share", 100)), "pure"
    elif _SAYS_TRACE.search(original):
        named, how = float(shares.get("trace_share", 25)), "trace"
    elif _SAYS_BLEND.search(original):
        named = 90.0 if len(found) > 1 else float(shares.get("blend_share", 50))
        how = "blend"
    else:
        named, how = float(shares.get("plain_share", 85)), "plain"

    comp = [(fibre, round(named / len(found), 1)) for fibre in found]
    if named < 100:
        comp.append(("other", round(100 - named, 1)))
    return comp, how
