"""Manual import: you paste a product link, the tool takes what the link says.

The page itself is never opened: COS and Weekday refuse automated browsers on
product pages, and a server never opens a store's page at all. The tool takes
what the link says (store, product name, colour, article number) and, if that
article was seen on a category page during a refresh, copies its name, price,
colour and picture. Whatever is still missing you type in on the piece's page.

With one link you may also send the product's page as you saved it from your
own browser ("Save page as"). Then its name, price, colour and fabric are read
from that file by the generic reader (generic.py), which works for any store.
Stilsmith still asks the store nothing. The photo is never taken from it.

Only links to stores customers are offered are taken (programmes.py): a link
to a store without a partner programme, such as Zara, is refused. So is a link
to a store the customer unticked on Profile (profile.stores): his pieces are
not picked from it, and what he added from it would not be shown. The stores
that have no products yet (Tom Tailor, OTTO, Hirmer and the others without
category pages in config/stores.toml) are served by this alone.

Menswear only (menswear.py): a link whose own words say women's or children's
("/damen/", "/kinder/"), or whose saved page says so in its breadcrumbs, is
refused with a sentence saying why.

What happened to each link is said to the customer after the product's name
("Added “X”: only the link could be read …") or after the link itself ("Not
added: “link” is not a COS or Weekday link."), so the notes below read on from those.
"""
from __future__ import annotations

import hashlib
import re
from urllib.parse import urlsplit

from .. import catalog, composition, menswear, profile, programmes
from . import generic, load_settings, pages


def hosts() -> dict[str, str]:
    """{'cos.com': 'cos', 'weekday.com': 'weekday'}: the web addresses of the stores customers are offered and the
    customer ticked (profile.stores), from each store's `base` in config/stores.toml."""
    cfg = load_settings()
    out = {}
    for key in profile.stores():
        host = urlsplit(str(cfg.get(key, {}).get("base", ""))).netloc.lower().removeprefix("www.")
        if host:
            out[host] = key
    return out


def store_of(url: str) -> str | None:
    parts = urlsplit(url.strip())
    if parts.scheme not in ("http", "https"):
        return None
    host = parts.netloc.lower().split(":")[0]
    return next((key for domain, key in hosts().items() if host == domain or host.endswith("." + domain)), None)


# Parts of a link that are not the product's name: "/p/", "/product/", "/de-de/", "/herren/", "index.html".
_NOT_A_NAME = re.compile(r"(?:p|pd|pdp|product|products|produkt|produkte|artikel|item|shop|index|[a-z]{2}(?:[-_][a-z]{2})?)")
# A word of a link that is an article number, not a word of the name: "4100000902", "p01234567", "C1689044821",
# "1041234_10668" (anything with a digit in it).
_NUMBER = re.compile(r".*\d.*")


def _slug(url: str) -> str:
    """The part of a link that names the product: its last part with a word in it. COS ends a link
    "…/product/brushed-merino-jumper-black-4100000902", others "…/oxford-hemd-hellblau/p/1001234567/" or
    "…/p/regular-fit-hemd-C1689044821/": a part that is only a number, or only "p" or "product", is passed over."""
    parts = [re.sub(r"\.html?$", "", part) for part in urlsplit(url).path.split("/") if part]
    for part in reversed(parts):
        if re.search(r"[a-zA-Z]{3}", part) and not _NOT_A_NAME.fullmatch(part.lower()):
            return part
    return parts[-1] if parts else ""


def _from_link_alone(url: str, store: str, slot: dict, known: list[dict]) -> tuple[dict, str]:
    """What a link says by itself, plus anything a refresh already saw for that article."""
    from ..settings import SITE_NAME            # the product's name, for the note below
    last = re.sub(r"\.html?$", "", urlsplit(url).path.rstrip("/").rsplit("/", 1)[-1])
    slug = _slug(url)
    number = (re.search(r"(\d{7,13})$", last) or re.search(r"p(\d{8})", last)
              or re.search(r"(\d{5,13})(?!.*\d{5})", urlsplit(url).path))     # else the path's last long number
    sku = number.group(1) if number else hashlib.sha1(url.encode(), usedforsecurity=False).hexdigest()[:10]
    # Seen by a refresh, that is: not what he pasted himself before, which knew no more than this link does.
    seen = next((c for c in known if c.get("store") == store and c.get("id") == f"{store}-{sku}"
                 and c.get("source") != "manual"), None)
    if seen:
        cand = {k: v for k, v in seen.items() if k != "manual"}
        cand.update(slot_id=slot["id"], source="manual", url=url, collected_at=catalog.now_iso())
        return cand, f"its name, price, colour and picture were already in {SITE_NAME}'s product list"

    # The article number is not part of the name: COS ends a link "…-black-4100000902", Zara "…-p01234567"
    # (without the "-p" too, the name of "stiefel-aus-leder-p01234567" would be "Stiefel aus leder p"), OTTO
    # "…-C1689044821", Tom Tailor "…-1041234_10668": the words with a digit at the end of the name are left off.
    parts = [word for word in re.split(r"[-_+ ]+", slug) if word]
    while parts and _NUMBER.fullmatch(parts[-1]):
        parts.pop()
    words = " ".join(parts)
    cand = {
        "id": f"{store}-{sku}", "slot_id": slot["id"], "store": store,
        "name": words[:1].upper() + words[1:] if words else "Product", "slug": slug,
        "price": 0.0, "currency": "EUR", "colour": "", "colour_hex": None,
        "composition_text": "", "fit": pages.fit_from(words), "description": "",
        "sizes_all": [], "sizes_in_stock": [], "url": url, "image_url": "",
        "source": "manual", "collected_at": catalog.now_iso(),
    }
    return cand, "only the link could be read — add the price, fabric and sizes under “Add details”"


def _not_menswear(whom: str) -> str:
    """'is a women's product, and Stilsmith is for menswear only': why a link was not added."""
    from ..settings import SITE_NAME
    return f"is {menswear.WORDS[whom]}, and {SITE_NAME} is for menswear only"


def _from_saved_page(cand: dict, info: dict) -> str:
    """Fill a product added by its link with what its saved page says (generic.read), and say what was read.
    Never the photo: a store's photo needs that store's licence."""
    read = []
    if info.get("name"):
        cand["name"], cand["fit"] = pages.tidy_name(info["name"]), pages.fit_from(info["name"])
        read.append("name")
    if info.get("price"):
        cand["price"], cand["currency"] = info["price"], info.get("currency") or "EUR"
        read.append("price")
    if info.get("colour"):
        cand["colour"] = info["colour"]
        read.append("colour")
    if info.get("material") and composition.parse(info["material"]):
        cand["composition_text"] = info["material"]
        read.append("fabric")
    if not read:
        return "the page you saved says nothing about the product, so only the link could be read — add the " \
               "price, fabric and sizes under “Add details”"
    missing = [word for word in ("price", "fabric") if word not in read] + ["sizes"]
    listed = lambda words: ", ".join(words[:-1]) + " and " + words[-1] if len(words) > 1 else words[0]  # noqa: E731
    return (f"its {listed(read)} {'was' if len(read) == 1 else 'were'} read from the page you saved — add the "
            f"{listed(missing)} under “Add details”")


def from_urls(urls: list[str], slot: dict, page: str | None = None) -> list[tuple[str, dict | None, str]]:
    """One (link, candidate or None, what happened) per pasted link. No page is ever opened.
    `page`: the HTML of the product's page as the customer saved it, read for one link only."""
    known = catalog.load().get("candidates", [])
    mine = list(hosts().values())
    # "is not a COS or Weekday link"; with more stores than a sentence holds, the form's own list is pointed to.
    not_ours = f"is not a {programmes.names(mine, last='or')} link" if len(mine) <= 3 \
        else "is not a link to one of the stores listed above"
    info = generic.read(page) if page and len(urls) == 1 else {}
    results: list[tuple[str, dict | None, str]] = []
    for url in urls:
        store = store_of(url)
        if store is None:
            results.append((url, None, not_ours))
            continue
        # The page he saved must be this store's: its own address, where it gives a whole one, says whose it is.
        address = str(info.get("address", ""))
        theirs = store_of(address) if address.startswith(("http://", "https://")) else store
        said = info if theirs == store else None
        whom = menswear.link_not_for_men(url) or (menswear.not_for_men(
            said.get("gender"), None, " > ".join(said.get("breadcrumbs", [])), said.get("category")) if said else None)
        if whom:
            results.append((url, None, _not_menswear(whom)))
            continue
        stub, note = _from_link_alone(url, store, slot, known)
        if said is None:
            note += ". The page you saved is not this store's, so it was not read"
        elif page and len(urls) == 1 and stub.get("price", 0) <= 0:   # what the list already had is better
            note = _from_saved_page(stub, said)
        if page and len(urls) > 1:
            note += ". The saved page was not read: send it with one link at a time"
        results.append((url, stub, note))
    return results
