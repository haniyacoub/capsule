"""Pool mode (python -m wardrobe refresh --pool): every plain product of a store's category pages, sorted into one
garment type each, kept on this computer in data/pool.json and merged per store, then published into a service's
list without touching the other stores' products. Made-up pages only (tests/fixtures), served by a fake browser."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from wardrobe import catalog, collect, config, db, paths, shared
from wardrobe.collect import pool
from wardrobe.collect.browser import Blocked, PageMissing

FIXTURES = Path(__file__).parent / "fixtures"
WEEKDAY = "https://www.weekday.com"
SETTINGS = config.load("stores.toml")["collector"]


class FakeSession:
    """Serves the made-up Weekday page for every address, or refuses from the `refuse_from`-th page on."""

    def __init__(self, refuse_from=None, missing=()):
        self.refuse_from, self.missing = refuse_from, set(missing)
        self.pages_loaded: dict[str, int] = {}
        self.opened: list[str] = []

    def fetch(self, store, base, url):
        self.opened.append(url)
        if url[len(base):] in self.missing:
            raise PageMissing(url)
        self.pages_loaded[store] = self.pages_loaded.get(store, 0) + 1
        if self.refuse_from is not None and len(self.opened) >= self.refuse_from:
            raise Blocked(store, url, "the store answered 403 (Access Denied)")
        return (FIXTURES / "weekday_listing.html").read_text(encoding="utf-8")


def item(name, sku="1", price=20.0, **more):
    return {"store": "musterhaus", "sku": sku, "name": name, "slug": "", "price": price, "url": f"https://x/{sku}",
            **more}


def rules(*garments):
    return {g: pool.rules_of({}, g, SETTINGS) for g in garments}


def a_product(store, sku, category="knit", **more):
    return {"id": f"{store}-{sku}", "store": store, "category": category, "name": f"Product {sku}", "price": 30.0,
            "colour": "Grau", "url": f"https://example.com/{sku}", "source": "collected", **more}


class SortingIntoOneGarment(unittest.TestCase):
    def test_a_shared_page_sorts_each_product_by_its_name(self):
        bottoms = rules("trousers", "chinos", "cargo")
        self.assertEqual(pool.sort(item("Slim Fit Chinohose"), list(bottoms), bottoms, []), ("chinos", ""))
        self.assertEqual(pool.sort(item("Cargohose aus Ripstop"), list(bottoms), bottoms, []), ("cargo", ""))
        self.assertEqual(pool.sort(item("Anzughose aus Wolle"), list(bottoms), bottoms, []), ("trousers", ""))
        tops = rules("tee", "longsleeve")
        self.assertEqual(pool.sort(item("Langarmshirt aus Baumwolle"), list(tops), tops, []), ("longsleeve", ""))
        self.assertEqual(pool.sort(item("T-Shirt in Regular Fit"), list(tops), tops, []), ("tee", ""))
        outer = rules("coat", "jacket", "overshirt")
        self.assertEqual(pool.sort(item("Wollmantel"), list(outer), outer, []), ("coat", ""))
        self.assertEqual(pool.sort(item("Bomberjacke"), list(outer), outer, []), ("jacket", ""))
        self.assertEqual(pool.sort(item("Overshirt aus Cord"), list(outer), outer, []), ("overshirt", ""))

    def test_a_product_that_fits_no_garment_or_two_is_left_out(self):
        bottoms = rules("trousers", "chinos", "cargo")
        self.assertEqual(pool.sort(item("Chino-Shorts"), list(bottoms), bottoms, []), (None, pool.NO_GARMENT))
        two = {"chinos": {"include": ["chino"], "exclude": []}, "cargo": {"include": ["cargo"], "exclude": []}}
        self.assertEqual(pool.sort(item("Cargo-Chino"), ["chinos", "cargo"], two, []), (None, pool.TWO_GARMENTS))
        skip = [w.lower() for w in SETTINGS["skip_words"]]
        self.assertEqual(pool.sort(item("Gestreiftes T-Shirt"), ["tee"], rules("tee"), skip), (None, pool.NOT_PLAIN))

    def test_on_a_page_of_one_garment_the_page_decides_unless_its_words_say_otherwise(self):
        sneakers = rules("sneakers")
        self.assertEqual(pool.sort(item("Air Classic 90"), ["sneakers"], sneakers, []), ("sneakers", ""),
                         "a shoe's name rarely says 'sneaker'")
        self.assertEqual(pool.sort(item("Chelsea Boot"), ["sneakers"], sneakers, []), (None, pool.NO_GARMENT))

    def test_where_a_page_is_one_garments_alone_some_garments_need_no_word_for_it(self):
        longsleeve, hoodie = rules("longsleeve"), rules("hoodie")
        self.assertEqual(pool.sort(item("Nordfaden T-Shirt 4711"), ["longsleeve"], longsleeve, []),
                         ("longsleeve", ""), "a long-sleeve page's T-shirt is a long-sleeve tee")
        self.assertEqual(pool.sort(item("Nordfaden T-Shirt 4711"), ["tee", "longsleeve"], rules("tee", "longsleeve"),
                                   []), ("tee", ""), "on a shared page its words decide")
        self.assertEqual(pool.sort(item("Sweatshirt aus Baumwolle"), ["hoodie"], hoodie, []), (None, pool.NO_GARMENT),
                         "a hoodie page's sweatshirt is not a hoodie")
        self.assertEqual(pool.sort(item("Langarm-Polo"), ["longsleeve"], longsleeve, []), (None, pool.NO_GARMENT),
                         "its exclude words still count")

    def test_a_stores_own_words_replace_the_general_ones(self):
        cos = config.load("stores.toml")["cos"]
        self.assertEqual(pool.rules_of(cos, "chinos", SETTINGS), {"include": ["chino"], "exclude": [],
                                                                  "page_decides": False})
        self.assertIn("jeans", pool.rules_of({}, "trousers", SETTINGS)["exclude"])


class OneProductPerLinkAndColour(unittest.TestCase):
    def test_a_product_listed_twice_is_kept_once(self):
        first = a_product("musterhaus", "1", url="https://example.com/p/l0001?c=250", colour="Weiss")
        again = a_product("musterhaus", "2", url="https://example.com/p/l0001?c=250", colour="Weiss")
        other = a_product("musterhaus", "3", url="https://example.com/p/l0001?c=800", colour="Schwarz")
        kept, copies = pool.distinct([first, again, other])
        self.assertEqual([p["id"] for p in kept], ["musterhaus-1", "musterhaus-3"])
        self.assertEqual(copies, [again])

    def test_collecting_again_under_new_numbers_leaves_no_copy(self):
        the_pool = pool.empty()
        old = a_product("musterhaus", "900001-250", category="tee", url="https://example.com/p/l0001?c=250")
        the_pool["products"] = [old]
        read = pool.Read("musterhaus", "Musterhaus")
        read.products = [a_product("musterhaus", "l0001-250", category="tee", url="https://example.com/p/l0001?c=250")]
        pool.merge(the_pool, read)          # (tee was not read in full: its old products would stay)
        self.assertEqual([p["id"] for p in the_pool["products"]], ["musterhaus-l0001-250"])

    def test_the_size_a_listing_happens_to_show_is_not_part_of_the_number(self):
        # A listing that shows each product in one of its sizes gives the article number with that size after it; the
        # link names the article alone. The next collection may show another size: the product keeps its number.
        link = "https://example.com/Hemden/Musterhaus/Marine/p/30004711/"
        for shown in ("30004711L", "30004711XXL", "300047113XL", "3000471138", "300047113130", "30004711"):
            item = {"store": "musterhaus", "sku": shown, "name": "Hemd", "price": 59.95, "url": link}
            self.assertEqual(pool.product(item, "shirt", "2026-11-23")["id"], "musterhaus-30004711", shown)
        for own, url in (("l0001-250", "https://example.com/p/l0001?c=250"), ("P4711", "https://example.com/hemd-4711"),
                         ("300047119", link)):
            item = {"store": "musterhaus", "sku": own, "name": "Hemd", "price": 59.95, "url": url}
            self.assertEqual(pool.product(item, "shirt", "2026-11-23")["id"], f"musterhaus-{own}", "its own number")


class CollectingAStore(unittest.TestCase):
    STORE = {"label": "Weekday", "base": WEEKDAY, "programme": "rakuten",
             "garments": {"knit": {"pages": ["/men/knitwear/"]}, "cardigan": {"pages": ["/men/knitwear/"]},
                          "hoodie": {"pages": ["/men/hoodies/"]}}}

    def collect(self, session, store=None):
        return pool.collect_store(session, "weekday", store or self.STORE, SETTINGS, log=lambda *_: None)

    def test_every_plain_product_is_kept_once_in_one_garment(self):
        read = self.collect(FakeSession())
        kept = {p["id"]: p["category"] for p in read.products}
        self.assertEqual(kept["weekday-5100000203"], "cardigan")
        self.assertEqual(kept["weekday-5100000001"], "knit")
        self.assertEqual(len(kept), len(read.products), "each product once, though two pages showed it")
        self.assertNotIn("weekday-5100000105", kept, "the striped one is not plain")
        self.assertEqual(len(read.left_out[pool.NOT_PLAIN]), 1)
        for p in read.products:
            self.assertEqual((p["store"], p["source"], p["currency"]), ("weekday", "collected", "EUR"))
            for field in ("name", "price", "colour", "url", "image_url", "sizes_all", "collected_at"):
                self.assertIn(field, p)
        self.assertEqual(read.complete, {"knit", "cardigan", "hoodie"})
        lines = "\n".join(pool.report(read))
        self.assertIn("knit", lines)
        self.assertIn("left out, patterned, a multipack or cropped: 1", lines)

    def test_the_first_refusal_stops_the_store_and_keeps_what_was_read(self):
        session = FakeSession(refuse_from=2)
        read = self.collect(session)
        self.assertEqual(read.state, "blocked")
        self.assertEqual(len(session.opened), 2, "nothing is retried and no other page is tried")
        self.assertTrue(read.products, "the first page's products are kept")

    def test_a_page_that_is_gone_is_an_address_to_fix(self):
        read = self.collect(FakeSession(missing={"/men/hoodies/"}))
        self.assertEqual(read.state, "ok")
        self.assertNotIn("hoodie", read.complete)
        self.assertTrue(any("no longer exists" in note for note in read.notes))


class MergedPerStore(unittest.TestCase):
    def setUp(self):
        pool.pool_path().unlink(missing_ok=True)

    tearDown = setUp

    def read(self, key, products, state="ok", complete=("knit",)):
        read = pool.Read(key, key)
        read.products, read.state, read.complete = products, state, set(complete)
        return read

    def test_a_store_collected_again_replaces_only_its_own_products(self):
        cos = [a_product("cos", "1"), a_product("cos", "2")]
        the_pool = {"collected_at": None, "stores": {"cos": {"status": "ok"}}, "products": [dict(p) for p in cos]}
        pool.merge(the_pool, self.read("musterhaus", [a_product("musterhaus", "9")]))
        pool.merge(the_pool, self.read("musterhaus", [a_product("musterhaus", "8")]))
        self.assertEqual([p["id"] for p in the_pool["products"]], ["cos-1", "cos-2", "musterhaus-8"])
        self.assertEqual(the_pool["products"][:2], cos, "the other store's products are exactly as they were")
        self.assertEqual(the_pool["stores"]["musterhaus"]["products"], 1)

    def test_what_a_products_own_page_gave_is_kept_when_its_store_is_read_again(self):
        the_pool = pool.empty()
        read_page = {"composition_text": "100% Baumwolle", "fabric_from": "product page",
                     "page_read_at": "2026-11-22T10:00:00+01:00"}
        the_pool["products"] = [a_product("musterhaus", "1", **read_page), a_product("musterhaus", "2", page_read_at="x")]
        pool.merge(the_pool, self.read("musterhaus", [a_product("musterhaus", "1"), a_product("musterhaus", "2")]))
        first, second = the_pool["products"]
        self.assertEqual({k: first[k] for k in read_page}, read_page)
        self.assertEqual(second["page_read_at"], "x", "a page read without a fabric is not read again either")

    def test_a_garment_not_read_to_the_end_keeps_its_old_products(self):
        the_pool = pool.empty()
        the_pool["products"] = [a_product("musterhaus", "1", "knit"), a_product("musterhaus", "2", "jeans")]
        pool.merge(the_pool, self.read("musterhaus", [a_product("musterhaus", "3", "knit")], "blocked", ["knit"]))
        self.assertEqual(sorted(p["id"] for p in the_pool["products"]), ["musterhaus-2", "musterhaus-3"])

    def test_the_pool_is_saved_and_read_back(self):
        the_pool = pool.empty()
        pool.merge(the_pool, self.read("musterhaus", [a_product("musterhaus", "1")]))
        pool.save(the_pool)
        self.assertEqual(pool.load()["products"][0]["id"], "musterhaus-1")


class Publishing(unittest.TestCase):
    def setUp(self):
        for path in (paths.DB_PATH, paths.CATALOG_PATH, pool.pool_path()):
            path.unlink(missing_ok=True)
        catalog._cache = None
        db.init()

    def tearDown(self):
        pool.pool_path().unlink(missing_ok=True)

    def test_publishing_the_pool_keeps_the_other_stores_exactly_as_they_were(self):
        before = {"published_at": "2026-11-11T17:55:27+01:00", "collected_at": "2026-11-11T17:00:18+01:00",
                  "stores": {"cos": {"status": "ok"}, "weekday": {"status": "ok"}, "zara": {"status": "ok"}},
                  "products": [a_product("cos", "1"), a_product("weekday", "2"), a_product("zara", "3")]}
        the_pool = pool.empty()
        pool.merge(the_pool, CollectingAStore().collect(FakeSession()))
        pool.save(the_pool)
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder) / shared.POOL_NAME).write_text(json.dumps(before), encoding="utf-8")
            written, kept = shared.publish(Path(folder))
            after = json.loads((Path(folder) / shared.POOL_NAME).read_text(encoding="utf-8"))
        self.assertEqual((written, kept), (len(the_pool["products"]), 2))
        self.assertEqual([p for p in after["products"] if p["store"] in ("cos", "zara")], [before["products"][0],
                                                                                          before["products"][2]])
        self.assertEqual(sorted(p["id"] for p in after["products"] if p["store"] == "weekday"),
                         sorted(p["id"] for p in the_pool["products"]), "Weekday's old products are replaced")
        self.assertEqual(after["stores"]["cos"], {"status": "ok"})
        self.assertIn("gives", after["stores"]["weekday"])
        self.assertIn("left_out", the_pool["stores"]["weekday"], "kept on this computer for its report")
        self.assertNotIn("left_out", after["stores"]["weekday"], "and not published")
        self.assertNotIn("addresses", after["stores"]["weekday"])
        self.assertNotEqual(after["published_at"], before["published_at"])


class TheLocalFileOfAddresses(unittest.TestCase):
    def test_it_is_read_over_the_public_file_and_kept_out_of_the_repository(self):
        with tempfile.TemporaryDirectory() as folder:
            local = Path(folder) / "collect.local.toml"
            local.write_text('[collector]\nmax_listing_pages = 9\n\n[jd-sports.garments.hoodie]\npages = ["/men/hoodies/"]\n'
                             '[zara.garments.tee]\npages = ["/men/t-shirts/"]\n', encoding="utf-8")
            with mock.patch.dict(os.environ, {"WARDROBE_COLLECT_LOCAL": str(local)}):
                merged = collect.load_settings()
                self.assertEqual(merged["collector"]["max_listing_pages"], 9)
                self.assertEqual(merged["collector"]["pause_seconds"], [5, 9], "the rest of the public file stays")
                self.assertEqual(merged["jd-sports"]["label"], "JD Sports")
                self.assertEqual(merged["jd-sports"]["garments"]["hoodie"]["pages"], ["/men/hoodies/"])
                self.assertIn("jd-sports", collect.collected_stores())
                self.assertNotIn("zara", collect.collected_stores(), "a store without a programme is never read")
        self.assertNotIn("jd-sports", collect.collected_stores(), "the tests read no local file of their own")
        ignored = (paths.ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
        self.assertIn("config/collect.local.toml", ignored)


class TheFabricAListingNames(unittest.TestCase):
    def test_a_fabric_named_without_its_shares_is_an_estimate_from_that_name(self):
        from wardrobe import scoring
        tee = {"store": "hm", "name": "T-Shirt in Slim Fit", "slug": "productpage.0000000001", "price": 9.99}
        unnamed = scoring.score(tee, "tee")
        named = scoring.score({**tee, "fabric_words": "Baumwolljersey"}, "tee")
        self.assertNotEqual(unnamed.fabric_source, "name", "nothing in its name says a fibre")
        self.assertEqual(named.fabric_source, "name", "an estimate still, from the fabric's name")
        self.assertEqual(named.comp[0][0], "cotton")
        self.assertIn("only the fabric's name, “Baumwolljersey”: estimated from that", named.parts[0].lines[0])


class WordsAtTheEdgeOfAWord(unittest.TestCase):
    """Words are found inside other words (German makes one word of several), except at an edge a rule marks."""

    def test_a_coating_is_not_a_coat_and_a_draft_shirt_is_no_t_shirt(self):
        outer = rules("coat", "jacket", "overshirt")
        self.assertEqual(pool.sort(item("Nordfaden Jacke mit Coating"), list(outer), outer, []), ("jacket", ""))
        self.assertEqual(pool.sort(item("Nordfaden Raincoat"), list(outer), outer, []), ("coat", ""))
        self.assertEqual(pool.sort(item("Wollmantel"), list(outer), outer, []), ("coat", ""), "inside a word still")
        shirts = rules("shirt", "overshirt")
        draft = item("L/S Draft Shirt", slug="l-s-draft-shirt-black-4711")
        self.assertEqual(pool.sort(draft, list(shirts), shirts, []), ("shirt", ""))
        self.assertEqual(pool.sort(item("Langarm-T-Shirt"), list(shirts), shirts, []), (None, pool.NO_GARMENT))
        self.assertTrue(pool.has("vest sweater vest-sweater", [" vest"]), "the start of the text is an edge too")
        self.assertFalse(pool.has("harvest shirt", [" vest"]))

    def test_the_shared_pages_cases(self):
        shirts, outer = rules("shirt", "overshirt"), rules("coat", "jacket", "overshirt")
        for garments in (shirts, outer):
            self.assertEqual(pool.sort(item("Nordfaden Shirt Jac"), list(garments), garments, []), ("overshirt", ""))
        self.assertEqual(pool.sort(item("S/S Nordfaden Shirt"), list(shirts), shirts, []), (None, pool.NO_GARMENT),
                         "a short-sleeved shirt is no shirt of the plan")
        knits = rules("knit", "cardigan", "hoodie")
        self.assertEqual(pool.sort(item("Nordfaden Knit Jacket"), list(knits), knits, []), ("cardigan", ""))
        self.assertEqual(pool.sort(item("Nordfaden Sweater Jacket"), list(knits), knits, []), ("cardigan", ""))
        for name in ("Nordfaden Vest Sweater", "Nordfaden Sakko", "Nordfaden Sweatjacke"):
            self.assertEqual(pool.sort(item(name), list(knits), knits, []), (None, pool.NO_GARMENT), name)


class WhatALeftOutProductIs(unittest.TestCase):
    WORDS = pool.words_of({"skip_words": ["teamline"], "own_brands": ["Musterhaus"]}, SETTINGS)

    def judge(self, product, garments=("tee",)):
        return pool.judge(product, set(garments), rules(*garments), self.WORDS)

    def test_a_pattern_its_colour_names_is_a_pattern(self):
        self.assertEqual(self.judge(item("T-Shirt", colour="Weiß/Gestreift")), (None, pool.NOT_PLAIN))
        self.assertEqual(self.judge(item("T-Shirt", colour="blau-weiß gestreift")), (None, pool.NOT_PLAIN))
        self.assertEqual(self.judge(item("T-Shirt", colour="Weiß")), ("tee", ""))

    def test_a_print_its_colour_names_is_not_plain(self):
        for colour in ("Schwarz/Nordlicht Club", "Weiß/Musterband® Originals", "Dunkelgrau/Colourblocking"):
            self.assertEqual(self.judge(item("T-Shirt", colour=colour)), (None, pool.NOT_PLAIN), colour)
        for colour in ("Schwarz/Weiß", "Cremefarben/Dunkelbraun", "Black / Dk Slate Grey", "Black / Xq 205 White / White"):
            self.assertEqual(self.judge(item("T-Shirt", colour=colour)), ("tee", ""), f"two colours: {colour}")

    def test_sportswear_underwear_and_a_stores_own_words(self):
        self.assertEqual(self.judge(item("Trainingshose"), ("trousers",)), (None, pool.NOT_EVERYDAY))
        self.assertEqual(self.judge(item("Nordfaden Unterzieh-T-Shirt")), (None, pool.NOT_EVERYDAY))
        self.assertEqual(self.judge(item("Teamline Tee")), (None, pool.NOT_EVERYDAY), "the store's own word")
        general = pool.words_of({}, SETTINGS)
        self.assertEqual(pool.judge(item("Teamline Tee"), {"tee"}, rules("tee"), general), ("tee", ""))

    def test_another_brand_sold_there_too(self):
        self.assertEqual(self.judge(item("T-Shirt", brand="Nordfaden")), (None, pool.ANOTHER_BRAND))
        self.assertEqual(self.judge(item("T-Shirt", brand="MUSTERHAUS")), ("tee", ""))
        self.assertEqual(self.judge(item("T-Shirt")), ("tee", ""), "where the page names no brand, it is kept")
        self.assertEqual(pool.judge(item("T-Shirt", brand="Nordfaden"), {"tee"}, rules("tee"), pool.words_of({}, SETTINGS)),
                         ("tee", ""), "a store selling many brands keeps them all")
        self.assertEqual(self.judge(item("T-Shirt", price=None)), (None, pool.NO_PRICE))

    def test_one_picture_shows_one_colour(self):
        # Its own number in the picture's address: it keeps it. The other colour shows none.
        black = a_product("musterhaus", "4711L", colour="Schwarz", image_url="https://img.example/4711-front.jpg")
        navy = a_product("musterhaus", "4712", colour="Marine", image_url="https://img.example/4711-front.jpg")
        other = a_product("musterhaus", "4713", colour="Marine", image_url="https://img.example/4713-front.jpg")
        self.assertEqual(pool.one_picture_each([black, navy, other]), 1)
        self.assertEqual([p["image_url"] for p in (black, navy, other)],
                         ["https://img.example/4711-front.jpg", "", "https://img.example/4713-front.jpg"])
        # No number of theirs in it: which colour it shows is not known, so neither shows it.
        white = a_product("musterhaus", "1", colour="Weiß", image_url="https://img.example/A7_89.jpg")
        grey = a_product("musterhaus", "2", colour="Grau", image_url="https://img.example/A7_89.jpg")
        self.assertEqual(pool.one_picture_each([white, grey]), 2)
        self.assertEqual((white["image_url"], grey["image_url"]), ("", ""))


class SortingAgainWithoutOpeningAPage(unittest.TestCase):
    CFG = {"collector": SETTINGS,
           "musterhaus": {"label": "Musterhaus", "base": "https://example.com", "garments": {
               "overshirt": {"pages": ["/jacken"]}, "jacket": {"pages": ["/jacken"]}, "coat": {"pages": ["/jacken"]},
               "trousers": {"pages": ["/hosen"]}, "chinos": {"pages": ["/hosen"]}}},
           "nordfaden": {"label": "Nordfaden", "base": "https://example.org"}}

    def a_pool(self):
        the_pool = pool.empty()
        the_pool["products"] = [
            a_product("musterhaus", "1", category="jacket", name="Nordfaden Shirt Jac", page_read_at="2026-11-22",
                      composition_text="100% Baumwolle", fabric_from="product page"),
            a_product("musterhaus", "2", category="trousers", name="Trainingshose"),
            a_product("musterhaus", "3", category="chinos", name="Chinohose", colour="Rot",
                      url="https://example.com/Hosen/Chino/Bordeaux/p/3/"),
            a_product("musterhaus", "4", category="chinos", name="Chinohose", colour="Rot",
                      url="https://example.com/Hosen/Chino/Bordeaux/p/3/"),
            a_product("nordfaden", "9", category="tee", name="Nordfaden T-Shirt")]
        the_pool["stores"] = {
            "musterhaus": {"status": "ok", "message": "", "gives": "", "products": 4, "pages": 2, "label": "Musterhaus",
                           "left_out": {pool.NO_GARMENT: {"count": 5, "examples": ["Henley (tee)"]}}},
            "nordfaden": {"status": "ok", "message": "", "gives": "", "products": 1, "pages": 1, "label": "Nordfaden"}}
        return the_pool

    def test_each_product_is_judged_again_as_a_new_collection_would(self):
        the_pool = self.a_pool()
        untouched = json.dumps([p for p in the_pool["products"] if p["store"] == "nordfaden"])
        results = pool.sort_again(the_pool, self.CFG, ["musterhaus"])
        kept = {p["id"]: p for p in the_pool["products"] if p["store"] == "musterhaus"}
        self.assertEqual(kept["musterhaus-1"]["category"], "overshirt", "the jacket page's shirt jacket")
        self.assertEqual((kept["musterhaus-1"]["composition_text"], kept["musterhaus-1"]["page_read_at"]),
                         ("100% Baumwolle", "2026-11-22"), "what its own page said stays")
        self.assertNotIn("musterhaus-2", kept, "sportswear")
        self.assertEqual(kept["musterhaus-3"]["colour"], "Bordeaux", "the colour its own link names")
        self.assertNotIn("musterhaus-4", kept, "the same link and colour: one product")
        self.assertEqual(json.dumps([p for p in the_pool["products"] if p["store"] == "nordfaden"]), untouched)
        self.assertEqual(results["musterhaus"].left_out[pool.NOT_EVERYDAY], ["Trainingshose"])
        said = the_pool["stores"]["musterhaus"]
        self.assertEqual(said["products"], 2, "the store's line counts what the pool holds now")
        self.assertEqual(said["left_out"][pool.NO_GARMENT]["count"], 5, "what its collection left out stays counted")
        self.assertEqual(said["left_out"][pool.NOT_EVERYDAY]["count"], 1)
        self.assertEqual(said["left_out"][pool.TWICE]["count"], 1)

    def test_the_report_covers_every_store_the_pool_holds(self):
        the_pool = self.a_pool()
        pool.sort_again(the_pool, self.CFG, ["musterhaus"])
        with tempfile.TemporaryDirectory() as folder, mock.patch.object(paths, "DATA_DIR", Path(folder)):
            pool.write_report(the_pool)
            text = pool.report_path().read_text(encoding="utf-8")
        self.assertIn("Musterhaus (musterhaus): 2 products kept", text)
        self.assertIn("Nordfaden (nordfaden): 1 products kept", text)
        self.assertIn(f"left out, {pool.NO_GARMENT}: 5 (e.g. Henley (tee))", text)
        self.assertIn(f"left out, {pool.NOT_EVERYDAY}: 1 (e.g. Trainingshose)", text)
