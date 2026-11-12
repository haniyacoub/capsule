"""The app end to end, through its pages, on the demo data."""
import html
import re
import shutil
import tempfile
import unittest
from pathlib import Path

from wardrobe import capsule, catalog, colours, config, db, outfits, paths, selection, shared
from wardrobe import profile as profile_mod
from wardrobe.app import create_app, weblink

HX = {"HX-Request": "true"}


class AppCase(unittest.TestCase):
    def setUp(self):
        for path in (paths.DB_PATH, paths.CATALOG_PATH):   # a fresh first run for every test
            path.unlink(missing_ok=True)
        catalog._cache = None
        self.client = create_app().test_client()

    def post(self, url, **data):
        return self.client.post(url, data=data, headers=HX)

    def set_mode(self, mode, threshold=70):
        return self.post("/settings", mode=mode, threshold=threshold)

    def view(self, slot_id):
        return selection.build().get(slot_id)

    def first(self, category):
        return next(s for s in selection.build().slots if s.garment.key == category)


class Pages(AppCase):
    def test_every_page_renders(self):
        w = selection.build()
        urls = ["/", "/outfits", "/outfits?occasion=office&n=24&seed=7", "/slots", "/profile"]
        urls += [f"/slot/{s.slot['id']}" for s in w.slots]
        urls += [f"/slot/{w.slots[0].slot['id']}?sort=score"]
        for url in urls:
            self.assertEqual(self.client.get(url).status_code, 200, url)
        self.assertEqual(self.client.get("/slot/nope").status_code, 404)

    def test_first_run_is_demo_data_with_a_capsule(self):
        w = selection.build()
        self.assertEqual(w.source, "mock")
        self.assertTrue(15 <= len(w.slots) <= 20)
        self.assertEqual(w.n_unfilled, 0)
        self.assertIn(b"Demo data", self.client.get("/").data)

    def test_missing_images_fall_back_to_a_swatch(self):
        chinos = self.first("chinos")
        html = self.client.get(f"/slot/{chinos.slot['id']}").data.decode()
        self.assertIn('class="pic noimg"', html)          # Zara chinos have no image in the demo data
        self.assertEqual(self.client.get("/mock/img/tee.svg?c=1f2a44").status_code, 200)
        self.assertEqual(self.client.get("/mock/img/does-not-exist.jpg").status_code, 404)

    def test_buttons_from_another_site_are_refused(self):
        r = self.client.post("/settings", data={"mode": "cheapest"}, headers={"Origin": "http://evil.example"})
        self.assertEqual(r.status_code, 403)


class Selection(AppCase):
    def test_cheapest_takes_the_lowest_price_in_stock(self):
        self.set_mode("cheapest", 0)
        for s in selection.build().slots:
            in_stock = [c for c in s.cands if c.available]
            self.assertEqual(s.chosen.price, min(c.price for c in in_stock), s.slot["name"])

    def test_a_minimum_quality_takes_the_lowest_price_above_it(self):
        self.set_mode("cheapest", 80)
        for s in selection.build().slots:
            good = [c for c in s.cands if c.available and c.score.total >= 80]
            if good:
                self.assertGreaterEqual(s.chosen.score.total, 80, s.slot["name"])
                self.assertEqual(s.chosen.price, min(c.price for c in good), s.slot["name"])
                self.assertFalse(s.warn)
            else:   # nothing good enough: best available, flagged
                self.assertEqual(s.chosen.score.total, max(c.score.total for c in s.cands if c.available))
                self.assertTrue(s.warn)

    def test_impossible_threshold_still_fills_every_slot_with_a_warning(self):
        self.set_mode("cheapest", 100)
        w = selection.build()
        self.assertEqual(w.n_unfilled, 0)
        self.assertTrue(all(s.warn for s in w.slots))

    def test_toggle_updates_cards_and_summary_together(self):
        cheap = self.set_mode("cheapest", 0)
        cheap_total = selection.build().total
        good = self.set_mode("cheapest", 85)
        good_total = selection.build().total
        self.assertGreater(good_total, cheap_total)
        for r in (cheap, good):
            html = r.data.decode()
            self.assertIn('id="summary"', html)
            self.assertIn('hx-swap-oob="true"', html)
            self.assertIn('class="slot ', html)

    def test_total_is_price_times_quantity(self):
        w = selection.build()
        expected = sum(s.chosen.price * s.qty for s in w.slots)
        self.assertAlmostEqual(w.total, expected, places=2)
        self.assertAlmostEqual(w.remaining, w.budget - w.total, places=2)
        self.assertTrue(any(s.qty > 1 for s in w.slots))


class ManualControl(AppCase):
    def test_swapping_locks_the_choice_and_the_toggle_respects_it(self):
        self.set_mode("cheapest")
        s = self.first("knit")
        other = next(c for c in s.cands if c.available and c.id != s.chosen.id)
        r = self.post(f"/slot/{s.slot['id']}/pick?view=slot", candidate=other.id)
        self.assertEqual(r.status_code, 200)
        self.assertIn("Chosen and locked", r.data.decode())
        for mode, threshold in (("cheapest", 90), ("top", 70), ("medium", 0)):
            self.set_mode(mode, threshold)
            after = self.view(s.slot["id"])
            self.assertEqual((after.state, after.chosen.id), ("locked", other.id))

    def test_unlocking_hands_the_slot_back_to_the_toggle(self):
        self.set_mode("cheapest")
        s = self.first("coat")
        priciest = max((c for c in s.cands if c.available), key=lambda c: c.price)
        self.post(f"/slot/{s.slot['id']}/pick", candidate=priciest.id)
        self.assertEqual(self.view(s.slot["id"]).chosen.id, priciest.id)
        self.post(f"/slot/{s.slot['id']}/lock")            # tap the lock again
        after = self.view(s.slot["id"])
        self.assertEqual(after.state, "auto")
        self.assertEqual(after.chosen.id, s.chosen.id)

    def test_locking_freezes_the_automatic_pick(self):
        self.set_mode("cheapest", 85)
        s = self.first("shirt")
        self.post(f"/slot/{s.slot['id']}/lock")
        self.set_mode("top", 0)
        after = self.view(s.slot["id"])
        self.assertEqual((after.state, after.chosen.id), ("locked", s.chosen.id))

    def test_already_own_costs_nothing_and_can_be_undone(self):
        before = selection.build()
        s = self.first("coat")
        self.post(f"/slot/{s.slot['id']}/own")
        owned = selection.build()
        self.assertAlmostEqual(owned.total, before.total - s.cost, places=2)
        self.assertEqual(owned.n_owned, 1)
        self.assertEqual(owned.get(s.slot["id"]).cost, 0)
        self.post(f"/slot/{s.slot['id']}/own")
        self.assertAlmostEqual(selection.build().total, before.total, places=2)

    def test_choosing_something_that_is_not_a_candidate_is_refused(self):
        s = self.first("tee")
        self.assertEqual(self.post(f"/slot/{s.slot['id']}/pick", candidate="made-up").status_code, 404)

    def test_locked_item_that_left_the_catalogue_falls_back_with_a_warning(self):
        s = self.first("jeans")
        db.update_slot(s.slot["id"], locked=True, pick="gone-from-the-store")
        after = self.view(s.slot["id"])
        self.assertEqual(after.state, "auto")
        self.assertIsNotNone(after.chosen)
        self.assertTrue(after.warn)

    def test_no_size_in_stock_leaves_the_slot_unfilled_not_broken(self):
        profile_mod.save({**profile_mod.load(), "shoe": "49"})   # no store makes a 49
        w = selection.build()
        sneakers = next(s for s in w.slots if s.garment.key == "sneakers")
        self.assertIsNone(sneakers.chosen)
        self.assertEqual(sneakers.cost, 0)
        self.assertGreaterEqual(w.n_unfilled, 1)
        self.assertEqual(self.client.get("/").status_code, 200)
        self.assertEqual(self.client.get("/outfits").status_code, 200)


class SlotsAndProfile(AppCase):
    def test_add_edit_remove_a_slot(self):
        n = len(db.list_slots())
        self.client.post("/slots/add", data={"name": "", "category": "overshirt", "colour": "burgundy", "qty": "1"})
        slots = db.list_slots()
        self.assertEqual(len(slots), n + 1)
        new = slots[-1]
        self.assertEqual(new["name"], "Burgundy overshirt")       # named from colour + garment
        self.assertTrue(self.view(new["id"]).cands, "demo candidates appear for the new slot")

        self.post(f"/slot/{new['id']}/lock")
        self.client.post(f"/slots/{new['id']}/save",
                         data={"name": "Rust overshirt", "category": "overshirt", "colour": "rust", "qty": "2"})
        edited = db.get_slot(new["id"])
        self.assertEqual((edited["name"], edited["colour"], edited["qty"]), ("Rust overshirt", "rust", 2))
        self.assertFalse(edited["locked"], "a recoloured slot drops its old pick")

        self.client.post(f"/slots/{new['id']}/delete")
        self.assertEqual(len(db.list_slots()), n)

    def test_bad_slot_input_is_refused(self):
        r = self.client.post("/slots/add", data={"category": "cape", "colour": "navy"})
        self.assertEqual(r.status_code, 400)

    def test_saving_the_profile_rebuilds_the_plan_and_keeps_your_choices(self):
        form = {"top_size": "L", "waist": "34", "length": "32", "shoe": "44", "height_cm": "185",
                "weight_kg": "85", "budget": "900", "liked": "black, white, burgundy",
                "refused": "navy", "use": "everyday", "shoes": "on"}
        saved = self.client.post("/profile", data=form)
        self.assertEqual(saved.headers["Location"], "/outfits", "the new plan is shown on the model")
        prof = profile_mod.load()
        self.assertFalse(prof["example"])
        self.assertEqual((prof["top_size"], prof["budget"], prof["outerwear"]), ("L", 900, False))
        colours_used = {s["colour"] for s in db.list_slots()}
        self.assertIn("black", colours_used)
        self.assertIn("burgundy", colours_used)
        self.assertNotIn("navy", colours_used)
        self.assertFalse({s["category"] for s in db.list_slots()} & {"coat", "jacket"})
        self.assertEqual(selection.build().budget, 900)

        # A product chosen by hand no longer freezes the plan: the next change rebuilds it, and keeps
        # the choice, because a white tee is in the new plan too.
        tee = self.view("white-tee")
        other = next(c for c in tee.cands if c.available and c.id != tee.chosen.id)
        self.post("/slot/white-tee/pick", candidate=other.id)
        self.client.post("/profile", data={**form, "liked": "grey, white", "refused": ""})
        colours_used = {s["colour"] for s in db.list_slots()}
        self.assertIn("grey", colours_used)
        self.assertNotIn("burgundy", colours_used, "the plan follows the new answers")
        after = self.view("white-tee")
        self.assertEqual((after.state, after.chosen.id), ("locked", other.id), "the choice made by hand is kept")
        self.assertIn("Kept your 1 hand-picked piece.", self.client.get("/outfits").data.decode())

    def test_budget_change_alone_keeps_everything(self):
        s = self.first("coat")
        current = profile_mod.load()
        form = {"top_size": current["top_size"], "waist": current["waist"], "length": current["length"],
                "shoe": current["shoe"], "height_cm": current["height_cm"], "weight_kg": current["weight_kg"],
                "budget": "2000", "liked": "navy, grey, white, olive", "refused": "", "use": "both",
                "shoes": "on", "outerwear": "on", "owned": ""}
        before = [x["id"] for x in db.list_slots()]
        self.client.post("/profile", data=form)
        self.assertEqual([x["id"] for x in db.list_slots()], before)
        self.assertEqual(selection.build().budget, 2000)
        self.assertEqual(self.view(s.slot["id"]).chosen.id, s.chosen.id)


class RebuildingThePlan(AppCase):
    """Saving new colours, uses or owned things rebuilds the plan and keeps what was picked or marked as
    owned by hand. Only a plan changed on the plan page itself is left as it is, until you start over."""

    NEW = {"liked": "black, grey, white", "use": "office"}

    def profile_form(self, **changes) -> dict:
        """The Profile form as the page sends it: today's answers with these changes (None unticks a box)."""
        p = profile_mod.load()

        def names(keys):
            return ", ".join(colours.get(k).label.lower() for k in keys)

        form = {"top_size": p["top_size"], "waist": p["waist"], "length": p["length"], "shoe": p["shoe"],
                "height_cm": p["height_cm"], "weight_kg": p["weight_kg"], "budget": p["budget"],
                "liked": names(p["liked"]), "refused": names(p["refused"]), "use": p["use"], "owned": p["owned"],
                "shoes": "on" if p["shoes"] else None, "outerwear": "on" if p["outerwear"] else None}
        form.update(changes)
        return {k: v for k, v in form.items() if v is not None}

    def save_profile(self, **changes):
        return self.client.post("/profile", data=self.profile_form(**changes))

    def messages(self, url="/outfits") -> str:
        """What the next page says at the top, as the customer reads it (links kept as tags)."""
        page = self.client.get(url).data.decode()
        return " | ".join(html.unescape(m) for m in re.findall(r'<p class="flash" role="status">(.*?)</p>', page, re.S))

    def test_a_swap_in_an_outfit_no_longer_stops_the_profile_from_applying(self):
        outfit = next(o for o in outfits.generate(selection.build(), limit=12)[0] if "white-tee" in o.slots)
        tee = self.view("white-tee")
        other = next(c for c in tee.cands if c.available and c.id != tee.chosen.id)
        swapped = self.post("/slot/white-tee/pick", candidate=other.id, outfit=outfit.sig)
        self.assertIn("/outfits?at=", swapped.headers["Location"], "swapped from inside the outfit")

        saved = self.save_profile(**self.NEW)
        self.assertEqual(saved.headers["Location"], "/outfits", "the new plan is shown on the model")
        used = {s["colour"] for s in db.list_slots()}
        self.assertTrue({"black", "grey", "white"} <= used, used)
        self.assertFalse(used & {"navy", "olive", "indigo", "dark-brown"}, "the example's other colours are gone")
        pieces = sum(s["qty"] for s in db.list_slots())
        self.assertEqual(self.messages(), f"Your plan now has {pieces} pieces in your colours. Kept your 1 hand-picked piece.")
        self.assertEqual(self.view("white-tee").chosen.id, other.id)

    def test_a_kept_choice_keeps_its_product_and_lock_and_owned_pieces_stay_owned(self):
        jumper = self.view("grey-merino-jumper")
        self.post("/slot/grey-merino-jumper/lock")          # freeze what the price level picked
        self.post("/slot/navy-tee/own")                      # "Own it" on the Wardrobe page
        self.save_profile(**self.NEW)
        after = self.view("grey-merino-jumper")
        self.assertEqual((after.state, after.chosen.id), ("locked", jumper.chosen.id))
        tees = [(s.slot["colour"], s.qty, s.state) for s in selection.build().slots if s.garment.key == "tee"]
        self.assertEqual(tees, [("white", 1, "auto"), ("navy", 1, "owned")],
                         "the navy tee you own takes the place of one of the two white tees, not both")
        self.assertIn("Kept your 1 hand-picked piece and the 1 you own.", self.messages())

    def test_a_choice_that_no_longer_fits_is_named(self):
        for slot_id in ("navy-merino-jumper", "indigo-jeans"):
            self.post(f"/slot/{slot_id}/lock")
        self.save_profile(**self.NEW)
        self.assertIn("Not kept: Navy merino jumper (not in your new colours), Indigo jeans (not in your new plan).",
                      self.messages())
        self.assertNotIn("Kept your", self.messages())
        self.assertFalse(any(s["locked"] for s in db.list_slots()))

    def test_a_kept_piece_keeps_its_id_so_its_product_is_still_on_offer(self):
        trousers = self.view("charcoal-tailored-trousers")
        other = next(c for c in trousers.cands if c.available and c.id != trousers.chosen.id)
        self.post("/slot/charcoal-tailored-trousers/pick", candidate=other.id)
        self.assertIn("charcoal-wool-trousers", [s["id"] for s in capsule.propose(
            {**profile_mod.load(), "liked": ["navy", "charcoal"]})[0]], "a fresh proposal names it differently")
        self.save_profile(liked="navy, charcoal")
        self.assertNotIn("charcoal-wool-trousers", [s["id"] for s in db.list_slots()])
        after = self.view("charcoal-tailored-trousers")
        self.assertEqual((after.state, after.chosen.id), ("locked", other.id))

    def test_a_kept_choice_that_left_the_catalogue_is_said_not_kept(self):
        db.update_slot("white-tee", locked=True, pick="gone-from-the-store")
        self.save_profile(**self.NEW)
        self.assertIn("Not kept: White tee (no longer in Capsule's product list).", self.messages())
        self.assertFalse(db.get_slot("white-tee")["locked"])

    def test_owned_lines_follow_the_profile_and_owned_marks_stay(self):
        self.save_profile(owned="white leather sneakers")
        self.assertTrue(db.get_slot("white-leather-sneakers")["owned"])
        self.post("/slot/stone-chinos/own")                  # marked by hand on the Wardrobe page
        self.save_profile(owned="", liked="black, grey, white")
        self.assertFalse(db.get_slot("white-leather-sneakers")["owned"], "a line deleted from the profile")
        self.assertTrue(db.get_slot("stone-chinos")["owned"], "a piece marked as owned by hand")
        self.assertIn("Kept the 1 piece you own.", self.messages())

    def test_something_owned_never_takes_the_place_of_a_piece_picked_by_hand(self):
        old, _ = capsule.propose(profile_mod.EXAMPLE)
        next(s for s in old if s["id"] == "white-tee").update(locked=True, pick="my-white-tee")
        plan = capsule.rebuild({**profile_mod.EXAMPLE, "use": "office", "owned": "black tee"}, old)
        tees = [(s["name"], s["qty"], s["owned"], s.get("pick")) for s in plan.slots if s["category"] == "tee"]
        self.assertEqual(tees, [("White tee", 2, False, "my-white-tee"), ("Black tee", 1, True, None)])
        self.assertEqual([s["id"] for s in plan.picked], ["white-tee"])
        # Without a choice made by hand, the black tee takes the place of one of the two white ones.
        slots, _ = capsule.propose({**profile_mod.EXAMPLE, "use": "office", "owned": "black tee"})
        self.assertEqual([(s["name"], s["qty"], s["owned"]) for s in slots if s["category"] == "tee"],
                         [("White tee", 1, False), ("Black tee", 1, True)])

    def test_a_plan_edited_on_the_plan_page_is_never_rebuilt_without_asking(self):
        coat = db.get_slot("charcoal-wool-coat")
        self.client.post("/slots/charcoal-wool-coat/save", data={"name": "My charcoal coat", "category": coat["category"],
                                                                 "colour": coat["colour"], "qty": coat["qty"]})
        before = db.list_slots()
        saved = self.save_profile(**self.NEW)
        self.assertTrue(saved.headers["Location"].endswith("/profile"), "it stays on the profile")
        self.assertEqual(db.list_slots(), before, "the plan is exactly as it was edited")
        self.assertIn('Profile saved. Your plan stays as you edited it. To rebuild it from these answers, use '
                      '“Start over from my profile” on <a href="/slots">the plan page</a>.', self.messages("/profile"))
        self.assertIn("Start over from my profile</button>", self.client.get("/slots").data.decode(),
                      "the button the message names")
        self.client.post("/slots/repropose")                # Start over from my profile
        self.assertEqual(self.save_profile(liked="navy, grey").headers["Location"], "/outfits",
                         "after starting over, profile changes apply again")

    def test_adding_recolouring_or_removing_a_piece_counts_as_editing_the_plan(self):
        liked = iter(["black, grey, white", "navy, grey", "black, white", "grey, white"])

        def plan_stays(what):
            before = db.list_slots()
            self.assertTrue(self.save_profile(liked=next(liked)).headers["Location"].endswith("/profile"), what)
            self.assertEqual(db.list_slots(), before, what)
            self.client.post("/slots/repropose")             # start over for the next one

        self.client.post("/slots/add", data={"name": "", "category": "overshirt", "colour": "rust", "qty": "1"})
        plan_stays("a piece added")
        first = db.list_slots()[0]
        self.client.post(f"/slots/{first['id']}/save", data={"name": first["name"], "category": first["category"],
                                                             "colour": "rust", "qty": first["qty"]})
        plan_stays("a piece recoloured")
        self.client.post(f"/slots/{db.list_slots()[-1]['id']}/delete")
        plan_stays("a piece removed")
        same = db.list_slots()[0]
        self.client.post(f"/slots/{same['id']}/save", data={k: same[k] for k in ("name", "category", "colour", "qty", "keywords")})
        self.assertEqual(self.save_profile(liked=next(liked)).headers["Location"], "/outfits",
                         "pressing Save on the plan page without changing anything is no edit")

    def test_sizes_or_budget_alone_stay_on_the_profile(self):
        self.post("/slot/white-oxford-shirt/lock")
        before = db.list_slots()
        saved = self.save_profile(budget="2000", top_size="L")
        self.assertTrue(saved.headers["Location"].endswith("/profile"))
        self.assertEqual(db.list_slots(), before, "every piece, choice and lock as it was")
        self.assertEqual(self.messages("/profile"), 'Profile saved. <a href="/outfits">See your outfits</a>')

    def test_an_older_account_that_only_picked_things_gets_its_profile_applied(self):
        # Before plan_edited, one setting stood for every change made by hand, and new answers saved
        # after a lock or a swap were never applied. Such a plan is still the example's: rebuilt now.
        self.post("/slot/charcoal-wool-coat/lock")
        db.set_setting("slots_customised", True)
        profile_mod.save({**profile_mod.load(), "example": False, "liked": ["black", "white"]})   # saved, ignored
        self.assertEqual(self.save_profile(**self.NEW).headers["Location"], "/outfits")
        self.assertIn("black", {s["colour"] for s in db.list_slots()})
        self.assertEqual(self.view("charcoal-wool-coat").state, "locked")
        self.assertIs(db.get_setting("plan_edited"), False)

    def test_an_older_account_with_a_plan_edited_by_hand_keeps_it(self):
        db.update_slot("charcoal-wool-coat", name="My charcoal coat")       # edited before plan_edited existed
        db.set_setting("slots_customised", True)
        before = db.list_slots()
        self.assertTrue(self.save_profile(**self.NEW).headers["Location"].endswith("/profile"))
        self.assertEqual(db.list_slots(), before)
        self.assertIs(db.get_setting("plan_edited"), True)


class PiecesWithNothingToBuy(AppCase):
    """A piece the product list has nothing for says so, and offers the colours Capsule has in one tap
    (the published list is tested in test_production.py; this is your own machine)."""

    @staticmethod
    def collected(slot_id, sku, colour):
        return {"id": f"zara-{sku}", "slot_id": slot_id, "store": "zara", "name": "Pullover", "slug": "pullover",
                "price": 39.95, "colour": colour, "colour_hex": None, "sizes_all": ["M"], "sizes_in_stock": ["M"],
                "url": "https://www.zara.com/de/", "image_url": "", "source": "collected"}

    def test_on_your_own_machine_the_colours_on_offer_are_those_collected(self):
        catalog.save({"source": "collected", "collected_at": "2026-11-11T17:00:00+01:00", "stores": {}, "candidates": [
            self.collected("grey-merino-jumper", "1", "Grau"), self.collected("navy-merino-jumper", "2", "Marineblau"),
            {**self.collected("navy-merino-jumper", "3", "Schwarz"), "source": "manual"}]})     # yours: not on offer
        on_offer = shared.colours_on_offer("knit")
        ids = {key: {product["id"] for product in products} for key, products in on_offer.items()}
        self.assertEqual((ids["grey"], ids["navy"]), ({"zara-1"}, {"zara-2"}))
        self.assertNotIn("black", on_offer)
        self.assertEqual(shared.colours_on_offer("coat"), {})

        # A black jumper added on the plan page could only copy one of the two: nothing is offered, and it says why,
        # truly: Capsule's grey and navy knitwear is there, as the grey and the navy jumper.
        self.client.post("/slots/add", data={"name": "", "category": "knit", "colour": "black", "qty": "1"})
        jumper = selection.build().get("black-jumper")
        self.assertEqual((jumper.note, jumper.offers), ("Not in Capsule's product list in black yet", []))
        page = html.unescape(self.client.get("/slot/black-jumper").data.decode())
        self.assertIn("Capsule's knitwear in other colours you wear is already in your plan, so this piece is left out "
                      "of your outfits and your total.", page)
        self.assertNotIn("Capsule has no knitwear", page)
        self.assertIn("python -m wardrobe refresh --slot black-jumper", page)
        self.assertIn("Capsule has no coats yet", html.unescape(self.client.get("/").data.decode()))
        self.assertEqual(self.client.post("/slot/black-jumper/colour", data={"colour": "grey"}).status_code, 409)

    def test_a_new_colour_renames_a_piece_named_after_its_colour(self):
        from wardrobe.app import recoloured_name
        self.assertEqual(recoloured_name("Black wool blazer", "black", "navy"), "Navy wool blazer")
        self.assertEqual(recoloured_name("Light grey tee", "light-grey", "navy"), "Navy tee")
        self.assertEqual(recoloured_name("Black tee", "black", "light-grey"), "Light grey tee")
        self.assertEqual(recoloured_name("black tee", "black", "green"), "forest green tee")
        self.assertEqual(recoloured_name("My lucky blazer", "black", "navy"), "My lucky blazer")
        self.assertEqual(recoloured_name("Blackwatch shirt", "black", "navy"), "Blackwatch shirt")

    def test_the_demo_has_something_for_every_piece(self):
        w = selection.build()
        self.assertEqual((w.n_missing, w.n_no_size, w.n_no_price, w.unfilled_words), (0, 0, 0, []))
        self.assertFalse([s.slot["name"] for s in w.slots if s.offers or s.left_out])
        self.assertNotIn("not in the product list", self.client.get("/").data.decode())


class Outfits(AppCase):
    def test_outfits_are_complete_and_coherent(self):
        w = selection.build()
        boards, total = outfits.generate(w, limit=24)
        self.assertEqual(len(boards), 24)
        self.assertGreater(total, 24)
        order = ["outer", "mid", "top", "bottom", "shoes"]
        for o in boards:
            layers = [("mid" if p.layer == "top" and i < len(o.pieces) - 1 and o.pieces[i + 1].layer == "top"
                       else p.layer) for i, p in enumerate(o.pieces)]
            self.assertEqual(layers, sorted(layers, key=order.index), "top-to-bottom order")
            self.assertIn("bottom", layers)
            self.assertIn("top", layers)
            self.assertIn("shoes", layers)
            accents = {p.colour.family for p in o.pieces if not p.colour.neutral}
            self.assertLessEqual(len(accents), 1)
            low = max(p.view.garment.formality[0] for p in o.pieces)
            high = min(p.view.garment.formality[1] for p in o.pieces)
            self.assertLessEqual(low, high)

    def test_every_piece_gets_an_outing(self):
        w = selection.build()
        boards, _ = outfits.generate(w, limit=24)
        shown = {p.view.slot["id"] for o in boards for p in o.pieces}
        self.assertEqual(shown, {s.slot["id"] for s in w.slots})

    def test_occasion_filter_and_shuffle(self):
        w = selection.build()
        office, _ = outfits.generate(w, occasion="office", limit=12)
        everyday, _ = outfits.generate(w, occasion="everyday", limit=12)
        self.assertTrue(all(o.level >= 3 for o in office))
        self.assertTrue(all(o.level <= 3 for o in everyday))
        a, _ = outfits.generate(w, limit=12, seed=1)
        b, _ = outfits.generate(w, limit=12, seed=2)
        self.assertNotEqual([o.key for o in a], [o.key for o in b])
        again, _ = outfits.generate(w, limit=12, seed=1)
        self.assertEqual([o.key for o in a], [o.key for o in again])

    def test_owned_pieces_still_appear_in_outfits(self):
        s = self.first("sneakers")
        self.post(f"/slot/{s.slot['id']}/own")
        boards, _ = outfits.generate(selection.build(), limit=12)
        owned = [p for o in boards for p in o.pieces if p.owned]
        self.assertTrue(owned)
        self.assertTrue(all(p.price == 0 for p in owned))
        self.assertIn(b"Owned", self.client.get("/outfits").data)


class EditingTheRules(AppCase):
    """config/scoring.toml is meant to be edited by hand — on a copy here."""

    def setUp(self):
        super().setUp()
        self.real_dir = config.CONFIG_DIR
        self.tmp = Path(tempfile.mkdtemp(prefix="capsule-config-"))
        shutil.copytree(self.real_dir, self.tmp / "config")
        config.CONFIG_DIR = self.tmp / "config"
        config._cache.clear()

    def tearDown(self):
        config.CONFIG_DIR = self.real_dir
        config._cache.clear()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def edit(self, old, new):
        path = config.CONFIG_DIR / "scoring.toml"
        text = path.read_text(encoding="utf-8")
        self.assertIn(old, text)
        path.write_text(text.replace(old, new), encoding="utf-8")

    def test_a_rule_change_applies_on_the_next_page_load(self):
        knit = self.first("knit")
        merino = next(c for c in knit.cands if c.fabric == "100% merino")
        self.edit("merino    = 100", "merino    = 40")
        again = next(c for c in self.view(knit.slot["id"]).cands if c.id == merino.id)
        self.assertLess(again.score.total, merino.score.total - 20)

    def test_a_typo_gets_a_readable_page_not_a_crash(self):
        self.edit("[weights]", "[weights")
        r = self.client.get("/")
        self.assertEqual(r.status_code, 500)
        self.assertIn(b"config/scoring.toml has a syntax error", r.data)

    def test_a_nonsense_value_is_named(self):
        self.edit("polyester      = 25", 'polyester      = "low"')
        r = self.client.get("/")
        self.assertEqual(r.status_code, 500)
        self.assertIn(b"fabric.fibres.polyester must be a number", r.data)

    def test_price_bands_must_be_in_order(self):
        self.edit("fair             = [12, 40]", "fair             = [70, 40]")
        r = self.client.get("/")
        self.assertEqual(r.status_code, 500)
        self.assertIn(b"price.bands.tee", r.data)


class Safety(AppCase):
    def test_only_web_addresses_become_links(self):
        self.assertEqual(weblink("https://www.cos.com/de-de/x"), "https://www.cos.com/de-de/x")
        self.assertEqual(weblink("javascript:alert(1)"), "#")
        self.assertEqual(weblink(None), "#")

    def test_try_on_is_an_extension_point_not_a_feature(self):
        self.assertNotIn(b"Try on", self.client.get("/outfits").data)
        self.assertEqual(self.client.post("/outfits/tryon").status_code, 501)

    def test_unpriced_items_are_never_picked_automatically(self):
        s = self.first("coat")
        data = catalog.load()
        for cand in data["candidates"]:
            if cand["id"] == s.chosen.id:
                cand["price"] = 0
        catalog.save(data)
        self.set_mode("cheapest")
        after = self.view(s.slot["id"])
        self.assertNotEqual(after.chosen.id, s.chosen.id)
        self.assertGreater(after.chosen.price, 0)


class DemoData(AppCase):
    def test_rebuilding_keeps_ids_stable_so_locks_survive(self):
        from wardrobe import mock
        first = [c["id"] for c in mock.build(db.list_slots())["candidates"]]
        second = [c["id"] for c in mock.build(db.list_slots())["candidates"]]
        self.assertEqual(first, second)
        self.assertEqual(len(first), len(set(first)))

    def test_demo_rebuild_never_overwrites_collected_data(self):
        from wardrobe.__main__ import main
        data = catalog.load()
        catalog.save({**data, "source": "collected"})
        with self.assertRaises(SystemExit):
            main(["mock"])
        self.assertEqual(catalog.load()["source"], "collected")


if __name__ == "__main__":
    unittest.main()
