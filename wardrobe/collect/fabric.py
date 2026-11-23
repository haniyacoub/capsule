"""The fabric pass: each collected product's own page, read once, only for its fabric.

    python -m wardrobe refresh --pool --fabric                       every store in the pool
    python -m wardrobe refresh --pool --fabric --store hm            one store (repeatable)
    python -m wardrobe refresh --pool --fabric --max-pages 20        a sample: at most 20 pages a store

The owner agreed on 22 Nov 2026 that the collector may also open each collected product's own page, for one purpose:
to read its fabric. Nothing else about the rule changes. The pass reads, once, the page of each product in the pool
(data/pool.json, pool.py) that has no fabric yet: a product whose category page gave its fibres with their shares
("95% Baumwolle, 5% Elasthan") is skipped; one whose category page only names a fibre ("Baumwolljersey") is read, as
only its own page gives the shares. It reads the page with the product-page reader (generic.py: the page's schema.org
"material"), and where that says nothing, the fibres with their shares that the page writes in its own data or its
text near "Material" or "Zusammensetzung", where the fibres known add up to at least 90% (composition.stated: "100% aus"
cut from a sentence is no fabric). It goes through the same browser session as the rest of the collector:
robots.txt first, a pause of 5 to 9 seconds between two pages of a store, and a stop for that store at its first
refusal. Stores that refuse product pages to automated browsers are marked `product_pages = false` in
config/stores.toml (COS and Weekday) and are never asked. `product_pages = false` under [collector] switches the
pass off altogether.

At most `max_product_pages` pages per store in one run (300 is about 45 minutes a store): a later run carries on with
the products still without a fabric. A product whose page was read is marked (page_read_at) whether or not a fabric
was found there, so it is not read again; a page that is gone (the product sold out and was taken down) is marked too.
What was found goes where the scoring reads it (composition_text, as a store's label states it), so that product's
rating is no longer an estimate. The pool is saved every few pages, so Ctrl+C keeps what was read.
"""
from __future__ import annotations

import json
import re
import time
from typing import Any

from .. import catalog, composition
from . import generic, listing, load_settings, pool
from .browser import Blocked, BrowserClosed, LimitReached, NotAllowed, PageMissing, Session

SAVE_EVERY = 20          # pages read between two saves of the pool
SECONDS_A_PAGE = 9       # what one page costs, pause included: for the report's estimate

# Where a page writes its fibres in plain words: the share and the fibre ("100% Baumwolle", "95 % cotton"), with at most
# one small word between them ("100% aus Baumwolle", "10 % recycelten Polyester").
_SHARE = r"\d{1,3}(?:[.,]\d+)?\s*%\s*(?:[a-zäöüß]+\s+)?[A-Za-zÄÖÜäöüß][\w-]*"
_SHARES = re.compile(_SHARE + r"(?:\s*[,/;+]?\s*(?:und\s+|and\s+)?" + _SHARE + r")*")
_NEAR = re.compile(r"(material|zusammensetzung|composition|obermaterial|außenmaterial|aussenmaterial|oberstoff|"
                   r"stoff|fabric|qualität)", re.I)
_TAG = re.compile(r"<[^>]+>")


class Pass:
    """What the fabric pass did at one store."""

    def __init__(self, key: str, label: str):
        self.key, self.label = key, label
        self.read = self.found = self.gone = 0
        self.state, self.message = "ok", ""
        self.left = 0                    # products still without a fabric (and not read) after this run
        self.skipped = ""                # why the store was not asked at all


def _from_json(trees: list) -> str:
    """The first fibres-with-shares a page's own data states: a text under a key that names the material
    ("composition": "100% Baumwolle"), or a list of fibres with their shares ([{"name": "baumwolle", "percentage":
    "100"}])."""
    stack: list[Any] = list(trees)
    seen: set[int] = set()
    while stack:
        node = stack.pop()
        if id(node) in seen:
            continue
        seen.add(id(node))
        if isinstance(node, dict):
            for key, value in node.items():
                if isinstance(value, str) and _NEAR.search(key) and composition.stated(value):
                    return composition.stated(value)[:200]
            name = node.get("name") or node.get("fibre") or node.get("material")
            share = node.get("percentage") or node.get("percent") or node.get("share")
            if isinstance(name, str) and isinstance(share, (str, int, float)) and str(share).replace(".", "").isdigit() \
                    and composition.stated(f"{share}% {name}"):
                return f"{share}% {name}"
            stack += [v for v in node.values() if isinstance(v, (dict, list))]
        elif isinstance(node, list):
            parts = [f"{d.get('percentage')}% {d.get('name')}" for d in node if isinstance(d, dict)
                     and isinstance(d.get("name"), str) and str(d.get("percentage", "")).replace(".", "").isdigit()]
            if parts and composition.stated(", ".join(parts)):
                return composition.stated(", ".join(parts))[:200]
            stack += [v for v in node if isinstance(v, (dict, list))]
    return ""


def _from_text(html: str) -> str:
    """The fibres with their shares that the page's own words state near "Material", "Zusammensetzung" and the like."""
    body = re.sub(r"<script\b.*?</script>|<style\b.*?</style>", " ", html, flags=re.S | re.I)
    text = " ".join(_TAG.sub(" ", body).split())
    for near in _NEAR.finditer(text):
        found = _SHARES.search(text, near.end(), near.end() + 160)
        if found and composition.stated(found.group()):
            return composition.stated(found.group())[:200]
    return ""


def fabric_of(html: str) -> str:
    """A product page's fabric, as its label would state it ("95% Baumwolle, 5% Elasthan"), or ""."""
    said = composition.stated(generic.read(html).get("material", ""))
    if said:
        return said[:200]
    trees: list = []
    for found in (listing._flight(html), listing._turbo(html), listing._scripts(html)):
        trees += found
    for block in re.findall(r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', html, re.S | re.I):
        try:
            trees.append(json.loads(block))
        except ValueError:
            continue
    return _from_json(trees) or _from_text(html)


def wanted(product: dict) -> bool:
    """Whether this product's own page is still to be read: no fabric with shares yet, and not read before."""
    return not product.get("page_read_at") and not composition.stated(product.get("composition_text"))


def run(store_keys: list[str] | None = None, most: int | None = None, log=print) -> dict[str, Pass]:
    """The fabric pass over the pool's stores (all of them when none are named). Returns {store: what it did}."""
    cfg = load_settings()
    settings = cfg.get("collector", {})
    if settings.get("product_pages") is False:
        raise RuntimeError("Product pages are switched off (product_pages = false under [collector] in "
                           "config/stores.toml), so the fabric pass does not run.")
    most = int(most or settings.get("max_product_pages", 300))
    the_pool = pool.load()
    keys = [k for k in the_pool["stores"] if not store_keys or k in store_keys]
    results: dict[str, Pass] = {}
    # Its own ceiling on pages a store: the collector's usual one (max_pages_per_store) is for category pages.
    with Session({**settings, "max_pages_per_store": most + 2}, log) as session:
        for key in keys:
            store = cfg.get(key, {})
            done = Pass(key, store.get("label", key))
            results[key] = done
            if store.get("product_pages") is False:
                done.skipped = "its product pages are refused to automated browsers"
                done.left = sum(1 for p in the_pool["products"] if p.get("store") == key and wanted(p))
                continue
            try:
                _one_store(session, key, store, the_pool, done, most, log)
            except (BrowserClosed, KeyboardInterrupt):
                pool.save(the_pool)
                raise
            # (the store's line says how many of its products now state their fabric, and so does the report)
            the_pool["stores"][key]["gives"] = pool.gives([p for p in the_pool["products"] if p.get("store") == key])
            pool.save(the_pool)
            pool.write_report(the_pool)
    return results


def in_turn(products: list[dict]) -> list[dict]:
    """The products one garment type at a time, in turn (a coat, a jacket, …, then a second coat …), so that a run
    that stops early, or a sample, has read some of every garment."""
    by_garment: dict[str, list[dict]] = {}
    for product in products:
        by_garment.setdefault(product.get("category", ""), []).append(product)
    queues = list(by_garment.values())
    out: list[dict] = []
    while queues:
        out += [queue.pop(0) for queue in queues]
        queues = [queue for queue in queues if queue]
    return out


def _one_store(session: Session, key: str, store: dict, the_pool: dict, done: Pass, most: int, log) -> None:
    todo = in_turn([p for p in the_pool["products"] if p.get("store") == key and wanted(p)])
    log(f"\n{done.label}: {len(todo)} product pages to read, at most {most} in this run")
    base = store.get("base", "")
    for product in todo[:most]:
        url = product.get("url", "")
        try:
            html = session.fetch(key, base, url)
        except NotAllowed:
            product["page_read_at"] = catalog.now_iso()     # its robots.txt asks automated visitors to stay out
            continue
        except PageMissing:
            product["page_read_at"], product["page_gone"] = catalog.now_iso(), True
            done.gone += 1
            continue
        except LimitReached as stop:
            done.state, done.message = "stopped", f"Stopped: {stop.reason}."
            break
        except Blocked as stop:
            done.state = "blocked"
            done.message = f"{done.label} refused a product page: {stop.reason}. Its pass stopped there; nothing was retried."
            break
        done.read += 1
        product["page_read_at"] = catalog.now_iso()
        found = fabric_of(html)
        if found:
            product["composition_text"], product["fabric_from"] = found, "product page"
            done.found += 1
        if done.read % SAVE_EVERY == 0:
            pool.save(the_pool)
            log(f"  {done.read} pages read, a fabric on {done.found}")
    done.left = sum(1 for p in the_pool["products"] if p.get("store") == key and wanted(p))
    if done.message:
        log(f"  ! {done.message}")


def report(done: Pass) -> str:
    """One line per store: pages read, fabric found, pages gone, a refusal, and how long the rest would take."""
    if done.skipped:
        return f"{done.label}: not asked: {done.skipped} ({done.left} products without a fabric)"
    if done.state == "blocked":
        return (f"{done.label}: {done.read} product pages read, a fabric on {done.found}; then it refused one, so its "
                f"{done.left} other products keep an estimated fabric. {done.message} Mark it product_pages = false "
                "in config/stores.toml.")
    rest = done.left * SECONDS_A_PAGE
    hours = f"{rest / 3600:.1f} hours" if rest >= 3600 else f"{round(rest / 60)} minutes"
    line = (f"{done.label}: {done.read} product pages read, a fabric on {done.found}"
            + (f", {done.gone} gone" if done.gone else "")
            + f"; {done.left} still without a fabric (about {hours} more at {SECONDS_A_PAGE} s a page)")
    return line + (f". {done.message}" if done.message else "")


def elapsed(start: float) -> str:
    minutes = (time.time() - start) / 60
    return f"{minutes:.0f} minutes"
