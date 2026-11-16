"""The wardrobe is the outfits the customer said yes to (wardrobe/yes.py).

A new customer answers a short welcome and is then offered outfits one at a time. "Add to my wardrobe" is a yes,
"Not for me" a no. His wardrobe is the pieces of the outfits he said yes to: the Wardrobe page, the shopping list,
its files and the budget bar count those and nothing else. Each outfit on offer says what it would add, the ones
that reuse his pieces come first, and taking an outfit out removes only the pieces no other outfit of his wears.
Someone who was a customer before this loses nothing: what he had becomes a truthful start (db.py, version 9).
"""
import csv
import html
import io
import json
import re
import sqlite3
from contextlib import closing

from wardrobe import db, outfits, paths, selection, yes
from wardrobe import profile as profile_mod
from wardrobe.app import eur

from .test_app import HX, AppCase
from .test_production import ProductionCase, words


def read(page: str) -> str:
    """A page as the customer reads it (a no-break space reads as a space)."""
    return html.unescape(words(page))


def plain(text: str) -> str:
    """Words with their no-break spaces as spaces, to look for in what `read` gives."""
    return text.replace("\xa0", " ")


class YesCase(AppCase):
    def page(self, url, **query) -> str:
        return self.client.get(url, query_string=query or None).data.decode()

    def offered(self, **query) -> list[str]:
        """The outfits on the Outfits page, in the order shown: which pieces each combines."""
        return [html.unescape(sig) for sig in
                re.findall(r'<form class="no" method="post" action="/outfits/no">.*?name="sig" value="([^"]*)"',
                           self.page("/outfits", **query), re.S)]

    def say_yes(self, outfit, **more):
        return self.client.post("/outfits/save", data={"key": outfit.key, "sig": outfit.sig, "want": "save", **more})

    def take_out(self, outfit, **more):
        return self.client.post("/outfits/save", data={"key": outfit.key, "sig": outfit.sig, "want": "remove", **more})

    def say_no(self, outfit, **more):
        return self.client.post("/outfits/no", data={"sig": outfit.sig, **more})

    def every(self) -> list:
        return outfits.all_outfits(selection.build())

    def two_that_share(self):
        """Two outfits with some pieces in common and some not, and none of them wanted twice."""
        every = [o for o in self.every() if all(p.view.qty == 1 for p in o.pieces)]
        for a in every:
            for b in every:
                shared = set(a.slots) & set(b.slots)
                if shared and set(a.slots) - shared and set(b.slots) - shared:
                    return a, b
        self.fail("the demo plan has no two outfits that share only some pieces")

    def mine(self) -> set[str]:
        return {view.slot["id"] for view in selection.build().mine.slots}


class BeforeAnyYes(YesCase):
    def test_his_wardrobe_is_empty_and_every_page_says_so_and_leads_to_the_outfits(self):
        w = selection.build()
        self.assertTrue(w.slots, "the plan has pieces: outfits are made from them")
        self.assertEqual((w.mine.slots, w.mine.total, w.n_outfits), ([], 0, 0))
        wardrobe = self.page("/")
        self.assertIn("Your wardrobe is empty. It holds the pieces of the outfits you say yes to.", read(wardrobe))
        self.assertIn('<a class="btn" href="/outfits">See the outfits</a>', wardrobe)
        self.assertNotIn('class="slot ', wardrobe, "no card of a piece he did not say yes to")
        self.assertNotIn("€", read(wardrobe), "no figure that reads as a price or a total of his")
        shopping = self.page("/list")
        self.assertIn("Nothing on your list yet. It lists the pieces of the outfits you say yes to.", read(shopping))
        self.assertIn('<a class="btn" href="/outfits">See the outfits</a>', shopping)
        self.assertNotIn('<li class="buy">', shopping)
        for url in ("/", "/list", "/outfits", "/profile"):
            bar = re.search(r'<section id="summary".*?</section>', self.page(url), re.S).group(0)
            self.assertIn("Your wardrobe: nothing yet", read(bar), url)
            self.assertNotIn("€", read(bar), url)
        rows = list(csv.DictReader(io.StringIO(self.client.get("/list.csv").data.decode("utf-8-sig"))))
        self.assertEqual(rows, [], "the file to download lists nothing either")

    def test_each_outfit_says_what_it_would_add_and_has_the_two_answers(self):
        page = self.page("/outfits")
        shown = self.offered()
        self.assertEqual(len(shown), 12)
        w = selection.build()
        first = outfits.find_by_sig(w, shown[0])
        adds = yes.adds(w, first)
        self.assertEqual((adds.have, adds.in_wardrobe, adds.over_by), ([], False, 0))
        self.assertEqual([view.slot["id"] for view in adds.new], list(first.slots))
        self.assertAlmostEqual(adds.cost, sum(p.view.chosen.price * p.view.qty for p in first.pieces), places=2)
        self.assertTrue(adds.words.startswith(f"{adds.n_new} new pieces {eur(adds.cost)}"), adds.words)
        self.assertIn(f'<p class="adds">{html.escape(adds.words)}</p>', page)
        self.assertEqual(page.count("<span>Add to my wardrobe</span>"), 12)
        self.assertEqual(page.count(">Not for me</button>"), 12)
        self.assertIn(f'<span class="plus">+ {eur(adds.cost)}</span>', page, "the button says what the yes adds")
        self.assertNotIn("come first", page, "nothing to reuse yet, so no line about the order")
        self.assertNotIn("over your budget", page, "he has given no budget")

    def test_a_piece_the_plan_wants_twice_is_counted_twice_and_the_line_says_so(self):
        w = selection.build()
        outfit = next(o for o in outfits.all_outfits(w) if any(p.view.qty == 2 for p in o.pieces))
        adds = yes.adds(w, outfit)
        twice = next(p.view for p in outfit.pieces if p.view.qty == 2)
        self.assertEqual(adds.n_new, len(outfit.pieces) + 1)
        self.assertIn(f"(2 × {twice.slot['name']})", adds.words)
        self.assertAlmostEqual(adds.cost, outfit.cost + twice.chosen.price, places=2)
        self.say_yes(outfit)
        self.assertAlmostEqual(selection.build().mine.total, adds.cost, places=2, msg="what the line said is what the bar counts")


class SayingYes(YesCase):
    def test_a_yes_puts_the_outfits_pieces_into_his_wardrobe_and_nothing_else(self):
        outfit = outfits.find_by_sig(selection.build(), self.offered()[0])
        said = yes.adds(selection.build(), outfit)
        answer = self.say_yes(outfit)
        self.assertEqual(answer.headers["Location"], f"/outfits?added={outfit.key}")
        w = selection.build()
        self.assertEqual(self.mine(), set(outfit.slots))
        self.assertEqual((w.n_outfits, db.yes_sigs()), (1, [outfit.sig]))
        self.assertAlmostEqual(w.mine.total, said.cost, places=2)
        page = self.page(answer.headers["Location"])
        self.assertIn(plain(f"Added “{outfit.label}” to your wardrobe: {said.words[0].lower()}{said.words[1:]}. Undo"),
                      read(page))
        self.assertIn("My outfits 1</a>", page)
        self.assertNotIn(outfit.sig, self.offered(), "an outfit he answered is not offered again")
        # The Wardrobe page, the shopping list and its files hold those pieces, and the bar their total.
        wardrobe = self.page("/")
        self.assertEqual(set(re.findall(r'id="card-([\w-]+)"', wardrobe)), set(outfit.slots))
        bar = read(re.search(r'<section id="summary".*?</section>', wardrobe, re.S).group(0))
        self.assertIn(plain(f"Total {eur(w.mine.total)}"), bar)
        self.assertIn("· 1 outfit", bar)
        shopping = self.page("/list")
        self.assertEqual(len(re.findall(r'<li class="buy">', shopping)), len(outfit.pieces))
        rows = list(csv.DictReader(io.StringIO(self.client.get("/list.csv").data.decode("utf-8-sig"))))
        self.assertEqual({row["slot"] for row in rows}, {p.view.slot["name"] for p in outfit.pieces})
        self.assertIn(plain(eur(w.mine.total)), read(shopping))

    def test_the_next_outfits_say_what_is_new_and_what_he_has_and_those_that_reuse_most_come_first(self):
        a, b = self.two_that_share()
        self.say_yes(a)
        w = selection.build()
        b = outfits.find_by_sig(w, b.sig)       # (the same outfit, of the wardrobe as it is now)
        adds = yes.adds(w, b)
        shared = [slot_id for slot_id in b.slots if slot_id in a.slots]
        self.assertEqual([view.slot["id"] for view in adds.have], shared)
        self.assertEqual([view.slot["id"] for view in adds.new], [s for s in b.slots if s not in a.slots])
        self.assertAlmostEqual(adds.cost, sum(p.view.chosen.price for p in b.pieces if p.view.slot["id"] not in a.slots), places=2)
        self.assertLess(adds.cost, b.cost, "he pays less for it than its price: he has some of it already")
        n_new, n_have = len(b.slots) - len(shared), len(shared)
        self.assertEqual(adds.words, f"{n_new} new {'piece' if n_new == 1 else 'pieces'} {eur(adds.cost)}, "
                                     f"{n_have} already in your wardrobe")
        page = self.page("/outfits", at=b.sig)
        self.assertIn(f'<p class="adds">{html.escape(adds.words)}</p>', page)
        self.assertIn(f'<b class="board-cost" title="What the pieces in this outfit cost together">{eur(b.cost)}</b>', page)
        # The order: the more of his pieces an outfit wears, the earlier it is offered, and the page says why.
        have = set(a.slots)
        reused = [len(have & set(sig.split("~"))) for sig in self.offered()]
        self.assertEqual(reused, sorted(reused, reverse=True))
        self.assertGreater(reused[0], 0)
        self.assertIn("outfits that use pieces you already have come first", read(self.page("/outfits")))

    def test_a_piece_he_owns_is_one_he_has_and_costs_nothing(self):
        outfit = outfits.find_by_sig(selection.build(), self.offered()[0])
        owned = outfit.slots[0]
        self.post(f"/slot/{owned}/own")
        w = selection.build()
        outfit = outfits.find_by_sig(w, outfit.sig)
        adds = yes.adds(w, outfit)
        self.assertEqual([view.slot["id"] for view in adds.have], [owned])
        self.assertAlmostEqual(adds.cost, sum(p.view.cost for p in outfit.pieces if p.view.slot["id"] != owned), places=2)
        self.assertEqual(self.mine(), {owned}, "what he owns is in his wardrobe")
        self.assertEqual(w.mine.total, 0)

    def test_every_piece_already_his_adds_nothing(self):
        # An outfit with a coat, and the same outfit without it: after a yes to the first, the second adds nothing.
        every = self.every()
        big, small = next((a, b) for a in every for b in every if set(b.slots) < set(a.slots))
        self.say_yes(big)
        w = selection.build()
        adds = yes.adds(w, outfits.find_by_sig(w, small.sig))
        self.assertEqual((adds.cost, adds.new, adds.over_words), (0, [], ""))
        self.assertEqual(adds.words, f"Nothing new to buy: all {len(small.slots)} pieces are already in your wardrobe")
        self.assertIn(f'<span class="plus">+ {eur(0)}</span>', self.page("/outfits", at=small.sig))

    def test_a_piece_says_how_many_of_his_outfits_wear_it(self):
        a, b = self.two_that_share()
        self.say_yes(a)
        self.say_yes(b)
        in_both = next(s for s in a.slots if s in b.slots)
        only_a = next(s for s in a.slots if s not in b.slots)
        other = next(view.slot["id"] for view in selection.build().slots if not view.mine)
        self.assertEqual(self.view(in_both).in_outfits_words, "In 2 of your outfits")
        self.assertEqual(self.view(only_a).in_outfits_words, "In 1 of your outfits")
        wardrobe = self.page("/")
        card = re.search(rf'<article class="slot[^"]*" id="card-{in_both}">(.*?)</article>', wardrobe, re.S).group(1)
        self.assertIn('<span class="in-outfits">In 2 of your outfits</span>', card)
        self.assertIn('<p class="in-outfits">In 2 of your outfits.</p>', self.page(f"/slot/{in_both}"))
        popup = self.client.get("/outfits/piece", query_string={"at": a.sig, "slot": in_both}, headers=HX).data.decode()
        self.assertIn("In 2 of your outfits.", read(popup))
        # A piece no outfit of his wears is not in his wardrobe, and its page and pop-up say so.
        self.assertIn("Not in your wardrobe yet: it joins with the first outfit you add that wears it.",
                      read(self.page(f"/slot/{other}")))

    def test_buy_this_outfit_says_when_the_outfit_is_not_in_his_wardrobe_and_offers_the_yes(self):
        outfit = outfits.find_by_sig(selection.build(), self.offered()[0])
        page = self.page("/outfits/buy", at=outfit.sig)
        self.assertIn("This outfit is not in your wardrobe yet, so it is not on your shopping list or in your total. "
                      + plain(yes.adds(selection.build(), outfit).words) + ".", read(page))
        self.assertIn('name="on" value="buy"', page)
        back = self.say_yes(outfit, on="buy")
        self.assertEqual(back.headers["Location"], "/outfits/buy?at=" + outfit.sig, "the yes leads back to the Buy page")
        page = self.page("/outfits/buy", at=outfit.sig)
        self.assertNotIn("not in your wardrobe yet", page)
        self.assertNotIn("Add to my wardrobe", page)

    def test_a_yes_to_an_outfit_that_no_longer_exists_is_refused(self):
        self.assertEqual(self.client.post("/outfits/save", data={"key": "nope", "want": "save"}).status_code, 409)
        self.assertEqual(db.list_saved(), [])


class NotForMe(YesCase):
    def test_a_no_is_not_offered_again_and_can_be_undone(self):
        shown = self.offered()
        outfit = outfits.find_by_sig(selection.build(), shown[0])
        total = int(re.search(r"12 of (\d+) outfits", self.page("/outfits")).group(1))
        answer = self.say_no(outfit)
        self.assertEqual(answer.headers["Location"], "/outfits?declined=" + outfit.sig)
        self.assertEqual(db.declined_sigs(), {outfit.sig})
        page = self.page(answer.headers["Location"])
        self.assertIn(f"“{outfit.label}” will not be offered again. Undo", read(page))
        self.assertIn(f"12 of {total - 1} outfits", page)
        self.assertIn("You said no to 1 outfit, so it is not shown. Offer it again", read(page))
        for seed in (0, 1, 2, 3):
            self.assertNotIn(outfit.sig, self.offered(n=60, seed=seed), "an outfit he said no to is offered again")
        self.assertEqual(self.mine(), set(), "a no puts nothing into his wardrobe")
        # Undo: the outfit is shown again, first.
        back = self.client.post("/outfits/no", data={"sig": outfit.sig, "want": "undo"})
        self.assertEqual(back.headers["Location"], "/outfits?at=" + outfit.sig)
        self.assertEqual(db.declined_sigs(), set())
        self.assertEqual(self.offered(at=outfit.sig)[0], outfit.sig)
        self.assertNotIn("will not be offered again", self.page("/outfits", declined=outfit.sig),
                         "after Undo the page still says the outfit is not offered")

    def test_offer_them_again_brings_back_every_outfit_he_said_no_to(self):
        w = selection.build()
        for sig in self.offered()[:3]:
            self.say_no(outfits.find_by_sig(w, sig))
        self.assertIn("You said no to 3 outfits, so they are not shown. Offer them again", read(self.page("/outfits")))
        back = self.client.post("/outfits/no", data={"want": "all"})
        self.assertEqual(back.headers["Location"], "/outfits")
        self.assertEqual(db.declined_sigs(), set())
        page = self.page("/outfits")
        self.assertIn("The 3 outfits you said no to are offered again.", read(page))
        self.assertNotIn("You said no to", read(self.page("/outfits")))

    def test_a_no_to_an_outfit_in_his_wardrobe_or_to_none_is_refused_and_a_yes_after_a_no_counts(self):
        outfit = outfits.find_by_sig(selection.build(), self.offered()[0])
        self.assertEqual(self.client.post("/outfits/no", data={"sig": "no~such~outfit"}).status_code, 409)
        self.say_no(outfit)
        self.say_yes(outfit)            # (from "Buy this outfit", or a page still open)
        self.assertEqual((db.declined_sigs(), db.yes_sigs()), (set(), [outfit.sig]))
        self.assertEqual(self.say_no(outfit).status_code, 409)
        self.assertEqual(db.yes_sigs(), [outfit.sig])

    def test_what_he_said_no_to_is_in_his_data_export_and_is_his_alone(self):
        outfit = outfits.find_by_sig(selection.build(), self.offered()[0])
        self.say_no(outfit)
        self.assertEqual(db.export_user()["outfits_you_said_no_to"], [outfit.sig])


class TakingAnOutfitOut(YesCase):
    def test_only_the_pieces_no_other_outfit_wears_go_and_the_page_names_them_with_undo(self):
        a, b = self.two_that_share()
        self.say_yes(a)
        self.say_yes(b)
        self.assertEqual(self.mine(), set(a.slots) | set(b.slots))
        only_a = [s for s in a.slots if s not in b.slots]
        names = yes.names([self.view(s) for s in only_a])
        saved_a = next(fav for fav in db.list_saved() if fav["sig"] == a.sig)

        answer = self.take_out(a, on="saved")
        self.assertEqual(answer.headers["Location"], f"/outfits?occasion=saved&removed={a.key}")
        self.assertEqual(self.mine(), set(b.slots), "the pieces the other outfit wears stay")
        page = read(self.page(answer.headers["Location"]))
        self.assertIn(f"Took “{a.label}” out of your wardrobe. With it went {names}: no other outfit of yours wears "
                      f"{'them' if len(only_a) > 1 else 'it'}. Undo", page)
        # Undo puts back exactly what was taken out.
        back = self.client.post("/outfits/save", data={"key": a.key, "want": "restore", "on": "saved"})
        self.assertEqual(back.status_code, 302)
        self.assertEqual(self.mine(), set(a.slots) | set(b.slots))
        self.assertEqual(next(fav for fav in db.list_saved() if fav["sig"] == a.sig), saved_a)

    def test_a_piece_he_owns_stays_and_an_outfit_that_shares_everything_takes_nothing_with_it(self):
        a, b = self.two_that_share()
        self.say_yes(a)
        owned = next(s for s in a.slots if s not in b.slots)
        self.post(f"/slot/{owned}/own")
        w = selection.build()
        left = [view.slot["id"] for view in yes.leaving(w, a.sig)]
        self.assertNotIn(owned, left)
        self.assertEqual(set(left), set(a.slots) - {owned})
        self.take_out(a)
        self.assertEqual(self.mine(), {owned})

    def test_an_outfit_saved_twice_before_version_9_takes_nothing_with_it_while_the_other_is_there(self):
        # The heart could save the same pieces twice, once before and once after a product was swapped.
        outfit = outfits.find_by_sig(selection.build(), self.offered()[0])
        self.say_yes(outfit)
        again = dict(db.list_saved()[0])
        db.save_outfit("another-key", again["saved_at"], again["label"], again["pieces"], again["sig"])
        self.assertEqual(selection.build().n_outfits, 1, "the same pieces are one outfit of his")
        answer = self.take_out(outfit, on="saved")
        self.assertEqual(self.mine(), set(outfit.slots), "the pieces are still his through the other one")
        said = read(self.page(answer.headers["Location"]))
        self.assertIn(f"Took “{outfit.label}” out of your wardrobe. All its pieces stay", said)
        self.assertNotIn("With it went", said)

    def test_taken_out_among_the_outfits_on_offer_it_is_on_offer_again_and_says_what_went(self):
        outfit = outfits.find_by_sig(selection.build(), self.offered()[0])
        self.say_yes(outfit)
        undo = self.take_out(outfit)        # "Undo" on the line that said it was added
        self.assertEqual(undo.headers["Location"], f"/outfits?at={outfit.sig}&removed={outfit.key}")
        self.assertEqual(self.mine(), set())
        page = self.page("/outfits", at=outfit.sig, removed=outfit.key)
        self.assertIn(f"Took “{outfit.label}” out of your wardrobe.", read(page))
        self.assertEqual(self.offered(at=outfit.sig)[0], outfit.sig)


class TheBudget(YesCase):
    def give_budget(self, amount):
        profile_mod.save({**profile_mod.load(), "budget": amount})
        profile_mod.answer("budget")

    def test_until_he_gives_a_budget_the_bar_shows_the_total_and_the_way_to_set_one(self):
        outfit = outfits.find_by_sig(selection.build(), self.offered()[0])
        self.say_yes(outfit)
        w = selection.build()
        self.assertFalse(w.budget_known)
        bar = re.search(r'<section id="summary".*?</section>', self.page("/"), re.S).group(0)
        self.assertNotIn("over", bar)
        self.assertEqual(re.findall(r'<span class="lbl">(.*?)</span>', bar), ["Total", "Budget"])
        self.assertIn('<a href="/profile#budget">Set a budget</a>', bar)
        self.assertNotIn(plain(eur(w.budget)), read(bar), "the budget every account starts with is not shown as his")
        self.assertNotIn("over your budget", self.page("/outfits"))
        self.assertIn('<a href="/profile#budget">Set a budget</a>', self.page("/list"))

    def test_the_bar_counts_his_wardrobe_against_his_budget(self):
        outfit = outfits.find_by_sig(selection.build(), self.offered()[0])
        cost = yes.adds(selection.build(), outfit).cost
        self.give_budget(round(cost) + 100)
        self.say_yes(outfit)
        w = selection.build().mine
        self.assertAlmostEqual(w.remaining, round(cost) + 100 - cost, places=2)
        bar = read(re.search(r'<section id="summary".*?</section>', self.page("/outfits"), re.S).group(0))
        self.assertIn(plain(f"Total {eur(w.total)} Budget of {eur(w.budget)}"), bar)
        self.assertIn(plain(f"Left {eur(w.remaining)}"), bar)

    def test_an_outfit_that_would_take_him_over_says_by_how_much_before_he_says_yes(self):
        a, b = self.two_that_share()
        first, second = yes.adds(selection.build(), a).cost, None
        self.say_yes(a)
        second = yes.adds(selection.build(), outfits.find_by_sig(selection.build(), b.sig)).cost
        self.assertGreater(second, 0)
        self.give_budget(round(first + second / 2))
        w = selection.build()
        a, b = outfits.find_by_sig(w, a.sig), outfits.find_by_sig(w, b.sig)     # (of the wardrobe as it is now)
        adds = yes.adds(w, b)
        over = round(first + second - round(first + second / 2), 2)
        self.assertAlmostEqual(adds.over_by, over, places=2)
        said = f"With it your wardrobe comes to {eur(first + second)}: {eur(over)} over your budget."
        self.assertEqual(adds.over_words, said)
        self.assertIn(f'<p class="adds over">{html.escape(said)}</p>', self.page("/outfits", at=b.sig))
        self.assertIn(plain(said), read(self.page("/outfits/buy", at=b.sig)))
        # One that adds nothing to buy takes him nowhere: it says nothing of the budget.
        self.assertEqual(yes.adds(w, a).over_words, "")
        # After the yes the bar says he is over, by that much.
        self.say_yes(b)
        bar = read(re.search(r'<section id="summary".*?</section>', self.page("/"), re.S).group(0))
        self.assertIn(plain(f"Over budget {eur(over)}"), bar)

    def test_best_for_budget_fits_his_wardrobe_and_not_the_whole_plan(self):
        a, _ = self.two_that_share()
        self.say_yes(a)
        self.set_mode("cheapest", 60)
        floor = selection.build().mine.total
        self.give_budget(round(floor) + 150)
        self.set_mode("budget", 60)
        w = selection.build()
        self.assertGreater(w.mine.total, floor, "the money left buys better for his pieces")
        self.assertLessEqual(w.mine.total, round(floor) + 150)
        self.assertEqual(w.mine.note, "")
        self.assertGreater(w.total, w.budget, "the whole plan would not fit, and need not")

    def test_best_for_budget_without_a_budget_says_what_it_does_meanwhile(self):
        a, _ = self.two_that_share()
        self.say_yes(a)
        self.set_mode("budget", 60)
        self.assertIn("“Best for budget” needs your budget: set one on the Profile page.", read(self.page("/")))


class PiecesOnTheirOwnAccount(YesCase):
    """A piece he had chosen by hand before version 9 is in his wardrobe without an outfit ("kept"), and so is one
    whose "Owned" he takes back. Such a piece has "Take out" on its card, with Undo."""

    def test_take_out_and_undo(self):
        piece = selection.build().slots[0].slot["id"]
        yes.keep(piece, True)
        self.assertEqual(self.mine(), {piece})
        card = re.search(rf'<article class="slot[^"]*" id="card-{piece}">(.*?)</article>', self.page("/"), re.S).group(1)
        self.assertIn("In none of your outfits yet · you chose it yourself", read(card))
        self.assertIn(f'<button id="out-{piece}"', card)
        out = self.client.post(f"/slot/{piece}/keep", data={"want": "out"})
        self.assertEqual(out.headers["Location"], f"/?took={piece}")
        self.assertEqual(self.mine(), set())
        self.assertIsNotNone(selection.build().get(piece), "it stays a piece outfits are made from")
        page = self.page("/", took=piece)
        self.assertIn(f"Took “{self.view(piece).slot['name']}” out of your wardrobe. Outfits are still made with it. Undo",
                      read(page))
        back = self.client.post(f"/slot/{piece}/keep", data={"want": "in"})
        self.assertEqual(back.headers["Location"], f"/#card-{piece}")
        self.assertEqual(self.mine(), {piece})
        self.assertNotIn("Took “", self.page("/", took=piece), "after Undo the page still says it was taken out")

    def test_a_piece_of_an_outfit_has_no_take_out_of_its_own(self):
        outfit = outfits.find_by_sig(selection.build(), self.offered()[0])
        self.say_yes(outfit)
        piece = outfit.slots[0]
        self.assertNotIn(f'id="out-{piece}"', self.page("/"))
        self.assertEqual(self.client.post(f"/slot/{piece}/keep", data={"want": "out"}).status_code, 409)
        self.assertEqual(self.client.post("/slot/nope/keep", data={"want": "out"}).status_code, 404)

    def test_owned_taken_back_leaves_the_piece_in_his_wardrobe_to_buy(self):
        piece = selection.build().slots[0].slot["id"]
        self.post(f"/slot/{piece}/own")
        self.assertEqual(self.mine(), {piece})
        self.post(f"/slot/{piece}/own")
        self.assertEqual(self.mine(), {piece}, "the card vanished under his finger")
        self.assertGreater(selection.build().mine.total, 0)

    def test_new_answers_on_the_profile_keep_the_pieces_of_his_outfits(self):
        outfit = next(o for o in self.every() if any(self.view(s).slot["colour"] == "navy" for s in o.slots))
        self.say_yes(outfit)
        form = {"top_size": "M", "waist": "32", "length": "32", "shoe": "43", "height_cm": "180", "weight_kg": "78",
                "budget": "1500", "liked": "black, white", "refused": "navy", "use": "office", "shoes": "on",
                "outerwear": "on", "owned": ""}
        saved = self.client.post("/profile", data=form)
        self.assertEqual(saved.headers["Location"], "/outfits")
        self.assertLessEqual(set(outfit.slots), {slot["id"] for slot in db.list_slots()})
        self.assertEqual(self.mine(), set(outfit.slots))
        self.assertIn("black", {slot["colour"] for slot in db.list_slots()}, "the rest of the plan follows the new answers")
        self.assertRegex(read(self.page("/outfits")), r"Also kept, as (it was|they were): the \d+ pieces? of your wardrobe "
                                                      r"that the new plan has no place for\.")
        # … and so does "Start over from my profile" on the plan page.
        self.client.post("/slots/repropose")
        self.assertEqual(self.mine(), set(outfit.slots))


class WhoWasACustomerBefore(YesCase):
    """Version 9 of the database. What a customer had becomes a truthful start: his saved outfits are outfits he
    said yes to, the pieces he chose by hand are in his wardrobe, nothing is deleted, and the pages say so once."""

    def version_8(self):
        """Today's database as version 8 left it: no `sig` on a saved outfit, no table for the no's, and none of
        the settings version 9 writes."""
        with closing(sqlite3.connect(paths.DB_PATH)) as con:
            con.executescript("""
                DROP TABLE outfits_declined;
                ALTER TABLE saved_outfits DROP COLUMN sig;
                DELETE FROM settings WHERE key IN ('kept_pieces', 'wardrobe_news', 'welcome', 'answered');
                PRAGMA user_version = 8;
            """)
            con.commit()

    def rows(self, table: str, columns: str = "*") -> list:
        with closing(sqlite3.connect(paths.DB_PATH)) as con:
            return sorted(con.execute(f"SELECT {columns} FROM {table}").fetchall())  # nosec

    def test_what_he_had_becomes_his_wardrobe_and_nothing_is_deleted(self):
        self.page("/")                                       # the first run: his plan and its products
        a, b = self.two_that_share()
        self.client.post("/outfits/save", data={"key": a.key}, headers=HX)      # the heart, as it saved an outfit
        others = [view.slot["id"] for view in selection.build().slots if view.slot["id"] not in a.slots]
        locked, owned, untouched = others[0], others[1], others[2:]
        self.post(f"/slot/{locked}/lock")                    # a product chosen by hand
        self.post(f"/slot/{owned}/own")
        db.set_setting("kept_pieces", None)                  # (the owned mark of today notes nothing here either)
        self.version_8()
        slots, saved = self.rows("slots"), self.rows("saved_outfits")
        settings = self.rows("settings")
        self.assertEqual(len(saved[0]), 5, "a saved outfit of version 8 has no sig")

        db.init()
        with closing(sqlite3.connect(paths.DB_PATH)) as con:
            self.assertEqual(con.execute("PRAGMA user_version").fetchone()[0], 9)
        self.assertEqual(self.rows("slots"), slots, "every piece of the plan is as it was")
        self.assertEqual(self.rows("saved_outfits", "user_id, key, saved_at, label, pieces"), saved)
        self.assertEqual(self.rows("saved_outfits", "sig"), [(a.sig,)], "the saved outfit says which pieces it combines")
        self.assertEqual([row for row in self.rows("settings") if row[1] not in ("kept_pieces", "wardrobe_news")],
                         settings, "his answers and choices are as they were")
        self.assertEqual((db.get_setting("kept_pieces"), db.get_setting("wardrobe_news")), ([locked], True))
        self.assertEqual(self.rows("outfits_declined"), [])

        # His wardrobe: the saved outfit's pieces, the piece he chose by hand (with its product), the one he owns.
        w = selection.build()
        self.assertEqual(self.mine(), set(a.slots) | {locked, owned})
        self.assertEqual((w.n_outfits, w.get(locked).state, w.get(owned).state), (1, "locked", "owned"))
        self.assertTrue(all(w.get(slot_id).chosen for slot_id in untouched), "the rest keeps its products")
        # The first page says so, once, with the numbers.
        n_mine = sum(view.qty for view in w.mine.slots)
        n_rest = sum(view.qty for view in w.slots if not view.mine)
        news = (f"Your wardrobe is now the outfits you say yes to. It starts with the 1 outfit you had saved, the 1 "
                f"piece you chose yourself and the 1 you own: {n_mine} pieces in all. The other {n_rest} pieces of your "
                "plan were not deleted: outfits are still made from them, with the same products, and each joins your "
                "wardrobe with the first outfit you add that wears it. Only your wardrobe counts in the total now.")
        self.assertIn(news, read(self.page("/outfits")))
        self.assertNotIn("Your wardrobe is now the outfits", self.page("/outfits"))
        self.assertNotIn("Your wardrobe is now the outfits", self.page("/"))
        self.assertIn("My outfits 1</a>", self.page("/outfits"))
        # He was a customer already: no welcome for him, and his own budget counts as his.
        self.assertIsNone(db.get_setting("welcome"))
        db.init()                                            # starting again changes nothing
        self.assertEqual(db.get_setting("kept_pieces"), [locked])

    def test_someone_who_had_touched_nothing_starts_with_an_empty_wardrobe_and_is_told(self):
        self.page("/")
        self.version_8()
        db.init()
        self.assertEqual((self.mine(), db.get_setting("kept_pieces")), (set(), []))
        n = sum(view.qty for view in selection.build().slots)
        said = read(self.page("/"))
        self.assertIn(f"Your wardrobe is now the outfits you say yes to. It starts empty: add the outfits you like. The "
                      f"other {n} pieces of your plan were not deleted", said)

    def test_a_saved_outfit_that_cannot_be_read_stays_as_it_is(self):
        self.page("/")
        self.version_8()
        with closing(sqlite3.connect(paths.DB_PATH)) as con:
            con.execute("INSERT INTO saved_outfits VALUES (1, 'odd', '2026-11-12T12:00:00+01:00', 'Everyday', 'not json')")
            con.execute("INSERT INTO saved_outfits VALUES (1, 'old', '2026-11-12T12:00:00+01:00', 'Everyday', ?)",
                        (json.dumps([{"slot_id": "white-tee"}, {"slot_id": "indigo-jeans"}]),))
            con.commit()
        db.init()
        self.assertEqual(self.rows("saved_outfits", "key, sig"), [("odd", ""), ("old", "white-tee~indigo-jeans")])


class TheWelcome(ProductionCase):
    """Three short steps after signing up, each of which he may skip: what he answers is saved to his profile, what
    he skips stays unanswered. (That it opens after signing up, and what the pages say of what he skipped:
    test_production.py, StartsWithAWelcome.)"""

    def profile(self, email="ada@example.com") -> dict:
        with db.as_user(self.user_id(email)):
            return profile_mod.load()

    def answered(self, email="ada@example.com") -> set:
        with db.as_user(self.user_id(email)):
            return profile_mod.answered()

    def test_his_sizes_are_saved_as_his(self):
        ada = self.member("ada@example.com")
        page = ada.get("/welcome").data.decode()
        self.assertNotIn(" selected", page, "no size is filled in for him")
        self.assertNotIn('value="43"', page)
        onwards = self.post(ada, "/welcome", top_size="L", waist="34", length="30", shoe="44")
        self.assertEqual(onwards.headers["Location"], "/welcome/2")
        mine = self.profile()
        self.assertEqual((mine["top_size"], str(mine["waist"]), str(mine["length"]), str(mine["shoe"])), ("L", "34", "30", "44"))
        with db.as_user(self.user_id("ada@example.com")):
            self.assertFalse(profile_mod.sizes_unconfirmed(profile_mod.load()))
        self.assertIn("Your sizes: Tops L · Trousers W34 L30 · Shoes 44", read(ada.get(
            "/outfits/buy?at=" + self.first_outfit("ada@example.com").sig).data.decode()))

    def first_outfit(self, email):
        with db.as_user(self.user_id(email)):
            return outfits.generate(selection.build(), limit=1)[0][0]

    def test_the_examples_sizes_typed_by_him_are_his_and_half_an_answer_is_asked_again(self):
        ada = self.member("ada@example.com")
        half = self.post(ada, "/welcome", top_size="M", waist="", length="", shoe="")
        self.assertEqual(half.status_code, 400)
        self.assertIn("Give all four sizes, or skip this step.", read(half.data.decode()))
        self.assertIn("<option selected>M</option>", half.data.decode(), "what he chose is still there")
        self.post(ada, "/welcome", top_size="M", waist="32", length="32", shoe="43")
        with db.as_user(self.user_id("ada@example.com")):
            self.assertFalse(profile_mod.sizes_unconfirmed(profile_mod.load()))

    def test_colours_and_budget_are_saved_and_the_plan_follows_the_colours(self):
        ada = self.member("ada@example.com")
        self.assertEqual(self.answered(), set())
        page = ada.get("/welcome/2").data.decode()
        self.assertNotIn("checked", page, "no colour is ticked for him")
        self.assertNotIn('value="1500"', page, "no budget is filled in for him")
        token = self.token(ada)
        onwards = ada.post("/welcome/2", data={"csrf_token": token, "liked": ["black", "white"], "budget": "800"})
        self.assertEqual(onwards.headers["Location"], "/welcome/3")
        mine = self.profile()
        self.assertEqual((mine["liked"], mine["budget"]), (["black", "white"], 800))
        self.assertEqual(self.answered(), {"colours", "budget"})
        with db.as_user(self.user_id("ada@example.com")):
            self.assertIn("black", {slot["colour"] for slot in db.list_slots()})
            self.assertTrue(selection.build().budget_known)
        self.assertNotIn("You have not chosen colours yet", ada.get("/profile").data.decode())

    def test_what_he_dresses_for_is_saved_and_then_come_the_outfits(self):
        ada = self.member("ada@example.com")
        done = self.post(ada, "/welcome/3", use="office")
        self.assertEqual(done.headers["Location"], "/outfits")
        self.assertEqual(self.profile()["use"], "office")
        self.assertEqual(self.answered(), {"use"})
        with db.as_user(self.user_id("ada@example.com")):
            self.assertEqual(db.get_setting("welcome"), "done")

    def test_skipping_everything_answers_nothing(self):
        ada = self.member("ada@example.com")
        before = self.profile()
        for url in ("/welcome", "/welcome/2", "/welcome/3"):
            self.post(ada, url, skip="1", top_size="L", liked="black", budget="100", use="office")
        self.assertEqual(self.profile(), before)
        self.assertEqual(self.answered(), set())
        with db.as_user(self.user_id("ada@example.com")):
            self.assertTrue(profile_mod.sizes_unconfirmed(profile_mod.load()))
            self.assertFalse(selection.build().budget_known)
        # "Continue" with nothing filled in answers nothing either.
        bob = self.member("bob@example.com")
        self.post(bob, "/welcome")
        self.post(bob, "/welcome/2")
        self.post(bob, "/welcome/3")
        self.assertEqual(self.answered("bob@example.com"), set())

    def test_the_welcome_shows_no_total_and_needs_the_pages_token_and_an_account(self):
        ada = self.member("ada@example.com")
        for url in ("/welcome", "/welcome/2", "/welcome/3"):
            page = ada.get(url).data.decode()
            self.assertNotIn('id="summary"', page, url)
            self.assertNotIn("€", read(page), url)
            self.assertIn(">Skip</button>", page, url)
        self.assertEqual(ada.get("/welcome/4").status_code, 404)
        self.assertEqual(ada.post("/welcome/3", data={"use": "office"}).status_code, 400, "no token")
        visitor = self.app.test_client()
        self.assertEqual(visitor.get("/welcome").status_code, 302)
        self.assertIn("/login", visitor.get("/welcome").headers["Location"])

    def test_two_customers_answers_and_yeses_are_their_own(self):
        ada, bob = self.member("ada@example.com"), self.member("bob@example.com")
        outfit = self.first_outfit("ada@example.com")
        self.post(ada, "/outfits/save", key=outfit.key, sig=outfit.sig, want="save")
        self.post(bob, "/outfits/no", sig=outfit.sig)
        with db.as_user(self.user_id("ada@example.com")):
            self.assertEqual((db.yes_sigs(), db.declined_sigs()), ([outfit.sig], set()))
        with db.as_user(self.user_id("bob@example.com")):
            self.assertEqual((db.yes_sigs(), db.declined_sigs()), ([], {outfit.sig}))
        self.assertEqual(json.loads(bob.get("/account/export").data)["outfits_you_said_no_to"], [outfit.sig])
        self.assertEqual(json.loads(ada.get("/account/export").data)["outfits_you_said_no_to"], [])
