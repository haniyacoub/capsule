"""The style brief: how a customer wants to dress, and how that steers the picks.

A brief is a small dict, every part of it optional:

    styles         ["street", "minimal"]     styles of config/style.toml
    formality      "casual" | "smart" | "formal" | ""
    colours_like   ["black", "grey"]         colour keys (colours.py)
    colours_avoid  ["mustard"]
    fits           ["relaxed", "oversized"]  as the stores name a product's fit
    price          "low" | "mid" | "high" | ""
    not_wanted     ["logo"]                  things he does not want, in his words

It comes from two places on Profile: the styles he ticks under "What do you
dress for?", and the style chat (stylechat.py), whose suggestion he corrects and
confirms. Only what he confirmed is stored (the setting "style_brief"), and only
that is read here.

What a brief does, all of it in this file and in plain arithmetic:

    product_points   a product's points for a brief, from its store, name, fabric, fit and colour
    narrow           among a piece's products, those that fit the brief first (selection.py)
    outfit_bonus     how far an outfit moves up or down the order (outfits.generate)
    why              one line saying why an outfit fits: "Street: relaxed jeans, overshirt"
    stores_that_suit the stores ranked by the style table in config/stores.toml

Without a brief (`current()` is None) none of it runs, and every pick is as it was before.
The numbers and the words are in config/style.toml.

A brief can come from a text model, so `clean` treats it as untrusted: it keeps only the
styles, colours, fits and levels that exist here, and short plain words for "not wanted".
Nothing in a brief names a product or a store: those are always chosen here, from the
catalogue.
"""
from __future__ import annotations

import re

from . import capsule, colours, config, db, programmes
from .config import ConfigError
from .garments import GARMENTS

SETTING = "style_brief"
FITS = {"slim": "Slim", "regular": "Regular", "relaxed": "Relaxed", "oversized": "Oversized"}
EMPTY: dict = {"styles": [], "formality": "", "colours_like": [], "colours_avoid": [], "fits": [], "price": "",
               "not_wanted": []}
MAX_NOT_WANTED = 8          # how many things he does not want are kept …
MAX_WORD = 30               # … and how long each may be
MAX_COLOURS = 8
POINTS = ("style_word", "style_garment", "fit", "other_fit", "colour", "colour_avoid", "not_wanted", "store_style",
          "store_price", "outfit_per_point", "outfit_most", "outfit_least", "formality")


# ── the rules (config/style.toml) ─────────────────────────────────────────────

def _check(data: dict) -> None:
    points = config.table(data.get("points"), "points")
    for name in POINTS:
        config.number(points.get(name), f"points.{name}")
    styles = config.table(data.get("styles"), "styles")
    if not styles:
        raise ConfigError("[styles] needs at least one style")
    for key, entry in styles.items():
        entry = config.table(entry, f"styles.{key}")
        if not isinstance(entry.get("label"), str) or not entry["label"].strip():
            raise ConfigError(f"styles.{key}.label must be the style's name")
        for name in ("words", "garments"):
            if not isinstance(entry.get(name), list) or not all(isinstance(word, str) for word in entry[name]):
                raise ConfigError(f"styles.{key}.{name} must be a list of words")
        unknown = [g for g in entry["garments"] if g not in GARMENTS]
        if unknown:
            raise ConfigError(f"styles.{key}.garments names {unknown[0]!r}, which is not a garment type")
    for key, entry in config.table(data.get("formality"), "formality").items():
        levels = config.table(entry, f"formality.{key}").get("levels")
        if not isinstance(levels, list) or len(levels) != 2:
            raise ConfigError(f"formality.{key}.levels must be two numbers, lowest and highest")
        for level in levels:
            config.number(level, f"formality.{key}.levels")
    for key, entry in config.table(data.get("price"), "price").items():
        if not isinstance(config.table(entry, f"price.{key}").get("stores"), list):
            raise ConfigError(f"price.{key}.stores must be a list of words")
    for key, words in config.table(data.get("not_wanted", {}), "not_wanted").items():
        if not isinstance(words, list) or not all(isinstance(word, str) for word in words):
            raise ConfigError(f"not_wanted.{key} must be a list of words")
    chat = config.table(data.get("chat"), "chat")
    if not isinstance(chat.get("model"), str) or not chat["model"].strip():
        raise ConfigError("chat.model must be the name of Google's text model")
    for name in ("per_day", "per_customer_per_day", "max_message_chars", "keep_turns"):
        if config.number(chat.get(name), f"chat.{name}") < 0:
            raise ConfigError(f"chat.{name} cannot be negative")


def load_rules() -> dict:
    return config.load("style.toml", _check)


def styles() -> dict[str, str]:
    """The styles a customer can tick, {key: name}, in the file's order."""
    return {key: entry["label"] for key, entry in load_rules()["styles"].items()}


def formalities() -> dict[str, str]:
    return {key: entry["label"] for key, entry in load_rules()["formality"].items()}


def prices() -> dict[str, str]:
    return {key: entry["label"] for key, entry in load_rules()["price"].items()}


# ── a brief: cleaning, storing ────────────────────────────────────────────────

def _strings(value: object, most: int = 20) -> list[str]:
    """A list of short strings out of anything: a list (other things in it are dropped), or one string."""
    items = value if isinstance(value, list) else [value] if isinstance(value, str) else []
    return [item for item in items if isinstance(item, str)][:most]


def _colours(value: object) -> list[str]:
    keys: list[str] = []
    for text in _strings(value):
        key = colours.find(text[:40])
        if key and key not in keys:
            keys.append(key)
    return keys[:MAX_COLOURS]


def _word(text: str) -> str:
    """Something he does not want, as a short plain word or two: letters, digits, spaces and hyphens only."""
    plain = " ".join(re.sub(r"[^a-z0-9äöüß -]+", " ", text.lower()).split())
    return plain[:MAX_WORD].strip(" -")


def clean(raw: object) -> dict:
    """A brief out of anything (a form, a text model's answer): only what exists here is kept. Never raises."""
    data = raw if isinstance(raw, dict) else {}
    rules = load_rules()
    wanted = [str(key).strip().lower().replace(" ", "-") for key in _strings(data.get("styles"))]
    formality, price = data.get("formality"), data.get("price")
    like = _colours(data.get("colours_like"))
    avoid = [key for key in _colours(data.get("colours_avoid"))]
    words: list[str] = []
    for text in _strings(data.get("not_wanted"), most=40):
        word = _word(text)
        if len(word) >= 2 and word not in words:
            words.append(word)
    return {
        "styles": [key for key in rules["styles"] if key in wanted],       # the file's order, each once
        "formality": formality if isinstance(formality, str) and formality in rules["formality"] else "",
        "colours_like": [key for key in like if key not in avoid],          # named in both: avoided, as on Profile
        "colours_avoid": avoid,
        "fits": [key for key in FITS if key in [str(f).strip().lower() for f in _strings(data.get("fits"))]],
        "price": price if isinstance(price, str) and price in rules["price"] else "",
        "not_wanted": words[:MAX_NOT_WANTED],
    }


def from_form(form) -> dict:
    """The brief as the customer corrected it on Profile (the fields of _style_chat.html)."""
    return clean({
        "styles": form.getlist("styles"), "formality": form.get("formality", ""),
        "colours_like": re.split(r"[,;/\n]", form.get("colours_like", "")),
        "colours_avoid": re.split(r"[,;/\n]", form.get("colours_avoid", "")),
        "fits": form.getlist("fits"), "price": form.get("price", ""),
        "not_wanted": re.split(r"[,;/\n]", form.get("not_wanted", "")),
    })


def active(brief: dict | None) -> bool:
    """Whether a brief says anything at all."""
    return brief is not None and any(brief.get(name) for name in EMPTY)


def stored() -> dict:
    """The brief he confirmed, whole (every part present), or an empty one."""
    return clean(db.get_setting(SETTING))


def current() -> dict | None:
    """The brief that steers the picks: the one he confirmed, or None when there is none (or it says nothing)."""
    raw = db.get_setting(SETTING)
    if not raw:
        return None
    brief = clean(raw)
    return brief if active(brief) else None


def save(brief: dict) -> None:
    db.set_setting(SETTING, clean(brief))


def set_styles(keys: list[str]) -> bool:
    """The styles ticked under "What do you dress for?": they are the brief's styles. True if that changed them."""
    brief = stored()
    new = clean({**brief, "styles": keys})
    if new == brief:
        return False
    save(new)
    return True


def remove() -> None:
    db.set_setting(SETTING, None)


# ── the stores ────────────────────────────────────────────────────────────────

def _store(key: str) -> dict:
    store = config.load("stores.toml").get(key)
    return store if isinstance(store, dict) else {}


def store_points(key: str, brief: dict) -> int:
    """A store's points for a brief, from its `styles` and `price` lines in config/stores.toml."""
    rules = load_rules()
    points, store = rules["points"], _store(key)
    listed = store.get("styles")
    theirs = listed if isinstance(listed, list) else []
    shared_styles = [style for style in brief["styles"] if style in theirs]
    total = min(2, len(shared_styles)) * points["store_style"]
    level = str(store.get("price") or "")
    if brief["price"] and any(word in level for word in rules["price"][brief["price"]]["stores"]):
        total += points["store_price"]
    return int(total)


def stores_that_suit(brief: dict, among: list[str] | None = None) -> list[str]:
    """The stores that suit a brief, best first (at equal points, in config/stores.toml's order): those customers
    are offered, or only the ones in `among` (the stores he ticked on Profile). A store with no points is left out."""
    keys = [key for key in programmes.offered() if among is None or key in among]
    ranked = sorted(((store_points(key, brief), -index, key) for index, key in enumerate(keys)), reverse=True)
    return [key for score, _, key in ranked if score > 0]


# ── a product ─────────────────────────────────────────────────────────────────

def _text(product: dict) -> str:
    """Everything a store says about a product, in lower case: its name (the German one and the English one in
    its address), fabric, fit and description."""
    parts = (product.get("name"), product.get("store_name"), str(product.get("slug") or "").replace("-", " "),
             product.get("composition_text"), product.get("composition"), product.get("fit"),
             product.get("description"))
    return " ".join(str(part).lower() for part in parts if part)


def _has(text: str, word: str) -> bool:
    """Whether a word (or the start of one: "woll" finds "wollmischung") is in the text."""
    return re.search(rf"(?<![a-zäöüß]){re.escape(word.lower())}", text) is not None


def judge(product: dict, category: str, brief: dict) -> tuple[int, str | None, str]:
    """A product (or an outfit's piece) against a brief: (points, the first of his styles it fits or None, the fit
    that earned points or ""). `category` is its garment type. Something he owns has no store, name or fit, so
    only its garment type counts."""
    rules = load_rules()
    points = rules["points"]
    text = _text(product)
    total = 0
    fits_style = None
    for key in brief["styles"]:
        style = rules["styles"][key]
        earned = 0
        if any(_has(text, word) for word in style["words"]):
            earned += points["style_word"]
        if category in style["garments"]:
            earned += points["style_garment"]
        if earned and fits_style is None:
            fits_style = key
        total += earned
    fit = str(product.get("fit") or "").lower()
    fit_liked = ""
    if brief["fits"] and fit in FITS:
        if fit in brief["fits"]:
            total += points["fit"]
            fit_liked = fit
        else:
            total += points["other_fit"]
    colour = colours.find(product.get("colour")) if product.get("colour") else None
    if colour:
        if colour in capsule.banned(brief["colours_avoid"]):      # avoiding "green" avoids olive too, as on Profile
            total += points["colour_avoid"]
        elif colour in brief["colours_like"]:
            total += points["colour"]
    for word in brief["not_wanted"]:
        if any(_has(text, form) for form in rules.get("not_wanted", {}).get(word, [word])):
            total += points["not_wanted"]
    if product.get("store"):
        total += store_points(product["store"], brief)
    return int(total), fits_style, fit_liked


def product_points(product: dict, category: str, brief: dict) -> int:
    return judge(product, category, brief)[0]


def narrow(pool: list, category: str, brief: dict | None) -> list:
    """Among a piece's products (selection.Cand), those the price level chooses among: the ones that fit the brief
    (more than 0 points) if there are any, else the ones it says nothing about, else all of them. So a product
    against the brief is picked only when the piece has nothing else. Without a brief: all of them, as before."""
    if not brief or not pool:
        return pool
    scored = [(product_points(cand.data, category, brief), cand) for cand in pool]
    return ([cand for score, cand in scored if score > 0]
            or [cand for score, cand in scored if score == 0]
            or pool)


# ── an outfit ─────────────────────────────────────────────────────────────────

def outfit_bonus(pieces: list[dict], level: float, brief: dict | None) -> float:
    """How far an outfit moves up (or down) the order for a brief: from its pieces' points and from whether it is
    as formal as he asked. `pieces` as outfits.snapshot gives them. 0 without a brief."""
    if not brief:
        return 0.0
    points = load_rules()["points"]
    total = sum(judge(piece, piece.get("category", ""), brief)[0] for piece in pieces)
    bonus = max(points["outfit_least"], min(points["outfit_most"], total * points["outfit_per_point"]))
    if brief["formality"]:
        low, high = load_rules()["formality"][brief["formality"]]["levels"]
        bonus += points["formality"] if low <= level <= high else -points["formality"]
    return float(bonus)


def why(pieces: list[dict], brief: dict | None) -> str:
    """One line saying why an outfit fits the brief: "Street: relaxed jeans, overshirt", or "" when nothing in it
    does. It names only what is true of the pieces: a garment the style is built on or whose store's words hold
    one of the style's words, with its fit when that is one he favours and the store states it."""
    if not brief:
        return ""
    rules = load_rules()
    by_style: dict[str, list[str]] = {}
    for piece in pieces:
        category = piece.get("category", "")
        score, style, fit = judge(piece, category, brief)
        if score <= 0 or category not in GARMENTS:
            continue
        name = GARMENTS[category].label.lower()
        colour = colours.find(piece.get("colour")) if piece.get("colour") else None
        if fit:
            name = f"{fit} {name}"
        elif colour and colour in brief["colours_like"]:
            name = f"{colours.get(colour).label.lower()} {name}"
        elif style is None:
            continue                    # its points are its store's alone: nothing to say about the piece itself
        by_style.setdefault(style or "", []).append(name)
    if not by_style:
        return ""
    # The style most of the pieces fit leads; pieces that fit only by fit or colour are named after it.
    lead = max(by_style, key=lambda key: (key != "", len(by_style[key])))
    named = list(dict.fromkeys(by_style[lead] + [n for key, names in by_style.items() if key != lead for n in names]))
    label = rules["styles"][lead]["label"] if lead else "Your brief"
    return f"{label}: {', '.join(named[:3])}"


# ── in words, for the page ────────────────────────────────────────────────────

def in_words(brief: dict) -> list[tuple[str, str]]:
    """A brief as (what, value) lines for the page; parts that are empty are left out."""
    rules = load_rules()
    lines = [
        ("Styles", ", ".join(rules["styles"][key]["label"] for key in brief["styles"])),
        ("How formal", rules["formality"][brief["formality"]]["label"] if brief["formality"] else ""),
        ("Colours to favour", ", ".join(colours.get(key).label.lower() for key in brief["colours_like"])),
        ("Colours to avoid", ", ".join(colours.get(key).label.lower() for key in brief["colours_avoid"])),
        ("Fits", ", ".join(FITS[key].lower() for key in brief["fits"])),
        ("Price feeling", rules["price"][brief["price"]]["label"] if brief["price"] else ""),
        ("Not wanted", ", ".join(brief["not_wanted"])),
    ]
    return [(what, value) for what, value in lines if value]
