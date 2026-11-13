"""The store feeds (wardrobe/feeds/), without touching the internet.

The files in tests/fixtures/feeds are invented: three made-up stores (Musterhaus, Nordfaden and
Kleiderwerk) with made-up products, prices, ids and example.com / example.org addresses, one for
each format the importers read. No test opens a network connection: the downloader's opener is
replaced in every test, and a test fails if it was used, except where a test hands it a file://
address or a stand-in server on this computer on purpose.
"""
import contextlib
import email.utils
import gzip
import io
import json
import os
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
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from wardrobe import config, db, paths, settings
from wardrobe.__main__ import main
from wardrobe.feeds import awin_csv, google, refresh, registry, rows, tradedoubler

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
        refresh._last_request.clear()
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

    def test_a_database_at_version_4_gains_the_store_tables_and_nothing_else_changes(self):
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
                              ("index", "sqlite_autoindex_stores_1"), ("table", "products"), ("table", "stores")])
            self.assertEqual({t: sorted(con.execute(f"SELECT * FROM {t}").fetchall()) for t in old_tables},  # nosec
                             rows_before, "every row is as it was")
            self.assertEqual(con.execute("PRAGMA user_version").fetchone()[0], 5)
        db.init()                                                   # starting again changes nothing
        with closing(sqlite3.connect(paths.DB_PATH)) as con:
            self.assertEqual(set(con.execute("SELECT type, name, tbl_name, sql FROM sqlite_master")), after)
        with db.as_user(2):
            self.assertEqual(db.get_setting("mode"), "cheapest")
            self.assertEqual([s["id"] for s in db.list_slots()], ["white-tee"])


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
        self.assertIn("nordfaden: failed, and its products are kept as they were: there is no file tests/fixtures/feeds/gone.csv", said)
        self.assertEqual(str(stopped.exception), "1 store failed; the reason is above and in `python -m wardrobe stores`.")
        self.assertIn("last refresh failed", self.cli("stores"))
        db.save_store("nordfaden", nordfaden)
        self.cli("feeds", "--store", "nordfaden")
        self.assertIsNone(db.get_store("nordfaden")["last_error"], "a refresh that works clears the error")

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
        # A real store's file is not licensed until its programme has approved Capsule: nothing of it is kept.
        for status in ("none", "applied", "refused"):
            db.save_store("real", a_store(status=status))
            with self.assertRaises(SystemExit) as refused:
                self.cli("feeds", "--store", "real", "--from", str(FEEDS / "musterhaus.jsonl"))
            self.assertEqual(str(refused.exception), f"real is {status!r}, not approved: Capsule takes a store's products "
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
        self.send_header("Content-Length", str(len(body)))
        if self.path.startswith("/feed.jsonl") and type(self).last_modified:
            self.send_header("Last-Modified", type(self).last_modified)
        self.end_headers()
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
        StandIn.last_modified = ""
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

    def test_awin_is_asked_at_most_once_every_12_seconds(self):
        self.use_the_real_opener()
        base = self.stand_in()
        self.store(network="awin", feed_location=base + "/feed.jsonl", rules={"check_url": base + "/last-updated"})
        with mock.patch.object(refresh.time, "sleep") as sleep:
            refresh.run("remote", say=lambda line: None)
        self.assertEqual(len(StandIn.seen), 2)
        self.assertEqual(sleep.call_count, 1, "the second request waited")
        self.assertTrue(11 < sleep.call_args[0][0] <= 12, sleep.call_args)

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


if __name__ == "__main__":
    unittest.main()
