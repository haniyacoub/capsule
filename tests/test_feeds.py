"""The store feeds (wardrobe/feeds/), without touching the internet.

The files in tests/fixtures/feeds are invented: three made-up stores (Musterhaus, Nordfaden and
Kleiderwerk) with made-up products, prices, ids and example.com / example.org addresses, one for
each format the importers read. No test opens a network connection: the downloader's opener is
replaced in every test, and a test fails if it was used, except where a test hands it a file://
address or a stand-in server on this computer on purpose.
"""
import contextlib
import email.utils
import fcntl
import gzip
import io
import json
import os
import re
import shutil
import sqlite3
import tempfile
import threading
import time
import tomllib
import unittest
import urllib.request
from collections import Counter
from contextlib import closing
from datetime import datetime, timedelta, timezone
from html import unescape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from wardrobe import config, db, owner, paths, settings
from wardrobe.__main__ import main
from wardrobe.app import create_app
from wardrobe.feeds import awin_csv, google, refresh, registry, rows, tradedoubler

from .test_production import HX, PASSWORD, ProductionCase
from .test_production import words as page_text

FEEDS = Path(__file__).parent / "fixtures" / "feeds"
MUSTERHAUS = [f"MH-1001-{s}" for s in "LMS"] + ["MH-2001-M", "MH-3001-3232", "MH-4001", "MH-5002-M", "MH-6002-43"]


def fresh_database() -> None:
    for suffix in ("", "-wal", "-shm"):
        paths.DB_PATH.with_name(paths.DB_PATH.name + suffix).unlink(missing_ok=True)


def sample_rows() -> list[dict]:
    """Musterhaus's products, ready for the products table as an import would write them."""
    found = google.read(FEEDS / "musterhaus.jsonl").rows
    return [{**row, "imported_at": "2026-11-13T06:00:00+01:00"} for row in found]


def a_store(**values) -> dict:
    """Settings for a store, as config/feeds.toml would give them."""
    return {"label": "A test store", "network": None, "programme_id": None, "status": "approved",
            "feed_format": "google", "feed_location": None, "delivery_note": None, "disclaimer": None,
            "rules": {}, **values}


# What a database made by version 4 holds: wardrobe/db.py's SCHEMA and SCHEMA_PICTURES as they were
# at version 4, copied here word for word. Never edit it: databases made by version 4 are still in use.
VERSION_4 = """
CREATE TABLE users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    email         TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash TEXT NOT NULL,
    created_at    TEXT NOT NULL,
    session_epoch INTEGER NOT NULL DEFAULT 0     -- raised to sign out every device
);
CREATE TABLE settings (
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    key     TEXT NOT NULL,
    value   TEXT NOT NULL,              -- JSON: profile, mode, threshold, …
    PRIMARY KEY (user_id, key)
);
CREATE TABLE slots (
    user_id   INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    id        TEXT NOT NULL,            -- stable slug, e.g. 'white-tee'
    position  INTEGER NOT NULL,
    name      TEXT NOT NULL,
    category  TEXT NOT NULL,            -- a key from garments.py
    colour    TEXT NOT NULL,            -- a key from colours.py
    keywords  TEXT NOT NULL DEFAULT '',
    qty       INTEGER NOT NULL DEFAULT 1,
    owned     INTEGER NOT NULL DEFAULT 0,   -- 1 = already own, costs nothing
    locked    INTEGER NOT NULL DEFAULT 0,   -- 1 = the price level must not change it
    pick      TEXT,                     -- candidate id, set while locked
    PRIMARY KEY (user_id, id)
);
CREATE TABLE saved_outfits (
    user_id   INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    key       TEXT NOT NULL,            -- fingerprint of the pieces
    saved_at  TEXT NOT NULL,
    label     TEXT NOT NULL,
    pieces    TEXT NOT NULL,            -- JSON snapshot, so a favourite survives a refresh
    PRIMARY KEY (user_id, key)
);
CREATE TABLE catalogs (                 -- production: each customer's candidates (JSON)
    user_id    INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    updated_at TEXT NOT NULL,
    data       TEXT NOT NULL
);
CREATE TABLE login_attempts (           -- failed logins, to slow down guessing
    email TEXT NOT NULL,
    ip    TEXT NOT NULL,
    at    REAL NOT NULL
);
CREATE INDEX login_attempts_at ON login_attempts (at);
CREATE TABLE signups (ip TEXT NOT NULL, at REAL NOT NULL);
CREATE TABLE reset_tokens (             -- only a hash of each emailed token is kept
    token_hash TEXT PRIMARY KEY,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    expires_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS looks (      -- one row per picture, the files are in <data>/looks/
    key        TEXT PRIMARY KEY,        -- fingerprint of what was sent to the image service
    user_id    INTEGER REFERENCES users(id) ON DELETE CASCADE,   -- only for a picture of someone's own photo
    status     TEXT NOT NULL,           -- waiting (its turn) | working | ready | failed
    started_at REAL NOT NULL,
    file       TEXT,                    -- the picture, once there is one
    error      TEXT,                    -- why the last attempt failed
    service    TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS look_requests (   -- when a picture was asked for: the daily limits
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    at      REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS look_requests_at ON look_requests (at);
"""


class FeedCase(unittest.TestCase):
    def setUp(self):
        fresh_database()
        db.init()
        self.folder = Path(tempfile.mkdtemp(prefix="capsule-feeds-"))
        self.addCleanup(shutil.rmtree, self.folder, ignore_errors=True)
        (paths.DATA_DIR / "feeds" / "asked.json").unlink(missing_ok=True)     # when each network was last asked
        # The downloader's way out is replaced: a test that reaches it without meaning to fails.
        self.real_opener = refresh._opener
        patcher = mock.patch.object(refresh, "_opener", side_effect=AssertionError("a network connection was opened"))
        self.opener = patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.no_network_unless_meant)
        self.network_meant = False

    def no_network_unless_meant(self):
        if not self.network_meant:
            self.assertFalse(self.opener.called, "a test opened a network connection")

    def cli(self, *argv: str) -> str:
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            main(list(argv))
        return out.getvalue()

    def ids(self, store: str) -> list[str]:
        return sorted(p["product_id"] for p in db.store_products(store))

    def write(self, name: str, text: str) -> Path:
        path = self.folder / name
        path.write_text(text, encoding="utf-8")
        return path


# ── the tables ────────────────────────────────────────────────────────────────

class Schema(FeedCase):
    def tables(self, con) -> set[str]:
        return {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}

    def test_a_fresh_database_has_the_store_tables(self):
        with closing(sqlite3.connect(paths.DB_PATH)) as con:
            self.assertLessEqual({"stores", "products", "users", "looks"}, self.tables(con))
            self.assertEqual(con.execute("PRAGMA user_version").fetchone()[0], db.SCHEMA_VERSION)
            columns = [r[1] for r in con.execute("PRAGMA table_info(products)")]
        self.assertEqual(columns, list(db.PRODUCT_COLUMNS))

    def test_a_database_at_version_4_gains_the_new_tables_and_nothing_else_changes(self):
        # The owner's own server runs a database made by version 4: the tables below, holding data.
        fresh_database()
        with closing(sqlite3.connect(paths.DB_PATH)) as con:
            for statement in VERSION_4.split(";"):
                if statement.strip():
                    con.execute(statement)
            con.executescript("""
                PRAGMA journal_mode = WAL;
                INSERT INTO users (id, email, password_hash, created_at) VALUES
                    (1, 'local@localhost', '', '2026-11-11T10:00:00+01:00'),
                    (2, 'someone@example.com', 'a hash', '2026-11-12T10:00:00+01:00');
                INSERT INTO settings VALUES (2, 'mode', '"cheapest"');
                INSERT INTO slots (user_id, id, position, name, category, colour) VALUES (2, 'white-tee', 0, 'White tee', 'tee', 'white');
                INSERT INTO saved_outfits VALUES (2, 'abc', '2026-11-12T12:00:00+01:00', 'Everyday', '[]');
                INSERT INTO catalogs VALUES (2, '2026-11-12T12:00:00+01:00', '{"candidates": []}');
                INSERT INTO login_attempts VALUES ('someone@example.com', '127.0.0.1', 1000.5);
                INSERT INTO signups VALUES ('127.0.0.1', 1000.5);
                INSERT INTO reset_tokens VALUES ('a token hash', 2, 99999999999.0);
                INSERT INTO looks (key, user_id, status, started_at, file) VALUES ('k1', NULL, 'ready', 1000.5, 'k1.png');
                INSERT INTO look_requests (user_id, at) VALUES (2, 1000.5);
                PRAGMA user_version = 4;
            """)
            old_tables = self.tables(con)
            before = set(con.execute("SELECT type, name, tbl_name, sql FROM sqlite_master"))
            rows_before = {t: sorted(con.execute(f"SELECT * FROM {t}").fetchall()) for t in old_tables}  # nosec

        db.init()
        with closing(sqlite3.connect(paths.DB_PATH)) as con:
            after = set(con.execute("SELECT type, name, tbl_name, sql FROM sqlite_master"))
            self.assertEqual(before - after, set(), "no table or index of version 4 was changed or removed")
            self.assertEqual(sorted((kind, name) for kind, name, _, _ in after - before),
                             [("index", "products_by_group"), ("index", "sqlite_autoindex_products_1"),
                              ("index", "sqlite_autoindex_stores_1"), ("table", "owners"), ("table", "products"),
                              ("table", "stores")])
            self.assertEqual({t: sorted(con.execute(f"SELECT * FROM {t}").fetchall()) for t in old_tables},  # nosec
                             rows_before, "every row is as it was")
            self.assertEqual(con.execute("PRAGMA user_version").fetchone()[0], 6)
        db.init()                                                   # starting again changes nothing
        with closing(sqlite3.connect(paths.DB_PATH)) as con:
            self.assertEqual(set(con.execute("SELECT type, name, tbl_name, sql FROM sqlite_master")), after)
        with db.as_user(2):
            self.assertEqual(db.get_setting("mode"), "cheapest")
            self.assertEqual([s["id"] for s in db.list_slots()], ["white-tee"])


    def test_a_database_at_version_5_gains_the_owners_table_and_nothing_else_changes(self):
        # A database made by version 5 (the store tables, with stores and products in them).
        fresh_database()
        with closing(sqlite3.connect(paths.DB_PATH)) as con:
            for statement in (VERSION_4 + db.SCHEMA_FEEDS).split(";"):
                if statement.strip():
                    con.execute(statement)
            con.executescript("""
                PRAGMA journal_mode = WAL;
                INSERT INTO users (id, email, password_hash, created_at) VALUES (1, 'local@localhost', '', 'x'), (2, 'someone@example.com', 'a hash', 'x');
                INSERT INTO stores (key, label, status) VALUES ('musterhaus', 'Musterhaus', 'approved');
                INSERT INTO products (store, product_id, name, price, currency, buy_link, imported_at)
                    VALUES ('musterhaus', 'MH-1', 'Hemd', 39.95, 'EUR', 'https://shop.example.com/1', 'x');
                PRAGMA user_version = 5;
            """)
            before = set(con.execute("SELECT type, name, tbl_name, sql FROM sqlite_master"))
            rows_before = {t: con.execute(f"SELECT * FROM {t}").fetchall() for t in ("users", "stores", "products")}  # nosec
        db.init()
        with closing(sqlite3.connect(paths.DB_PATH)) as con:
            after = set(con.execute("SELECT type, name, tbl_name, sql FROM sqlite_master"))
            self.assertEqual(before - after, set(), "no table or index of version 5 was changed or removed")
            self.assertEqual(sorted((kind, name) for kind, name, _, _ in after - before), [("table", "owners")])
            self.assertEqual({t: con.execute(f"SELECT * FROM {t}").fetchall() for t in rows_before}, rows_before)  # nosec
            self.assertEqual(con.execute("PRAGMA user_version").fetchone()[0], 6)
            self.assertEqual(con.execute("SELECT COUNT(*) FROM owners").fetchone()[0], 0, "nobody is an owner by itself")


# ── reading the values ────────────────────────────────────────────────────────

class Values(unittest.TestCase):
    def test_prices_in_every_spelling(self):
        for given, wanted in [
            ("39,95 EUR", (39.95, "EUR")), ("39.95 EUR", (39.95, "EUR")), (39.95, (39.95, None)), (40, (40.0, None)),
            ("EUR 39.95", (39.95, "EUR")), ("€39,95", (39.95, "EUR")), ("39.95EUR", (39.95, "EUR")),
            ("1.299,00 EUR", (1299.0, "EUR")), ("1,299.00 EUR", (1299.0, "EUR")), ("1.299 EUR", (1299.0, "EUR")),
            ("19 GBP", (19.0, "GBP")), ("39.95 incl. VAT", (39.95, None)),
            ({"value": "39.95", "currency": "EUR"}, (39.95, "EUR")), ({"value": 12}, (12.0, None)),
            ("", (None, None)), (None, (None, None)), ("free", (None, None)), (True, (None, None)),
            (float("nan"), (None, None)), ("1,2.3,4 EUR", (None, None)), ("1.2,3.4 EUR", (None, None)),
        ]:
            self.assertEqual(rows.parse_price(given), wanted, given)
        self.assertEqual(rows.parse_price(39.95, "EUR"), (39.95, "EUR"), "a number takes the feed's currency")

    def test_a_product_needs_an_id_a_name_a_price_above_zero_and_a_web_link(self):
        good = {"product_id": "1", "name": "Shirt", "price": "10 EUR", "buy_link": "https://shop.example.com/1"}
        self.assertEqual(rows.product(**good)["currency"], "EUR")
        for change, reason in [({"product_id": " "}, "without an id"), ({"name": None}, "without a name"),
                               ({"price": "0.00 EUR"}, "without a price"), ({"price": "on request"}, "without a price"),
                               ({"buy_link": ""}, "without a link"), ({"buy_link": "javascript:alert(1)"}, "without a link")]:
            with self.assertRaises(rows.Skip) as skipped:
                rows.product(**{**good, **change})
            self.assertEqual(str(skipped.exception), reason, change)

    def test_a_photo_address_is_kept_exactly_as_given_or_not_at_all(self):
        base = {"product_id": "1", "name": "Shirt", "price": "10 EUR", "buy_link": "https://shop.example.com/1"}
        odd = "https://images.example.com/a b/Photo.JPG?w=600&crop=none"
        self.assertEqual(rows.product(**base, image_url=odd)["image_url"], odd)
        self.assertIsNone(rows.product(**base, image_url="file:///etc/passwd")["image_url"])

    def test_stock_words_numbers_and_silence(self):
        for given, wanted in [(("in_stock",), True), (("out_of_stock",), False), (("preorder",), False),
                              (("backorder",), False), (("in stock",), True), (("Lieferbar",), True),
                              (("nicht lieferbar",), False), (("1",), True), (("0",), False), (("yes",), True),
                              (("no",), False), ((None, "12"), True), (("", 0), False), ((None, None), None),
                              (("ask in the shop",), None), ((None, "maybe", "out of stock"), False)]:
            self.assertEqual(rows.in_stock(*given), wanted, given)

    def test_sizes_and_sizes_in_stock(self):
        self.assertEqual(rows.split_sizes("S, M,L|XL;M"), ["S", "M", "L", "XL"])
        self.assertEqual(rows.split_sizes("32/34"), ["32/34"], "a slash belongs to the size")
        self.assertEqual(rows.size_stock("S:available|M:out of stock|L:"), {"S": True, "M": False})

    def test_times(self):
        noon = datetime(2026, 11, 12, 6, 0, tzinfo=timezone.utc)
        for given in ("2026-11-12T06:00:00Z", "2026-11-12T07:00:00+01:00", 1794463200, 1794463200000,
                      "1794463200000", "Thu, 12 Nov 2026 06:00:00 GMT"):
            self.assertEqual(datetime.fromisoformat(rows.parse_time(given)), noon, given)
        for given in (None, "", "soon", True, 1e300, -1e300, float("inf"), float("nan"), "9999-12-31T23:59:59-12:00"):
            self.assertIsNone(rows.parse_time(given), given)          # not a time, or none a calendar here can hold

    def test_a_sale_price_counts_only_below_the_price(self):
        base = {"product_id": "1", "name": "Shirt", "price": "10 EUR", "buy_link": "https://shop.example.com/1"}
        for sale, kept in (("8 EUR", 8.0), ("10 EUR", None), ("15 EUR", None), ("0 EUR", None), ("soon", None), (None, None)):
            self.assertEqual(rows.product(**base, sale_price=sale)["sale_price"], kept, sale)

    def test_a_sale_runs_between_its_dates(self):
        def at(when: str) -> datetime:
            return datetime.fromisoformat(when)

        november = "2026-11-20T00:00+01:00/2026-11-30T23:59+01:00"          # Google's own way of writing it
        for dates in (november, "2026-11-20T00:00+0100/2026-11-30T23:59+0100", " 2026-11-20T00:00+01:00 / 2026-11-30T23:59+01:00 "):
            for when, runs in (("2026-11-19T23:59+01:00", False),            # before
                               ("2026-11-20T00:00+01:00", True),             # from its first minute
                               ("2026-11-19T23:30+00:00", True),             # the same moment written in another zone
                               ("2026-11-25T12:00+01:00", True),             # inside
                               ("2026-11-30T23:59+01:00", True),             # to its last
                               ("2026-12-01T00:00+01:00", False)):           # after
                self.assertEqual(rows.sale_runs(dates, at(when)), runs, f"{dates} at {when}")
        # Open-ended: no start, or no end.
        self.assertTrue(rows.sale_runs("2026-11-20T00:00+01:00/", at("2099-01-01T00:00+00:00")))
        self.assertFalse(rows.sale_runs("2026-11-20T00:00+01:00/", at("2026-11-19T12:00+01:00")))
        self.assertTrue(rows.sale_runs("/2026-11-30T23:59+01:00", at("2020-01-01T00:00+00:00")))
        self.assertFalse(rows.sale_runs("/2026-11-30T23:59+01:00", at("2026-12-01T00:00+01:00")))
        # A day alone as the end: all of that day, in this computer's time.
        last_evening = datetime(2026, 11, 30, 23, 0).astimezone()
        self.assertTrue(rows.sale_runs("2026-11-20/2026-11-30", last_evening))
        self.assertFalse(rows.sale_runs("2026-11-20/2026-11-30", last_evening + timedelta(hours=1)))
        # No dates, or dates that cannot be read: the sale price stands, and it is no error.
        for dates in (None, "", "next week", "2026-11-20T00:00+01:00", "2026-13-45/2026-11-30", "/", "a/b/c",
                      "2026-11-20/soon", 42):
            self.assertTrue(rows.sale_runs(dates, at("2099-01-01T00:00+00:00")), dates)

    def test_a_sale_price_counts_only_while_its_sale_runs(self):
        base = {"product_id": "1", "name": "Shirt", "price": "10 EUR", "buy_link": "https://shop.example.com/1",
                "sale_price": "8 EUR"}
        for dates, kept in (("2020-01-01T00:00+01:00/2099-12-31T23:59+01:00", 8.0),     # running now
                            ("2099-01-01T00:00+01:00/2099-12-31T23:59+01:00", None),    # not begun
                            ("2020-01-01T00:00+01:00/2020-12-31T23:59+01:00", None),    # over
                            ("2020-01-01T00:00+01:00/", 8.0), ("/2099-12-31T23:59+01:00", 8.0),   # open-ended
                            ("whenever", 8.0), (None, 8.0)):                            # unreadable, or none given
            self.assertEqual(rows.product(**base, sale_dates=dates)["sale_price"], kept, dates)


# ── the importers ─────────────────────────────────────────────────────────────

class Importers(FeedCase):
    def test_google_format_every_field_lands_where_it_should(self):
        result = google.read(FEEDS / "musterhaus.jsonl")
        by_id = {r["product_id"]: r for r in result.rows}
        self.assertEqual(sorted(by_id), MUSTERHAUS)
        self.assertEqual(by_id["MH-2001-M"], {
            "product_id": "MH-2001-M", "group_id": "MH-2001", "name": "Rundhalspullover aus Merinowolle",
            "brand": "Musterhaus", "category": "Herren > Strick", "gender": "male",
            "colour": "Grau meliert", "colour_key": "grey",
            "material": "100% Merinowolle", "composition": [["merino", 100.0]],
            "price": 79.0, "sale_price": 59.0, "currency": "EUR",
            "sizes": ["M"], "sizes_in_stock": ["M"], "available": True,
            "image_url": "https://images.example.com/musterhaus/mh-2001.jpg",
            "buy_link": "https://track.example.org/click?m=900001&p=MH-2001-M",    # Awin's tracked link, not the shop page
            "feed_updated_at": None,
        })
        self.assertEqual((by_id["MH-1001-M"]["price"], by_id["MH-1001-L"]["available"],
                          by_id["MH-1001-L"]["sizes_in_stock"]), (39.95, False, []))
        self.assertEqual(by_id["MH-3001-3232"]["composition"], [["cotton", 98.0], ["elastane", 2.0]])
        self.assertEqual(by_id["MH-6002-43"]["available"], False, "a back-order cannot be bought now")

    def test_google_format_as_csv_and_tsv_gives_the_same_rows_as_json_lines(self):
        lines = google.read(FEEDS / "musterhaus.jsonl")
        for name in ("musterhaus.csv", "musterhaus.tsv"):
            other = google.read(FEEDS / name)
            self.assertEqual(other.rows, lines.rows, name)
            self.assertEqual(other.skipped, lines.skipped, name)

    def test_google_format_keeps_a_sale_price_only_while_its_sale_runs(self):
        line = ('{"id": "S%d", "title": "Hemd", "price": "50.00 EUR", "sale_price": "35.00 EUR", '
                '"sale_price_effective_date": "%s", "link": "https://shop.example.com/s"}\n')
        cases = [("2020-01-01T00:00+01:00/2099-12-31T23:59+01:00", 35.0),    # inside
                 ("2099-01-01T00:00+0100/2099-12-31T23:59+0100", None),      # before
                 ("2020-01-01T00:00Z/2020-12-31T23:59Z", None),              # after
                 ("2020-01-01T00:00+01:00/", 35.0),                          # open-ended
                 ("from Friday", 35.0)]                                      # malformed: kept, and not skipped
        path = self.write("sale.jsonl", "".join(line % (i, dates) for i, (dates, _) in enumerate(cases)))
        result = google.read(path)
        self.assertEqual([r["sale_price"] for r in result.rows], [kept for _, kept in cases])
        self.assertEqual(result.skipped, Counter(), "a malformed range is no error")
        self.assertEqual({r["price"] for r in result.rows}, {50.0}, "the regular price stays whatever the dates")

    def test_google_names_written_as_in_its_xml_are_read_too(self):
        path = self.write("g.csv", "g:id,g:title,g:price,g:link,g:size,g:availability\n"
                                   "A1,Hemd,25.00 EUR,https://shop.example.com/a1,L,in stock\n")
        row = google.read(path).rows[0]
        self.assertEqual((row["product_id"], row["name"], row["price"], row["sizes_in_stock"]), ("A1", "Hemd", 25.0, ["L"]))

    def test_awin_csv_every_field_lands_where_it_should(self):
        by_id = {r["product_id"]: r for r in awin_csv.read(FEEDS / "nordfaden.csv").rows}
        self.assertEqual(sorted(by_id), ["70011", "70012", "70021", "70031", "70061"])
        self.assertEqual(by_id["70011"], {
            "product_id": "70011", "group_id": "NF-700", "name": "Rollkragenpullover aus Merinowolle",
            "brand": "Nordfaden", "category": "Herren > Pullover", "gender": "Male",
            "colour": "Marineblau", "colour_key": "navy",
            "material": "100% Merinowolle", "composition": [["merino", 100.0]],
            "price": 69.9, "sale_price": None, "currency": "EUR",                # rrp_price, a "was" price, is not read
            "sizes": ["S", "M", "L", "XL"], "sizes_in_stock": ["S", "M", "XL"], "available": True,
            "image_url": "https://images.example.com/nordfaden/nf-700-navy.jpg",
            "buy_link": "https://track.example.org/aw?m=900002&p=70011",
            "feed_updated_at": rows.parse_time("2026-11-12 05:30:00"),
        })
        self.assertEqual(by_id["70012"]["price"], 69.9, '"69,90"')
        self.assertEqual(by_id["70061"]["price"], 1299.0, '"1.299,00"')
        self.assertEqual(by_id["70021"]["available"], False, "in_stock 0")

    def test_tradedoubler_json_every_field_lands_where_it_should(self):
        by_id = {r["product_id"]: r for r in tradedoubler.read(FEEDS / "kleiderwerk.json").rows}
        self.assertEqual(sorted(by_id), ["KW-10-L", "KW-10-M", "KW-20-3234", "KW-30"])
        self.assertEqual(by_id["KW-10-M"], {
            "product_id": "KW-10-M", "group_id": "KW-10", "name": "Leinenhemd",
            "brand": "Kleiderwerk", "category": "Herren > Hemden", "gender": "male",
            "colour": "Hellblau", "colour_key": "light-blue",
            "material": "100% Leinen", "composition": [["linen", 100.0]],
            "price": 49.95, "sale_price": None, "currency": "EUR",               # the newest of its price history
            "sizes": ["M"], "sizes_in_stock": ["M"], "available": True,
            "image_url": "https://images.example.org/kleiderwerk/kw-10.jpg",
            "buy_link": "https://track.example.org/td?p=900003&a=KW-10-M",
            "feed_updated_at": rows.parse_time(1794456000000),
        })
        chino = by_id["KW-20-3234"]
        self.assertEqual((chino["price"], chino["sizes"], chino["available"]), (69.95, ["32/34"], True),
                         "a plain offer price, a size among the store's fields, and a stock count")
        self.assertEqual(by_id["KW-30"]["price"], 89.0)

    def test_unknown_sizes_stay_unknown(self):
        found = {r["product_id"]: r for path, reader in ((FEEDS / "musterhaus.jsonl", google.read),
                                                          (FEEDS / "nordfaden.csv", awin_csv.read),
                                                          (FEEDS / "kleiderwerk.json", tradedoubler.read))
                 for r in reader(path).rows}
        for pid in ("MH-4001", "70021", "KW-30"):                   # the feed names no size
            self.assertEqual((found[pid]["sizes"], found[pid]["sizes_in_stock"]), ([], []), pid)
        # Sizes named, in stock, but the feed does not say which sizes: none is claimed to be in stock.
        self.assertEqual((found["70012"]["sizes"], found["70012"]["sizes_in_stock"], found["70012"]["available"]),
                         (["M", "L"], [], True))

    def test_rows_without_a_price_or_a_link_are_skipped_and_counted(self):
        for path, reader in ((FEEDS / "musterhaus.jsonl", google.read), (FEEDS / "musterhaus.csv", google.read),
                             (FEEDS / "musterhaus.tsv", google.read), (FEEDS / "nordfaden.csv", awin_csv.read),
                             (FEEDS / "kleiderwerk.json", tradedoubler.read)):
            result = reader(path)
            self.assertEqual(result.skipped, Counter({"without a price": 1, "without a link": 1}), path.name)
            self.assertEqual(result.summary(), "2 skipped: 1 without a link, 1 without a price")

    def test_unreadable_lines_and_repeated_ids_are_counted_and_the_rest_imported(self):
        good = '{"id": "A1", "title": "Hemd", "price": "25 EUR", "link": "https://shop.example.com/a1"}\n'
        path = self.write("odd.jsonl", good + "this is not json\n[1, 2]\n\n" + good)
        result = google.read(path)
        self.assertEqual([r["product_id"] for r in result.rows], ["A1"])
        self.assertEqual(result.skipped, Counter({"unreadable": 2, "with an id seen before in the file": 1}))

    def test_one_garbled_record_costs_that_record_only(self):
        good = '{"id": "A%d", "title": "Hemd", "price": "25 EUR", "link": "https://shop.example.com/a"}\n'
        garbled = '{"id": "A3", "title": "Hemd", "price": "1,2.3,4 EUR", "link": "https://shop.example.com/a"}\n'
        result = google.read(self.write("garbled.jsonl", good % 1 + good % 2 + garbled))
        self.assertEqual(([r["product_id"] for r in result.rows], result.summary()), (["A1", "A2"], "1 skipped: 1 without a price"))

        td = json.loads((FEEDS / "kleiderwerk.json").read_text(encoding="utf-8"))
        td["products"][0]["fields"], td["products"][1]["offers"][0]["priceHistory"] = 5, 7    # shapes nobody expects
        td["products"][3]["offers"][0]["modified"] = 1e300                                    # a time out of range
        result = tradedoubler.read(self.write("odd.json", json.dumps(td)))
        self.assertEqual({r["product_id"]: r["feed_updated_at"] for r in result.rows},
                         {"KW-20-3234": rows.parse_time(1794456000000), "KW-30": None}, "a time out of range is no time")
        self.assertEqual(result.skipped, Counter({"unreadable": 2, "without a link": 1, "without a price": 1}))

        registry.sync()                                         # and through the command line: the rest is imported
        said = self.cli("feeds", "--store", "musterhaus", "--from", str(self.folder / "garbled.jsonl"))
        self.assertIn("musterhaus: 2 products imported, 1 skipped: 1 without a price", said)

    def test_a_gzipped_feed_is_read_like_the_plain_one(self):
        packed = self.folder / "musterhaus.jsonl.gz"
        packed.write_bytes(gzip.compress((FEEDS / "musterhaus.jsonl").read_bytes()))
        self.assertEqual(google.read(packed).rows, google.read(FEEDS / "musterhaus.jsonl").rows)


# ── the registry ──────────────────────────────────────────────────────────────

class Registry(FeedCase):
    def test_the_file_in_the_project_is_valid_and_its_stores_are_invented_samples(self):
        stores = registry.load()
        self.assertEqual(sorted(stores), ["kleiderwerk", "musterhaus", "nordfaden"])
        for key, values in stores.items():
            self.assertTrue(values["rules"]["sample"], key)
            self.assertIn("(sample)", values["label"])
            self.assertTrue((paths.ROOT / values["feed_location"]).is_file(), key)

    def test_the_example_of_a_real_store_is_valid_once_the_first_hash_of_each_line_is_removed(self):
        text = (paths.CONFIG_DIR / "feeds.toml").read_text(encoding="utf-8")
        example = text[text.index("# [stores.yourstore]"):]
        uncommented = "\n".join(line.removeprefix("#") for line in example.splitlines())
        store = registry.load(tomllib.loads(uncommented))["yourstore"]
        self.assertEqual((store["label"], store["network"], store["status"], store["feed_format"]),
                         ("Your Store", "awin", "applied", "google"))
        self.assertIn("{AWIN_PUBLISHER_ID}", store["feed_location"])
        self.assertEqual(store["rules"]["headers"], {"Authorization": "Bearer {AWIN_API_TOKEN}"})

    def test_sync_adds_updates_and_never_deletes(self):
        data = {"stores": {"one": {"label": "One", "status": "approved", "feed_format": "google", "programme_id": 41},
                           "two": {"label": "Two"}}}
        self.assertEqual(registry.sync(data), ["one: added", "two: added"])
        self.assertEqual(db.get_store("one")["programme_id"], "41", "a number is kept as text")
        self.assertEqual(db.get_store("two")["status"], "none")
        self.assertEqual(registry.sync(data), ["one: unchanged", "two: unchanged"])
        data["stores"]["one"]["label"] = "One, renamed"
        self.assertEqual(registry.sync(data)[0], "one: updated")
        self.assertEqual(db.get_store("one")["label"], "One, renamed")

        db.replace_products("one", sample_rows())
        del data["stores"]["one"]
        said = registry.sync(data)
        self.assertIn("one: in the database but no longer in config/feeds.toml; left as it is", said)
        self.assertEqual(len(db.store_products("one")), 8, "its products are still there")

    def test_a_mistake_in_the_file_is_named(self):
        for entry, words in [({"label": "X", "status": "aproved"}, "stores.x.status is 'aproved'"),
                             ({"label": "X", "network": "zalando"}, "stores.x.network"),
                             ({"label": "X", "feed_format": "rakuten_pipe"}, "stores.x.feed_format"),
                             ({"label": "X", "colour": "red"}, "a setting this does not know: colour"),
                             ({"status": "none"}, "needs a label"),
                             ({"label": "X", "rules": {"refresh_hours": 0}}, "refresh_hours must be more than 0")]:
            with self.assertRaises(config.ConfigError) as problem:
                registry.sync({"stores": {"x": entry}})
            self.assertIn(words, str(problem.exception))
        with self.assertRaises(config.ConfigError):
            registry.sync({"stores": {"Bad Key": {"label": "X"}}})
        self.assertEqual(db.list_stores(), [], "nothing was written")

    def test_the_samples_are_left_out_in_production(self):
        with mock.patch.object(settings, "PRODUCTION", True):
            said = registry.sync()
            self.assertEqual(said, [f"{key}: an invented sample store, left out in production"
                                    for key in ("musterhaus", "nordfaden", "kleiderwerk")])
            self.assertEqual(db.list_stores(), [])
        registry.sync()                                          # synced on your own machine, then run in production
        with mock.patch.object(settings, "PRODUCTION", True):
            self.assertEqual(refresh.chosen(None, None), [])
            with self.assertRaises(refresh.FeedError):
                refresh.chosen("musterhaus", None)

    def test_an_ended_store_stays_ended_until_it_is_reopened(self):
        registry.sync()
        self.cli("feeds", "--store", "musterhaus")
        self.assertIn("musterhaus: ended, 8 products deleted", self.cli("stores", "end", "musterhaus"))
        self.assertEqual(db.store_products("musterhaus"), [])
        said = self.cli("stores", "sync")                       # the file still says approved
        self.assertIn("musterhaus: unchanged (ended with `stores end`, so it stays ended.", said)
        self.assertEqual(db.get_store("musterhaus")["status"], "ended")
        with self.assertRaises(SystemExit) as refused:
            self.cli("feeds", "--store", "musterhaus")
        self.assertIn("has ended", str(refused.exception))
        self.assertNotIn("musterhaus", [s["key"] for s in refresh.chosen(None, None)])
        self.assertIn("musterhaus: updated", self.cli("stores", "sync", "--reopen", "musterhaus"))
        self.assertEqual(db.get_store("musterhaus")["status"], "approved")

    def test_ending_a_store_the_file_already_marks_ended_is_pointed_out(self):
        data = {"stores": {"one": {"label": "One", "status": "approved", "feed_format": "google"}}}
        registry.sync(data)
        db.replace_products("one", sample_rows())
        data["stores"]["one"]["status"] = "ended"
        self.assertIn("one: marked ended but still has 8 products. Delete them with: python -m wardrobe stores end one",
                      registry.sync(data))
        with self.assertRaises(SystemExit):
            self.cli("stores", "end", "nobody")

    def test_a_store_no_longer_approved_that_still_has_products_is_pointed_out(self):
        data = {"stores": {"one": {"label": "One", "status": "approved", "feed_format": "google"}}}
        registry.sync(data)
        db.replace_products("one", sample_rows())
        for status in ("refused", "applied", "none"):
            data["stores"]["one"]["status"] = status
            self.assertIn("one: no longer approved but still has 8 products. Delete them with: "
                          "python -m wardrobe stores end one", registry.sync(data), status)
            self.assertEqual(len(db.store_products("one")), 8, "nothing is deleted unless asked")
        data["stores"]["one"]["status"] = "approved"
        self.assertEqual(registry.sync(data), ["one: updated"], "approved again: nothing to point out")
        # A sample store's file may be tried by hand whatever its status, so its products are not pointed out.
        registry.sync()
        self.cli("feeds", "--store", "musterhaus")
        sample = {"stores": {"musterhaus": {**tomllib.loads((paths.CONFIG_DIR / "feeds.toml").read_text(
            encoding="utf-8"))["stores"]["musterhaus"], "status": "applied"}}}
        self.assertEqual(registry.sync(sample)[0], "musterhaus: updated")
        self.assertNotIn("no longer approved", " ".join(registry.sync(sample)))

    def test_a_feed_older_than_its_refresh_hours_plus_a_day_is_stale(self):
        now = datetime(2026, 11, 13, 6, 0).astimezone()
        store = {"status": "approved", "rules": {"refresh_hours": 24}, "last_import_at": None}
        for hours_old, stale in ((47, False), (49, True)):
            when = (now - timedelta(hours=hours_old)).isoformat()
            self.assertEqual(registry.stale({**store, "last_feed_update": when}, now), stale, hours_old)
        twice_a_day = {**store, "rules": {"refresh_hours": 12}, "last_feed_update": (now - timedelta(hours=37)).isoformat()}
        self.assertTrue(registry.stale(twice_a_day, now))
        self.assertTrue(registry.stale({**store, "last_feed_update": None}, now), "approved, and no feed yet")
        self.assertFalse(registry.stale({**store, "status": "applied", "last_feed_update": None}, now))

        registry.sync()
        self.cli("feeds")
        just_now = datetime.now().astimezone()
        for key in ("musterhaus", "kleiderwerk"):              # the sample files' own times may be old
            db.note_store(key, error=None, feed_update=just_now.isoformat(timespec="seconds"))
        db.note_store("nordfaden", error=None, feed_update=(just_now - timedelta(days=3)).isoformat(timespec="seconds"))
        listing = self.cli("stores")
        self.assertRegex(listing, r"nordfaden\s+approved\s+awin\s+5\s+\S+ \S+\s+\S+ \S+\n    STALE: the feed is older")
        self.assertEqual(listing.count("STALE"), 1)


# ── importing, through the command line ───────────────────────────────────────

class Importing(FeedCase):
    def test_sync_then_each_sample_format_imports_every_product(self):
        said = self.cli("stores", "sync")
        self.assertEqual(said.splitlines(), ["musterhaus: added", "nordfaden: added", "kleiderwerk: added"])
        for store, name, reader in (("musterhaus", "musterhaus.jsonl", google.read),
                                    ("musterhaus", "musterhaus.csv", google.read),
                                    ("musterhaus", "musterhaus.tsv", google.read),
                                    ("nordfaden", "nordfaden.csv", awin_csv.read),
                                    ("kleiderwerk", "kleiderwerk.json", tradedoubler.read)):
            wanted = sorted(r["product_id"] for r in reader(FEEDS / name).rows)
            said = self.cli("feeds", "--store", store, "--from", str(FEEDS / name))
            self.assertIn(f"{store}: {len(wanted)} products imported", said)
            self.assertIn("2 skipped: 1 without a link, 1 without a price", said)
            self.assertEqual(self.ids(store), wanted, name)
        listing = self.cli("stores")
        self.assertRegex(listing, r"musterhaus\s+approved\s+awin\s+8 ")
        self.assertRegex(listing, r"nordfaden\s+approved\s+awin\s+5 ")
        self.assertRegex(listing, r"kleiderwerk\s+approved\s+tradedoubler\s+4 ")

    def test_what_a_product_row_holds_once_imported(self):
        registry.sync()
        self.cli("feeds", "--store", "nordfaden")
        coat = next(p for p in db.store_products("nordfaden") if p["product_id"] == "70061")
        self.assertEqual((coat["store"], coat["sizes_in_stock"], coat["composition"], coat["available"]),
                         ("nordfaden", ["48", "50", "52"], [["wool", 90.0], ["cashmere", 10.0]], True))
        self.assertEqual(coat["imported_at"], db.get_store("nordfaden")["last_import_at"])
        self.assertIsNone(db.get_store("nordfaden")["last_error"])

    def test_a_product_missing_from_the_next_file_is_gone(self):
        registry.sync()
        self.cli("feeds", "--store", "musterhaus", "--from", str(FEEDS / "musterhaus.jsonl"))
        lines = (FEEDS / "musterhaus.jsonl").read_text(encoding="utf-8").splitlines(keepends=True)
        smaller = self.write("smaller.jsonl", "".join(line for line in lines if '"MH-2001-M"' not in line))
        said = self.cli("feeds", "--store", "musterhaus", "--from", str(smaller))
        self.assertIn("musterhaus: 7 products imported, 1 from the last import is gone", said)
        self.assertEqual(self.ids("musterhaus"), [p for p in MUSTERHAUS if p != "MH-2001-M"])

    def test_a_file_given_by_hand_is_dated_by_its_products_not_by_when_it_was_copied(self):
        registry.sync()
        for store, name, reader in (("nordfaden", "nordfaden.csv", awin_csv.read),
                                    ("kleiderwerk", "kleiderwerk.json", tradedoubler.read)):
            copied = self.folder / name
            shutil.copyfile(FEEDS / name, copied)                 # copied just now: the file's own time is now
            newest = max((r["feed_updated_at"] for r in reader(copied).rows), key=datetime.fromisoformat)
            self.cli("feeds", "--store", store, "--from", str(copied))
            self.assertEqual(db.get_store(store)["last_feed_update"], newest, store)
            # Never newer than the file itself, though: a file written before its products' times.
            earlier = datetime.fromisoformat(newest).timestamp() - 3600
            os.utime(copied, (earlier, earlier))
            self.cli("feeds", "--store", store, "--from", str(copied))
            self.assertEqual(datetime.fromisoformat(db.get_store(store)["last_feed_update"]).timestamp(), earlier, store)
        # Google's format carries no time per product: the file's own time is all there is, for each product too.
        copied = self.folder / "musterhaus.jsonl"
        shutil.copyfile(FEEDS / "musterhaus.jsonl", copied)
        os.utime(copied, (1794456000, 1794456000))
        self.cli("feeds", "--store", "musterhaus", "--from", str(copied))
        when = datetime.fromtimestamp(1794456000, timezone.utc)
        self.assertEqual(datetime.fromisoformat(db.get_store("musterhaus")["last_feed_update"]), when)
        self.assertEqual({datetime.fromisoformat(p["feed_updated_at"]) for p in db.store_products("musterhaus")}, {when})

    def test_ending_a_store_removes_all_its_products_and_only_its(self):
        registry.sync()
        self.cli("feeds")
        self.assertEqual(len(db.store_products("musterhaus")), 8)
        self.cli("stores", "end", "musterhaus")
        self.assertEqual(db.store_products("musterhaus"), [])
        self.assertEqual(len(db.store_products("nordfaden")), 5)
        self.assertRegex(self.cli("stores"), r"musterhaus\s+ended\s+awin\s+0 ")

    def test_a_failure_part_way_through_an_import_keeps_the_old_products(self):
        registry.sync()
        self.cli("feeds", "--store", "musterhaus")
        before = db.store_products("musterhaus")
        written = []
        real = db._product_values

        def fails_at_the_fourth(store, row):
            written.append(row["product_id"])
            if len(written) == 4:
                raise sqlite3.OperationalError("disk I/O error")
            return real(store, row)

        with mock.patch.object(db, "_product_values", fails_at_the_fourth):
            with self.assertRaises(SystemExit) as stopped:
                self.cli("feeds", "--store", "musterhaus", "--from", str(FEEDS / "musterhaus.csv"))
        self.assertIn("1 store failed", str(stopped.exception))
        self.assertEqual(len(written), 4, "it got part of the way")
        self.assertEqual(db.store_products("musterhaus"), before, "exactly the old rows")
        self.assertIn("an unexpected OperationalError", db.get_store("musterhaus")["last_error"])

    def test_a_file_in_which_no_product_can_be_read_changes_nothing(self):
        registry.sync()
        self.cli("feeds", "--store", "musterhaus")
        page = self.write("error.html", "<html><body>Service unavailable</body></html>\n")
        with self.assertRaises(SystemExit):
            self.cli("feeds", "--store", "musterhaus", "--from", str(page))
        self.assertEqual(self.ids("musterhaus"), MUSTERHAUS)
        self.assertIn("no product in the file could be read", db.get_store("musterhaus")["last_error"])
        broken = self.write("broken.json", '{"products": [')
        with self.assertRaises(SystemExit):
            self.cli("feeds", "--store", "kleiderwerk", "--from", str(broken))
        self.assertIn("could not be read as tradedoubler_json (JSONDecodeError)", db.get_store("kleiderwerk")["last_error"])

    def test_one_store_failing_does_not_stop_the_others(self):
        registry.sync()
        nordfaden = {name: db.get_store("nordfaden")[name] for name in db.STORE_SETTINGS}
        db.save_store("nordfaden", {**nordfaden, "feed_location": "tests/fixtures/feeds/gone.csv"})
        out = io.StringIO()
        with contextlib.redirect_stdout(out), self.assertRaises(SystemExit) as stopped:
            main(["feeds"])
        said = out.getvalue()
        self.assertIn("kleiderwerk: 4 products imported", said)
        self.assertIn("musterhaus: 8 products imported", said)
        self.assertIn("nordfaden: failed, and nothing was imported: there is no file tests/fixtures/feeds/gone.csv", said)
        self.assertEqual(str(stopped.exception), "1 store failed; the reason is above and in `python -m wardrobe stores`.")
        self.assertIn("last refresh failed", self.cli("stores"))
        db.save_store("nordfaden", nordfaden)
        self.cli("feeds", "--store", "nordfaden")
        self.assertIsNone(db.get_store("nordfaden")["last_error"], "a refresh that works clears the error")

    def test_a_failed_run_says_what_the_store_has(self):
        registry.sync()
        missing = str(self.folder / "missing.jsonl")
        # Its first run fails: there is nothing to keep, and no feed yet.
        said: list[str] = []
        self.assertEqual(refresh.run("musterhaus", from_file=missing, say=said.append), 1)
        self.assertEqual(said, [f"musterhaus: failed, and nothing was imported: there is no file {missing}",
                                "musterhaus: STALE: no feed imported yet"])
        self.assertIn("    STALE: no feed imported yet", self.cli("stores"), "the same words as the list of stores")
        # Once it has products, a failure keeps them, and an old feed is stale for being old.
        self.cli("feeds", "--store", "musterhaus", "--from", str(FEEDS / "musterhaus.jsonl"))
        db.note_store("musterhaus", error=None, feed_update=(datetime.now().astimezone() - timedelta(days=3)).isoformat())
        said = []
        refresh.run("musterhaus", from_file=missing, say=said.append)
        self.assertEqual(said, [f"musterhaus: failed, and its products are kept as they were: there is no file {missing}",
                                "musterhaus: STALE: the feed is older than its refresh hours plus a day"])
        self.assertEqual(self.ids("musterhaus"), MUSTERHAUS)

    def test_a_file_that_would_remove_most_of_a_store_is_refused_unless_forced(self):
        def feed(name: str, numbers) -> Path:
            return self.write(name, "".join(json.dumps({"id": f"BIG-{n:02}", "title": "Hemd", "price": "25 EUR",
                                                        "link": f"https://shop.example.com/big/{n}"}) + "\n"
                                            for n in numbers))

        registry.sync()
        db.save_store("big", a_store(label="A big test store"))
        whole = feed("whole.jsonl", range(1, 13))
        self.assertIn("big: 12 products imported", self.cli("feeds", "--store", "big", "--from", str(whole)))
        before = db.get_store("big")

        # 5 of 12 left: 7 would go, more than half. Nothing changes, and the store says why and how to go on.
        few = feed("few.jsonl", range(1, 6))
        out = io.StringIO()
        with contextlib.redirect_stdout(out), self.assertRaises(SystemExit) as stopped:
            main(["feeds", "--store", "big", "--from", str(few)])
        reason = ("the new file would remove 7 of its 12 products, more than half. If the store really has that few "
                  "now, import it with: python -m wardrobe feeds --store big --from FILE --force")
        self.assertEqual(out.getvalue(), f"big: failed, and its products are kept as they were: {reason}\n")
        self.assertIn("1 store failed", str(stopped.exception))
        self.assertEqual(len(db.store_products("big")), 12, "the old products stay")
        after = db.get_store("big")
        self.assertTrue(after["last_error"].endswith(reason), after["last_error"])
        self.assertEqual((after["last_feed_update"], after["last_import_at"]),
                         (before["last_feed_update"], before["last_import_at"]), "not taken as imported")

        # Exactly half may go.
        db.save_store("half", a_store(label="Another test store"))
        self.cli("feeds", "--store", "half", "--from", str(whole))
        self.assertIn("half: 6 products imported, 6 from the last import are gone",
                      self.cli("feeds", "--store", "half", "--from", str(feed("half.jsonl", range(1, 7)))))

        # --force takes the file as it is, and clears the error.
        self.assertIn("big: 5 products imported, 7 from the last import are gone",
                      self.cli("feeds", "--store", "big", "--from", str(few), "--force"))
        self.assertIsNone(db.get_store("big")["last_error"])

        # A store with fewer than 10 products is not held back: one product left of Musterhaus's 8.
        self.cli("feeds", "--store", "musterhaus", "--from", str(FEEDS / "musterhaus.jsonl"))
        first = (FEEDS / "musterhaus.jsonl").read_text(encoding="utf-8").splitlines(keepends=True)[0]
        self.assertIn("musterhaus: 1 products imported, 7 from the last import are gone",
                      self.cli("feeds", "--store", "musterhaus", "--from", str(self.write("one.jsonl", first))))

    def test_a_refused_store_does_not_stop_the_others(self):
        registry.sync()
        big = self.folder / "big.jsonl"
        db.save_store("big", a_store(label="A big test store", feed_location=str(big)))
        lines = [json.dumps({"id": f"BIG-{n:02}", "title": "Hemd", "price": "25 EUR",
                             "link": f"https://shop.example.com/big/{n}"}) + "\n" for n in range(1, 21)]
        big.write_text("".join(lines), encoding="utf-8")
        os.utime(big, (time.time() - 7200,) * 2)
        self.cli("feeds")
        self.assertEqual(len(db.store_products("big")), 20)
        # The store's own file is cut to a quarter (as a cut download whose server gave no size would be).
        big.write_text("".join(lines[:5]), encoding="utf-8")
        os.utime(big, (time.time() - 3600,) * 2)             # a newer version of it
        for key in ("musterhaus", "nordfaden", "kleiderwerk"):
            db.note_store(key, error=None, feed_update="2026-01-01T06:00:00+01:00")      # so they are imported again
        out = io.StringIO()
        with contextlib.redirect_stdout(out), self.assertRaises(SystemExit):
            main(["feeds"])
        said = out.getvalue()
        self.assertIn("big: failed, and its products are kept as they were: the new file would remove 15 of its 20 "
                      "products, more than half. If the store really has that few now, import it with: "
                      "python -m wardrobe feeds --store big --force", said)
        for key, count in (("musterhaus", 8), ("nordfaden", 5), ("kleiderwerk", 4)):
            self.assertIn(f"{key}: {count} products imported", said)
        self.assertEqual(len(db.store_products("big")), 20)
        self.assertIn("big: 5 products imported, 15 from the last import are gone", self.cli("feeds", "--store", "big", "--force"))

    def test_an_unchanged_feed_is_not_imported_again_unless_forced(self):
        registry.sync()
        self.cli("feeds")
        self.assertEqual(self.cli("feeds").count("unchanged since"), 3)
        self.assertIn("musterhaus: 8 products imported", self.cli("feeds", "--store", "musterhaus", "--force"))

    def test_what_is_refused(self):
        registry.sync()
        for argv, words in [(["feeds", "--from", str(FEEDS / "musterhaus.csv")], "--from needs --store"),
                            (["feeds", "--store", "nobody"], "There is no store called 'nobody'")]:
            with self.assertRaises(SystemExit) as refused:
                self.cli(*argv)
            self.assertIn(words, str(refused.exception))
        musterhaus = {name: db.get_store("musterhaus")[name] for name in db.STORE_SETTINGS}
        db.save_store("musterhaus", {**musterhaus, "status": "applied"})
        with self.assertRaises(SystemExit) as refused:
            self.cli("feeds", "--store", "musterhaus")
        self.assertIn("not approved", str(refused.exception))
        self.assertIn("8 products imported", self.cli("feeds", "--store", "musterhaus", "--from", str(FEEDS / "musterhaus.csv")),
                      "an invented sample store's file may be tried whatever its status")
        self.assertNotIn("musterhaus", self.cli("feeds"), "only approved stores are fetched")
        # A real store's file is not licensed until its programme has approved Stilsmith: nothing of it is kept.
        for status in ("none", "applied", "refused"):
            db.save_store("real", a_store(status=status))
            with self.assertRaises(SystemExit) as refused:
                self.cli("feeds", "--store", "real", "--from", str(FEEDS / "musterhaus.jsonl"))
            self.assertEqual(str(refused.exception), f"real is {status!r}, not approved: Stilsmith takes a store's products "
                                                     "only once its programme has approved it, so no file of it is imported either")
            self.assertEqual(db.store_products("real"), [], status)
        db.save_store("real", a_store(status="approved"))
        self.assertIn("real: 8 products imported", self.cli("feeds", "--store", "real", "--from", str(FEEDS / "musterhaus.jsonl")))
        db.save_store("musterhaus", {**musterhaus, "feed_format": None})
        with self.assertRaises(SystemExit):
            self.cli("feeds", "--store", "musterhaus", "--from", str(FEEDS / "musterhaus.csv"))
        self.assertIn("feed_format", db.get_store("musterhaus")["last_error"])
        with self.assertRaises(SystemExit):
            self.cli("feeds", "--store", "nordfaden", "--from", str(self.folder / "missing.csv"))

    def test_with_no_approved_store_it_says_how_to_add_one(self):
        self.assertIn("No approved stores", self.cli("feeds"))
        self.assertIn("No stores yet", self.cli("stores"))


# ── downloading ───────────────────────────────────────────────────────────────

class StandIn(BaseHTTPRequestHandler):
    """A feed server on this computer: /feed.jsonl, /last-updated saying when it changed, and /moved,
    which sends the downloader on to /feed.jsonl."""
    feed = b""
    changed = 1794456000000
    last_modified = ""          # the feed's Last-Modified header, if any
    refuse = False
    cut = False                 # send half the feed under the whole one's Content-Length, then hang up
    unsized = False             # send a quarter of the feed with no Content-Length at all, then hang up
    seen: list = []

    def do_GET(self):
        type(self).seen.append((self.path, self.headers.get("Authorization")))
        if self.path.startswith("/moved"):
            self.send_response(302)
            self.send_header("Location", "/feed.jsonl")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if self.path.startswith("/last-updated"):
            body = json.dumps({"lastUpdated": type(self).changed}).encode()
        elif self.path.startswith("/feed.jsonl") and not type(self).refuse:
            body = type(self).feed
        else:
            self.send_response(403)
            self.end_headers()
            return
        self.send_response(200)
        if self.path.startswith("/feed.jsonl") and type(self).unsized:
            body = body[:len(body) // 4]            # nothing to check it against: the connection just closes
        else:
            self.send_header("Content-Length", str(len(body)))
        if self.path.startswith("/feed.jsonl") and type(self).last_modified:
            self.send_header("Last-Modified", type(self).last_modified)
        self.end_headers()
        if self.path.startswith("/feed.jsonl") and type(self).cut:
            body = body[:len(body) // 2]            # the connection closes after this (HTTP/1.0)
        self.wfile.write(body)

    def log_message(self, *args):
        pass


class Downloads(FeedCase):
    def use_the_real_opener(self):
        self.network_meant = True
        self.opener.side_effect = self.real_opener

    def store(self, key="remote", **values) -> dict:
        db.save_store(key, a_store(**values))
        return db.get_store(key)

    def stand_in(self) -> str:
        StandIn.feed = (FEEDS / "musterhaus.jsonl").read_bytes()
        StandIn.changed, StandIn.refuse, StandIn.seen = int(time.time() - 3600) * 1000, False, []   # an hour ago
        StandIn.last_modified, StandIn.cut, StandIn.unsized = "", False, False
        server = ThreadingHTTPServer(("127.0.0.1", 0), StandIn)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return f"http://127.0.0.1:{server.server_address[1]}"

    def test_importing_the_samples_opens_no_network_connection(self):
        self.opener.side_effect = AssertionError("a network connection was opened")
        registry.sync()
        self.cli("feeds")
        self.cli("feeds", "--force")
        self.cli("feeds", "--store", "nordfaden", "--from", str(FEEDS / "nordfaden.csv"))
        self.assertEqual(len(db.store_products("musterhaus")) + len(db.store_products("nordfaden")), 13)
        self.opener.assert_not_called()

    def test_a_file_address_goes_through_the_downloader_and_is_not_fetched_again_unchanged(self):
        self.use_the_real_opener()
        self.store(feed_location=(FEEDS / "musterhaus.jsonl").as_uri())
        self.assertEqual(refresh.run("remote", say=lambda line: None), 0)
        self.assertEqual(self.ids("remote"), MUSTERHAUS)
        self.assertEqual(self.opener.call_count, 1)
        said = []
        refresh.run("remote", say=said.append)
        self.assertIn("unchanged since", said[0])
        self.assertFalse((paths.DATA_DIR / "feeds" / "remote.download").exists(), "no copy of the feed is kept")

    def test_a_stand_in_server_is_asked_first_and_the_feed_fetched_only_when_it_changed(self):
        self.use_the_real_opener()
        base = self.stand_in()
        self.store(network="tradedoubler", feed_location=base + "/feed.jsonl?token={CAPSULE_TEST_TOKEN}",
                   rules={"check_url": base + "/last-updated", "headers": {"Authorization": "Bearer {CAPSULE_TEST_TOKEN}"}})
        with mock.patch.dict(os.environ, {"CAPSULE_TEST_TOKEN": "a-secret/token"}):
            said = []
            refresh.run("remote", say=said.append)
            self.assertEqual(said, ["remote: 8 products imported, 2 skipped: 1 without a link, 1 without a price"])
            self.assertEqual(StandIn.seen, [("/last-updated", "Bearer a-secret/token"),
                                            ("/feed.jsonl?token=a-secret%2Ftoken", "Bearer a-secret/token")])
            self.assertEqual(datetime.fromisoformat(db.get_store("remote")["last_feed_update"]),
                             datetime.fromtimestamp(StandIn.changed / 1000, timezone.utc), "the feed's own time")

            self.assertIsNotNone(db.get_store("remote")["last_download_at"], "the download is recorded")
            db.note_download("remote", "2026-11-01T06:00:00+01:00")

            StandIn.seen = []
            refresh.run("remote", say=said.append)
            self.assertIn("unchanged since", said[-1])
            self.assertEqual([path for path, _ in StandIn.seen], ["/last-updated"], "asked, not downloaded")

            StandIn.seen, StandIn.changed, StandIn.refuse = [], StandIn.changed + 60_000, True
            refresh.run("remote", say=said.append)
            self.assertEqual(said[-1], "remote: failed, and its products are kept as they were: its feed address answered 403")
            self.assertEqual(self.ids("remote"), MUSTERHAUS)
            self.assertEqual(db.get_store("remote")["last_download_at"], "2026-11-01T06:00:00+01:00",
                             "neither the question nor a refusal counts as a download")
            for text in (said[-1], db.get_store("remote")["last_error"]):
                self.assertNotIn("secret", text)

    def test_a_missing_secret_is_named_and_nothing_is_fetched(self):
        self.store(feed_location="https://feeds.example.com/{programme_id}.jsonl?key={CAPSULE_TEST_MISSING}",
                   programme_id="77")
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("CAPSULE_TEST_MISSING", None)
            said = []
            self.assertEqual(refresh.run("remote", say=said.append), 1)
        self.assertIn("{CAPSULE_TEST_MISSING} in its feed address has no value: set the environment variable", said[0])
        self.opener.assert_not_called()

    def test_only_https_addresses_are_fetched(self):
        for where in ("http://feeds.example.com/feed.jsonl", "ftp://feeds.example.com/feed.jsonl"):
            self.store(feed_location=where)
            said = []
            refresh.run("remote", say=said.append)
            self.assertIn("only https:// feed addresses are fetched", said[0])
        self.opener.assert_not_called()

    def test_a_feed_bigger_than_its_limit_is_refused(self):
        self.use_the_real_opener()
        registry.sync()
        self.cli("feeds", "--store", "musterhaus")
        self.store(key="musterhaus", label="Musterhaus (sample)", feed_location=(FEEDS / "musterhaus.jsonl").as_uri(),
                   rules={"max_mb": 0.001, "sample": True})
        said = []
        refresh.run("musterhaus", force=True, say=said.append)
        self.assertIn("the feed is larger than 0.001 MB; rules.max_mb can allow more", said[0])
        self.assertEqual(self.ids("musterhaus"), MUSTERHAUS, "the old products stay")
        self.assertIsNotNone(db.get_store("musterhaus")["last_download_at"], "a download that broke off counts too")
        self.assertFalse((paths.DATA_DIR / "feeds" / "musterhaus.download").exists())

    def test_a_download_that_stops_short_of_its_announced_size_keeps_the_old_products(self):
        self.use_the_real_opener()
        base = self.stand_in()
        StandIn.last_modified = email.utils.formatdate(time.time() - 3600, usegmt=True)
        self.store(feed_location=base + "/feed.jsonl")
        refresh.run("remote", say=lambda line: None)
        self.assertEqual(self.ids("remote"), MUSTERHAUS)
        before = db.get_store("remote")
        db.note_download("remote", "2026-11-01T06:00:00+01:00")

        # A new version, and the server hangs up half-way through it, after announcing its whole size.
        StandIn.cut, StandIn.last_modified = True, email.utils.formatdate(time.time() - 60, usegmt=True)
        said: list[str] = []
        self.assertEqual(refresh.run("remote", say=said.append), 1)
        whole = len(StandIn.feed)
        self.assertEqual(said, [f"remote: failed, and its products are kept as they were: "
                                f"the download broke off ({whole // 2} of {whole} bytes arrived)"])
        self.assertEqual(self.ids("remote"), MUSTERHAUS, "the old products stay")
        after = db.get_store("remote")
        self.assertIn("the download broke off", after["last_error"])
        self.assertNotEqual(after["last_download_at"], "2026-11-01T06:00:00+01:00", "the download is recorded")
        self.assertEqual(after["last_feed_update"], before["last_feed_update"], "the cut version is not taken as imported")
        self.assertFalse((paths.DATA_DIR / "feeds" / "remote.download").exists())

        StandIn.cut = False                      # so the next run fetches that version again, whole this time
        refresh.run("remote", say=said.append)
        self.assertIn("remote: 8 products imported", said[-1])
        self.assertIsNone(db.get_store("remote")["last_error"])

    def test_a_cut_download_with_no_size_given_is_stopped_when_it_would_remove_most_of_a_store(self):
        self.use_the_real_opener()
        base = self.stand_in()
        StandIn.feed = "".join(json.dumps({"id": f"BIG-{n:02}", "title": "Hemd", "price": "25 EUR",
                                           "link": f"https://shop.example.com/big/{n}"}) + "\n"
                               for n in range(1, 21)).encode()
        StandIn.last_modified = email.utils.formatdate(time.time() - 3600, usegmt=True)
        self.store(feed_location=base + "/feed.jsonl")
        said: list[str] = []
        refresh.run("remote", say=said.append)
        self.assertEqual(said, ["remote: 20 products imported"])
        before = db.get_store("remote")

        # A new version, and the server hangs up a quarter of the way through, having given no size.
        StandIn.unsized, StandIn.last_modified = True, email.utils.formatdate(time.time() - 60, usegmt=True)
        self.assertEqual(refresh.run("remote", say=said.append), 1)
        self.assertRegex(said[-1], r"^remote: failed, and its products are kept as they were: the new file would remove "
                                   r"1[56] of its 20 products, more than half\. If the store really has that few now, "
                                   r"import it with: python -m wardrobe feeds --store remote --force$")
        self.assertEqual(len(db.store_products("remote")), 20, "the old products stay")
        self.assertEqual(db.get_store("remote")["last_feed_update"], before["last_feed_update"])
        self.assertFalse((paths.DATA_DIR / "feeds" / "remote.download").exists())

        StandIn.unsized = False                  # the next run fetches that version again, whole this time
        refresh.run("remote", say=said.append)
        self.assertEqual(said[-1], "remote: 20 products imported")

    def test_a_product_dated_in_the_future_never_makes_the_feed_look_fresh(self):
        # Nowhere to ask, and no Last-Modified: the feed is dated by its products. One of them says 2099.
        self.use_the_real_opener()
        base = self.stand_in()
        csv_text = (FEEDS / "nordfaden.csv").read_text(encoding="utf-8")
        self.assertEqual(csv_text.count("2026-11-12 05:30:00"), 6)
        StandIn.feed = csv_text.replace("2026-11-12 05:30:00", "2099-01-01 00:00:00", 1).encode()
        self.store(network="awin", feed_format="awin_csv", feed_location=base + "/feed.jsonl")
        with mock.patch.object(refresh.time, "sleep"):
            refresh.run("remote", say=lambda line: None)
        store = db.get_store("remote")
        self.assertEqual(store["last_feed_update"], store["last_import_at"], "no later than the import")
        future = [p for p in db.store_products("remote") if p["product_id"] == "70011"][0]
        self.assertEqual(future["feed_updated_at"], store["last_import_at"], "nor is the product's own time")
        two_days_on = datetime.fromisoformat(store["last_import_at"]) + timedelta(hours=49)
        self.assertTrue(registry.stale(store, two_days_on), "so it turns stale like any other feed")
        # A file given by hand is still never dated after the file itself.
        dated = self.write("future.csv", csv_text.replace("2026-11-12 05:30:00", "2099-01-01 00:00:00"))
        os.utime(dated, (1794456000, 1794456000))
        self.cli("feeds", "--store", "remote", "--from", str(dated))
        self.assertEqual(datetime.fromisoformat(db.get_store("remote")["last_feed_update"]).timestamp(), 1794456000)

    def test_awin_is_asked_at_most_once_every_12_seconds(self):
        self.use_the_real_opener()
        base = self.stand_in()
        self.store(network="awin", feed_location=base + "/feed.jsonl", rules={"check_url": base + "/last-updated"})
        with mock.patch.object(refresh.time, "sleep") as sleep:
            refresh.run("remote", say=lambda line: None)
        self.assertEqual(len(StandIn.seen), 2)
        self.assertEqual(sleep.call_count, 1, "the second request waited")
        self.assertTrue(11 < sleep.call_args[0][0] <= 12, sleep.call_args)
        # The next run, in another process (the timer's, right after one started by hand), waits too:
        # when Awin was last asked is kept in the data folder. Here the run before asked it 5 seconds ago.
        (paths.DATA_DIR / "feeds" / "asked.json").write_text(json.dumps({"awin": time.time() - 5}), encoding="utf-8")
        with mock.patch.object(refresh.time, "sleep") as sleep:
            refresh.run("remote", say=lambda line: None)
        self.assertEqual(len(StandIn.seen), 3, "asked again, and the feed had not changed")
        self.assertEqual(sleep.call_count, 1, "its first request waited")
        self.assertTrue(6 < sleep.call_args[0][0] <= 7, sleep.call_args)
        # A kept time that cannot be read counts as "not asked yet": it never stops a run.
        for garbled in ("not json", "[]", '{"awin": "soon"}'):
            (paths.DATA_DIR / "feeds" / "asked.json").write_text(garbled, encoding="utf-8")
            with mock.patch.object(refresh.time, "sleep") as sleep:
                self.assertEqual(refresh.run("remote", say=lambda line: None), 0, garbled)
            sleep.assert_not_called()

    def test_only_one_run_goes_at_a_time(self):
        registry.sync()
        lock = paths.DATA_DIR / "feeds" / "run.lock"
        lock.parent.mkdir(parents=True, exist_ok=True)
        with lock.open("a") as other_run:
            fcntl.flock(other_run, fcntl.LOCK_EX | fcntl.LOCK_NB)        # a run that is still going
            for argv in (["feeds"], ["feeds", "--store", "musterhaus", "--from", str(FEEDS / "musterhaus.csv")]):
                with self.assertRaises(SystemExit) as stopped:
                    self.cli(*argv)
                self.assertEqual(str(stopped.exception),
                                 "another `python -m wardrobe feeds` is running: try again once it has finished")
            self.assertEqual(db.store_products("musterhaus"), [], "nothing was imported")
        self.assertIn("musterhaus: 8 products imported", self.cli("feeds"), "once it has finished, the next run goes")
        self.assertIn("unchanged since", self.cli("feeds"), "and one run after another, too")

    def ago(self, **how_long) -> str:
        return (datetime.now().astimezone() - timedelta(**how_long)).isoformat(timespec="seconds")

    def test_tradedoubler_downloads_of_one_version_are_spread_over_the_day(self):
        self.use_the_real_opener()
        base = self.stand_in()
        StandIn.changed = int(time.time() - 3 * 3600) * 1000                      # the feed changed 3 hours ago
        self.store(network="tradedoubler", feed_location=base + "/feed.jsonl", rules={"check_url": base + "/last-updated"})
        db.note_store("remote", error=None, feed_update=rows.parse_time(StandIn.changed), imported_at=self.ago(hours=3))
        db.note_download("remote", self.ago(minutes=30))
        said = []
        refresh.run("remote", force=True, say=said.append)          # that version was downloaded half an hour ago
        self.assertIn("not downloaded: the network allows 3 downloads of one feed version a day", said[-1])
        self.assertEqual([p for p, _ in StandIn.seen], ["/last-updated"])
        db.note_download("remote", self.ago(hours=9))
        refresh.run("remote", force=True, say=said.append)          # 9 hours later it may be fetched again
        self.assertIn("8 products imported", said[-1])

        StandIn.changed, StandIn.seen = int(time.time() - 600) * 1000, []         # it changed after that download
        db.note_download("remote", self.ago(minutes=20))
        refresh.run("remote", say=said.append)
        self.assertIn("8 products imported", said[-1], "a new version is fetched at once")

        # Changed once more, after the last download, but this file cannot be read. It was still downloaded,
        # so the next run does not fetch the same version again.
        StandIn.changed, StandIn.feed, StandIn.seen = StandIn.changed + 1000, b"<html>Service unavailable</html>", []
        db.note_download("remote", self.ago(minutes=20))
        refresh.run("remote", say=said.append)
        self.assertIn("no product in the file could be read", said[-1])
        refresh.run("remote", say=said.append)
        self.assertIn("not downloaded", said[-1])
        self.assertEqual([p for p, _ in StandIn.seen], ["/last-updated", "/feed.jsonl", "/last-updated"])

    def test_tradedoubler_without_a_check_url_is_downloaded_at_most_3_times_a_day(self):
        # Nowhere to ask first, and the feed's Last-Modified never changes. An hourly timer still makes
        # at most 3 downloads of that one version a day, counting the ones that were not imported.
        self.use_the_real_opener()
        base = self.stand_in()
        StandIn.last_modified = email.utils.formatdate(time.time() - 3600, usegmt=True)     # an hour ago, and it stays
        self.store(network="tradedoubler", feed_location=base + "/feed.jsonl")
        said: list[str] = []
        for hour in range(24):        # a day of an hourly timer: each hour the last download moves an hour back
            this_run: list[str] = []
            refresh.run("remote", force=hour == 5, say=this_run.append)
            said.append(this_run[0])
            last = datetime.fromisoformat(db.get_store("remote")["last_download_at"])
            db.note_download("remote", (last - timedelta(hours=1)).isoformat(timespec="seconds"))
        self.assertEqual(len(StandIn.seen), 3, said)
        self.assertEqual([i for i, line in enumerate(said) if "not downloaded" not in line], [0, 8, 16], "every 8 hours")
        self.assertIn("8 products imported", said[0])
        self.assertIn("unchanged since", said[8])
        self.assertIn("not downloaded: the network allows 3 downloads of one feed version a day", said[5], "--force too")

    def test_a_token_header_is_not_passed_on_when_the_feed_moves(self):
        self.use_the_real_opener()
        base = self.stand_in()
        self.store(feed_location=base + "/moved", rules={"headers": {"Authorization": "Bearer {CAPSULE_TEST_TOKEN}"}})
        with mock.patch.dict(os.environ, {"CAPSULE_TEST_TOKEN": "a-secret"}):
            said = []
            refresh.run("remote", say=said.append)
        self.assertIn("remote: 8 products imported", said[0])
        self.assertEqual(StandIn.seen, [("/moved", "Bearer a-secret"), ("/feed.jsonl", None)])

    def test_in_production_only_https_is_fetched_or_followed(self):
        self.store(feed_location=(FEEDS / "musterhaus.jsonl").as_uri())
        moved, asked = refresh._OnlyHttps(), urllib.request.Request("https://feeds.example.com/feed.jsonl")
        self.assertIsNotNone(moved.redirect_request(asked, None, 302, "Found", {}, "http://127.0.0.1:8102/feed"),
                             "on this computer the tests' stand-in may be followed")
        with mock.patch.object(settings, "PRODUCTION", True):
            said = []
            refresh.run("remote", say=said.append)
            self.assertIn("only https:// feed addresses are fetched", said[0])
            for where in ("http://127.0.0.1:8000/x", "http://localhost/x", "http://[::1]/x", "file:///etc/passwd",
                          "http://feeds.example.com/x"):
                self.assertIsNone(moved.redirect_request(asked, None, 302, "Found", {}, where), where)
            self.assertIsNotNone(moved.redirect_request(asked, None, 302, "Found", {}, "https://cdn.example.com/feed"))
        self.opener.assert_not_called()

    def test_the_opener_never_asks_the_computer_for_its_proxy_settings(self):
        def trap(*args, **kwargs):
            raise AssertionError("the system proxy settings were asked for")

        with mock.patch.multiple(urllib.request, getproxies=trap, getproxies_macosx_sysconf=trap, create=True):
            opener = self.real_opener()
            with opener.open((FEEDS / "musterhaus.jsonl").as_uri(), timeout=5) as answer:
                self.assertTrue(answer.read(1))
            with mock.patch.dict(os.environ, {"https_proxy": "http://127.0.0.1:9"}):   # a proxy set the usual way
                with_proxy = self.real_opener()
        proxies = [h.proxies for h in with_proxy.handlers if isinstance(h, urllib.request.ProxyHandler)]
        self.assertEqual(proxies, [{"https": "http://127.0.0.1:9"}], "taken from the environment, and only from there")
        self.assertFalse([h for h in opener.handlers if isinstance(h, urllib.request.ProxyHandler) and h.proxies])

    def test_the_time_in_an_answer_about_the_last_change(self):
        noon = datetime(2026, 11, 12, 6, 0, tzinfo=timezone.utc)
        listing = ("Advertiser ID,Advertiser Name,Last Imported,URL\n"
                   "900009,Another invented store,2026-11-01 06:00:00,https://feeds.example.com/9\n"
                   "900001,Musterhaus,2026-11-12T06:00:00Z,https://feeds.example.com/1\n")
        for answer in ('{"lastUpdated": 1794463200000}', '"2026-11-12T06:00:00Z"', "2026-11-12T06:00:00Z\n", listing):
            self.assertEqual(datetime.fromisoformat(refresh.version_in(answer, "900001")), noon, answer)
        self.assertIsNone(refresh.version_in(listing, "123"))
        self.assertIsNone(refresh.version_in('{"products": []}', "900001"))


# ── the owner's catalogue view (owner.py, /stores) ────────────────────────────

SAMPLES = (("musterhaus", "musterhaus.jsonl"), ("nordfaden", "nordfaden.csv"), ("kleiderwerk", "kleiderwerk.json"))


class OwnerCatalogue(ProductionCase):
    """The owner's view of every listed store's catalogue, in production: owners only, from the feeds only."""

    def setUp(self):
        super().setUp()
        # The invented samples are left out in production, so they are imported as on the owner's own machine.
        patcher = mock.patch.object(refresh, "_opener", side_effect=AssertionError("a network connection was opened"))
        patcher.start()
        self.addCleanup(patcher.stop)
        with mock.patch.object(settings, "PRODUCTION", False):
            registry.sync()
            for store, name in SAMPLES:
                self.assertEqual(refresh.run(store, from_file=str(FEEDS / name), say=lambda line: None), 0)
        self.products = {f"{p['store']}/{p['product_id']}": p for store, _ in SAMPLES for p in db.store_products(store)}
        self.assertEqual(len(self.products), 17)

    def cli(self, *argv: str) -> str:
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            main(list(argv))
        return out.getvalue()

    def an_owner(self, email="olga@example.com"):
        client = self.member(email)
        self.assertIn("is now an owner", self.cli("owner", "add", email))
        return client

    def shown(self, client, address="/stores") -> list[str]:
        """The products listed on the page, as store/id, in their order."""
        response = client.get(address)
        self.assertEqual(response.status_code, 200, address)
        return re.findall(r'<tr role="row" data-product="([^"]+)">', response.get_data(as_text=True))

    def test_owners_are_marked_in_the_database_from_the_command_line_without_a_restart(self):
        olga = self.member("olga@example.com")
        self.assertEqual(olga.get("/stores").status_code, 404)
        self.assertIn("No owners yet", self.cli("owner"))
        with self.assertRaises(SystemExit) as refused:
            self.cli("owner", "add", "nobody@example.com")
        self.assertIn("There is no account with the address nobody@example.com", str(refused.exception))
        self.assertIn("olga@example.com is now an owner", self.cli("owner", "add", " Olga@Example.com "))
        self.assertIn("olga@example.com is an owner already", self.cli("owner", "add", "olga@example.com"))
        self.assertEqual(olga.get("/stores").status_code, 200, "from the next page, with the same app running")
        self.assertRegex(self.cli("owner", "list"), r"olga@example\.com\s+owner since ")
        self.assertIn("olga@example.com is no longer an owner", self.cli("owner", "remove", "olga@example.com"))
        self.assertEqual(olga.get("/stores").status_code, 404)
        with self.assertRaises(SystemExit) as refused:
            self.cli("owner", "remove", "olga@example.com")
        self.assertIn("is not an owner", str(refused.exception))

    def test_anyone_else_gets_exactly_the_page_that_is_not_there(self):
        # Signed out or signed in, by every method: what /stores answers is what an address that does not exist
        # answers, word for word. Nothing says the page is there, not even "log in first" or "not allowed".
        ada = self.member("ada@example.com")
        visitor = self.app.test_client()
        visitor.get("/login")
        self.an_owner()                                   # there is an owner, just not them

        def answers(client, address):
            token = self.token(client)
            got = [client.get(address), client.head(address), client.options(address),
                   client.get(address, headers=HX), client.post(address), client.post(address, data={"csrf_token": token}),
                   client.put(address, data={"csrf_token": token}), client.delete(address, headers={"X-CSRF-Token": token})]
            return [(r.status_code, sorted(map(same_any_second, r.headers.items())), r.get_data()) for r in got]

        def same_any_second(header):
            # The log-in cookie is signed with the time to the second and carries its expiry date, so two answers a
            # second apart differ there and nowhere else: compare its name and settings, not its value or date.
            name, value = header
            if name.lower() != "set-cookie":
                return header
            cookie, *settings_ = value.split(";")
            kept = sorted(part.strip().lower() for part in settings_ if not part.strip().lower().startswith("expires"))
            return name, cookie.split("=", 1)[0] + "; " + "; ".join(kept)

        for who, client in (("a visitor", visitor), ("a customer", ada)):
            for address in ("/stores", "/stores?store=musterhaus", "/stores/"):
                there, missing = answers(client, address), answers(client, "/no-such-page")
                self.assertEqual(there, missing, f"{who} at {address}")
                self.assertEqual([status for status, _, _ in there], [404, 404, 404, 404, 400, 404, 404, 404])
        page = unescape(page_text(ada.get("/stores").get_data(as_text=True)))
        self.assertIn("We can't find that page", page)
        self.assertNotIn("Store", page)
        account = ada.get("/account").get_data(as_text=True)
        self.assertNotIn("/stores", account)
        self.assertNotIn("catalogue", account.lower())
        self.assertNotIn("stores", self.app.test_client().get("/robots.txt").get_data(as_text=True).lower())

    def test_an_owner_sees_the_page_and_its_link_on_the_account_page(self):
        olga = self.an_owner()
        account = olga.get("/account").get_data(as_text=True)
        self.assertIn('<a class="btn ghost small" href="/stores">Open the store catalogues</a>', account)
        response = olga.get("/stores")
        self.assertEqual(response.status_code, 200)
        self.assertIn('<meta name="robots" content="noindex">', response.get_data(as_text=True))
        self.assertEqual(olga.post("/stores", data={"csrf_token": self.token(olga)}).status_code, 405,
                         "an owner is told the truth: the page takes no forms")
        # On your own machine, one person and no login: the local user is the owner.
        with mock.patch.object(settings, "PRODUCTION", False):
            self.assertEqual(create_app().test_client().get("/stores").status_code, 200)

    def test_each_store_is_listed_with_its_counts_and_dates(self):
        olga = self.an_owner()
        page = unescape(page_text(olga.get("/stores").get_data(as_text=True)))
        self.assertIn("Store catalogues Products from the stores' own feeds, as of each store's feed date.", page)
        for store in db.list_stores():
            line = (f"{store['label']} {store['key']} {owner.NETWORKS[store['network']]} Approved "
                    f"· {store['products']} products Feed of {owner.when(store['last_feed_update'])} "
                    f"Imported {owner.when(store['last_import_at'])}")
            self.assertIn(line, page)
        self.assertEqual([db.get_store(key)["products"] for key, _ in SAMPLES], [8, 5, 4])
        self.assertIn("17 products.", page)
        # What the owner must act on: a failed refresh, a stale feed, products of a store no longer approved.
        db.note_store("nordfaden", error="2026-11-13T06:00:00+01:00: there is no file gone.csv")
        kleiderwerk = {name: db.get_store("kleiderwerk")[name] for name in db.STORE_SETTINGS}
        db.save_store("kleiderwerk", {**kleiderwerk, "status": "applied", "rules": {}})
        with closing(sqlite3.connect(paths.DB_PATH)) as con:
            con.execute("UPDATE stores SET last_feed_update = '2026-01-01T06:00:00+01:00' WHERE key = 'musterhaus'")
            con.commit()
        page = unescape(page_text(olga.get("/stores").get_data(as_text=True)))
        self.assertIn("The last refresh failed: 2026-11-13T06:00:00+01:00: there is no file gone.csv", page)
        self.assertIn("Stale: the feed is older than its refresh hours plus a day", page)
        self.assertIn("No longer approved, yet its products are still here. "
                      "Delete them: python -m wardrobe stores end kleiderwerk", page)

    def test_filtering_by_store_colour_size_category_and_words_narrows_the_list(self):
        olga = self.an_owner()
        every = self.shown(olga)
        self.assertEqual(sorted(every), sorted(self.products), "every product of every store, once")

        def expected(keep) -> list[str]:
            return sorted(key for key, p in self.products.items() if keep(p))

        cases = {
            "/stores?store=nordfaden": lambda p: p["store"] == "nordfaden",
            "/stores?colour=white": lambda p: p["colour_key"] == "white",
            "/stores?colour=navy": lambda p: p["colour_key"] == "navy",
            "/stores?size=M": lambda p: "M" in p["sizes_in_stock"],
            "/stores?size=32/32": lambda p: "32/32" in p["sizes_in_stock"],
            "/stores?store=musterhaus&size=M": lambda p: p["store"] == "musterhaus" and "M" in p["sizes_in_stock"],
            "/stores?category=Herren+>+Hemden": lambda p: p["category"] == "Herren > Hemden",
            "/stores?q=WEISS": lambda p: p["colour"] == "Weiß",
            "/stores?q=navy+merino": lambda p: p["colour_key"] == "navy" and "Merino" in p["name"] + (p["material"] or ""),
        }
        for address, keep in cases.items():
            wanted = expected(keep)
            self.assertTrue(wanted, f"{address} should find something in the samples")
            self.assertLess(len(wanted), len(self.products), address)
            self.assertEqual(sorted(self.shown(olga, address)), wanted, address)
            text = unescape(page_text(olga.get(address).get_data(as_text=True)))
            self.assertIn(f"{len(wanted)} of 17 products match.", text, address)
        self.assertEqual(self.shown(olga, "/stores?size=XXXL"), [])
        self.assertIn("Nothing matches these filters.", unescape(page_text(olga.get("/stores?size=XXXL").get_data(as_text=True))))
        # The filters offer what the products have, each with its count, and keep what was chosen. A store's
        # count is in the stores' table just above, so its option is its name alone (and fits its box).
        page = olga.get("/stores?store=nordfaden&colour=navy").get_data(as_text=True)
        self.assertIn('<option value="nordfaden" selected>Nordfaden (sample)</option>', page)
        self.assertIn("Nordfaden (sample) nordfaden Awin Approved · 5 products", unescape(page_text(page)))
        self.assertEqual(re.findall(r'<option value="(\w+)">', page.split('name="store"')[1].split("</select>")[0]),
                         ["kleiderwerk", "musterhaus"], "every other store with products is offered")
        self.assertIn('<option value="navy" selected>Navy (2)</option>', page)
        self.assertIn('<option value="M">M (5)</option>', page)

    def test_a_product_names_its_brand_only_when_it_is_not_the_store(self):
        for brand, label, shown in (("Kleiderwerk", "Kleiderwerk (sample)", None), ("KLEIDERWERK", "Kleiderwerk (Sample)", None),
                                    ("Kleiderwerk", "Kleiderwerk", None), (None, "Kleiderwerk", None), ("", "Kleiderwerk", None),
                                    ("Feldweg", "Kleiderwerk (sample)", "Feldweg"),
                                    ("Kleiderwerk Studio", "Kleiderwerk (sample)", "Kleiderwerk Studio")):
            self.assertEqual(owner.other_brand(brand, label), shown, (brand, label))
        db.save_store("haus", {"label": "Kaufhaus Beispiel", "network": "awin", "programme_id": None, "status": "approved",
                               "feed_format": "google", "feed_location": None, "delivery_note": None, "disclaimer": None,
                               "rules": {}})
        own, other = ({**rows.product(product_id=pid, name="Hemd", price="30 EUR", brand=brand,
                                      buy_link=f"https://haus.example.com/{pid}"), "imported_at": db.now_iso()}
                      for pid, brand in (("H-1", "kaufhaus beispiel"), ("H-2", "Feldweg")))
        db.replace_products("haus", [own, other])
        olga = self.an_owner()
        lines = re.findall(r'<span class="cat-name" lang="de">[^<]*</span>\s*<span class="cat-sub">([^<]*)</span>',
                           olga.get("/stores?store=haus").get_data(as_text=True))
        self.assertEqual(sorted(unescape(line) for line in lines), ["Feldweg · Kaufhaus Beispiel", "Kaufhaus Beispiel"])
        everything = unescape(olga.get("/stores").get_data(as_text=True))
        for label in ("Musterhaus (sample)", "Nordfaden (sample)", "Kleiderwerk (sample)"):
            name = label.removesuffix(" (sample)")
            self.assertIn(f'<span class="cat-sub">{label}</span>', everything)
            self.assertNotIn(f"{name} · {label}", everything, "the samples' brand is the store's own name")

    def test_photos_and_links_are_the_feeds_own_addresses(self):
        olga = self.an_owner()
        page = olga.get("/stores").get_data(as_text=True)
        photos = [unescape(src) for src in re.findall(r'<img src="([^"]+)"', page)]
        self.assertEqual(sorted(photos), sorted(p["image_url"] for p in self.products.values() if p["image_url"]),
                         "every photo from the feed's address, unchanged: no copy, no proxy")
        links = re.findall(r'<a class="cat-link" href="([^"]+)" target="_blank" rel="sponsored noopener">', page)
        self.assertEqual(sorted(unescape(link) for link in links), sorted(p["buy_link"] for p in self.products.values()))
        css = (paths.ROOT / "wardrobe" / "static" / "app.css").read_text()
        self.assertRegex(css, r"\.cat-pic img \{ object-fit: contain;", "the whole photo, never cropped")
        self.assertNotIn("download", page.lower(), "no export or download from this page")
        self.assertNotIn(".csv", page)

    def test_it_shows_only_the_feeds_products(self):
        olga = self.an_owner()
        self.assertEqual(len(self.shown(olga)), 17, "exactly the rows of the products table")
        for store, _ in SAMPLES:
            registry.end(store)
        page = unescape(page_text(olga.get("/stores").get_data(as_text=True)))
        self.assertIn("No products yet.", page)
        self.assertEqual(self.shown(olga), [])
        self.assertIn("Ended", page)

    def test_a_hundred_to_a_page_with_the_filters_kept(self):
        olga = self.an_owner()
        with mock.patch.object(owner, "PER_PAGE", 4):
            first = olga.get("/stores?store=musterhaus").get_data(as_text=True)
            self.assertIn("8 of 17 products match. Showing 1–4, page 1 of 2.", unescape(page_text(first)))
            self.assertIn('href="/stores?store=musterhaus&amp;page=2" rel="next"', first)
            second = self.shown(olga, "/stores?store=musterhaus&page=2")
            self.assertEqual(len(second), 4)
            self.assertEqual(sorted(self.shown(olga, "/stores?store=musterhaus") + second),
                             sorted(k for k in self.products if k.startswith("musterhaus/")))
            self.assertEqual(self.shown(olga, "/stores?store=musterhaus&page=99"), second, "past the end: the last page")
            self.assertEqual(self.shown(olga, "/stores?page=nonsense"), self.shown(olga, "/stores"))
        self.assertEqual(owner.PER_PAGE, 100)

    def test_the_owner_mark_is_in_the_owners_copy_of_their_data_and_goes_with_the_account(self):
        olga = self.an_owner()
        ada = self.member("ada@example.com")
        self.assertIn("owner_since", json.loads(olga.get("/account/export").data)["account"])
        self.assertNotIn("owner", json.dumps(json.loads(ada.get("/account/export").data)["account"]))
        olga_id = self.user_id("olga@example.com")
        self.post(olga, "/account/delete", current=PASSWORD)
        self.assertFalse(db.is_owner(olga_id))
        self.assertIn("No owners yet", self.cli("owner", "list"))


if __name__ == "__main__":
    unittest.main()
