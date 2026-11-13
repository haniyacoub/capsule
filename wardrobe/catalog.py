"""What the stores sell: data/catalog.json.

Shape of the file:

    {
      "source": "mock" | "collected",
      "collected_at": "2026-11-11T15:00:00+01:00",
      "stores": {"weekday": {"status": "ok", "message": "…", "checked_at": "…"}},
      "candidates": [
        {
          "id": "weekday-1234567001", "slot_id": "grey-merino-jumper", "store": "weekday",
          "name": "…", "slug": "…", "price": 69.95, "currency": "EUR",
          "colour": "Grau", "colour_hex": "#8d8f92",
          "composition_text": "Aussen: 100% wolle",
          "fit": "regular", "description": "…",
          "sizes_all": ["S", "M", "L"], "sizes_in_stock": ["S", "L"],
          "url": "https://…", "image_url": "https://…",
          "source": "collected" | "manual" | "mock",
          "manual": {"composition_text": "…"},      # details you typed in; they win
          "collected_at": "…"
        }
      ]
    }

`python -m wardrobe refresh` rewrites the collected candidates. Candidates you
added by hand ("source": "manual") and details you typed in ("manual": {…})
are kept.

Only the products of stores customers are offered are ever read (programmes.py):
a store without a partner programme is skipped, and left out when the
catalogue is next saved. What you added yourself by its link is never deleted
for it: it is set aside (set_aside), kept in your catalogue but never among a
piece's options, in an outfit or on the shopping list, and it comes back if
the store is offered again. Your piece's page lists it, to remove.
"""
from __future__ import annotations

import json
import os
from datetime import datetime

from . import db, paths, programmes, settings

_cache: tuple[int, dict] | None = None

def empty() -> dict:
    return {"source": "empty", "collected_at": None, "candidates": []}


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def load() -> dict:
    """The catalogue: the local file, or in production the signed-in customer's own, with only the products
    of stores customers are offered (programmes.py)."""
    return programmes.only_offered(stored())


def stored() -> dict:
    """The catalogue as it is stored, the products of every store in it: what the customer had until now."""
    global _cache
    if settings.PRODUCTION:
        data = db.get_catalog() or empty()
        data.setdefault("candidates", [])
        return data
    try:
        mtime = paths.CATALOG_PATH.stat().st_mtime_ns
    except FileNotFoundError:
        return empty()
    if _cache and _cache[0] == mtime:
        return _cache[1]
    with paths.CATALOG_PATH.open(encoding="utf-8") as f:
        data = json.load(f)
    data.setdefault("candidates", [])
    _cache = (mtime, data)
    return data


def save(catalog: dict) -> None:
    """Write atomically, so a crash mid-write can't leave half a file."""
    global _cache
    if settings.PRODUCTION:
        db.put_catalog(catalog)
        return
    paths.DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = paths.CATALOG_PATH.with_suffix(".json.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(catalog, f, ensure_ascii=False, indent=2)
    os.replace(tmp, paths.CATALOG_PATH)
    _cache = None


def update(change) -> dict:
    """Read the file, apply `change(catalog)`, write it back. Returns the catalogue.

    Both the app and the collector write this way, so neither overwrites what
    the other saved a moment ago. The change is given what is kept (kept): the
    products of the stores customers are offered and, set aside, what you added
    yourself from a store that no longer is, so that removing a piece's
    products (prune), or one of them (app.slot_remove), removes those too.
    """
    cat = kept(stored())
    change(cat)
    save(cat)
    return cat


def _yours(cand: dict) -> bool:
    return cand.get("source") == "manual"


def kept(catalogue: dict) -> dict:
    """A catalogue as it is saved: the products of the stores customers are offered (programmes.only_offered),
    and every product you added yourself by its link, from any store. A new dict; the one given is left as it is."""
    out = programmes.only_offered(catalogue)
    offered = programmes.offered()
    out["candidates"] = [c for c in catalogue.get("candidates", []) if c.get("store") in offered or _yours(c)]
    return out


def set_aside(slot_id: str) -> list[dict]:
    """What you added to this piece yourself, by its link, from a store that is no longer offered (programmes.py):
    kept in your catalogue, but never among the piece's options, in an outfit or on the shopping list, until the
    store is offered again. The piece's page lists it, with a button to remove it (_set_aside.html)."""
    offered = programmes.offered()
    return [c for c in stored().get("candidates", [])
            if c.get("slot_id") == slot_id and _yours(c) and c.get("store") not in offered]


def start_collected(cat: dict) -> None:
    """Switch from demo data to real data: the invented items go, yours stay."""
    if cat.get("source") != "collected":
        cat["candidates"] = [c for c in cat.get("candidates", []) if c.get("source") == "manual"]
        cat["source"] = "collected"
        cat["stores"] = {}
        cat.pop("note", None)


def replace_collected(cat: dict, store: str, slot_id: str, found: list[dict]) -> None:
    """Swap in freshly collected candidates for one store and slot."""
    def mine(c: dict) -> bool:
        return c.get("store") == store and c.get("slot_id") == slot_id and c.get("source") != "manual"

    typed_in = {c["id"]: c["manual"] for c in cat["candidates"] if mine(c) and c.get("manual")}
    cat["candidates"] = [c for c in cat["candidates"] if not mine(c)]
    for c in found:
        if c["id"] in typed_in:
            c["manual"] = typed_in[c["id"]]
        cat["candidates"].append(c)


def prune(cat: dict, slot_ids: set[str]) -> None:
    """Forget candidates of slots that no longer exist."""
    cat["candidates"] = [c for c in cat.get("candidates", []) if c.get("slot_id") in slot_ids]


def find(cat: dict, slot_id: str, cand_id: str) -> dict | None:
    return next((c for c in cat.get("candidates", [])
                 if c.get("slot_id") == slot_id and c.get("id") == cand_id), None)


def by_slot(catalog: dict) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for cand in catalog.get("candidates", []):
        out.setdefault(cand.get("slot_id", ""), []).append(cand)
    return out


def collected_label(catalog: dict) -> str:
    """'11 Nov 2026, 15:02' for the page footer."""
    stamp = catalog.get("collected_at")
    if not stamp:
        return "never"
    try:
        return datetime.fromisoformat(stamp).strftime("%-d %b %Y, %H:%M")
    except ValueError:
        return stamp
