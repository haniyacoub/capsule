"""Budgets from 150 € (the owner, 18 Nov 2026: "800 for one website is actually insane").

What this round promises:
  * the usual price ranges start where budget stores sell (config/scoring.toml): a 7.99 € cotton tee reaches the
    minimum quality of 70, and cheap is still not always good enough;
  * the demo has a budget store's basics (OTTO, mock.py), every one of them read in the customer's own sizes;
"""
import unittest

from wardrobe import mock, programmes, scoring, shared, sizes
from wardrobe.garments import GARMENTS

from .test_production import ProductionCase
from .test_store_picker import empty_rows, rows


def rated(store: str, price: float, label: str, category: str, rules: dict | None = None) -> int:
    """The quality a product of this store, price and fabric label gets, 0-100."""
    return scoring.score({"store": store, "price": price, "composition_text": label}, category,
                         rules or scoring.load_rules()).total


ME = {"top_size": "M", "waist": 32, "length": 32, "shoe": "43"}       # the example's sizes


class UsualPrices(unittest.TestCase):
    def test_a_cotton_tee_for_799_euros_reaches_the_minimum_quality(self):
        # Before the usual ranges moved down it was rated 69: "far below the usual 12 €–40 € for T-shirts".
        self.assertGreaterEqual(rated("otto", 7.99, "100 % Baumwolle", "tee"), 70)
        said = scoring.price_part(7.99, "tee", scoring.load_rules())[1][0].replace(" ", " ")
        self.assertEqual(said, "7.99 € is in the usual range for T-shirts (7 €–40 €)")

    def test_cheap_is_not_always_good_enough(self):
        self.assertLess(rated("otto", 39.99, "100 % Polyurethan", "shoes"), 50, "derby shoes of polyurethane")
        # Trousers of polyester and viscose never reach 70: not with a store rated 100, nor at a usual price.
        best = {**scoring.load_rules(), "brand": {"anyone": {"default": 100}}}
        self.assertLess(rated("anyone", 40, "64 % Polyester, 34 % Viskose, 2 % Elasthan", "trousers", best), 70)

    def test_only_the_lower_ends_moved(self):
        # Where a price counts as steep stayed where it was, so dear products are rated as before.
        bands = scoring.load_rules()["price"]["bands"]
        self.assertEqual({key: (band["fair"][1], band["steep_above"]) for key, band in bands.items()}, {
            "tee": (40, 60), "longsleeve": (50, 75), "polo": (90, 130), "shirt": (95, 140), "knit": (140, 220),
            "cardigan": (150, 240), "overshirt": (150, 230), "blazer": (260, 400), "coat": (380, 550),
            "jacket": (200, 320), "trousers": (150, 230), "chinos": (100, 150), "jeans": (120, 180),
            "sneakers": (180, 280), "shoes": (230, 350), "boots": (260, 380)})


class TheDemosBudgetStore(unittest.TestCase):
    def test_its_stores_are_all_offered_so_none_of_its_products_is_dropped(self):
        slots = [{"id": f"piece-{category}", "category": category, "colour": "navy"} for category in GARMENTS]
        demo = mock.build(slots)
        self.assertEqual({c["store"] for c in demo["candidates"]}, {"cos", "weekday", "otto"})
        self.assertLessEqual(set(mock.STORE_HOME), set(programmes.offered()))
        self.assertEqual(programmes.only_offered(demo)["candidates"], demo["candidates"])
        for category in GARMENTS:       # OTTO has every garment, and one at least that reaches the minimum quality
            otto = [c for c in demo["candidates"] if c["store"] == "otto" and c["slot_id"] == f"piece-{category}"]
            self.assertTrue(otto, category)
            self.assertTrue(any(scoring.score(c, category).total >= 70 for c in otto), category)

    def test_a_store_without_a_size_table_prints_sizes_that_read_without_one(self):
        # Waist/length on trousers, chinos and jeans, letters on tops, EU sizes on shoes: OTTO's EU numbers on trousers
        # would have read as "Not made in your size" for everyone.
        charts = sizes.load_charts()
        self.assertNotIn("otto", charts)
        for category, garment in GARMENTS.items():
            run = mock.size_run("otto", category)
            with self.subTest(category):
                if garment.size_group == "bottoms":
                    self.assertIn("32/32", run)
                elif garment.size_group == "tops":
                    self.assertEqual(run, ["XS", "S", "M", "L", "XL", "XXL"])
                else:
                    self.assertIn("43", run)
                self.assertTrue(any(sizes.label_fits(label, ME, "otto", category, charts) for label in run))
        # COS and Weekday print as before: their tables translate their EU numbers.
        self.assertIn("48", mock.size_run("cos", "trousers"))
        self.assertIn("48", mock.size_run("cos", "coat"))
        self.assertIn("48", mock.size_run("weekday", "chinos"))
        self.assertIn("32/32", mock.size_run("weekday", "jeans"))


class TheStoresTab(ProductionCase):
    def test_while_no_list_is_published_the_demos_stores_are_the_ones_with_products(self):
        # Every customer has the demo's products until a list is published, OTTO's among them: OTTO is not shown
        # under "No products yet" beside OTTO products in his wardrobe.
        self.assertFalse(shared.published())
        self.assertEqual(shared.stocked(), ["cos", "weekday", "otto"])
        page = self.member("ada@example.com").get("/profile").get_data(as_text=True)
        self.assertEqual([key for key, _, _ in rows(page)], ["cos", "weekday", "otto"])
        self.assertNotIn("otto", [key for key, _, _ in empty_rows(page)])
