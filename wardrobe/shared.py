"""The store catalogue all customers share (production mode).

On your own machine the collector fills data/catalog.json for *your* slots.
A public service has many customers with different slots, so it keeps one list
of products instead — `store_catalog.json` in its data folder — and gives each
customer the products that fit each of their slots: same garment type, same
colour, keyword matches first, cheapest first.

    python -m wardrobe publish ./data-production

copies what your last refresh collected into that list. A licensed product
feed would be loaded into the same file. Whether a list may be shown to the
public is a question of the stores' permission, not of this code.
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

from . import catalog, config, db, paths
from .collect import matching

POOL_NAME = "store_catalog.json"
_cache: tuple[int, dict] | None = None


def load() -> dict | None:
    """The shared list in this service's data folder, or None if nothing was published."""
    global _cache
    path = paths.DATA_DIR / POOL_NAME
    try:
        mtime = path.stat().st_mtime_ns
    except FileNotFoundError:
        return None
    if _cache and _cache[0] == mtime:
        return _cache[1]
    with path.open(encoding="utf-8") as f:
        pool = json.load(f)
    _cache = (mtime, pool)
    return pool


def publish(target: Path) -> int:
    """Write the locally collected products, tagged with their garment type, into `target`."""
    cat = catalog.load()
    slots = {s["id"]: s for s in db.list_slots()}
    products: dict[str, dict] = {}
    for cand in cat.get("candidates", []):
        slot = slots.get(cand.get("slot_id"))
        if slot is None or cand.get("source") != "collected":
            continue                                   # demo items and your own additions stay private
        product = {k: v for k, v in cand.items() if k not in ("slot_id", "manual")}
        product["category"] = slot["category"]
        products.setdefault(product["id"], product)
    stamp = datetime.now().astimezone().isoformat(timespec="microseconds")   # tells two publishes apart
    pool = {"published_at": stamp, "collected_at": cat.get("collected_at"),
            "stores": cat.get("stores", {}), "products": list(products.values())}
    target.mkdir(parents=True, exist_ok=True)
    tmp = target / (POOL_NAME + ".tmp")
    tmp.write_text(json.dumps(pool, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, target / POOL_NAME)
    return len(products)


def candidates_for(pool: dict, slot: dict, collector: dict) -> list[dict]:
    """The products that fit one slot: per store, best colour match, keyword matches, then cheapest."""
    skip_words = collector.get("skip_words", [])
    vocabulary = collector.get("keyword_words", {})
    per_store = int(collector.get("max_candidates", 6))
    ranked: dict[str, list[tuple[tuple, dict]]] = {}
    for product in pool.get("products", []):
        if product.get("category") != slot["category"]:
            continue
        level = matching.colour_level(slot, product.get("colour"), product.get("colour_hex"), skip_words)
        if not level:
            continue
        hits = matching.keyword_hits(slot.get("keywords", ""), matching.text_of(product), vocabulary)
        ranked.setdefault(product.get("store", ""), []).append(((-level, -hits, product.get("price", 0)), product))
    out = []
    for entries in ranked.values():
        entries.sort(key=lambda entry: entry[0])
        out += [{**product, "slot_id": slot["id"]} for _, product in entries[:per_store]]
    return out


def build_catalog(slots: list[dict], previous: dict | None) -> dict | None:
    """One customer's candidates from the shared list. Their own additions and typed-in details are kept."""
    pool = load()
    if pool is None:
        return None
    collector = config.load("stores.toml").get("collector", {})
    before = (previous or {}).get("candidates", [])
    typed_in = {c["id"]: c["manual"] for c in before if c.get("manual")}
    slot_ids = {s["id"] for s in slots}
    candidates = [c for c in before if c.get("source") == "manual" and c.get("slot_id") in slot_ids]
    taken = {(c["slot_id"], c["id"]) for c in candidates}
    for slot in slots:
        for cand in candidates_for(pool, slot, collector):
            if (cand["slot_id"], cand["id"]) in taken:
                continue                               # you added this one yourself; yours wins
            if cand["id"] in typed_in:
                cand["manual"] = typed_in[cand["id"]]
            candidates.append(cand)
    return {"source": "collected", "collected_at": pool.get("collected_at"), "stores": pool.get("stores", {}),
            "pool": pool.get("published_at"), "candidates": candidates}


def refresh_customer() -> None:
    """Rebuild the signed-in customer's candidates if the shared list changed since they last got it."""
    pool = load()
    if pool is None or db.get_setting("pool") == pool.get("published_at"):
        return
    built = build_catalog(db.list_slots(), catalog.load())
    if built:
        catalog.save(built)
        db.set_setting("pool", pool.get("published_at"))
