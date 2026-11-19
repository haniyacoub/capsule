"""Budgets from 150 € (the owner, 18 Nov 2026: "800 for one website is actually insane").

What this round promises:
  * the usual price ranges start where budget stores sell (config/scoring.toml): a 7.99 € cotton tee reaches the
    minimum quality of 70, and cheap is still not always good enough;
  * the demo has a budget store's basics (OTTO, mock.py), every one of them read in the customer's own sizes;
  * "Best for budget" gives a piece with nothing rated 70 or more its cheapest option in his size, and says so: the
    best-rated one, which a price level takes, could break the budget by itself;
  * on the demo, the plan each budget proposes (capsule.py, config/budget.toml; its rule is tested in test_rules.py)
    fits that budget at "Best for budget", with nothing rated under 70;
  * a deploy changes no customer's plan: only his own plan-shaping Profile save or "Start over" makes a new one, as
    before, and never of a plan he edited by hand.
"""
import html
import re
import sqlite3
import unittest
from contextlib import closing
from pathlib import Path
from unittest import mock as patch

from wardrobe import capsule, catalog, config, db, guests, mock, onboarding, outfits, paths, programmes, scoring
from wardrobe import selection, shared, sizes
from wardrobe import profile as profile_mod
from wardrobe.app import create_app
from wardrobe.garments import GARMENTS

from . import having
from .test_app import AppCase
from .test_production import ProductionCase
from .test_production import words as page_words
from .test_store_picker import FORM, empty_rows, rows


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


# The example's plan as it was made until 18 Nov 2026 (the lists before config/budget.toml, the example's colours,
# everyday and office): (id, name, garment, colour, keywords, quantity). Every account of today has a plan like it.
PLAN_BEFORE = [
    ("charcoal-wool-coat", "Charcoal wool coat", "coat", "charcoal", "wool", 1),
    ("navy-light-jacket", "Navy light jacket", "jacket", "navy", "lightweight", 1),
    ("navy-wool-blazer", "Navy wool blazer", "blazer", "navy", "wool", 1),
    ("olive-overshirt", "Olive overshirt", "overshirt", "olive", "", 1),
    ("grey-merino-jumper", "Grey merino jumper", "knit", "grey", "merino crew-neck", 1),
    ("navy-merino-jumper", "Navy merino jumper", "knit", "navy", "merino crew-neck", 1),
    ("ecru-cardigan", "Ecru cardigan", "cardigan", "ecru", "wool", 1),
    ("white-oxford-shirt", "White oxford shirt", "shirt", "white", "oxford", 1),
    ("light-blue-oxford-shirt", "Light blue oxford shirt", "shirt", "light-blue", "oxford", 1),
    ("white-tee", "White tee", "tee", "white", "heavyweight", 2),
    ("navy-tee", "Navy tee", "tee", "navy", "heavyweight", 1),
    ("grey-tee", "Grey tee", "tee", "grey", "heavyweight", 1),
    ("grey-wool-trousers", "Grey wool trousers", "trousers", "grey", "wool", 1),
    ("charcoal-tailored-trousers", "Charcoal tailored trousers", "trousers", "charcoal", "tailored", 1),
    ("stone-chinos", "Stone chinos", "chinos", "stone", "", 1),
    ("indigo-jeans", "Indigo jeans", "jeans", "indigo", "straight", 1),
    ("white-leather-sneakers", "White leather sneakers", "sneakers", "white", "leather", 1),
    ("dark-brown-derby-shoes", "Dark brown derby shoes", "shoes", "dark-brown", "leather derby", 1),
]


class ExistingCustomers(ProductionCase):
    """Customers with today's plans, through the deploy of this round: a restart that brings the database to version
    11, their pages, and a Profile save of sizes and budget."""

    def from_before(self, email: str, edited: bool):
        """A customer whose plan is the one every account has today, with a product locked and a piece he owns, and
        his own answers saved once (an edited plan has a piece he renamed)."""
        client = self.member(email)
        self.assertEqual(self.post(client, "/profile", **FORM).status_code, 302)       # his answers, 1,500 €
        with db.as_user(self.user_id(email)):
            db.replace_slots([{"id": i, "name": name, "category": garment, "colour": colour, "keywords": keywords,
                               "qty": qty, "owned": False} for i, name, garment, colour, keywords, qty in PLAN_BEFORE])
            catalog.save(mock.build(db.list_slots()))
            db.update_slot("navy-merino-jumper", owned=True)
            view = selection.build().get("stone-chinos")
            db.update_slot("stone-chinos", locked=True, pick=view.chosen.id)
            if edited:
                db.update_slot("charcoal-wool-coat", name="My charcoal coat")
            db.set_setting("plan_edited", edited)
        return client

    def plan(self, email: str) -> list[dict]:
        with db.as_user(self.user_id(email)):
            return db.list_slots()

    def test_a_deploy_changes_no_plan_and_a_plan_edited_by_hand_is_never_rebuilt(self):
        old = self.from_before("old@example.com", edited=False)
        edited = self.from_before("edited@example.com", edited=True)
        before = {email: self.plan(email) for email in ("old@example.com", "edited@example.com")}
        with closing(sqlite3.connect(paths.DB_PATH)) as con:      # the database as the live servers have it
            con.execute("PRAGMA user_version = 10")
            con.commit()
        self.app = create_app()                                    # the deploy: a restart with this round's code
        for client in (old, edited):
            for url in ("/", "/outfits", "/profile", "/slots", "/list"):
                self.assertEqual(client.get(url).status_code, 200, url)
        self.assertEqual({email: self.plan(email) for email in before}, before, "no plan changed")
        # His sizes alone leave the plan as it is.
        for client in (old, edited):
            saved = self.post(client, "/profile", **{**FORM, "top_size": "L"})
            self.assertTrue(saved.headers["Location"].endswith("/profile"))
        self.assertEqual({email: self.plan(email) for email in before}, before, "no plan changed")
        # A new budget plans the wardrobe (since round 1b, as new colours do): a plan edited by hand stays as it is,
        # and says so in one line, with the button that plans it from his profile ...
        stays = self.post(edited, "/profile", **{**FORM, "budget": "300", "top_size": "L"})
        self.assertTrue(stays.headers["Location"].endswith("/profile"))
        self.assertIn('<div class="flash plan-kept" role="status"><span>Profile saved. Your plan stays as you edited '
                      'it.</span>', edited.get("/profile").get_data(as_text=True))
        self.assertEqual(self.plan("edited@example.com"), before["edited@example.com"])
        # ... and one that was not is planned afresh for it: its ids each once.
        rebuilt = self.post(old, "/profile", **{**FORM, "budget": "300", "top_size": "L"})
        self.assertEqual(rebuilt.headers["Location"], "/outfits")
        plan = self.plan("old@example.com")
        self.assertEqual(len({s["id"] for s in plan}), len(plan))
        self.assertEqual(sum(s["qty"] for s in plan), 9, "the plan of a 300 € budget")
        self.assertFalse([s["name"] for s in plan if any(w in s["name"].lower() for w in ("merino", "wool", "leather"))
                          and not s["owned"]])
        self.assertTrue(any(s["owned"] and (s["category"], s["colour"]) == ("knit", "navy") for s in plan),
                        "the piece he owns stays his")


# ── Round 1b: the five budget choices, budget as plan-shaping, the level at sign-up, the example's own budget ───────

def answers_form(**changes) -> dict:
    """Profile's form with the example's answers, as a browser sends it (the budget's choice and field in `changes`)."""
    form = {"top_size": "M", "waist": "32", "length": "32", "shoe": "43", "height_cm": "180", "weight_kg": "78",
            "liked": "navy, grey, white, olive", "refused": "", "use": "both", "shoes": "on", "outerwear": "on",
            "owned": ""}
    return {key: value for key, value in {**form, **changes}.items() if value is not None}


def choices(page: str) -> list[tuple[str, bool, str]]:
    """The budget's choices on a page: (value, chosen, what its label says), in order."""
    pick = re.search(r'<fieldset class="budget-pick".*?</fieldset>', page, re.S).group(0)
    rows = re.findall(r'<label class="check budget-choice"><input type="radio" name="budget_choice" value="([^"]+)"'
                      r'([^>]*)>(.*?)</label>', pick, re.S)
    return [(value, "checked" in rest, html.unescape(page_words(label))) for value, rest, label in rows]


class TheFiveChoices(AppCase):
    """Profile's Budget tab and the welcome's step 2: Starter 150 € · Basic 300 € · Solid 600 € · Full 1,000 €+ · Other
    amount, each preset with about how many pieces it plans for his kinds (capsule's own rule), and where a kind waits
    at it, the budget that kind joins at."""

    def test_each_preset_says_what_it_plans_for_his_kinds(self):
        page = self.client.get("/profile").get_data(as_text=True)
        self.assertEqual(capsule.presets(), {"Starter": 150, "Basic": 300, "Solid": 600, "Full": 1000})
        self.assertEqual(choices(page), [
            ("150", False, "Starter 150 € about 7 pieces Office joins at about 206 €"),
            ("300", False, "Basic 300 € about 9 pieces"),
            ("600", False, "Solid 600 € about 12 pieces"),
            ("1000", False, "Full 1,000 €+ about 17 pieces"),
            ("other", False, "Other amount")])
        self.assertIn("About how many pieces each plans for everyday and the office.", html.unescape(page_words(page)))
        # The counts are the rule's own (capsule.pieces_at), and so is the joining point: a whole euro less, and the
        # office waits.
        example = profile_mod.load()
        for amount, pieces in ((150, 7), (300, 9), (600, 12), (1000, 17)):
            self.assertEqual(capsule.pieces_at(example, amount), pieces)
        self.assertEqual(capsule.joins_at(example), {"office": 206})
        self.assertEqual(capsule.kinds_in({**example, "budget": 206}), ["everyday", "office"])
        self.assertEqual(capsule.kinds_in({**example, "budget": 205}), ["everyday"])

    def test_the_counts_follow_what_he_dresses_for_and_his_ticks(self):
        profile_mod.save({**profile_mod.load(), "use": "office"})
        self.assertEqual([label for _, _, label in choices(self.client.get("/profile").get_data(as_text=True))][:4],
                         ["Starter 150 € about 4 pieces", "Basic 300 € about 6 pieces", "Solid 600 € about 9 pieces",
                          "Full 1,000 €+ about 15 pieces"])      # one kind: none waits
        profile_mod.save({**profile_mod.load(), "use": "both", "shoes": False})
        starter = choices(self.client.get("/profile").get_data(as_text=True))[0][2]
        self.assertTrue(starter.startswith("Starter 150 € about "), starter)
        self.assertNotIn("joins", starter, "without shoes the office's first pieces fit at 103 €")
        self.assertEqual(capsule.joins_at(profile_mod.load()), {"office": 103})

    def test_radio_buttons_with_labels_and_the_field_other_amount_opens(self):
        page = self.client.get("/profile").get_data(as_text=True)
        pick = re.search(r'<fieldset class="budget-pick" aria-describedby="budget-for">\s*<legend>For the whole '
                         r'wardrobe</legend>.*?</fieldset>', page, re.S).group(0)
        self.assertEqual(pick.count('type="radio" name="budget_choice"'), 5, "each a native radio button in its label")
        # The field for an amount of his own keeps its name and id (the budget bar's link, older forms), under
        # "Other amount", which opens it (app.css hides it until then, where the browser can tell; app.js 13e
        # chooses "Other amount" when something is typed in it).
        self.assertRegex(pick, r'(?s)value="other"[^>]*data-budget-other>.*?<div class="budget-own">\s*<label class="field">'
                               r'<span>Your amount <small>\(EUR\)</small></span>\s*<input type="number" id="budget" '
                               r'name="budget"')
        css = (Path(paths.ROOT) / "wardrobe" / "static" / "app.css").read_text(encoding="utf-8")
        self.assertIn(".budget-pick:not(:has(input[data-budget-other]:checked)) .budget-own { display: none; }", css)
        self.assertIn(".budget-choice { min-height: 48px;", css, "a row to tap, 48px tall")
        script = (Path(paths.ROOT) / "wardrobe" / "static" / "app.js").read_text(encoding="utf-8")
        self.assertIn("field.addEventListener('input', () => {", script)

    def test_a_preset_beats_the_field_and_other_amount_reads_it(self):
        saved = self.client.post("/profile", data=answers_form(budget_choice="600", budget="450"))
        self.assertEqual((profile_mod.load()["budget"], profile_mod.budget_known()), (600, True))
        self.assertEqual(saved.headers["Location"], "/outfits", "a new budget plans the wardrobe: shown on the model")
        self.assertEqual(capsule.count(db.list_slots()), 12)
        page = self.client.get("/profile").get_data(as_text=True)
        self.assertEqual([value for value, on, _ in choices(page) if on], ["600"])
        self.client.post("/profile", data=answers_form(budget_choice="other", budget="450"))
        self.assertEqual(profile_mod.load()["budget"], 450)
        page = self.client.get("/profile").get_data(as_text=True)
        self.assertEqual([value for value, on, _ in choices(page) if on], ["other"])
        self.assertIn('id="budget" name="budget" min="0" inputmode="numeric" value="450"', page)
        self.assertIn(f"At 450 €: about {capsule.pieces_at(profile_mod.load(), 450)} pieces.",
                      html.unescape(page_words(page)))
        # "Other amount" with nothing in its field: no budget (what the line under the choices says to do).
        self.client.post("/profile", data=answers_form(budget_choice="other", budget=""))
        self.assertFalse(profile_mod.budget_known())
        self.assertEqual([value for value, on, _ in choices(self.client.get("/profile").get_data(as_text=True)) if on],
                         [], "nothing chosen while he has no budget")
        # A form without the choices (an older page) is read as before: its field.
        self.client.post("/profile", data=answers_form(budget="350"))
        self.assertEqual((profile_mod.load()["budget"], profile_mod.budget_known()), (350, True))

    def test_the_welcome_offers_the_same_five_and_a_choice_plans_the_wardrobe(self):
        page = self.client.get("/welcome/2").get_data(as_text=True)
        self.assertEqual([label for _, _, label in choices(page)], [
            "Starter 150 € about 7 pieces Office joins at about 206 €", "Basic 300 € about 9 pieces",
            "Solid 600 € about 12 pieces", "Full 1,000 €+ about 17 pieces", "Other amount"])
        said = html.unescape(page_words(page))
        self.assertIn("About how many pieces each plans for everyday and the office: you choose what you dress for in "
                      "the next step.", said)
        self.assertIn("It sizes the wardrobe we plan for you.", said)
        self.assertLess(page.index('class="budget-pick"'), page.index('class="pick-colours"'), "above the colours")
        self.client.post("/welcome/2", data={"budget_choice": "150", "budget": ""})
        self.assertEqual((profile_mod.load()["budget"], profile_mod.answered()), (150, {"budget"}))
        self.assertEqual(capsule.count(db.list_slots()), 7, "the plan of 150 €")
        self.client.post("/welcome/2", data={"budget_choice": "other", "budget": "1500"})
        self.assertEqual(capsule.count(db.list_slots()), 24, "the plan of 1,500 €")
        # Once he has said what he dresses for, the counts are for that, and the line says so plainly.
        self.client.post("/welcome/3", data={"use": "everyday"})
        page = self.client.get("/welcome/2").get_data(as_text=True)
        self.assertIn("About how many pieces each plans for everyday wear.", html.unescape(page_words(page)))
        self.assertEqual([value for value, on, _ in choices(page) if on], ["other"])


class BudgetShapesThePlan(AppCase):
    """A budget is plan-shaping: a save that changes it plans the wardrobe afresh (app.profile_page, the welcome), but a
    plan edited by hand is never rebuilt without asking, and Profile says so in one line, with "Start over"."""

    def test_an_edited_plan_stays_and_the_line_offers_to_start_over(self):
        self.client.post("/slots/add", data={"name": "", "category": "overshirt", "colour": "rust", "qty": "1"})
        before = db.list_slots()
        saved = self.client.post("/profile", data=answers_form(budget_choice="1000", budget="", tab="budget"))
        self.assertTrue(saved.headers["Location"].endswith("/profile#budget"), "it stays on the tab it was sent from")
        self.assertEqual(db.list_slots(), before, "the plan is exactly as he edited it")
        self.assertEqual(profile_mod.load()["budget"], 1000, "the budget itself is saved")
        page = self.client.get("/profile").get_data(as_text=True)
        line = re.search(r'<div class="flash plan-kept" role="status">.*?</div>', page, re.S).group(0)
        self.assertEqual(html.unescape(page_words(line)),
                         "Profile saved. Your plan stays as you edited it. Start over from my profile")
        self.assertIn('action="/slots/repropose" data-confirm="Start over from your profile?', line)
        self.assertEqual(len(re.findall(r'<(?:p|div) class="flash[^"]*" role="status">', page)), 1, "one line")
        # The button plans it from the profile: his 1,000 €.
        self.client.post("/slots/repropose")
        self.assertEqual(capsule.count(db.list_slots()), 17)

    def test_the_welcome_never_rebuilds_an_edited_plan(self):
        self.client.post("/slots/add", data={"name": "", "category": "overshirt", "colour": "rust", "qty": "1"})
        before = db.list_slots()
        self.client.post("/welcome/2", data={"budget_choice": "600", "budget": ""})
        self.assertEqual(db.list_slots(), before)


class PlanPage(AppCase):
    """Reading the plan page: a line of it, its colours; and saving Profile with a budget chosen."""

    def line(self, of: str = "plan-for") -> str:
        page = self.client.get("/slots").get_data(as_text=True)
        found = re.search(rf'<p class="muted small" id="{of}">(.*?)</p>', page, re.S)
        return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", found.group(1)))).strip() if found else ""

    def chips(self) -> list[str]:
        page = self.client.get("/slots").get_data(as_text=True)
        return [" ".join(html.unescape(re.sub(r"<[^>]+>", " ", chip)).split())
                for chip in re.findall(r'<span class="swatch-chip">(.*?)</span>', page, re.S)]

    def save(self, amount: str) -> None:
        self.client.post("/profile", data=answers_form(budget_choice=amount, budget=""))


class ThePlanPageSays(PlanPage):
    """What the plan was made for, from the kinds the budget lets in, the budget and the count."""

    def test_planned_for_the_kinds_the_budget_and_the_count(self):
        self.save("300")
        self.assertEqual(self.line(), "Planned for everyday and the office, for 300 €: 9 pieces.")
        self.save("150")        # "both", but at 150 € only everyday's pieces fit: said, and when the office joins
        self.assertEqual(self.line(), "Planned for everyday wear, for 150 €: 7 pieces. Office joins at about 206 €.")
        self.client.post("/profile", data=answers_form(budget_choice="600", budget="", use="office"))
        self.assertEqual(self.line(), "Planned for the office, for 600 €: 9 pieces.")

    def test_a_budget_he_has_not_given_is_said_to_be_so(self):
        self.assertEqual(self.line(), "Planned for everyday and the office, for 300 € until you set your budget: "
                                      "9 pieces.")
        page = self.client.get("/slots").get_data(as_text=True)
        self.assertIn('until you <a href="/profile#budget">set your budget</a>', page)

    def test_a_plan_that_is_not_what_his_answers_plan_says_what_they_would(self):
        self.save("300")
        self.client.post("/slots/add", data={"name": "", "category": "overshirt", "colour": "rust", "qty": "1"})
        self.assertEqual(self.line(), "From your profile as it is now (everyday and the office, 300 €), your plan "
                                      "would have 9 pieces.")
        # An account's plan from before the budget sized plans (19 pieces, 1,500 €): not called planned for it.
        db.replace_slots([{"id": i, "name": name, "category": garment, "colour": colour, "keywords": keywords,
                           "qty": qty, "owned": False} for i, name, garment, colour, keywords, qty in PLAN_BEFORE])
        db.set_setting("plan_edited", False)
        profile_mod.save({**profile_mod.load(), "budget": 1500})
        self.assertEqual(self.line(), "From your profile as it is now (everyday and the office, 1,500 €), your plan "
                                      "would have 24 pieces.")

    def test_what_start_over_would_keep_is_counted_as_start_over_then_says(self):
        # Edited by hand, the plan stays as it is when the budget changes; the page says what his answers would plan,
        # and apart from that the pieces of his wardrobe "Start over" keeps (app.his_pieces): together, as many as
        # "Start over" then says. A piece he only marked as owned is not among them: "Start over" loses that mark, as
        # its question says, and the piece leaves a plan that has no place for it.
        self.save("600")
        db.set_setting("kept_pieces", ["navy-light-jacket"])       # in his wardrobe; the 300 € plan has no jacket
        self.client.post("/slot/stone-chinos/own")                  # owned; the 300 € plan has no chinos either
        self.client.post("/slots/add", data={"name": "", "category": "overshirt", "colour": "rust", "qty": "1"})
        self.save("300")
        self.assertIn("navy-light-jacket", {s["id"] for s in db.list_slots()}, "the edited plan stays as it is")
        self.assertTrue(db.get_slot("stone-chinos")["owned"], "the chinos are his, marked as owned")
        self.assertEqual(self.line(), "From your profile as it is now (everyday and the office, 300 €), your plan "
                                      "would have 9 pieces. Besides them, 1 piece of your wardrobe would stay.")
        again = self.client.post("/slots/repropose")
        told = re.findall(r'<p class="flash[^"]*" role="status">(.*?)</p>',
                          self.client.get(again.headers["Location"]).get_data(as_text=True), re.S)
        self.assertEqual(told, ["Started over from your profile: your plan has 10 pieces."])
        self.assertNotIn("stone-chinos", {s["id"] for s in db.list_slots()})
        self.assertEqual(self.line(), "Planned for everyday and the office, for 300 €: 9 pieces. Besides them, 1 piece "
                                      "of your wardrobe stays from your plan before.")

    def test_pieces_of_his_wardrobe_a_new_budget_had_no_place_for_are_counted_apart(self):
        self.save("600")
        db.set_setting("kept_pieces", ["navy-light-jacket"])       # in his wardrobe; the 300 € plan has no jacket
        self.save("300")
        self.assertIn("navy-light-jacket", {s["id"] for s in db.list_slots()}, "it stays in his plan")
        self.assertEqual(self.line(), "Planned for everyday and the office, for 300 €: 9 pieces. Besides them, 1 piece "
                                      "of your wardrobe stays from your plan before.")


class ThePlanPagesColours(PlanPage):
    """The colours beside the plan are the ones its pieces are in, as many as the page counts, and what is said of
    how they go together is said only where the pieces show it (capsule.plan_colours)."""

    def counted(self) -> str:
        page = self.client.get("/slots").get_data(as_text=True)
        return re.search(r"\d+ pieces? in (\d+) colours?, planned from your profile", page_words(page)).group(1)

    def test_a_small_plan_shows_its_own_colours_and_no_accent(self):
        # The starting colours (navy, grey, white, olive): at 150 € 7 pieces in 5 colours, at 300 € and 600 € no olive
        # piece either. The palette's other colours (olive, ecru, charcoal ...) are not shown as if the plan wore them.
        self.save("150")
        self.assertEqual(self.chips(), ["Navy anchor", "Grey mid neutral", "White light", "Stone earth tone",
                                        "Indigo denim"])
        self.assertEqual(self.counted(), "5")
        self.assertEqual(self.line("plan-colours"),
                         "Trousers and shoes stay neutral so nearly every top works with every pair of trousers.")
        for amount in ("300", "600"):
            self.save(amount)
            self.assertNotIn("accent", self.line("plan-colours"), amount)
            self.assertNotIn("Olive accent", self.chips(), amount)
            self.assertEqual(str(len(self.chips())), self.counted(), amount)

    def test_the_accent_is_said_once_a_top_layer_wears_it(self):
        self.save("1000")       # the olive overshirt comes in
        self.assertIn("Olive accent", self.chips())
        self.assertEqual(str(len(self.chips())), self.counted())
        self.assertEqual(self.line("plan-colours"),
                         "Trousers and shoes stay neutral so nearly every top works with every pair of trousers; the "
                         "accent colour appears on a top layer or two.")
        # Recoloured by hand, chinos in olive: the accent is no longer only on top layers, and the trousers are no
        # longer all neutral, so neither is said. Olive is still the accent, and still shown as one.
        self.client.post("/slots/stone-chinos/save", data={"name": "Olive chinos", "category": "chinos",
                                                            "colour": "olive", "qty": "1", "keywords": ""})
        self.assertIn("Olive accent", self.chips())
        self.assertEqual(self.line("plan-colours"), "")
        self.assertNotIn('id="plan-colours"', self.client.get("/slots").get_data(as_text=True))

    def test_a_colour_he_chose_by_hand_is_shown_without_a_part(self):
        self.save("150")
        self.client.post("/slots/add", data={"name": "", "category": "tee", "colour": "rust", "qty": "1"})
        self.assertEqual(self.chips()[-1], "Rust")
        self.assertEqual(str(len(self.chips())), self.counted())

    def test_without_shoes_only_the_trousers_are_said_to_stay_neutral(self):
        self.client.post("/profile", data=answers_form(budget_choice="300", budget="", shoes=None))
        self.assertFalse({s["category"] for s in db.list_slots()} & capsule.SHOES)
        self.assertEqual(self.line("plan-colours"),
                         "Trousers stay neutral so nearly every top works with every pair of trousers.")


class TheLevelAtSignUp(ProductionCase):
    def test_a_new_account_starts_on_best_for_budget_and_one_with_no_level_stays_on_cheapest(self):
        self.member("ada@example.com")
        with db.as_user(self.user_id("ada@example.com")):
            self.assertEqual((db.get_setting("mode"), db.get_setting("levels")), ("budget", True))
            w = selection.build()
            self.assertEqual(w.mode, "budget")
            # He has not given a budget yet: the level says it needs one, and shows the cheapest good options.
            self.assertTrue(w.note.startswith("“Best for budget” needs your budget"), w.note)
            # An account with no level stored (from before this setting) is on Cheapest, as before.
            db.set_setting("mode", None)
            self.assertEqual((selection.DEFAULT_MODE, selection.build().mode), ("cheapest", "cheapest"))
            # The setup runs once: it never writes a level over one an account has, nor a first one.
            onboarding.ensure_setup()
            self.assertIsNone(db.get_setting("mode"))

    def test_the_starting_values_are_300_euros_for_everyday_and_the_office(self):
        self.assertEqual((profile_mod.EXAMPLE["budget"], profile_mod.EXAMPLE["use"]), (300, "both"))
        self.assertEqual(capsule.KINDS[profile_mod.EXAMPLE["use"]], ("everyday", "office"))


class TheExampleWardrobe(ProductionCase):
    """The visitors' example: its own budget (config/site.toml, example_budget = 600), everyday and the office, on
    Best for budget, with its budget, colours and use answered. On the demo it fits its budget."""

    def test_its_own_budget_answered_and_fitted(self):
        self.assertEqual(guests.example_budget(), 600)
        self.assertEqual(guests.EXAMPLE_LEVEL, "budget")
        with db.as_user(guests.example_id()):
            self.assertEqual(profile_mod.load(), {**profile_mod.EXAMPLE, "budget": 600})
            self.assertEqual(profile_mod.answered(), {"budget", "colours", "use"})
            self.assertTrue(profile_mod.budget_known())
            w = selection.build()
            self.assertEqual((w.mode, w.source, w.budget), ("budget", "mock", 600))
            self.assertEqual(capsule.kinds_in(profile_mod.load()), ["everyday", "office"])
            self.assertEqual(sum(view.planned for view in w.slots), 12)
            self.assertEqual(w.note, "", "it fits its budget")
            self.assertLessEqual(w.total, 600)
            for view in w.slots:
                self.assertGreaterEqual(view.chosen.score.total, 70, view.slot["name"])
            self.MARGINS["example"] = (sum(view.planned for view in w.slots), w.total,
                                       len(outfits.all_outfits(w)))

    MARGINS: dict = {}

    def test_a_new_budget_replans_it_at_the_next_start_and_a_broken_one_is_said(self):
        with db.as_user(guests.example_id()):
            self.assertEqual(capsule.count(db.list_slots()), 12)
        with patch.patch.object(guests, "example_budget", return_value=1000):
            create_app()                                    # the next start
        with db.as_user(guests.example_id()):
            self.assertEqual(capsule.count(db.list_slots()), 17, "the plan of 1,000 €")
            self.assertEqual(profile_mod.load()["budget"], 1000)
        with patch.patch.object(config, "load", return_value={"guests": True, "example_budget": "600 €"}):
            with self.assertRaises(config.ConfigError) as said:
                guests.example_budget()
        self.assertIn("example_budget must be an amount in euros", str(said.exception))
        with patch.patch.object(config, "load", return_value={"guests": True}):
            self.assertEqual(guests.example_budget(), guests.EXAMPLE_BUDGET, "none named: 600 €")
        # The file says what a change means.
        text = (Path(paths.ROOT) / "config" / "site.toml").read_text(encoding="utf-8")
        self.assertIn("example_budget = 600", text)
        self.assertIn("must then be drawn again", text)


class SaidInTheExampleSize(AppCase):
    def test_the_lists_say_the_cheapest_in_the_example_size_as_the_wardrobe_does(self):
        # A piece with nothing rated 70 or more, on Best for budget: "this is the cheapest in your size", which is the
        # example size while his sizes are the example's, on the shopping list too (export: line.said).
        piece = NothingGoodEnough.PIECE
        options = [derby("otto", 2, 39.99, ["43"]), derby("weekday", 1, 90, ["43"]),
                   derby("cos", 3, 25, [], sizes_all=[])]        # sizes not checked: passed over for those in his size
        catalog.update(lambda cat: cat.update(candidates=[c for c in cat["candidates"] if c["slot_id"] != piece]
                                              + [{**option, "slot_id": piece} for option in options]))
        having.the_whole_plan()
        self.set_mode("budget")
        self.assertTrue(profile_mod.sizes_unconfirmed(profile_mod.load()))
        listed = html.unescape(page_words(self.client.get("/list").get_data(as_text=True)))
        self.assertIn("Nothing reaches 70 — this is the cheapest in the example size.", listed)
        self.assertNotIn("in your size", listed)
        db.set_setting("sizes_confirmed", True)
        listed = html.unescape(page_words(self.client.get("/list").get_data(as_text=True)))
        self.assertIn("Nothing reaches 70 — this is the cheapest in your size.", listed)


class KeywordsOfASmallBudget(unittest.TestCase):
    def test_a_150_euro_jumper_is_not_offered_merino_first(self):
        # Under 450 € the words a piece's products are matched by leave out merino, wool and leather, as its name does
        # (config/budget.toml): with room for one product per store, the 300 € plan's jumper gets the cheaper cotton
        # one, the 600 € plan's the merino one.
        def jumper(budget: int) -> dict:
            return next(s for s in capsule.propose({**profile_mod.EXAMPLE, "budget": budget})[0] if s["category"] == "knit")
        pool = {"products": [
            {"id": "cos-1", "store": "cos", "category": "knit", "name": "Pullover aus Merinowolle", "colour": "Grau",
             "price": 89.0},
            {"id": "cos-2", "store": "cos", "category": "knit", "name": "Pullover aus Baumwolle", "colour": "Grau",
             "price": 49.0}]}
        collector = {**config.load("stores.toml")["collector"], "max_candidates": 1}
        self.assertEqual(jumper(300)["id"], jumper(600)["id"], "the same piece")
        self.assertEqual([c["id"] for c in shared.candidates_for(pool, jumper(300), collector)], ["cos-2"])
        self.assertEqual([c["id"] for c in shared.candidates_for(pool, jumper(600), collector)], ["cos-1"])
