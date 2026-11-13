"""Sizes told truthfully, and only pieces in your size picked.

The product list of 11 Nov had sizes for Weekday (26 of 26 products) and Zara (90 of 90), and none for COS (0 of 60):
COS's list pages show no sizes and its product pages were never opened. So for a COS product nobody knows whether
your size is in stock. The promises:

  * that is said as it is, with the store's name: "Sizes not checked at COS: look on its page before you buy";
  * the automatic pick takes a product known to be in stock in your size before one whose sizes were not checked,
    at every price level and for the best your budget buys, and never one known to be sold out in your size or not
    made in it (those stay on the piece's page, marked, to choose by hand);
  * a piece's page counts only what is known: "8 options · 1 in your size · 6 with sizes not checked".

The products below have the shapes of 11 Nov (COS without sizes, Weekday and Zara with them); the store's
catalogue itself stays whole, as every customer shares it: what is filtered is each customer's pick.
"""
import html
import re
import unittest
from dataclasses import replace

from wardrobe import catalog, scoring, selection, sizecheck, sizes
from wardrobe import profile as profile_mod

from .test_app import AppCase
from .test_production import words as page_words

CHARTS = sizes.load_charts()
RULES = scoring.load_rules()
ME = {**profile_mod.EXAMPLE}                     # tops M, W32 L32, shoes 43
LEVELS = list(selection.POSITION)                # cheapest … top
TEE = {"id": "white-tee", "name": "White tee", "category": "tee", "colour": "white"}
ALPHA = ["XS", "S", "M", "L", "XL"]


def product(store: str, number: int, price: float, sizes_all: list[str], in_stock: list[str]) -> dict:
    """A product as the collector stored it on 11 Nov."""
    return {"id": f"{store}-{number}", "store": store, "name": f"T-Shirt {number}", "price": price,
            "price_before": None, "currency": "EUR", "colour": "Weiß", "colour_hex": None,
            "composition_text": "100 % Baumwolle" if store == "zara" else "", "fit": "regular", "description": "",
            "sizes_all": sizes_all, "sizes_in_stock": in_stock, "url": f"https://example.com/{store}/{number}",
            "image_url": "", "source": "collected", "collected_at": "2026-11-11T16:59:24+01:00", "category": "tee"}


def cos(number: int, price: float) -> dict:
    return product("cos", number, price, [], [])                     # COS: no sizes on its list pages


def weekday(number: int, price: float, in_stock: list[str] | None = None, sizes_all: list[str] | None = None) -> dict:
    return product("weekday", number, price, sizes_all or ALPHA, ALPHA if in_stock is None else in_stock)


def zara(number: int, price: float, in_stock: list[str] | None = None) -> dict:
    return product("zara", number, price, ["S", "M", "L", "XL"], ["S", "M", "L", "XL"] if in_stock is None else in_stock)


def option(raw: dict, quality: int = 80, profile: dict | None = None) -> selection.Cand:
    """One option for the white tee, its quality set to `quality` so the tests say what they mean."""
    cand = selection._cand(raw, TEE, profile or ME, RULES, CHARTS)
    return replace(cand, score=replace(cand.score, total=quality))


class SaidTruthfully(unittest.TestCase):
    def test_a_store_that_gave_no_sizes_is_named_and_nothing_is_claimed(self):
        status = sizes.my_size(cos(1, 25), ME, "tee", CHARTS)
        self.assertFalse(status.known)
        self.assertEqual(status.rank, sizes.NOT_CHECKED)
        self.assertEqual(status.text, "Sizes not checked at COS: look on its page before you buy")
        note = sizecheck.check(cos(1, 25), status, ME, "tee", CHARTS).notes
        self.assertEqual(note, ["Sizes not checked at COS: look on its page before you buy."])
        for words in (status.text, *note):
            self.assertNotIn("gave no", words, "the store page was never opened: it did not 'give no sizes'")

    def test_known_sizes_keep_their_words(self):
        self.assertEqual(sizes.my_size(weekday(1, 20), ME, "tee", CHARTS).text, "M in stock")
        self.assertEqual(sizes.my_size(weekday(1, 20), ME, "tee", CHARTS).rank, sizes.IN_YOUR_SIZE)
        sold_out = sizes.my_size(weekday(1, 20, in_stock=["S", "L"]), ME, "tee", CHARTS)
        self.assertEqual((sold_out.text, sold_out.rank), ("M sold out", sizes.NOT_IN_YOUR_SIZE))
        not_made = sizes.my_size(weekday(1, 20, sizes_all=["XS", "S"], in_stock=["XS", "S"]), ME, "tee", CHARTS)
        self.assertEqual((not_made.text, not_made.rank), ("Not made in your size", sizes.NOT_IN_YOUR_SIZE))
        self.assertEqual(sizes.my_size(zara(1, 20), ME, "tee", CHARTS).rank, sizes.IN_YOUR_SIZE)

    def test_a_product_without_a_store_still_says_where_to_look(self):
        self.assertEqual(sizes.not_checked(""), "Sizes not checked: look on the store's page before you buy")


class PickedInYourSize(unittest.TestCase):
    def test_in_your_size_is_picked_before_sizes_not_checked_at_every_level(self):
        # COS is cheaper and dearer than the Weekday tees: whichever level, a tee known to be in your size is taken.
        cands = [option(cos(1, 15)), option(weekday(2, 25)), option(weekday(3, 30)), option(cos(4, 59))]
        for level in LEVELS:
            pick, note, warn = selection.choose(cands, level, 70)
            self.assertEqual(pick.data["store"], "weekday", level)
            self.assertEqual((note, warn), (None, False), level)
        self.assertEqual(selection.choose(cands, "cheapest", 70)[0].id, "weekday-2")
        self.assertEqual(selection.choose(cands, "top", 70)[0].id, "weekday-3")

    def test_sizes_not_checked_are_picked_when_nothing_is_known_to_be_in_your_size(self):
        sold_out = option(weekday(2, 9, in_stock=["S", "L"]))
        not_made = option(weekday(3, 10, sizes_all=["XS", "S"], in_stock=["XS", "S"]))
        cands = [sold_out, not_made, option(cos(1, 25)), option(cos(4, 35))]
        for level in LEVELS:
            pick = selection.choose(cands, level, 70)[0]
            self.assertEqual(pick.data["store"], "cos", level)
        self.assertEqual(selection.choose(cands, "cheapest", 70)[0].id, "cos-1")
        self.assertEqual(selection.choose(cands, "top", 70)[0].id, "cos-4")

    def test_sold_out_or_not_made_in_your_size_is_never_picked_automatically(self):
        sold_out = option(weekday(2, 9, in_stock=["S", "L"]), quality=99)
        not_made = option(weekday(3, 10, sizes_all=["XS", "S"], in_stock=["XS", "S"]), quality=99)
        for others in ([], [option(cos(1, 25), quality=40)], [option(zara(5, 30), quality=40)]):
            cands = [sold_out, not_made, *others]
            for level in LEVELS:
                for threshold in (0, 70, 100):
                    pick = selection.choose(cands, level, threshold)[0]
                    self.assertNotIn(pick and pick.id, (sold_out.id, not_made.id), (level, threshold, others))
        self.assertEqual(selection.choose([sold_out, not_made], "cheapest", 0), (None, "Nothing in stock in your size", True))

    def test_the_minimum_quality_comes_first_then_your_size(self):
        # The customer's minimum quality is his own choice: a tee in your size that falls short of it is not taken
        # over one that reaches it whose sizes were not checked. Among those that reach it, your size comes first.
        short = option(weekday(2, 20), quality=60)
        reaches = option(cos(1, 30), quality=75)
        self.assertEqual(selection.choose([short, reaches], "cheapest", 70)[0].id, reaches.id)
        self.assertEqual(selection.choose([short, reaches], "cheapest", 50)[0].id, short.id)
        # Nothing reaches the minimum: the best in your size, said so, before a better one whose sizes are unknown.
        pick, note, warn = selection.choose([short, option(cos(1, 30), quality=65)], "cheapest", 70)
        self.assertEqual((pick.id, note, warn), (short.id, "Nothing reaches 70 — this is the best in your size", True))
        pick, note, warn = selection.choose([option(cos(1, 30), quality=65), option(cos(4, 20), quality=50)], "top", 70)
        self.assertEqual((pick.id, note), ("cos-1", "Nothing reaches 70 — this is the best available"))

    def test_best_for_budget_moves_among_those_in_your_size_first(self):
        # A tee in your size is dearer than one whose sizes were not checked: best for budget, like every price
        # level, still takes the one in your size, however much budget is left.
        w = selection.Wardrobe(slots=[], mode="budget", threshold=70, budget=1000, source="collected", collected="")
        view = selection.SlotView(slot={**TEE, "qty": 1}, garment=selection.GARMENTS["tee"],
                                  colour=selection.colours.get("white"),
                                  cands=[option(cos(1, 15), quality=90), option(weekday(2, 25), quality=72),
                                         option(weekday(3, 9, in_stock=["S"]), quality=99)])
        w.slots.append(view)
        picks, fits, total = selection._fit(w)
        self.assertEqual(picks["white-tee"].id, "weekday-2")
        self.assertTrue(fits)
        self.assertEqual(total, 25)


class AWardrobeInTheShapesOf11Nov(AppCase):
    """The demo wardrobe with its COS products stripped of their sizes, as COS's were on 11 Nov."""

    def setUp(self):
        super().setUp()
        selection.build()                         # the first run builds the plan and the demo catalogue
        catalog.update(lambda cat: [c.update(sizes_all=[], sizes_in_stock=[]) for c in cat["candidates"]
                                    if c["store"] == "cos"])

    def assert_picked_in_your_size(self, w: selection.Wardrobe, where: str) -> int:
        """Every automatic pick is in your size when one in your size reaches the minimum quality, and never sold
        out in your size or not made in it. Returns how many picks had sizes not checked."""
        not_checked = 0
        for view in w.slots:
            if view.state != "auto" or view.chosen is None:
                continue
            name = f"{where}: {view.slot['name']}"
            self.assertNotEqual(view.chosen.size.rank, sizes.NOT_IN_YOUR_SIZE, name)
            known = [c for c in view.cands if c.size.rank == sizes.IN_YOUR_SIZE and c.price > 0
                     and c.score.total >= w.threshold]
            if known:
                self.assertEqual(view.chosen.size.rank, sizes.IN_YOUR_SIZE, name)
            not_checked += view.chosen.size.rank == sizes.NOT_CHECKED
        return not_checked

    def check_every_level(self, who: str) -> None:
        unchecked_options = 0
        for threshold in (0, 70):
            for level in [*LEVELS, "budget"]:
                self.set_mode(level, threshold)
                w = selection.build()
                self.assert_picked_in_your_size(w, f"{who}, {level}, minimum {threshold}")
                # The total the budget bar shows is the level's own total, to the cent.
                self.assertEqual(w.total, w.levels[level], f"{who}, {level}, minimum {threshold}")
                unchecked_options = sum(v.n_not_checked for v in w.slots)
        self.assertGreater(unchecked_options, 0, "the demo has COS options, now without sizes")

    def test_on_the_example_sizes(self):
        self.assertTrue(profile_mod.sizes_unconfirmed(profile_mod.load()))
        self.check_every_level("example sizes")

    def test_on_his_own_sizes(self):
        profile_mod.save({**profile_mod.load(), "example": False, "top_size": "L", "waist": 30, "length": 32,
                          "shoe": "44"})
        self.check_every_level("his own sizes")

    def test_a_pieces_page_counts_only_what_is_known(self):
        w = selection.build()
        view = next(v for v in w.slots if v.n_not_checked and v.n_in_your_size)
        said = html.unescape(page_words(self.client.get(f"/slot/{view.slot['id']}").data.decode()))
        n = len(view.cands)
        self.assertIn(f"{n} options · {view.n_in_your_size} in your size · {view.n_not_checked} with sizes not checked",
                      said)
        self.assertLess(view.n_in_your_size, view.n_available, "COS's options are no longer counted as in your size")
        # Listed in your size first, then sizes not checked, then sold out or not made in your size; by price within.
        ranks = [(c.size.rank, c.price) for c in view.cands]
        self.assertEqual(ranks, sorted(ranks))
        by_quality = self.client.get(f"/slot/{view.slot['id']}?sort=score").data.decode()
        order = re.findall(r'id="cand-([^"]+)"', by_quality)
        ranks = {c.id: c.size.rank for c in view.cands}
        self.assertEqual([ranks[i] for i in order], sorted(ranks[i] for i in order))
        # Each COS option says so with the store's name, once.
        cos_options = [c for c in view.cands if c.data["store"] == "cos"]
        self.assertEqual(said.count("Sizes not checked at COS: look on its page before you buy."), len(cos_options))
        # No shoe in a 49 at Weekday: none of its options is in your size, and that is said.
        profile_mod.save({**profile_mod.load(), "shoe": "49"})
        shoes = next(v for v in selection.build().slots if v.garment.key == "sneakers")
        said = html.unescape(page_words(self.client.get(f"/slot/{shoes.slot['id']}").data.decode()))
        self.assertEqual(shoes.n_in_your_size, 0)
        self.assertIn(f"{len(shoes.cands)} options · 0 in your size · {shoes.n_not_checked} with sizes not checked",
                      said)

    def test_the_picked_piece_says_in_your_size_only_when_it_is(self):
        self.set_mode("top", 70)
        w = selection.build()
        known = next(v for v in w.slots if v.state == "auto" and v.chosen and v.chosen.size.known and v.n_not_checked)
        said = html.unescape(page_words(self.client.get(f"/slot/{known.slot['id']}").data.decode()))
        self.assertIn("Picked for you: the top option in your size rated 70 or more.", said)
        # A piece whose every option is at COS: its pick is not said to be in your size.
        sid = known.slot["id"]
        catalog.update(lambda cat: [c.update(sizes_all=[], sizes_in_stock=[]) for c in cat["candidates"]
                                    if c["slot_id"] == sid])
        said = html.unescape(page_words(self.client.get(f"/slot/{sid}").data.decode()))
        self.assertIn("Picked for you: the top option rated 70 or more.", said)
        self.assertNotIn("in your size rated", said)
        n = len(known.cands)
        self.assertIn(f"{n} options · {n} with sizes not checked By price", said, "not '0 in your size'")
        self.assertNotIn("0 in your size", said)

    def test_the_pop_up_marks_options_whose_sizes_were_not_checked(self):
        from wardrobe import outfits
        w = selection.build()
        outfit = next(o for o in outfits.all_outfits(w)
                      if any(w.get(sid).n_not_checked and len(w.get(sid).cands) > 1 for sid in o.slots))
        sid = next(s for s in outfit.slots if w.get(s).n_not_checked and len(w.get(s).cands) > 1)
        page = self.client.get("/outfits/piece", query_string={"at": outfit.sig, "slot": sid},
                               headers={"HX-Request": "true"}).data.decode()
        rows = re.findall(r"<li(?: class=\"out\")?>.*?</li>", page.split("Swap it for", 1)[1], re.S)
        others = [c for c in w.get(sid).cands if c.id != w.get(sid).chosen.id][:6]
        self.assertEqual(len(rows), len(others))
        for row, cand in zip(rows, others):
            said = " ".join(html.unescape(re.sub(r"<[^>]+>", " ", row)).split())
            self.assertEqual("sizes not checked" in said, not cand.size.known, said)
            self.assertEqual("not in your size" in said, not cand.available, said)

    def test_the_store_list_is_never_cut_for_one_customer(self):
        # The catalogue the customer's pick is made from still holds every COS product: none is dropped for
        # having no sizes, and none of the shared list's products is changed by a customer's sizes.
        cat = catalog.load()
        cos_products = [c for c in cat["candidates"] if c["store"] == "cos"]
        self.assertTrue(cos_products)
        w = selection.build()
        offered = {c.id for v in w.slots for c in v.cands}
        self.assertTrue({c["id"] for c in cos_products} <= offered)


if __name__ == "__main__":
    unittest.main()
