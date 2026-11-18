"""Proposes the plan: the pieces outfits are made from, in one coherent palette, as many as the budget buys.

How many: config/budget.toml says, step by step (the budget's money for pieces, each piece at its usual price, the
kinds of wardrobe that join, and the line their pieces stand in), with at most 24 pieces. Which: the ranked lists
below (RANKED), most needed first.

The idea behind the palette:
  * one dark anchor, one mid neutral, one light — most pieces come from these
  * one accent colour, used once or twice on top layers
  * trousers and shoes stay neutral, so nearly every top works with every bottom

The proposal is only a starting point: every slot can be edited, removed or
added on the Slots page. When the profile changes, rebuild() proposes afresh
and keeps what was picked or marked as owned by hand.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

from . import config
from .colours import COLOURS, Colour, find as find_colour, get as get_colour
from .garments import GARMENTS

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

# The pieces of each kind of wardrobe, most needed first: (garment, colour role, name, keywords, quantity). {c} is
# the colour. Rows 1-3 are a kind's first three pieces, a top, trousers and shoes: the smallest wardrobe that makes
# an outfit of that kind. Under config/budget.toml's `full_names_from` (450 €) the words of its `left_out_below`
# (merino, wool, leather) are left out of the names; the ids keep the full names at every budget.
RANKED = {
    "everyday": [
        ("tee", "light", "{c} tee", "heavyweight", 2),
        ("jeans", "denim", "{c} jeans", "straight", 1),
        ("sneakers", "light", "{c} leather sneakers", "leather", 1),
        ("tee", "anchor", "{c} tee", "heavyweight", 1),
        ("chinos", "earth", "{c} chinos", "", 1),
        ("knit", "mid", "{c} merino jumper", "merino crew-neck", 1),
        ("jacket", "anchor", "{c} light jacket", "lightweight", 1),
        ("overshirt", "accent", "{c} overshirt", "", 1),
        ("shirt", "light", "{c} oxford shirt", "oxford", 1),
        ("tee", "mid", "{c} tee", "heavyweight", 1),
        ("knit", "accent2", "{c} merino jumper", "merino crew-neck", 1),
        ("coat", "dark2", "{c} wool coat", "wool", 1),
        ("longsleeve", "light", "{c} long-sleeve tee", "", 1),
        ("jeans", "denim2", "{c} jeans", "straight", 1),
        ("boots", "shoe_dark", "{c} chelsea boots", "leather chelsea", 1),
        ("shirt", "shirt_blue", "{c} oxford shirt", "oxford", 1),
        ("cardigan", "light2", "{c} cardigan", "wool", 1),
        ("polo", "anchor", "{c} knitted polo", "knitted", 1),
    ],
    "office": [
        ("shirt", "light", "{c} oxford shirt", "oxford", 1),
        ("trousers", "mid", "{c} wool trousers", "wool", 1),
        ("shoes", "shoe_dark", "{c} derby shoes", "leather derby", 1),
        ("knit", "mid", "{c} merino jumper", "merino crew-neck", 1),
        ("chinos", "earth", "{c} chinos", "", 1),
        ("shirt", "shirt_blue", "{c} oxford shirt", "oxford", 1),
        ("blazer", "anchor", "{c} wool blazer", "wool", 1),
        ("trousers", "dark2", "{c} tailored trousers", "tailored", 1),
        ("knit", "accent2", "{c} merino jumper", "merino crew-neck", 1),
        ("coat", "dark2", "{c} wool coat", "wool", 1),
        ("cardigan", "light2", "{c} cardigan", "wool", 1),
        ("polo", "anchor", "{c} knitted polo", "knitted", 1),
        ("tee", "light", "{c} tee", "heavyweight", 1),
        ("sneakers", "light", "{c} leather sneakers", "leather", 1),
        ("trousers", "anchor", "{c} tailored trousers", "tailored", 1),
    ],
}
FIRST = 3       # a kind's first three pieces

# What each answer to "What do you dress for?" plans: its kinds, in the order they join.
KINDS = {"everyday": ("everyday",), "office": ("office",), "both": ("everyday", "office")}

# The garments "Include shoes" and "Include outerwear" leave out when unticked.
SHOES = frozenset({"sneakers", "shoes", "boots"})
OUTERWEAR = frozenset({"coat", "jacket"})

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
    slots, taken = _planned(profile)
    unmatched = apply_owned(slots, profile.get("owned", ""), taken)
    return slots, unmatched


def _check_budget(rules: dict) -> None:
    """Catch values in config/budget.toml that are valid TOML but would plan nonsense."""
    number, table = config.number, config.table
    money = table(rules.get("money", {}), "money")
    if number(money.get("whole_budget_up_to"), "money.whole_budget_up_to") < 0:
        raise config.ConfigError("money.whole_budget_up_to must be 0 or more")
    if not 0 <= number(money.get("share_of_the_rest"), "money.share_of_the_rest") <= 1:
        raise config.ConfigError("money.share_of_the_rest must be between 0 and 1 (0.5 = half)")
    if number(money.get("most_pieces"), "money.most_pieces") < 1:
        raise config.ConfigError("money.most_pieces must be 1 or more")
    names = table(rules.get("names", {}), "names")
    number(names.get("full_names_from"), "names.full_names_from")
    words = names.get("left_out_below")
    if not isinstance(words, list) or not all(isinstance(word, str) for word in words):
        raise config.ConfigError('names.left_out_below must be a list of words, like ["merino", "wool"]')
    prices = table(rules.get("usual_price", {}), "usual_price")
    for category in sorted({row[0] for rows in RANKED.values() for row in rows}):
        if number(prices.get(category), f"usual_price.{category}") <= 0:
            raise config.ConfigError(f"usual_price.{category} must be more than 0")


def budget_rules() -> dict:
    return config.load("budget.toml", _check_budget)


def money_for_pieces(budget: float, rules: dict | None = None) -> float:
    """What of a budget buys pieces (config/budget.toml): all of it up to 200 €, and half of what is above that.
    150 € -> 150 €, 300 € -> 250 €, 1,000 € -> 600 €. The rest buys better versions of the same pieces."""
    money = (rules or budget_rules())["money"]
    up_to = float(money["whole_budget_up_to"])
    return min(budget, up_to) + max(0.0, budget - up_to) * float(money["share_of_the_rest"])


def _budget(profile: dict) -> float | None:
    """The budget the plan is sized for, or None when the profile holds none (never so for a customer: his profile
    starts with the example's budget). Without one the plan is as big as the lists and config/budget.toml allow."""
    try:
        budget = float(profile.get("budget") or 0)
    except (TypeError, ValueError):
        return None
    return budget if 0 < budget < math.inf else None


@dataclass(frozen=True)
class _Piece:
    """One row of RANKED in these colours. `name` is the full name, which the id comes from."""
    id: str
    category: str
    colour: str
    name: str
    keywords: str
    qty: int


def _pieces(profile: dict) -> tuple[dict[tuple[str, str], _Piece], dict[str, list[tuple[int, tuple[str, str]]]]]:
    """Every piece the kinds of this profile could have, by (garment, colour), and each kind's rows as (rank, that
    key), without the garments the shoes and outerwear ticks leave out. A piece's name and id are given here, in one
    fixed order (the kinds in order, each top to bottom), so that a piece has the same id at every budget, whichever
    kinds the budget lets in. Two rows in the same garment and colour are one piece: the first one's."""
    palette = build_palette(profile.get("liked", []), profile.get("refused", []))
    kinds = KINDS.get(profile.get("use", "both"), KINDS["both"])
    left_out = (SHOES if not profile.get("shoes", True) else frozenset()) | \
               (OUTERWEAR if not profile.get("outerwear", True) else frozenset())
    pieces: dict[tuple[str, str], _Piece] = {}
    rows: dict[str, list[tuple[int, tuple[str, str]]]] = {}
    ids: set[str] = set()
    for kind in kinds:
        rows[kind] = []
        for rank, (category, role, name, keywords, qty) in enumerate(RANKED[kind]):
            if category in left_out:
                continue
            key = (category, palette[role])
            if key not in pieces:
                full = name.format(c=get_colour(key[1]).label)
                piece_id = unique_id(slugify(full), ids)
                ids.add(piece_id)
                pieces[key] = _Piece(piece_id, category, key[1], full, keywords, qty)
            rows[kind].append((rank, key))
    return pieces, rows


def _sized(profile: dict) -> tuple[list[str], list[_Piece]]:
    """The kinds of wardrobe that join at this profile's budget, and the pieces of the plan, most needed first
    (config/budget.toml says how, step by step). The first kind is always in with its first three pieces, also
    where the money would not buy them: fewer would make no outfit, and "Best for budget" then says the budget is
    too small."""
    rules = budget_rules()
    usual = rules["usual_price"]
    budget = _budget(profile)
    money = math.inf if budget is None else money_for_pieces(budget, rules)
    most = int(rules["money"]["most_pieces"])
    pieces, rows = _pieces(profile)

    def first(kind: str) -> list[tuple[str, str]]:     # a kind's first three pieces (fewer when a tick left one out)
        return list(dict.fromkeys(key for rank, key in rows[kind] if rank < FIRST))

    def cost(key: tuple[str, str]) -> float:
        return float(usual[key[0]]) * pieces[key].qty

    # A kind joins when its first three pieces fit in the money; a piece already in the plan counts nothing. The
    # first kind that does not fit waits, and every kind after it waits too.
    joined: list[str] = []
    planned: set[tuple[str, str]] = set()
    spent = 0.0
    for kind in rows:
        new = [key for key in first(kind) if key not in planned]
        if joined and spent + sum(cost(key) for key in new) > money:
            break
        joined.append(kind)
        planned.update(new)
        spent += sum(cost(key) for key in new)

    # The line: the joined kinds' first three pieces, then each kind's 4th piece, then each kind's 5th, and so on. A
    # piece already in the line (same garment, same colour) is skipped: a piece two kinds share is bought once.
    line = [key for kind in joined for key in first(kind)]
    for rank in range(FIRST, max(len(ranked) for ranked in RANKED.values())):
        line += [key for kind in joined for at, key in rows[kind] if at == rank]
    line = list(dict.fromkeys(line))

    # The plan: the line from the top, for as long as the money lasts and with at most `most` pieces.
    always = set(first(joined[0])) if joined else set()
    plan: list[_Piece] = []
    total, count = 0.0, 0
    for key in line:
        piece = pieces[key]
        if key not in always and (total + cost(key) > money or count + piece.qty > most):
            break
        plan.append(piece)
        total += cost(key)
        count += piece.qty
    return joined, plan


def kinds_in(profile: dict) -> list[str]:
    """The kinds of wardrobe ("everyday", "office") the profile's budget lets into the plan, in the order they join."""
    return _sized(profile)[0]


def _planned(profile: dict) -> tuple[list[dict], set[str]]:
    """The slots these answers call for, before anything already owned is placed, and their ids. In the order the
    garments are listed (garments.py): coats first, shoes last."""
    rules = budget_rules()["names"]
    budget = _budget(profile)
    plain = budget is not None and budget < float(rules["full_names_from"])
    words = {str(word).lower() for word in rules["left_out_below"]} if plain else set()
    order = list(GARMENTS)
    slots: list[dict] = []
    for piece in sorted(_sized(profile)[1], key=lambda p: order.index(p.category)):
        name = " ".join(word for word in piece.name.split(" ") if word.lower() not in words)
        slots.append({"id": piece.id, "name": name, "category": piece.category, "colour": piece.colour,
                      "keywords": piece.keywords, "qty": piece.qty, "owned": False})
    return slots, {slot["id"] for slot in slots}


@dataclass
class Rebuilt:
    """A plan rebuilt from new answers (see rebuild), and what became of the choices made by hand."""
    slots: list[dict]
    unmatched: list[str] = field(default_factory=list)   # "already own" lines whose garment wasn't recognised
    picked: list[dict] = field(default_factory=list)     # slots that kept the product picked by hand
    owned: list[str] = field(default_factory=list)       # pieces marked as owned by hand: still owned
    lost: list[tuple[str, str]] = field(default_factory=list)   # (piece, why) for picks that could not be kept
    stayed: list[dict] = field(default_factory=list)     # pieces of his wardrobe the new plan had no place for: kept as they were (app.py)


def rebuild(profile: dict, old: list[dict], old_owned_text: str = "") -> Rebuilt:
    """A fresh proposal from the profile that keeps what was decided by hand in the old plan.

    * A slot whose product was chosen or locked by hand keeps that product and its lock when the
      new plan has the same garment in the same colour. It keeps its id, name and keywords too,
      so it is offered the same products. Otherwise it is listed in `lost`, with the reason.
    * A slot marked as owned stays owned: it takes the place of a slot of that garment, the way
      a line of "Things to build around" does (see own). Slots that are owned because of such a
      line follow the lines instead (`old_owned_text` is the text the old plan was built with):
      a line deleted from the profile is no longer owned.
    """
    slots, taken = _planned(profile)
    done = Rebuilt(slots)
    for before in old:
        if before.get("owned") or not (before.get("locked") and before.get("pick")):
            continue
        same = [s for s in slots if (s["category"], s["colour"]) == (before["category"], before["colour"])
                and not s.get("locked")]
        if not same:
            garment_stays = any(s["category"] == before["category"] for s in slots)
            done.lost.append((before["name"], "not in your new colours" if garment_stays else "not in your new plan"))
            continue
        slot = next((s for s in same if s["id"] == before["id"]), same[0])
        if slot["id"] != before["id"] and before["id"] not in {s["id"] for s in slots}:
            taken.discard(slot["id"])
            taken.add(before["id"])
            slot["id"] = before["id"]       # the products on offer belong to the id
        slot.update(name=before["name"], keywords=before.get("keywords", ""), locked=True, pick=before["pick"])
        done.picked.append(slot)

    done.unmatched = apply_owned(slots, profile.get("owned", ""), taken)
    for before in _owned_by_hand(old, old_owned_text):
        if not any(s["owned"] and (s["category"], s["colour"]) == (before["category"], before["colour"])
                   for s in slots):
            own(slots, before["category"], before["colour"], before["name"], taken, int(before.get("qty") or 1))
        done.owned.append(before["name"])
    done.picked = [s for s in done.picked if not s["owned"]]   # owned now: its product is no longer needed
    return done


def _owned_by_hand(old: list[dict], owned_text: str) -> list[dict]:
    """The owned slots of a plan that were marked by hand, not placed by a line of `owned_text`."""
    owned = [s for s in old if s.get("owned")]
    for line in _lines(owned_text):
        category, colour = detect_garment(line), find_colour(line)
        placed = next((s for s in owned if s["category"] == category and colour in (None, s["colour"])), None)
        if placed is not None:
            owned.remove(placed)
    return owned


def same_plan(slots: list[dict], profile: dict) -> bool:
    """Whether the slots are, one for one, what the profile proposes: nothing was added, renamed,
    recoloured or removed by hand. Products chosen, locks and owned marks don't count."""
    def shape(plan: list[dict]) -> list[tuple]:
        return sorted((s["id"], s["name"], s["category"], s["colour"], int(s.get("qty") or 1), s.get("keywords", ""))
                      for s in plan)
    return shape(slots) == shape(propose(profile)[0])


def detect_garment(text: str) -> str | None:
    t = re.sub(r"[-_]", " ", text.lower())
    for category, words in _GARMENT_WORDS:
        if any(re.search(rf"(?<![a-zäöüß]){re.escape(w)}", t) for w in words):
            return category
    return None


def garment_words(category: str) -> list[str]:
    """The words that name one kind of garment: "coat", "overcoat", "trench", "parka", "mantel" for a coat."""
    return next((words for key, words in _GARMENT_WORDS if key == category), [])


def _lines(owned_text: str) -> list[str]:
    """The lines of "Things to build around", without list marks and blank lines."""
    return [line for line in (raw.strip(" \t-•*") for raw in (owned_text or "").splitlines()) if line]


def apply_owned(slots: list[dict], owned_text: str, taken: set[str]) -> list[str]:
    """Build around what you already own.

    Each line ("white leather sneakers") is matched to a slot of the same
    garment type (see own). Lines whose garment type isn't recognised are returned.
    """
    unmatched: list[str] = []
    for line in _lines(owned_text):
        category = detect_garment(line)
        if category is None:
            unmatched.append(line)
            continue
        own(slots, category, find_colour(line), line[:1].upper() + line[1:], taken)
    return unmatched


def own(slots: list[dict], category: str, colour: str | None, title: str, taken: set[str], qty: int = 1) -> None:
    """Put something you own into the plan.

    A free slot of that garment in that colour becomes owned. Otherwise the first free slot of
    that garment takes the owned colour and name (with no colour known, it keeps its own); a slot
    planned more times than you own gives up only as many as you own, as a slot of their own.
    A slot whose product was picked by hand is never recoloured. With no slot of that garment,
    one is added.
    """
    free = sorted((s for s in slots if s["category"] == category and not s["owned"]),
                  key=lambda s: bool(s.get("locked")))            # slots picked by hand come last
    exact = [s for s in free if s["colour"] == colour]
    spare = [s for s in free if not s.get("locked")]
    if exact:
        exact[0]["owned"] = True
    elif free and colour is None:
        free[0]["owned"] = True
    elif spare and int(spare[0].get("qty") or 1) > qty:          # e.g. two white tees planned, a black one owned
        spare[0]["qty"] = int(spare[0]["qty"]) - qty
        slots.insert(slots.index(spare[0]) + 1, {**new_slot(category, colour or "grey", title, "", qty, taken),
                                                 "owned": True})
    elif spare:
        spare[0].update(colour=colour, owned=True, name=title, qty=qty)
    else:
        slots.append({**new_slot(category, colour or "grey", title, "", qty, taken), "owned": True})
