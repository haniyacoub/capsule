"""Which reader reads a store's category page, and reading one page with it.

COS and Weekday have readers of their own (cos.py, weekday.py), written for the JSON their pages embed, and Pull&Bear
one for the product data its page fetches (pullandbear.py). Every other
store is read by the generic listing reader (listing.py), from the page as a visitor's browser shows it: after it has
loaded, scrolled a few screens where the list grows, with the JSON the page itself fetched (Session.fetch_listing).

Two things a category page can do besides showing products:
  * open another page instead, most often the store's home page (a category that moved), or another category
    beside it: that page is skipped and named in the run's report as an address to fix (Moved);
  * come back almost empty, with no products: where a category page was expected, that is a check page for automated
    browsers (OTTO sent 819 bytes, adidas a 4 KB page in the probe of 22 Nov 2026), so the store is stopped there, as
    for any other refusal (Blocked). Nothing is retried;
  * say "page not found" in an ordinary page (some stores answer a wrong address that way, not with a 404): an
    address to fix (PageMissing), as a 404 is.
"""
from __future__ import annotations

import re
from types import ModuleType
from urllib.parse import urlsplit

from . import cos, listing, pullandbear, weekday
from .browser import Blocked, PageMissing, Session

OWN: dict[str, ModuleType] = {"cos": cos, "weekday": weekday, "pull-and-bear": pullandbear}

# A category page with no products and less HTML than this is a check page, not a category page.
TINY = 12_000
# What a store's "page not found" says, where it answers with an ordinary page instead of a 404 (Carhartt WIP and
# OLYMP do): an address to fix, not a refusal.
NOT_FOUND = re.compile(r"seite wurde (leider )?nicht gefunden|seite konnte nicht gefunden werden|seite nicht gefunden|"
                       r"page not found|<title>[^<]*(not found|404)[^<]*</title>", re.I)


class Moved(Exception):
    """The address opened another page (most often the store's home page): the category moved."""

    def __init__(self, url: str, landed: str):
        super().__init__(f"{url} opened {landed}")
        self.url, self.landed = url, landed


def reader(key: str) -> ModuleType:
    """The module that reads this store's category pages: its own, or the generic listing reader."""
    return OWN.get(key, listing)


def moved(url: str, landed: str) -> bool:
    """Whether opening `url` ended on another page than the category asked for: the store's home page, a folder
    above it, or another category beside it (a page can also change its own address as it loads: one asked for
    oversize shirts ended on the store's T-shirts, and its products would have been sorted as shirts). The same page
    with a slash more or less, in other capitals, with a query, below a language folder ("/de_de/…") or a page below
    it is not a move."""
    if not landed or landed == url:
        return False
    asked = urlsplit(url).path.rstrip("/").lower()
    got = urlsplit(landed).path.rstrip("/").lower()
    return not (got == asked or got.startswith(asked + "/") or (asked and got.endswith(asked)))


def read_page(session: Session, key: str, base: str, url: str, module: ModuleType,
              first: bool = True) -> tuple[list[dict], str]:
    """The products on one category page, and the page's HTML (for the address of its next page). `first`: the
    first page of a category (later pages are its ?page=2 and so on)."""
    if module is not listing and not getattr(module, "NEEDS_FETCHED", False):
        html = session.fetch(key, base, url)
        return module.parse_listing(html, base), html
    html, fetched, landed = session.fetch_listing(key, base, url)
    if first and moved(url, landed):
        raise Moved(url, landed)
    items = module.parse_listing(html, base, fetched, key)
    if not items and NOT_FOUND.search(html):
        raise PageMissing(url)
    if not items and len(html) < TINY:
        raise Blocked(key, url, "the store sent an almost empty page where its category page was expected "
                                "(a check for automated browsers)")
    return items, html
