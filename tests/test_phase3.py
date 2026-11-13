"""Size check, saved outfits, and the shopping list."""
import csv
import io
import re
import unittest

from wardrobe import catalog, db, export, outfits, paths, programmes, selection, sizecheck, sizes
from wardrobe import profile as profile_mod
from wardrobe.app import create_app

HX = {"HX-Request": "true"}
CHARTS = sizes.load_charts()
ME = {**profile_mod.EXAMPLE, "top_size": "M", "waist": 32, "length": 32, "shoe": "43",
      "height_cm": 180, "weight_kg": 78}
IN_STOCK = sizes.SizeStatus(True, "M", "M in stock")


def notes(category="knit", store="cos", fit="regular", size=IN_STOCK, **profile):
    data = {"store": store, "fit": fit}
    return sizecheck.check(data, size, {**ME, **profile}, category, CHARTS).notes


class SizeCheck(unittest.TestCase):
    def test_nothing_to_say_about_a_regular_item_in_your_size(self):
        self.assertEqual(notes(), [])

    def test_oversized_and_slim_cuts_are_flagged(self):
        self.assertIn("Oversized cut", notes(fit="oversized")[0])
        self.assertIn("Slim cut", notes(fit="slim")[0])
        self.assertEqual(notes(fit="relaxed"), [], "only the two cuts the spec names are flagged")
        # height and weight tune the advice
        self.assertIn("one size down", notes(fit="oversized", height_cm=185, weight_kg=68)[0])
        self.assertIn("one size up", notes(fit="slim", height_cm=175, weight_kg=88)[0])
        self.assertNotIn("one size up", notes(fit="slim")[0])

    def test_between_sizes_by_the_stores_chart(self):
        self.assertEqual(notes(), [], "no chest entered: no chart check")
        border = notes(chest_cm=98)                      # COS: M ends and L begins at 98
        self.assertTrue(any("Between sizes at COS" in n and "M" in n and "L" in n for n in border), border)
        other = notes(chest_cm=100)                      # squarely an L at COS
        self.assertTrue(any("COS's chart puts a 100 cm chest in L; you entered M" in n for n in other), other)
        self.assertEqual(notes(store="weekday", chest_cm=98), [], "the same chest is a plain M at Weekday")
        self.assertTrue(any("outside" in n for n in notes(chest_cm=140)))

    def test_trouser_waist_against_the_chart(self):
        label_42 = sizes.SizeStatus(True, "42", "42 in stock")
        at_border = notes("trousers", "zara", size=label_42, waist_cm=86)
        self.assertTrue(any("Between sizes at Zara" in n and "42" in n and "44" in n for n in at_border), at_border)
        disagree = notes("trousers", "zara", size=label_42, waist_cm=92)
        self.assertTrue(any("puts an 92 cm waist in 46" in n for n in disagree), disagree)

    def test_half_shoe_sizes_and_odd_lengths(self):
        shoes = notes("sneakers", size=sizes.SizeStatus(True, "43", "43 in stock"), shoe="42.5")
        self.assertTrue(any("between 42 and 43" in n for n in shoes), shoes)
        jeans = notes("jeans", "weekday", size=sizes.SizeStatus(True, "32/34", "32/34 in stock"), length=33)
        self.assertTrue(any("length 33" in n and "34" in n for n in jeans), jeans)

    def test_one_length_garments_for_tall_and_short_people(self):
        self.assertTrue(any("192 cm" in n for n in notes("coat", height_cm=192)))
        self.assertTrue(any("run long" in n for n in notes("trousers", height_cm=166)))
        self.assertEqual(notes("coat", height_cm=180), [])
        with_length = sizes.SizeStatus(True, "32/32", "32/32 in stock")
        self.assertEqual(notes("jeans", "weekday", size=with_length, height_cm=195), [], "jeans come in lengths")
        self.assertEqual(notes("tee", height_cm=195), [], "a tee's length is not flagged")

    def test_missing_size_information_is_said_out_loud(self):
        # Truthfully: nobody opened the store's product page, so the sizes were not checked, at a store named.
        unknown = sizes.SizeStatus(True, None, "unknown", known=False)
        self.assertEqual(notes(size=unknown)[-1], "Sizes not checked at COS: look on its page before you buy.")
        self.assertEqual(notes(store="weekday", size=unknown)[-1],
                         "Sizes not checked at Weekday: look on its page before you buy.")

    def test_the_likely_label_when_a_store_gives_no_sizes(self):
        for store, category, expected in [("cos", "tee", "M"), ("cos", "coat", "M / 48"), ("cos", "trousers", "48"),
                                          ("zara", "chinos", "42"), ("weekday", "jeans", "32/32"), ("cos", "boots", "43")]:
            self.assertEqual(sizecheck.usual_size(ME, category, store, CHARTS), expected, (store, category))

    def test_chart_lookup(self):
        table = {"S": [90, 94], "M": [94, 98], "L": [98, 102]}
        self.assertEqual(sizecheck.by_chart(table, 96, 1.5), ("M", None))
        self.assertEqual(sizecheck.by_chart(table, 97, 1.5), ("M", "L"))
        self.assertEqual(sizecheck.by_chart(table, 94.5, 1.5), ("M", "S"))
        self.assertEqual(sizecheck.by_chart(table, 102, 1.5), ("L", None))
        self.assertEqual(sizecheck.by_chart(table, 80, 1.5), (None, None))


class AppCase(unittest.TestCase):
    def setUp(self):
        for path in (paths.DB_PATH, paths.CATALOG_PATH):
            path.unlink(missing_ok=True)
        catalog._cache = None
        self.client = create_app().test_client()


class SizeCheckInTheApp(AppCase):
    def test_body_measurements_are_optional_and_feed_the_check(self):
        form = {"top_size": "M", "waist": "32", "length": "32", "shoe": "43", "height_cm": "180",
                "weight_kg": "78", "budget": "1500", "liked": "navy, grey, white, olive", "refused": "",
                "use": "both", "shoes": "on", "outerwear": "on", "owned": "", "chest_cm": "", "waist_cm": ""}
        self.client.post("/profile", data=form)
        self.assertIsNone(profile_mod.load()["chest_cm"])
        self.client.post("/profile", data={**form, "chest_cm": "98,5", "waist_cm": "abc"})
        prof = profile_mod.load()
        self.assertEqual((prof["chest_cm"], prof["waist_cm"]), (98.5, None))
        flagged = [c for s in selection.build().slots for c in s.cands
                   if any("chest" in n for n in c.check.notes)]
        self.assertTrue(flagged, "tops now carry chart notes")

    def test_notes_show_on_the_slot_page_and_the_card(self):
        w = selection.build()
        view = next(s for s in w.slots if any(c.data["fit"] == "oversized" and c.available for c in s.cands))
        cand = next(c for c in view.cands if c.data["fit"] == "oversized" and c.available)
        self.assertIn(b"Oversized cut", self.client.get(f"/slot/{view.slot['id']}").data)
        self.client.post(f"/slot/{view.slot['id']}/pick", data={"candidate": cand.id}, headers=HX)
        self.assertIn(b"Oversized cut", self.client.get("/").data)

    def test_the_size_to_order_is_the_stores_own_label(self):
        w = selection.build()
        trousers = next(s for s in w.slots if s.garment.key == "trousers")
        labels = {c.data["store"]: c.size_to_order for c in trousers.cands}
        self.assertEqual(labels["cos"], "48")                     # W32 at COS
        self.assertEqual(labels["weekday"], "48")
        jeans = next(s for s in w.slots if s.garment.key == "jeans")
        labels = {c.data["store"]: c.size_to_order for c in jeans.cands}
        self.assertEqual(labels["weekday"], "32/32")              # W32 L32 on Weekday's jeans: the same waist, its own label


class SavedOutfits(AppCase):
    def first_key(self):
        boards, _ = outfits.generate(selection.build(), limit=4)
        return boards[0].key, boards[0]

    def test_save_and_unsave_with_the_heart(self):
        key, outfit = self.first_key()
        r = self.client.post("/outfits/save", data={"key": key}, headers=HX)
        self.assertEqual(r.status_code, 200)
        self.assertIn('aria-pressed="true"', r.data.decode())
        self.assertEqual(db.saved_keys(), {key})
        page = self.client.get("/outfits?occasion=saved").data.decode()
        self.assertIn(f'id="outfit-{key}"', page)
        self.assertIn("Saved 1", self.client.get("/outfits").data.decode())

        r = self.client.post("/outfits/save", data={"key": key}, headers=HX)
        self.assertIn('aria-pressed="false"', r.data.decode())
        self.assertEqual(db.saved_keys(), set())
        self.assertIn("Nothing saved yet", self.client.get("/outfits?occasion=saved").data.decode())

    def test_a_favourite_keeps_its_pieces_when_the_wardrobe_moves_on(self):
        key, outfit = self.first_key()
        self.client.post("/outfits/save", data={"key": key}, headers=HX)
        before = db.list_saved()[0]
        self.assertEqual([p["slot_id"] for p in before["pieces"]], [p.view.slot["id"] for p in outfit.pieces])
        self.assertTrue(all(p["name"] and p["hex"] for p in before["pieces"]))

        self.client.post("/settings", data={"mode": "cheapest", "threshold": "70"}, headers=HX)
        catalog.update(lambda cat: cat["candidates"].clear())      # even if the catalogue is wiped
        after = db.list_saved()[0]
        self.assertEqual(after["pieces"], before["pieces"])
        page = self.client.get("/outfits?occasion=saved").data.decode()
        self.assertIn("changed", page)
        self.assertIn(before["pieces"][0]["name"], page)

    def test_a_single_outfit_has_no_arrows(self):
        # The arrows move to the next or the previous outfit: with one outfit there is none, so there are no arrows
        # (rather than two that never work). With two outfits, or more to show, there are both.
        arrows = re.compile(r'<button class="reel-nav (prev|next)"')
        boards, _ = outfits.generate(selection.build(), limit=4)
        self.client.post("/outfits/save", data={"key": boards[0].key}, headers=HX)
        page = self.client.get("/outfits?occasion=saved").data.decode()
        self.assertEqual(page.count("data-slide"), 1)
        self.assertEqual(arrows.findall(page), [])
        self.client.post("/outfits/save", data={"key": boards[1].key}, headers=HX)
        self.assertEqual(arrows.findall(self.client.get("/outfits?occasion=saved").data.decode()), ["prev", "next"])
        self.assertEqual(arrows.findall(self.client.get("/outfits").data.decode()), ["prev", "next"])

    def test_saving_something_that_no_longer_exists_is_refused(self):
        r = self.client.post("/outfits/save", data={"key": "000000000000"}, headers=HX)
        self.assertEqual(r.status_code, 409)


class ShoppingList(AppCase):
    def test_grouped_by_store_with_subtotals_that_add_up(self):
        coat = next(s for s in selection.build().slots if s.garment.key == "coat")
        self.client.post(f"/slot/{coat.slot['id']}/own", headers=HX)
        profile_mod.save({**profile_mod.load(), "shoe": "49"})       # nobody stocks a 49
        w = selection.build()
        sl = export.build(w)

        # In the order config/stores.toml lists the stores customers are offered.
        self.assertEqual([g.key for g in sl.groups], [k for k in programmes.offered() if k in {g.key for g in sl.groups}])
        self.assertEqual([g.key for g in sl.groups], ["cos", "weekday"], "the demo data has products of both")
        self.assertAlmostEqual(sum(g.subtotal for g in sl.groups), w.total, places=2)
        self.assertEqual(sl.pieces, w.n_buy)
        self.assertEqual(sl.owned, [coat.slot["name"]])
        self.assertTrue(any("sneakers" in slot.lower() for slot, _ in sl.missing))
        tee = next(line for g in sl.groups for line in g.lines if line.qty == 2)
        self.assertAlmostEqual(tee.total, tee.unit_price * 2, places=2)
        for g in sl.groups:
            for line in g.lines:
                self.assertTrue(line.url.startswith("http"))
                self.assertTrue(line.size)

    def test_markdown_and_csv_say_the_same_thing(self):
        sl = export.build(selection.build())
        md = export.to_markdown(sl)
        self.assertIn("DEMO DATA", md)
        for g in sl.groups:
            self.assertIn(f"## {g.label} — {g.pieces} pieces", md)
        self.assertEqual(md.count("- [ ] "), sum(len(g.lines) for g in sl.groups))

        rows = list(csv.DictReader(io.StringIO(export.to_csv(sl))))
        self.assertEqual(len(rows), sum(len(g.lines) for g in sl.groups))
        self.assertAlmostEqual(sum(float(r["total_eur"]) for r in rows), sl.total, places=2)
        self.assertEqual(set(rows[0]), {"store", "slot", "product", "colour", "size", "quantity",
                                        "unit_price_eur", "total_eur", "link", "notes"})

    def test_things_to_check_travel_with_the_list(self):
        w = selection.build()
        view = next(s for s in w.slots if any(c.data["fit"] == "slim" and c.available for c in s.cands))
        cand = next(c for c in view.cands if c.data["fit"] == "slim" and c.available)
        self.client.post(f"/slot/{view.slot['id']}/pick", data={"candidate": cand.id}, headers=HX)
        sl = export.build(selection.build())
        line = next(line for g in sl.groups for line in g.lines if line.slot == view.slot["name"])
        self.assertTrue(any("Slim cut" in n for n in line.notes))
        self.assertIn("Slim cut", export.to_markdown(sl))

    def test_pages_and_downloads(self):
        page = self.client.get("/list")
        self.assertEqual(page.status_code, 200)
        self.assertIn(b'href="/list.csv">Download for a spreadsheet (.csv)', page.data)
        self.assertIn(b'href="/list.md">Download as text (.md)', page.data)
        md = self.client.get("/list.md")
        self.assertIn("attachment", md.headers["Content-Disposition"])
        self.assertIn("# Shopping list", md.data.decode())
        data = self.client.get("/list.csv")
        self.assertTrue(data.data.decode("utf-8-sig").startswith("store,slot,product"))

    def test_an_empty_wardrobe_still_gives_a_page(self):
        db.replace_slots([])
        self.assertIn(b"Nothing to buy yet", self.client.get("/list").data)
        self.assertEqual(self.client.get("/list.md").status_code, 200)


if __name__ == "__main__":
    unittest.main()
