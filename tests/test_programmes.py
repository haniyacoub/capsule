"""Only stores with a partner programme are offered: Zara is not (it has none).

config/stores.toml gives every store a `programme` line (programmes.py). The products of a store whose programme is
"none" never reach a customer: not the planner, the piece pages, the pop-up, Buy, the shopping list or a saved outfit.
Accounts that already had them get their pieces picked again, with one plain message on the Wardrobe page.

The products below are invented, in the shapes the stores' pages had on 11 Nov 2026: Zara with fabric and sizes,
COS with neither, Weekday with sizes.
"""
import html
import json
import re
import unittest
from unittest import mock

from wardrobe import catalog, config, db, mock as demo, paths, selection, shared
from wardrobe.app import create_app

from .test_production import ProductionCase, words

PUBLISHED = "2026-11-11T17:55:27.180518+01:00"


def shaped(store, sku, name, price, colour, category, **more):
    """One product as `python -m wardrobe publish` wrote it on 11 Nov, with the fields each store gave."""
    sizes = {"zara": ["S", "M", "L", "XL"], "cos": [], "weekday": ["XS", "S", "M", "L", "XL"]}[store]
    sizes = more.pop("sizes", sizes)
    address = {"zara": f"https://www.zara.com/de/de/{name.lower().replace(' ', '-')}-p0{sku}.html",
               "cos": f"https://www.cos.com/de-de/men/product/{name.lower().replace(' ', '-')}-{sku}",
               "weekday": f"https://www.weekday.com/de-de/p/men/{name.lower().replace(' ', '-')}-{sku}/"}[store]
    picture = {"zara": f"https://static.zara.net/photos/{sku}.jpg", "cos": f"https://media.cos.com/assets/{sku}.jpg",
               "weekday": f"https://media.weekday.com/assets/{sku}.jpg"}[store]
    return {"id": f"{store}-{sku}", "store": store, "name": name, "slug": name.lower().replace(" ", "-"),
            "price": price, "price_before": None, "currency": "EUR", "colour": colour, "colour_hex": None,
            "composition_text": more.pop("fabric", "100% Merinowolle" if store == "zara" else ""),
            "fit": "regular", "description": "Größe des Models: 188 cm." if store == "zara" else "",
            "sizes_all": sizes, "sizes_in_stock": sizes, "url": address, "image_url": picture,
            "source": "collected", "collected_at": "2026-11-11T16:59:24+01:00", "category": category, **more}


# What the published list held for four of the example plan's pieces. Zara is the cheapest for each, so the
# cheapest level picked Zara for all four; the charcoal coat had nothing but Zara.
LIST = [
    shaped("zara", "1000001", "Pullover aus Merinowolle", 39.95, "Grau", "knit"),
    shaped("cos", "1000000101", "Pullover aus Merinowolle", 89.0, "Grey", "knit"),
    shaped("weekday", "1000000201", "Pullover aus Wollmischung", 59.0, "Grau", "knit"),
    shaped("zara", "1000002", "Basic T-Shirt", 12.95, "Weiß", "tee", fabric="100% Baumwolle"),
    shaped("cos", "1000000102", "T-Shirt aus schwerem Baumwolljersey", 35.0, "White", "tee"),
    shaped("zara", "1000003", "Jeans Straight Fit", 29.95, "Blau", "jeans", fabric="100% Baumwolle",
           sizes=["40", "42", "44"]),
    shaped("weekday", "1000000203", "Space Jeans", 60.0, "Blau", "jeans", sizes=["31/32", "32/32", "33/32"]),
    shaped("zara", "1000004", "Mantel mit Wolle", 89.95, "Dunkelgrau", "coat", fabric="51% Wolle, 49% Polyester"),
]
STORES = {"cos": {"status": "ok", "gives": "name, price, colour and picture"},
          "weekday": {"status": "ok", "gives": "name, price, colour, picture and size stock"},
          "zara": {"status": "ok", "gives": "name, price, colour, picture, sizes in stock and fabric"}}


class StoresWithAProgramme(unittest.TestCase):
    """One place decides: the `programme` line of each store in config/stores.toml."""

    def test_zara_has_no_programme_and_is_the_only_store_not_offered(self):
        from wardrobe import programmes
        stores = config.load("stores.toml")
        listed = {key: table["programme"] for key, table in stores.items() if key != "collector"}
        self.assertEqual(listed, {"cos": "rakuten", "weekday": "rakuten", "zara": "none"})
        self.assertEqual(programmes.offered(), {"cos": "COS", "weekday": "Weekday"})
        self.assertFalse(programmes.is_offered("zara"))
        self.assertEqual(programmes.label("zara"), "Zara", "its name is still known, for the message that it went")
        # Weekday's German programme is not confirmed: it stays offered, and the file says so next to it.
        text = (paths.CONFIG_DIR / "stores.toml").read_text(encoding="utf-8")
        weekday = text[text.index("[weekday]"):text.index("[weekday.garments")]
        self.assertIn("UNCONFIRMED for Germany", weekday)
        # Nothing is left to collect from Zara: no pages, no reader.
        from wardrobe import collect
        self.assertNotIn("zara", collect.ADAPTERS)
        self.assertNotIn("zara", collect.STORE_ORDER)
        self.assertNotIn("garments", stores["zara"])

    def test_a_store_must_say_its_programme(self):
        from wardrobe import programmes
        programmes.check({"collector": {"pause_seconds": [5, 9]}, "cos": {"programme": "rakuten"},
                          "zara": {"programme": "none"}})
        with self.assertRaisesRegex(config.ConfigError, r"\[arket\] needs a programme line"):
            programmes.check({"arket": {"label": "Arket"}})
        with self.assertRaisesRegex(config.ConfigError, r"arket.programme is 'rakutem'"):
            programmes.check({"arket": {"label": "Arket", "programme": "rakutem"}})

    def test_names_in_a_sentence(self):
        from wardrobe import programmes
        self.assertEqual(programmes.names(["zara"]), "Zara")
        self.assertEqual(programmes.names(["cos", "weekday"]), "COS and Weekday")
        self.assertEqual(programmes.names(["cos", "weekday"], last="or"), "COS or Weekday")

    def test_one_line_takes_a_store_out_everywhere(self):
        """Should Weekday turn out to have no German programme, its one line takes it out too."""
        from wardrobe import programmes
        real = programmes._stores()
        without = {**real, "weekday": {**real["weekday"], "programme": "none"}}
        catalog.save({"source": "collected", "candidates": [{**LIST[1], "slot_id": "a"}, {**LIST[2], "slot_id": "a"}]})
        try:
            with mock.patch.object(programmes, "_stores", return_value=without):
                self.assertEqual([c["store"] for c in catalog.load()["candidates"]], ["cos"])
                self.assertTrue(shared.revision({"published_at": PUBLISHED}).endswith("#cos"))
            self.assertTrue(shared.revision({"published_at": PUBLISHED}).endswith("#cos,weekday"))
        finally:
            paths.CATALOG_PATH.unlink(missing_ok=True)
            catalog._cache = None


class OnYourOwnMachine(unittest.TestCase):
    def setUp(self):
        for path in (paths.DB_PATH, paths.CATALOG_PATH):
            path.unlink(missing_ok=True)
        catalog._cache = None

    def tearDown(self):
        paths.CATALOG_PATH.unlink(missing_ok=True)
        catalog._cache = None

    def test_the_demo_data_has_no_zara(self):
        client = create_app().test_client()
        slots = db.list_slots()
        stores = {c["store"] for c in demo.build(slots)["candidates"]}
        self.assertEqual(stores, {"cos", "weekday"})
        for path in ["/", "/outfits", "/list", "/list.md", "/list.csv", *(f"/slot/{s['id']}" for s in slots)]:
            self.assertNotIn("zara", client.get(path).get_data(as_text=True).lower(), path)

    def test_zara_rows_in_a_catalogue_file_are_skipped_not_deleted(self):
        rows = [{**product, "slot_id": "grey-merino-jumper"} for product in LIST[:3]]
        catalog.save({"source": "collected", "collected_at": PUBLISHED, "stores": STORES, "candidates": rows})
        on_disk = paths.CATALOG_PATH.read_bytes()
        read = catalog.load()
        self.assertEqual([c["store"] for c in read["candidates"]], ["cos", "weekday"])
        self.assertEqual(sorted(read["stores"]), ["cos", "weekday"], "nor is it in the notes about each store")
        self.assertEqual(paths.CATALOG_PATH.read_bytes(), on_disk, "reading changes nothing in the file")

    def test_saving_leaves_zara_out_but_keeps_what_you_added_from_it(self):
        own = {**LIST[3], "id": "zara-1000099", "slot_id": "white-tee", "source": "manual"}
        rows = [{**LIST[3], "slot_id": "white-tee"}, {**LIST[4], "slot_id": "white-tee"}, own]
        catalog.save({"source": "collected", "collected_at": PUBLISHED, "stores": STORES, "candidates": rows})
        catalog.update(lambda cat: None)         # any change saved: a link added, details typed in
        on_disk = json.loads(paths.CATALOG_PATH.read_text(encoding="utf-8"))
        self.assertEqual([c["id"] for c in on_disk["candidates"]], ["cos-1000000102", "zara-1000099"])
        self.assertEqual(sorted(on_disk["stores"]), ["cos", "weekday"])
        self.assertEqual([c["id"] for c in catalog.load()["candidates"]], ["cos-1000000102"], "set aside, not shown")
        self.assertEqual(catalog.set_aside("white-tee"), [own])
        self.assertEqual(catalog.set_aside("indigo-jeans"), [])


class AccountsThatHadZara(ProductionCase):
    """An account built from the list before Zara went, as the owner's is on their server and on stilsmith.com."""

    def setUp(self):
        super().setUp()
        self.listed = paths.DATA_DIR / shared.POOL_NAME
        self.listed.write_text(json.dumps({"published_at": PUBLISHED, "collected_at": "2026-11-11T17:00:18+01:00",
                                           "stores": STORES, "products": LIST}, ensure_ascii=False), encoding="utf-8")
        self.on_disk = self.listed.read_bytes()
        self.ada = self.member("ada@example.com")
        with db.as_user(self.user_id("ada@example.com")):
            # What the list gave every customer before: each piece's products in all three stores ...
            collector = config.load("stores.toml")["collector"]
            had = [c for slot in db.list_slots() for c in shared.candidates_for(json.loads(self.on_disk), slot, collector)]
            catalog.save({"source": "collected", "collected_at": "2026-11-11T17:00:18+01:00", "stores": STORES,
                          "pool": f"{PUBLISHED}#refused", "candidates": had})
            db.set_setting("pool", f"{PUBLISHED}#refused")
            # ... the white tee locked to Zara's, chosen by hand ...
            db.update_slot("white-tee", locked=True, pick="zara-1000002")
            # ... and an outfit saved with Zara's jumper in it.
            db.save_outfit("0123456789ab", "2026-11-12T10:00:00+01:00", "Everyday", [
                self.saved_piece("grey-merino-jumper", "Grey merino jumper", "top", "knit", LIST[0]),
                self.saved_piece("indigo-jeans", "Indigo jeans", "bottom", "jeans", LIST[6])])

    def tearDown(self):
        self.listed.unlink(missing_ok=True)
        super().tearDown()

    @staticmethod
    def saved_piece(slot_id, slot_name, layer, category, product):
        return {"slot_id": slot_id, "slot_name": slot_name, "layer": layer, "role": layer, "category": category,
                "owned": False, "hex": "#8d8f92", "cand_id": product["id"], "name": product["name"],
                "store_name": product["name"], "store": product["store"], "price": product["price"],
                "url": product["url"], "image_url": product["image_url"], "colour": product["colour"],
                "composition": product["composition_text"], "fit": "regular", "slug": product["slug"],
                "description": product["description"], "source": "collected"}

    def picks(self):
        with db.as_user(self.user_id("ada@example.com")):
            w = selection.build()
            return {view.slot["id"]: (view.state, view.chosen.id if view.chosen else None,
                                      sorted(c.data["store"] for c in view.cands))
                    for view in w.slots if view.slot["id"] in ("grey-merino-jumper", "white-tee", "indigo-jeans",
                                                               "charcoal-wool-coat")}

    def test_zara_options_go_and_its_pieces_are_picked_again_with_one_message(self):
        with db.as_user(self.user_id("ada@example.com")):
            before = {c["store"] for c in catalog.stored()["candidates"]} if hasattr(catalog, "stored") else None
            self.assertIn("zara", before or {c["store"] for c in catalog.load()["candidates"]}, "the account had Zara")

        first = html.unescape(self.ada.get("/").get_data(as_text=True))
        self.assertIn("Zara has no partner programme, so Stilsmith no longer shows its products: 4 pieces were picked "
                      "again, and 1 has nothing in Stilsmith's product list yet.", first)
        self.assertEqual(first.lower().count("zara"), 1, "the message is the only place Zara is named")

        # Every option is from a store with a programme; each piece Zara filled has the best of the rest.
        self.assertEqual(self.picks(), {
            "grey-merino-jumper": ("auto", "weekday-1000000201", ["cos", "weekday"]),   # the cheapest of the rest
            "white-tee": ("auto", "cos-1000000102", ["cos"]),          # unlocked: Zara's tee was his own choice
            "indigo-jeans": ("auto", "weekday-1000000203", ["weekday"]),
            "charcoal-wool-coat": ("auto", None, []),                  # only Zara had one
        })
        with db.as_user(self.user_id("ada@example.com")):
            self.assertFalse(db.get_slot("white-tee")["locked"])
            self.assertIsNone(db.get_slot("white-tee")["pick"])
            stored = db.get_catalog()
            self.assertEqual({c["store"] for c in stored["candidates"]}, {"cos", "weekday"}, "saved back without Zara")
            self.assertNotIn("zara", stored["stores"])
        self.assertEqual(self.listed.read_bytes(), self.on_disk, "the published list itself is not edited")

        # Said once: from now on no page names Zara or links to it.
        pages = {"/": None, "/outfits": None, "/outfits?occasion=saved": None, "/list": None, "/list.md": None,
                 "/list.csv": None, "/slots": None, "/profile": None, "/account": None}
        pages.update({f"/slot/{slot}": None for slot in ("grey-merino-jumper", "white-tee", "indigo-jeans",
                                                         "charcoal-wool-coat")})
        outfits_page = self.ada.get("/outfits").get_data(as_text=True)
        found = [html.unescape(url) for url in re.findall(r'(?:hx-get|href)="(/outfits/(?:piece|buy)\?[^"]+)"',
                                                          outfits_page)]
        self.assertTrue(found, "the outfits have pop-ups and Buy pages to look at")
        pages.update({url: None for url in found})
        for path in pages:
            body = self.ada.get(path).get_data(as_text=True)
            self.assertNotIn("zara", body.lower(), path)

    def test_a_saved_outfit_keeps_the_piece_but_not_zara(self):
        page = html.unescape(self.ada.get("/outfits?occasion=saved").get_data(as_text=True))
        self.assertNotIn("zara", page.lower())
        self.assertIn("No longer offered", page)
        self.assertIn("Grey merino jumper", page)
        self.assertIn("Space Jeans", page, "the other piece stays as it was saved")

    def test_a_customer_without_zara_picks_gets_no_message(self):
        with db.as_user(self.user_id("ada@example.com")):
            for slot in ("grey-merino-jumper", "white-tee", "indigo-jeans", "charcoal-wool-coat"):
                db.update_slot(slot, owned=True)          # he owns them: nothing was picked from Zara
        page = self.ada.get("/").get_data(as_text=True)
        self.assertNotIn("picked again", page)
        self.assertNotIn("zara", page.lower())

    def test_a_customer_moving_from_the_demo_data_is_not_told_about_zara(self):
        with db.as_user(self.user_id("ada@example.com")):         # invented products, the old demo's Zara among them
            catalog.save({"source": "mock", "collected_at": PUBLISHED, "candidates": [
                {**LIST[0], "id": "mock-zara-grey-merino-jumper-0", "slot_id": "grey-merino-jumper", "source": "mock"}]})
        page = self.ada.get("/").get_data(as_text=True)
        self.assertNotIn("picked again", page, "the real products replace the invented ones in any case")
        self.assertNotIn("zara", page.lower())

    def test_a_new_customer_never_meets_zara(self):
        bob = self.member("bob@example.com")
        self.assertNotIn("zara", bob.get("/").get_data(as_text=True).lower())
        with db.as_user(self.user_id("bob@example.com")):
            self.assertEqual({c["store"] for c in db.get_catalog()["candidates"]}, {"cos", "weekday"})

    def test_the_public_pages_name_the_stores_that_are_offered(self):
        visitor = self.app.test_client()
        home = words(visitor.get("/").get_data(as_text=True))
        self.assertIn("picks the best-value real product for each from the high-street stores COS and Weekday,", home)
        for path in ("/", "/legal/impressum", "/legal/privacy", "/legal/terms", "/signup", "/login"):
            self.assertNotIn("zara", visitor.get(path).get_data(as_text=True).lower(), path)

    def test_the_message_counts_in_plain_words(self):
        with db.as_user(self.user_id("ada@example.com")):
            db.set_setting(shared.GONE_SETTING, {"stores": ["zara"], "pieces": 1, "empty": 0})
            self.assertEqual(shared.gone_message(keep=True), "Zara has no partner programme, so Stilsmith no longer "
                                                            "shows its products: 1 piece was picked again.")
            db.set_setting(shared.GONE_SETTING, {"stores": ["weekday", "zara"], "pieces": 2, "empty": 2})
            self.assertEqual(shared.gone_message(), "Weekday and Zara have no partner programme, so Stilsmith no longer "
                                                    "shows their products: 2 pieces were picked again, and 2 have "
                                                    "nothing in Stilsmith's product list yet.")
            self.assertEqual(shared.gone_message(), "", "said once")

    # ── what he added himself, by its link, from the store that went ──────────────────────────────────────────────

    OWN = {**LIST[0], "id": "zara-1000099", "name": "Pullover mit Zopfmuster", "slot_id": "grey-merino-jumper",
           "url": "https://www.zara.com/de/de/pullover-mit-zopfmuster-p01000099.html", "source": "manual",
           "manual": {"price": 45.0}}

    def added_his_own(self) -> None:
        """Before Zara went, Ada added a Zara jumper to her grey merino jumper by its link, and typed in its price."""
        with db.as_user(self.user_id("ada@example.com")):
            had = catalog.stored()
            had["candidates"].append(dict(self.OWN))
            catalog.save(had)

    def his_own(self) -> list[dict]:
        with db.as_user(self.user_id("ada@example.com")):
            return [c for c in db.get_catalog()["candidates"] if c["id"] == self.OWN["id"]]

    def test_what_he_added_from_a_store_that_went_is_set_aside_never_deleted(self):
        self.added_his_own()
        first = html.unescape(self.ada.get("/").get_data(as_text=True))
        self.assertIn("4 pieces were picked again", first, "his own Zara jumper was not his pick: the count is as it was")
        self.assertEqual(self.his_own(), [self.OWN], "kept in his account as he added it, his typed-in price too")

        # Hidden from picking, outfits and the shopping list: never among the piece's options.
        self.assertEqual(self.picks()["grey-merino-jumper"], ("auto", "weekday-1000000201", ["cos", "weekday"]))
        for path in ("/", "/outfits", "/list", "/list.md", "/list.csv", "/slots", "/slot/white-tee"):
            body = self.ada.get(path).get_data(as_text=True)
            self.assertNotIn("Zopfmuster", body, path)
            self.assertNotIn("no longer offers", body, path)

        # Listed on its piece's page, with what it is and a button to remove it.
        page = html.unescape(self.ada.get("/slot/grey-merino-jumper").get_data(as_text=True))
        listed = page[page.index('<section class="card set-aside"'):page.index('<section class="card add"')]
        self.assertIn("From a store Stilsmith no longer offers", words(listed))
        self.assertIn("Zara Pullover mit Zopfmuster 45 € Remove Pullover mit Zopfmuster", words(listed),
                      "its store, its name and the price he typed in, then Remove (its name heard with it)")
        self.assertIn("Zara has no partner programme, so Stilsmith keeps it for you but no longer offers it for this "
                      "piece or in your outfits. It comes back if the store is offered again.", words(listed))
        self.assertIn('action="/slot/grey-merino-jumper/remove"', listed)
        self.assertIn('name="candidate" value="zara-1000099"', listed)
        options = page[page.index('<ul class="cands">'):page.index('<section class="card set-aside"')]
        self.assertNotIn("Zopfmuster", options, "not among the options above it")

        # His data: in his copy of it.
        export = json.loads(self.ada.get("/account/export").get_data(as_text=True))
        self.assertIn(self.OWN["id"], [c["id"] for c in export["items_you_added"]])

        # Every later save keeps it: a link added to the same piece (catalog.update), another piece taken out of the
        # plan (sync_catalog, which rebuilds his products from the shared list).
        cos_link = "https://www.cos.com/de-de/men/product/pullover-aus-merinowolle-1000000101"
        self.post(self.ada, "/slot/grey-merino-jumper/import", urls=cos_link)
        self.post(self.ada, "/slots/white-tee/delete")
        self.assertEqual(self.his_own(), [self.OWN])
        self.assertIn("Pullover mit Zopfmuster", html.unescape(self.ada.get("/slot/grey-merino-jumper")
                                                               .get_data(as_text=True)))
        # Taking its own piece out of the plan takes it too: it belonged to that piece.
        self.post(self.ada, "/slots/grey-merino-jumper/delete")
        self.assertEqual(self.his_own(), [])

    def test_remove_takes_what_was_set_aside_out_of_his_account(self):
        self.added_his_own()
        self.ada.get("/")
        response = self.post(self.ada, "/slot/grey-merino-jumper/remove", candidate=self.OWN["id"])
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.his_own(), [])
        page = html.unescape(self.ada.get(response.headers["Location"]).get_data(as_text=True))
        self.assertIn("Removed “Pullover mit Zopfmuster”.", page)
        self.assertNotIn("no longer offers", page, "nothing left to list")
        self.assertEqual(self.post(self.ada, "/slot/grey-merino-jumper/remove", candidate=self.OWN["id"]).status_code,
                         404, "removed once")
        with db.as_user(self.user_id("ada@example.com")):
            self.assertEqual({c["store"] for c in db.get_catalog()["candidates"]}, {"cos", "weekday"})

    def test_what_was_set_aside_comes_back_when_its_store_is_offered_again(self):
        from wardrobe import programmes
        self.added_his_own()
        self.ada.get("/")
        real = programmes._stores()
        again = {**real, "zara": {**real["zara"], "programme": "awin"}}
        with mock.patch.object(programmes, "_stores", return_value=again):
            page = html.unescape(self.ada.get("/slot/grey-merino-jumper").get_data(as_text=True))
            self.assertNotIn("no longer offers", page)
            options = page[page.index('<ul class="cands">'):page.index('<section class="card add"')]
            self.assertIn("Pullover mit Zopfmuster", options, "among the piece's options again")
            self.assertIn("added by you", options)
            with db.as_user(self.user_id("ada@example.com")):
                view = selection.build().get("grey-merino-jumper")
                mine = next(c for c in view.cands if c.id == self.OWN["id"])
                self.assertEqual(mine.price, 45.0, "with the price he typed in")
        self.assertEqual(self.his_own(), [self.OWN])

    def published_again(self, stamp: str) -> None:
        """The owner imports a feed: the list is published again, the same products under a new date."""
        data = json.loads(self.on_disk)
        data["published_at"] = stamp
        self.listed.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        shared._cache = None        # read it again, even if the file's time did not move

    def test_what_was_set_aside_is_not_said_again_when_the_list_is_published_again(self):
        self.added_his_own()
        first = html.unescape(self.ada.get("/").get_data(as_text=True))
        self.assertIn("Zara has no partner programme, so Stilsmith no longer shows its products: 4 pieces were picked "
                      "again", first)
        picks = self.picks()
        self.published_again("2026-11-14T09:00:00.000000+01:00")
        with mock.patch.object(shared, "_picked_again", wraps=shared._picked_again) as counted:
            page = html.unescape(self.ada.get("/").get_data(as_text=True))
        self.assertNotIn("picked again", page, "nothing went since Zara, and Zara was said once")
        self.assertNotIn("zara", page.lower())
        counted.assert_not_called()
        with db.as_user(self.user_id("ada@example.com")):
            self.assertEqual(db.get_setting("pool"), "2026-11-14T09:00:00.000000+01:00#refused#cos,weekday",
                             "his products were rebuilt from the new publication")
        self.assertEqual(self.picks(), picks, "no piece was picked again")
        self.assertEqual(self.his_own(), [self.OWN], "still kept, set aside")

    def test_a_store_that_goes_later_is_named_alone(self):
        from wardrobe import programmes
        self.added_his_own()
        self.ada.get("/")                                  # Zara's message, said once
        real = programmes._stores()
        later = {**real, "weekday": {**real["weekday"], "programme": "none"}}
        with mock.patch.object(programmes, "_stores", return_value=later):
            page = html.unescape(self.ada.get("/").get_data(as_text=True))
            # The jumper had Weekday's (COS's is next) and the jeans had Weekday's (nothing is left for them).
            self.assertIn("Weekday has no partner programme, so Stilsmith no longer shows its products: 2 pieces were "
                          "picked again, and 1 has nothing in Stilsmith's product list yet.", page)
            self.assertNotIn("zara", page.lower(), "Zara went before, and was said then")
            self.assertEqual(self.picks(), {
                "grey-merino-jumper": ("auto", "cos-1000000101", ["cos"]),
                "white-tee": ("auto", "cos-1000000102", ["cos"]),
                "indigo-jeans": ("auto", None, []),
                "charcoal-wool-coat": ("auto", None, []),
            })
        self.assertEqual(self.his_own(), [self.OWN], "what he added from Zara is still kept")

    def test_an_owned_piece_locked_to_zara_stays_owned_its_lock_goes_and_it_is_not_counted(self):
        """What _stores_gone says it does: an owned piece is not picked again, but a lock to the gone store's product
        goes, so that the product is not his choice should he say he does not own it after all."""
        with db.as_user(self.user_id("ada@example.com")):
            db.update_slot("white-tee", owned=True)            # still locked to Zara's tee, from setUp
        first = html.unescape(self.ada.get("/").get_data(as_text=True))
        self.assertIn("Zara has no partner programme, so Stilsmith no longer shows its products: 3 pieces were picked "
                      "again, and 1 has nothing in Stilsmith's product list yet.", first)
        with db.as_user(self.user_id("ada@example.com")):
            tee = db.get_slot("white-tee")
        self.assertEqual((tee["owned"], tee["locked"], tee["pick"]), (True, False, None))


if __name__ == "__main__":
    unittest.main()
