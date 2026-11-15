"""The store picker: Profile's Stores tab, where a customer ticks the stores his pieces are picked from.

Every store customers are offered (programmes.offered: COS and Weekday today, a store whose programme says yes later)
is a row to tick, all ticked to start with. What is saved is the stores he unticked (the profile's `stores_off`; none
saved = every store). The planner reads only his stores (catalog.load), so Outfits, Wardrobe, Buy and the shopping list
follow. Unticking a store picks its pieces again, his own choices from it too, with one line saying so; his choices
from a store he kept stay. At least one store stays ticked.

The products below are invented, in the shapes the stores' pages had on 11 Nov 2026 (test_programmes.shaped).
"""
import html
import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from wardrobe import catalog, db, paths, programmes, selection, shared
from wardrobe import profile as profile_mod
from wardrobe.app import create_app

from .test_production import ProductionCase, words
from .test_programmes import PUBLISHED, STORES, shaped

# Four of the example plan's pieces: the grey jumper and the white tee in both stores (Weekday the cheaper), the jeans
# in both (Weekday the cheaper), the charcoal coat at Weekday only. And Zara's jumper, which is never offered.
LIST = [
    shaped("cos", "1000000101", "Pullover aus Merinowolle", 89.0, "Grey", "knit"),
    shaped("weekday", "1000000201", "Pullover aus Wollmischung", 59.0, "Grau", "knit"),
    shaped("cos", "1000000102", "T-Shirt aus schwerem Baumwolljersey", 35.0, "White", "tee"),
    shaped("weekday", "1000000202", "Standard T-Shirt", 25.0, "Weiß", "tee"),
    shaped("cos", "1000000103", "Gerade Jeans", 85.0, "Blau", "jeans"),
    shaped("weekday", "1000000203", "Space Jeans", 60.0, "Blau", "jeans", sizes=["31/32", "32/32", "33/32"]),
    shaped("weekday", "1000000204", "Mantel aus Wollmischung", 120.0, "Dunkelgrau", "coat"),
    shaped("zara", "1000001", "Pullover aus Merinowolle", 39.95, "Grau", "knit"),
]
PIECES = ("grey-merino-jumper", "white-tee", "indigo-jeans", "charcoal-wool-coat")
# The Profile form as a first save sends it, the example's answers kept (StartsOnTheOutfits.EXAMPLE_FORM).
FORM = {"top_size": "M", "waist": "32", "length": "32", "shoe": "43", "height_cm": "180", "weight_kg": "78",
        "budget": "1500", "liked": "navy, grey, white, olive", "refused": "", "use": "both", "shoes": "on",
        "outerwear": "on", "owned": ""}
SAMPLE = {"label": "Musterhaus", "programme": "awin"}     # an invented store whose programme said yes


def panel(page: str) -> str:
    """The Stores tab's part of the Profile page."""
    return re.search(r'<section class="cc-panel" id="panel-stores".*?</section>', page, re.S).group(0)


def rows(page: str) -> list[tuple[str, bool, str]]:
    """(the store's key, ticked, what the row says) for each row of the Stores tab."""
    return [(key, bool(on), words(said)) for key, on, said in re.findall(
        r'<label class="check store-row"><input type="checkbox" name="stores" value="(\w+)"( checked)?>(.*?)</label>',
        panel(page), re.S)]


class TheStorePicker(ProductionCase):
    def setUp(self):
        super().setUp()
        (paths.DATA_DIR / shared.POOL_NAME).write_text(json.dumps(
            {"published_at": PUBLISHED, "collected_at": "2026-11-11T17:00:18+01:00", "stores": STORES,
             "products": LIST}, ensure_ascii=False), encoding="utf-8")
        self.ada = self.member("ada@example.com")
        self.ada.get(self.save().headers["Location"])  # her own answers (a later save comes back to its tab), read

    def save(self, **changes):
        return self.post(self.ada, "/profile", **{**FORM, "tab": "stores", **changes})

    def as_ada(self):
        return db.as_user(self.user_id("ada@example.com"))

    def picks(self) -> dict:
        with self.as_ada():
            w = selection.build()
            return {view.slot["id"]: (view.state, view.chosen.id if view.chosen else None,
                                      sorted({c.data["store"] for c in view.cands}))
                    for view in w.slots if view.slot["id"] in PIECES}

    def said(self, response) -> str:
        """The messages the page a save leads to says at its top."""
        page = self.ada.get(response.headers["Location"]).get_data(as_text=True)
        return " | ".join(words(m) for m in re.findall(r'<p class="flash"[^>]*>(.*?)</p>', page, re.S))

    def test_the_tab_lists_every_store_offered_all_ticked_with_its_programme(self):
        page = self.ada.get("/profile").get_data(as_text=True)
        self.assertIn('<button type="button" role="tab" id="tab-stores" aria-controls="panel-stores"', page)
        self.assertEqual(rows(page), [("cos", True, "COS · Rakuten partner"), ("weekday", True, "Weekday · Rakuten partner")])
        self.assertNotIn("zara", panel(page).lower(), "a store without a programme is never listed")
        self.assertIn("Your pieces are picked only from the stores you tick. At least one stays ticked.", words(panel(page)))
        self.assertIn('<input type="hidden" name="stores_shown" value="1">', panel(page))
        self.assertIn('role="group" aria-labelledby="stores" aria-describedby="stores-help"', panel(page))

    def test_missing_means_every_store(self):
        with self.as_ada():
            stored = db.get_setting("profile")
            stored.pop("stores_off")                 # saved before there was a Stores tab
            db.set_setting("profile", stored)
            self.assertEqual(profile_mod.stores(), ["cos", "weekday"])
            self.assertEqual({c["store"] for c in catalog.load()["candidates"]}, {"cos", "weekday"})
        self.assertEqual([on for _, on, _ in rows(self.ada.get("/profile").get_data(as_text=True))], [True, True])
        # A form without the Stores tab (an older page, a save from elsewhere) leaves the stores as they are.
        self.save(stores=["cos"], stores_shown="1")
        self.save(budget="900")
        with self.as_ada():
            self.assertEqual(profile_mod.load()["stores_off"], ["weekday"])

    def test_only_the_ticked_stores_are_picked_and_every_page_follows(self):
        before = self.picks()
        self.assertEqual(before["indigo-jeans"], ("auto", "weekday-1000000203", ["cos", "weekday"]))
        saved = self.save(stores=["cos"], stores_shown="1")
        self.assertEqual(saved.headers["Location"], "/profile#stores", "back to the tab it was sent from")
        with self.as_ada():
            self.assertEqual(profile_mod.load()["stores_off"], ["weekday"])
            self.assertEqual(profile_mod.stores(), ["cos"])
            self.assertEqual({c["store"] for c in catalog.load()["candidates"]}, {"cos"})
            self.assertEqual({c["store"] for c in db.get_catalog()["candidates"]}, {"cos", "weekday"},
                             "what is stored keeps Weekday's products, for when it is ticked again")
        self.assertEqual(self.picks(), {
            "grey-merino-jumper": ("auto", "cos-1000000101", ["cos"]),
            "white-tee": ("auto", "cos-1000000102", ["cos"]),
            "indigo-jeans": ("auto", "cos-1000000103", ["cos"]),
            "charcoal-wool-coat": ("auto", None, []),
        })
        self.assertEqual(rows(self.ada.get("/profile").get_data(as_text=True)),
                         [("cos", True, "COS · Rakuten partner"), ("weekday", False, "Weekday · Rakuten partner")])
        # Outfits, its pop-ups and Buy pages, Wardrobe, the pieces' pages and the shopping list: no Weekday anywhere.
        outfits_page = self.ada.get("/outfits").get_data(as_text=True)
        found = [html.unescape(url) for url in re.findall(r'(?:hx-get|href)="(/outfits/(?:piece|buy)\?[^"]+)"', outfits_page)]
        self.assertTrue(found, "the outfits have pop-ups and Buy pages to look at")
        for path in ["/", "/outfits", "/list", "/list.md", "/list.csv", *found, *(f"/slot/{p}" for p in PIECES)]:
            body = self.ada.get(path).get_data(as_text=True)
            self.assertNotIn("weekday", body.lower(), path)
        # The coat only Weekday has: the Wardrobe says why it is empty, and that ticking Weekday again fills it.
        self.assertIn("Stilsmith has coats only from stores you unticked, so this piece is left out of your outfits "
                      "and your total.", html.unescape(self.ada.get("/").get_data(as_text=True)))
        # Ticked again: the products are back at once, nothing to rebuild.
        self.save(stores=["cos", "weekday"], stores_shown="1")
        self.assertEqual(self.picks(), before)

    def test_unticking_picks_its_pieces_again_his_own_choices_too_with_one_line(self):
        with self.as_ada():
            db.update_slot("grey-merino-jumper", locked=True, pick="weekday-1000000201")   # chosen at Weekday
            db.update_slot("white-tee", locked=True, pick="cos-1000000102")                # chosen at COS
        self.assertEqual(self.picks(), {
            "grey-merino-jumper": ("locked", "weekday-1000000201", ["cos", "weekday"]),
            "white-tee": ("locked", "cos-1000000102", ["cos", "weekday"]),
            "indigo-jeans": ("auto", "weekday-1000000203", ["cos", "weekday"]),
            "charcoal-wool-coat": ("auto", "weekday-1000000204", ["weekday"]),
        })
        saved = self.save(stores=["cos"], stores_shown="1")
        self.assertEqual(self.said(saved), "Your pieces now come only from COS: 3 pieces were picked again (1 of them you "
                                           "had chosen yourself), and 1 has nothing from your stores yet. | Profile "
                                           "saved. See your outfits")
        self.assertEqual(self.picks(), {
            "grey-merino-jumper": ("auto", "cos-1000000101", ["cos"]),     # his Weekday choice: unlocked, picked again
            "white-tee": ("locked", "cos-1000000102", ["cos"]),            # his COS choice stays
            "indigo-jeans": ("auto", "cos-1000000103", ["cos"]),
            "charcoal-wool-coat": ("auto", None, []),
        })
        with self.as_ada():
            self.assertEqual((db.get_slot("grey-merino-jumper")["locked"], db.get_slot("grey-merino-jumper")["pick"]),
                             (False, None))
        # Ticking Weekday again says nothing of the kind, and its products are among the options again.
        again = self.save(stores=["cos", "weekday"], stores_shown="1")
        self.assertEqual(self.said(again), "Profile saved. See your outfits")
        self.assertEqual(self.picks()["grey-merino-jumper"], ("auto", "weekday-1000000201", ["cos", "weekday"]))

    def test_the_line_counts_in_plain_words(self):
        with self.as_ada():
            before = profile_mod.load()
            after = {**before, "stores_off": ["weekday"]}
            db.update_slot("grey-merino-jumper", owned=True)
            db.update_slot("white-tee", owned=True)
            db.update_slot("charcoal-wool-coat", owned=True)
            db.update_slot("indigo-jeans", locked=True, pick="weekday-1000000203")
            for slot in db.list_slots():                 # every other piece owned: only the jeans are left to pick
                if slot["id"] != "indigo-jeans":
                    db.update_slot(slot["id"], owned=True)
            self.assertEqual(shared.stores_unticked(before, after), "Your pieces now come only from COS: 1 piece was "
                                                                    "picked again (you had chosen it yourself).")
            self.assertEqual(shared.stores_unticked(after, after), "", "nothing unticked, nothing said")
            db.update_slot("indigo-jeans", owned=True)
            self.assertEqual(shared.stores_unticked(before, after), "Your pieces now come only from COS.",
                             "nothing of his came from Weekday")

    def test_an_owned_piece_locked_to_an_unticked_store_stays_owned_and_is_not_counted(self):
        with self.as_ada():
            db.update_slot("grey-merino-jumper", owned=True, locked=True, pick="weekday-1000000201")
        saved = self.save(stores=["cos"], stores_shown="1")
        self.assertIn("Your pieces now come only from COS: 2 pieces were picked again, and 1 has nothing",
                      self.said(saved), "the jeans and the coat; the jumper he owns is not counted")
        with self.as_ada():
            jumper = db.get_slot("grey-merino-jumper")
            self.assertEqual((jumper["owned"], jumper["locked"], jumper["pick"]), (True, False, None))

    def test_the_last_store_cannot_be_unticked(self):
        saved = self.save(stores_shown="1")             # nothing ticked
        self.assertIn("At least one store must stay ticked, so your stores stay as they were.", self.said(saved))
        with self.as_ada():
            self.assertEqual(profile_mod.load()["stores_off"], [])
        self.save(stores=["weekday"], stores_shown="1")
        self.save(stores_shown="1")
        with self.as_ada():
            self.assertEqual(profile_mod.stores(), ["weekday"], "the one left stays")
        self.save(stores=["zara"], stores_shown="1")    # a store not offered is no store to keep
        with self.as_ada():
            self.assertEqual(profile_mod.stores(), ["weekday"])
            # Should every store he kept stop being offered, he has all those that are, never none.
            self.assertEqual(profile_mod.stores({"stores_off": ["cos", "weekday"]}), ["cos", "weekday"])

    def test_a_link_from_an_unticked_store_is_not_added(self):
        self.save(stores=["cos"], stores_shown="1")
        piece = self.ada.get("/slot/indigo-jeans").get_data(as_text=True)
        self.assertIn("Paste product page addresses from COS, one per line.", words(piece))
        link = "https://www.weekday.com/de-de/p/men/space-jeans-1000000299/"
        self.post(self.ada, "/slot/indigo-jeans/import", urls=link)
        page = html.unescape(self.ada.get("/slot/indigo-jeans").get_data(as_text=True))
        self.assertIn(f"Not added: “{link}” is not a COS link.", page)
        with self.as_ada():
            self.assertNotIn("weekday-1000000299", {c["id"] for c in db.get_catalog()["candidates"]})

    def test_a_store_offered_later_is_listed_and_ticked_and_one_left_out_stays_left_out(self):
        self.save(stores=["cos"], stores_shown="1")
        real = programmes._stores()
        more = {**real, "musterhaus": SAMPLE}
        with mock.patch.object(programmes, "_stores", return_value=more):
            page = self.ada.get("/profile").get_data(as_text=True)
            self.assertEqual(rows(page), [("cos", True, "COS · Rakuten partner"), ("weekday", False, "Weekday · Rakuten partner"),
                                          ("musterhaus", True, "Musterhaus · Awin partner")])
            with self.as_ada():
                self.assertEqual(profile_mod.stores(), ["cos", "musterhaus"])
        # Weekday stops being offered while he has it unticked, he saves, and it is offered again: still unticked.
        without = {**real, "weekday": {**real["weekday"], "programme": "none"}}
        with mock.patch.object(programmes, "_stores", return_value=without):
            self.assertEqual(rows(self.ada.get("/profile").get_data(as_text=True)), [("cos", True, "COS · Rakuten partner")])
            self.save(stores=["cos"], stores_shown="1")
        with self.as_ada():
            self.assertEqual(profile_mod.stores(), ["cos"])


class OnYourOwnMachine(unittest.TestCase):
    """What `python -m wardrobe publish` shares is every store's, whatever this computer's profile ticked."""

    def setUp(self):
        for path in (paths.DB_PATH, paths.CATALOG_PATH):
            path.unlink(missing_ok=True)
        catalog._cache = None
        create_app()                 # sets up the one local user and the example plan

    def tearDown(self):
        paths.CATALOG_PATH.unlink(missing_ok=True)
        catalog._cache = None

    def test_publishing_shares_every_store(self):
        rows_ = [{**product, "slot_id": "grey-merino-jumper"} for product in LIST[:2]]
        catalog.save({"source": "collected", "collected_at": PUBLISHED, "stores": STORES, "candidates": rows_})
        profile_mod.save({**profile_mod.load(), "stores_off": ["weekday"]})
        self.assertEqual([c["store"] for c in catalog.load()["candidates"]], ["cos"])
        with tempfile.TemporaryDirectory() as folder:
            self.assertEqual(shared.publish(Path(folder)), 2)
            listed = json.loads((Path(folder) / shared.POOL_NAME).read_text(encoding="utf-8"))
        self.assertEqual(sorted(p["store"] for p in listed["products"]), ["cos", "weekday"])
