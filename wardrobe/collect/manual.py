"""Manual import: you paste a product link, the tool takes what the link says.

The page itself is never opened: COS and Weekday refuse automated browsers on
product pages, and a server never opens a store's page at all. The tool takes
what the link says (store, product name, colour, article number) and, if that
article was seen on a category page during a refresh, copies its name, price,
colour and picture. Whatever is still missing you type in on the piece's page.

With one link you may also send the product's page as you saved it from your
own browser ("Save page as"). Then its name, price, colour and fabric are read
from that file, where it states them, by the generic reader (generic.py),
which works for any store. Pasting a link again never wipes what was known
about it: what the saved page gave, or what was typed in, is kept.
Stilsmith still asks the store nothing. The photo is never taken from it.

Only links to stores customers are offered are taken (programmes.py): a link
to a store without a partner programme, such as Zara, is refused. So is a link
to a store the customer unticked on Profile (profile.stores): his pieces are
not picked from it, and what he added from it would not be shown. The stores
that have no products yet (Tom Tailor, OTTO, Hirmer and the others without
category pages in config/stores.toml) are served by this alone.

Menswear only (menswear.py): a link whose folders say women's or children's
("/damen/", "/kinder/"), or whose saved page says so in its breadcrumbs, is
refused with a sentence saying why. Where only the product's name in the link
holds such a word ("kids-hoodie", but "beastie-boys-shirt" too), the link is
not refused: it is not added yet, and the customer is asked "Add it anyway?"
(a Question below), with one button that adds it. He is not asked when the
page he saved shows the store filing the product under men's.

The kind of garment is not checked hard, because a name read from a link is
too rough for a refusal: a link whose name plainly says another kind (a shirt
pasted on the coat) is added, and the answer says so and how to move it.

What happened to each link is said to the customer after the product's name
("Added “X”: only the link could be read …") or after the link itself ("Not
added: “link” is not a COS or Weekday link."), so the notes below read on from those.
"""
from __future__ import annotations

import hashlib
import re
from urllib.parse import urlsplit

from .. import capsule, catalog, composition, menswear, profile, programmes
from ..garments import GARMENTS
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


def _article(url: str) -> str:
    """The product's article number as its link gives it, which tells two products of one store apart.
    COS ends a link "…-black-4100000902", Zara "…-p01234567", others "…/p/1001234567/". Tom Tailor ends one
    "…-1041234_10668", article then colour: both are taken ("1041234-10668"), because the colour's number alone
    is the same for every product in that colour. A link without a number is told apart by the whole link."""
    path = urlsplit(url).path
    last = re.sub(r"\.html?$", "", path.rstrip("/").rsplit("/", 1)[-1])
    number = (re.search(r"(\d{7,13})$", last) or re.search(r"p(\d{8})", last)
              # else the path's last long number, with the shorter numbers joined to it by "_"
              or re.search(r"(\d{5,13}(?:_\d+)*)(?!.*\d{5})", path))
    if number:
        return number.group(1).replace("_", "-")
    return hashlib.sha1(url.encode(), usedforsecurity=False).hexdigest()[:10]


def _knows_more(cand: dict) -> bool:
    """Whether a product he pasted before holds more than its link says: a price, a fabric, a colour, sizes,
    from the page he saved or typed in under "Add details"."""
    return bool(cand.get("price", 0) > 0 or cand.get("composition_text") or cand.get("colour")
                or cand.get("sizes_in_stock") or cand.get("manual"))


def _from_link_alone(url: str, store: str, slot: dict, known: list[dict]) -> tuple[dict, str]:
    """What a link says by itself, plus anything a refresh already saw for that article."""
    from ..settings import SITE_NAME            # the product's name, for the note below
    slug = _slug(url)
    sku = _article(url)
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
    """'looks like a women's product, and Stilsmith is for menswear only': why a link was not added. "Looks like":
    it is read from the link's folders or the saved page's words, where a brand's name can be mistaken for one."""
    from ..settings import SITE_NAME
    return f"looks like {menswear.WORDS[whom]}, and {SITE_NAME} is for menswear only"


class Question(str):
    """What is asked about a link that was not added yet, in place of a reason why it was refused: "Its name says
    “kids”: this may be a children's product. Add it anyway?". The page shows it with a button that pastes the
    link again with the answer yes (app.slot_import, `anyway`)."""


def _name_asks(url: str, word: str, whom: str, page: bool) -> Question:
    """The question about a link whose name holds a word such as "kids" or "damen" (menswear.link_name_says).
    "Its name says": the word is in the part of the link that names the product; else "Its link says".
    `page`: he sent the saved page along, which is not kept while he is asked."""
    in_name = menswear.link_name_says("/" + _slug(url))
    where = "name" if in_name and in_name[0] == word else "link"
    again = " The page you saved was not kept: once the link is added, send it again with the link." if page else ""
    return Question(f"is not added yet. Its {where} says “{word}”: this may be {menswear.WORDS[whom]}. "
                    f"Add it anyway?{again}")


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
    listed = lambda words: ", ".join(words[:-1]) + " and " + words[-1] if len(words) > 1 else words[0]  # noqa: E731
    typed = cand.get("manual") or {}
    missing = [word for word, there in (
        ("price", cand.get("price", 0) > 0 or typed.get("price")),
        ("fabric", cand.get("composition_text") or typed.get("composition_text")),
        ("sizes", cand.get("sizes_in_stock") or typed.get("sizes_in_stock"))) if not there]
    if not missing:
        return f"its {listed(read)} {'was' if len(read) == 1 else 'were'} read from the page you saved"
    return (f"its {listed(read)} {'was' if len(read) == 1 else 'were'} read from the page you saved — add the "
            f"{listed(missing)} under “Add details”")


def _another_kind(cand: dict, slot: dict) -> str:
    """A sentence to add when the product's name says another kind of garment than the piece it was pasted on:
    an "Oxford-Hemd" on the coat. Said, never refused: names from links are rough. Only when the name says a kind
    worn elsewhere on the body (a shirt on a coat, jeans on a jumper), and holds no word for the piece's own kind
    ("Jeansjacke" on a jacket says nothing). "Jeans" and "denim" at the start of a longer word are the cloth, not
    the kind: a "Jeansjacke" is a jacket (nothing to say on the coat), a "Jeanshemd" a shirt. And "denim" alone
    is only the cloth ("Denim Trucker"): nothing is said for it, the name must say "jeans" to be called jeans."""
    mine = GARMENTS.get(slot.get("category", ""))
    text = f"{cand.get('name', '')} {cand.get('slug', '')}"
    said = GARMENTS.get(capsule.detect_garment(text) or "")
    if said is not None and said.key == "jeans":
        letter = "a-zäöüß"
        rest = re.sub(rf"(?i)(?<![{letter}])(?:jeans|denim)(?=[{letter}])", "", text)
        said = GARMENTS.get(capsule.detect_garment(rest) or "") or said
        if said.key == "jeans" and not re.search(rf"(?i)(?<![{letter}])jeans(?![{letter}])", text):
            return ""
    if mine is None or said is None or said.layer == mine.layer:
        return ""
    low = re.sub(r"[-_+]", " ", text.lower())
    if any(word in low for word in capsule.garment_words(mine.key)):
        return ""
    return (f". Check the kind: its name says “{said.label}”, and this piece is “{mine.label}”. If it belongs to "
            "another piece, remove it here and paste the link there")


def from_urls(urls: list[str], slot: dict, page: str | None = None,
              anyway: bool = False) -> list[tuple[str, dict | None, str]]:
    """One (link, candidate or None, what happened) per pasted link. No page is ever opened.
    `page`: the HTML of the product's page as the customer saved it, read for one link only.
    `anyway`: he was asked about these links ("Add it anyway?") and said yes. A link he is asked about comes back
    without a candidate, and what happened is a Question."""
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
        # Only the product's name in the link holds a word such as "kids" or "damen": not refused, asked about
        # once. Not again after his yes, nor for a product he already added to this piece, nor where the page he
        # saved shows the store filing it under men's ("Herren > Hemden"): then the store has said it plainly.
        filed_men = menswear.filed_for_men(" > ".join(said.get("breadcrumbs", [])), said.get("category")) if said else False
        asked = None if anyway or filed_men else menswear.link_name_says(url)
        mine_already = any(c.get("id") == stub["id"] and c.get("slot_id") == slot["id"] and c.get("source") == "manual"
                           for c in known)
        if asked and not mine_already:
            results.append((url, None, _name_asks(url, *asked, page=bool(page and len(urls) == 1))))
            continue
        # Pasted on this piece before, and more is known about it than a link says (from the page he saved then,
        # or typed in): that is kept, not wiped by pasting the link again.
        before = next((c for c in known if c.get("id") == stub["id"] and c.get("slot_id") == slot["id"]
                       and c.get("source") == "manual" and _knows_more(c)), None)
        kept = before is not None and stub.get("price", 0) <= 0      # a product a refresh saw is better still
        if before is not None and kept:
            stub = {**before, "url": url, "collected_at": catalog.now_iso()}
            note = "you added this link before, and what was known about it was kept"
            if said and page and len(urls) == 1 and any(said.get(k) for k in ("name", "price", "colour", "material")):
                note = _from_saved_page(stub, said)
        elif said is None:
            note += ". The page you saved is not this store's, so it was not read"
        elif page and len(urls) == 1 and stub.get("price", 0) <= 0:   # what the list already had is better
            note = _from_saved_page(stub, said)
        if said is None and kept:
            note += ". The page you saved is not this store's, so it was not read"
        if page and len(urls) > 1:
            note += ". The saved page was not read: send it with one link at a time"
        results.append((url, stub, note + _another_kind(stub, slot)))
    return results
