"""A store's German name for a product, in plain English, from a small list of garment words.

    name("Einreihiger Oversize-Mantel aus Wollmischung")  ->  "Single-breasted oversized coat, wool blend"
    name("Rider Jeans mit Geradem Bein")                  ->  None   ("Rider" is not in the list)

No AI and no outside service: every word of the name must be in WORDS below (or be made of words that are, like
"Leinenhose" = "Leinen" + "Hose"). One word that is not, and there is no English line at all, so the customer sees
the store's own words only and never a half-translated name that says something the store did not. The pages always
show the original too, in small print, because it is what the store's own page calls the product.

Two things in a name are not words to look up: a model's own name before a dash stays as it is ("Florian - Legere
Anzughose" -> "Florian – relaxed suit trousers"), and a cut said after the garment comes first, as in English ("Jeans
Slim Tapered" -> "Slim tapered jeans"). A name that is English already ("Classic Boxy T-Shirt") gets no second line.

To teach it a word, add it to WORDS with its English, and to the table in tests/test_english.py.
"""
from __future__ import annotations

import re
from functools import lru_cache

# German word (lower case) -> English. Adjectives are listed by their stem ("einreihig"): the endings German adds
# ("Einreihiger", "Lockere", "Geradem") are taken off when looking them up. Words that are already English in German
# names ("Oversize", "Boxy", "Relaxed Fit") are listed too, so that a name mixing both still reads in full.
WORDS = {
    # What it is
    "mantel": "coat",
    "jacke": "jacket",
    "bomberjacke": "bomber jacket",
    "windjacke": "windbreaker",
    "blazer": "blazer",
    "overshirt": "overshirt",
    "pullover": "jumper",
    "strickjacke": "cardigan",
    "cardigan": "cardigan",
    "hemd": "shirt",
    "t-shirt": "T-shirt",
    "langarmshirt": "long-sleeved top",
    "poloshirt": "polo shirt",
    "strickpolo": "knitted polo",
    "hose": "trousers",
    "anzughose": "suit trousers",
    "chinohose": "chinos",
    "chino": "chinos",
    "chinos": "chinos",
    "jeans": "jeans",
    "trousers": "trousers",
    "turnschuhe": "sneakers",
    "sneaker": "sneakers",
    "schuhe": "shoes",
    "loafer": "loafers",
    "loafers": "loafers",
    "derbys": "derby shoes",
    "derby": "derby",
    "boots": "boots",
    "stiefel": "boots",
    # Its parts and details
    "bein": "leg",
    "kragen": "collar",
    "schalkragen": "shawl collar",
    "kapuze": "hood",
    "reissverschluss": "zip",
    "reißverschluss": "zip",
    "v-ausschnitt": "V-neck",
    "rundhalsausschnitt": "crew neck",
    "rundhals": "crew-neck",
    "falten": "pleats",
    "bundfalten": "pleats",
    "bügelfalten": "pressed creases",
    "taille": "waist",
    "passform": "fit",
    "fit": "fit",
    "taschendetail": "pocket detail",
    "stretch": "stretch",
    "gürteldetail": "belt detail",
    "used-details": "worn-look details",
    "struktur": "texture",
    # What it is made of
    "wolle": "wool",
    "woll": "wool",
    "wollmischung": "wool blend",
    "wollmix": "wool blend",
    "mix": "blend",
    "merinowolle": "merino wool",
    "merinowoll": "merino wool",
    "merino": "merino",
    "kaschmir": "cashmere",
    "baumwolle": "cotton",
    "baumwoll": "cotton",
    "leinen": "linen",
    "seide": "silk",
    "popeline": "poplin",
    "jersey": "jersey",
    "twill": "twill",
    "flanell": "flannel",
    "piqué": "piqué",
    "denim": "denim",
    "cord": "corduroy",
    "canvas": "canvas",
    "nylon": "nylon",
    "modal": "modal",
    "leder": "leather",
    "veloursleder": "suede",
    "spalt": "split",
    "bouclé": "bouclé",
    "strick": "knit",
    "grobstrick": "chunky-knit",
    "doubleface": "double-faced",
    "slub": "slub",
    "selvedge": "selvedge",
    # How it is cut and made
    "einreihig": "single-breasted",
    "doppelreihig": "double-breasted",
    "zweireihig": "double-breasted",
    "oversize": "oversized",
    "oversized": "oversized",
    "locker": "relaxed",
    "leger": "relaxed",
    "relaxt": "relaxed",
    "relaxed": "relaxed",
    "entspannt": "relaxed",
    "lässig": "casual",
    "boxy": "boxy",
    "kastig": "boxy",
    "klassisch": "classic",
    "classic": "classic",
    "regular": "regular",
    "normal": "regular",
    "slim": "slim",
    "schmal": "slim",
    "weit": "wide",
    "gerad": "straight",
    "barrel": "barrel",
    "gerippt": "ribbed",
    "rip": "ribbed",
    "gestrickt": "knitted",
    "gekocht": "boiled",
    "meliert": "marled",
    "unstrukturiert": "unstructured",
    "nahtlos": "seamless",
    "rein": "pure",
    "fein": "fine",
    "schwer": "heavy",
    "leicht": "light",
    "kurz": "short",
    "markant": "bold",
    "geschnitten": "cut",
    "zulaufend": "tapering",
    "standard": "standard",
    "tapered": "tapered",
    "loose": "loose",
    "baggy": "baggy",
    "straight": "straight",
    "heavyweight": "heavyweight",
    "midweight": "midweight",
    "low": "low",
    "oxford": "Oxford",
    "penny": "penny",
    "chelsea": "Chelsea",
    # The little words between
    "mit": "with",
    "und": "and",
    "&": "and",
    "im": "in a",
    "in": "in",
}

# Two words that mean one thing together ("Schmal Zulaufendem Bein": a tapered leg), by their stems.
PAIRS = {
    ("schmal", "zulaufend"): "tapered",
    ("schmal", "geschnitten"): "slim-cut",
    ("locker", "geschnitten"): "relaxed-cut",
}

# "aus" (made of) becomes a comma, as in "Single-breasted oversized coat, wool blend".
MADE_OF = "aus"
# How it is cut, said after the garment ("Jeans Slim Tapered"): in English it comes first ("Slim tapered jeans").
AFTER = {"regular", "relaxed", "standard", "slim", "tapered", "loose", "baggy", "straight", "heavyweight", "midweight",
         "low"}
DASHES = {"-", "–"}

_ENDINGS = ("", "e", "en", "er", "es", "em")      # what German adds to an adjective: "einreihig" + "er"
_MODEL = re.compile(r"^(\w+)\s+[-–]\s+(.+)$")      # "Florian - Legere Anzughose": the model's name, then the name


def _stem(word: str) -> str | None:
    """English for one word as it is written in the name (any case, any adjective ending), or None."""
    low = word.lower()
    for ending in _ENDINGS:
        if low.endswith(ending) and low[: len(low) - len(ending)] in WORDS:
            return low[: len(low) - len(ending)]
    return None


def word(text: str) -> str | None:
    """English for one word of a name: itself or its stem ("Einreihiger"), its parts joined by hyphens
    ("Baumwoll-T-Shirt"), or the listed words it is made of ("Wollhose" = "Woll" + "Hose"); None if any part is not
    in the list."""
    stem = _stem(text)
    if stem:
        return WORDS[stem]
    if "-" in text:
        parts, out, i = text.split("-"), [], 0
        while i < len(parts):         # the longest run of parts that is one word: "T-Shirt" in "Baumwoll-T-Shirt"
            for j in range(len(parts), i, -1):
                found = _stem("-".join(parts[i:j]))
                if found:
                    out.append(WORDS[found])
                    i = j
                    break
            else:
                return None
        return " ".join(out)
    return _compound(text.lower())


def _compound(low: str, room: int = 3) -> str | None:
    """A German compound ("leinenhose") as the listed words it is made of, in their order ("linen trousers"): at most
    `room` parts of three letters or more, the last one taking German's endings."""
    for cut in range(3, len(low) - 2):
        head, rest = low[:cut], low[cut:]
        if head not in WORDS:
            continue
        stem = _stem(rest)
        tail = WORDS[stem] if stem else _compound(rest, room - 1) if room > 2 else None
        if tail:
            return f"{WORDS[head]} {tail}"
    return None


def _say(text: str) -> str | None:
    """`text` in English, starting in lower case unless its first word never does ("T-shirt"); None if a word is
    not in the list."""
    model = _MODEL.match(text)
    if model:                                  # the model's own name stays as it is: "Florian – relaxed suit trousers"
        rest = _say(model.group(2))
        return f"{model.group(1)} – {rest}" if rest else None
    words = text.replace(",", " , ").split()
    after = 0                                  # "Jeans Slim Tapered": the cut goes first
    while after < len(words) - 1 and words[len(words) - 1 - after].lower() in AFTER:
        after += 1
    if after:
        words = words[len(words) - after:] + words[:len(words) - after]
    out: list[str] = []
    i = 0
    while i < len(words):
        piece = words[i]
        if piece == ",":
            out.append(",")
        elif piece in DASHES:
            out.append("–")
        elif piece.lower() == MADE_OF:
            if not out:
                return None
            out.append(",")
        else:
            pair = (_stem(piece), _stem(words[i + 1]) if i + 1 < len(words) else None)
            if pair in PAIRS:
                out.append(PAIRS[pair])     # type: ignore[index]
                i += 2
                continue
            english = word(piece)
            if english is None:
                return None
            out.append(english)
        i += 1
    said = re.sub(r"(\s*,)+", ",", " ".join(out)).strip(" ,")
    return said or None


@lru_cache(maxsize=4096)
def name(original: str | None) -> str | None:
    """The product's name in English, or None when a word is not in the list or the name already is English."""
    text = " ".join(str(original or "").split())
    said = _say(text) if text else None
    if not said or said.lower().replace("-", " ") == text.lower().replace("-", " "):
        return None                            # nothing to say, or already English: the name is shown once
    return said[0].upper() + said[1:]
