"""Proposes the capsule: about 15-20 slots in one coherent palette.

The idea behind the palette:
  * one dark anchor, one mid neutral, one light — most pieces come from these
  * one accent colour, used once or twice on top layers
  * trousers and shoes stay neutral, so nearly every top works with every bottom

The proposal is only a starting point: every slot can be edited, removed or
added on the Slots page.
"""
from __future__ import annotations

import re

from .colours import COLOURS, Colour, find as find_colour, get as get_colour

# Colour roles and, for each, the candidates in order of preference. A colour
# you like is taken first; a colour you refuse is never taken.
ROLE_OPTIONS = {
    "anchor": ["navy", "charcoal", "black", "dark-brown"],
    "mid": ["grey", "light-grey", "stone", "beige", "charcoal"],
    "light": ["white", "ecru", "light-grey"],
    "light2": ["ecru", "white", "light-grey", "stone"],
    "dark2": ["charcoal", "navy", "black", "dark-brown"],
    "earth": ["stone", "beige", "camel", "light-grey"],
    "accent": ["olive", "burgundy", "green", "rust", "camel"],
    "shirt_blue": ["light-blue", "ecru", "light-grey", "white"],
    "denim": ["indigo", "black", "ecru", "grey"],
    "denim2": ["black", "ecru", "grey", "indigo"],
    "shoe_dark": ["dark-brown", "black", "brown"],
}
# For these roles the classic choice wins even if you like a later option more:
# liking grey should not turn the jeans grey.
_CLASSIC_FIRST = {"shirt_blue", "denim", "denim2", "shoe_dark"}

ROLE_LABELS = {
    "anchor": "Anchor", "mid": "Mid neutral", "light": "Light", "accent": "Accent",
    "dark2": "Second dark", "earth": "Earth tone", "light2": "Soft light",
    "shirt_blue": "Shirt colour", "denim": "Denim", "shoe_dark": "Dark shoes",
}

# (garment, colour role, name, keywords, quantity, when)
#   when: "e" everyday + both · "o" office + both · "eo" always
#         "E" everyday only   · "O" office only
TEMPLATE = [
    ("coat", "dark2", "{c} wool coat", "wool", 1, "eo"),
    ("jacket", "anchor", "{c} light jacket", "lightweight", 1, "e"),
    ("blazer", "anchor", "{c} wool blazer", "wool", 1, "o"),
    ("overshirt", "accent", "{c} overshirt", "", 1, "e"),
    ("knit", "mid", "{c} merino jumper", "merino crew-neck", 1, "eo"),
    ("knit", "accent2", "{c} merino jumper", "merino crew-neck", 1, "eo"),
    ("cardigan", "light2", "{c} cardigan", "wool", 1, "o"),
    ("polo", "anchor", "{c} knitted polo", "knitted", 1, "O"),
    ("shirt", "light", "{c} oxford shirt", "oxford", 1, "eo"),
    ("shirt", "shirt_blue", "{c} oxford shirt", "oxford", 1, "eo"),
    ("tee", "light", "{c} tee", "heavyweight", 2, "eo"),
    ("tee", "anchor", "{c} tee", "heavyweight", 1, "e"),
    ("tee", "mid", "{c} tee", "heavyweight", 1, "e"),
    ("longsleeve", "light", "{c} long-sleeve tee", "", 1, "E"),
    ("trousers", "mid", "{c} wool trousers", "wool", 1, "eo"),
    ("trousers", "dark2", "{c} tailored trousers", "tailored", 1, "o"),
    ("trousers", "anchor", "{c} tailored trousers", "tailored", 1, "O"),
    ("chinos", "earth", "{c} chinos", "", 1, "eo"),
    ("jeans", "denim", "{c} jeans", "straight", 1, "e"),
    ("jeans", "denim2", "{c} jeans", "straight", 1, "E"),
    ("sneakers", "light", "{c} leather sneakers", "leather", 1, "eo"),
    ("shoes", "shoe_dark", "{c} derby shoes", "leather derby", 1, "o"),
    ("boots", "shoe_dark", "{c} chelsea boots", "leather chelsea", 1, "E"),
]

# Added, in this order, when switching off shoes/outerwear leaves fewer than 15 slots.
EXTRAS = [
    ("polo", "anchor", "{c} knitted polo", "knitted", 1),
    ("longsleeve", "light", "{c} long-sleeve tee", "", 1),
    ("chinos", "anchor", "{c} chinos", "", 1),
    ("knit", "light2", "{c} cotton jumper", "cotton", 1),
    ("shirt", "earth", "{c} casual shirt", "", 1),
]
MIN_SLOTS = 15

# Refusing one of these refuses the whole family ("green" also rules out olive).
_FAMILY_HEADS = {"grey", "blue", "green", "brown", "red", "beige"}

# Words that identify a garment in "things I already own" (first match wins).
_GARMENT_WORDS = [
    ("sneakers", ["sneaker", "trainer", "turnschuh"]),
    ("boots", ["boot", "stiefel"]),
    ("shoes", ["derby", "derbies", "loafer", "brogue", "oxford shoe", "shoe", "schuh"]),
    ("blazer", ["blazer", "sakko", "sport coat", "suit jacket"]),
    ("coat", ["coat", "overcoat", "trench", "parka", "mantel"]),
    ("overshirt", ["overshirt", "shacket", "hemdjacke"]),
    ("jacket", ["jacket", "bomber", "harrington", "jacke"]),
    ("cardigan", ["cardigan", "strickjacke"]),
    ("polo", ["polo"]),
    ("knit", ["jumper", "sweater", "pullover", "knit", "crew neck", "crewneck"]),
    ("longsleeve", ["long sleeve", "longsleeve", "langarm"]),
    ("tee", ["t shirt", "tshirt", "tee"]),
    ("shirt", ["shirt", "hemd"]),
    ("jeans", ["jeans", "denim"]),
    ("chinos", ["chino"]),
    ("trousers", ["trousers", "pants", "slacks", "hose"]),
]


def banned(refused: list[str]) -> set[str]:
    out = set(refused)
    for key in refused:
        if key in _FAMILY_HEADS:
            out |= {c.key for c in COLOURS.values() if c.family == COLOURS[key].family}
    return out


def _pick(options: list[str], liked: list[str], ban: set[str], taken: set[str]) -> str:
    for key in options:  # liked and not already used
        if key in liked and key not in ban and key not in taken:
            return key
    for key in options:  # acceptable and not already used
        if key not in ban and key not in taken:
            return key
    for key in options:  # acceptable, even if it repeats
        if key not in ban:
            return key
    for c in COLOURS.values():  # every option refused: any neutral that isn't
        if c.neutral and c.key not in ban:
            return c.key
    return "grey"


def build_palette(liked: list[str], refused: list[str]) -> dict[str, str]:
    """Colour role -> colour key."""
    ban = banned(refused)
    liked = [k for k in liked if k in COLOURS and k not in ban]

    def pick(role: str, *taken: str) -> str:
        preferred = [] if role in _CLASSIC_FIRST else liked
        return _pick(ROLE_OPTIONS[role], preferred, ban, set(taken))

    p: dict[str, str] = {}
    p["anchor"] = pick("anchor")
    p["mid"] = pick("mid", p["anchor"])
    p["light"] = pick("light")
    p["light2"] = pick("light2", p["light"])
    p["dark2"] = pick("dark2", p["anchor"])
    p["earth"] = pick("earth", p["mid"], p["light2"])

    accents = [k for k in liked if not COLOURS[k].neutral]
    if accents:
        p["accent"] = accents[0]
    elif liked:
        # Only neutrals liked: keep the capsule neutral rather than invent an accent.
        spare = [k for k in liked if k not in (p["anchor"], p["mid"], p["light"])]
        p["accent"] = spare[0] if spare else p["dark2"]
    else:
        p["accent"] = pick("accent")
    p["accent2"] = accents[1] if len(accents) > 1 else p["anchor"]

    p["shirt_blue"] = pick("shirt_blue", p["light"])
    # A black-anchored wardrobe gets black jeans and black shoes; otherwise the classics.
    black = p["anchor"] == "black"
    p["denim"] = "black" if black else pick("denim")
    p["denim2"] = pick("denim2", p["denim"])
    p["shoe_dark"] = "black" if black else pick("shoe_dark")
    return p


def palette_summary(profile: dict) -> list[tuple[str, Colour]]:
    """[(role label, Colour)] for display, most important first, no repeats."""
    palette = build_palette(profile.get("liked", []), profile.get("refused", []))
    seen: set[str] = set()
    out: list[tuple[str, Colour]] = []
    for role, label in ROLE_LABELS.items():
        key = palette[role]
        if key not in seen:
            seen.add(key)
            out.append((label, get_colour(key)))
    return out


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "slot"


def unique_id(base: str, taken: set[str]) -> str:
    slot_id, n = base, 2
    while slot_id in taken:
        slot_id, n = f"{base}-{n}", n + 1
    return slot_id


def new_slot(category: str, colour: str, name: str, keywords: str, qty: int, taken: set[str]) -> dict:
    """A slot dict with a fresh id that isn't in `taken` (which is updated)."""
    slot_id = unique_id(slugify(name), taken)
    taken.add(slot_id)
    return {"id": slot_id, "name": name, "category": category, "colour": colour,
            "keywords": keywords, "qty": qty, "owned": False}


def propose(profile: dict) -> tuple[list[dict], list[str]]:
    """The proposed slot list, plus any 'already own' lines that couldn't be placed."""
    palette = build_palette(profile.get("liked", []), profile.get("refused", []))
    use = profile.get("use", "both")
    wanted = {"everyday": "eE", "office": "oO", "both": "eo"}.get(use, "eo")

    slots: list[dict] = []
    taken: set[str] = set()
    seen: set[tuple[str, str]] = set()

    def add(category: str, role: str, name: str, keywords: str, qty: int) -> None:
        colour = palette[role]
        if (category, colour) in seen:
            return  # two roles resolved to the same colour: don't propose a duplicate
        seen.add((category, colour))
        label = name.format(c=get_colour(colour).label)
        slots.append(new_slot(category, colour, label, keywords, qty, taken))

    for category, role, name, keywords, qty, when in TEMPLATE:
        if not set(when) & set(wanted):
            continue
        if category in ("coat", "jacket") and not profile.get("outerwear", True):
            continue
        if category in ("sneakers", "shoes", "boots") and not profile.get("shoes", True):
            continue
        add(category, role, name, keywords, qty)

    for category, role, name, keywords, qty in EXTRAS:
        if len(slots) >= MIN_SLOTS:
            break
        add(category, role, name, keywords, qty)

    unmatched = apply_owned(slots, profile.get("owned", ""), taken)
    return slots, unmatched


def detect_garment(text: str) -> str | None:
    t = re.sub(r"[-_]", " ", text.lower())
    for category, words in _GARMENT_WORDS:
        if any(re.search(rf"(?<![a-zäöüß]){re.escape(w)}", t) for w in words):
            return category
    return None


def apply_owned(slots: list[dict], owned_text: str, taken: set[str]) -> list[str]:
    """Build around what you already own.

    Each line ("white leather sneakers") is matched to a slot of the same
    garment type: same colour if there is one, otherwise the first free slot of
    that type takes the owned colour. With no slot of that type, one is added.
    Lines whose garment type isn't recognised are returned.
    """
    unmatched: list[str] = []
    for line in (owned_text or "").splitlines():
        line = line.strip(" \t-•*")
        if not line:
            continue
        category = detect_garment(line)
        if category is None:
            unmatched.append(line)
            continue
        colour = find_colour(line)
        title = line[:1].upper() + line[1:]
        same_type = [s for s in slots if s["category"] == category and not s["owned"]]
        exact = [s for s in same_type if s["colour"] == colour]
        if exact:
            exact[0]["owned"] = True
        elif same_type and colour is None:
            same_type[0]["owned"] = True
        elif same_type:
            same_type[0].update(colour=colour, owned=True, name=title)
        else:
            slot = new_slot(category, colour or "grey", title, "", 1, taken)
            slot["owned"] = True
            slots.append(slot)
    return unmatched
