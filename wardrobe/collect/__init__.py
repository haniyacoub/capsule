"""The collector: fills data/catalog.json from COS and Weekday.

    python -m wardrobe refresh                     every slot, every store
    python -m wardrobe refresh --store cos         one store
    python -m wardrobe refresh --slot white-tee    one slot

For each slot it reads the category page(s) listed for that garment type in
config/stores.toml and shortlists the products that fit (matching.py). Product
pages are never opened: both stores refuse them to automated browsers. Only
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

from .. import catalog, colours, config, db, programmes
from . import cos, matching, pages, weekday
from .browser import Blocked, BrowserClosed, LimitReached, NotAllowed, PageMissing, Session

ADAPTERS = {"cos": cos, "weekday": weekday}
STORE_ORDER = ["cos", "weekday"]


def load_settings() -> dict:
    return config.load("stores.toml")


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
