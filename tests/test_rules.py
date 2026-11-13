"""The rules that decide things: parsing, scoring, sizes, the capsule proposal."""
import unittest

from wardrobe import capsule, colours, composition, programmes, scoring, sizes
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
        # A store without a partner programme (programmes.py) is not offered, so it is not rated either.
        self.assertEqual(sorted(self.rules["brand"]), sorted(programmes.offered()))
        self.assertNotIn("zara", self.rules["brand"])

    def test_mostly_synthetic_penalty_is_explained(self):
        s = self.score("weekday", 35.95, "74 % Polyester, 24 % Viskose, 2 % Elasthan", "trousers")
        fabric = s.parts[0]
        self.assertTrue(any("mostly synthetic" in line for line in fabric.lines))
        # jackets are exempt: technical shells are legitimately synthetic
        j = self.score("weekday", 59.95, "100 % Polyamid", "jacket")
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

    def test_the_working_is_said_in_plain_words(self):
        # A price below the usual range counts against an option, and the breakdown says why instead of calling it
        # "suspiciously cheap"; the brand part says that the rating is Stilsmith's own.
        def price_line(price):
            return scoring.price_part(price, "tee", self.rules)[1][0].replace("\u00a0", " ")   # "12 €" never splits

        self.assertEqual(price_line(25), "25 € is in the usual range for T-shirts (12 €–40 €)")
        self.assertNotIn(" €", scoring.price_part(25, "tee", self.rules)[1][0], "an amount and its € never split")
        self.assertEqual(price_line(10), "10 € is below the usual 12 €–40 € for T-shirts. Prices this low often mean "
                                         "lower quality, so this counts a little against it.")
        self.assertEqual(price_line(5), "5 € is far below the usual 12 €–40 € for T-shirts. Prices this low often mean "
                                        "lower quality, so this counts against it.")
        self.assertEqual(price_line(50), "50 € is above the usual 12 €–40 € for T-shirts, so this counts a little "
                                         "against it.")
        self.assertEqual(price_line(90), "90 € is far above the usual 12 €–40 € for T-shirts, so this counts against it.")
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
