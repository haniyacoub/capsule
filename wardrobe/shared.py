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

Only the products of stores customers are offered are read from the list
(programmes.py): a store without a partner programme, such as Zara, stays in the
file and is skipped. When a store stops being offered, every customer's products
are rebuilt without it, and his pieces that were picked from it are picked again
(refresh_customer).
"""
from __future__ import annotations

import json
import os
from collections import Counter
from datetime import datetime
from pathlib import Path

from . import capsule, catalog, colours, config, db, paths, programmes, settings
from . import profile as profile_mod
from .collect import matching, pages

POOL_NAME = "store_catalog.json"
_cache: tuple[int, frozenset[str], dict] | None = None     # (the file's time, the stores offered, the list)
# (the list, the colours on offer per garment and set of refused colours)
_offers: tuple[dict, dict[tuple[str, frozenset[str]], dict[str, list[dict]]]] | None = None

# When the way a product's details are read improves, the published list is corrected as it is
# read (see _corrected), without asking any store again. A new REVISION then makes every
# customer's products be rebuilt from the corrected list once (see refresh_customer).
#   fit2: "weder schmaler noch weiter" (a straight leg) is no longer read as a slim cut.
#   refused: a product in a colour the customer refused is no longer among his options, but for what he chose
#            himself (see _for_piece).
# The stores customers are offered are part of the revision too (see revision): a store that gains or loses its
# place makes every customer's products be rebuilt once, without a new REVISION.
REVISION = "refused"


def load() -> dict | None:
    """The shared list in this service's data folder, with only the products of stores customers are offered
    (programmes.py), or None if nothing was published. The file itself is never changed."""
    global _cache
    path = paths.DATA_DIR / POOL_NAME
    try:
        mtime = path.stat().st_mtime_ns
    except FileNotFoundError:
        return None
    offered = frozenset(programmes.offered())
    if _cache and _cache[:2] == (mtime, offered):
        return _cache[2]
    with path.open(encoding="utf-8") as f:
        pool = programmes.only_offered(_corrected(json.load(f)))
    _cache = (mtime, offered, pool)
    return pool


def _corrected(pool: dict) -> dict:
    """The list as published, with each product's cut read again from its own name and description.

    Only products with a description: the cut of the others was read from the name and web
    address, and that reading has not changed. The file itself is left as it is.
    """
    for product in pool.get("products", []):
        if product.get("description"):
            product["fit"] = pages.fit_from(f"{product.get('name', '')} {product['description']}")
    return pool


def revision(pool: dict) -> str:
    """Which publication of the list, read with which corrections and for which stores, a customer's products
    come from: '2026-11-11T17:55:27+01:00#refused#cos,weekday'."""
    return f"{pool.get('published_at')}#{REVISION}#{','.join(sorted(programmes.offered()))}"


def _collected(cat: dict) -> dict[str, dict]:
    """The products the last refresh collected for your pieces, each tagged with the garment type of
    the piece it was collected for: the products of a published list, before they are published."""
    slots = {s["id"]: s for s in db.list_slots()}
    products: dict[str, dict] = {}
    for cand in cat.get("candidates", []):
        slot = slots.get(cand.get("slot_id"))
        if slot is None or cand.get("source") != "collected":
            continue                                   # demo items and your own additions stay private
        product = {k: v for k, v in cand.items() if k not in ("slot_id", "manual")}
        product["category"] = slot["category"]
        products.setdefault(product["id"], product)
    return products


def publish(target: Path) -> int:
    """Write the locally collected products, tagged with their garment type, into `target`."""
    cat = catalog.load()
    products = _collected(cat)
    stamp = datetime.now().astimezone().isoformat(timespec="microseconds")   # tells two publishes apart
    pool = {"published_at": stamp, "collected_at": cat.get("collected_at"),
            "stores": cat.get("stores", {}), "products": list(products.values())}
    target.mkdir(parents=True, exist_ok=True)
    tmp = target / (POOL_NAME + ".tmp")
    tmp.write_text(json.dumps(pool, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, target / POOL_NAME)
    return len(products)


def candidates_for(pool: dict, slot: dict, collector: dict, refused: frozenset[str] = frozenset()) -> list[dict]:
    """The products that fit one slot: per store, best colour match, keyword matches, then cheapest. A product
    whose own colour is one of `refused` (the customer's refused colours, see refused_colours) is left out, also
    where it would match: "Dunkelblau" jeans are never blue jeans for a customer who refused navy. (Which of
    his pieces this applies to, and what he chose himself that stays: _for_piece.)"""
    skip_words = collector.get("skip_words", [])
    vocabulary = collector.get("keyword_words", {})
    per_store = int(collector.get("max_candidates", 6))
    ranked: dict[str, list[tuple[tuple, dict]]] = {}
    for product in pool.get("products", []):
        if product.get("category") != slot["category"]:
            continue
        level = matching.colour_level(slot, product.get("colour"), product.get("colour_hex"), skip_words)
        if not level or matching.refused(product.get("colour"), refused):
            continue
        hits = matching.keyword_hits(slot.get("keywords", ""), matching.text_of(product), vocabulary)
        ranked.setdefault(product.get("store", ""), []).append(((-level, -hits, product.get("price", 0)), product))
    out = []
    for entries in ranked.values():
        entries.sort(key=lambda entry: entry[0])
        out += [{**product, "slot_id": slot["id"]} for _, product in entries[:per_store]]
    return out


def refused_colours() -> frozenset[str]:
    """The colours the signed-in customer refused, as the plan reads them: refusing "green" refuses olive too."""
    return frozenset(capsule.banned(profile_mod.load().get("refused", [])))


def colours_on_offer(category: str, refused: frozenset[str] = frozenset()) -> dict[str, list[dict]]:
    """The colours Capsule has a garment in: for each colour, the products a piece of that garment in
    that colour is offered. Each colour is tried with candidates_for, the matching that fills every
    piece, so a colour listed here really fills one. The colours most of the products are named in
    come first: where two colours reach the same products ('white' and 'ecru' both reach an ecru
    cardigan), the one the stores call them leads. Products in a `refused` colour are left out, as
    candidates_for leaves them out of the piece the tap fills.

    Worked out once per published list (and set of refused colours). On your own machine there is no
    published list: there it is the colours of what the last refresh collected for your pieces of that
    garment.
    """
    global _offers
    pool = load() if settings.PRODUCTION else None
    if pool is None:
        return _on_offer({"products": list(_collected(catalog.load()).values())}, category, refused)
    if _offers is None or _offers[0] is not pool:      # a list published since: work it out again
        _offers = (pool, {})
    known = _offers[1]
    if (category, refused) not in known:
        known[(category, refused)] = _on_offer(pool, category, refused)
    return known[(category, refused)]


def _on_offer(pool: dict, category: str, refused: frozenset[str]) -> dict[str, list[dict]]:
    collector = config.load("stores.toml").get("collector", {})
    named = Counter(colours.find(p.get("colour")) for p in pool.get("products", []) if p.get("category") == category)
    found: dict[str, list[dict]] = {}
    for key in colours.COLOURS:
        probe = {"id": "", "category": category, "colour": key, "keywords": ""}
        products = candidates_for(pool, probe, collector, refused)
        if products:
            found[key] = products
    return dict(sorted(found.items(), key=lambda item: -named[item[0]]))     # equal counts keep the table's order


def build_catalog(slots: list[dict], previous: dict | None) -> dict | None:
    """One customer's candidates from the shared list, never in a colour they refused (see _for_piece). Their own
    additions, typed-in details and locked choices are kept."""
    pool = load()
    if pool is None:
        return None
    collector = config.load("stores.toml").get("collector", {})
    refused = refused_colours()
    before = (previous or {}).get("candidates", [])
    typed_in = {c["id"]: c["manual"] for c in before if c.get("manual")}
    slot_ids = {s["id"] for s in slots}
    candidates = [c for c in before if c.get("source") == "manual" and c.get("slot_id") in slot_ids]
    taken = {(c["slot_id"], c["id"]) for c in candidates}
    for slot in slots:
        for cand in _for_piece(pool, slot, collector, refused):
            if (cand["slot_id"], cand["id"]) in taken:
                continue                               # you added this one yourself; yours wins
            if cand["id"] in typed_in:
                cand["manual"] = typed_in[cand["id"]]
            candidates.append(cand)
    return {"source": "collected", "collected_at": pool.get("collected_at"), "stores": pool.get("stores", {}),
            "pool": revision(pool), "candidates": candidates}


def _for_piece(pool: dict, slot: dict, collector: dict, refused: frozenset[str]) -> list[dict]:
    """The products one of the customer's pieces is offered: candidates_for, leaving out the colours he refused.

    Two things he decided himself win over his refused colours. A piece that is itself in a refused colour was
    kept or added by hand (the plan never proposes one): it is matched as anyone's is, so a navy blazer he keeps
    keeps its navy blazers. And the product a piece is locked to stays, whatever its colour: "Lock this choice"
    or a product chosen by hand before he refused navy is still his choice, until he unlocks it.
    """
    if slot["colour"] in refused:
        return candidates_for(pool, slot, collector)
    found = candidates_for(pool, slot, collector, refused)
    pick = slot.get("pick") if slot.get("locked") else None
    if pick and all(c["id"] != pick for c in found):
        found += [c for c in candidates_for(pool, slot, collector) if c["id"] == pick]
    return found


def kept_for_its_lock(slot: dict, *products: dict) -> bool:
    """Whether one of these products of a piece is among its options only because the piece is (or was) locked to
    it (see _for_piece): its colour is one the customer refused, and the piece's own colour is not. A product he
    added himself by its link is his own option, whatever its colour."""
    refused = refused_colours()
    return slot["colour"] not in refused and any(
        product.get("source") != "manual" and matching.refused(product.get("colour"), refused) for product in products)


def refresh_customer() -> None:
    """Rebuild the signed-in customer's candidates if the shared list changed since they last got it, or is now
    read with a correction they have not had yet (a new REVISION), or for other stores (see revision)."""
    pool = load()
    if pool is None or db.get_setting("pool") == revision(pool):
        return
    gone = _stores_gone()
    built = build_catalog(db.list_slots(), catalog.load())
    if built:
        catalog.save(built)
        db.set_setting("pool", revision(pool))
        if gone:
            _picked_again(gone)


# ── a store that is no longer offered ─────────────────────────────────────────

GONE_SETTING = "stores_gone"     # what the Wardrobe page says once, after a store went (see gone_message)


def _stores_gone() -> dict[str, list[str]] | None:
    """Before a customer's products are rebuilt: the stores among them that are no longer offered (programmes.py),
    and his pieces that were picked from them. Those are unlocked here, so that the rebuilt products pick them
    again: a piece locked to such a product, by "Lock this choice" or a product he chose himself, is automatic
    again. Owned pieces are not touched. None when no store went, or when he was on the demo data (invented
    products, which the real ones replace in any case)."""
    stored = catalog.stored()
    if stored.get("source") != "collected":
        return None
    gone = {c["store"] for c in stored.get("candidates", []) if c.get("store")} - set(programmes.offered())
    if not gone:
        return None
    from . import selection        # here: selection itself builds on this module

    before = selection.build(catalogue=stored)      # the pieces as he saw them until now
    picked = [view.slot["id"] for view in before.slots
              if view.state != "owned" and view.chosen and view.chosen.data.get("store") in gone]
    their_ids = {c.get("id") for c in stored.get("candidates", []) if c.get("store") in gone}
    for slot in db.list_slots():
        if slot["locked"] and slot["pick"] in their_ids:
            db.update_slot(slot["id"], locked=False, pick=None)
            if slot["id"] not in picked and not slot["owned"]:
                picked.append(slot["id"])
    return {"stores": sorted(gone), "pieces": picked}


def _picked_again(gone: dict[str, list[str]]) -> None:
    """After the rebuild: note for the Wardrobe page what went, how many pieces were picked again, and how many of
    those have nothing to pick now."""
    if not gone["pieces"]:
        return
    from . import selection

    now = selection.build()
    empty = sum(1 for view in now.slots if view.slot["id"] in gone["pieces"] and view.chosen is None)
    db.set_setting(GONE_SETTING, {"stores": gone["stores"], "pieces": len(gone["pieces"]), "empty": empty})


def gone_message(keep: bool = False) -> str:
    """The one plain message about stores that are no longer offered, once (or "" when there is none): "Zara has
    no partner programme, so Capsule no longer shows its products: 17 pieces were picked again." The Wardrobe page
    shows it the first time it is opened after the change; `keep` leaves it to be shown again."""
    note = db.get_setting(GONE_SETTING)
    if not isinstance(note, dict) or not note.get("pieces"):
        return ""
    if not keep:
        db.set_setting(GONE_SETTING, None)
    stores, n, empty = note.get("stores", []), int(note["pieces"]), int(note.get("empty") or 0)
    has = "has" if len(stores) == 1 else "have"
    its = "its" if len(stores) == 1 else "their"
    words = (f"{programmes.names(stores)} {has} no partner programme, so {settings.SITE_NAME} no longer shows "
             f"{its} products: {n} {'piece was' if n == 1 else 'pieces were'} picked again")
    if empty:
        words += f", and {empty} {'has' if empty == 1 else 'have'} nothing in {settings.SITE_NAME}'s product list yet"
    return words + "."
