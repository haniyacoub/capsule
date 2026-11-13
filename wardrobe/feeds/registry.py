"""The store registry: the stores in config/feeds.toml, copied into the database's `stores` table.

    python -m wardrobe stores sync       add the stores listed in config/feeds.toml, update their settings
    python -m wardrobe stores            list them: status, products, feed date, stale or failed
    python -m wardrobe stores end KEY    a programme ended or the store asked: all its products go now

Syncing never deletes a store or its products: a store that is no longer in the file stays as it
was, and is listed. Ending one is always a separate, explicit step, and it stays ended until it is
reopened on purpose (`stores sync --reopen KEY`).

The sample stores in the file (sample = true) are invented, for trying the importers on your own
machine; in production they are left out.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta

from .. import config, db, settings
from . import FORMATS

STATUSES = ("none", "applied", "approved", "refused", "ended")
NETWORKS = ("awin", "tradedoubler", "rakuten", "webgains", "impact")
DEFAULT_REFRESH_HOURS = 24
_KEY = re.compile(r"[a-z0-9][a-z0-9-]{0,39}")
_TEXT = ("label", "programme_id", "feed_location", "delivery_note", "disclaimer")
_ALLOWED = {*_TEXT, "network", "status", "feed_format", "rules", "sample"}


def check(data: dict) -> None:
    """Refuse a file with a mistake in it, naming the store and the setting."""
    stores = config.table(data.get("stores", {}), "stores")
    for key, entry in stores.items():
        where = f"stores.{key}"
        if not _KEY.fullmatch(key):
            raise config.ConfigError(f"[{where}]: a store's key is lower-case letters, digits and dashes")
        entry = config.table(entry, where)
        unknown = sorted(set(entry) - _ALLOWED)
        if unknown:
            raise config.ConfigError(f"[{where}] has a setting this does not know: {', '.join(unknown)}")
        if not isinstance(entry.get("label"), str) or not entry["label"].strip():
            raise config.ConfigError(f"[{where}] needs a label: the store's name as people read it")
        for name in _TEXT:
            if not isinstance(entry.get(name, ""), (str, int)) or isinstance(entry.get(name), bool):
                raise config.ConfigError(f"{where}.{name} must be text")
        for name, allowed in (("status", STATUSES), ("network", NETWORKS), ("feed_format", tuple(FORMATS))):
            value = entry.get(name, "none" if name == "status" else None)
            if value is not None and value not in allowed:
                raise config.ConfigError(f"{where}.{name} is {value!r}; it can be {' | '.join(allowed)}")
        hours = config.table(entry.get("rules", {}), f"{where}.rules").get("refresh_hours", DEFAULT_REFRESH_HOURS)
        if config.number(hours, f"{where}.rules.refresh_hours") <= 0:
            raise config.ConfigError(f"{where}.rules.refresh_hours must be more than 0")


def load(data: dict | None = None) -> dict[str, dict]:
    """The stores in config/feeds.toml (or in `data`, for the tests), as the database keeps them."""
    if data is None:
        data = config.load("feeds.toml", check)
    else:
        check(data)
    out = {}
    for key, entry in data.get("stores", {}).items():
        values: dict = {name: str(entry.get(name, "")).strip() or None for name in _TEXT}   # a number, too, as text
        values.update(network=entry.get("network"), status=entry.get("status", "none"),
                      feed_format=entry.get("feed_format"), rules=dict(entry.get("rules", {})))
        if entry.get("sample"):
            values["rules"]["sample"] = True
        out[key] = values
    return out


def sync(data: dict | None = None, reopen: tuple[str, ...] | list[str] = ()) -> list[str]:
    """Copy the file into the `stores` table. Returns what happened, one line per store."""
    lines = []
    listed = load(data)
    for key, values in listed.items():
        if values["rules"].get("sample") and settings.PRODUCTION:
            lines.append(f"{key}: an invented sample store, left out in production")
            continue
        old = db.get_store(key)
        note = ""
        if old and old["status"] == "ended" and values["status"] != "ended" and key not in reopen:
            values["status"] = "ended"
            note = (" (ended with `stores end`, so it stays ended. If its programme takes Capsule back:"
                    f" python -m wardrobe stores sync --reopen {key})")
        lines.append(f"{key}: {db.save_store(key, values)}{note}")
        if values["status"] == "ended" and old and old["products"]:
            lines.append(f"{key}: marked ended but still has {old['products']} products. "
                         f"Delete them with: python -m wardrobe stores end {key}")
    for store in db.list_stores():
        if store["key"] not in listed:
            lines.append(f"{store['key']}: in the database but no longer in config/feeds.toml; left as it is")
    return lines


def stale(store: dict, now: datetime | None = None) -> bool:
    """True for an approved store whose feed is older than its refresh hours plus a day, or that
    has none yet. Its prices may be out of date, so later rounds leave it out of the outfits."""
    if store["status"] != "approved":
        return False
    when = store.get("last_feed_update") or store.get("last_import_at")
    if not when:
        return True
    hours = float(store["rules"].get("refresh_hours", DEFAULT_REFRESH_HOURS))
    return (now or datetime.now().astimezone()) - datetime.fromisoformat(when) > timedelta(hours=hours + 24)


def table(now: datetime | None = None) -> list[str]:
    """`python -m wardrobe stores`: one line per store, and a second one for a problem."""
    stores = db.list_stores()
    if not stores:
        return ["No stores yet. List them in config/feeds.toml, then run: python -m wardrobe stores sync"]
    lines = [f"{'store':<16}{'status':<10}{'network':<14}{'products':>9}  {'feed of':<18}imported"]
    for s in stores:
        lines.append(f"{s['key']:<16}{s['status']:<10}{s['network'] or '-':<14}{s['products']:>9}  "
                     f"{_short(s['last_feed_update']):<18}{_short(s['last_import_at']):<18}".rstrip())
        if stale(s, now):
            lines.append("    STALE: " + ("no feed imported yet" if not (s["last_feed_update"] or s["last_import_at"])
                                         else "the feed is older than its refresh hours plus a day"))
        if s["last_error"]:
            lines.append(f"    last refresh failed: {s['last_error']}")
    return lines


def _short(when: str | None) -> str:
    return when[:16].replace("T", " ") if when else "-"


def end(key: str) -> int:
    """Delete all of a store's products and mark it ended. Returns how many went."""
    if db.get_store(key) is None:
        raise LookupError(key)
    return db.end_store(key)
