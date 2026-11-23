"""The visitors' example wardrobe stays exactly as it is when the product list grows (config/site.toml,
example_locked): each piece is locked at start-up to the product it shows, so a bigger list, with a new store's
products in every piece's colour, changes none of its products or outfits, and so none of its pictures."""
import json
from unittest import mock

from wardrobe import colours, db, guests, paths, selection, shared
from wardrobe.app import create_app

from .test_guests import GuestCase
from .test_guests import LIST, PUBLISHED, STORES

BIGGER = "2026-11-22T23:00:00.000000+01:00"


class TheExampleStays(GuestCase):
    def example(self):
        """(each piece's product, the first 12 outfits' keys, each piece's number of options, its locks)."""
        with db.as_user(guests.example_id()):
            w = selection.build()
            picks = {v.slot["id"]: (v.chosen.id if v.chosen else None) for v in w.slots}
            first = [o.key for o, _ in guests.first_outfits(w, 12)]
            options = {v.slot["id"]: len(v.cands) for v in w.slots}
            locks = {s["id"]: (s["locked"], s["pick"]) for s in db.list_slots()}
        return picks, first, options, locks

    def publish_more(self):
        """A bigger list: the same COS and Weekday products, and a new store's, in the colour of every piece of the
        example, rated higher and cheaper than what it shows (so that, unlocked, "Best for budget" takes them)."""
        with db.as_user(guests.example_id()):
            slots = db.list_slots()
        extra = [{"id": f"suitsupply-{n}", "store": "suitsupply", "category": s["category"], "name": f"Piece {n}",
                  "price": 9.0, "colour": colours.get(s["colour"]).label, "composition_text": "100% Baumwolle",
                  "url": f"https://suitsupply.com/de-de/p/{n}", "image_url": "", "source": "collected",
                  "sizes_all": [], "sizes_in_stock": []} for n, s in enumerate(slots)]
        (paths.DATA_DIR / shared.POOL_NAME).write_text(json.dumps(
            {"published_at": BIGGER, "collected_at": "2026-11-22T22:00:00+01:00", "stores": STORES,
             "products": LIST + extra}, ensure_ascii=False), encoding="utf-8")

    def restart(self):
        self.app = create_app()
        self.visitor = self.app.test_client()

    def test_each_piece_is_locked_to_the_product_it_shows(self):
        picks, _, _, locks = self.example()
        shown = {key: value for key, value in picks.items() if value}
        self.assertTrue(shown)
        self.assertEqual({key: locks[key] for key in shown}, {key: (True, value) for key, value in shown.items()})

    def test_a_bigger_list_changes_none_of_its_products_or_outfits_only_its_options(self):
        before = self.example()
        self.publish_more()
        self.restart()
        after = self.example()
        self.assertEqual(after[0], before[0], "the same product on every piece")
        self.assertEqual(after[1], before[1], "the same first 12 outfits, so the same pictures and clips")
        self.assertTrue(all(after[2][key] >= before[2][key] for key in before[2]))
        self.assertGreater(sum(after[2].values()), sum(before[2].values()), "its options grew")

    def test_also_when_the_bigger_list_is_there_before_the_locks(self):
        # The order on a server where the new list is published before the code that locks first starts: the locks
        # are taken from the products the example showed until then, before it is given the new list.
        (paths.DATA_DIR / shared.POOL_NAME).unlink()
        with mock.patch.object(guests, "example_locked", return_value=False):
            (paths.DATA_DIR / shared.POOL_NAME).write_text(json.dumps(
                {"published_at": PUBLISHED, "collected_at": "2026-11-11T17:00:18+01:00", "stores": STORES,
                 "products": LIST}, ensure_ascii=False), encoding="utf-8")
            with db.as_user(guests.example_id()):
                for slot in db.list_slots():
                    db.update_slot(slot["id"], locked=False, pick=None)
            self.restart()
            before = self.example()
            self.assertFalse(any(locked for locked, _ in before[3].values()), "the code before the locks")
        self.publish_more()
        self.restart()
        after = self.example()
        self.assertEqual((after[0], after[1]), (before[0], before[1]))

    def test_without_the_switch_best_for_budget_picks_from_the_whole_list_again(self):
        before = self.example()
        self.publish_more()
        with mock.patch.object(guests, "example_locked", return_value=False):
            with db.as_user(guests.example_id()):
                for slot in db.list_slots():
                    db.update_slot(slot["id"], locked=False, pick=None)
            self.restart()
            after = self.example()
        self.assertNotEqual(after[0], before[0], "what the locks hold is what would otherwise change")

    def test_the_switch_is_on_and_says_what_it_does(self):
        self.assertTrue(guests.example_locked())
        text = (paths.CONFIG_DIR / "site.toml").read_text(encoding="utf-8")
        self.assertIn("example_locked = true", text)
        self.assertIn("publish COS's and Weekday's products as they are", " ".join(text.replace("#", " ").split()))
