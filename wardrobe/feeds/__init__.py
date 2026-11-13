"""The store feeds: products from the stores whose affiliate programmes license Stilsmith their feed.

This is separate from the collector (collect/, `python -m wardrobe refresh`), which reads store
pages on the owner's own machine. Nothing here reads a store's pages, and nothing here comes from
the collector or its snapshot: products arrive only in a feed that a network hands to an approved
partner, or in a file the owner imports by hand.

    registry.py      config/feeds.toml -> the `stores` table; the list; ending a store
    refresh.py       fetch a feed when it changed, import it, replace that store's products at once
    rows.py          what every importer shares: prices, times, stock, sizes, the products row
    google.py        Google Shopping format: Awin's product API (JSON Lines), Webgains and others (CSV, TSV)
    awin_csv.py      Awin's standard CSV
    tradedoubler.py  Tradedoubler's Products API (JSON)
    commands.py      `python -m wardrobe stores ...` and `python -m wardrobe feeds ...`

Rakuten's pipe-delimited files (where COS is) come in a later round.
"""
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from . import awin_csv, google, tradedoubler
from .rows import Result

# feed_format in config/feeds.toml -> the importer that reads it
FORMATS: dict[str, Callable[[Path], Result]] = {
    "google": google.read,
    "awin_csv": awin_csv.read,
    "tradedoubler_json": tradedoubler.read,
}
