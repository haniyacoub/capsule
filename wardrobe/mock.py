"""Invented demo catalogue, used until real data is collected (Phase 2).

NOTHING HERE IS A REAL PRODUCT. Names, prices and fabrics are made up to look
like what COS and Weekday typically sell on their German sites, so the app can
be tried end to end. Product links go to each store's home page. Only stores
with a partner programme are in it (programmes.py): there is no Zara.

The data is deterministic: the same slot always gets the same candidates, so
your locks survive a rebuild. Two things are broken on purpose so the image
fallback can be seen working:
  * every Weekday chino has no image at all
  * the Weekday "Ledersneaker" has an image URL that fails to load
"""
from __future__ import annotations

import random

from . import catalog, colours, composition
from .garments import GARMENTS

STORE_HOME = {
    "cos": "https://www.cos.com/de-de",
    "weekday": "https://www.weekday.com/de-de",
}

FIT_TEXT = {
    "regular": "Normale Passform.",
    "slim": "Schmale Passform.",
    "relaxed": "Lockere Passform.",
    "oversized": "Oversized-Passform – fällt groß aus.",
}

COLOUR_NAMES_DE = {
    "white": ["Weiß"], "ecru": ["Ecru", "Cremeweiß"], "light-grey": ["Hellgrau"],
    "grey": ["Grau", "Graumeliert"], "charcoal": ["Anthrazit", "Dunkelgrau"],
    "black": ["Schwarz"], "navy": ["Marineblau", "Dunkelblau"], "indigo": ["Indigoblau"],
    "blue": ["Blau"], "light-blue": ["Hellblau"], "stone": ["Stein", "Sand"],
    "beige": ["Beige"], "camel": ["Camel"], "brown": ["Braun"], "dark-brown": ["Dunkelbraun"],
    "olive": ["Khaki", "Olivgrün"], "green": ["Dunkelgrün"], "burgundy": ["Bordeaux"],
    "rust": ["Rostrot"], "red": ["Rot"], "mustard": ["Senfgelb"], "pink": ["Rosa"],
    "purple": ["Lila"],
}

# garment -> store -> [(name, price EUR, composition, fit)]
VARIANTS: dict[str, dict[str, list[tuple[str, float, str, str]]]] = {
    "tee": {
        "cos": [
            ("T-Shirt aus schwerem Baumwolljersey", 35, "100 organic_cotton", "regular"),
            ("Kastiges T-Shirt mit Rundhalsausschnitt", 29, "100 cotton", "relaxed"),
            ("Schmales T-Shirt aus Pima-Baumwolle", 39, "100 cotton", "slim"),
        ],
        "weekday": [
            ("Oversized T-Shirt Heavyweight", 22, "100 cotton", "oversized"),
            ("Standard T-Shirt aus Baumwolle", 12, "100 cotton", "regular"),
            ("Relaxed T-Shirt Midweight", 17, "100 organic_cotton", "relaxed"),
        ],
    },
    "longsleeve": {
        "cos": [
            ("Langarmshirt aus schwerem Jersey", 45, "100 organic_cotton", "regular"),
            ("Langarmshirt mit Waffelstruktur", 55, "100 cotton", "relaxed"),
        ],
        "weekday": [
            ("Oversized Langarmshirt Heavyweight", 27, "100 cotton", "oversized"),
            ("Schmales Langarmshirt aus Rippjersey", 20, "95 cotton, 5 elastane", "slim"),
        ],
    },
    "polo": {
        "cos": [
            ("Gestricktes Poloshirt aus Merinowolle", 89, "100 merino", "regular"),
            ("Poloshirt aus Baumwollpiqué", 55, "100 cotton", "regular"),
            ("Strickpolo aus Baumwolle und Seide", 79, "80 cotton, 20 silk", "relaxed"),
        ],
        "weekday": [
            ("Strickpolo Relaxed", 40, "100 cotton", "relaxed"),
            ("Piqué-Poloshirt Standard", 30, "100 cotton", "regular"),
            ("Strickpolo mit Reißverschluss", 45, "60 cotton, 40 polyamide", "oversized"),
        ],
    },
    "shirt": {
        "cos": [
            ("Hemd aus Baumwoll-Oxford", 79, "100 organic_cotton", "regular"),
            ("Lockeres Hemd aus Popeline", 69, "100 cotton", "relaxed"),
            ("Schmales Hemd aus Twill", 89, "100 cotton", "slim"),
        ],
        "weekday": [
            ("Oxford-Hemd Regular", 45, "100 cotton", "regular"),
            ("Oversized Hemd aus Popeline", 40, "100 cotton", "oversized"),
            ("Relaxed Hemd mit Stretch", 35, "65 polyester, 32 cotton, 3 elastane", "relaxed"),
        ],
    },
    "knit": {
        "cos": [
            ("Pullover aus Merinowolle", 89, "100 merino", "regular"),
            ("Pullover aus schwerer Wolle", 115, "100 wool", "relaxed"),
            ("Pullover aus Wolle und Kaschmir", 135, "90 wool, 10 cashmere", "regular"),
        ],
        "weekday": [
            ("Pullover aus Wollmix", 55, "50 wool, 30 polyamide, 20 acrylic", "relaxed"),
            ("Oversized Strickpullover", 45, "60 cotton, 40 polyester", "oversized"),
            ("Merino-Pullover Standard", 65, "100 merino", "regular"),
        ],
    },
    "cardigan": {
        "cos": [
            ("Cardigan aus Merinowolle", 115, "100 merino", "regular"),
            ("Cardigan aus Bouclé-Wolle", 135, "64 wool, 30 polyamide, 6 elastane", "relaxed"),
            ("Cardigan aus Baumwollstrick", 99, "100 cotton", "relaxed"),
        ],
        "weekday": [
            ("Cardigan aus Wollmix", 60, "40 wool, 35 polyester, 25 acrylic", "relaxed"),
            ("Oversized Cardigan", 55, "70 cotton, 30 polyamide", "oversized"),
        ],
    },
    "overshirt": {
        "cos": [
            ("Overshirt aus Wollmix", 135, "70 wool, 30 polyamide", "relaxed"),
            ("Overshirt aus Baumwolltwill", 99, "100 cotton", "regular"),
            ("Overshirt aus Wollflanell", 150, "100 wool", "relaxed"),
        ],
        "weekday": [
            ("Overshirt aus Twill Relaxed", 60, "100 cotton", "relaxed"),
            ("Workwear-Overshirt", 70, "100 cotton", "oversized"),
            ("Overshirt aus Wollmix", 80, "50 wool, 50 polyester", "relaxed"),
        ],
    },
    "blazer": {
        "cos": [
            ("Blazer aus Wolle – Regular Fit", 225, "100 wool", "regular"),
            ("Unkonstruierter Blazer aus Wollmix", 190, "54 wool, 44 polyester, 2 elastane", "relaxed"),
            ("Blazer aus Baumwolle und Leinen", 175, "60 cotton, 40 linen", "relaxed"),
        ],
        "weekday": [
            ("Oversized Blazer", 100, "64 polyester, 34 viscose, 2 elastane", "oversized"),
            ("Blazer aus Wollmix", 130, "50 wool, 50 polyester", "regular"),
        ],
    },
    "coat": {
        "cos": [
            ("Mantel aus Wollmix", 275, "80 wool, 20 polyamide", "regular"),
            ("Zweireihiger Mantel aus Wolle", 350, "100 wool", "relaxed"),
            ("Kurzer Mantel aus recycelter Wolle", 225, "67 wool, 28 polyamide, 5 other", "regular"),
        ],
        "weekday": [
            ("Oversized Mantel aus Wollmix", 180, "55 wool, 45 polyester", "oversized"),
            ("Car Coat", 150, "60 polyester, 40 wool", "regular"),
        ],
    },
    "jacket": {
        "cos": [
            ("Harrington-Jacke aus Baumwolltwill", 150, "100 cotton", "regular"),
            ("Leichte Jacke aus Nylon", 135, "100 polyamide", "relaxed"),
            ("Arbeitsjacke aus Canvas", 135, "100 organic_cotton", "relaxed"),
        ],
        "weekday": [
            ("Bomberjacke", 80, "100 polyamide", "oversized"),
            ("Workwear-Jacke aus Canvas", 90, "100 cotton", "relaxed"),
            ("Harrington-Jacke", 75, "65 polyester, 35 cotton", "regular"),
        ],
    },
    "trousers": {
        "cos": [
            ("Hose aus Wollflanell mit geradem Bein", 135, "100 wool", "regular"),
            ("Tapered Hose aus Wollmix", 115, "54 wool, 44 polyester, 2 elastane", "slim"),
            ("Weite Hose aus Wolle mit Bundfalten", 150, "98 wool, 2 elastane", "relaxed"),
        ],
        "weekday": [
            ("Anzughose Relaxed", 55, "64 polyester, 34 viscose, 2 elastane", "relaxed"),
            ("Weite Hose mit Bundfalten", 60, "70 polyester, 28 viscose, 2 elastane", "oversized"),
            ("Hose aus Wollmix", 80, "50 wool, 48 polyester, 2 elastane", "regular"),
        ],
    },
    "chinos": {
        "cos": [
            ("Chino aus Baumwolltwill mit geradem Bein", 89, "100 organic_cotton", "regular"),
            ("Tapered Chino mit Stretch", 79, "97 cotton, 3 elastane", "slim"),
            ("Weite Chino mit Bundfalten", 99, "100 cotton", "relaxed"),
        ],
        "weekday": [
            ("Chino Regular", 45, "100 cotton", "regular"),
            ("Lockere Chino aus Twill", 50, "100 cotton", "relaxed"),
            ("Workwear-Hose", 55, "65 polyester, 35 cotton", "relaxed"),
        ],
    },
    "jeans": {
        "cos": [
            ("Jeans mit geradem Bein", 99, "100 organic_cotton", "regular"),
            ("Tapered Jeans", 89, "99 cotton, 1 elastane", "slim"),
            ("Weite Jeans aus Selvedge-Denim", 135, "100 cotton", "relaxed"),
        ],
        "weekday": [
            ("Jeans Straight Regular", 60, "100 cotton", "regular"),
            ("Jeans Loose Baggy", 65, "100 organic_cotton", "oversized"),
            ("Jeans Slim Tapered", 50, "98 cotton, 2 elastane", "slim"),
        ],
    },
    "sneakers": {
        "cos": [
            ("Sneaker aus Leder", 150, "100 leather", "regular"),
            ("Minimalistische Ledersneaker", 175, "100 leather", "regular"),
            ("Sneaker aus Veloursleder", 160, "100 suede", "regular"),
        ],
        "weekday": [
            ("Sneaker Low", 70, "100 polyurethane", "regular"),
            ("Ledersneaker", 90, "100 leather", "regular"),
        ],
    },
    "shoes": {
        "cos": [
            ("Derby-Schuhe aus Leder", 190, "100 leather", "regular"),
            ("Loafer aus Leder", 175, "100 leather", "regular"),
            ("Derby-Schuhe aus Veloursleder", 190, "100 suede", "regular"),
        ],
        "weekday": [
            ("Loafer aus Leder", 100, "100 leather", "regular"),
            ("Derby-Schuhe", 90, "100 polyurethane", "regular"),
        ],
    },
    "boots": {
        "cos": [
            ("Chelsea-Boots aus Leder", 225, "100 leather", "regular"),
            ("Schnürstiefel aus Leder", 250, "100 leather", "regular"),
            ("Chelsea-Boots aus Veloursleder", 225, "100 suede", "regular"),
        ],
        "weekday": [
            ("Chelsea-Boots", 110, "100 leather", "regular"),
            ("Chunky Boots", 100, "100 polyurethane", "regular"),
        ],
    },
}

_ALPHA = ["XS", "S", "M", "L", "XL", "XXL"]
_EU_TAILORING = ["44", "46", "48", "50", "52", "54", "56"]
_WAIST_LENGTH = [f"{w}/{length}" for w in (28, 29, 30, 31, 32, 33, 34, 36, 38) for length in (30, 32, 34)]
_SHOES = ["39", "40", "41", "42", "43", "44", "45", "46", "47"]


def size_run(store: str, category: str) -> list[str]:
    """The labels a store would print for this garment (each store has its own system)."""
    group = GARMENTS[category].size_group
    if group == "shoes":
        return _SHOES
    if group == "tops":
        return _EU_TAILORING if store == "cos" and category in ("coat", "blazer") else _ALPHA
    return _WAIST_LENGTH if category == "jeans" else _EU_TAILORING


def _parse_comp(text: str) -> list[tuple[str, float]]:
    out = []
    for part in text.split(","):
        pct, fibre = part.split()
        out.append((fibre, float(pct)))
    return out


def candidates_for(slot: dict, stamp: str) -> list[dict]:
    category, colour_key = slot["category"], slot["colour"]
    base = colours.get(colour_key)
    out = []
    for store, variants in VARIANTS.get(category, {}).items():
        for i, (name, price, comp, fit) in enumerate(variants):
            rng = random.Random(f"{slot['id']}|{category}|{colour_key}|{store}|{i}")
            names = COLOUR_NAMES_DE.get(colour_key, [base.label])
            hex_ = colours.shade(base.hex, rng.uniform(-0.07, 0.07))
            run = size_run(store, category)
            in_stock = [s for s in run if rng.random() < 0.8]

            image = f"/mock/img/{category}.svg?c={hex_.lstrip('#')}"
            if store == "weekday" and category == "chinos":
                image = ""                               # demo: no image at all
            elif store == "weekday" and name == "Ledersneaker":
                image = "/mock/img/does-not-exist.jpg"   # demo: image fails to load

            out.append({
                "id": f"mock-{store}-{slot['id']}-{category}-{colour_key}-{i}",
                "slot_id": slot["id"],
                "store": store,
                "name": name,
                "price": float(price),
                "currency": "EUR",
                "colour": names[i % len(names)],
                "colour_hex": hex_,
                "composition_text": composition.to_german(_parse_comp(comp)),
                "fit": fit,
                "description": FIT_TEXT[fit],
                "sizes_all": run,
                "sizes_in_stock": in_stock,
                "url": STORE_HOME[store],
                "image_url": image,
                "collected_at": stamp,
            })
    return out


def build(slots: list[dict]) -> dict:
    stamp = catalog.now_iso()
    candidates: list[dict] = []
    for slot in slots:
        candidates.extend(candidates_for(slot, stamp))
    return {
        "source": "mock",
        "collected_at": stamp,
        "note": "Invented demo data — not real products, prices or stock.",
        "candidates": candidates,
    }
