"""The fabric pass (python -m wardrobe refresh --pool --fabric): each pooled product's own page, read once, only for its
fabric. Invented product pages, served by a fake browser; nothing touches the internet."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from wardrobe import scoring
from wardrobe.collect import fabric, pool
from wardrobe.collect.browser import Blocked, LimitReached, PageMissing

SCHEMA_PAGE = ('<html><script type="application/ld+json">{"@type": "Product", "name": "Oxford-Hemd", '
               '"material": "100% Baumwolle", "offers": {"price": "49.95", "priceCurrency": "EUR"}}</script></html>')
DATA_PAGE = ('<html><script>window.__product = {"detail": {"composition": [{"part": "1", "composition": ['
             '{"name": "baumwolle", "percentage": "95"}, {"name": "elasthan", "percentage": "5"}]}]}, '
             '"filler": "' + "x" * 500 + '"};</script></html>')
TEXT_PAGE = "<html><body><h2>Material &amp; Pflege</h2><p>Obermaterial: 80% Wolle, 20% Polyamid</p></body></html>"
NOTHING = "<html><body><p>Ein schönes Hemd.</p></body></html>"


class ReadingAProductPage(unittest.TestCase):
    def test_the_fabric_from_its_schema_org_data_its_own_data_or_its_words(self):
        self.assertEqual(fabric.fabric_of(SCHEMA_PAGE), "100% Baumwolle")
        self.assertEqual(fabric.fabric_of(DATA_PAGE), "95% baumwolle, 5% elasthan")
        self.assertEqual(fabric.fabric_of(TEXT_PAGE), "80% Wolle, 20% Polyamid")
        self.assertEqual(fabric.fabric_of(NOTHING), "")
        self.assertEqual(fabric.fabric_of('<p>Material: <b>Baumwolle</b>, sehr weich</p>'), "", "no shares, no fabric")


def product(store, sku, **more):
    return {"id": f"{store}-{sku}", "store": store, "category": "shirt", "name": f"Hemd {sku}", "price": 49.95,
            "url": f"https://www.{store}.example/p/{sku}", "composition_text": "", "source": "collected", **more}


class FakeSession:
    pages: dict = {}
    opened: list = []

    def __init__(self, settings, log=print):
        self.settings = settings

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return None

    def fetch(self, store, base, url):
        FakeSession.opened.append(url)
        if len([u for u in FakeSession.opened if store in u]) > self.settings["max_pages_per_store"]:
            raise LimitReached(store, url, "the run's limit")
        page = FakeSession.pages.get(url, NOTHING)
        if isinstance(page, Exception):
            raise page
        return page


class ThePass(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.local = Path(self.folder.name) / "collect.local.toml"
        self.local.write_text("[musterhaus]\nlabel = \"Musterhaus\"\nbase = \"https://www.musterhaus.example\"\n"
                              "[nordfaden]\nproduct_pages = false\n", encoding="utf-8")
        self.env = mock.patch.dict(os.environ, {"WARDROBE_COLLECT_LOCAL": str(self.local)})
        self.env.start()
        FakeSession.opened = []
        the_pool = pool.empty()
        the_pool["stores"] = {"musterhaus": {"status": "ok"}, "nordfaden": {"status": "ok"}}
        the_pool["products"] = [
            product("musterhaus", "1"),                                         # read: schema.org data
            product("musterhaus", "2", composition_text="100% Leinen", fabric_from="listing"),   # stated: skipped
            product("musterhaus", "3", fabric_words="Baumwolljersey"),          # named without shares: read
            product("musterhaus", "4"),                                         # gone
            product("musterhaus", "5"),
            product("nordfaden", "6"),                                          # its product pages are refused
        ]
        pool.save(the_pool)
        FakeSession.pages = {
            "https://www.musterhaus.example/p/1": SCHEMA_PAGE,
            "https://www.musterhaus.example/p/3": TEXT_PAGE,
            "https://www.musterhaus.example/p/4": PageMissing("https://www.musterhaus.example/p/4"),
            "https://www.musterhaus.example/p/5": DATA_PAGE,
        }

    def tearDown(self):
        self.env.stop()
        pool.pool_path().unlink(missing_ok=True)
        self.folder.cleanup()

    def run_pass(self, most=None, stores=None):
        with mock.patch.object(fabric, "Session", FakeSession):
            return fabric.run(stores, most, log=lambda *_: None)

    def test_each_page_without_a_fabric_is_read_once_and_the_fabric_is_rated_as_stated(self):
        done = self.run_pass()
        self.assertEqual(FakeSession.opened, [f"https://www.musterhaus.example/p/{n}" for n in (1, 3, 4, 5)],
                         "a product whose listing stated its fabric is not opened; a refusing store is not asked")
        mh = done["musterhaus"]
        self.assertEqual((mh.read, mh.found, mh.gone, mh.left, mh.state), (3, 3, 1, 0, "ok"))
        self.assertEqual(done["nordfaden"].skipped, "its product pages are refused to automated browsers")
        products = {p["id"]: p for p in pool.load()["products"]}
        self.assertEqual(products["musterhaus-1"]["composition_text"], "100% Baumwolle")
        self.assertEqual(products["musterhaus-1"]["fabric_from"], "product page")
        self.assertTrue(products["musterhaus-4"]["page_gone"])
        self.assertEqual(products["musterhaus-2"]["fabric_from"], "listing")
        rated = scoring.score(products["musterhaus-1"], "shirt")
        self.assertEqual(rated.fabric_source, "listed", "the rating is no longer an estimate")
        FakeSession.opened = []
        self.run_pass()
        self.assertEqual(FakeSession.opened, [], "a page read once is not read again")

    def test_at_most_so_many_pages_a_run_and_the_next_run_carries_on(self):
        first = self.run_pass(most=2)["musterhaus"]
        self.assertEqual((first.read, first.left), (2, 2))
        second = self.run_pass(most=2)["musterhaus"]
        self.assertEqual((second.read + second.gone, second.left), (2, 0))
        self.assertIn("still without a fabric", fabric.report(second))

    def test_the_first_refusal_stops_that_store(self):
        FakeSession.pages["https://www.musterhaus.example/p/3"] = Blocked("musterhaus", "x", "the store answered 403")
        mh = self.run_pass()["musterhaus"]
        self.assertEqual((mh.state, mh.read), ("blocked", 1))
        self.assertEqual(len(FakeSession.opened), 2, "nothing after the refusal, nothing retried")
        self.assertIn("refused a product page", fabric.report(mh))
        self.assertNotIn("more at", fabric.report(mh), "no time is promised for a store that refuses")

    def test_the_pass_can_be_switched_off(self):
        self.local.write_text(self.local.read_text() + "\n[collector]\nproduct_pages = false\n", encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError, "switched off"):
            self.run_pass()
        self.assertEqual(FakeSession.opened, [])


class TheStoresFile(unittest.TestCase):
    def test_cos_and_weekday_are_marked_and_the_cost_is_said(self):
        from wardrobe import config, paths
        stores = config.load("stores.toml")
        self.assertIs(stores["cos"]["product_pages"], False)
        self.assertIs(stores["weekday"]["product_pages"], False)
        self.assertIs(stores["hm"]["product_pages"], False, "H&M refused them on 22 Nov 2026")
        self.assertIs(stores["collector"]["product_pages"], True)
        self.assertEqual(stores["collector"]["max_product_pages"], 300)
        text = (paths.CONFIG_DIR / "stores.toml").read_text(encoding="utf-8")
        self.assertIn("300 pages are about 45 minutes a store", " ".join(text.replace("#", " ").split()))
        self.assertTrue(json.dumps(stores))      # (plain values only)


class InTurn(unittest.TestCase):
    def test_one_garment_at_a_time_in_turn(self):
        products = [{"id": n, "category": c} for n, c in enumerate(["coat", "coat", "coat", "tee", "jeans", "tee"])]
        self.assertEqual([p["category"] for p in fabric.in_turn(products)],
                         ["coat", "tee", "jeans", "coat", "tee", "coat"])


class WhatCountsAsAStatedFabric(unittest.TestCase):
    def test_fibres_adding_up_to_most_of_it_and_never_a_piece_of_a_sentence(self):
        from wardrobe import composition
        self.assertEqual(composition.stated("100% aus"), "", "cut from '100% aus Baumwolle'")
        self.assertEqual(composition.stated("30% Polyamid, 10% Kaschmir"), "", "only part of the label")
        self.assertEqual(composition.stated("90% Daunen und 10% Federn"), "", "the filling, in fibres not known here")
        self.assertEqual(composition.stated("80/20% Lambswool/Nylon"), "80% Lambswool, 20% Nylon")
        self.assertEqual(composition.stated("54% Leinen/ 44% Baumwolle/ 2% Elasthan"),
                         "54% Leinen, 44% Baumwolle, 2% Elasthan")
        self.assertEqual(composition.stated("Oberstoff: 100% Wolle"), "Oberstoff: 100% Wolle")
        self.assertEqual(fabric.fabric_of("<p>Material: 100% aus Baumwolle, weich</p>"), "100% aus Baumwolle")
        self.assertEqual(fabric.fabric_of("<p>Material: 30% Polyamid, 10% Kaschmir</p>"), "")

    def test_a_word_for_what_was_done_to_the_cloth_is_no_fibre(self):
        from wardrobe import composition
        self.assertEqual(composition.stated("100% gummierte"), "", "rubberised what? cut from a sentence")
        self.assertEqual(composition.stated("100% gummierte Baumwolle"), "100% gummierte Baumwolle")
        self.assertEqual(composition.parse("100% gummierte Baumwolle"), [("cotton", 100.0)])
        self.assertEqual(composition.stated("100% Gummi"), "100% Gummi")

    def test_a_label_without_commas_between_its_fibres(self):
        # As a store's own product page gave it (23 Nov): the first share alone is under 90%, so it once said nothing.
        from wardrobe import composition
        self.assertEqual(composition.stated("89% Baumwolle 9% Viskose 2% Elastan"), "89% Baumwolle, 9% Viskose, 2% Elastan")
        self.assertEqual(composition.parse(composition.stated("89% Baumwolle 9% Viskose 2% Elastan")),
                         [("cotton", 89.0), ("viscose", 9.0), ("elastane", 2.0)])
        self.assertEqual(composition.stated("Obermaterial: 70% Wolle 30% Polyamid"), "Obermaterial: 70% Wolle, 30% Polyamid")
        self.assertEqual(composition.stated("60 % Baumwolle 40 % Polyester"), "60 % Baumwolle, 40 % Polyester")
        self.assertEqual(composition.stated("50% Baumwolle und 50% Lyocell"), "50% Baumwolle und 50% Lyocell",
                         "an 'und' already stands between them")
        self.assertEqual(composition.stated("Baumwolle 98% Elasthan 2%"), "Baumwolle 98% Elasthan 2%",
                         "shares after their fibres are left as they are")

    def test_a_product_whose_page_is_gone_is_not_published(self):
        from wardrobe import catalog, db, paths, shared
        for path in (paths.DB_PATH, paths.CATALOG_PATH):
            path.unlink(missing_ok=True)
        catalog._cache = None
        db.init()
        the_pool = pool.empty()
        the_pool["stores"] = {"musterhaus": {"status": "ok"}}
        the_pool["products"] = [product("musterhaus", "1"), product("musterhaus", "2", page_gone=True)]
        pool.save(the_pool)
        try:
            fresh, _, _ = shared.to_publish()
            self.assertEqual([p["id"] for p in fresh["musterhaus"]], ["musterhaus-1"])
        finally:
            pool.pool_path().unlink(missing_ok=True)
