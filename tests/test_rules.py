"""The rules that decide things: parsing, scoring, sizes, the capsule proposal."""
import unittest

from wardrobe import capsule, colours, composition, mock, programmes, scoring, sizes
from wardrobe.paths import CONFIG_DIR
from wardrobe.profile import EXAMPLE


class Composition(unittest.TestCase):
    def test_german_percent_first(self):
        self.assertEqual(composition.parse("80 % Wolle, 20 % Polyamid"),
                         [("wool", 80.0), ("polyamide", 20.0)])

    def test_name_first_and_english(self):
        self.assertEqual(composition.parse("Polyester 64%, Viskose 34%, Elasthan 2%"),
                         [("polyester", 64.0), ("viscose", 34.0), ("elastane", 2.0)])
        self.assertEqual(composition.parse("100% organic cotton"), [("organic_cotton", 100.0)])

    def test_baumwolle_is_cotton_not_wool(self):
        self.assertEqual(composition.parse("100 % Baumwolle"), [("cotton", 100.0)])
        self.assertEqual(composition.parse("100 % Bio-Baumwolle"), [("organic_cotton", 100.0)])
        self.assertEqual(composition.parse("100 % Merinowolle"), [("merino", 100.0)])

    def test_only_the_main_fabric_counts(self):
        text = "Obermaterial: 80% Wolle, 20% Polyamid; Futter: 100% Polyester"
        self.assertEqual(composition.parse(text), [("wool", 80.0), ("polyamide", 20.0)])

    def test_unknown_and_empty(self):
        self.assertEqual(composition.parse("5 % Sonstige Fasern, 95 % Wolle"), [("wool", 95.0), ("other", 5.0)])
        self.assertEqual(composition.parse(""), [])
        self.assertEqual(composition.parse(None), [])

    def test_a_shoe_is_its_upper_not_its_tongue(self):
        # Zara's shoe labels, word for word: the upper ("Schnitt"), then the tongue ("Zunge") with its own 100%.
        self.assertEqual(composition.parse(ZARA_SHOE_LABELS["Leder-Turnie"]), [("leather", 100.0)])
        self.assertEqual(composition.parse(ZARA_SHOE_LABELS["Sneaker aus Leder im Retro-Stil"]),
                         [("leather", 82.0), ("polyurethane", 18.0)])
        self.assertEqual(composition.parse(ZARA_SHOE_LABELS["Retro-Leder-Sneaker"]), [("leather", 100.0)],
                         "the nylon tongue is not half the shoe")
        self.assertEqual(composition.describe(composition.parse(ZARA_SHOE_LABELS["Lederschuh mit Track-Sohle"])),
                         "100% leather", "never '200% leather'")
        self.assertEqual(composition.parse("Upper: 100% leather; Tongue: 100% polyester"), [("leather", 100.0)])
        self.assertEqual(composition.parse("Obermaterial: 100% Leder; Lasche: 100% Polyester"), [("leather", 100.0)])

    def test_no_mix_is_ever_over_100_percent(self):
        # Two parts of a garment the parser cannot tell apart, or a store's own rounding: scaled back to 100.
        self.assertEqual(composition.parse("Vorderteil: 100 % Baumwolle; Rückenteil: 100 % Polyester"),
                         [("cotton", 50.0), ("polyester", 50.0)])
        self.assertEqual(composition.parse("Außen: 70 % Wolle, 30 % Polyamid; Ärmel: 100 % Wolle"),
                         [("wool", 85.0), ("polyamide", 15.0)])
        self.assertEqual(composition.parse("51 % Baumwolle, 50 % Polyester"), [("cotton", 50.0), ("polyester", 50.0)])
        self.assertEqual(composition.parse("Oben: 60 % Wolle, 40 % Kaschmir; Unten: 55 % Wolle, 45 % Seide"),
                         [("wool", 58.0), ("silk", 22.0), ("cashmere", 20.0)])
        labels = [*ZARA_SHOE_LABELS.values(), "Vorderteil: 100 % Baumwolle; Rückenteil: 100 % Polyester",
                  "100 % Baumwolle; 100 % Baumwolle; 100 % Polyester", "33,3 % Wolle, 33,3 % Kaschmir, 33,4 % Seide",
                  "Polyester 64%, Viskose 34%, Elasthan 2%", "Obermaterial: 80% Wolle, 20% Polyamid; Futter: 100% Polyester"]
        for text in labels:
            self.assertLessEqual(sum(pct for _, pct in composition.parse(text)), 100, text)


# Zara's shoe labels as collected on 11 Nov 2026, by product name.
ZARA_SHOE_LABELS = {
    "Leder-Turnie": "Schnitt: 100% kuhleder; Zunge: 100% kuhleder; Futter: 75% polyester, 25% polyurethan; "
                    "Sohle: 100% polyurethan; Innensohle: 65% baumwolle, 35% polyester",
    "Sneaker aus Leder im Retro-Stil": "Schnitt: 82% kuhleder, 18% polyurethan; Zunge: 65% polyurethan, 35% kuhleder; "
                                       "Futter: 60% polyester, 40% polyurethan; Sohle: 100% sbs; Innensohle: 100% polyester",
    "Retro-Leder-Sneaker": "Schnitt: 100% kuhleder; Zunge: 100% polyamid; Futter: 60% baumwolle, 32% polyester, "
                           "8% polyurethan; Sohle: 100% sbs; Innensohle: 65% baumwolle, 35% polyester",
    "Kombinierter Retro-Turnschuh": "Schnitt: 70% polyurethan, 30% polyester; Zunge: 100% polyurethan; "
                                    "Futter: 86% polyamid, 14% elastan; Sohle: 100% kautschuk; "
                                    "Innensohle: 86% polyamid, 14% elastan",
    "Lederschuh mit Track-Sohle": "Schnitt: 100% kuhleder; Zunge: 100% kuhleder; Futter: 100% polyester; "
                                  "Sohle: 100% sbs; Innensohle: 100% polyurethan",
}


class Scoring(unittest.TestCase):
    rules = scoring.load_rules()

    def score(self, store, price, comp, category):
        return scoring.score({"store": store, "price": price, "composition_text": comp}, category, self.rules)

    def test_natural_beats_synthetic(self):
        merino = self.score("weekday", 49.95, "100 % Merinowolle", "knit")
        acrylic = self.score("weekday", 35.95, "45 % Polyacryl, 30 % Polyester, 25 % Wolle", "knit")
        self.assertGreater(merino.total, 80)
        self.assertLess(acrylic.total, 50)

    def test_brand_tier_depends_on_garment(self):
        same = dict(price=60, comp="100 % Baumwolle")
        self.assertGreater(self.score("weekday", category="jeans", **same).total,
                           self.score("cos", category="jeans", **same).total)
        self.assertGreater(self.score("cos", category="knit", **same).total,
                           self.score("weekday", category="knit", **same).total)

    def test_only_the_stores_customers_are_offered_are_rated(self):
        # A store without a partner programme (programmes.py) is not offered, so it is not rated either. The stores
        # Stilsmith has products from (the ones the collector reads, and the demo's: OTTO's basics since 18 Nov) are
        # each rated. A store whose products can only be pasted in by their links (Hirmer and the others of round 6)
        # is not rated yet, and the working says so instead of claiming a rating nobody gave.
        # (The shared list's first batch, collected for testing since 22 Nov 2026, is rated too: config/stores.toml.)
        from .test_programmes import BATCH_1
        self.assertEqual(sorted(self.rules["brand"]),
                         sorted(set(programmes.read_by_the_collector()) | set(mock.STORE_HOME) | set(BATCH_1)))
        self.assertLessEqual(set(self.rules["brand"]), set(programmes.offered()))
        self.assertNotIn("zara", self.rules["brand"])
        self.assertIn("hirmer", programmes.offered())
        self.assertEqual(scoring.brand_part("hirmer", "shirt", self.rules),
                         (50.0, ["Stilsmith has not rated Hirmer yet, so its brand counts as the middle, 50/100"]))

    def test_mostly_synthetic_penalty_is_explained(self):
        s = self.score("weekday", 35.95, "74 % Polyester, 24 % Viskose, 2 % Elasthan", "trousers")
        fabric = s.parts[0]
        self.assertTrue(any("mostly synthetic" in line for line in fabric.lines))
        # jackets are exempt: technical shells are legitimately synthetic
        j = self.score("weekday", 59.95, "100 % Polyamid", "jacket")
        self.assertFalse(any("mostly synthetic" in line for line in j.parts[0].lines))

    def test_price_sanity(self):
        fair, _ = scoring.price_part(25, "tee", self.rules)
        cheap, _ = scoring.price_part(3, "tee", self.rules)
        steep, _ = scoring.price_part(90, "tee", self.rules)
        between, _ = scoring.price_part(5, "tee", self.rules)
        self.assertEqual(fair, 100)
        self.assertEqual(cheap, 40)
        self.assertEqual(steep, 55)
        self.assertTrue(40 < between < 100)

    def test_the_working_is_said_in_plain_words(self):
        # A price below the usual range counts against an option, and the breakdown says why instead of calling it
        # "suspiciously cheap"; the brand part says that the rating is Stilsmith's own.
        def price_line(price):
            return scoring.price_part(price, "tee", self.rules)[1][0].replace("\u00a0", " ")   # "12 €" never splits

        self.assertEqual(price_line(25), "25 € is in the usual range for T-shirts (7 €–40 €)")
        self.assertNotIn(" €", scoring.price_part(25, "tee", self.rules)[1][0], "an amount and its € never split")
        self.assertEqual(price_line(5), "5 € is below the usual 7 €–40 € for T-shirts. Prices this low often mean "
                                        "lower quality, so this counts a little against it.")
        self.assertEqual(price_line(3), "3 € is far below the usual 7 €–40 € for T-shirts. Prices this low often mean "
                                        "lower quality, so this counts against it.")
        self.assertEqual(price_line(50), "50 € is above the usual 7 €–40 € for T-shirts, so this counts a little "
                                         "against it.")
        self.assertEqual(price_line(90), "90 € is far above the usual 7 €–40 € for T-shirts, so this counts against it.")
        self.assertEqual(scoring.brand_part("weekday", "knit", self.rules)[1], [
            f"Stilsmith rates Weekday {self.rules['brand']['weekday']['knit']}/100 for knitwear"])
        rated = self.score("weekday", 49.95, "100 % Merinowolle", "knit")
        self.assertEqual(rated.note, "Fabric counts most. The brand part is Stilsmith's own judgement of how well each "
                                     "store makes this kind of garment.")
        evenly = {**self.rules, "weights": {"fabric": 1, "brand": 1, "price": 1}}
        self.assertEqual(scoring.score({"store": "weekday", "price": 49.95}, "knit", evenly).note,
                         "The brand part is Stilsmith's own judgement of how well each store makes this kind of garment.",
                         "with every part weighing the same, none is said to count most")
        said = " ".join(line for part in rated.parts for line in part.lines)
        for word in ("suspicious", "fair band", "steep", "is rated"):
            self.assertNotIn(word, said)

    def test_parts_add_up_to_the_total(self):
        s = self.score("cos", 275, "80 % Wolle, 20 % Polyamid", "coat")
        self.assertAlmostEqual(sum(p.weight for p in s.parts), 1.0)
        self.assertEqual(s.total, int(sum(p.points for p in s.parts) + 0.5))

    def test_missing_composition_is_neutral_not_a_crash(self):
        s = self.score("cos", 89, None, "knit")
        self.assertIn("No composition", s.parts[0].lines[0])

    def test_a_shoe_is_scored_on_its_upper(self):
        whole_label = self.score("cos", 69.95, ZARA_SHOE_LABELS["Retro-Leder-Sneaker"], "sneakers")
        upper_only = self.score("cos", 69.95, "Schnitt: 100% kuhleder", "sneakers")
        self.assertEqual(whole_label.total, upper_only.total, "its nylon tongue does not pull the score down")
        self.assertEqual(whole_label.fabric_text, "100% leather")
        self.assertEqual(whole_label.parts[0].lines, upper_only.parts[0].lines, "'How it's rated' shows the upper only")


class Sizes(unittest.TestCase):
    charts = sizes.load_charts()
    me = {**EXAMPLE, "top_size": "M", "waist": 32, "length": 32, "shoe": "43"}

    def fits(self, label, store, category):
        return sizes.label_fits(label, self.me, store, category, self.charts)

    def test_same_waist_three_labels(self):
        self.assertTrue(self.fits("32/32", "weekday", "jeans"))
        self.assertTrue(self.fits("W32 L32", "weekday", "jeans"))
        self.assertTrue(self.fits("48", "cos", "trousers"))
        self.assertTrue(self.fits("EU 42 (US 32)", "zara", "trousers"))

    def test_near_misses(self):
        self.assertFalse(self.fits("32/34", "weekday", "jeans"))   # right waist, wrong length
        self.assertFalse(self.fits("42", "cos", "trousers"))       # 42 only means W32 at Zara
        self.assertFalse(self.fits("48", "zara", "trousers"))
        self.assertFalse(self.fits("L", "cos", "tee"))

    def test_tops_and_shoes(self):
        self.assertTrue(self.fits("M", "zara", "tee"))
        self.assertTrue(self.fits("48", "cos", "coat"))            # COS tailoring numbers
        self.assertTrue(self.fits("43", "cos", "sneakers"))
        self.assertFalse(self.fits("44", "cos", "sneakers"))

    def test_in_between_sizes_match_their_neighbours(self):
        half = {**self.me, "shoe": "42.5"}
        self.assertTrue(sizes.label_fits("42", half, "cos", "sneakers", self.charts))
        self.assertTrue(sizes.label_fits("43", half, "cos", "sneakers", self.charts))
        self.assertFalse(sizes.label_fits("44", half, "cos", "sneakers", self.charts))
        odd = {**self.me, "length": 33}
        self.assertTrue(sizes.label_fits("32/32", odd, "weekday", "jeans", self.charts))
        self.assertTrue(sizes.label_fits("32/34", odd, "weekday", "jeans", self.charts))
        self.assertFalse(sizes.label_fits("32/30", odd, "weekday", "jeans", self.charts))

    def test_stock_status(self):
        cand = {"store": "cos", "sizes_all": ["S", "M", "L"], "sizes_in_stock": ["S", "L"]}
        status = sizes.my_size(cand, self.me, "tee", self.charts)
        self.assertFalse(status.available)
        self.assertEqual(status.label, "M")
        cand["sizes_in_stock"] = ["M"]
        self.assertTrue(sizes.my_size(cand, self.me, "tee", self.charts).available)
        unknown = sizes.my_size({"store": "cos"}, self.me, "tee", self.charts)
        self.assertTrue(unknown.available)
        self.assertFalse(unknown.known)


class Colours(unittest.TestCase):
    def test_german_and_english_names(self):
        for text, key in [("Marineblau", "navy"), ("Cremeweiß", "ecru"), ("Hellgrau", "light-grey"),
                          ("Khaki", "olive"), ("dark brown", "dark-brown"), ("Smaragdgrün", "green"),
                          ("Steingrau", "stone"), ("Graumeliert", "grey"),
                          # the stores' own vocabulary
                          ("CHARCOAL MÉLANGE", "charcoal"), ("Dunkles Marineblau", "navy"), ("Graphit", "charcoal"),
                          ("OFF-WHITE", "ecru"), ("Taupegrau", "taupe"), ("Bitter Chocolate", "dark-brown"),
                          ("Midnight", "navy"), ("Hellgrau meliert", "light-grey")]:
            self.assertEqual(colours.find(text), key, text)

    def test_no_false_positive_inside_words(self):
        self.assertIsNone(colours.find("tailored trousers"))      # contains "red"
        self.assertIsNone(colours.find("standard fit"))           # contains "tan"

    def test_parse_list(self):
        keys, unknown = colours.parse_list("navy, grey and white; glitter")
        self.assertEqual(keys, ["navy", "grey", "white"])
        self.assertEqual(unknown, ["glitter"])

    def test_the_name_on_a_swatch_is_readable(self):
        # When a product photo is missing, its colour swatch shows with the colour's name written on it.
        # The name must read at 4.5:1 (WCAG AA) on every swatch: Stilsmith's own colours, the middle greys
        # and browns of real products (white on '#7c8286' was 3.9:1), and every colour in between.
        self.assertAlmostEqual(colours.contrast("#000000", "#ffffff"), 21.0)
        self.assertAlmostEqual(colours.contrast("#ffffff", "#ffffff"), 1.0)
        steps = range(0, 256, 15)
        swatches = [c.hex for c in colours.COLOURS.values()] + ["#7c8286", "#8b7560", "#767676", "#777777"]
        swatches += ["#{:02x}{:02x}{:02x}".format(r, g, b) for r in steps for g in steps for b in steps]
        for hex_ in swatches:
            self.assertGreaterEqual(colours.contrast(hex_, colours.ink_on(hex_)), 4.5, hex_)
        self.assertEqual(colours.ink_on("#f5f4f0"), "#1b1b1a")     # white tee: Stilsmith's ink
        self.assertEqual(colours.ink_on("#1f2a44"), "#ffffff")     # navy: white


class Capsule(unittest.TestCase):
    def propose(self, **changes):
        """The plan the example's answers propose, with these changes. At 1,500 € unless a budget is given: the full
        plan (24 pieces), where every rule of the lists shows. (A new account starts at 300 €: 9 pieces.)"""
        slots, unmatched = capsule.propose({**EXAMPLE, "budget": 1500, **changes})
        return slots, unmatched

    # Each kind's pieces in the example's colours (navy, grey, white, olive), most needed first (capsule.RANKED). The
    # first three are a top, trousers and shoes.
    EVERYDAY = ["white-tee", "indigo-jeans", "white-leather-sneakers", "navy-tee", "stone-chinos", "grey-merino-jumper",
                "navy-light-jacket", "olive-overshirt", "white-oxford-shirt", "grey-tee", "navy-merino-jumper",
                "charcoal-wool-coat", "white-long-sleeve-tee", "black-jeans", "dark-brown-chelsea-boots",
                "light-blue-oxford-shirt", "ecru-cardigan", "navy-knitted-polo"]
    OFFICE = ["white-oxford-shirt", "grey-wool-trousers", "dark-brown-derby-shoes", "grey-merino-jumper",
              "stone-chinos", "light-blue-oxford-shirt", "navy-wool-blazer", "charcoal-tailored-trousers", "navy-merino-jumper",
              "charcoal-wool-coat", "ecru-cardigan", "navy-knitted-polo", "white-tee", "white-leather-sneakers",
              "navy-tailored-trousers"]
    # Both: everyday's first three, office's first three, then each one's 4th, 5th … piece, a shared piece once.
    BOTH = ["white-tee", "indigo-jeans", "white-leather-sneakers", "white-oxford-shirt", "grey-wool-trousers",
            "dark-brown-derby-shoes", "navy-tee", "grey-merino-jumper", "stone-chinos", "light-blue-oxford-shirt",
            "navy-light-jacket", "navy-wool-blazer", "olive-overshirt", "charcoal-tailored-trousers",
            "navy-merino-jumper", "grey-tee", "charcoal-wool-coat", "ecru-cardigan", "navy-knitted-polo",
            "white-long-sleeve-tee", "black-jeans", "dark-brown-chelsea-boots", "navy-tailored-trousers"]

    def test_the_budget_sizes_the_plan(self):
        # How many of each list a budget buys (config/budget.toml), and how many pieces that is: a white tee ×2 is
        # two. The money for pieces is the budget up to 200 €, and half of what is above it: 150, 250, 400, 600 and
        # 850 €.
        plans = {
            "everyday": {150: (self.EVERYDAY[:6], 7), 300: (self.EVERYDAY[:8], 9), 600: (self.EVERYDAY[:11], 12),
                         1000: (self.EVERYDAY, 19), 1500: (self.EVERYDAY, 19)},
            "office": {150: (self.OFFICE[:4], 4), 300: (self.OFFICE[:6], 6), 600: (self.OFFICE[:9], 9),
                       1000: (self.OFFICE, 15), 1500: (self.OFFICE, 15)},
            "both": {150: (self.EVERYDAY[:6], 7), 300: (self.BOTH[:8], 9), 600: (self.BOTH[:11], 12),
                     1000: (self.BOTH[:16], 17), 1500: (self.BOTH, 24)},
        }
        for use, by_budget in plans.items():
            for budget, (ids, pieces) in by_budget.items():
                with self.subTest(use=use, budget=budget):
                    slots, _ = self.propose(use=use, budget=budget)
                    self.assertEqual(sorted(s["id"] for s in slots), sorted(ids))
                    self.assertEqual(sum(s["qty"] for s in slots), pieces)
        self.assertEqual([capsule.money_for_pieces(b) for b in (150, 300, 600, 1000, 1500)], [150, 250, 400, 600, 850])

    def test_both_is_everyday_then_office_which_joins_when_its_first_three_fit(self):
        # Office's first three (an oxford shirt, trousers, derby shoes) cost 120 € on top of everyday's 83 €: they
        # fit from a budget of 206 €. Where office joins, its first three go ahead of everyday's further pieces.
        self.assertEqual(capsule.kinds_in({**EXAMPLE, "use": "both", "budget": 205}), ["everyday"])
        self.assertEqual(capsule.kinds_in({**EXAMPLE, "use": "both", "budget": 210}), ["everyday", "office"])
        self.assertEqual(capsule.kinds_in({**EXAMPLE, "use": "office", "budget": 150}), ["office"])
        before, _ = self.propose(budget=205)
        after, _ = self.propose(budget=210)
        self.assertEqual(sorted(s["id"] for s in after), sorted(self.BOTH[:6]))
        self.assertEqual((sum(s["qty"] for s in before), sum(s["qty"] for s in after)), (8, 7))

    def test_ids_come_from_the_full_names_and_under_450_euros_the_names_leave_out_the_fabric(self):
        small = {s["id"]: s["name"] for s in self.propose(budget=300)[0]}
        self.assertEqual((small["grey-merino-jumper"], small["white-leather-sneakers"], small["grey-wool-trousers"]),
                         ("Grey jumper", "White sneakers", "Grey trousers"))
        full = {s["id"]: s["name"] for s in self.propose(budget=450)[0]}
        self.assertEqual((full["grey-merino-jumper"], full["white-leather-sneakers"], full["grey-wool-trousers"]),
                         ("Grey merino jumper", "White leather sneakers", "Grey wool trousers"))
        # The words its products are matched by leave it out too (collect/matching.py ranks by them), so that the jumper
        # a small budget buys is not offered merino jumpers first; from 450 € they are the full ones again.
        small = {s["id"]: s["keywords"] for s in self.propose(budget=300)[0]}
        self.assertEqual((small["grey-merino-jumper"], small["white-leather-sneakers"], small["grey-wool-trousers"],
                          small["dark-brown-derby-shoes"]), ("crew-neck", "", "", "derby"))
        full = {s["id"]: s["keywords"] for s in self.propose(budget=450)[0]}
        self.assertEqual((full["grey-merino-jumper"], full["white-leather-sneakers"], full["grey-wool-trousers"],
                          full["dark-brown-derby-shoes"]), ("merino crew-neck", "leather", "wool", "leather derby"))
        for budget in range(50, 450, 5):
            for slot in self.propose(budget=budget)[0]:
                self.assertFalse({"merino", "wool", "leather"} & set(slot["keywords"].lower().split()), (budget, slot))

    def test_every_5_euros_kinds_never_drop_and_the_plan_only_grows_while_the_same_kinds_are_in(self):
        # Every budget from 50 € to 2,000 €, for each use, with and without shoes and outerwear. A piece keeps its id
        # at every budget (and its id names one garment in one colour); no plan has a name with merino, wool or
        # leather under 450 €, nor more than 24 pieces. At the budget where a kind joins the plan can be smaller than
        # just under it (its first three pieces go ahead of the other kind's further pieces): never otherwise.
        ids: dict[str, tuple[str, str]] = {}
        for use in ("everyday", "office", "both"):
            for shoes in (True, False):
                for outerwear in (True, False):
                    before = None
                    for budget in range(50, 2001, 5):
                        answers = {**EXAMPLE, "use": use, "budget": budget, "shoes": shoes, "outerwear": outerwear}
                        where = f"{use}, {budget} €, shoes {shoes}, outerwear {outerwear}"
                        kinds, slots = capsule.kinds_in(answers), capsule.propose(answers)[0]
                        plan = {s["id"] for s in slots}
                        self.assertEqual(len(plan), len(slots), where)
                        self.assertLessEqual(sum(s["qty"] for s in slots), 24, where)
                        for s in slots:
                            self.assertEqual(ids.setdefault(s["id"], (s["category"], s["colour"])),
                                             (s["category"], s["colour"]), where)
                            if budget < 450:
                                self.assertNotRegex(s["name"].lower(), r"merino|wool|leather", where)
                        if before is not None:
                            self.assertLessEqual(set(before[0]), set(kinds), f"a kind dropped: {where}")
                            if before[0] == kinds:
                                self.assertLessEqual(before[1], plan, f"the plan lost a piece: {where}")
                        before = (kinds, plan)

    def test_the_smallest_plan_is_one_outfit_of_the_first_kind(self):
        # Below the price of a kind's first three pieces they are the plan all the same: fewer would make no outfit,
        # and "Best for budget" then says the budget is too small.
        tiny, _ = self.propose(budget=20)
        self.assertEqual(sorted(s["id"] for s in tiny), sorted(self.EVERYDAY[:3]))
        office, _ = self.propose(use="office", budget=20)
        self.assertEqual(sorted(s["id"] for s in office), sorted(self.OFFICE[:3]))

    def test_without_shoes_and_outerwear_the_money_goes_to_the_other_pieces(self):
        slots, _ = self.propose(shoes=False, outerwear=False)
        self.assertFalse({s["category"] for s in slots} & {"coat", "jacket", "sneakers", "shoes", "boots"})
        self.assertEqual(sum(s["qty"] for s in slots), 19, "every other piece of both lists, at 1,500 €")
        # A kind's first three are then a top and trousers.
        tiny, _ = self.propose(budget=20, shoes=False)
        self.assertEqual(sorted(s["id"] for s in tiny), ["indigo-jeans", "white-tee"])
        with_shoes = {s["id"] for s in self.propose(budget=300)[0]}
        without = {s["id"] for s in self.propose(budget=300, shoes=False)[0]}
        self.assertLessEqual(with_shoes - {"white-leather-sneakers", "dark-brown-derby-shoes"}, without)
        self.assertGreater(len(without), len(with_shoes - {"white-leather-sneakers", "dark-brown-derby-shoes"}))

    def test_the_usual_prices_say_which_were_read_and_which_are_estimates(self):
        # Only the tee's usual price was read on shops' pages; every other one is an estimate, and no source is
        # named for an estimate.
        text = (CONFIG_DIR / "budget.toml").read_text(encoding="utf-8")
        section = text.split("[usual_price]", 1)[1]
        lines = {line.split("=")[0].strip(): line for line in section.splitlines() if "=" in line}
        self.assertEqual(set(lines), {row[0] for rows in capsule.RANKED.values() for row in rows})
        for garment, line in lines.items():
            with self.subTest(garment):
                if garment == "tee":
                    self.assertIn("read on 18 Nov 2026", line)
                else:
                    self.assertIn("# estimate", line)
                    self.assertNotRegex(line, r"read|\.com|\.de\b|www|http|zalando|C&A|Pull&Bear")

    def test_trousers_and_shoes_stay_neutral(self):
        slots, _ = self.propose(liked=["navy", "grey", "white", "olive", "burgundy"])
        for s in slots:
            if s["category"] in ("trousers", "chinos", "jeans", "sneakers", "shoes", "boots"):
                self.assertTrue(colours.get(s["colour"]).neutral, s["name"])
        self.assertIn("olive", {s["colour"] for s in slots})      # the accent is used somewhere

    def test_refused_colours_never_appear(self):
        slots, _ = self.propose(liked=["black", "white"], refused=["navy", "grey", "green"])
        used = {s["colour"] for s in slots}
        self.assertFalse(used & {"navy", "grey", "light-grey", "charcoal", "olive", "green"})

    def test_classics_are_not_overridden_by_liked_colours(self):
        slots, _ = self.propose()
        jeans = [s["colour"] for s in slots if s["category"] == "jeans"]
        self.assertEqual(jeans, ["indigo", "black"])              # liking grey must not make grey jeans
        self.assertEqual([s["colour"] for s in slots if s["category"] == "chinos"], ["stone"])

    def test_built_around_what_is_owned(self):
        slots, unmatched = self.propose(owned="white leather sneakers\nburgundy overshirt\nmy lucky hat")
        sneakers = next(s for s in slots if s["category"] == "sneakers")
        overshirt = next(s for s in slots if s["category"] == "overshirt")
        self.assertTrue(sneakers["owned"])
        self.assertTrue(overshirt["owned"])
        self.assertEqual(overshirt["colour"], "burgundy")         # the slot took the owned colour
        self.assertEqual(unmatched, ["my lucky hat"])

    def test_garment_words(self):
        for text, category in [("navy knitted polo", "polo"), ("a white t-shirt", "tee"),
                               ("oxford shirt", "shirt"), ("sport coat", "blazer"),
                               ("denim jacket", "jacket"), ("chelsea boots", "boots")]:
            self.assertEqual(capsule.detect_garment(text), category, text)


if __name__ == "__main__":
    unittest.main()
