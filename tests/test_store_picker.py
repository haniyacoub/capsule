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

from . import having
from .test_production import ProductionCase, words
from .test_programmes import NO_PRODUCTS_YET, PUBLISHED, STORES, shaped

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
# The Profile form as a first save sends it: the example's answers, with the 1,500 € every account started with until
# 19 Nov 2026, so that the plan is the 24 pieces of 1,500 € (the coat among them: a budget sizes the plan).
FORM = {"top_size": "M", "waist": "32", "length": "32", "shoe": "43", "height_cm": "180", "weight_kg": "78",
        "budget": "1500", "liked": "navy, grey, white, olive", "refused": "", "use": "both", "shoes": "on",
        "outerwear": "on", "owned": ""}
SAMPLE = {"label": "Musterhaus", "programme": "awin"}     # an invented store whose programme said yes


def panel(page: str) -> str:
    """The Stores tab's part of the Profile page."""
    return re.search(r'<section class="cc-panel" id="panel-stores".*?</section>', page, re.S).group(0)


def rows(page: str) -> list[tuple[str, bool, str]]:
    """(the store's key, ticked, what the row says) for each row of the Stores tab: the stores with products."""
    return [(key, bool(on), words(said)) for key, on, said in re.findall(
        r'<label class="check store-row"><input type="checkbox" name="stores" value="([\w-]+)"( checked)?>(.*?)</label>',
        panel(page), re.S)]


def empty_rows(page: str) -> list[tuple[str, bool, str]]:
    """The same for the rows shown apart, under "No products yet": the stores only pasted links come from."""
    apart = re.search(r'<div class="store-empty" role="group" aria-labelledby="stores-empty">.*?</div>', panel(page), re.S)
    return [(key, bool(on), words(said)) for key, on, said in re.findall(
        r'<label class="check store-row"><input type="checkbox" name="stores" value="([\w-]+)" data-empty( checked)?>(.*?)</label>',
        apart.group(0) if apart else "", re.S)]


PASTED = list(NO_PRODUCTS_YET)     # the stores only pasted links come from: their keys, in config/stores.toml's order
PASTED_NAMES = html.escape("Tom Tailor, OTTO, Hirmer, Breuninger, Blue Tomato, Bergfreunde, JD Sports, H&M, "
                           "Herrenausstatter, just4men, Suitsupply, Seidensticker, Foot Locker, Carhartt WIP, Pull&Bear "
                           "or OLYMP", quote=False)      # as the page writes it


class TheStorePicker(ProductionCase):
    def setUp(self):
        super().setUp()
        (paths.DATA_DIR / shared.POOL_NAME).write_text(json.dumps(
            {"published_at": PUBLISHED, "collected_at": "2026-11-11T17:00:18+01:00", "stores": STORES,
             "products": LIST}, ensure_ascii=False), encoding="utf-8")
        self.ada = self.member("ada@example.com")
        self.ada.get(self.save().headers["Location"])  # her own answers (a later save comes back to its tab), read

    def save(self, only=False, **changes):
        """Save Profile from its Stores tab. The stores with no products yet stay ticked, as the page sends them,
        unless `only`: then the stores given are all that is ticked."""
        if "stores" in changes and not only:
            changes["stores"] = [*changes["stores"], *PASTED]
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

    def test_a_store_is_called_a_partner_only_once_its_programme_has_accepted_stilsmith(self):
        settings = {"label": "COS", "network": "rakuten", "programme_id": None, "feed_format": None,
                    "feed_location": None, "delivery_note": None, "disclaimer": None, "rules": {}}
        for status in ("none", "applied", "refused", "ended"):
            db.save_store("cos", {**settings, "status": status})
            self.assertEqual(rows(self.ada.get("/profile").get_data(as_text=True)),
                             [("cos", True, "COS"), ("weekday", True, "Weekday")], status)
        db.save_store("cos", {**settings, "status": "approved"})
        self.assertEqual(rows(self.ada.get("/profile").get_data(as_text=True)),
                         [("cos", True, "COS · Rakuten partner"), ("weekday", True, "Weekday")])

    def test_the_foot_says_not_affiliated_only_while_no_programme_has_accepted(self):
        foot = lambda: re.search(r'<footer class="site-foot">.*?</footer>', self.ada.get("/profile").get_data(as_text=True), re.S).group(0)   # noqa: E731
        self.assertIn("Not affiliated with any retailer.", foot())
        # An invented sample store marked approved (for trying the importers) is no partner: the line stays.
        db.save_store("kleiderwerk", {"label": "Kleiderwerk (sample)", "network": "awin", "programme_id": "900001",
                                      "feed_format": None, "feed_location": None, "delivery_note": None,
                                      "disclaimer": None, "rules": {"sample": True}, "status": "approved"})
        self.assertIn("Not affiliated with any retailer.", foot(), "it vanished for a sample store")
        db.save_store("cos", {"label": "COS", "network": "rakuten", "programme_id": None, "feed_format": None,
                              "feed_location": None, "delivery_note": None, "disclaimer": None, "rules": {},
                              "status": "approved"})
        self.assertNotIn("affiliated", foot(), "a partner on the Stores tab and 'not affiliated' below it would contradict")
        self.assertIn("Impressum", foot())

    def test_partner_links_are_said_to_be_partner_links(self):
        # From the day a store's programme has accepted Stilsmith its links may earn a commission, and German law
        # (UWG § 5a) wants such links marked as advertising, before the click. The foot of every page says so in
        # place of "Not affiliated with any retailer", naming the stores, and so do the shopping list and Buy this
        # outfit, under the stores' links. Before that, and for an invented sample store, nothing calls a link a
        # partner link.
        foot = lambda page: words(re.search(r'<footer class="site-foot">.*?</footer>', page, re.S).group(0))  # noqa: E731
        costs = lambda page: words(re.search(r'<div class="costs">.*?</div>', page, re.S).group(0))  # noqa: E731
        with self.as_ada():
            having.the_whole_plan()
        sample = {"network": "awin", "programme_id": "900001", "feed_format": None, "feed_location": None,
                  "delivery_note": None, "disclaimer": None}
        db.save_store("kleiderwerk", {**sample, "label": "Kleiderwerk (sample)", "rules": {"sample": True},
                                      "status": "approved"})
        for url in ("/profile", "/list"):
            page = self.ada.get(url).get_data(as_text=True)
            self.assertNotIn("partner link", page.lower(), url)
            self.assertIn("Not affiliated with any retailer.", foot(page), url)
        db.save_store("cos", {**sample, "label": "COS", "network": "rakuten", "rules": {}, "status": "approved"})
        said = "Partner links: Stilsmith may earn a commission when you buy at COS. You pay the same."
        for url in ("/profile", "/list", "/outfits", "/account", "/legal/privacy", "/no-such-page"):
            self.assertIn(said, foot(self.ada.get(url).get_data(as_text=True)), url)
        self.assertIn("Links to COS are partner links: if you buy there, Stilsmith may earn a commission. You pay "
                      "the same, and the commission does not change which product is picked for a piece.",
                      costs(self.ada.get("/list").get_data(as_text=True)))
        db.save_store("weekday", {**sample, "label": "Weekday", "network": "rakuten", "rules": {}, "status": "approved"})
        self.assertIn("when you buy at COS or Weekday.", foot(self.ada.get("/list").get_data(as_text=True)))
        self.assertIn("Links to COS and Weekday are partner links", costs(self.ada.get("/list").get_data(as_text=True)))
        # A visitor reads it on the website's pages too (not on his outfits, which show no store and no link).
        self.assertIn("when you buy at COS or Weekday.", foot(self.app.test_client().get("/about").get_data(as_text=True)))

    def test_the_tab_lists_every_store_offered_all_ticked_with_its_programme(self):
        page = self.ada.get("/profile").get_data(as_text=True)
        self.assertIn('<button type="button" role="tab" id="tab-stores" aria-controls="panel-stores"', page)
        # No programme has accepted Stilsmith yet (nothing is "approved" in the owner's registry): the stores are
        # named, and nothing calls them partners. The page's foot says "Not affiliated with any retailer".
        self.assertEqual(rows(page), [("cos", True, "COS"), ("weekday", True, "Weekday")])
        self.assertNotIn("partner", words(panel(page)).lower())
        self.assertIn("Menswear only. More stores will join.", words(panel(page)))
        self.assertIn("Not affiliated with any retailer.", page)
        self.assertNotIn("zara", panel(page).lower(), "a store without a programme is never listed")
        self.assertIn("Your pieces are picked only from the stores you tick. At least one store with products stays "
                      "ticked.", words(panel(page)))
        self.assertIn('<input type="hidden" name="stores_shown" value="1">', panel(page))
        self.assertIn('role="group" aria-labelledby="stores" aria-describedby="stores-help"', panel(page))

    def test_missing_means_every_store(self):
        with self.as_ada():
            stored = db.get_setting("profile")
            stored.pop("stores_off")                 # saved before there was a Stores tab
            db.set_setting("profile", stored)
            self.assertEqual(profile_mod.stores(), ["cos", "weekday", *PASTED])
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
            self.assertEqual(profile_mod.stores(), ["cos", *PASTED])
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
                         [("cos", True, "COS"), ("weekday", False, "Weekday")])
        with self.as_ada():
            having.the_whole_plan()     # every piece is in his wardrobe, so the Wardrobe and the list show them all
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
        # Ticking Weekday again says nothing of the kind, and its products are among the options again. The pick stays
        # COS's merino jumper, rated 93, which his budget pays for: Weekday's, rated 73, is known to be in his size,
        # but being sure of the size is worth 5 points, not 20 (selection.prefer_known_size).
        again = self.save(stores=["cos", "weekday"], stores_shown="1")
        self.assertEqual(self.said(again), "Profile saved. See your outfits")
        self.assertEqual(self.picks()["grey-merino-jumper"], ("auto", "cos-1000000101", ["cos", "weekday"]))

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
        stay = "At least one store with products must stay ticked, so your stores stay as they were."
        saved = self.save(stores_shown="1")             # nothing ticked
        self.assertIn(stay, self.said(saved))
        with self.as_ada():
            self.assertEqual(profile_mod.load()["stores_off"], [])
        self.save(stores=["weekday"], stores_shown="1")
        self.save(stores_shown="1")
        with self.as_ada():
            self.assertEqual(profile_mod.stores(), ["weekday", *PASTED], "the one left stays")
        self.save(only=True, stores=["zara"], stores_shown="1")    # a store not offered is no store to keep
        with self.as_ada():
            self.assertEqual(profile_mod.stores(), ["weekday", *PASTED])
            # Should every store he kept stop being offered, he has all those that are, never none.
            self.assertEqual(profile_mod.stores({"stores_off": ["cos", "weekday", *PASTED]}), ["cos", "weekday", *PASTED])

    def test_a_store_with_no_products_yet_cannot_be_the_only_store_ticked(self):
        # Hirmer and the other five have no products yet: his pieces cannot come from them. However many of them are
        # ticked, a store with products must be ticked too, or the save changes no store and says why.
        stay = "At least one store with products must stay ticked, so your stores stay as they were."
        for ticked in (["hirmer"], PASTED):
            saved = self.save(only=True, stores=ticked, stores_shown="1")
            self.assertIn(stay, self.said(saved), ticked)
            with self.as_ada():
                self.assertEqual(profile_mod.load()["stores_off"], [], ticked)
        # With a store that has products, any of them may be ticked or not: his pieces come from COS alone here.
        saved = self.save(only=True, stores=["cos", "hirmer"], stores_shown="1")
        self.assertNotIn(stay, self.said(saved))
        with self.as_ada():
            self.assertEqual(profile_mod.stores(), ["cos", "hirmer"])
            # A profile that somehow kept only such stores (saved another way) is read as every store offered.
            self.assertEqual(profile_mod.stores({"stores_off": ["cos", "weekday"]}), ["cos", "weekday", *PASTED])
        page = self.ada.get("/profile").get_data(as_text=True)
        self.assertEqual([(key, on) for key, on, _ in rows(page)], [("cos", True), ("weekday", False)])
        self.assertEqual([key for key, on, _ in empty_rows(page) if on], ["hirmer"])

    def test_stores_with_no_products_yet_are_shown_apart_and_only_take_pasted_links(self):
        page = self.ada.get("/profile").get_data(as_text=True)
        # Apart from COS and Weekday, under their own line, each a row to tick, without the word "partner": none of
        # their programmes has been applied to.
        self.assertIn("""<h3 class="store-empty-head" id="stores-empty">No products yet: paste a link on a piece's page</h3>""",
                      panel(page))
        self.assertEqual(empty_rows(page), [(key, True, html.escape(name)) for key, name in NO_PRODUCTS_YET.items()])
        self.assertLess(panel(page).index('value="weekday"'), panel(page).index('id="stores-empty"'))
        self.assertEqual(shared.stocked(), ["cos", "weekday"])
        # Unticking one changes no piece, so nothing is said of pieces picked again.
        before = self.picks()
        saved = self.save(only=True, stores=["cos", "weekday", "hirmer"], stores_shown="1")
        self.assertEqual(self.said(saved), "Profile saved. See your outfits")
        self.assertEqual(self.picks(), before)
        # A link from one that is ticked is added; from one that is not, refused.
        piece = words(self.ada.get("/slot/indigo-jeans").get_data(as_text=True))
        self.assertIn("Paste product page addresses from COS, Weekday or Hirmer, one per line. Menswear only.", piece)
        self.post(self.ada, "/slot/indigo-jeans/import",
                  urls="https://www.hirmer.de/herren/jeans/straight-fit-jeans-dunkelblau/p/1234567\n"
                       "https://www.bergfreunde.de/herren-jeans-blau-7654321/")
        said = html.unescape(self.ada.get("/slot/indigo-jeans").get_data(as_text=True))
        self.assertIn("Added “Straight fit jeans dunkelblau”: only the link could be read", said)
        self.assertIn("Not added: “https://www.bergfreunde.de/herren-jeans-blau-7654321/” is not a COS, Weekday or "
                      "Hirmer link.", said)
        # A store with products in the published list is no longer shown apart, whatever config/stores.toml lists.
        pool = json.loads((paths.DATA_DIR / shared.POOL_NAME).read_text(encoding="utf-8"))
        pool["products"].append({**shaped("cos", "1000000301", "Hemd aus Popeline", 79.0, "White", "shirt"),
                                 "id": "hirmer-1000000301", "store": "hirmer"})
        pool["published_at"] = "2026-11-16T09:00:00.000000+01:00"
        (paths.DATA_DIR / shared.POOL_NAME).write_text(json.dumps(pool, ensure_ascii=False), encoding="utf-8")
        self.assertEqual(shared.stocked(), ["cos", "weekday", "hirmer"])
        page = self.ada.get("/profile").get_data(as_text=True)
        self.assertEqual([key for key, _, _ in rows(page)], ["cos", "weekday", "hirmer"])
        self.assertNotIn("hirmer", [key for key, _, _ in empty_rows(page)])

    def test_a_link_from_an_unticked_store_is_not_added(self):
        self.save(stores=["cos"], stores_shown="1")
        piece = self.ada.get("/slot/indigo-jeans").get_data(as_text=True)
        self.assertIn(f"Paste product page addresses from COS, {PASTED_NAMES}, one per line.", words(piece))
        link = "https://www.weekday.com/de-de/p/men/space-jeans-1000000299/"
        self.post(self.ada, "/slot/indigo-jeans/import", urls=link)
        page = html.unescape(self.ada.get("/slot/indigo-jeans").get_data(as_text=True))
        self.assertIn(f"Not added: “{link}” is not a link to one of the stores listed above.", page)
        with self.as_ada():
            self.assertNotIn("weekday-1000000299", {c["id"] for c in db.get_catalog()["candidates"]})

    def test_a_store_offered_later_is_listed_and_ticked_and_one_left_out_stays_left_out(self):
        self.save(stores=["cos"], stores_shown="1")
        real = programmes._stores()
        more = {**real, "musterhaus": SAMPLE}
        with mock.patch.object(programmes, "_stores", return_value=more):
            page = self.ada.get("/profile").get_data(as_text=True)
            # Musterhaus has no products yet either: it joins the stores shown apart, ticked like them.
            self.assertEqual(rows(page), [("cos", True, "COS"), ("weekday", False, "Weekday")])
            self.assertEqual(empty_rows(page)[-1], ("musterhaus", True, "Musterhaus"))
            with self.as_ada():
                self.assertEqual(profile_mod.stores(), ["cos", *PASTED, "musterhaus"])
        # Weekday stops being offered while he has it unticked, he saves, and it is offered again: still unticked.
        without = {**real, "weekday": {**real["weekday"], "programme": "none"}}
        with mock.patch.object(programmes, "_stores", return_value=without):
            self.assertEqual(rows(self.ada.get("/profile").get_data(as_text=True)), [("cos", True, "COS")])
            self.save(stores=["cos"], stores_shown="1")
        with self.as_ada():
            self.assertEqual(profile_mod.stores(), ["cos", *PASTED])


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
            self.assertEqual(shared.publish(Path(folder)), (2, 0))
            listed = json.loads((Path(folder) / shared.POOL_NAME).read_text(encoding="utf-8"))
        self.assertEqual(sorted(p["store"] for p in listed["products"]), ["cos", "weekday"])
