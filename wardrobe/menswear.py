"""Stilsmith is for men: which products are menswear, decided in this one place. There is no switch.

Every way a product comes in asks here:

    a store's product feed    (feeds/rows.py)       its gender field, its age group and its category
    a pasted product link     (collect/manual.py)   the words of the link itself ("/damen/", "/kinder/"), and,
                                                    when the customer also gives the page as he saved it, the
                                                    page's breadcrumbs and what it says the product is for

A product is refused only when those words say it is for women or for children. One that says it is for men,
for everyone ("unisex"), or says nothing at all is kept: Hirmer sells to men only and need not say so on every
product. The collector reads only the stores' men's category pages (config/stores.toml), so it has nothing to ask.

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
_BABY = {"baby", "babys", "babies"}       # not read from a link: "baby-blue" is a colour there
# A gender field may hold one letter: "M", "W" (weiblich) or "F". Read only there, never in a category or a link.
_LETTERS = {"m": "men", "h": "men", "w": "women", "f": "women", "d": "women"}

WORDS = {"women": "a women's product", "children": "a children's product"}     # as a sentence names them


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
    """What a product link's own words say: "women" for ".../damen/jacken/...", "children" for ".../kinder/...".
    Only the path is read, never the store's name ("ladies-and-gentlemen.example") or what follows a "?".
    A men's word anywhere in the link wins: ".../herren/billionaire-boys-club-hoodie/..." is kept."""
    return not_for_men(None, None, unquote(urlsplit(url).path), link=True)
