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
from unittest import mock

from wardrobe import db, export, outfits, paths, selection, yes
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

    def keys_of(self, sigs) -> str:
        """The outfits' keys, joined as an address names the row ("front")."""
        w = selection.build()
        return ".".join(outfits.find_by_sig(w, sig).key for sig in sigs)

    def every(self) -> list:
        return outfits.all_outfits(selection.build())

    def two_that_share(self):
        """Two outfits with some pieces in common and some not, and none of them a piece the plan has twice."""
        every = [o for o in self.every() if all(p.view.planned == 1 for p in o.pieces)]
        for a in every:
            for b in every:
                shared = set(a.slots) & set(b.slots)
                if shared and set(a.slots) - shared and set(b.slots) - shared:
                    return a, b
        self.fail("the demo plan has no two outfits that share only some pieces")

    def mine(self) -> set[str]:
        return {view.slot["id"] for view in selection.build().mine.slots}

    def named(self, outfit) -> str:
        """How the message after taking an outfit out names it: 'outfit with the charcoal wool coat and indigo jeans'."""
        return yes.name(outfits.snapshot(outfit))

    def called(self, outfit, number: int | None = None) -> str:
        """How the messages after a yes or a no name this outfit, as a pattern to look for: by its number in the row
        and its title, 'outfit 2 (Smart casual)' (review N2). `number`: where it stood, if the test knows it."""
        which = "this outfit" if number == 0 else f"outfit {number or r'\d+'}"     # 0: shown on its own, in no row
        return rf"{which} \({re.escape(yes.title(outfit.label, 'all'))}\)"

    def its_pieces(self, outfit) -> str:
        """... and every one of its pieces, which a screen reader hears and the eye sees as small photos."""
        return re.escape("Its pieces: " + ", ".join(p["slot_name"] for p in outfits.snapshot(outfit)) + ".")

    def answered_line(self, page: str) -> str:
        """The message after a yes or a no, as the customer reads it."""
        return read(re.search(r'<div class="flash said short answered" role="status" data-answered>.*?</div>', page, re.S).group(0))

    def bar(self, page: str) -> str:
        return read(re.search(r'<section id="summary".*?</section>', page, re.S).group(0))

    def give_budget(self, amount):
        profile_mod.save({**profile_mod.load(), "budget": amount})
        profile_mod.answer("budget")

    def plan_at_its_cheapest(self) -> float:
        """What every piece of the plan costs on its cheapest option, each as often as the plan has it."""
        self.set_mode("cheapest", 60)
        return round(sum(view.chosen.price * view.planned for view in selection.build().slots if view.chosen), 2)

    def products(self) -> dict:
        return {view.slot["id"]: view.chosen.id for view in selection.build().slots if view.chosen}

    def card(self, slot_id: str) -> str:
        """A piece's card on the Wardrobe page."""
        return re.search(rf'<article class="slot[^"]*" id="card-{slot_id}">(.*?)</article>', self.page("/"), re.S).group(1)

    def with_the_tee(self):
        """(The piece the plan has twice, an outfit that wears it.)"""
        w = selection.build()
        twice = next(view for view in w.slots if view.planned == 2)
        return twice.slot["id"], next(o for o in outfits.all_outfits(w) if twice.slot["id"] in o.slots)


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
        self.assertAlmostEqual(adds.cost, first.cost, places=2)       # one of each piece: the outfit's own price
        self.assertEqual(adds.words, f"{len(first.pieces)} new pieces {eur(first.cost)}")
        self.assertIn(f'<p class="adds">{html.escape(adds.words)}</p>', page)
        self.assertEqual(page.count("<span>Add to my wardrobe</span>"), 12)
        self.assertEqual(page.count(">Not for me</button>"), 12)
        self.assertIn(f'<span class="plus">+ {eur(adds.cost)}</span>', page, "the button says what the yes adds")
        self.assertNotIn("come first", page, "nothing to reuse yet, so no line about the order")
        self.assertNotIn("over your budget", page, "he has given no budget")

    def test_messages_name_an_outfit_by_its_main_pieces_never_by_its_occasion_alone(self):
        w = selection.build()
        coat = next(o for o in outfits.all_outfits(w) if o.pieces[0].layer == "outer")
        plain_one = next(o for o in outfits.all_outfits(w) if len(o.pieces) == 3)       # a top, trousers and shoes
        top, bottom = (next(p for p in coat.pieces if p.layer == layer).view.slot["name"] for layer in ("outer", "bottom"))
        self.assertEqual(self.named(coat), f"outfit with the {top.lower()} and {bottom.lower()}")
        self.assertEqual(self.named(plain_one), f"outfit with the {plain_one.pieces[0].view.slot['name'].lower()} and "
                                                f"{plain_one.pieces[1].view.slot['name'].lower()}")
        self.assertEqual(yes.name([]), "outfit")
        self.assertEqual(yes.name(None), "outfit")
        for label in outfits.OCCASIONS.values():
            self.assertNotIn(label.lower(), self.named(coat))


    def test_a_yes_and_a_no_to_two_outfits_with_the_same_coat_and_jeans_never_read_the_same(self):
        # Review N2: "Added the outfit with the charcoal wool coat and indigo jeans", then, after a no to the next
        # outfit, "The outfit with the charcoal wool coat and indigo jeans will not be offered again": he read that
        # his new outfit was thrown away. Now each is named by its number and title, and shows all its pieces.
        w = selection.build()
        row = [outfits.find_by_sig(w, sig) for sig in self.offered(n=60)]
        a, b = next((a, b) for i, a in enumerate(row) for b in row[i + 1:]
                    if yes.name(outfits.snapshot(a)) == yes.name(outfits.snapshot(b)))
        said_yes = self.answered_line(self.page(self.say_yes(a, n="60").headers["Location"]))
        said_no = self.answered_line(self.page(self.say_no(b, n="60").headers["Location"]))
        self.assertRegex(said_yes, "^Added " + self.called(a, row.index(a) + 1) + " to your wardrobe")
        self.assertRegex(said_yes, self.its_pieces(a))
        self.assertRegex(said_no, self.its_pieces(b))
        self.assertNotEqual(said_yes.split(" to your wardrobe")[0].removeprefix("Added "),
                            said_no.split(" will not be offered")[0].lower())


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
        # By its number and title, and its pieces: its title alone names a filter and dozens of outfits.
        self.assertRegex(self.answered_line(page), "^Added " + self.called(outfit, 1) + re.escape(plain(
            f" to your wardrobe: {said.words[0].lower()}{said.words[1:]}. ")) + self.its_pieces(outfit) + " Undo$")
        self.assertEqual(len(re.findall(r'<span class="pic', re.search(r'<p class="answered-pieces">.*?</p>', page, re.S).group(0))),
                         len(outfit.pieces), "a small photo for every piece")
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
        self.assertEqual(adds.words, f"Nothing new to buy: all {len(small.slots)} are in your wardrobe")
        self.assertIn(f'<span class="plus">+ {eur(0)}</span>', self.page("/outfits", at=small.sig))
        # After the yes the page says so in a sentence of its own, and the bar has not moved.
        total = selection.build().mine.total
        answer = self.say_yes(outfits.find_by_sig(selection.build(), small.sig))
        self.assertRegex(self.answered_line(self.page(answer.headers["Location"])), "^Added " + self.called(small, 0)
                         + re.escape(f" to your wardrobe. Nothing new to buy: all {len(small.slots)} are in your wardrobe. ")
                         + self.its_pieces(small) + " Undo$")
        self.assertEqual(selection.build().mine.total, total)

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
        second = outfits.find_by_sig(selection.build(), shown[1])       # which now stands where it stood
        # Every other outfit of the row stays in its place (front), and the page comes back on the one that followed.
        self.assertEqual(answer.headers["Location"],
                         f"/outfits?declined={outfit.sig}&front={self.keys_of(shown[1:])}#outfit-{second.key}")
        self.assertEqual(db.declined_sigs(), {outfit.sig})
        page = self.page(answer.headers["Location"])
        # By its number and title, and its pieces: its title alone reads as if every such outfit were switched off.
        self.assertRegex(self.answered_line(page), "^O" + self.called(outfit, 1)[1:] + " will not be offered again\\. "
                         + self.its_pieces(outfit) + " Undo$")
        self.assertIn(f"12 of {total - 1} outfits", page)
        self.assertIn("You said no to 1 outfit, so it is not shown. Offer it again", read(page))
        for seed in (0, 1, 2, 3):
            self.assertNotIn(outfit.sig, self.offered(n=60, seed=seed), "an outfit he said no to is offered again")
        self.assertEqual(self.mine(), set(), "a no puts nothing into his wardrobe")
        # Undo: the outfit is back in its place, and the page comes back on it.
        back = self.client.post("/outfits/no", data={"sig": outfit.sig, "want": "undo"})
        self.assertEqual(back.headers["Location"], f"/outfits?front={self.keys_of(shown)}#outfit-{outfit.key}")
        self.assertEqual(db.declined_sigs(), set())
        self.assertEqual(self.offered(), shown)
        self.assertNotIn("will not be offered again", self.page("/outfits", declined=outfit.sig),
                         "after Undo the page still says the outfit is not offered")

    def no_forms(self, page: str) -> dict:
        """The "Not for me" form of each outfit on the page, by the pieces it combines."""
        forms = re.findall(r'<form class="no" method="post" action="/outfits/no">.*?</form>', page, re.S)
        return {html.unescape(re.search(r'name="sig" value="([^"]*)"', form).group(1)): form for form in forms}

    def test_after_a_no_he_goes_on_from_where_he_was(self):
        # (He was thrown back to the first outfit, with the ones he had passed in front of him again.)
        page = self.page("/outfits")
        shown = self.offered()
        keys = re.findall(r'<article class="slide" id="outfit-(\w+)"', page)
        self.assertEqual(len(keys), 12)
        fifth = outfits.find_by_sig(selection.build(), shown[4])
        self.assertEqual(fifth.key, keys[4])
        form = self.no_forms(page)[fifth.sig]
        self.assertIn(f'<input type="hidden" name="next" value="{keys[5]}">', form, "the form names the outfit that follows")
        answer = self.client.post("/outfits/no", data={"sig": fifth.sig, "next": keys[5]})
        self.assertEqual(answer.headers["Location"],
                         f"/outfits?declined={fifth.sig}&front={'.'.join(keys[:4] + keys[5:])}#outfit-{keys[5]}")
        after = self.offered(front=".".join(keys[:4] + keys[5:]))
        self.assertEqual(after[:11], shown[:4] + shown[5:], "the other outfits are where they were")
        self.assertNotIn(after[11], shown, "one more joins the row")
        self.assertIn(f'<article class="slide" id="outfit-{keys[5]}"', self.page(answer.headers["Location"]))
        # Undo puts it back where it was, and the page comes back on it.
        back = self.client.post("/outfits/no", data={"sig": fifth.sig, "want": "undo",
                                                     "front": ".".join(keys[:4] + keys[5:])})
        self.assertEqual(back.headers["Location"], f"/outfits?front={'.'.join(keys)}#outfit-{fifth.key}")
        self.assertEqual(self.offered(front=".".join(keys)), shown)

    def test_a_no_to_the_last_of_the_row_comes_back_on_what_stands_there_now(self):
        page = self.page("/outfits")
        shown = self.offered()
        last = outfits.find_by_sig(selection.build(), shown[-1])
        form = self.no_forms(page)[last.sig]
        self.assertIn('<input type="hidden" name="i" value="11">', form)
        self.assertNotIn('name="next"', form)
        answer = self.client.post("/outfits/no", data={"sig": last.sig, "i": "11"})
        front = self.keys_of(shown[:11])
        now = self.offered(front=front)
        self.assertEqual(now[:11], shown[:11])
        there = outfits.find_by_sig(selection.build(), now[11])
        self.assertEqual(answer.headers["Location"], f"/outfits?declined={last.sig}&front={front}#outfit-{there.key}")
        # A page that names no place, or nonsense, still gets an answer: the first outfit.
        other = outfits.find_by_sig(selection.build(), now[3])
        answer = self.client.post("/outfits/no", data={"sig": other.sig, "next": "../../x", "i": "many", "front": front})
        first = outfits.find_by_sig(selection.build(), now[0])
        self.assertTrue(answer.headers["Location"].startswith(f"/outfits?declined={other.sig}&front="))
        self.assertTrue(answer.headers["Location"].endswith(f"#outfit-{first.key}"))

    def test_an_answer_comes_back_to_the_same_row_of_outfits(self):
        # After "Show more outfits" (24 of them) and Shuffle, the answers carry which row it is.
        page = self.page("/outfits", n=24, seed=7)
        shown = self.offered(n=24, seed=7)
        self.assertEqual(len(shown), 24)
        sixth = outfits.find_by_sig(selection.build(), shown[5])
        for form in (self.no_forms(page)[sixth.sig],
                     re.search(r'<form class="save".*?</form>', page[page.index(f'id="outfit-{sixth.key}"'):], re.S).group(0)):
            self.assertIn('<input type="hidden" name="n" value="24"><input type="hidden" name="seed" value="7">', form)
        keys = re.findall(r'<article class="slide" id="outfit-(\w+)"', page)
        answer = self.client.post("/outfits/no", data={"sig": sixth.sig, "next": keys[6], "n": "24", "seed": "7"})
        rest = ".".join(keys[:5] + keys[6:])
        self.assertEqual(answer.headers["Location"],
                         f"/outfits?declined={sixth.sig}&n=24&seed=7&front={rest}#outfit-{keys[6]}")
        self.assertEqual(self.offered(n=24, seed=7, front=rest)[:23], shown[:5] + shown[6:])
        undo = re.search(r'<div class="flash said short answered" role="status" data-answered>.*?</div>',
                         self.page(answer.headers["Location"]), re.S).group(0)
        self.assertIn('name="n" value="24"', undo)
        seventh = outfits.find_by_sig(selection.build(), shown[6])
        answer = self.say_yes(seventh, n="24", seed="7", front=rest)
        self.assertTrue(answer.headers["Location"].startswith(
            f"/outfits?added={seventh.key}&n=24&seed=7&front={'.'.join(keys[:5])}#outfit-"), answer.headers["Location"])
        # The row every visit starts with needs no words for it.
        self.assertNotIn('name="seed"', self.page("/outfits"))
        self.assertNotIn('name="n"', self.page("/outfits"))

    def test_the_page_has_the_bar_for_a_phones_answers_before_the_outfits_and_none_under_my_outfits(self):
        # On a phone app.js moves the outfit's box into it (the walk-through checks where it then stands).
        page = self.page("/outfits")
        self.assertLess(page.index('<div class="dock" id="dock"'), page.index('<section class="looks'))
        self.assertIn('<div class="dock" id="dock" role="group" aria-label="Your answer to the outfit that is showing" hidden></div>', page)
        self.assertEqual(page.count('<div class="yes-box" data-answer>'), 12)
        outfit = outfits.find_by_sig(selection.build(), self.offered()[0])
        self.say_yes(outfit)
        self.assertNotIn('id="dock"', self.page("/outfits", occasion="saved"))

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
        self.assertIn(f"Took the {self.named(a)} out of your wardrobe. With it went {names}: no other outfit of "
                      f"yours wears {'them' if len(only_a) > 1 else 'it'}. Undo", page)
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
        answer = self.take_out(outfit, on="saved")
        self.assertEqual(self.mine(), set(outfit.slots), "the pieces are still his through the other one")
        said = read(self.page(answer.headers["Location"]))
        self.assertIn(f"Took the {self.named(outfit)} out of your wardrobe. All its pieces stay", said)
        self.assertNotIn("With it went", said)

    def test_the_same_pieces_saved_twice_are_two_outfits_wherever_outfits_are_counted(self):
        # My outfits shows two of them (as they were saved, with different products), so two is what the chip, the
        # bar, the Wardrobe page, a piece and the one-time message all say.
        outfit = outfits.find_by_sig(selection.build(), self.offered()[0])
        self.say_yes(outfit)
        again = dict(db.list_saved()[0])
        db.save_outfit("another-key", again["saved_at"], again["label"], again["pieces"], again["sig"])
        db.set_setting("wardrobe_news", True)
        w = selection.build()
        self.assertEqual((w.n_outfits, w.get(outfit.slots[0]).outfits_in), (2, 2))
        page = self.page("/outfits", occasion="saved")
        self.assertEqual(page.count('<article class="slide"'), 2)
        self.assertIn("My outfits 2</a>", page)
        self.assertIn("It starts with the 2 outfits you had saved", read(page))
        wardrobe = self.page("/")
        bar = read(re.search(r'<section id="summary".*?</section>', wardrobe, re.S).group(0))
        self.assertIn("· 2 outfits", bar)
        self.assertIn('<a href="/outfits?occasion=saved">2 outfits</a> you said yes to', wardrobe)
        self.assertIn("In 2 of your outfits", read(wardrobe))

    def test_taken_out_among_the_outfits_on_offer_it_is_on_offer_again_and_says_what_went(self):
        outfit = outfits.find_by_sig(selection.build(), self.offered()[0])
        self.say_yes(outfit)
        undo = self.take_out(outfit)        # "Undo" on the line that said it was added
        # (The row as it stood before the yes comes back, every outfit in its place: front.)
        self.assertTrue(undo.headers["Location"].startswith(
            f"/outfits?at={outfit.sig}&removed={outfit.key}&front={outfit.key}."), undo.headers["Location"])
        self.assertEqual(self.mine(), set())
        page = self.page("/outfits", at=outfit.sig, removed=outfit.key)
        self.assertIn(f"Took the {self.named(outfit)} out of your wardrobe.", read(page))
        self.assertEqual(self.offered(at=outfit.sig)[0], outfit.sig)


class RemovingAPieceFromThePlan(YesCase):
    """The plan page removes a piece from the plan. One that is in his wardrobe leaves it with that: the question
    says so before, the message after, and an outfit of his that wore it says why it can no longer be bought."""

    def confirm(self, slot_id: str) -> str:
        form = re.search(rf'<form method="post" action="/slots/{slot_id}/delete" data-confirm="([^"]*)"', self.page("/slots"))
        return html.unescape(form.group(1))

    def test_a_piece_two_of_his_outfits_wear(self):
        a, b = self.two_that_share()
        self.say_yes(a)
        self.say_yes(b)
        piece = next(s for s in a.slots if s in b.slots)
        name, cost, total = self.view(piece).slot["name"], self.view(piece).cost, selection.build().mine.total
        self.assertEqual(self.confirm(piece), f"Remove “{name}” from your plan? It is in your wardrobe, in 2 of your "
                         "outfits: it leaves your wardrobe, your total and your shopping list too, and those outfits "
                         "can no longer be bought as outfits.")
        back = self.client.post(f"/slots/{piece}/delete")
        self.assertIn(f"Removed “{name}” from your plan, and with that from your wardrobe, your total and your shopping "
                      "list. It was in 2 of your outfits: they stay under My outfits as you added them, but can no "
                      "longer be bought as outfits.", read(self.page(back.headers["Location"])))
        self.assertNotIn(piece, self.mine())
        self.assertAlmostEqual(selection.build().mine.total, total - cost, places=2)
        self.assertNotIn(name, read(self.page("/list")))
        # My outfits: both are there as he added them, and each says what became of the piece.
        mine = self.page("/outfits", occasion="saved")
        self.assertEqual(mine.count('<article class="slide"'), 2)
        self.assertEqual(read(mine).count(f"“{name}” is no longer in your plan, so it is not in your wardrobe or your total, "
                                          "and this outfit can no longer be bought as one."), 2)
        self.assertEqual(mine.count("<small>removed</small>"), 2)
        self.assertNotIn("Buy this outfit", mine)
        self.assertEqual(selection.build().n_outfits, 2)

    def test_a_piece_one_outfit_wears_and_one_that_is_in_none(self):
        a, _ = self.two_that_share()
        self.say_yes(a)
        piece = a.slots[0]
        name = self.view(piece).slot["name"]
        self.assertEqual(self.confirm(piece), f"Remove “{name}” from your plan? It is in your wardrobe, in 1 of your "
                         "outfits: it leaves your wardrobe, your total and your shopping list too, and that outfit can "
                         "no longer be bought as an outfit.")
        back = self.client.post(f"/slots/{piece}/delete")
        self.assertIn(f"Removed “{name}” from your plan, and with that from your wardrobe, your total and your shopping "
                      "list. It was in 1 of your outfits: it stays under My outfits as you added it, but can no longer "
                      "be bought as an outfit.", read(self.page(back.headers["Location"])))
        # A piece that is not in his wardrobe: nothing of his changes, and nothing more is said.
        other = next(view for view in selection.build().slots if not view.mine)
        self.assertEqual(self.confirm(other.slot["id"]), f"Remove “{other.slot['name']}” from your plan?")
        total = selection.build().mine.total
        back = self.client.post(f"/slots/{other.slot['id']}/delete")
        said = read(self.page(back.headers["Location"]))
        self.assertIn(f"Removed “{other.slot['name']}” from your plan.", said)
        self.assertNotIn("from your wardrobe", said)
        self.assertEqual(selection.build().mine.total, total)

    def test_two_pieces_of_one_outfit_removed_are_named_together(self):
        a, _ = self.two_that_share()
        self.say_yes(a)
        first, second = a.slots[0], a.slots[1]
        names = [self.view(slot_id).slot["name"] for slot_id in (first, second)]
        db.update_slot(first, name="Black and white coat")      # (a name with "and" in it is still one piece)
        self.client.post(f"/slots/{second}/delete")
        mine = read(self.page("/outfits", occasion="saved"))
        self.assertIn(f"“{names[1]}” is no longer in your plan, so it is not in your wardrobe", mine)
        self.client.post(f"/slots/{first}/delete")
        mine = read(self.page("/outfits", occasion="saved"))
        self.assertIn(f"“{names[0]}” and “{names[1]}” are no longer in your plan, so they are not in your wardrobe or your "
                      "total, and this outfit can no longer be bought as one.", mine)

    def test_a_piece_he_kept_and_one_he_owns(self):
        kept, owned = (view.slot["id"] for view in selection.build().slots[:2])
        yes.keep(kept, True)
        self.post(f"/slot/{owned}/own")
        name = self.view(kept).slot["name"]
        self.assertEqual(self.confirm(kept), f"Remove “{name}” from your plan? It is in your wardrobe: it leaves your "
                                             "wardrobe, your total and your shopping list too.")
        back = self.client.post(f"/slots/{kept}/delete")
        self.assertIn(f"Removed “{name}” from your plan, and with that from your wardrobe, your total and your shopping "
                      "list.", read(self.page(back.headers["Location"])))
        self.assertEqual(db.get_setting("kept_pieces"), [], "a piece that is gone is no longer one he kept")
        # What he owns was in no total and on no list to buy.
        name = self.view(owned).slot["name"]
        self.assertEqual(self.confirm(owned), f"Remove “{name}” from your plan? It is in your wardrobe: it leaves your "
                                              "wardrobe too.")
        back = self.client.post(f"/slots/{owned}/delete")
        self.assertIn(f'<p class="flash" role="status">Removed “{name}” from your plan, and with that from your '
                      'wardrobe.</p>', self.page(back.headers["Location"]))

    def test_an_outfit_of_his_that_is_none_today_says_so(self):
        # Its pieces are all in the plan still, but he made the trousers a second top: no outfit without trousers.
        a, _ = self.two_that_share()
        self.say_yes(a)
        top = next(p for p in a.pieces if p.layer == "top").view.slot
        bottom = next(p for p in a.pieces if p.layer == "bottom").view.slot
        self.client.post(f"/slots/{bottom['id']}/save", data={"name": bottom["name"], "category": top["category"],
                                                              "colour": bottom["colour"], "qty": "1", "keywords": ""})
        self.assertIsNone(outfits.find_by_sig(selection.build(), a.sig))
        mine = self.page("/outfits", occasion="saved")
        self.assertIn("These pieces no longer make an outfit as your plan is today, so it cannot be bought as one.", read(mine))
        self.assertNotIn("no longer in your plan", mine)
        self.assertNotIn("Buy this outfit", mine)


class WhatAnOutfitSaysIsWhatTheBarGains(YesCase):
    """At every price level, "Best for budget" included: the outfit's own price, the sum on its button, the line
    under it, the message after the yes, what the bar gains and "Buy this outfit" agree, and the yes changes no
    product: he gets the products the outfit showed, at the prices it showed.

    (At "Best for budget" a piece showed its cheapest product until it joined his wardrobe and a dearer one after:
    the button said + 40 €, the bar went up by 79 €, and My outfits marked the pieces "changed" at once. And at every
    level a yes added the plan's second white tee without the outfit's price saying so.)"""

    def agree(self, level: str) -> None:
        floor = self.plan_at_its_cheapest()
        self.give_budget(round(floor) + 150)        # room for "Best for budget" to take dearer products for some
        self.set_mode(level, 60)
        for turn in range(4):
            w = selection.build()
            products = self.products()
            outfit = next(o for o in (outfits.find_by_sig(w, sig) for sig in self.offered()) if yes.adds(w, o).cost > 0)
            said = yes.adds(w, outfit)
            new = [p for p in outfit.pieces if not p.view.mine]
            where = f"{level}, yes number {turn + 1}"
            # One of each piece: what it adds is the price of its new pieces, each once.
            self.assertAlmostEqual(said.cost, sum(p.price for p in new), places=2, msg=where)
            self.assertEqual(said.n_new, len(new), where)
            if turn == 0:       # nothing is his yet: what the first outfit adds is its own price
                self.assertAlmostEqual(said.cost, outfit.cost, places=2, msg=where)
            # The page: the outfit's price, the button, the line.
            page = self.page("/outfits", at=outfit.sig)
            slide = page[page.index(f'<article class="slide" id="outfit-{outfit.key}"'):]
            slide = slide[:slide.index("</article>")]
            self.assertIn(f'title="What the pieces in this outfit cost together">{eur(outfit.cost)}</b>', slide, where)
            self.assertIn(f'<span class="plus">+ {eur(said.cost)}</span>', slide, where)
            short = f'<span class="over-short"> · {html.escape(said.over_short)}</span>' if said.over_short else ""
            self.assertIn(f'<p class="adds">{html.escape(said.words)}{short}</p>', slide, where)
            self.assertIn(plain(f"{said.n_new} new {'piece' if said.n_new == 1 else 'pieces'} {eur(said.cost)}"),
                          plain(said.words), where)
            # Buy this outfit: the same pieces, one of each, for the outfit's price.
            buy = export.build(w, only=outfit.slots)
            self.assertAlmostEqual(buy.total, outfit.cost, places=2, msg=where)
            self.assertEqual(buy.pieces, len(outfit.pieces), where)
            self.assertIn(f'<p class="buy-head"><b>{eur(outfit.cost)}</b>', self.page("/outfits/buy", at=outfit.sig), where)
            # The yes: the bar gains what the outfit said, piece for piece and cent for cent.
            total, n_buy = w.mine.total, w.mine.n_buy
            answer = self.say_yes(outfit)
            now = selection.build()
            self.assertAlmostEqual(now.mine.total - total, said.cost, places=2,
                                   msg=f"{where}: the outfit said + {said.cost}, the bar went up by another sum")
            self.assertAlmostEqual(now.mine.total, said.total_after, places=2, msg=where)
            self.assertEqual(now.mine.n_buy - n_buy, said.n_new, where)
            self.assertEqual(self.products(), products, f"{where}: the yes changed a product")
            back = self.page(answer.headers["Location"])
            self.assertRegex(self.answered_line(back), "^Added " + self.called(outfit) + re.escape(plain(
                f" to your wardrobe: {said.words[0].lower()}{said.words[1:]}. ")) + self.its_pieces(outfit) + " Undo$", where)
            self.assertIn(plain(f"Total {eur(now.mine.total)}"), self.bar(back), where)
            # The shopping list holds what the bar counts, and My outfits shows the outfit as it is: nothing "changed".
            self.assertAlmostEqual(export.build(now.mine).total, now.mine.total, places=2, msg=where)
            self.assertEqual(export.build(now.mine).pieces, now.mine.n_buy, where)
            mine = self.page("/outfits", occasion="saved")
            self.assertNotIn("· changed", mine, where)
            self.assertIn(f'title="What the pieces in this outfit cost together">{eur(outfit.cost)}</b>', mine, where)
            self.assertAlmostEqual(export.build(now, only=outfit.slots).total, outfit.cost, places=2, msg=where)
        self.assertGreater(len(selection.build().mine.slots), len(outfit.pieces), "later yeses added to what he had")

    def test_at_cheapest(self):
        self.agree("cheapest")

    def test_at_cheap(self):
        self.agree("cheap")

    def test_at_medium(self):
        self.agree("medium")

    def test_at_expensive(self):
        self.agree("expensive")

    def test_at_top(self):
        self.agree("top")

    def test_at_best_for_budget(self):
        self.agree("budget")
        fitted = self.products()
        self.set_mode("cheapest", 60)
        self.assertNotEqual(self.products(), fitted, "the level took no dearer product than Cheapest: nothing was tested")

    def test_every_level_is_one_of_these(self):
        tested = {name.removeprefix("test_at_").replace("best_for_", "") for name in dir(self) if name.startswith("test_at_")}
        self.assertEqual(tested, set(selection.MODES))


class ASpare(YesCase):
    """Where the plan has a piece twice (two white tees), an outfit wears one and a yes adds that one. The second is a
    spare: the piece's card offers "Add a spare" and "Take the spare out", and it is counted and said as a spare."""

    def test_a_yes_adds_one_and_the_card_offers_the_other(self):
        # (A yes to an outfit of five pieces for 511.98 € added six for 536.97 €, "Buy this outfit" listed five.)
        tee, outfit = self.with_the_tee()
        adds = yes.adds(selection.build(), outfit)
        self.assertEqual((adds.n_new, adds.cost), (len(outfit.pieces), outfit.cost))
        self.assertEqual(adds.words, f"{len(outfit.pieces)} new pieces {eur(outfit.cost)}")
        self.assertNotIn("×", self.page("/outfits", at=outfit.sig).split('id="reel"')[1].split("</article>")[0])
        self.say_yes(outfit)
        w = selection.build()
        view = w.get(tee)
        self.assertEqual((view.qty, view.planned, view.cost), (1, 2, view.chosen.price))
        self.assertAlmostEqual(w.mine.total, outfit.cost, places=2)
        self.assertEqual(w.mine.n_buy, len(outfit.pieces))
        card = self.card(tee)
        self.assertNotIn('class="qty"', card, "one tee is his: the card does not say ×2")
        self.assertIn(f"Your outfits wear one. The plan has 2. Add a spare + {plain(eur(view.chosen.price))}", read(card))
        self.assertIn(f'<input type="hidden" name="want" value="in">\n      <button class="btn ghost small" id="spare-{tee}">', card)
        rows = list(csv.DictReader(io.StringIO(self.client.get("/list.csv").data.decode("utf-8-sig"))))
        self.assertEqual([row["quantity"] for row in rows if row["slot"] == view.slot["name"]], ["1"])
        self.assertEqual(len(rows), len(outfit.pieces))
        # A piece the plan has once has no such line.
        other = next(slot_id for slot_id in outfit.slots if slot_id != tee)
        self.assertNotIn("spare", self.card(other))
        # The plan page still shows what the plan has, and says what that means.
        plan = self.page("/slots")
        self.assertIn(f'{view.slot["name"]} <span class="qty">×2</span>', plan)
        self.assertIn("Where the plan has a piece twice (×2), an outfit adds one; the second is a spare you can add on "
                      "the piece's card in your Wardrobe.", read(plan))

    def test_add_a_spare_counts_it_and_says_so_and_take_it_out_again(self):
        tee, outfit = self.with_the_tee()
        self.say_yes(outfit)
        before = selection.build()
        price, name = before.get(tee).chosen.price, before.get(tee).slot["name"]
        added = self.client.post(f"/slot/{tee}/spare", data={"want": "in"})
        self.assertEqual(added.headers["Location"], f"/?spare={tee}&did=in")
        self.assertEqual(db.get_setting("spares"), [tee])
        w = selection.build()
        self.assertEqual((w.get(tee).qty, w.mine.n_buy), (2, before.mine.n_buy + 1))
        self.assertAlmostEqual(w.mine.total, before.mine.total + price, places=2)
        page = self.page(added.headers["Location"])
        self.assertIn(plain(f"Added a spare “{name}” to your wardrobe: {eur(price)}. Undo"), read(page))
        self.assertIn(plain(f"Total {eur(w.mine.total)}"), self.bar(page))
        self.assertIn(f"{w.mine.n_buy} pieces in your wardrobe", read(page))
        card = self.card(tee)
        self.assertIn(f'{name} <span class="qty">×2</span>', card)
        self.assertIn(plain(f"2 × {eur(price)}"), read(card))
        self.assertIn("One of the 2 is a spare. Take the spare out", read(card))
        # The shopping list and its files count two, and say that one is a spare.
        shopping = read(self.page("/list"))
        self.assertIn(plain(f"2 × {eur(price)} (one is a spare)"), shopping)
        self.assertIn(plain(eur(w.mine.total)), shopping)
        self.assertIn("(one is a spare)", self.client.get("/list.md").data.decode())
        rows = list(csv.DictReader(io.StringIO(self.client.get("/list.csv").data.decode("utf-8-sig"))))
        self.assertEqual([row["quantity"] for row in rows if row["slot"] == name], ["2"])
        # "Buy this outfit" is still the outfit: one of each.
        self.assertAlmostEqual(export.build(w, only=outfit.slots).total, outfit.cost, places=2)
        # Undo in the message, or "Take the spare out" on the card: one tee again, and the page says so.
        undo = re.search(r'<div class="flash said short" role="status">\s*Added a spare.*?</div>', page, re.S).group(0)
        self.assertIn(f'action="/slot/{tee}/spare"', undo)
        self.assertIn('name="want" value="out"', undo)
        taken = self.client.post(f"/slot/{tee}/spare", data={"want": "out"})
        self.assertEqual(taken.headers["Location"], f"/?spare={tee}&did=out")
        w = selection.build()
        self.assertEqual((w.get(tee).qty, db.get_setting("spares")), (1, []))
        self.assertAlmostEqual(w.mine.total, before.mine.total, places=2)
        page = self.page(taken.headers["Location"])
        self.assertIn(plain(f"Took the spare “{name}” out of your wardrobe: {eur(price)} less. Undo"), read(page))
        self.assertIn('name="want" value="in"', re.search(r'<div class="flash said short" role="status">\s*Took the spare.*?</div>',
                                                          page, re.S).group(0))
        # The message is said for what is so: opened again after Undo, the page says nothing of it.
        self.client.post(f"/slot/{tee}/spare", data={"want": "in"})
        self.assertNotIn("Took the spare", self.page(taken.headers["Location"]))

    def test_only_a_piece_of_his_wardrobe_that_the_plan_has_twice_has_a_spare(self):
        tee, outfit = self.with_the_tee()
        self.assertEqual(self.client.post(f"/slot/{tee}/spare", data={"want": "in"}).status_code, 409,
                         "the tee is not in his wardrobe yet")
        self.say_yes(outfit)
        once = next(slot_id for slot_id in outfit.slots if slot_id != tee)
        self.assertEqual(self.client.post(f"/slot/{once}/spare", data={"want": "in"}).status_code, 409)
        self.assertEqual(self.client.post("/slot/no-such-piece/spare", data={"want": "in"}).status_code, 404)
        self.post(f"/slot/{tee}/own")           # what he owns he need not buy twice
        self.assertEqual(self.client.post(f"/slot/{tee}/spare", data={"want": "in"}).status_code, 409)
        self.assertNotIn("spare", self.card(tee))
        self.assertEqual(db.get_setting("spares") or [], [])

    def test_three_in_the_plan_are_two_spares(self):
        tee, outfit = self.with_the_tee()
        db.update_slot(tee, qty=3)
        self.say_yes(outfit)
        view = self.view(tee)
        self.assertEqual(view.spare_words, ("2 of the 3 are spares", "Add 2 spares", "Take the spares out"))
        self.assertIn(f"Your outfits wear one. The plan has 3. Add 2 spares + {plain(eur(2 * view.chosen.price))}",
                      read(self.card(tee)))
        added = self.client.post(f"/slot/{tee}/spare", data={"want": "in"})
        self.assertIn(plain(f"Added 2 spares of “{view.slot['name']}” to your wardrobe: {eur(2 * view.chosen.price)}."),
                      read(self.page(added.headers["Location"])))
        self.assertIn("2 of the 3 are spares. Take the spares out", read(self.card(tee)))
        self.assertIn("(2 are spares)", read(self.page("/list")))
        self.assertEqual(self.view(tee).qty, 3)

    def test_the_spare_goes_with_its_piece_and_comes_back_with_undo(self):
        tee, outfit = self.with_the_tee()
        self.say_yes(outfit)
        self.client.post(f"/slot/{tee}/spare", data={"want": "in"})
        total = selection.build().mine.total
        name = self.view(tee).slot["name"]
        out = self.take_out(outfit, on="saved")
        self.assertEqual((self.mine(), db.get_setting("spares")), (set(), []))
        self.assertIn(f"{name} with its spare", read(self.page(out.headers["Location"])))
        self.client.post("/outfits/save", data={"key": outfit.key, "want": "restore", "on": "saved"})
        self.assertEqual(db.get_setting("spares"), [tee])
        self.assertAlmostEqual(selection.build().mine.total, total, places=2)
        # Taken out for good, and a later yes to an outfit with the tee: one tee, as that outfit shows.
        self.take_out(outfit, on="saved")
        db.set_setting("spares", [tee])         # (a mark left from earlier must not make the yes add two)
        w = selection.build()
        self.assertEqual(w.get(tee).qty, 1)
        other = next(o for o in outfits.all_outfits(w) if tee in o.slots and o.sig != outfit.sig)
        said = yes.adds(w, other)
        self.say_yes(other)
        self.assertEqual((self.view(tee).qty, db.get_setting("spares")), (1, []))
        self.assertAlmostEqual(selection.build().mine.total, said.cost, places=2)

    def test_a_kept_piece_taken_out_takes_its_spare_along_and_undo_brings_both_back(self):
        tee, _ = self.with_the_tee()
        yes.keep(tee, True)
        self.client.post(f"/slot/{tee}/spare", data={"want": "in"})
        self.assertEqual(self.view(tee).qty, 2)
        out = self.client.post(f"/slot/{tee}/keep", data={"want": "out"})
        self.assertEqual(out.headers["Location"], f"/?took={tee}&with_spare=1")
        self.assertEqual((self.mine(), db.get_setting("spares")), (set(), []))
        page = self.page(out.headers["Location"])
        self.assertIn(f"Took “{self.view(tee).slot['name']}” with its spare out of your wardrobe.", read(page))
        self.assertIn('<input type="hidden" name="spare" value="1">', page)
        self.client.post(f"/slot/{tee}/keep", data={"want": "in", "spare": "1"})
        self.assertEqual((self.view(tee).qty, self.view(tee).kept), (2, True))

    def test_removed_from_the_plan_its_spare_is_forgotten(self):
        tee, outfit = self.with_the_tee()
        self.say_yes(outfit)
        self.client.post(f"/slot/{tee}/spare", data={"want": "in"})
        self.client.post(f"/slots/{tee}/delete")
        self.assertEqual(db.get_setting("spares"), [])

    def test_at_best_for_budget_a_spare_changes_no_product(self):
        # The level is fitted for the whole plan, each piece as often as the plan has it: adding the spare, or taking
        # it out, moves no money between pieces.
        floor = self.plan_at_its_cheapest()
        self.give_budget(round(floor) + 150)
        self.set_mode("budget", 60)
        tee, outfit = self.with_the_tee()
        products = self.products()
        self.say_yes(outfits.find_by_sig(selection.build(), outfit.sig))
        self.assertEqual(self.products(), products)
        total = selection.build().mine.total
        self.client.post(f"/slot/{tee}/spare", data={"want": "in"})
        self.assertEqual(self.products(), products)
        w = selection.build()
        self.assertAlmostEqual(w.mine.total, total + w.get(tee).chosen.price, places=2)
        self.assertLessEqual(w.mine.total, w.budget)


class WhereHeGoesOnAfterAYes(YesCase):
    """After a yes the page comes back on the next outfit in line, never back at the first: the outfits that stood
    in front of the one he answered keep their places, and behind them come the others, those that reuse most of
    what he now has first."""

    def keys(self, page: str) -> list[str]:
        return re.findall(r'<article class="slide" id="outfit-(\w+)"', page)

    def test_after_a_yes_to_the_fifth_outfit_the_four_he_passed_are_still_in_front(self):
        page = self.page("/outfits")
        keys, shown = self.keys(page), self.offered()
        fifth = outfits.find_by_sig(selection.build(), shown[4])
        self.assertEqual(fifth.key, keys[4])
        answer = self.say_yes(fifth)
        where = answer.headers["Location"]
        self.assertTrue(where.startswith(f"/outfits?added={fifth.key}&front={'.'.join(keys[:4])}#outfit-"), where)
        back = self.page(where.split("#")[0])
        now, now_shown = self.keys(back), self.offered(front=".".join(keys[:4]))
        self.assertEqual(now[:4], keys[:4], "the four outfits he had passed are not in front any more")
        self.assertEqual(where.split("#outfit-")[1], now[4], "the page does not come back on the outfit now fifth in line")
        self.assertNotIn(fifth.key, now)
        self.assertEqual(len(now), 12)
        # Behind the four, the outfits that wear most of what he now has come first, and the page says where that starts.
        have = set(fifth.slots)
        reused = [len(have & set(sig.split("~"))) for sig in now_shown[4:]]
        self.assertEqual(reused, sorted(reused, reverse=True))
        self.assertGreater(reused[0], 0)
        self.assertIn("from outfit 5 on, those that use pieces you already have come first", read(back))
        self.assertRegex(self.answered_line(back), "^Added " + self.called(fifth, 5) + " to your wardrobe")
        # Every form under an outfit, and Undo, carry the row, so the next answer comes back to it too.
        self.assertEqual(back.count(f'<input type="hidden" name="front" value="{".".join(keys[:4])}">'), 12 + 12 + 1)
        # A second yes, to the outfit he is now on: the same four stay in front.
        sixth = outfits.find(selection.build(), now[4])
        again = self.say_yes(sixth, front=".".join(keys[:4]))
        self.assertTrue(again.headers["Location"].startswith(
            f"/outfits?added={sixth.key}&front={'.'.join(keys[:4])}#outfit-"), again.headers["Location"])
        self.assertEqual(self.keys(self.page(again.headers["Location"].split("#")[0]))[:4], keys[:4])

    def test_after_a_yes_to_the_first_outfit_the_next_in_line_is_the_new_first(self):
        first = outfits.find_by_sig(selection.build(), self.offered()[0])
        answer = self.say_yes(first)
        self.assertEqual(answer.headers["Location"], f"/outfits?added={first.key}")
        page = self.page(answer.headers["Location"])
        self.assertIn("· outfits that use pieces you already have come first", read(page))
        self.assertNotIn('name="front"', page)

    def test_undo_after_a_yes_shows_that_outfit_again_where_it_was(self):
        page = self.page("/outfits")
        keys, shown = self.keys(page), self.offered()
        third = outfits.find_by_sig(selection.build(), shown[2])
        answer = self.say_yes(third)
        front = ".".join(keys[:2])
        undo = self.take_out(third, front=front)
        self.assertEqual(undo.headers["Location"],
                         f"/outfits?at={third.sig}&removed={third.key}&front={'.'.join(keys)}#outfit-{third.key}")
        now = self.keys(self.page(undo.headers["Location"].split("#")[0]))
        # The whole row as it was before the yes: the outfits behind it are not sorted again either.
        self.assertEqual(now, keys, "Undo of the yes moved outfits of the row")
        self.assertEqual(self.mine(), set())
        self.assertIn("added=", answer.headers["Location"])

    def test_a_no_in_such_a_row_leaves_the_others_where_they_are(self):
        page = self.page("/outfits")
        keys, shown = self.keys(page), self.offered()
        self.say_yes(outfits.find_by_sig(selection.build(), shown[3]))
        front = ".".join(keys[:3])
        row = self.keys(self.page("/outfits", front=front))
        second = outfits.find(selection.build(), row[1])           # one of the three in front, after all
        answer = self.client.post("/outfits/no", data={"sig": second.sig, "next": row[2], "front": front})
        rest = ".".join(row[:1] + row[2:])
        self.assertEqual(answer.headers["Location"], f"/outfits?declined={second.sig}&front={rest}#outfit-{row[2]}")
        after = self.keys(self.page(answer.headers["Location"].split("#")[0]))
        self.assertEqual(after[:11], row[:1] + row[2:], "the other outfits moved")
        # Undo puts it back between the two.
        back = self.client.post("/outfits/no", data={"sig": second.sig, "want": "undo", "front": rest})
        self.assertEqual(back.headers["Location"], f"/outfits?front={'.'.join(row)}#outfit-{second.key}")
        self.assertEqual(self.keys(self.page(back.headers["Location"].split("#")[0])), row)

    def test_once_he_has_pieces_show_more_and_a_no_on_the_last_keep_what_he_has_seen_in_place(self):
        # (With pieces in his wardrobe the longer row was sorted again by pieces reused: of the 12 new outfits some
        # came in front of him, and a no on the last outfit put the newcomer among those he had passed.)
        first = outfits.find_by_sig(selection.build(), self.offered()[0])
        self.say_yes(first)
        seen = self.keys(self.page("/outfits"))
        more = html.unescape(re.search(r'<a class="btn" href="([^"]*)">Show more outfits</a>',
                                       self.page("/outfits")).group(1))
        self.assertIn(f"front={'.'.join(seen)}", more)
        longer = self.keys(self.page(more.split("#")[0]))
        self.assertEqual((len(longer), longer[:12]), (24, seen), "the new outfits are not all behind those he has seen")
        # A no on the last of the 24: the others stay, and one more joins at the end.
        last = outfits.find(selection.build(), longer[-1])
        front = more.split("front=")[1].split("#")[0]
        answer = self.client.post("/outfits/no", data={"sig": last.sig, "n": "24", "front": front, "i": "23"})
        after = self.keys(self.page(answer.headers["Location"].split("#")[0]))
        self.assertEqual(after[:23], longer[:23], "a no on the last outfit moved outfits he had passed")
        self.assertNotIn(last.key, after)
        self.assertTrue(answer.headers["Location"].endswith(f"#outfit-{after[23]}"))

    def test_what_stands_in_front_is_only_what_the_address_may_name(self):
        # Nonsense under "front", or outfits that no longer exist: the row every visit starts with.
        usual = self.keys(self.page("/outfits"))
        for front in ("x", "../../etc", "000000000000.111111111111", "." * 50):
            self.assertEqual(self.keys(self.page("/outfits", front=front)), usual, front)
        # An outfit named twice stands there once, and the row is never longer than asked for.
        twice = self.keys(self.page("/outfits", front=f"{usual[5]}.{usual[5]}.{usual[7]}"))
        self.assertEqual((twice[:2], len(twice), len(set(twice))), ([usual[5], usual[7]], 12, 12))
        # "Show more outfits" keeps the row as it is.
        self.assertIn(f"front={usual[5]}.{usual[7]}.", html.unescape(
            re.search(r'<a class="btn" href="([^"]*)">Show more outfits</a>',
                      self.page("/outfits", front=f"{usual[5]}.{usual[7]}")).group(1)))


class TheBudget(YesCase):
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
        page = self.page("/outfits", at=b.sig)
        # In red, as plain words with the small flag before them: money over budget.
        self.assertRegex(page, rf'<p class="adds over"><svg class="ic"[^>]*>.*?</svg> {re.escape(html.escape(said))}</p>')
        # … in the outfit's own box, above the button: on a phone the whole box is what stands over the tab bar
        # (the walk-through measures where it shows).
        box = re.search(rf'<article class="slide" id="outfit-{b.key}".*?<div class="yes-box" data-answer>(.*?)<ul class="pieces">',
                        page, re.S).group(1)
        self.assertLess(box.index('<p class="adds over">'), box.index(f'id="save-{b.key}"'))
        self.assertLess(box.index('<p class="adds">'), box.index('<p class="adds over">'))
        self.assertIn(plain(said), read(self.page("/outfits/buy", at=b.sig)))
        # One that adds nothing to buy takes him nowhere: it says nothing of the budget.
        self.assertEqual(yes.adds(w, a).over_words, "")
        # After the yes the bar says he is over, by that much.
        self.say_yes(b)
        bar = read(re.search(r'<section id="summary".*?</section>', self.page("/"), re.S).group(0))
        self.assertIn(plain(f"Over budget {eur(over)}"), bar)

    def test_best_for_budget_is_fitted_for_the_whole_plan_so_a_yes_changes_no_product(self):
        floor = self.plan_at_its_cheapest()
        self.give_budget(round(floor) + 150)
        self.set_mode("budget", 60)
        w = selection.build()
        self.assertGreater(w.total, floor, "the money left buys better")
        self.assertLessEqual(w.total, w.budget)
        self.assertEqual(w.note, "")
        before = self.products()
        for _ in range(4):      # one yes after another: no piece changes its product, in his wardrobe or outside it
            self.say_yes(outfits.find_by_sig(selection.build(), self.offered()[0]))
            self.assertEqual(self.products(), before)
        w = selection.build()
        self.assertGreater(w.mine.total, 0)
        self.assertLessEqual(w.mine.total, w.budget, "his wardrobe is part of the plan, and the plan fits")

    def test_at_best_for_budget_a_yes_adds_exactly_what_the_outfit_said(self):
        # (It did not: a piece showed its cheapest product until it joined his wardrobe, and a dearer one after, so
        # the bar went up by more than the button had said, and My outfits marked the pieces "changed" at once.)
        floor = self.plan_at_its_cheapest()
        self.give_budget(round(floor) + 150)
        self.set_mode("budget", 60)
        for _ in range(4):
            w = selection.build()
            outfit = next(o for o in (outfits.find_by_sig(w, sig) for sig in self.offered()) if yes.adds(w, o).cost > 0)
            said = yes.adds(w, outfit)
            page = self.page("/outfits", at=outfit.sig)
            self.assertIn(f'<span class="plus">+ {eur(said.cost)}</span>', page)
            self.assertIn(f'<p class="adds">{html.escape(said.words)}</p>', page)
            shown = {p.view.slot["id"]: p.view.chosen.id for p in outfit.pieces}
            total = w.mine.total
            answer = self.say_yes(outfit)
            now = selection.build()
            self.assertAlmostEqual(now.mine.total - total, said.cost, places=2, msg="the bar went up by another sum")
            self.assertAlmostEqual(now.mine.total, said.total_after, places=2)
            self.assertEqual({slot_id: now.get(slot_id).chosen.id for slot_id in shown}, shown,
                             "he got other products than the outfit he said yes to showed")
            back = self.page(answer.headers["Location"])
            self.assertIn(plain(f"{said.words[0].lower()}{said.words[1:]}. Its pieces: "), read(back))
            bar = read(re.search(r'<section id="summary".*?</section>', back, re.S).group(0))
            self.assertIn(plain(f"Total {eur(now.mine.total)}"), bar)
            self.assertNotIn("· changed", self.page("/outfits", occasion="saved"))

    def test_best_for_budget_says_so_when_the_whole_plan_cannot_fit_and_the_sums_stay_true(self):
        floor = self.plan_at_its_cheapest()
        cheapest = self.products()
        a, b = self.two_that_share()
        first = yes.adds(selection.build(), a).cost
        self.give_budget(round(first) + 5)
        self.assertLess(round(first) + 5, floor)
        self.set_mode("budget", 60)
        w = selection.build()
        self.assertEqual(self.products(), cheapest, "every piece is on its cheapest option")
        note = ("Even on their cheapest options that reach your minimum quality, the pieces your outfits are made from "
                "come to more than your budget together, so every piece is on its cheapest option.")
        self.assertTrue(w.note.startswith(note), w.note)
        self.say_yes(outfits.find_by_sig(w, a.sig))
        self.assertIn(note, read(self.page("/")))
        w = selection.build()
        adds = yes.adds(w, outfits.find_by_sig(w, b.sig))
        self.assertAlmostEqual(adds.over_by, first + adds.cost - w.budget, places=2)
        self.say_yes(outfits.find_by_sig(w, b.sig))
        self.assertAlmostEqual(selection.build().mine.remaining, -adds.over_by, places=2,
                               msg="after the yes he is over by what the outfit said")

    def test_the_level_row_says_what_his_wardrobe_costs_at_best_for_budget(self):
        floor = self.plan_at_its_cheapest()
        self.give_budget(round(floor) + 150)
        a, _ = self.two_that_share()
        self.say_yes(a)
        told = selection.build().mine.levels["budget"]        # said on the Wardrobe page while another level is on
        self.set_mode("budget", 60)
        w = selection.build().mine
        self.assertAlmostEqual(told, w.total, places=2, msg="choosing the level gives another sum than its label said")
        self.assertAlmostEqual(w.levels["budget"], w.total, places=2)

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

    def test_owned_taken_back_returns_the_piece_to_where_it_was(self):
        # A piece that was not in his wardrobe: "Owned" puts it there, taking it back takes it out again. (It stayed,
        # as something to buy he had never chosen, and the bar went up by its price.)
        piece = selection.build().slots[0].slot["id"]
        self.post(f"/slot/{piece}/own")
        self.assertEqual(self.mine(), {piece})
        self.post(f"/slot/{piece}/own")
        self.assertEqual(self.mine(), set(), "the piece stayed in his wardrobe as something to buy")
        self.assertEqual(selection.build().mine.total, 0)
        self.assertFalse(yes.owned_from_outside(piece))
        # A piece he kept, or one from before this was remembered: it was in his wardrobe, so it stays, now to buy.
        other = selection.build().slots[1].slot["id"]
        yes.keep(other, True)
        self.post(f"/slot/{other}/own")
        self.post(f"/slot/{other}/own")
        self.assertEqual(self.mine(), {other}, "the card vanished under his finger")
        self.assertGreater(selection.build().mine.total, 0)
        third = selection.build().slots[2].slot["id"]
        db.update_slot(third, owned=True)       # (owned before the place it came from was remembered)
        self.post(f"/slot/{third}/own")
        self.assertIn(third, self.mine())

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
        # The message counts every piece once: the new plan's pieces "in your colours", and apart from them the
        # pieces of his outfit that it has no place for (the navy one, in a colour he just refused).
        slots = db.list_slots()
        stayed = [slot for slot in slots if slot["id"] in outfit.slots and slot["colour"] == "navy"]
        n, kept = sum(slot["qty"] for slot in slots), sum(slot["qty"] for slot in stayed)
        self.assertGreater(kept, 0)
        said = re.search(r"Your plan now has (\d+) pieces in your colours\. The (\d+) pieces? of your wardrobe that the "
                         r"new plan has no place for (?:was kept as it was|were kept as they were): (\d+) pieces in all\.",
                         read(self.page("/outfits")))
        self.assertIsNotNone(said)
        fresh, counted, in_all = (int(number) for number in said.groups())
        self.assertEqual((fresh + counted, in_all), (n, n), "a piece is counted twice, or not at all")
        self.assertGreaterEqual(counted, kept)
        in_colours = [slot for slot in slots if slot["colour"] != "navy"]
        self.assertLessEqual(fresh, sum(slot["qty"] for slot in in_colours), "a refused colour among 'your colours'")
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
                DELETE FROM settings WHERE key IN ('kept_pieces', 'spares', 'wardrobe_news', 'welcome', 'answered',
                                                   'budget_as_before');
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
            self.assertEqual(con.execute("PRAGMA user_version").fetchone()[0], db.SCHEMA_VERSION)
        self.assertEqual(self.rows("slots"), slots, "every piece of the plan is as it was")
        self.assertEqual(self.rows("saved_outfits", "user_id, key, saved_at, label, pieces"), saved)
        self.assertEqual(self.rows("saved_outfits", "sig"), [(a.sig,)], "the saved outfit says which pieces it combines")
        self.assertEqual([row for row in self.rows("settings") if row[1] not in ("kept_pieces", "spares", "wardrobe_news")],
                         settings, "his answers and choices are as they were")
        self.assertEqual((db.get_setting("kept_pieces"), db.get_setting("wardrobe_news")), ([locked], True))
        self.assertEqual(db.get_setting("spares"), [], "none of his pieces is one the plan has twice")
        self.assertEqual(self.rows("outfits_declined"), [])

        # His wardrobe: the saved outfit's pieces, the piece he chose by hand (with its product), the one he owns.
        w = selection.build()
        self.assertEqual(self.mine(), set(a.slots) | {locked, owned})
        self.assertEqual((w.n_outfits, w.get(locked).state, w.get(owned).state), (1, "locked", "owned"))
        self.assertTrue(all(w.get(slot_id).chosen for slot_id in untouched), "the rest keeps its products")
        # The first page says so, once, with the numbers.
        n_mine = sum(view.qty for view in w.mine.slots)
        n_rest = sum(view.planned for view in w.slots if not view.mine)
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

    def test_on_best_for_budget_every_piece_keeps_its_product(self):
        # (One of his pieces changed product at the upgrade, under the sentence "with the same products".)
        self.page("/")
        profile_mod.save({**profile_mod.load(), "budget": 1400, "example": False})
        self.set_mode("budget", 60)
        a, _ = self.two_that_share()
        self.client.post("/outfits/save", data={"key": a.key}, headers=HX)
        others = [view.slot["id"] for view in selection.build().slots if view.slot["id"] not in a.slots]
        self.post(f"/slot/{others[0]}/lock")
        before = {view.slot["id"]: view.chosen.id for view in self.plan_of_version_8()}
        self.version_8()                                     # (an account from before the welcome: its budget is his)
        db.init()
        w = selection.build()
        self.assertTrue(w.budget_known)
        self.assertGreater(len(w.mine.slots), 0)
        self.assertGreater(w.total, self.cheapest_total(), "the level did upgrade pieces")
        self.assertEqual({view.slot["id"]: view.chosen.id for view in w.slots if view.chosen}, before)
        self.assertIn("outfits are still made from them, with the same products", read(self.page("/outfits")))

    def test_on_best_for_budget_with_the_budget_his_account_started_with_nothing_changes_either(self):
        # He never gave a budget: the level was fitted to the one his account started with, and the bar showed it.
        # From now on that level waits for a budget he gave himself, and would give him the cheapest products. He
        # keeps what he had, and the page says which budget it is fitted to.
        self.page("/")
        self.assertTrue(profile_mod.load()["example"])
        self.set_mode("cheapest", 60)
        cheapest = self.products()
        self.set_mode("budget", 60)
        a, _ = self.two_that_share()
        self.client.post("/outfits/save", data={"key": a.key}, headers=HX)
        before = {view.slot["id"]: view.chosen.id for view in self.plan_of_version_8()}
        self.assertNotEqual(before, cheapest, "the level did take dearer products")
        self.version_8()
        db.init()
        self.assertIs(db.get_setting("budget_as_before"), True)
        w = selection.build()
        self.assertFalse(w.budget_known)
        self.assertEqual(self.products(), before, "one of his products changed with the upgrade")
        budget = profile_mod.load()["budget"]
        page = self.page("/")
        self.assertIn(f"“Best for budget” is still fitted to {budget:,.0f} €, the budget your account started with, as "
                      "before. Set your own budget on the Profile page.", read(page))
        self.assertIn("Set a budget", self.bar(page), "the bar does not count against a budget he never gave")
        self.assertAlmostEqual(w.mine.levels["budget"], w.mine.total, places=2)
        # A yes still adds what the outfit says, and no product moves.
        outfit = next(o for o in (outfits.find_by_sig(w, sig) for sig in self.offered()) if yes.adds(w, o).cost > 0)
        said, total = yes.adds(w, outfit), w.mine.total
        self.say_yes(outfit)
        self.assertAlmostEqual(selection.build().mine.total - total, said.cost, places=2)
        self.assertEqual(self.products(), before)
        # Someone who was on another level then is not given this: the level asks him for a budget, as it asks a
        # new customer.
        self.set_mode("cheapest", 60)
        db.set_setting("budget_as_before", None)
        self.set_mode("budget", 60)
        self.assertIn("“Best for budget” needs your budget", selection.build().note)

    def plan_of_version_8(self) -> list:
        """Every piece with the product version 8 gave it at "Best for budget": the whole plan fitted to the
        budget, whatever was saved (there was no wardrobe apart from the plan)."""
        w = selection.build()
        picks = selection._fit(w)[0]
        for view in w.slots:
            if view.slot["id"] in picks:
                view.chosen = picks[view.slot["id"]]
        return [view for view in w.slots if view.chosen]

    def cheapest_total(self) -> float:
        return selection.build().levels["cheapest"]

    def test_a_database_at_this_number_that_never_had_this_upgrade_gets_it_when_the_number_goes_up(self):
        # The style chat, built alongside on a branch of its own, called its upgrade version 9 as well. Joined, this
        # upgrade is version 9 and the chat's is version 10. A database that carries the chat's 9 holds the chat's
        # table and saved outfits without `sig`: whether this upgrade ran is read from that, not from the number, so
        # it still gets it.
        self.page("/")
        a, _ = self.two_that_share()
        self.client.post("/outfits/save", data={"key": a.key}, headers=HX)
        self.version_8()                                     # (the chat's table stays: its branch had made it)
        with closing(sqlite3.connect(paths.DB_PATH)) as con:
            self.assertEqual(con.execute("SELECT COUNT(*) FROM chat_requests").fetchone()[0], 0)
            con.executescript("PRAGMA user_version = 9;")
            con.commit()
        db.init()
        with closing(sqlite3.connect(paths.DB_PATH)) as con:
            self.assertEqual(con.execute("PRAGMA user_version").fetchone()[0], db.SCHEMA_VERSION)
        self.assertEqual(self.rows("saved_outfits", "sig"), [(a.sig,)])
        self.assertEqual((db.get_setting("kept_pieces"), db.get_setting("wardrobe_news")), ([], True))
        self.assertEqual(self.rows("outfits_declined"), [])
        self.assertEqual(self.mine(), set(a.slots))

    def test_a_piece_the_plan_has_twice_still_counts_twice_where_it_is_in_his_wardrobe(self):
        # Before the upgrade his total counted both white tees. Where the tee is in his wardrobe (a saved outfit
        # wears it) it still counts twice, said as a spare he can take out; where it is not, nothing is his.
        self.page("/")
        w = selection.build()
        twice = next(view for view in w.slots if view.planned == 2)
        with_it = next(o for o in outfits.all_outfits(w) if twice.slot["id"] in o.slots)
        self.client.post("/outfits/save", data={"key": with_it.key}, headers=HX)
        self.version_8()
        db.init()
        self.assertEqual(db.get_setting("spares"), [twice.slot["id"]])
        view = self.view(twice.slot["id"])
        self.assertEqual((view.qty, view.cost), (2, 2 * view.chosen.price))
        self.assertAlmostEqual(selection.build().mine.total, with_it.cost + view.chosen.price, places=2)
        n_mine = len(with_it.slots) + 1         # the one-time message counts the spare, as the bar does
        self.assertIn(f"It starts with the 1 outfit you had saved: {n_mine} pieces in all.", read(self.page("/outfits")))
        self.assertIn("One of the 2 is a spare. Take the spare out", read(self.card(twice.slot["id"])))

    def test_a_piece_the_plan_has_twice_that_is_not_in_his_wardrobe_gets_no_spare(self):
        self.page("/")
        a, _ = self.two_that_share()                         # (neither wears the white tee)
        self.client.post("/outfits/save", data={"key": a.key}, headers=HX)
        self.version_8()
        db.init()
        self.assertEqual(db.get_setting("spares"), [])

    def test_the_start_is_given_once_whatever_number_the_database_carries(self):
        # A database that has had this upgrade, and then meets a later number (the two branches joined, or the next
        # version): he has since taken out a piece he had chosen by hand, and read the message. A second run would
        # put the piece back into his wardrobe and say the message again.
        self.page("/")
        piece = selection.build().slots[0].slot["id"]
        self.post(f"/slot/{piece}/lock")
        self.assertEqual(self.view(piece).state, "locked")
        self.assertIn(db.get_setting("kept_pieces"), (None, []))
        self.assertIsNone(db.get_setting("wardrobe_news"))
        settings = self.rows("settings")
        with mock.patch.object(db, "SCHEMA_VERSION", db.SCHEMA_VERSION + 1):
            db.init()
            with closing(sqlite3.connect(paths.DB_PATH)) as con:
                self.assertEqual(con.execute("PRAGMA user_version").fetchone()[0], db.SCHEMA_VERSION)
        self.assertEqual(self.rows("settings"), settings)
        self.assertEqual(self.mine(), set())

    def test_someone_who_had_touched_nothing_starts_with_an_empty_wardrobe_and_is_told(self):
        self.page("/")
        self.version_8()
        db.init()
        self.assertEqual((self.mine(), db.get_setting("kept_pieces")), (set(), []))
        n = sum(view.planned for view in selection.build().slots)
        self.assertEqual(n, sum(slot["qty"] for slot in db.list_slots()))
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

    def test_a_budget_of_0_is_no_budget(self):
        # (It was taken as a budget of 0 €: the bar read "of 0 €" and every outfit warned.)
        ada = self.member("ada@example.com")
        for typed in ("0", "0.4", "-20", "lots"):
            onwards = ada.post("/welcome/2", data={"csrf_token": self.token(ada), "budget": typed})
            self.assertEqual(onwards.headers["Location"], "/welcome/3")
            self.assertEqual(self.answered(), set(), typed)
            self.assertIn("A budget has to be more than 0 €, so what you typed was not saved as your budget.",
                          read(ada.get("/welcome/3").data.decode()), typed)
        with db.as_user(self.user_id("ada@example.com")):
            self.assertFalse(selection.build().budget_known)
        page = ada.get("/outfits").data.decode()
        self.assertNotIn("over your budget", page)
        self.assertNotIn("of 0", read(re.search(r'<section id="summary".*?</section>', page, re.S).group(0)))
        # On Profile too: the field is not saved, and a budget he had stays.
        form = {"top_size": "M", "waist": "32", "length": "32", "shoe": "43", "height_cm": "180", "weight_kg": "78",
                "liked": "navy, white", "refused": "", "use": "both", "shoes": "on", "outerwear": "on", "owned": ""}
        self.post(ada, "/profile", **form, budget="0")
        self.assertNotIn("budget", self.answered())
        self.post(ada, "/profile", **form, budget="900")
        self.assertEqual((self.profile()["budget"], "budget" in self.answered()), (900, True))
        saved = self.post(ada, "/profile", **form, budget="0")
        self.assertEqual(self.profile()["budget"], 900)
        self.assertIn("A budget has to be more than 0 €, so what you typed was not saved as your budget.",
                      read(ada.get(saved.headers["Location"]).data.decode()))

    def test_an_emptied_budget_field_clears_the_budget_and_says_so(self):
        # (Once set, a budget could not be taken away: an empty field kept it.)
        ada = self.member("ada@example.com")
        form = {"top_size": "M", "waist": "32", "length": "32", "shoe": "43", "height_cm": "180", "weight_kg": "78",
                "liked": "navy, white", "refused": "", "use": "both", "shoes": "on", "outerwear": "on", "owned": ""}
        self.post(ada, "/profile", **form, budget="900")
        self.assertIn("To have no budget, empty the field and save.", read(ada.get("/profile").data.decode()))
        saved = self.post(ada, "/profile", **form, budget="")
        self.assertNotIn("budget", self.answered())
        with db.as_user(self.user_id("ada@example.com")):
            self.assertFalse(selection.build().budget_known)
        self.assertIn("Budget cleared. The bar at the top now shows what your wardrobe costs, without a budget.",
                      read(ada.get(saved.headers["Location"]).data.decode()))
        self.assertIn('id="budget" name="budget" min="0" inputmode="numeric" value=""', ada.get("/profile").data.decode())
        # Saved again with the field still empty: nothing to clear, nothing said.
        again = self.post(ada, "/profile", **form, budget="")
        self.assertNotIn("Budget cleared", read(ada.get(again.headers["Location"]).data.decode()))

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
