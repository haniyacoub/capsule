"""Invented demo catalogue, used until real data is collected (Phase 2).

NOTHING HERE IS A REAL PRODUCT. Names, prices and fabrics are made up to look
like what COS, Weekday and Zara typically sell on their German sites, so the
app can be tried end to end. Product links go to each store's home page.

The data is deterministic: the same slot always gets the same candidates, so
your locks survive a rebuild. Two things are broken on purpose so the image
fallback can be seen working:
  * every Zara chino has no image at all
  * the Zara "Ledersneaker" has an image URL that fails to load
"""
from __future__ import annotations

import random

from . import catalog, colours, composition
from .garments import GARMENTS

STORE_HOME = {
    "cos": "https://www.cos.com/de-de",
    "weekday": "https://www.weekday.com/de-de",
    "zara": "https://www.zara.com/de/",
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
        "zara": [
            ("Basic-T-Shirt Heavy Weight", 17.95, "100 cotton", "relaxed"),
            ("Basic-T-Shirt Slim Fit", 9.95, "92 cotton, 8 elastane", "slim"),
            ("T-Shirt aus Mischgewebe", 7.95, "55 polyester, 45 cotton", "regular"),
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
        "zara": [
            ("Langarmshirt Heavy Weight", 19.95, "100 cotton", "relaxed"),
            ("Basic-Langarmshirt", 12.95, "60 polyester, 40 cotton", "regular"),
            ("Langarmshirt aus Strukturstoff", 22.95, "70 cotton, 30 polyester", "regular"),
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
        "zara": [
            ("Poloshirt aus Strick", 29.95, "58 viscose, 42 polyamide", "slim"),
            ("Piqué-Poloshirt", 22.95, "100 cotton", "regular"),
            ("Strickpolo aus Baumwolle", 35.95, "100 cotton", "relaxed"),
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
        "zara": [
            ("Oxford-Hemd", 29.95, "100 cotton", "regular"),
            ("Bügelleichtes Hemd Slim Fit", 25.95, "65 polyester, 35 cotton", "slim"),
            ("Hemd aus Strukturgewebe", 35.95, "78 cotton, 22 linen", "relaxed"),
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
        "zara": [
            ("Pullover aus 100 % Merinowolle", 49.95, "100 merino", "regular"),
            ("Basic-Strickpullover", 25.95, "50 viscose, 28 polyester, 22 polyamide", "slim"),
            ("Pullover mit Wollanteil", 35.95, "45 acrylic, 30 polyester, 25 wool", "regular"),
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
        "zara": [
            ("Strickjacke mit Knöpfen", 35.95, "50 acrylic, 30 polyester, 20 wool", "regular"),
            ("Cardigan aus Baumwolle", 39.95, "100 cotton", "regular"),
            ("Cardigan aus Wollmischung", 49.95, "55 wool, 45 polyamide", "relaxed"),
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
        "zara": [
            ("Overshirt aus Strukturstoff", 39.95, "68 polyester, 30 viscose, 2 elastane", "regular"),
            ("Overshirt aus Baumwolle", 45.95, "100 cotton", "relaxed"),
            ("Overshirt mit Wollanteil", 59.95, "60 polyester, 40 wool", "relaxed"),
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
        "zara": [
            ("Blazer aus Strukturgewebe", 79.95, "72 polyester, 26 viscose, 2 elastane", "slim"),
            ("Blazer mit Wollanteil", 99.95, "64 polyester, 36 wool", "regular"),
            ("Blazer aus 100 % Wolle", 149.0, "100 wool", "regular"),
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
        "zara": [
            ("Mantel mit Wollanteil", 129.0, "62 polyester, 38 wool", "regular"),
            ("Mantel aus Wollmischung", 169.0, "70 wool, 30 polyamide", "relaxed"),
            ("Mantel in Wolloptik", 89.95, "88 polyester, 10 viscose, 2 elastane", "regular"),
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
        "zara": [
            ("Bomberjacke", 49.95, "100 polyester", "regular"),
            ("Jacke aus Baumwolle", 69.95, "100 cotton", "regular"),
            ("Jacke aus technischem Gewebe", 59.95, "88 polyamide, 12 elastane", "slim"),
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
        "zara": [
            ("Hose aus Strukturgewebe Slim Fit", 35.95, "74 polyester, 24 viscose, 2 elastane", "slim"),
            ("Hose mit Wollanteil", 59.95, "56 polyester, 42 wool, 2 elastane", "regular"),
            ("Hose aus 100 % Wolle", 79.95, "100 wool", "regular"),
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
        "zara": [
            ("Chinohose Slim Fit", 29.95, "97 cotton, 3 elastane", "slim"),
            ("Chinohose Relaxed Fit", 35.95, "100 cotton", "relaxed"),
            ("Chino aus Mischgewebe", 25.95, "63 polyester, 34 viscose, 3 elastane", "regular"),
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
        "zara": [
            ("Jeans Straight Fit", 35.95, "100 cotton", "regular"),
            ("Jeans Slim Fit", 29.95, "92 cotton, 6 polyester, 2 elastane", "slim"),
            ("Jeans Baggy Fit", 39.95, "80 cotton, 20 lyocell", "oversized"),
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
        "zara": [
            ("Sneaker", 39.95, "100 polyurethane", "regular"),
            ("Ledersneaker", 69.95, "100 leather", "regular"),
            ("Retro-Sneaker", 49.95, "60 polyester, 40 polyurethane", "regular"),
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
        "zara": [
            ("Derby-Schuhe", 59.95, "100 polyurethane", "regular"),
            ("Derby-Schuhe aus Leder", 89.95, "100 leather", "regular"),
            ("Loafer aus Leder", 79.95, "100 leather", "regular"),
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
        "zara": [
            ("Chelsea-Boots", 69.95, "100 polyurethane", "regular"),
            ("Chelsea-Boots aus Leder", 99.95, "100 leather", "regular"),
            ("Schnürstiefel aus Leder", 119.0, "100 leather", "regular"),
        ],
    },
}

_ALPHA = ["XS", "S", "M", "L", "XL", "XXL"]
_EU_TAILORING = ["44", "46", "48", "50", "52", "54", "56"]
_ZARA_BOTTOMS = ["36", "38", "40", "42", "44", "46", "48", "50"]
_WAIST_LENGTH = [f"{w}/{length}" for w in (28, 29, 30, 31, 32, 33, 34, 36, 38) for length in (30, 32, 34)]
_SHOES = ["39", "40", "41", "42", "43", "44", "45", "46", "47"]


def size_run(store: str, category: str) -> list[str]:
    """The labels a store would print for this garment (each store has its own system)."""
    group = GARMENTS[category].size_group
    if group == "shoes":
        return _SHOES
    if group == "tops":
        return _EU_TAILORING if store == "cos" and category in ("coat", "blazer") else _ALPHA
    if store == "zara":
        return _ZARA_BOTTOMS
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
            if store == "zara" and category == "chinos":
                image = ""                               # demo: no image at all
            elif store == "zara" and name == "Ledersneaker":
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
