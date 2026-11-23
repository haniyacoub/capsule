"""Pool mode: every plain product on a store's category pages, for the list every customer's products come from.

    python -m wardrobe refresh --pool                    every store with category pages
    python -m wardrobe refresh --pool --store hm         one store (repeatable)

The ordinary refresh (collect/__init__.py) keeps the few products that fit each of YOUR pieces. A service with many
customers needs more than that: every plain product a store's category pages show, in every colour, so that each
customer's pieces find theirs among them (shared.candidates_for). This reads, for each chosen store and each garment
type it has pages for, the same category pages (config/stores.toml, and the addresses kept on this computer in
config/collect.local.toml), in the same browser session and with the same politeness: robots.txt first, a pause of a
few seconds between two pages of one store, at most `max_listing_pages` pages of one category, and a stop at the
store's first refusal. Nothing is retried or disguised.

Each product is sorted into exactly one garment type, by the page it came from and its name. Some garments share
pages (trousers, chinos and cargo trousers; T-shirts and long-sleeve tees; coats, jackets and overshirts; shirts and
overshirts): there the words of each garment decide ([<store>.garments.<garment>] include and exclude, or the general
[collector.garment_rules] when the store names none). A product that fits no garment, or two, is left out and
counted, as are patterned ones and multipacks (skip_words), sold-out ones, those without a price, and a second
listing of one product (the same link and colour: distinct).

What it keeps goes into data/pool.json, in the shape of the shared list (shared.py), merged per store: a store
collected again replaces its own products, and the other stores' products stay exactly as they were. What the fabric
pass read from a product's own page (fabric.py) is kept when its store is collected again. `python -m wardrobe
publish` copies the pool into a service's store_catalog.json. Each run prints, and writes to data/pool-report.txt,
per store and garment: the products kept, their prices and colours, how many state their fabric, and the ones left
out, with a few examples.

For your own machine and for testing only, as the ordinary refresh: run by hand, never on a schedule.
"""
from __future__ import annotations

import functools
import json
import os
import re
from collections import Counter
from pathlib import Path

from .. import catalog, colours, composition, paths
from ..garments import GARMENTS
from . import listing, load_settings, matching, pages, readers
from .browser import Blocked, BrowserClosed, LimitReached, NotAllowed, PageMissing, Session

POOL_NAME = "pool.json"
REPORT_NAME = "pool-report.txt"

# Why a product on a category page was left out of the pool.
NOT_PLAIN = "patterned, a multipack or cropped"
NOT_EVERYDAY = "sportswear, underwear or a logo line"
ANOTHER_BRAND = "another brand's, sold there too"
NO_GARMENT = "fits no garment"
TWO_GARMENTS = "fits two garments"
SOLD_OUT = "sold out"
NO_PRICE = "no price or link"
TWICE = "listed twice (the same link and colour)"
LEFT_OUT = (NO_GARMENT, TWO_GARMENTS, NOT_PLAIN, NOT_EVERYDAY, ANOTHER_BRAND, SOLD_OUT, NO_PRICE, TWICE)

# What the fabric pass (fabric.py) adds to a product, carried over when its store is collected again.
FROM_ITS_PAGE = ("composition_text", "fabric_from", "page_read_at")


def pool_path() -> Path:
    return paths.DATA_DIR / POOL_NAME


def report_path() -> Path:
    return paths.DATA_DIR / REPORT_NAME


def empty() -> dict:
    return {"collected_at": None, "stores": {}, "products": []}


def load() -> dict:
    """The pool on this computer (data/pool.json), or an empty one."""
    try:
        with pool_path().open(encoding="utf-8") as f:
            pool = json.load(f)
    except FileNotFoundError:
        return empty()
    pool.setdefault("stores", {})
    pool.setdefault("products", [])
    return pool


def save(pool: dict) -> None:
    """Write atomically, so a crash mid-write cannot leave half a file."""
    path = pool_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(pool, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)


# ── which garment a product is ───────────────────────────────────────────────

def pages_of(store: dict) -> dict[str, list[str]]:
    """Each category page of a store and the garment types it is listed for, in the file's order:
    {'/men/trousers': ['trousers', 'chinos', 'cargo'], …}. Garment types the app does not know are skipped."""
    out: dict[str, list[str]] = {}
    for garment, rules in (store.get("garments") or {}).items():
        if garment not in GARMENTS:
            continue
        for path in (rules or {}).get("pages", []):
            listed = out.setdefault(path, [])
            if garment not in listed:
                listed.append(garment)
    return out


def rules_of(store: dict, garment: str, settings: dict) -> dict:
    """The words that decide whether a product is this garment: the store's own include and exclude
    ([<store>.garments.<garment>]) where it gives either, else the general ones ([collector.garment_rules.<garment>]).
    `page_decides` (general rules only): on a page listed for this garment alone, its `include` words are not needed
    (a long-sleeve page's "Nordfaden T-Shirt 4711" is a long-sleeve tee); its `exclude` words still count."""
    own = (store.get("garments") or {}).get(garment) or {}
    general = "include" not in own and "exclude" not in own
    if general:
        own = (settings.get("garment_rules") or {}).get(garment) or {}
    return {"include": [w.lower() for w in own.get("include", [])],
            "exclude": [w.lower() for w in own.get("exclude", [])],
            "page_decides": general and own.get("page_decides") is True}


@functools.lru_cache(maxsize=None)
def _word(word: str) -> re.Pattern:
    return re.compile((r"(?<![^\W_])" if word.startswith(" ") else "") + re.escape(word.strip())
                      + (r"(?![^\W_])" if word.endswith(" ") else ""))


def has(text: str, words) -> bool:
    """Whether a product's name and link (matching.text_of) hold one of these words. A word is found anywhere,
    inside other words too, as German makes one word of several ("Wollmantel", "Poloshirt", "Strickjacke"), except
    at an edge it marks with a space: a space before it, and it must start a word (" t-shirt" is not the end of
    "draft-shirt"); a space after it, and it must end one ("coat " is not the start of "Coating"). A space, a
    hyphen, a slash, the start and the end of the text are all edges of a word."""
    return any(_word(word).search(text) for word in words)


def _accepts(text: str, rules: dict, alone: bool = False) -> bool:
    include, exclude = rules["include"], rules["exclude"]
    if include and not (alone and rules.get("page_decides")) and not has(text, include):
        return False
    return not has(text, exclude)


def words_of(store: dict, settings: dict) -> dict:
    """The words that leave a store's products out: `skip` (patterns, multipacks: [collector] skip_words),
    `not_everyday` (sportswear, underwear, logo lines: [collector] pool_skip_words, and the store's own skip_words
    in config/collect.local.toml), and `own_brands` (a store that also sells other brands' products, as H&M sells
    COS's: only its own brands are kept, where the page names the brand)."""
    return {"skip": [w.lower() for w in settings.get("skip_words", [])],
            "not_everyday": [w.lower() for w in settings.get("pool_skip_words", []) + store.get("skip_words", [])],
            "own_brands": {w.strip().lower() for w in store.get("own_brands", [])}}


def judge(item: dict, garments, rules: dict[str, dict], words: dict) -> tuple[str | None, str]:
    """(the one garment type this product is, "") or (None, why it is left out): no price or link, sold out,
    another brand's, not plain, not everyday wear, or no garment or two (sort). `garments`: the garment types of
    the pages it was seen on; `words`: words_of. The same for a product just read and for one sorted again."""
    if item.get("price") is None or not item.get("url") or not item.get("name"):
        return None, NO_PRICE
    if item.get("in_stock") is False:
        return None, SOLD_OUT
    brand = str(item.get("brand") or "").strip().lower()
    if brand and words["own_brands"] and brand not in words["own_brands"]:
        return None, ANOTHER_BRAND
    return sort(item, [g for g in GARMENTS if g in garments], rules, words["skip"], words["not_everyday"])


def sort(item: dict, garments: list[str], rules: dict[str, dict], skip_words: list[str],
         not_everyday: list[str] | tuple = ()) -> tuple[str | None, str]:
    """(the one garment type this product is, "") or (None, why it was left out). `garments`: the garment types of
    the pages it was seen on; `rules`: each one's words (rules_of). A pattern its colour names ("Weiß/Gestreift")
    leaves it out as its name would: no piece's colour ever matches it (matching.colour_level). So does a print its
    colour names (printed_colour)."""
    text = matching.text_of(item)
    colour = str(item.get("colour") or "").lower()
    if has(text, skip_words) or any(word.strip() in colour for word in skip_words) or printed_colour(colour):
        return None, NOT_PLAIN
    if has(text, not_everyday):
        return None, NOT_EVERYDAY
    alone = len(garments) == 1
    fits = [garment for garment in garments if _accepts(text, rules[garment], alone)]
    if len(fits) == 1:
        return fits[0], ""
    return None, NO_GARMENT if not fits else TWO_GARMENTS


def printed_colour(colour: str) -> bool:
    """Whether a colour names a print beside its colour: a part of it between slashes that names no colour Stilsmith
    knows ("Schwarz/Nordlicht Club", "Weiß/Musterband Originals"). Two colours ("Schwarz/Weiß", "Black / Dk Slate
    Grey") are not a print."""
    parts = [part for part in str(colour or "").split("/") if part.strip()]
    return len(parts) > 1 and not all(any(colours.find(word) for word in re.findall(r"[^\W\d_]+", part))
                                      for part in parts)


def product(item: dict, garment: str, stamp: str) -> dict:
    """A product of the pool, in the shape of the shared list (shared.py), from a product on a category page."""
    fabric = str(item.get("composition_text") or "")
    out = {
        "id": f"{item['store']}-{listing.article(item['sku'], item['url'])}",
        "store": item["store"],
        "category": garment,
        "name": item["name"],
        "slug": item.get("slug", ""),
        "price": item["price"],
        "price_before": item.get("price_before"),
        "currency": "EUR",
        "colour": item.get("colour", ""),
        "colour_hex": item.get("colour_hex"),
        "composition_text": fabric,
        "fit": pages.fit_from(f"{item['name']} {item.get('slug', '')}"),
        "description": "",
        "sizes_all": item.get("sizes_all", []),
        "sizes_in_stock": item.get("sizes_in_stock", []),
        "url": item["url"],
        "image_url": item.get("image_url", ""),
        "source": "collected",
        "collected_at": stamp,
    }
    if fabric:
        out["fabric_from"] = "listing"
    if item.get("fabric_words"):
        out["fabric_words"] = item["fabric_words"]       # the fabric the listing names, without its shares
    if item.get("brand"):
        out["brand"] = item["brand"]
    return out


# ── one store ────────────────────────────────────────────────────────────────

class Read:
    """What was read from one store in this run."""

    def __init__(self, key: str, label: str):
        self.key, self.label = key, label
        self.products: list[dict] = []
        self.left_out: dict[str, list[str]] = {reason: [] for reason in LEFT_OUT}
        self.left_counts: dict[str, int] = {}   # (a store as the pool holds it: how many, of which left_out has examples)
        self.complete: set[str] = set()     # the garment types all of whose pages were read
        self.state, self.message = "ok", ""
        self.pages = 0
        self.notes: list[str] = []          # pages that are gone or moved: addresses to fix
        self.interrupted: BaseException | None = None   # the window was closed, or Ctrl+C: the run ends after this store


def collect_store(session: Session, key: str, store: dict, settings: dict, log=print) -> Read:
    """Every plain product on one store's category pages, each sorted into one garment type."""
    read = Read(key, store.get("label", key))
    base, reader = store["base"], readers.reader(key)
    words = words_of(store, settings)
    most = int(settings.get("pool_listing_pages", settings.get("max_listing_pages", 3)))
    listed = pages_of(store)
    rules = {g: rules_of(store, g, settings) for gs in listed.values() for g in gs}
    seen: dict[str, tuple[dict, set[str]]] = {}       # product id -> (the product, the garments of its pages)
    finished: set[str] = set()                          # the pages read to their last page
    stamp = catalog.now_iso()
    log(f"\n{read.label}")
    try:
        for path, garments in listed.items():
            url: str | None = base + path
            first = True
            for _ in range(most):
                if url is None:
                    break
                try:
                    items, html = readers.read_page(session, key, base, url, reader, first)
                except NotAllowed:
                    read.notes.append(f"{url}: its robots.txt asks automated visitors to stay out")
                    break
                except PageMissing:
                    read.notes.append(f"{url} no longer exists: update its address")
                    break
                except readers.Moved as moved:
                    read.notes.append(f"{url} now opens {moved.landed}: update its address")
                    break
                for item in items:
                    entry = seen.setdefault(f"{key}-{item['sku']}", (item, set()))
                    entry[1].update(garments)
                log(f"  {'/'.join(garments):<28} {len(items):>4} products on {url[len(base):][:60]}")
                if first and not items:
                    read.notes.append(f"{url} showed no products: check its address")
                    break
                if not items:
                    finished.add(path)
                    break
                url, first = pages.next_page_url(html, url), False
            else:
                finished.add(path)
            if url is None:
                finished.add(path)
    except LimitReached as stop:
        read.state, read.message = "stopped", f"Stopped early: {stop.reason}."
    except Blocked as stop:
        read.state = "blocked"
        read.message = (f"{read.label} refused a page: {stop.reason}. Collection from {read.label} stopped there; "
                        "nothing was retried.")
    except (BrowserClosed, KeyboardInterrupt) as stop:      # what was read so far is kept (run)
        read.state, read.interrupted = "stopped", stop
        read.message = "Stopped early: " + (str(stop) if isinstance(stop, BrowserClosed) else "Ctrl+C") + "."
    finally:
        read.pages = session.pages_loaded.get(key, 0)
        _sort_all(read, seen, rules, words, stamp)
        # A garment type is read in full when every page listed for it was read to its end.
        read.complete = {g for gs in listed.values() for g in gs
                         if all(path in finished for path, listing in listed.items() if g in listing)}
    if read.message:
        log(f"  ! {read.message}")
    return read


def _sort_all(read: Read, seen: dict[str, tuple[dict, set[str]]], rules: dict, words: dict, stamp: str) -> None:
    for item, garments in seen.values():
        garment, why = judge(item, garments, rules, words)
        if garment is None:
            read.left_out[why].append(_named(item, garments, why))
            continue
        read.products.append(product(item, garment, stamp))
    read.products, copies = distinct(read.products)
    read.left_out[TWICE] += [p["name"] for p in copies]
    one_picture_each(read.products)


def _named(item: dict, garments, why: str) -> str:
    """How a product left out is named in the report: with the garment types of its pages where those decided."""
    name = item.get("name") or item.get("url", "")
    ordered = [g for g in GARMENTS if g in garments]
    return f"{name} ({'/'.join(ordered)})" if why in (NO_GARMENT, TWO_GARMENTS) else name


def one_picture_each(products: list[dict]) -> int:
    """A picture shows one colour: where products of a store in different colours have the same picture (a colour
    the page showed without a picture of its own, given another colour's), it stays only with the product whose own
    number its address names, and where none or several do, with none of them: which colour it shows is not known
    (the app shows their colour instead). Returns how many pictures it took away."""
    by_picture: dict[str, list[dict]] = {}
    for p in products:
        if p.get("image_url"):
            by_picture.setdefault(p["image_url"], []).append(p)
    taken = 0
    for picture, sharing in by_picture.items():
        if len({str(p.get("colour") or "").strip().lower() for p in sharing}) < 2:
            continue
        address = picture.split("?")[0]
        named = [p for p in sharing if _number(p) and _number(p) in address]
        for p in sharing:
            if len(named) != 1 or p is not named[0]:
                p["image_url"] = ""
                taken += 1
    return taken


def _number(product: dict) -> str:
    """The longest run of digits in a product's own article number ("4711" of "musterhaus-4711L")."""
    own = str(product.get("id", ""))[len(str(product.get("store", ""))) + 1:]
    return max(re.findall(r"\d+", own), key=len, default="")


def distinct(products: list[dict]) -> tuple[list[dict], list[dict]]:
    """One product per link and colour, the first: a store can list one article twice, under two product numbers
    (Pull&Bear does, once for each bundle it belongs to), and a customer must not see it twice among his options.
    Returns (the products kept, the copies left out)."""
    seen: set[tuple[str, str]] = set()
    kept: list[dict] = []
    copies: list[dict] = []
    for p in products:
        key = (str(p.get("url", "")), str(p.get("colour", "")).strip().lower())
        if key in seen:
            copies.append(p)
            continue
        seen.add(key)
        kept.append(p)
    return kept, copies


# ── the pool, merged per store ───────────────────────────────────────────────

def merge(pool: dict, read: Read) -> None:
    """Put one store's products into the pool. Its products of each garment type read in full are replaced; of a
    garment type it did not finish (the store stopped part-way, or one of its pages moved), its old products stay,
    but for those read again now.
    What the fabric pass read from a product's own page is carried over to the same product read again. The other
    stores' products are left exactly as they are."""
    old = {p["id"]: p for p in pool["products"] if p.get("store") == read.key}
    fresh = []
    for p in read.products:
        before = old.get(p["id"])
        if before and before.get("page_read_at"):
            for field in FROM_ITS_PAGE:
                if field in before and (field != "composition_text" or not p.get("composition_text")):
                    p[field] = before[field]
            if before.get("fabric_from") == "listing" and p.get("composition_text"):
                p["fabric_from"] = "listing"
        fresh.append(p)
    ids = {p["id"] for p in fresh}
    fresh += [p for p in old.values() if p["id"] not in ids and p.get("category") not in read.complete]
    fresh, _ = distinct(fresh)          # (an old product under another number than now is the same product)
    pool["products"] = [p for p in pool["products"] if p.get("store") != read.key] + fresh
    pool["stores"][read.key] = notes(read, fresh)
    pool["collected_at"] = catalog.now_iso()


def notes(read: Read, products: list[dict]) -> dict:
    """The store's line in the list's "stores" notes, as the per-piece refresh writes it (the Wardrobe page shows
    `gives` under its pieces), with what the pool holds of it. On this computer it also keeps what the collection
    left out and the addresses to fix, for the report (write_report); publish leaves those two out."""
    return {"status": read.state, "message": read.message, "gives": gives(products),
            "checked_at": catalog.now_iso(), "products": len(products), "pages": read.pages, "label": read.label,
            "left_out": {reason: {"count": len(names), "examples": names[:EXAMPLES]}
                         for reason, names in read.left_out.items() if names},
            "addresses": list(read.notes)}


EXAMPLES = 6        # names kept of the products left out for each reason


ONLY_HERE = ("left_out", "addresses")       # notes kept on this computer only (publish leaves them out)


def gives(products: list[dict]) -> str:
    """What a store's category pages give, in words: "name, price, colour, picture and sizes — fabric for 40% of
    them, estimated from the name for the rest"."""
    if not products:
        return "nothing yet"
    n = len(products)

    def share(test) -> float:
        return sum(1 for p in products if test(p)) / n

    said = ["name", "price"]
    if share(lambda p: p.get("colour")) >= 0.5:
        said.append("colour")
    if share(lambda p: p.get("image_url")) >= 0.5:
        said.append("picture")
    if share(lambda p: p.get("sizes_all")) >= 0.5:
        said.append("sizes")
    fabric = share(lambda p: composition.stated(p.get("composition_text")))
    words = ", ".join(said[:-1]) + " and " + said[-1]
    if fabric >= 0.95:
        return f"{words} and fabric"
    if fabric > 0:
        return f"{words}; fabric for {fabric:.0%} of them, estimated from the name for the rest"
    return f"{words}; fabric is estimated from the name"


# ── the report ───────────────────────────────────────────────────────────────

def _eur(value: float) -> str:
    return f"{value:,.0f} €" if float(value).is_integer() else f"{value:,.2f} €"


def report(read: Read) -> list[str]:
    """Per garment: products kept, price range, colours, how many state their fabric; then what was left out."""
    lines = [f"{read.label} ({read.key}): {len(read.products)} products kept from {read.pages} pages"
             + (f" — {read.message}" if read.message else "")]
    by_garment: dict[str, list[dict]] = {}
    for p in read.products:
        by_garment.setdefault(p["category"], []).append(p)
    for garment in GARMENTS:
        found = by_garment.get(garment)
        if not found:
            continue
        prices = [p["price"] for p in found]
        named = Counter(colours.find(p.get("colour")) or "other" for p in found)
        tones = ", ".join(f"{key} {n}" for key, n in named.most_common(6))
        fabric = sum(1 for p in found if composition.stated(p.get("composition_text")))
        words = sum(1 for p in found if p.get("fabric_words") and not composition.stated(p.get("composition_text")))
        lines.append(f"  {garment:<11} {len(found):>4}  {_eur(min(prices))}–{_eur(max(prices))}  "
                     f"fabric stated {fabric}" + (f" (+{words} name it without shares)" if words else "")
                     + f"  colours: {tones}")
    for reason in LEFT_OUT:
        names = read.left_out.get(reason) or []
        if names:
            examples = "; ".join(names[:4])
            lines.append(f"  left out, {reason}: {read.left_counts.get(reason, len(names))} (e.g. {examples})")
    for note in read.notes:
        lines.append(f"  address to fix: {note}")
    return lines


def held(the_pool: dict, key: str) -> Read:
    """What the pool holds of one store, as a Read for the report: its products as they are now, and what its last
    collection (and any sorting again since) left out."""
    said = the_pool["stores"].get(key, {})
    read = Read(key, said.get("label", key))
    read.products = [p for p in the_pool["products"] if p.get("store") == key]
    left = said.get("left_out") or {}
    read.left_out = {reason: list((left.get(reason) or {}).get("examples", [])) for reason in LEFT_OUT}
    read.left_counts = {reason: int(left[reason].get("count", 0)) for reason in left if reason in LEFT_OUT}
    read.state, read.message, read.pages = said.get("status", "ok"), said.get("message", ""), said.get("pages", 0)
    read.notes = list(said.get("addresses", []))
    return read


def write_report(the_pool: dict) -> None:
    """data/pool-report.txt: every store the pool holds, as the pool holds it now (not only the last run's)."""
    lines: list[str] = []
    for key in the_pool["stores"]:
        lines += report(held(the_pool, key)) + [""]
    path = report_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ── a whole run ──────────────────────────────────────────────────────────────

def run(store_keys: list[str] | None = None, log=print) -> dict[str, Read]:
    """Collect the chosen stores (all with category pages when none are named) into the pool, one store at a time,
    saving the pool and the report after each. Returns {store: what was read}."""
    from . import collected_stores
    cfg = load_settings()
    settings = cfg.get("collector", {})
    keys = [k for k in collected_stores(cfg) if not store_keys or k in store_keys]
    results: dict[str, Read] = {}
    with Session(settings, log) as session:
        for key in keys:
            read = collect_store(session, key, cfg[key], settings, log)
            results[key] = read
            pool = load()
            merge(pool, read)
            save(pool)
            write_report(pool)
            if isinstance(read.interrupted, KeyboardInterrupt):
                raise read.interrupted          # (after saving what was read)
            if read.interrupted is not None:
                break
    return results


# ── sorting again, without opening a page ────────────────────────────────────

def sort_again(the_pool: dict, cfg: dict, store_keys: list[str] | None = None) -> dict[str, Read]:
    """Sort the pool's products again with the words and readers as they are now, without opening any page: after
    the words in config/stores.toml or config/collect.local.toml changed, or a reader learned something. Each product
    is judged as a fresh collection judges it (judge, distinct, one_picture_each), with the colour its own link names
    (listing.link_colour), on each page listed for its garment type: it keeps its garment type where one of those
    pages still gives it that one, takes the one other garment type they agree on, or is left out (and counted with
    what its store's collection left out). What the fabric pass read from its own page stays. Returns, per store, a
    Read holding the products it kept and those it left out now."""
    settings = cfg.get("collector", {})
    results: dict[str, Read] = {}
    for key in [k for k in the_pool["stores"] if not store_keys or k in store_keys]:
        store = cfg.get(key, {})
        words, listed = words_of(store, settings), pages_of(store)
        rules = {g: rules_of(store, g, settings) for g in GARMENTS}
        read = Read(key, store.get("label", the_pool["stores"][key].get("label", key)))
        for row in [p for p in the_pool["products"] if p.get("store") == key]:
            row = {**row, "colour": listing.link_colour(row.get("name", ""), row.get("url", ""),
                                                         row.get("colour", ""))}
            category = row.get("category", "")
            verdicts = [judge(row, garments, rules, words)
                        for garments in ([gs for gs in listed.values() if category in gs] or [[category]])]
            fits = {garment for garment, _ in verdicts if garment}
            if category in fits or len(fits) == 1:
                row["category"] = category if category in fits else fits.pop()
                read.products.append(row)
            else:
                why = TWO_GARMENTS if fits else verdicts[0][1]
                read.left_out[why].append(_named(row, {g for gs in listed.values() if category in gs for g in gs}
                                                 or {category}, why))
        read.products, copies = distinct(read.products)
        read.left_out[TWICE] += [p["name"] for p in copies]
        one_picture_each(read.products)
        results[key] = read
        the_pool["products"] = [p for p in the_pool["products"] if p.get("store") != key] + read.products
        said = the_pool["stores"][key]
        before = said.get("left_out") or {}
        left = {}
        for reason in LEFT_OUT:
            had = before.get(reason) or {"count": 0, "examples": []}
            if had["count"] or read.left_out[reason]:
                left[reason] = {"count": had["count"] + len(read.left_out[reason]),
                                "examples": (had["examples"] + read.left_out[reason])[:EXAMPLES]}
        said.update(products=len(read.products), gives=gives(read.products), sorted_again_at=catalog.now_iso(),
                    left_out=left)
    return results
