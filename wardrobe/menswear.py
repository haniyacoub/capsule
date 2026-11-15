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
"""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import unquote, urlsplit

# Words as stores write them, in German, English and French. A word in a tuple of beginnings also counts at the
# start of a longer word: "Herrenmode", "Damenjacken", "Kinderschuhe".
_MEN = {"men", "mens", "man", "male", "homme", "hommes", "gentlemen", "unisex"}
_MEN_BEGIN = ("herren", "männer", "maenner", "manner")
_WOMEN = {"women", "womens", "woman", "female", "ladies", "lady", "femme", "femmes", "frau", "frauen", "dame"}
_WOMEN_BEGIN = ("damen",)
_CHILDREN = {"kids", "kid", "children", "child", "childrens", "boys", "boy", "girls", "girl", "junior", "juniors",
             "teen", "teens", "toddler", "toddlers", "infant", "infants", "newborn", "junge", "jungen", "jungs",
             "enfant", "enfants"}
_CHILDREN_BEGIN = ("kinder", "mädchen", "maedchen")
_BABY = {"baby", "babys", "babies"}       # not read from a link: "baby-blue" is a colour there

WORDS = {"women": "a women's product", "children": "a children's product"}     # as a sentence names them


def _words(text: Any) -> list[str]:
    return re.findall(r"[a-zäöüß]+", str(text or "").lower().replace("’", "'").replace("'s", "s"))


def _says(words: list[str], whole: set[str], beginnings: tuple[str, ...]) -> bool:
    return any(word in whole or word.startswith(beginnings) for word in words)


def not_for_men(gender: Any = None, age_group: Any = None, *paths: Any, link: bool = False) -> str | None:
    """"women" or "children" when these words say the product is for them, None when it may be menswear.

    `gender`: the product's own word for whom it is for ("male", "Damen", "unisex"). `age_group`: Google's
    ("adult", "kids", "toddler", "infant", "newborn"). `paths`: where the store files it, its category or
    breadcrumbs ("Herren > Hemden"). `link`: the words come from a web address, where "baby" may be a colour."""
    own, age = _words(gender), _words(age_group)
    filed = [word for path in paths for word in _words(path)]
    children = _CHILDREN if link else _CHILDREN | _BABY
    if _says(own + age + filed, children, _CHILDREN_BEGIN):
        return "children"
    if _says(own, _MEN, _MEN_BEGIN):
        return None                     # the product's own word counts most, wherever the store files it
    if _says(own, _WOMEN, _WOMEN_BEGIN):
        return "women"
    if _says(filed, _WOMEN, _WOMEN_BEGIN) and not _says(filed, _MEN, _MEN_BEGIN):
        return "women"
    return None


def link_not_for_men(url: str) -> str | None:
    """What a product link's own words say: "women" for ".../damen/jacken/...", "children" for ".../kinder/...".
    Only the path is read, never the store's name ("ladies-and-gentlemen.example") or what follows a "?"."""
    return not_for_men(None, None, unquote(urlsplit(url).path), link=True)
