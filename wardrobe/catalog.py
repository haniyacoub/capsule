"""What the stores sell: data/catalog.json.

Shape of the file:

    {
      "source": "mock" | "collected",
      "collected_at": "2026-11-11T15:00:00+01:00",
      "stores": {"zara": {"status": "ok", "message": "…", "checked_at": "…"}},
      "candidates": [
        {
          "id": "zara-01234567-800", "slot_id": "grey-merino-jumper", "store": "zara",
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
"""
from __future__ import annotations

import json
import os
from datetime import datetime

from . import db, paths, settings

_cache: tuple[int, dict] | None = None

def empty() -> dict:
    return {"source": "empty", "collected_at": None, "candidates": []}


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def load() -> dict:
    """The catalogue: the local file, or in production the signed-in customer's own."""
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
    the other saved a moment ago.
    """
    cat = load()
    change(cat)
    save(cat)
    return cat


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
