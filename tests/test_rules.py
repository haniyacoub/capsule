"""The rules that decide things: parsing, scoring, sizes, the capsule proposal."""
import unittest

from wardrobe import capsule, colours, composition, scoring, sizes
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


class Scoring(unittest.TestCase):
    rules = scoring.load_rules()

    def score(self, store, price, comp, category):
        return scoring.score({"store": store, "price": price, "composition_text": comp}, category, self.rules)

    def test_natural_beats_synthetic(self):
        merino = self.score("zara", 49.95, "100 % Merinowolle", "knit")
        acrylic = self.score("zara", 35.95, "45 % Polyacryl, 30 % Polyester, 25 % Wolle", "knit")
        self.assertGreater(merino.total, 80)
        self.assertLess(acrylic.total, 50)

    def test_brand_tier_depends_on_garment(self):
        same = dict(price=60, comp="100 % Baumwolle")
        self.assertGreater(self.score("weekday", category="jeans", **same).total,
                           self.score("cos", category="jeans", **same).total)
        self.assertGreater(self.score("cos", category="knit", **same).total,
                           self.score("weekday", category="knit", **same).total)

    def test_mostly_synthetic_penalty_is_explained(self):
        s = self.score("zara", 35.95, "74 % Polyester, 24 % Viskose, 2 % Elasthan", "trousers")
        fabric = s.parts[0]
        self.assertTrue(any("mostly synthetic" in line for line in fabric.lines))
        # jackets are exempt: technical shells are legitimately synthetic
        j = self.score("zara", 59.95, "100 % Polyamid", "jacket")
        self.assertFalse(any("mostly synthetic" in line for line in j.parts[0].lines))

    def test_price_sanity(self):
        fair, _ = scoring.price_part(25, "tee", self.rules)
        cheap, _ = scoring.price_part(5, "tee", self.rules)
        steep, _ = scoring.price_part(90, "tee", self.rules)
        between, _ = scoring.price_part(10, "tee", self.rules)
        self.assertEqual(fair, 100)
        self.assertEqual(cheap, 40)
        self.assertEqual(steep, 55)
        self.assertTrue(40 < between < 100)

    def test_parts_add_up_to_the_total(self):
        s = self.score("cos", 275, "80 % Wolle, 20 % Polyamid", "coat")
        self.assertAlmostEqual(sum(p.weight for p in s.parts), 1.0)
        self.assertEqual(s.total, int(sum(p.points for p in s.parts) + 0.5))

    def test_missing_composition_is_neutral_not_a_crash(self):
        s = self.score("cos", 89, None, "knit")
        self.assertIn("No composition", s.parts[0].lines[0])


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


class Capsule(unittest.TestCase):
    def propose(self, **changes):
        slots, unmatched = capsule.propose({**EXAMPLE, **changes})
        return slots, unmatched

    def test_size_of_the_proposal(self):
        for use in ("everyday", "office", "both"):
            slots, _ = self.propose(use=use)
            self.assertTrue(15 <= len(slots) <= 20, f"{use}: {len(slots)} slots")
            self.assertEqual(len({s["id"] for s in slots}), len(slots), "ids must be unique")

    def test_still_enough_slots_without_shoes_and_outerwear(self):
        slots, _ = self.propose(shoes=False, outerwear=False)
        self.assertGreaterEqual(len(slots), 15)
        self.assertFalse({s["category"] for s in slots} & {"coat", "jacket", "sneakers", "shoes", "boots"})

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
        by_cat = {s["category"]: s["colour"] for s in slots}
        self.assertEqual(by_cat["jeans"], "indigo")               # liking grey must not make grey jeans
        self.assertEqual(by_cat["chinos"], "stone")

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
