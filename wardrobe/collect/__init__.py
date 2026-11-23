"""The collector: fills data/catalog.json from COS and Weekday.

    python -m wardrobe refresh                     every slot, every store
    python -m wardrobe refresh --store cos         one store
    python -m wardrobe refresh --slot white-tee    one slot

For each slot it reads the category page(s) listed for that garment type in
config/stores.toml and shortlists the products that fit (matching.py). Product
pages are never opened here: both stores refuse them to automated browsers.
(`refresh --pool` collects every plain product of every store with category
pages for the shared list, pool.py, and `refresh --pool --fabric` reads each
collected product's own page once, only for its fabric, fabric.py.) Only
stores with a partner programme are collected (programmes.py): Zara has none,
and its reader was removed. The politeness rules — real browser, robots.txt,
pauses, stop at the first refusal — live in browser.py.

For your own machine and for testing only. Run it by hand, never on a
schedule (no cron job, timer or start-up call: nothing in deploy/ or the
container runs it), and never use what it collects as the source for the
public site. The public site is to use the stores' licensed product feeds
instead (PRODUCTION.md, "Before customers"). `python -m wardrobe refresh`
refuses to run in production mode.
"""
from __future__ import annotations

import os
import tomllib
from pathlib import Path

from .. import catalog, colours, config, db, paths, programmes
from . import cos, matching, pages, weekday
from .browser import Blocked, BrowserClosed, LimitReached, NotAllowed, PageMissing, Session

ADAPTERS = {"cos": cos, "weekday": weekday}
STORE_ORDER = ["cos", "weekday"]

# The stores' collection addresses that stay on this computer: config/collect.local.toml, never committed
# (.gitignore). It is read over config/stores.toml, table by table, whenever the collector loads its settings, so a
# store's category pages can be listed there while the public file names only the store itself (its name, web
# address, programme, styles and price). config/collect.local.example.toml shows its shape, with invented stores.
# WARDROBE_COLLECT_LOCAL names another file; set to nothing, no local file is read (the tests do that).
LOCAL_NAME = "collect.local.toml"


def local_path() -> Path | None:
    """The local file of collection addresses, or None when none is to be read."""
    named = os.environ.get("WARDROBE_COLLECT_LOCAL")
    if named is None:
        return paths.CONFIG_DIR / LOCAL_NAME
    return Path(named) if named.strip() else None


def _merged(public: dict, local: dict) -> dict:
    """`public` with `local` laid over it: tables are merged key by key, any other value of `local` wins."""
    out = dict(public)
    for key, value in local.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merged(out[key], value)
        else:
            out[key] = value
    return out


def load_settings() -> dict:
    """config/stores.toml, with the local file of collection addresses (local_path) read over it where there is one."""
    public = config.load("stores.toml")
    path = local_path()
    if path is None or not path.is_file():
        return public
    try:
        with path.open("rb") as f:
            local = tomllib.load(f)
    except tomllib.TOMLDecodeError as e:
        raise config.ConfigError(f"{path.name} has a syntax error: {e}") from None
    return _merged(public, local)


def collected_stores(cfg: dict | None = None) -> list[str]:
    """The stores the collector reads, in config/stores.toml's order: those customers are offered (a partner
    programme, programmes.py) whose category pages are listed, in the public file or in the local one. A store
    named only in the local file has no programme, so it is never read."""
    cfg = load_settings() if cfg is None else cfg
    return [key for key in programmes.offered()
            if any((rules or {}).get("pages") for rules in (cfg.get(key, {}).get("garments") or {}).values())]


def _eur(value: float) -> str:
    return f"{value:,.0f} €" if float(value).is_integer() else f"{value:,.2f} €"


def _candidate(item: dict, slot: dict, stamp: str) -> dict:
    """A catalogue entry from a product on a category page."""
    return {
        "id": f"{item['store']}-{item['sku']}",
        "slot_id": slot["id"],
        "store": item["store"],
        "name": item["name"],
        "slug": item.get("slug", ""),
        "price": item["price"],
        "price_before": item.get("price_before"),
        "currency": "EUR",
        "colour": item.get("colour", ""),
        "colour_hex": item.get("colour_hex"),
        "composition_text": "",
        "fit": pages.fit_from(f"{item['name']} {item.get('slug', '')}"),
        "description": "",
        "sizes_all": item.get("sizes_all", []),
        "sizes_in_stock": item.get("sizes_in_stock", []),
        "url": item["url"],
        "image_url": item.get("image_url", ""),
        "source": "collected",
        "collected_at": stamp,
    }


def collect_slot(session: Session, key: str, store: dict, slot: dict, settings: dict,
                 limit: int, found: list[dict], log) -> None:
    """Candidates for one slot from one store's category pages, appended to `found`."""
    adapter, base = ADAPTERS[key], store["base"]
    rules = store["garments"][slot["category"]]
    stamp = catalog.now_iso()
    items: dict[str, dict] = {}
    shortlist: list[tuple[dict, dict]] = []

    for path in rules["pages"]:
        url: str | None = base + path
        for _ in range(int(settings.get("max_listing_pages", 2))):
            if url is None:
                break
            try:
                html = session.fetch(key, base, url)
            except NotAllowed:
                log(f"      skipped {url} — the store's robots.txt asks automated visitors to stay out")
                break
            except PageMissing:
                log(f"      {url} no longer exists — update config/stores.toml")
                break
            for item in adapter.parse_listing(html, base):
                items.setdefault(item["sku"], item)
            shortlist = matching.shortlist(list(items.values()), slot, rules, settings)
            if len(shortlist) >= limit:
                break
            url = pages.next_page_url(html, url)
        if len(shortlist) >= limit:
            break
    found.extend(_candidate(item, slot, stamp) for item, _ in shortlist[:limit])


def collect_store(session: Session, key: str, store: dict, slots: list[dict], settings: dict,
                  limit: int, log) -> dict:
    """Everything one store offers for the given slots. Returns that store's status entry."""
    label = store.get("label", key)
    gives = ADAPTERS[key].LISTING_GIVES
    state, message, filled, total = "ok", "", 0, 0
    log(f"\n{label}")
    try:
        for slot in slots:
            if not (store.get("garments", {}).get(slot["category"]) or {}).get("pages"):
                log(f"  {slot['name']:<32} not sold at {label}")
                continue
            found: list[dict] = []
            try:
                collect_slot(session, key, store, slot, settings, limit, found, log)
            finally:   # keep what was read even if the store stops us half-way through a slot
                if found:
                    catalog.update(lambda cat: catalog.replace_collected(cat, key, slot["id"], found))
            if found:
                filled, total = filled + 1, total + len(found)
                log(f"  {slot['name']:<32} {len(found)} candidates, from {_eur(min(c['price'] for c in found))}")
            else:
                catalog.update(lambda cat: catalog.replace_collected(cat, key, slot["id"], []))
                log(f"  {slot['name']:<32} nothing suitable in {colours.get(slot['colour']).label.lower()}")
    except LimitReached as stop:
        state, message = "stopped", f"Stopped early: {stop.reason}."
    except Blocked as stop:
        state = "blocked"
        message = (f"{label} refused a page — {stop.reason}. Collection from {label} stopped there; "
                   "nothing was retried. Add products by hand on a slot's page (“Add a product by link”).")
    if message:
        log(f"  ! {message}")
    return {"status": state, "message": message, "gives": gives, "checked_at": catalog.now_iso(),
            "slots_filled": filled, "candidates": total, "pages": session.pages_loaded.get(key, 0)}


def refresh(store_keys: list[str] | None = None, slot_ids: list[str] | None = None,
            max_candidates: int | None = None, log=print) -> dict:
    """Collect and save. Returns {store: status}."""
    cfg = load_settings()
    settings = cfg.get("collector", {})
    # The per-piece refresh reads the stores with a reader of their own (COS and Weekday); the pool (pool.py) reads
    # every store with category pages.
    keys = [k for k in STORE_ORDER if k in cfg and programmes.is_offered(k) and (not store_keys or k in store_keys)]
    all_slots = db.list_slots()
    slots = [s for s in all_slots if not slot_ids or s["id"] in slot_ids]
    slots = [s for s in slots if not s["owned"]]          # nothing to buy for what you own
    limit = int(max_candidates or settings.get("max_candidates", 6))

    def begin(cat: dict) -> None:
        catalog.start_collected(cat)
        catalog.prune(cat, {s["id"] for s in all_slots})
    catalog.update(begin)

    results: dict[str, dict] = {}
    with Session(settings, log) as session:
        try:
            for key in keys:
                results[key] = collect_store(session, key, cfg[key], slots, settings, limit, log)
                catalog.update(lambda cat: cat.setdefault("stores", {}).update({key: results[key]}))
        except BrowserClosed as closed:
            log(f"\n{closed}")

    def finish(cat: dict) -> None:
        cat["collected_at"] = catalog.now_iso()
    catalog.update(finish)
    return results
