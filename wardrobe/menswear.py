"""Stilsmith is for men: which products are menswear, decided in this one place. There is no switch.

Every way a product comes in asks here:

    a store's product feed    (feeds/rows.py)       its gender field, its age group and its category
    a pasted product link     (collect/manual.py)   the folders of the link itself ("/damen/", "/kinder/": see
                                                    link_not_for_men), and, when the customer also gives the
                                                    page as he saved it, the page's breadcrumbs and what it says
                                                    the product is for

A product is refused only when those words say it is for women or for children. One that says it is for men,
for everyone ("unisex"), or says nothing at all is kept: Hirmer sells to men only and need not say so on every
product. The collector reads only the stores' men's category pages (config/stores.toml), so it has nothing to ask.
A pasted link whose folders say nothing, but whose product name holds such a word ("kids-hoodie", and
"beastie-boys-shirt" too), is not refused: the customer is asked whether to add it anyway (link_name_says).

    not_for_men("female")                                  -> "women"
    not_for_men("male", "kids")                            -> "children"
    not_for_men(None, None, "Damen > Jacken")              -> "women"
    not_for_men(None, None, "Damen & Herren > Mützen")     -> None      (for both: kept)
    not_for_men("unisex", None, "Damen > Mützen")          -> None      (the product's own word counts most)
    not_for_men("male", None, "Herren > Marken > Billionaire Boys Club")   -> None   (a brand's name, not a folder)
"""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import unquote, urlsplit

# Words as stores write them, in German, English, Dutch and French. A word in a tuple of beginnings also counts
# at the start of a longer word: "Herrenmode", "Menswear", "Damenjacken", "Womenswear", "Kinderschuhe".
_MEN = {"men", "mens", "man", "male", "homme", "hommes", "gentlemen", "unisex", "heren"}
_MEN_BEGIN = ("herren", "männer", "maenner", "manner", "männlich", "maennlich", "menswear")
_WOMEN = {"female", "ladies", "lady", "femme", "femmes", "feminin", "vrouwen"}
_WOMEN_BEGIN = ("dame", "women", "woman", "frau", "weiblich")
_CHILDREN = {"kids", "kid", "children", "child", "childrens", "boys", "boy", "girls", "girl", "junior", "juniors",
             "teen", "teens", "toddler", "toddlers", "infant", "infants", "newborn", "junge", "jungen", "jungs",
             "enfant", "enfants"}
_CHILDREN_BEGIN = ("kinder", "mädchen", "maedchen")
_BABY = {"baby", "babys", "babies"}       # in a link only as a folder of its own ("/baby/"): "baby-blue" is a colour there
# A gender field may hold one letter: "M", "W" (weiblich) or "F". Read only there, never in a category or a link.
_LETTERS = {"m": "men", "h": "men", "w": "women", "f": "women", "d": "women"}

WORDS = {"women": "a women's product", "children": "a children's product"}     # as a sentence names them

# A link's words are rougher than a feed's: a product's or a brand's name is in them too ("frau-holle-shirt",
# "billionaire-boys-club-hoodie", a "Beastie Boys" shirt, a "Kinder Bueno" one). So a link is refused only where
# the store itself says it plainly, and the customer is asked where only a name holds such a word:
#   refused (link_not_for_men): a folder of the link that holds nothing but such words, as before:
#     "/damen/", "/lady/", "/kids-boys/", "/Women-0002/", "/womenswear/", "/kindermode/", "/baby/"
#   asked "Add it anyway?" (link_name_says), when one of these stands anywhere else in the link:
#     a word for the group, as a word of its own, wherever it stands: "damen-slim-fit-jeans",
#       "patagonia-kids-down-sweater", "Girls+Elodie+Jacket", "mantel-fuer-jungen", "hoodie-kids",
#       "junior-steppjacke", and so "beastie-boys-shirt" too (_LINK_WOMEN, _LINK_CHILDREN)
#     a word for one person ("woman", "frau", "lady", "girl", "boy", "kid", "teen", "baby") right before a word
#       for clothes: "woman-coat", "girl-jacket", "teen-jacke", "baby-jacke"; "frau-holle-shirt", "lady-like-hemd",
#       "baby-blue-jacke" and "teen-spirit-jeans" say nothing (_LINK_ONE_WOMAN, _LINK_ONE_CHILD)
#     one word made of the group and the clothes: "damenjacke", "womenswear", "kindermode", "kidswear"
#       (_LINK_JOINED); "womensecret", "frauholle", "boyfriend", "damenhaft" say nothing
# A men's word anywhere in the link ("herren", "men") always keeps it, unasked. "unisex" keeps it from the women's
# question only: a "unisex-kids-hoodie" is for boys and girls, and is asked about.
_LINK_WOMEN = {"damen", "dames", "women", "womens", "frauen", "ladies", "female", "femme", "femmes", "vrouwen",
               "weiblich"}
_LINK_ONE_WOMAN = {"woman", "frau", "lady", "dame"}
_LINK_CHILDREN = {"kinder", "mädchen", "maedchen", "children", "childrens", "toddler", "toddlers", "enfant",
                  "enfants", "infant", "infants", "newborn", "kids", "boys", "girls", "jungen", "jungs", "junior",
                  "juniors", "teens"}
_LINK_ONE_CHILD = {"kid", "boy", "girl", "teen", "baby", "babys", "babies", "junge", "child"}
_LINK_JOINED = {"women": ("damen", "womens", "women", "frauen", "ladies"),
                "children": ("kinder", "mädchen", "maedchen", "jungen", "kids", "boys", "girls", "baby", "teen")}
# The beginnings of words for clothes, shoes and what a store calls them all ("mode", "wear"), German and English.
_CLOTHES = ("jacke", "jacket", "mantel", "coat", "parka", "anorak", "weste", "vest", "blazer", "sakko", "anzug", "suit",
            "hemd", "shirt", "tshirt", "bluse", "blouse", "polo", "pullover", "pulli", "sweat", "hoodie", "hoody",
            "strick", "knit", "cardigan", "jumper", "kleid", "dress", "skirt", "hose", "jeans", "chino", "trouser",
            "pants", "shorts", "legging", "jogg", "schuh", "shoe", "sneaker", "stiefel", "boots", "sandal", "trainer",
            "socke", "socks", "mütze", "muetze", "beanie", "schal", "scarf", "gürtel", "guertel", "handschuh",
            "glove", "wäsche", "waesche", "unterhose", "pyjama", "schlafanzug", "bademode", "badehose", "swim",
            "regen", "winter", "sommer", "daunen", "fleece", "overall", "mode", "wear", "fashion", "bekleidung",
            "kleidung", "clothing", "outfit")


def _is_clothes(word: str) -> bool:
    return word.startswith(_CLOTHES)


def _joined(word: str, group: str) -> bool:
    """One word made of a group and clothes: "damenjacke", "womenswear", "kinderschuhe"."""
    return any(word.startswith(begin) and _is_clothes(word[len(begin):]) for begin in _LINK_JOINED[group])


def _link_folder_says(folders: list[list[str]], group: str) -> bool:
    """Whether a folder of a link holds nothing but words for `group`, "women" or "children": "/damen/",
    "/kids-boys/", "/womenswear/". That is the store saying it plainly."""
    alone = _WOMEN | _LINK_WOMEN | _LINK_ONE_WOMAN if group == "women" else _CHILDREN | _BABY | set(_CHILDREN_BEGIN)
    return any(all(word in alone or _joined(word, group) for word in words) for words in folders)


def _link_name_word(folders: list[list[str]], group: str) -> str | None:
    """The word in a link's names that may say the product is for `group` ("kids", "damenjacke"), or None (the
    rule is above, at _LINK_WOMEN)."""
    anywhere, one = (_LINK_WOMEN, _LINK_ONE_WOMAN) if group == "women" else (_LINK_CHILDREN, _LINK_ONE_CHILD)
    for words in folders:
        # ("boys-t-shirt", "kid-s-jacket": a single letter is no word of its own)
        names = [word for word in words if len(word) > 1]
        for word, after in zip(names, names[1:] + [""]):
            if word in anywhere or _joined(word, group) or (word in one and _is_clothes(after)):
                return word
    return None


def _words(text: Any) -> list[str]:
    return re.findall(r"[a-zäöüß]+", str(text or "").lower().replace("’", "'").replace("'s", "s"))


def _says(words: list[str], whole: set[str], beginnings: tuple[str, ...]) -> bool:
    return any(word in whole or word.startswith(beginnings) for word in words)


def _folders(path: Any, link: bool) -> list[list[str]]:
    """The words of each step of a category ("Herren > Marken > Billionaire Boys Club") or of a link's path."""
    steps = re.split(r"/" if link else r"[>/|]", str(path or ""))
    return [words for words in map(_words, steps) if words]


def _filed_for_children(folders: list[list[str]], link: bool) -> bool:
    """Whether where a product is filed says children's. A children's word inside a brand's or a product's name
    says nothing: "Billionaire Boys Club", the skate brand "Girl", "Teen Spirit" jeans are for men. So:

        a category    its step must begin with the word: "Kinder", "Jungen > Jacken", "Kids & Teens", "Baby"
        a link        the folder must hold nothing else: "/kinder/", "/kids/", "/kids-boys/"
        either        a longer word beginning "kinder" or "mädchen" counts anywhere: "kindermode", "maedchen-kleid"
    """
    children = _CHILDREN if link else _CHILDREN | _BABY
    for words in folders:
        if _says(words, set(), _CHILDREN_BEGIN):
            return True
        if link and all(word in children for word in words):
            return True
        if not link and words[0] in children:
            return True
    return False


def not_for_men(gender: Any = None, age_group: Any = None, *paths: Any, link: bool = False) -> str | None:
    """"women" or "children" when these words say the product is for them, None when it may be menswear.

    `gender`: the product's own word for whom it is for ("male", "Damen", "weiblich", "W", "unisex").
    `age_group`: Google's ("adult", "kids", "toddler", "infant", "newborn"). `paths`: where the store files it,
    its category or breadcrumbs ("Herren > Hemden"). `link`: the words come from a web address.

    In this order: the product's own word or age group says children's: refused. Where it is filed says
    children's and nowhere men's: refused (a boys' jacket is "male" too, so "male" does not save it; "adult"
    does). Its own word says men's or unisex: kept. Its own word says women's: refused. Where it is filed says
    women's and nowhere men's: refused. Otherwise kept."""
    own, age = _words(gender), _words(age_group)
    letter = _LETTERS.get(own[0]) if len(own) == 1 else None
    folders = [folder for path in paths for folder in _folders(path, link)]
    filed = [word for folder in folders for word in folder]
    own_men = letter == "men" or _says(own, _MEN, _MEN_BEGIN)
    filed_men = _says(filed, _MEN, _MEN_BEGIN)
    if _says(own + age, _CHILDREN | _BABY, _CHILDREN_BEGIN):
        return "children"
    if link:        # only a link's words are known: a folder of it must say so (the rule is at _LINK_WOMEN)
        if filed_men:
            return None
        return next((group for group in ("children", "women") if _link_folder_says(folders, group)), None)
    if _filed_for_children(folders, link) and not filed_men and not (own_men and "adult" in age):
        return "children"
    if own_men:
        return None                     # the product's own word counts most, wherever the store files it
    if letter == "women" or _says(own, _WOMEN, _WOMEN_BEGIN):
        return "women"
    if _says(filed, _WOMEN, _WOMEN_BEGIN) and not filed_men:
        return "women"
    return None


def link_not_for_men(url: str) -> str | None:
    """What the folders of a product link say: "women" for ".../damen/jacken/...", "children" for ".../kinder/...".
    Such a link is refused. A word in the product's own name is not enough for that: see link_name_says.
    Only the path is read, never the store's name ("ladies-and-gentlemen.example") or what follows a "?".
    A men's word anywhere in the link wins: ".../herren/billionaire-boys-club-hoodie/..." is kept."""
    return not_for_men(None, None, unquote(urlsplit(url).path), link=True)


def link_name_says(url: str) -> tuple[str, str] | None:
    """A word in a product link's names that may say whom it is for, and for whom: ("kids", "children") for
    ".../patagonia-kids-down-sweater-123", ("damenjacke", "women") for ".../marke-damenjacke-123". None when no such
    word is there, or a men's word is anywhere in the link ("unisex" there answers only the women's question). A
    name alone is not reliable (".../beastie-boys-shirt" is a men's shirt), so such a link is not refused: the
    customer is asked whether to add it anyway (collect/manual.py)."""
    folders = _folders(unquote(urlsplit(url).path), True)
    words = [word for folder in folders for word in folder]
    if _says(words, _MEN - {"unisex"}, _MEN_BEGIN):
        return None
    for group in ("children",) if "unisex" in words else ("children", "women"):
        word = _link_name_word(folders, group)
        if word:
            return word, group
    return None


def filed_for_men(*paths: Any) -> bool:
    """Whether where a store files a product says men's: "Herren > Hemden", "Men / Jackets". Asked of the page a
    customer saved: then a word in the product's name ("Beastie Boys") needs no question. "Unisex" is not
    enough for that, since a children's product can be unisex too."""
    filed = [word for path in paths for folder in _folders(path, False) for word in folder]
    return _says(filed, _MEN - {"unisex"}, _MEN_BEGIN)
