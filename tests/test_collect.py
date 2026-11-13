"""The collector, without touching the internet.

The files in tests/fixtures are made-up pages in the shape of each store's
own pages (the same tags and JSON the parsers read), with a handful of
invented products: names, prices, ids and picture addresses are not real.
A fake browser session serves them, so everything from parsing to the saved
catalogue is exercised.
"""
import contextlib
import html
import io
import json
import re
import unittest
from pathlib import Path
from unittest import mock

from wardrobe import catalog, collect, composition, config, db, paths, scoring, selection, shared
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
        self.assertEqual([pages.fit_from(f"{it['name']} {it['slug']}") for it in items], ["relaxed"] * 6,
                         "every name on the page says its cut, as on the store's own page")

    def test_zara_category_page(self):
        items = zara.parse_listing(fixture("zara_listing.html"), ZARA)
        self.assertEqual(len(items), 5)
        first = items[0]
        self.assertEqual(first["price"], 59.95)                      # the page says 5995 cents
        self.assertRegex(first["url"], r"^https://www\.zara\.com/de/de/.+-p\d{8}\.html$")
        self.assertGreater(len(first["colours"]), 1)
        self.assertTrue(all(c["name"] for c in first["colours"]))
        self.assertEqual([pages.fit_from(f"{it['name']} {it['slug']}") for it in items],
                         ["regular", "relaxed", "regular", "regular", "regular"])

    def test_zara_product_page(self):
        detail = zara.parse_product(fixture("zara_product.html"), ZARA)
        self.assertEqual(composition.parse(detail["composition_text"]), [("wool", 100.0)],
                         "the lining is listed after the main fabric and ignored")
        self.assertEqual(len(detail["colours"]), 4)
        khaki = detail["colours"][0]
        self.assertEqual(khaki["price"], 59.95)
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
        self.assertEqual(pages.tidy_name("Boxy Pullover in kurzer Form aus Feinstrick"),
                         "Boxy Pullover in kurzer Form aus Feinstrick")
        self.assertEqual(pages.fit_from("Oversized-Pullover aus Alpaka-Mix"), "oversized")
        self.assertEqual(pages.fit_from("Schmal geschnittener Pullover aus Merinowolle"), "slim")
        self.assertEqual(pages.fit_from("Pullover aus Merinowolle"), "regular")

    def test_a_straight_leg_is_neither_slim_nor_wide(self):
        # Two jeans with a straight leg, name and description joined as the collector reads them.
        for sku, description in STRAIGHT_FIT_JEANS.items():
            self.assertEqual(pages.fit_from(f"Jeans Straight Fit {description}"), "regular", sku)
        self.assertEqual(pages.fit_from("Hose, nicht zu weit geschnitten"), "regular")
        self.assertEqual(pages.fit_from("Keine schmale Passform"), "regular")
        self.assertEqual(pages.fit_from("Neither slim nor wide"), "regular")
        self.assertEqual(pages.fit_from("A shirt that is not slim"), "regular")

    def test_only_the_denied_words_are_taken_back(self):
        self.assertEqual(pages.fit_from("Barrel-Jeans Modellgröße 183 cm. Weiter Schnitt an Oberschenkel und Knie, "
                                        "nach unten hin zulaufend."), "relaxed")
        self.assertEqual(pages.fit_from("Nicht dehnbar. Schmal geschnitten."), "slim")
        self.assertEqual(pages.fit_from("Jeans, weder zu eng noch zu weit, mit schmalem Bein"), "slim")
        self.assertEqual(pages.fit_from("Bootcut-Jeans mit geradem Bein bis zum Knie, das sich zum Saum hin leicht "
                                        "weitet."), "relaxed")


# Two made-up jeans descriptions with the phrases Zara uses for a straight leg. Before the cut reader
# took denied words out, the first read as slim ("schmaler") and the second as relaxed ("weiter");
# both say the leg is straight.
STRAIGHT_FIT_JEANS = {
    "zara-01000001-400": "Jeans mit geradem Bein und einer Passform, die weder schmaler noch weiter wird. Hoher "
                         "Bund. Fester Baumwoll-Denim. Fünf Taschen und Knopfleiste.",
    "zara-01000002-405": "Modellgröße 186 cm. Gerade geschnittene Jeans, die weder enger noch weiter wird. Mittlere "
                         "Leibhöhe. Steifer Denim mit Waschung. Knopfverschluss.",
}


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

    def test_the_collector_is_for_this_computer_only_and_never_scheduled(self):
        from wardrobe.__main__ import main
        printed = io.StringIO()
        with self.assertRaises(SystemExit), contextlib.redirect_stdout(printed):
            main(["refresh", "--help"])
        said = " ".join(printed.getvalue().split())
        for promise in ("Reads COS, Weekday and Zara category pages (and Zara's product pages for fabric and sizes)",
                        "For your own machine and for testing only", "never on a schedule",
                        "never use what it collects as the source for the public site"):
            self.assertIn(promise, said)
        # Nothing that runs on a server or on GitHub starts it: the container, gunicorn's settings, the
        # deploy folder and its subfolders (secret .env files left unread) and the workflows name neither
        # the command nor the collector's code.
        root = Path(__file__).parent.parent
        server_side = [root / "Dockerfile", root / "gunicorn.conf.py",
                       *(p for p in (root / "deploy").rglob("*") if p.is_file() and not p.name.endswith(".env")),
                       *(root / ".github" / "workflows").iterdir()]
        self.assertGreater(len(server_side), 5)
        for path in server_side:
            found = [line for line in path.read_text(encoding="utf-8").splitlines()
                     if re.search(r"wardrobe\s+refresh|wardrobe\.collect|collect\.refresh", line)]
            self.assertEqual(found, [], path.name)


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
        self.assertEqual([c["fit"] for c in found], ["relaxed", "relaxed"], "the cut each name announces")

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
        self.assertEqual(c["fit"], "regular", "the cut is read from the product page's name and description")
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
        self.assertEqual(self.guess("GROBSTRICKPULLOVER IN REGULAR FIT AUS 100 % WOLLE"), [("wool", 100.0)])
        self.assertEqual(self.guess("Relaxter Pullover mit Rippbündchen aus Wollmix"), [("wool", 50.0), ("other", 50.0)])
        self.assertEqual(self.guess("Pullover mit Wollanteil"), [("wool", 25.0), ("other", 75.0)])
        self.assertEqual(self.guess("Baumwoll-T-Shirt mit Rundhalsausschnitt"), [("cotton", 85.0), ("other", 15.0)])
        self.assertEqual(self.guess("Pullover aus Merinowoll-Kaschmir-Mix"),
                         [("cashmere", 45.0), ("merino", 45.0), ("other", 10.0)])
        self.assertEqual(self.guess("Sneaker in Lederoptik"), [("polyurethane", 85.0), ("other", 15.0)])
        self.assertEqual(self.guess("Boxy Pullover in kurzer Form aus Feinstrick"), [])

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


class PublishedListReadAgain(unittest.TestCase):
    """The store list all customers share is read with today's rules: a cut misread when the stores
    were visited is corrected for every customer, without asking any store again."""

    PUBLISHED = "2026-11-11T17:55:27.180518+01:00"

    def setUp(self):
        for path in (paths.DB_PATH, paths.CATALOG_PATH):
            path.unlink(missing_ok=True)
        catalog._cache = shared._cache = None
        db.init()
        db.replace_slots([slot("Indigo jeans", "jeans", "indigo"), slot("Grey wool trousers", "trousers", "grey")])
        pool = {"published_at": self.PUBLISHED, "collected_at": "2026-11-11T17:00:18+01:00", "stores": {}, "products": [
            self.product("zara-01000001-400", "slim", STRAIGHT_FIT_JEANS["zara-01000001-400"]),
            self.product("zara-01000002-405", "relaxed", STRAIGHT_FIT_JEANS["zara-01000002-405"]),
            # Its cut came from its web address ("relaxed-…"): there is no description to read again.
            self.product("cos-1", "relaxed", "", store="cos", name="Hose aus Wolle", category="trousers",
                         colour="Grey", slug="relaxed-wool-trousers-grey-1")]}
        (paths.DATA_DIR / shared.POOL_NAME).write_text(json.dumps(pool, ensure_ascii=False), encoding="utf-8")

    def tearDown(self):
        (paths.DATA_DIR / shared.POOL_NAME).unlink(missing_ok=True)
        catalog._cache = shared._cache = None

    @staticmethod
    def product(pid, fit, description, store="zara", name="Jeans Straight Fit", category="jeans", colour="Blau",
                slug=""):
        """A product as `python -m wardrobe publish` writes it, with the cut it was given on 11 Nov."""
        return {"id": pid, "store": store, "name": name, "slug": slug, "price": 39.95, "price_before": None,
                "currency": "EUR", "colour": colour, "colour_hex": None, "composition_text": "100% baumwolle",
                "fit": fit, "description": description, "sizes_all": ["40", "42", "44"],
                "sizes_in_stock": ["40", "42", "44"], "url": f"https://www.example.com/{pid}", "image_url": "",
                "source": "collected", "collected_at": "2026-11-11T16:59:22+01:00", "category": category}

    def test_the_cut_is_read_again_from_the_stores_own_words(self):
        fits = {p["id"]: p["fit"] for p in shared.load()["products"]}
        self.assertEqual(fits, {"zara-01000001-400": "regular", "zara-01000002-405": "regular", "cos-1": "relaxed"})
        on_disk = json.loads((paths.DATA_DIR / shared.POOL_NAME).read_text(encoding="utf-8"))
        self.assertEqual([p["fit"] for p in on_disk["products"]], ["slim", "relaxed", "relaxed"],
                         "the published file itself is left as it is")

    def test_every_customer_gets_the_corrected_cut_once(self):
        # A customer whose products were built from this list before the correction: the jeans say "Slim cut".
        jeans = {**self.product("zara-01000001-400", "slim", STRAIGHT_FIT_JEANS["zara-01000001-400"]),
                 "slot_id": "indigo-jeans"}
        catalog.save({"source": "collected", "collected_at": "2026-11-11T17:00:18+01:00", "stores": {},
                      "pool": self.PUBLISHED, "candidates": [jeans]})
        db.set_setting("pool", self.PUBLISHED)
        before = selection.build().get("indigo-jeans").chosen
        self.assertTrue(any(note.startswith("Slim cut") for note in before.check.notes), before.check.notes)

        with mock.patch.object(shared, "build_catalog", wraps=shared.build_catalog) as rebuild:
            shared.refresh_customer()
            shared.refresh_customer()                   # the next page they open
        self.assertEqual(rebuild.call_count, 1, "rebuilt once, not on every page")
        self.assertEqual(db.get_setting("pool"), self.PUBLISHED + "#refused")
        after = selection.build().get("indigo-jeans")
        self.assertEqual({c.id: c.data["fit"] for c in after.cands},
                         {"zara-01000001-400": "regular", "zara-01000002-405": "regular"})
        self.assertFalse([note for note in after.chosen.check.notes if "Slim" in note], after.chosen.check.notes)

    def test_a_new_customer_starts_on_the_corrected_list(self):
        built = shared.build_catalog(db.list_slots(), None)
        self.assertEqual({c["id"]: c["fit"] for c in built["candidates"]},
                         {"zara-01000001-400": "regular", "zara-01000002-405": "regular", "cos-1": "relaxed"})
        db.set_setting("pool", built["pool"])           # what sign-up keeps (onboarding.ensure_setup)
        with mock.patch.object(shared, "build_catalog", wraps=shared.build_catalog) as rebuild:
            shared.refresh_customer()
        self.assertEqual(rebuild.call_count, 0, "nothing to rebuild right after sign-up")


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
                "id": "cos-4100000901", "slot_id": self.sid, "store": "cos", "source": "collected",
                "name": "Schmal geschnittener Pullover aus Merinowolle",
                "slug": "slim-fine-merino-crew-neck-jumper-grey-4100000901",
                "price": 69.0, "colour": "Grey", "colour_hex": "#8d8e91", "composition_text": "",
                "sizes_all": [], "sizes_in_stock": [], "url": COS + "/de-de/x/product/slim-4100000901", "image_url": ""})
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
        link = COS + "/de-de/men/menswear/knitwear/jumpers/merino/product/brushed-merino-crew-neck-jumper-black-4100000902"
        r = self.client.post(f"/slot/{self.sid}/import", data={"urls": link})
        self.assertEqual(r.status_code, 302)
        added = self.cand("cos-4100000902")
        self.assertTrue(added.manual)
        self.assertEqual(added.data["name"], "Brushed merino crew neck jumper black")
        self.assertEqual(added.gaps, ["price", "fabric", "sizes"])
        self.assertNotEqual(self.view().chosen.id, added.id, "an item without a price is never picked")

    def test_a_link_seen_during_a_refresh_brings_its_price_and_colour(self):
        link = COS + "/de-de/x/product/slim-fine-merino-crew-neck-jumper-grey-4100000901"
        other = next(s for s in db.list_slots() if s["category"] == "cardigan")
        self.client.post(f"/slot/{other['id']}/import", data={"urls": link})
        copied = next(c for c in selection.build().get(other["id"]).cands if c.id == "cos-4100000901")
        self.assertEqual((copied.price, copied.data["colour"], copied.manual), (69.0, "Grey", True))

    def view(self):
        return selection.build().get(self.sid)

    def test_typed_in_details_complete_an_item_and_change_its_score(self):
        before = self.cand("cos-4100000901")
        self.assertEqual(before.score.fabric_source, "name")
        self.assertFalse(before.size.known)
        self.client.post(f"/slot/{self.sid}/details", data={
            "candidate": "cos-4100000901", "composition": "100% Merinowolle", "sizes": "S, L, XL", "price": ""})
        after = self.cand("cos-4100000901")
        self.assertEqual(after.score.fabric_source, "listed")
        self.assertGreater(after.score.total, before.score.total)
        self.assertTrue(after.size.known)
        self.assertFalse(after.available, "M was not among the sizes typed in")
        self.assertEqual(after.gaps, [])

        self.client.post(f"/slot/{self.sid}/details", data={"candidate": "cos-4100000901", "clear": "1"})
        self.assertEqual(self.cand("cos-4100000901").score.fabric_source, "name")

    def said(self, response, inside: str = "main") -> list[str]:
        """The messages on the page a form's answer leads to (followed), in order: in <main>, or in one section."""
        page = response.get_data(as_text=True)
        where = re.search(r'<section class="card add" id="add">(.*?)</section>', page, re.S) if inside == "add" else None
        part = where.group(1) if where else page.split("<main>", 1)[-1]
        return [html.unescape(m) for m in re.findall(r'<p class="flash[^"]*" role="status">(.*?)</p>', part, re.S)]

    def test_nonsense_details_are_reported_not_saved(self):
        def details(**typed):
            return self.client.post(f"/slot/{self.sid}/details", follow_redirects=True,
                                    data={"candidate": "cos-4100000901", **typed})

        # Nothing could be read: each problem is named, and nothing is said to be saved.
        self.assertEqual(self.said(details(composition="very nice wool", price="cheap")), [
            "Couldn't read the fabric “very nice wool”: write it as the label does, like “80% Wolle, 20% Polyamid”.",
            "“cheap” isn't a price."])
        self.assertEqual(self.cand("cos-4100000901").score.fabric_source, "name")
        self.assertFalse(self.cand("cos-4100000901").size.known)
        # Part of it could: what was saved is named, and only that.
        self.assertEqual(self.said(details(sizes="S, L", price="cheap")), ["“cheap” isn't a price.", "Saved the sizes."])
        self.assertTrue(self.cand("cos-4100000901").size.known)
        self.assertEqual(self.said(details(composition="100% Wolle", sizes="M", price="cheap")),
                         ["“cheap” isn't a price.", "Saved the fabric and sizes."])
        self.assertEqual(self.said(details(price="59")), ["Details saved."])
        self.assertEqual(self.said(details()), ["Nothing to save yet: type the fabric, the sizes in stock or the price."])
        self.assertEqual(self.said(details(clear="1")), ["Details cleared."])
        r = self.client.post(f"/slot/{self.sid}/details", data={"candidate": "nope"})
        self.assertEqual(r.status_code, 404)

    def test_what_pasted_links_came_to_is_said_in_their_own_section(self):
        # The page comes back to the "Add a product by link" section (#add), far down the page: the messages are
        # there, not at the top of the page where nobody looking at the section would see them.
        link = COS + "/de-de/men/knitwear/product/some-jumper-black-4100000902"
        r = self.client.post(f"/slot/{self.sid}/import", data={"urls": f"https://shop.example.org/jumper\n{link}"})
        self.assertTrue(r.headers["Location"].endswith("#add"), r.headers["Location"])
        page = self.client.get(r.headers["Location"])
        self.assertEqual(self.said(page, inside="add"), [
            "Not added: “https://shop.example.org/jumper” is not a COS, Weekday or Zara link.",
            "Added “Some jumper black”: only the link could be read — add the price, fabric and sizes under "
            "“Add details”."])
        before = page.get_data(as_text=True).split('id="add"')[0]
        self.assertNotIn('class="flash', before, "a message about the links at the top of the page")
        self.assertIn('<p class="flash bad" role="status">Not added: ', page.get_data(as_text=True))
        nothing = self.client.post(f"/slot/{self.sid}/import", data={"urls": " "}, follow_redirects=True)
        self.assertEqual(self.said(nothing, inside="add"), ["Paste at least one product link."])
        long = "https://shop.example.org/" + "x" * 200
        cut = self.client.post(f"/slot/{self.sid}/import", data={"urls": long}, follow_redirects=True)
        self.assertEqual(self.said(cut, inside="add"), [f"Not added: “{long[:79]}…” is not a COS, Weekday or Zara link."])

    def test_a_zara_link_gives_the_products_name_without_its_article_number(self):
        for link, name in (("https://www.zara.com/de/de/stiefel-aus-leder-p12345678.html", "Stiefel aus leder"),
                           ("https://www.zara.com/de/de/stiefel-aus-leder-p12345678.html?v1=99", "Stiefel aus leder"),
                           (COS + "/de-de/x/product/brushed-merino-jumper-black-4100000902", "Brushed merino jumper black")):
            [(_, cand, _)] = manual.from_urls([link], self.slot, allow_fetch=False)
            assert cand is not None
            self.assertEqual(cand["name"], name, link)

    def test_only_your_own_items_can_be_removed(self):
        r = self.client.post(f"/slot/{self.sid}/remove", data={"candidate": "cos-4100000901"})
        self.assertEqual(r.status_code, 404, "collected items are not removable")
        link = COS + "/de-de/x/product/some-jumper-black-4100000902"
        self.client.post(f"/slot/{self.sid}/import", data={"urls": link})
        self.client.post(f"/slot/{self.sid}/details", data={"candidate": "cos-4100000902", "price": "59,90"})
        self.assertEqual(self.cand("cos-4100000902").price, 59.9)
        self.client.post(f"/slot/{self.sid}/pick", data={"candidate": "cos-4100000902"})
        self.client.post(f"/slot/{self.sid}/remove", data={"candidate": "cos-4100000902"})
        view = self.view()
        self.assertNotIn("cos-4100000902", [c.id for c in view.cands])
        self.assertEqual(view.state, "auto", "the lock on a removed item is released")

    def test_recolouring_a_slot_drops_what_was_collected_for_the_old_colour(self):
        link = COS + "/de-de/x/product/some-jumper-black-4100000902"
        self.client.post(f"/slot/{self.sid}/import", data={"urls": link})
        r = self.client.post(f"/slots/{self.sid}/save", follow_redirects=True, data={
            "name": "Burgundy jumper", "category": "knit", "colour": "burgundy", "qty": "1", "keywords": ""})
        self.assertEqual([c.id for c in self.view().cands], ["cos-4100000902"],
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
        self.assertIn("Open at COS", html)
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
