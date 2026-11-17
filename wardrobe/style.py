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
    against          whether the brief speaks against a product: a colour he avoids, something he does not want
    narrow           among a piece's products, those that fit the brief first (selection.py)
    outfit_style     the one of his styles an outfit is as a whole, with the pieces that make it so, or none
    in_his_colours_or_fits   the same for a brief without styles: the outfit is mostly in his colours or fits
    outfit_bonus     how far an outfit moves up or down the order (outfits.generate)
    why              one line under an outfit that fits as a whole: "Street: t-shirt, relaxed jeans, sneakers"
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
from typing import NamedTuple

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
          "store_price", "outfit_per_point", "outfit_most", "outfit_least", "formality", "outfit_share",
          "outfit_pieces", "outfit_style")


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
        for garment, kinds in config.table(entry.get("kinds", {}), f"styles.{key}.kinds").items():
            if garment not in GARMENTS:
                raise ConfigError(f"styles.{key}.kinds names {garment!r}, which is not a garment type")
            if not isinstance(kinds, list) or not kinds or not all(isinstance(word, str) for word in kinds):
                raise ConfigError(f"styles.{key}.kinds.{garment} must be a list of words")
        _two_levels(entry.get("levels"), f"styles.{key}.levels")
        if "share" in entry and not 0 < config.number(entry["share"], f"styles.{key}.share") <= 1:
            raise ConfigError(f"styles.{key}.share must be more than 0 and at most 1")
    for key, entry in config.table(data.get("formality"), "formality").items():
        _two_levels(config.table(entry, f"formality.{key}").get("levels"), f"formality.{key}.levels")
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
    for name in ("at_once", "wait_seconds"):
        if config.number(chat.get(name), f"chat.{name}") < 1:
            raise ConfigError(f"chat.{name} must be at least 1")


def _two_levels(levels: object, where: str) -> None:
    if not isinstance(levels, list) or len(levels) != 2:
        raise ConfigError(f"{where} must be two numbers, lowest and highest")
    for level in levels:
        config.number(level, where)


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
    """Keep the brief he confirmed. One that says nothing is no brief: nothing is kept of it."""
    brief = clean(brief)
    if active(brief):
        db.set_setting(SETTING, brief)
    else:
        remove()


def set_styles(keys: list[str]) -> bool:
    """The styles ticked under "What do you dress for?": they are the brief's styles. True if that changed them."""
    if not styles_differ(keys):
        return False
    save({**stored(), "styles": keys})
    return True


def styles_differ(keys: list[str]) -> bool:
    """Whether ticking exactly these styles would change the brief (whether set_styles has something to do)."""
    brief = stored()
    return clean({**brief, "styles": keys}) != brief


def remove() -> None:
    """No brief any more: its row in the settings goes (nothing is left behind, not even an empty value)."""
    db.delete_setting(SETTING)


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
    """Whether a word (or the start of one: "woll" finds "wollmischung", and not "baumwolle") is in the text. A
    word written with a star before it is looked for anywhere, inside another word too: "*leder" finds
    "veloursleder" and "kuhleder"."""
    word = word.lower()
    if word.startswith("*"):
        return word[1:] in text
    return re.search(rf"(?<![a-zäöüß]){re.escape(word)}", text) is not None


def _names(category: str) -> set[str]:
    """What a garment type is called on the pages, as whole names and as single words, in lower case: for "shoes"
    that is "shoes", "leather shoes" and "leather"."""
    garment = GARMENTS.get(category)
    if garment is None:
        return set()
    whole = {garment.key, garment.label.lower(), garment.plural.lower()}
    return whole | {part for name in whole for part in name.split()}


def _is_called(category: str, word: str) -> bool:
    """Whether a word he wrote is what the garment itself is called ("blazer", "blazers", and "leather" for
    leather shoes), whatever the store's words for the product are."""
    word = word.lower().lstrip("*")
    return bool({word, word + "s", word.removesuffix("s")} & _names(category))


class Judged(NamedTuple):
    """A product (or an outfit's piece) against a brief."""
    points: int                 # what it earns and loses (config/style.toml, [points])
    style: str | None           # the first of his styles it fits, by a word or as a garment
    fit: str                    # its fit, when that is one he favours and the store states it; else ""
    against: bool               # the brief speaks against it: a colour he avoids, or something he does not want
    garment_of: tuple[str, ...]   # those of his styles it is a garment of (what makes an outfit that style)
    unwanted: bool = False      # … against it by the product itself (its colour, the store's words), not only by
    #                             what its garment is called: among "Leather shoes" a pair that is not leather


# Judgements already made: (the rules and the stores' lines they were made with, {what was judged: the judgement}).
# The Outfits page orders hundreds of combinations of the same twenty or so pieces, and judging a piece reads the
# store's words against every word of his styles, so a piece is judged once and remembered. A change of
# config/style.toml or config/stores.toml starts a new, empty memory (config.load then hands out a new object).
_judged: tuple[dict, dict, dict] | None = None
MOST_JUDGED = 20000         # judgements remembered at most; past that the memory starts again, empty


def judge(product: dict, category: str, brief: dict) -> Judged:
    """A product (or an outfit's piece) against a brief (Judged). `category` is its garment type. Something he
    owns has no store, name or fit, so only its garment type and its colour count. Worked out once for the same
    words, colour, fit, store and brief (_judge), and remembered while the rules stay as they are."""
    global _judged
    rules, stores = load_rules(), config.load("stores.toml")
    memory = _judged
    if memory is None or memory[0] is not rules or memory[1] is not stores or len(memory[2]) >= MOST_JUDGED:
        memory = _judged = (rules, stores, {})
    key = (category, _text(product), str(product.get("fit") or ""), str(product.get("colour") or ""),
           str(product.get("store") or ""), tuple(str(brief[name]) for name in EMPTY))
    found = memory[2].get(key)
    if found is None:
        found = memory[2][key] = _judge(product, category, brief)
    return found


def _judge(product: dict, category: str, brief: dict) -> Judged:
    """The judgement itself (see judge), worked out from the rules."""
    rules = load_rules()
    points = rules["points"]
    text = _text(product)
    total = 0
    fits_style = None
    garment_of = []
    for key in brief["styles"]:
        style = rules["styles"][key]
        earned = 0
        if any(_has(text, word) for word in style["words"]):
            earned += points["style_word"]
        # A garment the style is built on, or one it is built on only in some kinds (a jacket is street when the
        # store's words say it is a bomber, not when it is a boiled-wool jacket: `kinds`).
        if category in style["garments"] or any(_has(text, word) for word in style.get("kinds", {}).get(category, [])):
            earned += points["style_garment"]
            garment_of.append(key)
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
    unwanted = called = False
    colour = colours.find(product.get("colour")) if product.get("colour") else None
    if colour:
        if colour in capsule.banned(brief["colours_avoid"]):      # avoiding "green" avoids olive too, as on Profile
            total += points["colour_avoid"]
            unwanted = True
        elif colour in brief["colours_like"]:
            total += points["colour"]
    for word in brief["not_wanted"]:
        # In the store's words about the product, or in what the garment itself is called: "leather" speaks
        # against every piece the pages call "Leather shoes", whatever the store calls the pair.
        forms = rules.get("not_wanted", {}).get(word, [word])
        in_words = any(_has(text, form) for form in forms)
        is_called = any(_is_called(category, form) for form in [word, *forms])
        if in_words or is_called:
            total += points["not_wanted"]
        unwanted, called = unwanted or in_words, called or is_called
    if product.get("store"):
        total += store_points(product["store"], brief)
    return Judged(int(total), fits_style, fit_liked, unwanted or called, tuple(garment_of), unwanted)


def product_points(product: dict, category: str, brief: dict) -> int:
    return judge(product, category, brief).points


def against(product: dict, category: str, brief: dict | None) -> bool:
    """Whether the brief speaks against a product in any one respect: its colour is one he avoids, or something he
    does not want is in the store's words about it or in what the garment itself is called. Whatever else it
    earns points for does not make up for that: such a product is picked only when the piece has nothing else,
    and an outfit with such a piece is never said to fit the brief."""
    return brief is not None and judge(product, category, brief).against


def narrow(pool: list, category: str, brief: dict | None) -> list:
    """Among a piece's products (selection.Cand), those the price level chooses among. First the ones the brief
    does not speak against by themselves (their colour, the store's words: `unwanted`; what the garment is called
    is the same for all of them, so among "Leather shoes" a pair that is not leather comes first): of those, the
    ones that fit it (more than 0 points) if there are any, else the ones it says nothing about, else the rest of
    them. Only when the brief speaks against every product are all of them left, so no piece is left empty.
    Without a brief: all of them, as before."""
    return narrowed(pool, category, brief)[0]


def narrowed(pool: list, category: str, brief: dict | None) -> tuple[list, str]:
    """What `narrow` leaves of a piece's products, and how it got there, for the sentence on the piece's page
    ("Picked for you: the cheapest option that fits your style"): "" when the brief passed nothing over (or there
    is no brief), so the price level chose among all of them as it does without one; "fits" when it passed some
    over and the ones left fit it; "best" when it passed some over and none fits it, so the ones left are those
    that suit it best (it says nothing about them, or speaks against them least)."""
    if not brief or not pool:
        return pool, ""
    judged = [(judge(cand.data, category, brief), cand) for cand in pool]
    allowed = [(found.points, cand) for found, cand in judged if not found.unwanted]
    fits = [cand for score, cand in allowed if score > 0]
    left = (fits
            or [cand for score, cand in allowed if score == 0]
            or [cand for score, cand in allowed]
            or pool)
    return left, "" if len(left) == len(pool) else "fits" if fits else "best"


# ── an outfit ─────────────────────────────────────────────────────────────────

def _each_judged(pieces: list[dict], brief: dict) -> list[Judged] | None:
    """Each piece of an outfit against the brief, or None when the brief speaks against one of them: such an
    outfit does not fit the brief as a whole, whatever its other pieces are."""
    found = [judge(piece, piece.get("category", ""), brief) for piece in pieces]
    return None if any(one.against for one in found) else found


def outfit_style(pieces: list[dict], level: float, brief: dict | None) -> tuple[str, list[dict]] | None:
    """The one of his styles an outfit is as a whole, with the pieces that make it so, or None when it is none of
    them. `pieces` as outfits.snapshot gives them, `level` how formal the outfit is (1 very casual … 5 formal).

    An outfit is a style when all of this holds (the numbers are in config/style.toml):
      * the brief speaks against none of its pieces (`against`: a colour he avoids, something he does not want).
        With "no leather" an outfit with leather shoes is never "Tailored", however tailored the rest of it is;
      * at least three quarters of its pieces, and at least two, are garments the style is built on (jeans, a
        T-shirt and sneakers for street): all of three pieces, three of four, four of five. Minimal asks for
        every piece (its own `share`). The words a store uses do not count here: a shirt the store calls
        "loose" is not street by that. Only for a garment the style lists under `kinds` do they say which kind
        it is: a jacket is street when it is a bomber, not when it is a boiled-wool jacket;
      * the outfit is as formal as the style allows. Street stops below "Smart casual", so an Office outfit of an
        oxford shirt, chinos and derby shoes is never street.
    Where two of his styles hold, the one with more such pieces wins, then the one listed first."""
    if not brief or not brief["styles"] or not pieces:
        return None
    judged = _each_judged(pieces, brief)
    if judged is None:
        return None
    rules = load_rules()
    points = rules["points"]
    best: tuple[str, list[dict]] | None = None
    for key in brief["styles"]:
        style = rules["styles"][key]
        low, high = style["levels"]
        if not low <= level <= high:
            continue
        own = [piece for piece, found in zip(pieces, judged) if key in found.garment_of]
        share = style.get("share", points["outfit_share"])
        if len(own) < points["outfit_pieces"] or len(own) < share * len(pieces):
            continue
        if best is None or len(own) > len(best[1]):
            best = (key, own)
    return best


def in_his_colours_or_fits(pieces: list[dict], brief: dict | None) -> list[dict] | None:
    """For a brief that names no style (colours or fits only): the pieces of an outfit that are in a colour or a
    fit he favours, when the brief speaks against none of the outfit's pieces and they are enough of the outfit
    to say so of it as a whole (the threshold of outfit_style: three quarters of its pieces, and at least two).
    Else None."""
    if not brief or brief["styles"] or not pieces:
        return None
    judged = _each_judged(pieces, brief)
    if judged is None:
        return None
    his = []
    for piece, found in zip(pieces, judged):
        if piece.get("category", "") not in GARMENTS:
            continue
        colour = colours.find(piece.get("colour")) if piece.get("colour") else None
        if found.points > 0 and (found.fit or (colour and colour in brief["colours_like"])):
            his.append(piece)
    points = load_rules()["points"]
    if len(his) < points["outfit_pieces"] or len(his) < points["outfit_share"] * len(pieces):
        return None
    return his


def outfit_bonus(pieces: list[dict], level: float, brief: dict | None) -> float:
    """How far an outfit moves up (or down) the order for a brief: from its pieces' points, from whether it is
    as formal as he asked, and from whether it fits the brief as a whole (it is one of his styles, outfit_style,
    or, for a brief without styles, mostly in his colours or fits): those are the outfits that say why.
    `pieces` as outfits.snapshot gives them. 0 without a brief."""
    if not brief:
        return 0.0
    points = load_rules()["points"]
    total = sum(judge(piece, piece.get("category", ""), brief).points for piece in pieces)
    bonus = max(points["outfit_least"], min(points["outfit_most"], total * points["outfit_per_point"]))
    if brief["formality"]:
        low, high = load_rules()["formality"][brief["formality"]]["levels"]
        bonus += points["formality"] if low <= level <= high else -points["formality"]
    if outfit_style(pieces, level, brief) or in_his_colours_or_fits(pieces, brief):
        bonus += points["outfit_style"]
    return float(bonus)


def _named(piece: dict, brief: dict, fit: str) -> str:
    """A piece as the line names it: its garment ("jeans"), with its fit before it when that is one he favours and
    the store states it ("relaxed jeans", `fit` from judge), or else its colour when that is one he favours
    ("black jeans")."""
    name = GARMENTS[piece["category"]].label.lower()
    colour = colours.find(piece.get("colour")) if piece.get("colour") else None
    if fit:
        return f"{fit} {name}"
    if colour and colour in brief["colours_like"]:
        return f"{colours.get(colour).label.lower()} {name}"
    return name


def why(pieces: list[dict], level: float, brief: dict | None) -> str:
    """One line saying why an outfit fits the brief, or "" when there is nothing true to say of it as a whole.

    With styles in the brief: "Street: t-shirt, relaxed jeans, sneakers" only when the outfit is that style as a
    whole (outfit_style), naming the pieces that make it so. With a brief that names no style (colours or fits
    only): "Your brief: navy jumper, navy chinos, navy sneakers", under the same threshold
    (in_his_colours_or_fits). Any other outfit says nothing, so the line tells the outfits apart."""
    if not brief:
        return ""
    found = outfit_style(pieces, level, brief)
    if found:
        label, own = load_rules()["styles"][found[0]]["label"], found[1]
    else:
        label, own = "Your brief", in_his_colours_or_fits(pieces, brief) or []
    names = [_named(piece, brief, judge(piece, piece["category"], brief).fit) for piece in own]
    return f"{label}: {', '.join(dict.fromkeys(names))}" if names else ""


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
