"""The command line for the store feeds (added to `python -m wardrobe` in __main__.py):

    python -m wardrobe stores                       the stores, with status, products and dates
    python -m wardrobe stores sync                  copy config/feeds.toml into the database
    python -m wardrobe stores end KEY               delete all of a store's products now, and mark it ended
    python -m wardrobe feeds [--store KEY] [--force] [--from FILE]    fetch and import the feeds
"""
from __future__ import annotations

import argparse
import sys

from .. import config, db
from . import refresh, registry


def add(sub) -> None:
    """Add `stores` and `feeds` to the commands of `python -m wardrobe`."""
    p_stores = sub.add_parser("stores", help="the stores whose product feeds Capsule may use (config/feeds.toml)")
    p_stores.set_defaults(func=list_stores)
    what = p_stores.add_subparsers(title="what to do (without one: list them)")
    p_sync = what.add_parser("sync", help="copy config/feeds.toml into the database (never deletes products)")
    p_sync.add_argument("--reopen", action="append", default=[], metavar="KEY",
                        help="let a store that was ended take the status the file gives it again")
    p_sync.set_defaults(func=sync)
    p_end = what.add_parser("end", help="a programme ended or the store asked: delete all its products now")
    p_end.add_argument("key", help="the store's key, as `python -m wardrobe stores` lists it")
    p_end.set_defaults(func=end)

    p_feeds = sub.add_parser("feeds", help="fetch the approved stores' feeds when they changed, and import them")
    p_feeds.add_argument("--store", metavar="KEY", help="only this store")
    p_feeds.add_argument("--force", action="store_true", help="download even when the feed says it has not changed "
                              "(the networks' download limits still apply)")
    p_feeds.add_argument("--from", dest="from_file", metavar="FILE",
                         help="import this file for the store given with --store (an approved store, or an "
                              "invented sample); nothing is downloaded. The feed is dated by the newest time "
                              "its products carry, or by the file's own time if they carry none")
    p_feeds.set_defaults(func=feeds)


def list_stores(args: argparse.Namespace) -> None:
    db.init()
    print("\n".join(registry.table()))


def sync(args: argparse.Namespace) -> None:
    db.init()
    try:
        lines = registry.sync(reopen=args.reopen)
    except config.ConfigError as problem:
        sys.exit(str(problem))
    print("\n".join(lines) or "config/feeds.toml lists no stores.")


def end(args: argparse.Namespace) -> None:
    db.init()
    try:
        gone = registry.end(args.key)
    except LookupError:
        sys.exit(f"There is no store called {args.key!r}. The stores: python -m wardrobe stores")
    print(f"{args.key}: ended, {gone} products deleted. Set its status to \"ended\" in config/feeds.toml too.")


def feeds(args: argparse.Namespace) -> None:
    db.init()
    try:
        failed = refresh.run(args.store, force=args.force, from_file=args.from_file)
    except refresh.FeedError as problem:
        sys.exit(str(problem))
    if failed:
        sys.exit(f"{failed} store{'s' if failed != 1 else ''} failed; the reason is above and in `python -m wardrobe stores`.")
