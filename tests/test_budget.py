"""Budgets from 150 € (the owner, 18 Nov 2026: "800 for one website is actually insane").

What this round promises:
  * the usual price ranges start where budget stores sell (config/scoring.toml): a 7.99 € cotton tee reaches the
    minimum quality of 70, and cheap is still not always good enough;
  * the demo has a budget store's basics (OTTO, mock.py), every one of them read in the customer's own sizes;
  * "Best for budget" gives a piece with nothing rated 70 or more its cheapest option in his size, and says so: the
    best-rated one, which a price level takes, could break the budget by itself;
  * on the demo, the plan each budget proposes (capsule.py, config/budget.toml; its rule is tested in test_rules.py)
    fits that budget at "Best for budget", with nothing rated under 70.
"""
import html
import unittest

from wardrobe import capsule, catalog, db, mock, programmes, scoring, selection, shared, sizes
from wardrobe import profile as profile_mod
from wardrobe.garments import GARMENTS

from .test_app import AppCase
from .test_production import ProductionCase
from .test_production import words as page_words
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


EU = ["41", "42", "43", "44", "45"]


def derby(store: str, number: int, price: float, in_stock: list[str], sizes_all: list[str] | None = None) -> dict:
    """Dark brown derby shoes of polyurethane: rated far under 70 at any store."""
    return {"id": f"{store}-{number}", "store": store, "name": "Derby-Schuhe", "price": price, "currency": "EUR",
            "colour": "Dunkelbraun", "colour_hex": None, "composition_text": "100 % Polyurethan", "fit": "regular",
            "description": "", "sizes_all": EU if sizes_all is None else sizes_all, "sizes_in_stock": in_stock,
            "url": f"https://www.example.com/{store}/{number}", "image_url": "", "source": "collected",
            "category": "shoes"}


class NothingGoodEnough(AppCase):
    """A piece whose every option is rated under 70: at a price level its best-rated option, as before; at "Best for
    budget", fitted to his budget, its cheapest option in his size."""
    PIECE = "dark-brown-derby-shoes"

    def setUp(self):
        super().setUp()
        db.set_setting("sizes_confirmed", True)          # "in your size", not "in the example size"
        options = [derby("weekday", 1, 90, ["43"]),       # rated 35: the best-rated in his size
                   derby("otto", 2, 39.99, ["43"]),       # rated 34: the cheapest in his size
                   derby("cos", 3, 25, [], sizes_all=[]),  # sizes not checked: passed over for those in his size
                   derby("weekday", 4, 20, ["44"])]        # sold out in his size: never picked automatically

        def only_these(cat: dict) -> None:
            cat["candidates"] = [c for c in cat["candidates"] if c["slot_id"] != self.PIECE] + [
                {**option, "slot_id": self.PIECE} for option in options]
        catalog.update(only_these)

    def piece_page(self) -> str:
        return html.unescape(page_words(self.client.get(f"/slot/{self.PIECE}").data.decode()))

    def test_best_for_budget_takes_the_cheapest_option_in_his_size_and_says_so(self):
        self.set_mode("cheapest")
        w = selection.build()
        view = w.get(self.PIECE)
        self.assertEqual((view.chosen.id, view.note),
                         ("weekday-1", "Nothing reaches 70 — this is the best in your size"))
        self.assertIn("Picked for you: the best-rated option in your size.", self.piece_page())
        # A budget the cheapest level's total does not fit, with the best-rated shoes counted in it, but the plan
        # on its cheapest options does: so "Best for budget" fits it only with the cheapest shoes.
        budget = round(w.levels["cheapest"] - 20)
        profile_mod.save({**profile_mod.load(), "example": False, "budget": budget})
        profile_mod.answer("budget")
        self.set_mode("budget")
        w = selection.build()
        view = w.get(self.PIECE)
        self.assertEqual(view.chosen.id, "otto-2")
        self.assertTrue(view.warn and view.cheapest_instead)
        self.assertEqual(view.note, "Nothing reaches 70 — this is the cheapest in your size")
        self.assertEqual(w.note, "", "it fits the budget")
        self.assertLessEqual(w.total, budget)
        said = self.piece_page()
        self.assertIn("Picked for you: the cheapest option in your size. Choose another below to swap it in. "
                      "Nothing reaches your minimum quality of 70.", said)
        self.assertNotIn("best-rated", said)
        self.assertNotIn("what your budget allows", said)
        # What the price levels show for "Best for budget", seen from another level, is what it then costs.
        total = w.total
        self.set_mode("cheapest")
        self.assertEqual(selection.build().levels["budget"], total)

    def test_the_cheapest_in_his_size_is_never_one_he_cannot_buy(self):
        view = selection.build().get(self.PIECE)
        self.assertEqual(selection.cheapest_instead(view.cands).id, "otto-2", "not the sold-out one, nor the "
                                                                              "one whose sizes were not checked")
        unchecked = [c for c in view.cands if c.id == "cos-3"]
        self.assertEqual(selection.cheapest_instead(unchecked).id, "cos-3", "where none is known to be in his size")
        self.assertEqual(selection.cheapest_words(unchecked, 70),
                         "Nothing reaches 70 — this is the cheapest available")
        self.assertIsNone(selection.cheapest_instead([c for c in view.cands if c.id == "weekday-4"]))


class TheDemoFitsEachBudget(AppCase):
    """The plans of five budgets for each use, on the demo's products, the example's sizes and colours."""
    BUDGETS = (150, 300, 600, 1000, 1500)
    MARGINS: dict = {}          # what is left of each budget: read by the round's report (python -m unittest -v)

    def fitted(self, use: str, budget: int) -> selection.Wardrobe:
        answers = {**profile_mod.EXAMPLE, "example": False, "use": use, "budget": budget}
        profile_mod.save(answers)
        profile_mod.answer("budget")                     # a budget he gave: "Best for budget" fits to it
        slots, _ = capsule.propose(answers)
        db.replace_slots(slots)
        catalog.save(mock.build(slots))
        self.set_mode("budget")
        return selection.build()

    def test_best_for_budget_fits_every_budget_with_nothing_rated_under_70(self):
        for use in ("everyday", "office", "both"):
            for budget in self.BUDGETS:
                with self.subTest(use=use, budget=budget):
                    w = self.fitted(use, budget)
                    self.assertEqual(w.note, "", "it fits")
                    self.assertLessEqual(w.total, budget)
                    for view in w.slots:
                        self.assertIsNotNone(view.chosen, view.slot["name"])
                        self.assertGreaterEqual(view.chosen.score.total, 70, view.slot["name"])
                        self.assertFalse(view.warn, f"{view.slot['name']}: {view.note}")
                    self.MARGINS[use, budget] = (sum(view.planned for view in w.slots), w.total)

    def test_each_usual_price_buys_a_demo_product_rated_70_or_more(self):
        # The plan counts each piece at its usual price at a budget store (config/budget.toml). The demo's budget
        # store sells one rated 70 or more at that price or less, for every garment of the lists.
        usual = capsule.budget_rules()["usual_price"]
        slots = [{"id": f"piece-{category}", "category": category, "colour": "navy"} for category in usual]
        demo = mock.build(slots)
        for category, price in usual.items():
            with self.subTest(category):
                good = [c["price"] for c in demo["candidates"] if c["slot_id"] == f"piece-{category}"
                        and c["store"] == "otto" and scoring.score(c, category).total >= 70]
                self.assertLessEqual(min(good), price)
