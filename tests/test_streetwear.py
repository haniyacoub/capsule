"""Kinds you tick, and streetwear (round 2 of the budget-and-styles plan; the owner, 19 Nov 2026: "we need other forms
of clothes, office, street wear, sport, include whats needed").

What this round promises:
  * what he dresses for is the kinds of wardrobe he ticks (Everyday, Office, Streetwear), on Profile and in the
    welcome. An answer from before (one word: "both" is everyday and the office) is read as its kinds, with no
    migration, and plans exactly what it planned;
  * the rule that sizes the plan (config/budget.toml) takes a third list, streetwear (capsule.RANKED), and keeps its
    promises for every combination of kinds: no kind drops out as the budget grows, the plan only grows while the same
    kinds are in, never more than 24 pieces, and each piece's id is its own and the same at every budget;
  * Profile says when a kind he ticked joins, from the rule itself ("Streetwear joins at about 346 €");
  * hoodies and cargo trousers, end to end: garments, drawings, English names, things he owns, sizes, ratings, the
    collector's pages (config only: nothing is collected), the demo's products;
  * an everyday outfit with two street pieces is titled "Street", under a filter of its own, and the filter row shows
    his kinds only;
  * JD Sports is offered (Awin), with its rating and its demo products;
  * the visitors' example wardrobe keeps exactly its plan, its products and its outfits (so its pictures and clips
    stay the ones shown), and no customer's plan changes on deploy.
"""
import hashlib
import html
import re
import unittest

from wardrobe import capsule, catalog, config, db, guests, looks, mock, mockimg, outfits, paths, person, programmes
from wardrobe import scoring, selection, sizecheck, sizes, style
from wardrobe import profile as profile_mod
from wardrobe.app import create_app
from wardrobe.feeds import registry
from wardrobe.garments import GARMENTS, LAYER_OVER

from .test_app import AppCase
from .test_budget import answers_form
from .test_guests import WithExampleClips
from .test_production import ProductionCase
from .test_production import words as page_words

EXAMPLE = profile_mod.EXAMPLE
# Every combination of the three kinds, as he can tick them.
COMBINATIONS = [["everyday"], ["office"], ["street"], ["everyday", "office"], ["everyday", "street"],
                ["office", "street"], ["everyday", "office", "street"]]


def plan(use, budget: int, **changes) -> list[dict]:
    """The plan the example's answers propose for these kinds at this budget."""
    return capsule.propose({**EXAMPLE, "use": use, "budget": budget, **changes})[0]


def ids(slots: list[dict]) -> list[str]:
    return sorted(slot["id"] for slot in slots)


def said(page: str) -> str:
    return html.unescape(page_words(page))


# ── what he dresses for: the kinds he ticks, and the answers from before ───────────────────────────────

class TheAnswersFromBefore(unittest.TestCase):
    def test_one_word_from_before_is_read_as_its_kinds(self):
        self.assertEqual(capsule.kinds_of("both"), ("everyday", "office"))
        self.assertEqual(capsule.kinds_of("everyday"), ("everyday",))
        self.assertEqual(capsule.kinds_of("office"), ("office",))
        # The boxes he ticks, in the order the kinds join, whatever order they came in.
        self.assertEqual(capsule.kinds_of(["street", "everyday"]), ("everyday", "street"))
        self.assertEqual(capsule.kinds_of(["office", "street", "everyday"]), ("everyday", "office", "street"))
        # Nothing he could plan for: what a new account starts with.
        for nothing in (None, [], "", "nonsense", ["sport"]):
            self.assertEqual(capsule.ticked(nothing), (), nothing)
            self.assertEqual(capsule.kinds_of(nothing), ("everyday", "office"), nothing)

    def test_both_plans_exactly_what_everyday_and_the_office_plan(self):
        # An account's stored "both" is read as everyday and the office: at every budget, with and without shoes and
        # outerwear, the very same plan (ids, names, garments, colours, words, quantities), the same kinds in, and the
        # same budgets at which a waiting kind joins. So no plan is made anew for it.
        for old, kinds in (("both", ["everyday", "office"]), ("everyday", ["everyday"]), ("office", ["office"])):
            for shoes in (True, False):
                for outerwear in (True, False):
                    ticks = {"shoes": shoes, "outerwear": outerwear}
                    self.assertEqual(capsule.joins_at({**EXAMPLE, "use": old, **ticks}),
                                     capsule.joins_at({**EXAMPLE, "use": kinds, **ticks}))
                    for budget in range(50, 2001, 5):
                        where = f"{old}, {budget} €, {ticks}"
                        self.assertEqual(plan(old, budget, **ticks), plan(kinds, budget, **ticks), where)
                        self.assertEqual(capsule.kinds_in({**EXAMPLE, "use": old, "budget": budget, **ticks}),
                                         capsule.kinds_in({**EXAMPLE, "use": kinds, "budget": budget, **ticks}), where)



class AStoredAnswerFromBefore(AppCase):
    def test_reads_as_a_list_and_is_stored_as_one_at_his_next_save(self):
        db.set_setting("profile", {**EXAMPLE, "example": False, "use": "both"})
        self.assertEqual(profile_mod.load()["use"], ["everyday", "office"])
        db.set_setting("profile", {**EXAMPLE, "example": False, "use": "office"})
        self.assertEqual(profile_mod.load()["use"], ["office"])
        self.client.post("/profile", data=answers_form(use="both", budget_choice="300", budget=""))   # an older page
        self.assertEqual(db.get_setting("profile")["use"], ["everyday", "office"])


# ── the rule, with streetwear ──────────────────────────────────────────────────

class TheStreetwearList(unittest.TestCase):
    # Streetwear's pieces in the example's colours (navy, grey, white, olive), most needed first (capsule.RANKED). The
    # first three are a top, trousers and shoes.
    STREET = ["white-boxy-tee", "charcoal-cargo-trousers", "grey-chunky-sneakers", "grey-hoodie", "indigo-loose-jeans",
              "navy-boxy-tee", "olive-bomber-jacket", "navy-hoodie", "olive-workwear-overshirt", "navy-long-sleeve-tee",
              "stone-cargo-trousers", "grey-boxy-tee", "navy-parka", "black-loose-jeans", "charcoal-chunky-sneakers"]

    def test_streetwear_alone_by_budget(self):
        # The money for pieces is 150, 250, 400 and 600 €: rows 1-5, 1-8, 1-12, all 15 (a white boxy tee ×2 is two).
        for budget, rows, pieces in ((150, 5, 6), (300, 8, 9), (600, 12, 13), (1000, 15, 16)):
            with self.subTest(budget=budget):
                slots = plan(["street"], budget)
                self.assertEqual(ids(slots), sorted(self.STREET[:rows]))
                self.assertEqual(capsule.count(slots), pieces)
        first = {s["id"]: (s["name"], s["category"], s["keywords"], s["qty"]) for s in plan(["street"], 150)}
        self.assertEqual(first, {
            "white-boxy-tee": ("White boxy tee", "tee", "heavyweight boxy", 2),
            "charcoal-cargo-trousers": ("Charcoal cargo trousers", "cargo", "", 1),
            "grey-chunky-sneakers": ("Grey chunky sneakers", "sneakers", "chunky", 1),
            "grey-hoodie": ("Grey hoodie", "hoodie", "", 1),
            "indigo-loose-jeans": ("Indigo loose jeans", "jeans", "loose", 1)})

    def test_everyday_and_streetwear_at_300_euros_is_10_pieces_with_one_white_tee(self):
        # Everyday's first three (83 €) and streetwear's (its white tee is everyday's: 70 €) fit in 250 €; then each
        # one's 4th and 5th pieces, a piece the two share once, until the light jacket would go past 250 €.
        slots = plan(["everyday", "street"], 300)
        self.assertEqual(ids(slots), sorted([
            "white-tee", "indigo-jeans", "white-leather-sneakers", "charcoal-cargo-trousers", "grey-chunky-sneakers",
            "navy-tee", "grey-hoodie", "stone-chinos", "grey-merino-jumper"]))
        self.assertEqual(capsule.count(slots), 10)
        tees = [s for s in slots if (s["category"], s["colour"]) == ("tee", "white")]
        self.assertEqual([(s["name"], s["qty"]) for s in tees], [("White tee", 2)], "one white tee, everyday's")

    def test_with_the_office_and_streetwear_the_white_tee_is_streetwears(self):
        # The office's 13th piece is a plain white tee and streetwear's first is two boxy white tees: one garment in
        # one colour, so one piece. In the line streetwear's first three come before the office's 13th piece, so the
        # piece is streetwear's, at every budget. Streetwear joins when its two tees fit (about 216 €), and without
        # shoes its first pieces, the boxy tees and the cargo trousers, are two street pieces: a Street outfit.
        both = {**EXAMPLE, "use": ["office", "street"]}
        self.assertEqual(capsule.joins_at(both), {"street": 216})
        self.assertEqual(capsule.joins_at({**both, "shoes": False}), {"street": 108})
        for budget in (216, 300, 600, 1000, 2000):
            tees = [s for s in plan(both["use"], budget) if (s["category"], s["colour"]) == ("tee", "white")]
            self.assertEqual([(s["id"], s["name"], s["keywords"], s["qty"]) for s in tees],
                             [("white-boxy-tee", "White boxy tee", "heavyweight boxy", 2)], budget)
        self.assertEqual(capsule.kinds_in({**both, "budget": 215}), ["office"])
        no_shoes = plan(both["use"], 108, shoes=False)
        self.assertEqual(sorted((s["name"], s["qty"]) for s in no_shoes if s["category"] in ("tee", "cargo")),
                         [("Charcoal cargo trousers", 1), ("White boxy tee", 2)])

    def test_all_three_kinds_join_in_order_and_say_when(self):
        # Office's first three join from 206 €, streetwear's from 346 €: until then it waits, and so does every kind
        # after the first that waits.
        three = {**EXAMPLE, "use": ["everyday", "office", "street"]}
        self.assertEqual(capsule.joins_at(three), {"office": 206, "street": 346})
        for budget, kinds in ((150, ["everyday"]), (205, ["everyday"]), (206, ["everyday", "office"]),
                              (300, ["everyday", "office"]), (345, ["everyday", "office"]),
                              (346, ["everyday", "office", "street"])):
            self.assertEqual(capsule.kinds_in({**three, "budget": budget}), kinds, budget)
        # Until streetwear joins, the plan is the one everyday and the office plan.
        for budget in (150, 300, 345):
            self.assertEqual(plan(three["use"], budget), plan(["everyday", "office"], budget), budget)
        # At 600 € (400 € for pieces) the three kinds' first three, then each one's 4th, 5th and 6th pieces, a shared
        # piece once, until the light jacket would go past 400 €: 14 pieces.
        self.assertEqual(ids(plan(three["use"], 600)), sorted([
            "white-tee", "indigo-jeans", "white-leather-sneakers", "white-oxford-shirt", "grey-wool-trousers",
            "dark-brown-derby-shoes", "charcoal-cargo-trousers", "grey-chunky-sneakers", "navy-tee",
            "grey-merino-jumper", "grey-hoodie", "stone-chinos", "light-blue-oxford-shirt"]))
        self.assertEqual(capsule.count(plan(three["use"], 600)), 14)
        self.assertEqual(capsule.joins_at({**EXAMPLE, "use": ["everyday", "street"]}), {"street": 153})
        self.assertEqual(capsule.kinds_words(["everyday", "office", "street"]), "everyday, the office and streetwear")
        self.assertEqual(capsule.kinds_words(["street"]), "streetwear")
        self.assertEqual(capsule.kinds_words(["everyday", "street"]), "everyday and streetwear")

    def test_every_5_euros_for_every_combination_of_kinds(self):
        # Every budget from 50 € to 2,000 €, for each combination of the three kinds, with and without shoes and
        # outerwear. No kind drops out as the budget grows; while the same kinds are in, the plan only grows; no plan
        # has more than 24 pieces; the ids in a plan are each once, an id always names one garment in one colour, and
        # one garment in one colour keeps its id at every budget.
        named: dict[str, tuple[str, str]] = {}
        for kinds in COMBINATIONS:
            for shoes in (True, False):
                for outerwear in (True, False):
                    before = None
                    stable: dict[tuple[str, str], str] = {}
                    for budget in range(50, 2001, 5):
                        answers = {**EXAMPLE, "use": kinds, "budget": budget, "shoes": shoes, "outerwear": outerwear}
                        where = f"{kinds}, {budget} €, shoes {shoes}, outerwear {outerwear}"
                        joined, slots = capsule.kinds_in(answers), capsule.propose(answers)[0]
                        pieces = {s["id"] for s in slots}
                        self.assertEqual(len(pieces), len(slots), where)
                        self.assertLessEqual(capsule.count(slots), 24, where)
                        self.assertEqual(joined, [kind for kind in capsule.KIND_ORDER if kind in joined], where)
                        self.assertLessEqual(set(joined), set(kinds), where)
                        for s in slots:
                            key = (s["category"], s["colour"])
                            self.assertEqual(named.setdefault(s["id"], key), key, where)
                            self.assertEqual(stable.setdefault(key, s["id"]), s["id"], where)
                            if not shoes:
                                self.assertNotIn(s["category"], capsule.SHOES, where)
                            if not outerwear:
                                self.assertNotIn(s["category"], capsule.OUTERWEAR, where)
                        if before is not None:
                            self.assertLessEqual(set(before[0]), set(joined), f"a kind dropped: {where}")
                            if before[0] == joined:
                                self.assertLessEqual(before[1], pieces, f"the plan lost a piece: {where}")
                        before = (joined, pieces)
                    self.assertEqual(before[0], kinds, f"at 2,000 € every kind is in: {kinds}")


# ── hoodies and cargo trousers, end to end ─────────────────────────────────────

class HoodiesAndCargoTrousers(unittest.TestCase):
    def test_two_garments_with_their_layers(self):
        hoodie, cargo = GARMENTS["hoodie"], GARMENTS["cargo"]
        self.assertEqual((hoodie.label, hoodie.section, hoodie.layer, hoodie.size_group, hoodie.formality),
                         ("Hoodie", "Hoodies", "top", "tops", (1, 2)))
        self.assertEqual((cargo.label, cargo.section, cargo.layer, cargo.size_group, cargo.formality),
                         ("Cargo trousers", "Trousers", "bottom", "bottoms", (1, 2)))
        # An overshirt can go over a hoodie (as a jacket or a coat can: the outer layer goes over any top); a blazer,
        # a cardigan or a jumper cannot.
        self.assertIn("hoodie", LAYER_OVER["overshirt"])
        self.assertEqual([mid for mid, tops in LAYER_OVER.items() if "hoodie" in tops], ["overshirt"])

    def test_their_drawings(self):
        client = create_app().test_client()
        for kind in ("hoodie", "cargo"):
            response = client.get(f"/mock/img/{kind}.svg?c=8a8d91")
            self.assertEqual((response.status_code, response.mimetype), (200, "image/svg+xml"), kind)
            self.assertTrue(response.get_data(as_text=True).startswith("<svg"), kind)
        self.assertNotEqual(mockimg.svg("hoodie", "8a8d91"), mockimg.svg("longsleeve", "8a8d91"), "it has its hood")
        self.assertNotEqual(mockimg.svg("cargo", "8a8d91"), mockimg.svg("trousers", "8a8d91"), "and these their pockets")

    def test_things_he_owns(self):
        for line, garment in (("grey hoodie", "hoodie"), ("Kapuzenpullover", "hoodie"), ("navy zip hoody", "hoodie"),
                              ("schwarzer Kapuzen-Pullover", "hoodie"), ("black cargo pants", "cargo"),
                              ("Cargohose in Oliv", "cargo"), ("stone cargo trousers", "cargo"),
                              # what was there stays what it was
                              ("grey jumper", "knit"), ("denim jacket", "jacket"), ("indigo jeans", "jeans"),
                              ("charcoal trousers", "trousers"), ("a white t-shirt", "tee"),
                              # cargo shorts are no garment of the plans, as before cargo trousers came: he is told
                              ("cargo shorts", None), ("Cargo-Shorts in Khaki", None), ("kurze Cargohose", None)):
            self.assertEqual(capsule.detect_garment(line), garment, line)
        slots, unmatched = capsule.propose({**EXAMPLE, "use": ["everyday", "street"], "budget": 300,
                                            "owned": "olive cargo shorts"})
        self.assertEqual(unmatched, ["olive cargo shorts"])
        self.assertFalse(any(s["owned"] for s in slots), "his cargo trousers are still to buy")
        slots, unmatched = capsule.propose({**EXAMPLE, "use": ["everyday"], "budget": 300,
                                            "owned": "grey hoodie\nblack cargo pants"})
        self.assertEqual(unmatched, [])
        self.assertEqual(sorted((s["category"], s["colour"]) for s in slots if s["owned"]),
                         [("cargo", "black"), ("hoodie", "grey")], "each is a piece of his plan that he owns")

    def test_sizes(self):
        # Cargo trousers come in one length, as trousers and chinos do: a tall or short customer is told.
        self.assertIn("cargo", sizecheck.ONE_LENGTH)
        status = sizes.SizeStatus(True, "48", "48 in stock")
        tall = sizecheck.check({"store": "cos", "fit": "regular"}, status, {**EXAMPLE, "height_cm": 195}, "cargo",
                               sizes.load_charts()).notes
        self.assertIn("Comes in one length and you are 195 cm: check sleeve and leg length.", tall)
        # A store without a size table prints what reads without one: letters on hoodies, waist/length on cargo.
        me = {"top_size": "M", "waist": 32, "length": 32, "shoe": "43"}
        charts = sizes.load_charts()
        for store in ("otto", "jd-sports", "cos", "weekday"):
            for category in ("hoodie", "cargo"):
                run = mock.size_run(store, category)
                self.assertTrue(any(sizes.label_fits(label, me, store, category, charts) for label in run),
                                f"{store} {category}: {run}")
        self.assertEqual(mock.size_run("otto", "hoodie"), ["XS", "S", "M", "L", "XL", "XXL"])
        self.assertIn("32/32", mock.size_run("jd-sports", "cargo"))

    def test_ratings(self):
        def rated(store, price, label, category):
            return scoring.score({"store": store, "price": price, "composition_text": label}, category).total
        self.assertGreaterEqual(rated("otto", 29.99, "80 % Baumwolle, 20 % Polyester", "hoodie"), 70)
        self.assertGreater(rated("otto", 29.99, "100 % Baumwolle", "hoodie"),
                           rated("otto", 29.99, "100 % Polyester", "hoodie"))
        self.assertLess(rated("otto", 29.99, "100 % Polyester", "hoodie"), 70, "a polyester hoodie is not good enough")
        self.assertGreaterEqual(rated("otto", 29.99, "100 % Baumwolle", "cargo"), 70)
        rules = scoring.load_rules()
        self.assertEqual({key: (band["suspicious_below"], band["fair"], band["steep_above"])
                          for key, band in rules["price"]["bands"].items() if key in ("hoodie", "cargo")},
                         {"hoodie": (12, [20, 90], 140), "cargo": (15, [25, 110], 160)})
        fabric = rules["fabric"]["by_category"]
        self.assertEqual((fabric["hoodie"]["cotton"], fabric["hoodie"]["polyester"]), (85, 35))
        self.assertEqual((fabric["cargo"]["cotton"], fabric["cargo"]["polyamide"]), (85, 55))
        for store in ("cos", "weekday", "otto", "jd-sports"):
            for category in ("hoodie", "cargo"):
                self.assertIn(category, rules["brand"][store], f"{store} rates its {category}")
        # Their usual prices at a budget store, which the rule counts them at, are estimates and say so.
        usual = capsule.budget_rules()["usual_price"]
        self.assertEqual((usual["hoodie"], usual["cargo"]), (30, 30))
        text = (paths.CONFIG_DIR / "budget.toml").read_text(encoding="utf-8")
        for garment in ("hoodie", "cargo"):
            line = next(line for line in text.splitlines() if line.startswith(f"{garment} "))
            self.assertIn("# estimate", line)

    def test_the_collectors_pages_and_words_are_set_and_nothing_is_collected(self):
        stores = config.load("stores.toml")
        for key in ("cos", "weekday"):
            for category in ("hoodie", "cargo"):
                rules = stores[key]["garments"][category]
                self.assertTrue(rules["pages"], f"{key} {category}")
                self.assertTrue(all(page.startswith("/de-de/men/") for page in rules["pages"]), f"{key} {category}")
            self.assertIn("cargo", stores[key]["garments"]["cargo"]["include"])
            self.assertIn("cargo", stores[key]["garments"]["trousers"]["exclude"], "never offered as plain trousers")
            for word in ("hoodie", "kapuze"):      # (a "Strickpullover mit Kapuze" on a jumper page too)
                self.assertIn(word, stores[key]["garments"]["knit"]["exclude"], f"{key}: nor a hoodie as a jumper")
        words = stores["collector"]["keyword_words"]
        for word in ("boxy", "loose", "chunky", "cargo", "parka", "bomber"):
            self.assertIn(word, words[word], word)
        self.assertIn("weit", words["loose"])
        # Config only: the demo's products are invented, and nothing of the stores was read for this round.
        text = (paths.CONFIG_DIR / "stores.toml").read_text(encoding="utf-8")
        self.assertIn("These addresses were not opened", text)

    def test_the_street_style_is_built_on_them(self):
        styles = style.load_rules()["styles"]
        self.assertEqual(styles["street"]["garments"],
                         ["jeans", "overshirt", "tee", "longsleeve", "sneakers", "hoodie", "cargo"])


class TheDemosStreetwear(unittest.TestCase):
    def test_jd_sports_otto_cos_and_weekday_sell_hoodies_and_cargo_trousers(self):
        # Invented products, at the prices of the plan (2.9): JD Sports only these two for now.
        slots = [{"id": f"piece-{category}", "category": category, "colour": "grey"} for category in GARMENTS]
        demo = mock.build(slots)
        found: dict[str, dict[str, list[float]]] = {}
        for c in demo["candidates"]:
            found.setdefault(c["store"], {}).setdefault(c["slot_id"].removeprefix("piece-"), []).append(c["price"])
        self.assertEqual(sorted(found["jd-sports"]), ["cargo", "hoodie"])
        self.assertEqual((found["jd-sports"]["hoodie"], found["jd-sports"]["cargo"]), ([54.99], [49.99]))
        self.assertEqual((found["otto"]["hoodie"], found["otto"]["cargo"]), ([29.99, 34.99], [29.99, 34.99]))
        self.assertEqual((found["cos"]["hoodie"], found["cos"]["cargo"]), ([79.0], [99.0]))
        self.assertEqual((found["weekday"]["hoodie"], found["weekday"]["cargo"]), ([45.0], [60.0]))
        self.assertEqual(programmes.only_offered(demo)["candidates"], demo["candidates"], "every one is offered")
        for c in demo["candidates"]:
            if c["slot_id"] in ("piece-hoodie", "piece-cargo"):
                self.assertGreaterEqual(scoring.score(c, c["slot_id"].removeprefix("piece-")).total, 70, c["name"])

    def test_jd_sports_is_offered_for_streetwear(self):
        stores = config.load("stores.toml")
        jd = stores["jd-sports"]
        self.assertEqual((jd["label"], jd["programme"], jd["styles"], jd["price"]),
                         ("JD Sports", "awin", ["street"], "mid"))
        self.assertIn("jd-sports", programmes.offered())
        self.assertNotIn("jd-sports", programmes.read_by_the_collector(), "it has no pages to collect")
        rating = scoring.load_rules()["brand"]["jd-sports"]
        self.assertEqual((rating["hoodie"], rating["sneakers"]), (80, 82))
        listed = registry.load()["jd-sports"]
        self.assertEqual((listed["network"], listed["programme_id"], listed["status"]), ("awin", "10073", "none"))
        self.assertIn("jd-sports", style.stores_that_suit({**style.EMPTY, "styles": ["street"]}))


class TheDemoFitsStreetwear(AppCase):
    def test_best_for_budget_fits_with_nothing_rated_under_70(self):
        for kinds in (["street"], ["everyday", "street"], ["office", "street"], ["everyday", "office", "street"]):
            for budget in (150, 216, 300, 600, 1000):
                with self.subTest(kinds=kinds, budget=budget):
                    answers = {**EXAMPLE, "example": False, "use": kinds, "budget": budget}
                    profile_mod.save(answers)
                    profile_mod.answer("budget")
                    db.replace_slots(capsule.propose(answers)[0])
                    catalog.save(mock.build(db.list_slots()))
                    self.set_mode("budget")
                    w = selection.build()
                    self.assertEqual(w.note, "", "it fits")
                    self.assertLessEqual(w.total, budget)
                    for view in w.slots:
                        self.assertIsNotNone(view.chosen, view.slot["name"])
                        self.assertGreaterEqual(view.chosen.score.total, 70, view.slot["name"])
                        self.assertFalse(view.warn, f"{view.slot['name']}: {view.note}")


# ── outfits: the Street title and the filters ──────────────────────────────────

class TheStreetTitle(AppCase):
    def wardrobe(self, kinds: list[str], budget: int) -> selection.Wardrobe:
        """His plan for these kinds at this budget, on the demo's products."""
        answers = {**EXAMPLE, "example": False, "use": kinds, "budget": budget}
        profile_mod.save(answers)
        db.replace_slots(capsule.propose(answers)[0])
        catalog.save(mock.build(db.list_slots()))
        return selection.build()

    def outfit(self, w, *pieces: str) -> outfits.Outfit:
        found = outfits.find_by_sig(w, outfits.SEP.join(pieces))
        self.assertIsNotNone(found, pieces)
        return found

    def test_two_street_pieces_make_a_street_outfit(self):
        street = self.wardrobe(["street"], 300)
        self.assertEqual(self.outfit(street, "grey-hoodie", "indigo-loose-jeans", "grey-chunky-sneakers").label,
                         "Street")
        everyday = self.wardrobe(["everyday"], 300)
        self.assertEqual(self.outfit(everyday, "white-tee", "indigo-jeans", "white-leather-sneakers").label,
                         "Everyday")
        # One street piece is not enough: a hoodie with plain jeans and white sneakers is an everyday outfit.
        both = self.wardrobe(["everyday", "street"], 300)
        self.assertEqual(self.outfit(both, "grey-hoodie", "indigo-jeans", "white-leather-sneakers").label, "Everyday")
        self.assertEqual(self.outfit(both, "grey-hoodie", "charcoal-cargo-trousers", "white-leather-sneakers").label,
                         "Street")
        # A street piece is so by what the plan made it, not by the store's name for its product: plain indigo jeans
        # filled by "Jeans Loose Baggy" stay plain jeans.
        jeans = next(view for view in both.slots if view.slot["id"] == "indigo-jeans")
        baggy = next(c for c in jeans.cands if c.data["name"] == "Jeans Loose Baggy")
        db.update_slot("indigo-jeans", locked=True, pick=baggy.id)
        piece = next(p for p in outfits.pieces_of(selection.build()) if p.view.slot["id"] == "indigo-jeans")
        self.assertEqual((piece.view.chosen.data["name"], piece.street), ("Jeans Loose Baggy", False))

    def test_with_the_office_and_streetwear_its_first_pieces_make_a_street_outfit(self):
        # From the budget streetwear joins at, its first three pieces (two boxy white tees, charcoal cargo trousers,
        # grey chunky sneakers) are a Street outfit; without shoes the tees and the cargo trousers are.
        for budget in (216, 300, 600, 1000):
            w = self.wardrobe(["office", "street"], budget)
            self.assertEqual(self.outfit(w, "white-boxy-tee", "charcoal-cargo-trousers", "grey-chunky-sneakers").label,
                             "Street", budget)
            self.assertTrue(all(o.label != "Street" or o.suits("everyday") for o in outfits.all_outfits(w)), budget)
        answers = {**EXAMPLE, "example": False, "use": ["office", "street"], "budget": 300, "shoes": False}
        profile_mod.save(answers)
        db.replace_slots(capsule.propose(answers)[0])
        catalog.save(mock.build(db.list_slots()))
        self.assertEqual(self.outfit(selection.build(), "white-boxy-tee", "charcoal-cargo-trousers").label, "Street")

    def test_an_overshirt_or_a_jacket_goes_over_a_hoodie(self):
        w = self.wardrobe(["street"], 600)
        layered = [o.slots for o in outfits.all_outfits(w) if "navy-hoodie" in o.slots]
        self.assertTrue(any(slots[0] == "olive-workwear-overshirt" for slots in layered), "the overshirt over it")
        self.assertTrue(any(slots[0] == "olive-bomber-jacket" for slots in layered), "the bomber over it")
        office = self.wardrobe(["everyday", "office", "street"], 2000)
        self.assertFalse([o.slots for o in outfits.all_outfits(office)
                          if "navy-wool-blazer" in o.slots and {"grey-hoodie", "navy-hoodie"} & set(o.slots)],
                         "never a blazer with a hoodie")

    def test_an_empty_street_filter_names_the_pieces_that_have_no_product_yet(self):
        # As on a published list of COS and Weekday products, which has no hoodies, cargo trousers or chunky sneakers
        # in these colours: the street pieces are empty, so no outfit is titled Street, and the page says why.
        self.wardrobe(["everyday", "street"], 300)
        self.client.post("/profile", data=answers_form(use=["everyday", "street"], budget_choice="300", budget=""))
        empty = {"grey-hoodie", "charcoal-cargo-trousers", "grey-chunky-sneakers"}
        catalog.update(lambda cat: cat.update(candidates=[c for c in cat["candidates"] if c["slot_id"] not in empty]))
        self.assertFalse([o for o in outfits.all_outfits(selection.build()) if o.label == "Street"])
        page = said(self.client.get("/outfits?occasion=street").get_data(as_text=True))
        self.assertIn("No street outfits yet. Not in Stilsmith's product list yet: grey hoodie, charcoal cargo trousers "
                      "and grey chunky sneakers. All outfits", page)
        self.assertNotIn("An outfit needs at least a top and trousers", page)
        # Each with its own reason, as the budget bar counts them: options, but none in his size, is another one.
        db.set_setting("sizes_confirmed", True)
        catalog.update(lambda cat: cat.update(candidates=cat["candidates"] + [
            {**c, "slot_id": "charcoal-cargo-trousers", "sizes_in_stock": []}
            for c in mock.build([{"id": "charcoal-cargo-trousers", "category": "cargo", "colour": "charcoal"}])["candidates"]]))
        page = said(self.client.get("/outfits?occasion=street").get_data(as_text=True))
        self.assertIn("No street outfits yet. Not in Stilsmith's product list yet: grey hoodie and grey chunky sneakers. "
                      "Not in stock in your size: charcoal cargo trousers. All outfits", page)
        # Where Street outfits exist and he answered them all, it is the page's "no more to offer", not these words.
        catalog.save(mock.build(db.list_slots()))
        for outfit in [o for o in outfits.all_outfits(selection.build()) if o.label == "Street"]:
            self.client.post("/outfits/no", data={"sig": outfit.sig})
        page = said(self.client.get("/outfits?occasion=street").get_data(as_text=True))
        self.assertIn("No more outfits to offer for “street”.", page)
        self.assertNotIn("No street outfits yet", page)

    def test_the_street_filter_lists_only_street_outfits(self):
        w = self.wardrobe(["everyday", "street"], 600)
        every = outfits.all_outfits(w)
        street = [o for o in every if o.label == "Street"]
        self.assertTrue(street and len(street) < len(every))
        shown, total = outfits.generate(w, occasion="street", limit=60)
        self.assertEqual(total, len(street))
        self.assertTrue(shown and all(o.label == "Street" for o in shown), [o.label for o in shown])
        # Everyday is every outfit of level 3 or under, the Street ones too; Office none of them.
        self.assertTrue(all(o.suits("everyday") and not o.suits("office") for o in street))


class TheFilterRow(AppCase):
    def chips(self, url: str = "/outfits") -> tuple[list[str], list[str]]:
        """The filters over the outfits, and the one that is on."""
        page = self.client.get(url).get_data(as_text=True)
        row = re.search(r'<div class="chips" role="group" aria-label="Which outfits">(.*?)</div>', page, re.S).group(1)
        names = [html.unescape(name) for name in re.findall(r'<a class="chip-link[^"]*"[^>]*>([^<]+)</a>', row)]
        on = [html.unescape(name) for name in re.findall(r'aria-current="page">([^<]+)</a>', row)]
        return names, on

    def tick(self, *kinds: str) -> None:
        self.client.post("/profile", data=answers_form(use=list(kinds), budget_choice="600", budget=""))
        self.assertEqual(profile_mod.load()["use"], list(kinds))

    def test_only_his_kinds_and_the_page_opens_on_his_only_one(self):
        self.assertEqual(self.chips(), (["All", "Everyday", "Office", "My outfits"], ["All"]))
        self.tick("everyday", "street")
        self.assertEqual(self.chips(), (["All", "Everyday", "Street", "My outfits"], ["All"]))
        self.tick("everyday", "office", "street")
        self.assertEqual(self.chips()[0], ["All", "Everyday", "Street", "Office", "My outfits"])
        self.tick("street")
        self.assertEqual(self.chips(), (["All", "Street", "My outfits"], ["Street"]), "his only kind")
        self.tick("office")
        self.assertEqual(self.chips(), (["All", "Office", "My outfits"], ["Office"]))
        # An address that names a filter he does not dress for (a link from before) still says what it shows.
        self.assertEqual(self.chips("/outfits?occasion=street"), (["All", "Street", "Office", "My outfits"], ["Street"]))


# ── Profile and the welcome ────────────────────────────────────────────────────

class TickingOnProfile(AppCase):
    def boxes(self, page: str) -> list[tuple[str, bool]]:
        part = re.search(r'<div class="kinds" role="group" aria-labelledby="use-label".*?</div>', page, re.S).group(0)
        return [(value, bool(on)) for value, on in
                re.findall(r'<input type="checkbox" name="use" value="(\w+)"( checked)?>', part)]

    def test_a_box_for_each_kind_and_what_he_ticks_plans_the_wardrobe(self):
        page = self.client.get("/profile").get_data(as_text=True)
        self.assertEqual(self.boxes(page), [("everyday", True), ("office", True), ("street", False)])
        self.assertIn('<input type="hidden" name="use_shown" value="1">', page)
        labels = re.findall(r'<input type="checkbox" name="use" value="\w+"(?: checked)?><span>([^<]+)</span>', page)
        self.assertEqual(labels, ["Everyday", "Office", "Streetwear"])
        saved = self.client.post("/profile", data=answers_form(use=["everyday", "street"], budget_choice="300",
                                                               budget="", use_shown="1"))
        self.assertEqual(saved.headers["Location"], "/outfits", "new kinds plan the wardrobe afresh")
        self.assertEqual(profile_mod.load()["use"], ["everyday", "street"])
        self.assertEqual(ids(db.list_slots()), ids(plan(["everyday", "street"], 300)))
        self.assertEqual(self.boxes(self.client.get("/profile").get_data(as_text=True)),
                         [("everyday", True), ("office", False), ("street", True)])

    def test_ticking_none_keeps_his_kinds_and_says_so(self):
        self.client.post("/profile", data=answers_form(use=["street"], budget_choice="300", budget=""))
        before = db.list_slots()
        self.client.post("/profile", data=answers_form(use=None, budget_choice="300", budget="", use_shown="1"))
        self.assertEqual(profile_mod.load()["use"], ["street"])
        self.assertEqual(db.list_slots(), before, "his plan is as it was")
        self.assertIn(profile_mod.NO_KINDS, said(self.client.get("/profile").get_data(as_text=True)))

    def test_profile_says_when_a_waiting_kind_joins(self):
        saved = self.client.post("/profile", data=answers_form(use=["everyday", "office", "street"],
                                                               budget_choice="300", budget=""))
        message = said(self.client.get(saved.headers["Location"]).get_data(as_text=True))
        self.assertIn("Your plan now has 9 pieces in your colours. Streetwear joins at about 346 €.", message)
        page = self.client.get("/profile").get_data(as_text=True)
        under = said(re.search(r'<p class="muted small" id="kinds-say">.*?</p>', page, re.S).group(0))
        self.assertEqual(under, "Tick any. They join your plan in this order, as your budget allows. Your budget is "
                                "300 €: Streetwear joins at about 346 €.")
        choices = [said(label) for label in re.findall(r'<label class="check budget-choice">(.*?)</label>', page, re.S)]
        self.assertEqual(choices[:4], [
            "Starter 150 € about 7 pieces Office joins at about 206 € Streetwear joins at about 346 €",
            "Basic 300 € about 9 pieces Streetwear joins at about 346 €",
            "Solid 600 € about 14 pieces", "Full 1,000 €+ about 18 pieces"])
        self.assertEqual([capsule.pieces_at(profile_mod.load(), amount) for amount in (150, 300, 600, 1000)],
                         [7, 9, 14, 18], "the rule's own counts")
        slots_page = said(self.client.get("/slots").get_data(as_text=True))
        self.assertIn("Planned for everyday and the office, for 300 €: 9 pieces. Streetwear joins at about 346 €.",
                      slots_page)
        # At 150 € both wait, each with its own amount.
        self.client.post("/profile", data=answers_form(use=["everyday", "office", "street"], budget_choice="150",
                                                       budget=""))
        page = self.client.get("/profile").get_data(as_text=True)
        self.assertIn("Your budget is 150 €: Office joins at about 206 €, Streetwear at about 346 €.",
                      said(re.search(r'id="kinds-say">.*?</p>', page, re.S).group(0)))
        # Under the Street filter, where none of its pieces is in his plan yet, the page says why: also once he has
        # outfits in his wardrobe ("No more outfits to offer" would say he had seen them all).
        first = outfits.generate(selection.build(), limit=1)[0][0]
        self.client.post("/outfits/save", data={"key": first.key, "sig": first.sig, "want": "save"})
        self.assertEqual(len(db.list_saved()), 1)
        empty = said(self.client.get("/outfits?occasion=street").get_data(as_text=True))
        self.assertIn("No outfits for “street” yet: Streetwear joins your plan at a budget of about 346 €. Your budget "
                      "· All outfits", empty)
        self.assertNotIn("An outfit needs at least a top and trousers", empty)
        self.assertNotIn("No more outfits to offer", empty)
        # A budget he has not given: said as such.
        profile_mod.unanswer("budget")
        page = self.client.get("/profile").get_data(as_text=True)
        self.assertIn("Until you set your budget, plans are made for 150 €: Office joins at about 206 €, Streetwear at "
                      "about 346 €.", said(re.search(r'id="kinds-say">.*?</p>', page, re.S).group(0)))
        # Where none waits, nothing is said of it.
        self.client.post("/profile", data=answers_form(use=["street"], budget_choice="300", budget=""))
        page = self.client.get("/profile").get_data(as_text=True)
        self.assertNotIn("joins at about", said(re.search(r'id="kinds-say">.*?</p>', page, re.S).group(0)))


class TickingInTheWelcome(AppCase):
    def test_the_same_boxes_and_what_he_ticks_is_saved(self):
        page = self.client.get("/welcome/3").get_data(as_text=True)
        boxes = re.findall(r'<input type="checkbox" name="use" value="(\w+)"( checked)?><span>([^<]+)</span>', page)
        self.assertEqual(boxes, [("everyday", "", "Everyday"), ("office", "", "Office"), ("street", "", "Streetwear")],
                         "none ticked while he has not answered")
        self.client.post("/welcome/2", data={"budget_choice": "300", "budget": ""})
        self.client.post("/welcome/3", data={"use": ["street", "everyday"]})
        self.assertEqual((profile_mod.load()["use"], "use" in profile_mod.answered()), (["everyday", "street"], True))
        self.assertEqual(ids(db.list_slots()), ids(plan(["everyday", "street"], 300)), "the plan follows")
        page = self.client.get("/welcome/3").get_data(as_text=True)
        self.assertIn('<input type="checkbox" name="use" value="street" checked>', page)
        # His budget's counts in step 2 are for his kinds now.
        self.assertIn("About how many pieces each plans for everyday and streetwear.",
                      said(self.client.get("/welcome/2").get_data(as_text=True)))

    def test_none_ticked_leaves_the_question_unanswered(self):
        self.client.post("/welcome/3", data={})
        self.assertEqual((profile_mod.load()["use"], profile_mod.answered()), (["everyday", "office"], set()))


class ExistingCustomers(ProductionCase):
    """Accounts that hold an answer from before (one word), through the deploy of this round."""

    def test_a_deploy_and_a_save_of_sizes_change_no_plan(self):
        for email, word, kinds in (("both@example.com", "both", ["everyday", "office"]),
                                   ("office@example.com", "office", ["office"])):
            client = self.member(email)
            with db.as_user(self.user_id(email)):
                answers = {**EXAMPLE, "example": False, "use": word, "budget": 600}
                db.set_setting("profile", answers)
                profile_mod.answer("colours", "use", "budget")
                db.replace_slots(capsule.propose(answers)[0])
                db.set_setting("plan_edited", False)
                before = db.list_slots()
            self.app = create_app()                          # the deploy: a restart with this round's code
            for url in ("/", "/outfits", "/profile", "/slots"):
                self.assertEqual(client.get(url).status_code, 200, url)
            with db.as_user(self.user_id(email)):
                self.assertEqual(db.list_slots(), before, f"{email}: the deploy changed his plan")
                self.assertEqual(db.get_setting("profile")["use"], word, "nothing is written at the deploy")
                self.assertEqual(profile_mod.load()["use"], kinds)
            page = client.get("/profile").get_data(as_text=True)
            for kind in capsule.KIND_ORDER:
                ticked = f'<input type="checkbox" name="use" value="{kind}" checked>' in page
                self.assertEqual(ticked, kind in kinds, f"{email}: {kind}")
            # His sizes, saved with the boxes as the page shows them: the plan stays, and the answer is a list now.
            form = {**answers_form(use=kinds, budget_choice="600", budget="", top_size="L"), "use_shown": "1"}
            saved = self.post(client, "/profile", **form)
            self.assertTrue(saved.headers["Location"].endswith("/profile"), "no plan was made")
            with db.as_user(self.user_id(email)):
                self.assertEqual(db.list_slots(), before, f"{email}: a save of his sizes changed his plan")
                self.assertEqual(db.get_setting("profile")["use"], kinds)


# ── the visitors' example wardrobe stays exactly as it was ──────────────────────

# The example as the code before this round made it (main at 693e6d9, 19 Nov 2026), worked out then on the same
# products: its plan, the product picked for each piece, and the first 12 outfits a visitor sees (their keys: each
# outfit's pieces and products, which its AI picture and clip are named after).
EXAMPLE_PLAN = [
    ("navy-light-jacket", "Navy light jacket", "jacket", "navy", "lightweight", 1),
    ("grey-merino-jumper", "Grey merino jumper", "knit", "grey", "merino crew-neck", 1),
    ("white-oxford-shirt", "White oxford shirt", "shirt", "white", "oxford", 1),
    ("light-blue-oxford-shirt", "Light blue oxford shirt", "shirt", "light-blue", "oxford", 1),
    ("white-tee", "White tee", "tee", "white", "heavyweight", 2),
    ("navy-tee", "Navy tee", "tee", "navy", "heavyweight", 1),
    ("grey-wool-trousers", "Grey wool trousers", "trousers", "grey", "wool", 1),
    ("stone-chinos", "Stone chinos", "chinos", "stone", "", 1),
    ("indigo-jeans", "Indigo jeans", "jeans", "indigo", "straight", 1),
    ("white-leather-sneakers", "White leather sneakers", "sneakers", "white", "leather", 1),
    ("dark-brown-derby-shoes", "Dark brown derby shoes", "shoes", "dark-brown", "leather derby", 1),
]
# On the published list of tests/test_guests.py (COS and Weekday, as the live servers have such a list).
ON_THE_LIST = {
    "picks": {"navy-light-jacket": "weekday-2000000210", "grey-merino-jumper": "weekday-2000000203",
              "white-oxford-shirt": "weekday-2000000202", "light-blue-oxford-shirt": "weekday-2000000211",
              "white-tee": "cos-2000000101", "navy-tee": "cos-2000000112", "grey-wool-trousers": "weekday-2000000205",
              "stone-chinos": "weekday-2000000213", "indigo-jeans": "weekday-2000000204",
              "white-leather-sneakers": "cos-2000000109", "dark-brown-derby-shoes": "cos-2000000108"},
    "first": ["581a7cf3f0d4", "a6bf7aecb862", "09f0d08f2a09", "78ee2f55e27c", "9a9c5f35099d", "6f1bd5fdfa38",
              "b2c732e947f7", "da349068a70a", "f03ce7fc8e64", "f249198edef7", "a9e7246636f8", "ec4c1c5729ce"],
    "labels": ["Everyday", "Smart casual", "Everyday", "Office", "Smart casual", "Everyday", "Everyday", "Smart casual",
               "Office", "Everyday", "Smart casual", "Smart casual"],
    "all": (84, "3d3664e58950e4739ee0f5ef2c3d4c5d53948796b5d7bd0b83da41b25857fbba"),
    # What the image service was told of each (sha256 of looks.prompt, its first 16 characters): the same words give
    # the same picture's name, so the pictures drawn and paid for are the ones shown.
    "described": ["2124f0f8b5c45a5e", "642451b6721e2248", "4c6d35ba327311cc", "72fe3f81cc7a53a2", "749a2632351605d7",
                  "453667619db426bd", "25321536d0ba388d", "0cbceb2ae8cac8a2", "68e334305421c8ce", "f865709500e0c9d3",
                  "8cd3b41a1a277281", "00f65d602edffa97"],
}
# On the demo's invented products (no list published).
ON_THE_DEMO = {
    "picks": {"navy-light-jacket": "mock-otto-navy-light-jacket-jacket-navy-0",
              "grey-merino-jumper": "mock-cos-grey-merino-jumper-knit-grey-0",
              "white-oxford-shirt": "mock-cos-white-oxford-shirt-shirt-white-0",
              "light-blue-oxford-shirt": "mock-cos-light-blue-oxford-shirt-shirt-light-blue-0",
              "white-tee": "mock-weekday-white-tee-tee-white-1", "navy-tee": "mock-weekday-navy-tee-tee-navy-2",
              "grey-wool-trousers": "mock-otto-grey-wool-trousers-trousers-grey-0",
              "stone-chinos": "mock-otto-stone-chinos-chinos-stone-0",
              "indigo-jeans": "mock-weekday-indigo-jeans-jeans-indigo-2",
              "white-leather-sneakers": "mock-weekday-white-leather-sneakers-sneakers-white-1",
              "dark-brown-derby-shoes": "mock-otto-dark-brown-derby-shoes-shoes-dark-brown-0"},
    "first": ["3a1d4fc07a4d", "6e50f1455662", "b13b7a978183", "ba33e4f4bdce", "2c18148ca520", "11eefb7e4de8",
              "83017110261d", "a3be571e04be", "2a1727904aa4", "edebfa990dee", "6eaa64b0c8bf", "306b23acba57"],
    "all": (84, "52bfd1be2dcfe8ff1ad7fbf07495db9c1721a540c9694246de1ddce22886be53"),
}
# The example's answers as the code before this round stored them: what it dresses for in one word.
STORED_BEFORE = {**{key: value for key, value in EXAMPLE.items()}, "use": "both", "budget": 600}


def the_example(test, expected: dict) -> list[str]:
    """Check the example wardrobe against what the code before this round made of it (`expected`). Returns the keys
    of the first 12 outfits a visitor sees."""
    with db.as_user(guests.example_id()):
        w = selection.build()
        test.assertEqual([(s["id"], s["name"], s["category"], s["colour"], s["keywords"], s["qty"])
                          for s in db.list_slots()], EXAMPLE_PLAN, "its plan")
        test.assertEqual({view.slot["id"]: view.chosen.id for view in w.slots}, expected["picks"], "its products")
        first = guests.first_outfits(w, 12)
        test.assertEqual([o.key for o, _ in first], expected["first"], "its first 12 outfits")
        every = outfits.all_outfits(w)
        test.assertEqual((len(every), hashlib.sha256("|".join(sorted(o.key for o in every)).encode()).hexdigest()),
                         expected["all"], "all its outfits")
        if "labels" in expected:
            test.assertEqual([o.label for o, _ in first], expected["labels"], "their titles")
        if "described" in expected:
            rules = looks.load_rules()
            who = person.current(rules["pictures"]["photos"])
            test.assertEqual([hashlib.sha256(looks.prompt(outfits.snapshot(o), rules, who).encode()).hexdigest()[:16]
                              for o, _ in first], expected["described"], "what its pictures were drawn from")
        return [o.key for o, _ in first]


class TheExampleWardrobeOnTheList(WithExampleClips):
    def test_its_plan_products_outfits_pictures_and_clips_stay_through_the_deploy(self):
        # Before the deploy: the example as the code before this round stored it ("both"), with the pictures and
        # clips the owner made of its first outfits.
        with db.as_user(guests.example_id()):
            db.set_setting("profile", STORED_BEFORE)
            self.assertEqual(profile_mod.load()["use"], ["everyday", "office"])
            # Each piece locked to its product, as on the live servers since 23 Nov (guests.lock_pieces): "Best for
            # budget" now keeps a plan within a budget that its options rated 70 or more do not fit (as 600 € does
            # not on this list: selection.lower_to_fit), which moves no locked piece.
            for slot_id, pick in ON_THE_LIST["picks"].items():
                db.update_slot(slot_id, locked=True, pick=pick)
        keys = the_example(self, ON_THE_LIST)
        files = self.pictures_for(keys)
        clips = {key: self.clip_for(key) for key in keys[:3]}
        shown = self.shown("/")
        self.assertEqual(shown, [(key, files[key]) for key in keys], "each with its picture, in this order")
        drawn = len(self.made)
        # The deploy: a restart with this round's code.
        self.app = create_app()
        self.visitor = self.app.test_client()
        with db.as_user(guests.example_id()):
            self.assertEqual(db.get_setting("profile"), STORED_BEFORE, "nothing of it is written at the deploy")
            self.assertEqual(profile_mod.load()["use"], ["everyday", "office"])
        self.assertEqual(the_example(self, ON_THE_LIST), keys)
        self.assertEqual(self.shown("/"), shown, "the same outfits, with the same pictures")
        self.assertEqual({key: self.board(key)["clip"] for key in clips}, clips, "and the same clips")
        page = self.page("/")
        for key, clip in clips.items():
            self.assertIn(f"/outfits/{key}/clip/{clip}", page)
        self.assertEqual(len(self.made), drawn, "nothing was made again")
        # Its filters are what they were: All, Everyday and Office.
        row = re.search(r'<div class="chips" role="group" aria-label="Which outfits">(.*?)</div>', page, re.S).group(1)
        self.assertEqual(re.findall(r'>([^<]+)</a>', row), ["All", "Everyday", "Office"])


class TheExampleWardrobeOnTheDemo(ProductionCase):
    def test_its_plan_products_and_outfits_are_those_of_before(self):
        self.assertEqual(guests.example_budget(), 600)
        with db.as_user(guests.example_id()):
            self.assertEqual(profile_mod.load()["use"], ["everyday", "office"])
        the_example(self, ON_THE_DEMO)
        # The demo's new products are hoodies and cargo trousers only: none is among its pieces' options.
        with db.as_user(guests.example_id()):
            stores = {c["store"] for c in catalog.load()["candidates"]}
        self.assertEqual(stores, {"cos", "weekday", "otto"})


if __name__ == "__main__":
    unittest.main()
