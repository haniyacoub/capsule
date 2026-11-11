"""The collector, without touching the internet.

The files in tests/fixtures are real store pages cut down to a handful of
products (same HTML shape the parsers read). A fake browser session serves
them, so everything from parsing to the saved catalogue is exercised.
"""
import unittest
from pathlib import Path

from wardrobe import catalog, collect, composition, config, db, paths, scoring, selection
from wardrobe.app import create_app
from wardrobe.collect import cos, manual, matching, pages, weekday, zara
from wardrobe.collect.browser import Blocked, NotAllowed, block_reason
from wardrobe.collect.robots import Robots

FIXTURES = Path(__file__).parent / "fixtures"
COS, WEEKDAY, ZARA = "https://www.cos.com", "https://www.weekday.com", "https://www.zara.com"


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def slot(name, category, colour, keywords=""):
    return {"id": name.lower().replace(" ", "-"), "name": name, "category": category,
            "colour": colour, "keywords": keywords, "qty": 1, "owned": False, "locked": False, "pick": None}


GREY_KNIT = slot("Grey merino jumper", "knit", "grey", "merino crew-neck")
SETTINGS = config.load("stores.toml")


class FakeSession:
    """Stands in for the browser: serves fixture pages, or refuses like a store would."""

    def __init__(self, refuse_products=False, refuse_everything=False):
        self.refuse_products, self.refuse_everything = refuse_products, refuse_everything
        self.pages_loaded: dict[str, int] = {}
        self.opened: list[str] = []

    def fetch(self, store, base, url):
        self.opened.append(url)
        self.pages_loaded[store] = self.pages_loaded.get(store, 0) + 1
        is_product = "/product/" in url or "/p/" in url or "-p0" in url
        if self.refuse_everything or (is_product and self.refuse_products):
            raise Blocked(store, url, "the store answered 403 (Access Denied)")
        if "search" in url:
            raise NotAllowed(url)
        if store == "zara":
            return fixture("zara_product.html" if is_product else "zara_listing.html")
        return fixture(f"{store}_listing.html")


class Parsers(unittest.TestCase):
    def test_cos_category_page(self):
        items = cos.parse_listing(fixture("cos_listing.html"), COS)
        self.assertEqual(len(items), 6)
        for it in items:
            self.assertRegex(it["sku"], r"^\d{10}$")
            self.assertTrue(it["url"].startswith(COS + "/de-de/") and "/product/" in it["url"])
            self.assertIn("imwidth=", it["image_url"])
            self.assertGreater(it["price"], 0)
            self.assertFalse(it["name"].isupper(), "names are made readable")
            self.assertEqual(it["sizes_all"], [], "COS category pages carry no sizes")
        self.assertTrue(any(it["colour_hex"] for it in items))

    def test_weekday_category_page_has_size_stock(self):
        items = weekday.parse_listing(fixture("weekday_listing.html"), WEEKDAY)
        self.assertEqual(len(items), 6)
        self.assertTrue(all(it["url"].startswith(WEEKDAY + "/de-de/p/") and it["url"].endswith("/") for it in items))
        self.assertTrue(all(it["sizes_all"] for it in items))
        self.assertTrue(any(len(it["sizes_in_stock"]) < len(it["sizes_all"]) for it in items), "a sold-out size")
        self.assertTrue(all(it["colour_hex"] is None for it in items), "Weekday's swatch is not the real shade")

    def test_zara_category_page(self):
        items = zara.parse_listing(fixture("zara_listing.html"), ZARA)
        self.assertEqual(len(items), 5)
        first = items[0]
        self.assertEqual(first["price"], 69.95)                      # the page says 6995 cents
        self.assertRegex(first["url"], r"^https://www\.zara\.com/de/de/.+-p\d{8}\.html$")
        self.assertGreater(len(first["colours"]), 1)
        self.assertTrue(all(c["name"] for c in first["colours"]))

    def test_zara_product_page(self):
        detail = zara.parse_product(fixture("zara_product.html"), ZARA)
        self.assertEqual(composition.parse(detail["composition_text"]), [("wool", 100.0)],
                         "the lining is listed after the main fabric and ignored")
        self.assertEqual(len(detail["colours"]), 4)
        khaki = detail["colours"][0]
        self.assertEqual(khaki["price"], 69.95)
        self.assertEqual(khaki["sizes_all"], ["S", "M", "L", "XL"])
        self.assertEqual(khaki["sizes_in_stock"], ["S", "M", "XL"])
        self.assertIn("-e1", khaki["image_url"], "the plain product shot is preferred")
        self.assertNotIn("{width}", khaki["image_url"])
        self.assertIsNone(zara.parse_product("<html>not a product</html>", ZARA))

    def test_next_page_and_names(self):
        self.assertEqual(pages.next_page_url(fixture("cos_listing.html"), COS + "/de-de/men/knitwear/jumper"),
                         COS + "/de-de/men/knitwear/jumper?page=2")
        self.assertIsNone(pages.next_page_url(fixture("cos_listing.html"), COS + "/de-de/men/knitwear/jumper?page=2"))
        self.assertEqual(pages.tidy_name("PULLOVER AUS 100 % WOLLE"), "Pullover aus 100 % Wolle")
        self.assertEqual(pages.tidy_name("Boxy Strickpullover"), "Boxy Strickpullover")
        self.assertEqual(pages.fit_from("Oversized-Pullover aus Alpaka-Mix"), "oversized")
        self.assertEqual(pages.fit_from("Schmaler Merinowollpullover"), "slim")
        self.assertEqual(pages.fit_from("Pullover aus Merinowolle"), "regular")


class Matching(unittest.TestCase):
    def level(self, slot_colour, name, hex_=None, category="knit"):
        return matching.colour_level({"colour": slot_colour, "category": category}, name, hex_)

    def test_the_stores_colour_name_decides(self):
        self.assertEqual(self.level("navy", "NAVY", "#272930"), 2)       # looks black, sold as navy
        self.assertEqual(self.level("black", "NAVY", "#272930"), 0)
        self.assertEqual(self.level("grey", "Grey Mélange"), 2)
        self.assertEqual(self.level("grey", "Hellgrau meliert"), 1)       # a close shade
        self.assertEqual(self.level("grey", "Anthrazit"), 0)              # too dark to be "grey"
        self.assertEqual(self.level("white", "Ecru"), 1)

    def test_unknown_names_fall_back_to_the_swatch(self):
        self.assertEqual(self.level("navy", "Moonlight", "#1f2a44"), 2)
        self.assertEqual(self.level("navy", "Moonlight", "#c8c8c5"), 0)
        self.assertEqual(self.level("navy", "Moonlight", None), 0)

    def test_patterned_and_two_colour_items_are_out(self):
        self.assertEqual(self.level("black", "Schwarz / Weiß"), 0)
        self.assertEqual(self.level("white", "Weiß - Rote Kontrastkanten"), 0)
        self.assertEqual(self.level("beige", "BEIGE / UNDYED"), 2)        # one colour, described twice

    def test_a_pattern_is_not_a_colour(self):
        skip = SETTINGS["collector"]["skip_words"]
        charcoal_trousers = {"colour": "charcoal", "category": "trousers"}
        self.assertEqual(matching.colour_level(charcoal_trousers, "Gestreift", "#3c3e42"), 2, "the swatch alone fits")
        self.assertEqual(matching.colour_level(charcoal_trousers, "Gestreift", "#3c3e42", skip), 0)
        self.assertEqual(matching.colour_level(charcoal_trousers, "Anthrazit", None, skip), 2)

    def test_jeans_blue_counts_as_indigo(self):
        self.assertEqual(self.level("indigo", "Dunkelblau", category="jeans"), 2)
        self.assertEqual(self.level("indigo", "Dunkelblau", category="knit"), 0)

    def test_shortlist_order_and_filters(self):
        def item(name, price, colour="Grau", slug=""):
            return {"store": "x", "sku": name, "name": name, "slug": slug, "price": price,
                    "colour": colour, "colour_hex": None, "in_stock": True}
        items = [
            item("Pullover aus Baumwolle", 30),
            item("Pullover aus Merinowolle mit Rundhalsausschnitt", 80),
            item("Pullover aus Merinowolle", 60),
            item("Cardigan aus Merinowolle", 20),                    # excluded word
            item("Gestreifter Pullover", 10),                        # pattern
            item("Pullover aus Merinowolle", 25, colour="Rot"),      # wrong colour
            {**item("Pullover ausverkauft", 5), "in_stock": False},
        ]
        rules = {"exclude": ["cardigan"]}
        names = [it["name"] for it, _ in matching.shortlist(items, GREY_KNIT, rules, SETTINGS["collector"])]
        self.assertEqual(names, ["Pullover aus Merinowolle mit Rundhalsausschnitt",   # two keywords
                                 "Pullover aus Merinowolle",                           # one keyword
                                 "Pullover aus Baumwolle"])                            # none, cheapest last

    def test_the_slots_own_words_override_the_pattern_filter(self):
        striped = slot("Striped tee", "tee", "white", "striped")
        item = {"store": "x", "sku": "1", "name": "Gestreiftes T-Shirt", "slug": "striped-t-shirt",
                "price": 20, "colour": "Weiß", "colour_hex": None, "in_stock": True}
        self.assertTrue(matching.shortlist([item], striped, {}, SETTINGS["collector"]))
        self.assertFalse(matching.shortlist([item], slot("White tee", "tee", "white"), {}, SETTINGS["collector"]))


class Politeness(unittest.TestCase):
    def test_robots_rules(self):
        robots = Robots("User-agent: *\nDisallow: */search*\nDisallow: /api/\nDisallow: */checkout$\n"
                        "Disallow: *?color=\nAllow: */register-return\nDisallow: */register*\n\n"
                        "User-agent: SomeBot\nDisallow: /\n")
        self.assertTrue(robots.allowed(COS + "/de-de/men/knitwear/jumper"))
        self.assertTrue(robots.allowed(COS + "/de-de/men/knitwear/jumper?page=2"))
        self.assertFalse(robots.allowed(COS + "/de-de/search?q=merino"))
        self.assertFalse(robots.allowed(COS + "/api/products"))
        self.assertFalse(robots.allowed(COS + "/de-de/checkout"))
        self.assertTrue(robots.allowed(COS + "/de-de/checkout-help"))            # "$" means end of address
        self.assertFalse(robots.allowed(ZARA + "/de/de/x-p01234567.html?color=800"))
        self.assertTrue(robots.allowed(ZARA + "/de/de/x-p01234567.html?v1=123"))
        self.assertTrue(robots.allowed(COS + "/de-de/register-return"))           # the longer rule wins
        self.assertTrue(Robots("").allowed(COS + "/anything"))

    def test_the_configured_pages_are_not_search_pages(self):
        for key in collect.STORE_ORDER:
            for garment, rules in SETTINGS[key]["garments"].items():
                for path in rules["pages"]:
                    self.assertNotIn("search", path, f"{key}.{garment}")
                    self.assertNotIn("?", path, f"{key}.{garment}")

    def test_what_counts_as_a_refusal(self):
        self.assertIn("403", block_reason(403, "Access Denied", "<html>Access Denied</html>"))
        self.assertIsNotNone(block_reason(200, "Just a moment", "<html>Please complete the CAPTCHA</html>"))
        self.assertIsNotNone(block_reason(429, "", ""))
        self.assertIsNotNone(block_reason(502, "Bad gateway", ""))
        big_page = "<html>" + "x" * 30_000 + " grecaptcha captcha script </html>"
        self.assertIsNone(block_reason(200, "Pullover für Herren | COS DE", big_page))
        self.assertIsNone(block_reason(404, "Seite nicht gefunden", "<html>nicht gefunden</html>"))


class Collecting(unittest.TestCase):
    def setUp(self):
        for path in (paths.DB_PATH, paths.CATALOG_PATH):
            path.unlink(missing_ok=True)
        catalog._cache = None
        db.init()
        db.replace_slots([GREY_KNIT])
        catalog.save({"source": "collected", "candidates": [], "stores": {}})

    def run_store(self, key, session, limit=3):
        return collect.collect_store(session, key, SETTINGS[key], db.list_slots(), SETTINGS["collector"],
                                     limit, log=lambda *_: None)

    def test_a_store_without_product_pages_is_read_from_the_category_page_only(self):
        session = FakeSession()
        status = self.run_store("weekday", session)
        self.assertEqual(status["status"], "ok")
        self.assertFalse([u for u in session.opened if "/p/" in u], "no product page was opened")
        found = catalog.load()["candidates"]
        self.assertTrue(found)
        for c in found:
            self.assertEqual((c["store"], c["slot_id"], c["source"]), ("weekday", GREY_KNIT["id"], "collected"))
            self.assertEqual(c["composition_text"], "")
            self.assertTrue(c["sizes_all"])

    def test_zara_gets_fabric_and_sizes_from_product_pages(self):
        db.replace_slots([slot("Brown jumper", "knit", "brown")])
        status = self.run_store("zara", FakeSession())
        self.assertEqual(status["status"], "ok")
        found = catalog.load()["candidates"]
        self.assertTrue(found)
        c = found[0]
        self.assertEqual(c["colour"], "Braun")
        self.assertIn("wolle", c["composition_text"].lower())
        self.assertEqual(c["sizes_in_stock"], ["S", "M", "L", "XL"])
        self.assertIn("?v1=", c["url"])
        self.assertEqual(len({x["id"] for x in found}), len(found), "the same product is not listed twice")

    def test_the_first_refusal_stops_that_store_and_keeps_what_was_read(self):
        db.replace_slots([slot("Brown jumper", "knit", "brown"), slot("Grey jumper", "knit", "grey")])
        session = FakeSession(refuse_products=True)
        status = self.run_store("zara", session)
        self.assertEqual(status["status"], "blocked")
        self.assertIn("refused", status["message"])
        products_tried = [u for u in session.opened if "-p0" in u]
        self.assertEqual(len(products_tried), 1, "nothing is retried after a refusal")

        everything = FakeSession(refuse_everything=True)
        status = self.run_store("cos", everything)
        self.assertEqual(status["status"], "blocked")
        self.assertEqual(len(everything.opened), 1)

    def test_refresh_keeps_what_you_added_and_typed(self):
        self.run_store("weekday", FakeSession())
        first = catalog.load()["candidates"][0]

        def by_hand(cat):
            catalog.find(cat, GREY_KNIT["id"], first["id"])["manual"] = {"composition_text": "100% Wolle"}
            cat["candidates"].append({**first, "id": "cos-123", "store": "cos", "source": "manual"})
        catalog.update(by_hand)

        self.run_store("weekday", FakeSession())               # a second refresh
        cat = catalog.load()
        self.assertEqual(catalog.find(cat, GREY_KNIT["id"], first["id"])["manual"], {"composition_text": "100% Wolle"})
        self.assertIsNotNone(catalog.find(cat, GREY_KNIT["id"], "cos-123"))
        ids = [c["id"] for c in cat["candidates"]]
        self.assertEqual(len(ids), len(set(ids)), "nothing is duplicated by refreshing twice")

    def test_real_data_replaces_demo_data_but_not_your_own_items(self):
        cat = {"source": "mock", "note": "demo", "candidates": [
            {"id": "mock-1", "slot_id": "a", "source": "mock"}, {"id": "mine", "slot_id": "a", "source": "manual"}]}
        catalog.start_collected(cat)
        self.assertEqual(cat["source"], "collected")
        self.assertEqual([c["id"] for c in cat["candidates"]], ["mine"])
        catalog.prune(cat, {"b"})
        self.assertEqual(cat["candidates"], [], "candidates of deleted slots are forgotten")


class FabricFromTheName(unittest.TestCase):
    rules = scoring.load_rules()

    def guess(self, name):
        return composition.guess(name, self.rules["fabric"]["name_guess"])[0]

    def test_reading_fibres_out_of_names(self):
        self.assertEqual(self.guess("Pullover aus Merinowolle"), [("merino", 85.0), ("other", 15.0)])
        self.assertEqual(self.guess("PULLOVER REGULAR FIT 100 % WOLLE"), [("wool", 100.0)])
        self.assertEqual(self.guess("Relaxter Rundhalspullover aus Wollmix"), [("wool", 50.0), ("other", 50.0)])
        self.assertEqual(self.guess("Pullover mit Wollanteil"), [("wool", 25.0), ("other", 75.0)])
        self.assertEqual(self.guess("Baumwoll-T-Shirt mit Rundhalsausschnitt"), [("cotton", 85.0), ("other", 15.0)])
        self.assertEqual(self.guess("Pullover aus Merinowoll-Kaschmir-Mix"),
                         [("cashmere", 45.0), ("merino", 45.0), ("other", 10.0)])
        self.assertEqual(self.guess("Sneaker in Lederoptik"), [("polyurethane", 85.0), ("other", 15.0)])
        self.assertEqual(self.guess("Boxy Strickpullover"), [])

    def test_a_guess_is_scored_lower_than_the_label_and_says_so(self):
        listed = scoring.score({"store": "cos", "price": 89, "name": "Pullover aus Merinowolle",
                                "composition_text": "100% Merinowolle"}, "knit", self.rules)
        guessed = scoring.score({"store": "cos", "price": 89, "name": "Pullover aus Merinowolle"}, "knit", self.rules)
        unknown = scoring.score({"store": "cos", "price": 89, "name": "Strickpullover"}, "knit", self.rules)
        self.assertEqual((listed.fabric_source, guessed.fabric_source, unknown.fabric_source), ("listed", "name", "none"))
        self.assertGreater(listed.total, guessed.total)
        self.assertGreater(guessed.total, unknown.total)
        self.assertTrue(guessed.fabric_text.startswith("≈"))
        self.assertIn("estimated from the name", guessed.parts[0].lines[0])

    def test_denim_is_assumed_to_be_cotton(self):
        jeans = scoring.score({"store": "weekday", "price": 60, "name": "Jeans Straight"}, "jeans", self.rules)
        self.assertEqual(jeans.fabric_source, "assumed")
        self.assertIn("typical", jeans.parts[0].lines[0])


class ByHand(unittest.TestCase):
    """Manual import and typed-in details, through the app."""

    def setUp(self):
        for path in (paths.DB_PATH, paths.CATALOG_PATH):
            path.unlink(missing_ok=True)
        catalog._cache = None
        self.client = create_app().test_client()
        self.slot = next(s for s in db.list_slots() if s["category"] == "knit")
        self.sid = self.slot["id"]

        def go_real(cat):
            catalog.start_collected(cat)
            cat["candidates"].append({
                "id": "cos-1260173010", "slot_id": self.sid, "store": "cos", "source": "collected",
                "name": "Schmaler Merinowollpullover", "slug": "slim-merino-wool-crew-neck-jumper-grey-1260173010",
                "price": 69.0, "colour": "Grey", "colour_hex": "#8d8e91", "composition_text": "",
                "sizes_all": [], "sizes_in_stock": [], "url": COS + "/de-de/x/product/slim-1260173010", "image_url": ""})
        catalog.update(go_real)

    def cand(self, cand_id):
        return next(c for c in selection.build().get(self.sid).cands if c.id == cand_id)

    def test_links_that_are_not_from_the_three_stores_are_refused(self):
        self.assertEqual(manual.store_of("https://www.cos.com/de-de/x"), "cos")
        self.assertEqual(manual.store_of("https://www.zara.com/de/de/x-p01234567.html"), "zara")
        self.assertIsNone(manual.store_of("https://www.example.com/cos.com"))
        self.assertIsNone(manual.store_of("javascript:alert(1)"))
        results = manual.from_urls(["https://shop.example.org/jumper"], self.slot)
        self.assertIsNone(results[0][1])

    def test_a_cos_link_is_not_opened_and_gives_what_the_link_says(self):
        link = COS + "/de-de/men/menswear/knitwear/jumpers/merino/product/boiled-merino-wool-crew-neck-jumper-black-1338797001"
        r = self.client.post(f"/slot/{self.sid}/import", data={"urls": link})
        self.assertEqual(r.status_code, 302)
        added = self.cand("cos-1338797001")
        self.assertTrue(added.manual)
        self.assertEqual(added.data["name"], "Boiled merino wool crew neck jumper black")
        self.assertEqual(added.gaps, ["price", "fabric", "sizes"])
        self.assertNotEqual(self.view().chosen.id, added.id, "an item without a price is never picked")

    def test_a_link_seen_during_a_refresh_brings_its_price_and_colour(self):
        link = COS + "/de-de/x/product/slim-merino-wool-crew-neck-jumper-grey-1260173010"
        other = next(s for s in db.list_slots() if s["category"] == "cardigan")
        self.client.post(f"/slot/{other['id']}/import", data={"urls": link})
        copied = next(c for c in selection.build().get(other["id"]).cands if c.id == "cos-1260173010")
        self.assertEqual((copied.price, copied.data["colour"], copied.manual), (69.0, "Grey", True))

    def view(self):
        return selection.build().get(self.sid)

    def test_typed_in_details_complete_an_item_and_change_its_score(self):
        before = self.cand("cos-1260173010")
        self.assertEqual(before.score.fabric_source, "name")
        self.assertFalse(before.size.known)
        self.client.post(f"/slot/{self.sid}/details", data={
            "candidate": "cos-1260173010", "composition": "100% Merinowolle", "sizes": "S, L, XL", "price": ""})
        after = self.cand("cos-1260173010")
        self.assertEqual(after.score.fabric_source, "listed")
        self.assertGreater(after.score.total, before.score.total)
        self.assertTrue(after.size.known)
        self.assertFalse(after.available, "M was not among the sizes typed in")
        self.assertEqual(after.gaps, [])

        self.client.post(f"/slot/{self.sid}/details", data={"candidate": "cos-1260173010", "clear": "1"})
        self.assertEqual(self.cand("cos-1260173010").score.fabric_source, "name")

    def test_nonsense_details_are_reported_not_saved(self):
        r = self.client.post(f"/slot/{self.sid}/details", follow_redirects=True, data={
            "candidate": "cos-1260173010", "composition": "very nice wool", "price": "cheap"})
        self.assertIn("Couldn&#39;t read a composition".encode(), r.data)
        self.assertIn("a price".encode(), r.data)
        self.assertEqual(self.cand("cos-1260173010").score.fabric_source, "name")
        r = self.client.post(f"/slot/{self.sid}/details", data={"candidate": "nope"})
        self.assertEqual(r.status_code, 404)

    def test_only_your_own_items_can_be_removed(self):
        r = self.client.post(f"/slot/{self.sid}/remove", data={"candidate": "cos-1260173010"})
        self.assertEqual(r.status_code, 404, "collected items are not removable")
        link = COS + "/de-de/x/product/some-jumper-black-1338797001"
        self.client.post(f"/slot/{self.sid}/import", data={"urls": link})
        self.client.post(f"/slot/{self.sid}/details", data={"candidate": "cos-1338797001", "price": "59,90"})
        self.assertEqual(self.cand("cos-1338797001").price, 59.9)
        self.client.post(f"/slot/{self.sid}/pick", data={"candidate": "cos-1338797001"})
        self.client.post(f"/slot/{self.sid}/remove", data={"candidate": "cos-1338797001"})
        view = self.view()
        self.assertNotIn("cos-1338797001", [c.id for c in view.cands])
        self.assertEqual(view.state, "auto", "the lock on a removed item is released")

    def test_recolouring_a_slot_drops_what_was_collected_for_the_old_colour(self):
        link = COS + "/de-de/x/product/some-jumper-black-1338797001"
        self.client.post(f"/slot/{self.sid}/import", data={"urls": link})
        r = self.client.post(f"/slots/{self.sid}/save", follow_redirects=True, data={
            "name": "Burgundy jumper", "category": "knit", "colour": "burgundy", "qty": "1", "keywords": ""})
        self.assertEqual([c.id for c in self.view().cands], ["cos-1338797001"],
                         "only the item added by hand is kept")
        self.assertIn(b"python -m wardrobe refresh", r.data)
        self.client.post(f"/slots/{self.sid}/delete")
        self.assertFalse([c for c in catalog.load()["candidates"] if c["slot_id"] == self.sid],
                         "a deleted slot takes its candidates with it")

    def test_pages_work_on_real_data(self):
        for url in ("/", "/outfits", f"/slot/{self.sid}", "/slots"):
            self.assertEqual(self.client.get(url).status_code, 200, url)
        html = self.client.get(f"/slot/{self.sid}").data.decode()
        self.assertIn("Add details", html)
        self.assertIn("Add a product by link", html)
        self.assertIn("View at COS", html)
        self.assertNotIn("Demo data", html)
        self.assertIn("python -m wardrobe refresh --slot", self.client.get(
            f"/slot/{next(s['id'] for s in db.list_slots() if s['category'] == 'coat')}").data.decode())

    def test_refresh_command_checks_its_arguments(self):
        from wardrobe.__main__ import main
        with self.assertRaises(SystemExit) as stop:
            main(["refresh", "--slot", "no-such-slot"])
        self.assertIn("No slot called", str(stop.exception))


if __name__ == "__main__":
    unittest.main()
