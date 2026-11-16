"""A chosen product that is sold out in your size.

A product chosen by hand stays the piece's product when its size sells out afterwards (the automatic pick never takes
one that is). The promises:

  * wherever the piece shows (an outfit's list of pieces and its pop-up, the Wardrobe, the Shopping list, Buy this
    outfit, the Saved outfits) it says "Sold out in M" with the store's own label for your size;
  * one tap offers the next best product that is known to be in stock in your size, with the true difference in
    price ("+10 €", "−5 €", "same price"); it chooses it as the pop-up's Choose does, and the page you were on says
    so with Undo, which brings you back to the same page;
  * with nothing else in stock in your size, that is said, with "Add one you found yourself": but only when it is
    known. Other products whose sizes were never checked (COS) are counted and pointed to instead;
  * while the sizes are still the example's, the size is said to be the example size;
  * "not made in your size" is never counted under the words "sold out in your size";
  * the outfit stays as it is;
  * no total counts a sold-out product as something to buy, and every total that leaves one out says so.

The stock is the one the product list already has (each product's sizes in stock); nothing new is collected.
"""
import csv
import io
import re
import unittest

from wardrobe import catalog, db, english, export, outfits, programmes, selection, sizes
from wardrobe import profile as profile_mod
from wardrobe.app import eur

from .test_app import HX, AppCase
from .test_looks import as_read, flashes, status_line
from .test_size_picks import cos, option, weekday


class TheNextBest(unittest.TestCase):
    """selection.next_best: what is offered in place of a product sold out in your size."""

    def test_it_is_in_stock_in_your_size_and_nearest_in_price(self):
        gone = option(weekday(1, 30, in_stock=["S", "L"]))
        cheaper, dearer, far = option(weekday(2, 22)), option(weekday(3, 35)), option(weekday(4, 80))
        self.assertEqual(selection.next_best([gone, cheaper, dearer, far], gone, 70).id, dearer.id)
        self.assertEqual(selection.next_best([gone, cheaper, far], gone, 70).id, cheaper.id)

    def test_never_one_whose_sizes_were_not_checked_or_that_is_sold_out_too(self):
        gone = option(weekday(1, 30, in_stock=["S", "L"]))
        unchecked, also_gone, no_price = option(cos(2, 30)), option(weekday(3, 30, in_stock=["S"])), option(weekday(4, 0))
        self.assertEqual(unchecked.size.rank, sizes.NOT_CHECKED)
        self.assertIsNone(selection.next_best([gone, unchecked, also_gone, no_price], gone, 70))
        self.assertIsNone(selection.next_best([gone], gone, 70))

    def test_good_enough_first_and_at_the_same_distance_the_better_then_the_cheaper(self):
        gone = option(weekday(1, 30, in_stock=["S", "L"]))
        poor_but_same_price, good = option(weekday(2, 30), quality=40), option(weekday(3, 45), quality=85)
        self.assertEqual(selection.next_best([gone, poor_but_same_price, good], gone, 70).id, good.id)
        # With none that reaches the minimum quality, one in his size is still better than none.
        self.assertEqual(selection.next_best([gone, poor_but_same_price], gone, 70).id, poor_but_same_price.id)
        better, worse = option(weekday(4, 35), quality=90), option(weekday(5, 25), quality=75)
        self.assertEqual(selection.next_best([gone, worse, better], gone, 70).id, better.id)
        twin_low, twin_high = option(weekday(6, 25), quality=80), option(weekday(7, 35), quality=80)
        self.assertEqual(selection.next_best([gone, twin_high, twin_low], gone, 70).id, twin_low.id)


    def test_one_as_good_as_the_one_he_chose_is_good_enough(self):
        # He chose a 67 under a minimum of 70. Another 67 at the same price is the next best, not an 80 for 5 € more.
        gone = option(weekday(1, 19.99, in_stock=["S", "L"]), quality=67)
        twin, better = option(weekday(2, 19.99), quality=67), option(weekday(3, 24.99), quality=80)
        self.assertEqual(selection.next_best([gone, better, twin], gone, 70).id, twin.id)
        # One rated lower than his own choice and under the minimum still waits behind those that are good enough.
        worse = option(weekday(4, 19.99), quality=50)
        self.assertEqual(selection.next_best([gone, worse, better], gone, 70).id, better.id)

    def test_the_words_for_several_pieces_say_which_it_is(self):
        self.assertEqual(selection.gone_words(2, 0), "sold out in your size")
        self.assertEqual(selection.gone_words(0, 1), "not made in your size")
        self.assertEqual(selection.gone_words(1, 3), "sold out or not made in your size")
        self.assertEqual(selection.gone_words(1, 0, example=True), "sold out in the example size")


class SoldOutCase(AppCase):
    def setUp(self):
        super().setUp()
        db.set_setting("sizes_confirmed", True)         # "These are my sizes" (the example's are told apart below)

    def unchecked(self, sid: str, keep: str, n: int, store: str = "cos") -> None:
        """`n` of the piece's other products become products of a store that gave no sizes (as every COS product)."""
        ids = [c.id for c in selection.build().get(sid).cands if c.id != keep][:n]
        self.assertEqual(len(ids), n)
        catalog.update(lambda cat: [c.update(sizes_all=[], sizes_in_stock=[], store=store)
                                    for c in cat["candidates"] if c.get("slot_id") == sid and c.get("id") in ids])

    def sell_out(self, layer="outer", size="M", leave: int | None = None):
        """An outfit, and a piece of it whose product he chose by hand and whose size sold out afterwards. With
        `leave`, only that many of the piece's other products stay in stock in his size."""
        w = selection.build()
        outfit = next(o for o in outfits.all_outfits(w) if any(p.layer == layer for p in o.pieces))
        view = next(p for p in outfit.pieces if p.layer == layer).view
        sid, cand = view.slot["id"], view.chosen.id
        self.client.post(f"/slot/{sid}/pick", data={"candidate": cand})
        size = size or view.chosen.size.label
        self.assertEqual(view.chosen.size.label, size)
        others = [c for c in view.cands if c.id != cand and c.available]
        # Each store labels his size its own way (M at Weekday, 48 at COS): that label leaves the sizes in stock.
        emptied = {cand: size, **{c.id: c.size.label for c in (others[leave:] if leave is not None else [])}}
        catalog.update(lambda cat: [c.update(sizes_in_stock=[s for s in c.get("sizes_in_stock") or [] if s != emptied[c["id"]]])
                                    for c in cat["candidates"] if c.get("slot_id") == sid and c.get("id") in emptied])
        view = selection.build().get(sid)
        self.assertTrue(view.sold_out)
        return outfit, view

    def page(self, url: str) -> str:
        r = self.client.get(url)
        self.assertEqual(r.status_code, 200, url)
        return r.data.decode()

    def blocks(self, page: str) -> list[str]:
        """Every sold-out block on a page, as markup."""
        return re.findall(r'<div class="soldout">(.*?)</div>', page, re.S)

    def swap_form(self, block: str) -> dict:
        form = re.search(r'<form class="no-print" method="post" action="(/slot/[^"?]+/pick[^"]*)">(.*?)</form>', block, re.S)
        self.assertIsNotNone(form, f"no swap offered: {as_read(block)}")
        return {"action": form.group(1).replace("&amp;", "&"), "button": as_read(re.search(r"<button[^>]*>(.*?)</button>", form.group(2), re.S).group(1)),
                **dict(re.findall(r'name="(\w+)" value="([^"]*)"', form.group(2)))}

    def press(self, form: dict):
        sent = {k: v for k, v in form.items() if k not in ("action", "button", "csrf_token")}
        r = self.client.post(form["action"], data=sent)
        self.assertEqual(r.status_code, 302)
        return r.headers["Location"]

    def undo(self, page: str) -> str:
        form = re.search(r'<form method="post" action="(/slot/[^"]+/restore)">(.*?)</form>', page, re.S)
        self.assertIsNotNone(form, "no Undo")
        r = self.client.post(form.group(1), data=dict(re.findall(r'name="(\w+)" value="([^"]*)"', form.group(2))))
        self.assertEqual(r.status_code, 302)
        return r.headers["Location"]

    def difference(self, view) -> str:
        cents = round(view.swap.price * 100) - round(view.chosen.price * 100)
        return "same price" if cents == 0 else f"{'+' if cents > 0 else '−'}{eur(abs(cents) / 100)}"


class SaidWithTheSwap(SoldOutCase):
    def test_the_piece_itself_knows_it_and_counts_nothing(self):
        before = selection.build()
        outfit, view = self.sell_out()
        w = selection.build()
        self.assertEqual(view.sold_words, "Sold out in M")
        self.assertEqual((view.cost, view.price), (0.0, view.chosen.price * view.qty))
        self.assertAlmostEqual(w.total, before.total - before.get(view.slot["id"]).cost, places=2)
        self.assertEqual((w.n_buy, w.n_sold_out), (before.n_buy - view.qty, view.qty))
        self.assertEqual(w.unfilled_words, ["1 piece sold out in your size"])
        # What is offered is in stock in his size, and is not the product that sold out.
        self.assertIsNotNone(view.swap)
        self.assertTrue(view.swap.available and view.swap.size.rank == sizes.IN_YOUR_SIZE)
        self.assertNotEqual(view.swap.id, view.chosen.id)
        # The outfit stays: the same pieces make it, with the same product on the piece.
        still = outfits.find_by_sig(w, outfit.sig)
        self.assertIsNotNone(still)
        self.assertEqual(next(p for p in still.pieces if p.view.slot["id"] == view.slot["id"]).view.chosen.id, view.chosen.id)
        # The budget bar says why one piece fewer is to buy.
        self.assertIn("1 piece sold out in your size", as_read(self.page("/")))

    def test_every_place_says_sold_out_in_m_and_offers_the_same_swap(self):
        outfit, view = self.sell_out()
        sid = view.slot["id"]
        store = programmes.label(view.chosen.data["store"])
        wanted = f"Swap for {english.name(view.swap.data['name']) or view.swap.data['name']}, {self.difference(view)}"
        places = {"outfit": f"/outfits?at={outfit.sig}", "wardrobe": "/", "list": "/list",
                  "buy": f"/outfits/buy?at={outfit.sig}"}
        for back, url in places.items():
            with self.subTest(place=back):
                page = self.page(url)
                mine = [b for b in self.blocks(page) if f"/slot/{sid}/pick" in b]
                self.assertTrue(mine, f"{url} does not say the piece is sold out")
                said = as_read(mine[0])
                self.assertTrue(said.startswith("Sold out in M at "), said)
                self.assertTrue(said.startswith(f"Sold out in M at {store}"), said)
                form = self.swap_form(mine[0])
                button = re.search(r"<button[^>]*>(.*?)</button>", mine[0], re.S).group(1)
                self.assertEqual(as_read(re.sub(r'<span class="sr">.*?</span>', "", button)), wanted)
                self.assertEqual((form["candidate"], form["back"], form["was"], form["was_locked"]),
                                 (view.swap.id, back, view.chosen.id, "1"))
                self.assertIn(f"{eur(view.swap.price)} at ", said)
                self.assertIn(f"in stock in {view.swap.size.label}. It takes this piece's place in all your outfits.", said)
        # The pop-up of the piece says it too, before the quick changes.
        popup = self.client.get("/outfits/piece", query_string={"at": outfit.sig, "slot": sid}, headers=HX).data.decode()
        block = self.blocks(popup)
        self.assertEqual(len(block), 1)
        self.assertTrue(as_read(block[0]).startswith("Sold out in M at "))
        self.assertEqual(self.swap_form(block[0])["candidate"], view.swap.id)
        self.assertLess(popup.index('class="soldout"'), popup.index("Swap it for"))

    def test_the_difference_is_the_true_one_more_less_or_the_same(self):
        outfit, view = self.sell_out()
        sid, chosen, offered = view.slot["id"], view.chosen, view.swap
        for price, words, read_out in ((chosen.price + 10, f"+{eur(10)}", f"{eur(10)} more"),
                                       (chosen.price - 5, f"−{eur(5)}", f"{eur(5)} less"),
                                       (chosen.price, "same price", "same price")):
            with self.subTest(price=price):
                catalog.update(lambda cat: [c.update(price=price) for c in cat["candidates"]
                                            if c.get("slot_id") == sid and c.get("id") == offered.id])
                now = selection.build().get(sid)
                self.assertEqual(now.swap.id, offered.id, "the nearest in price is still the one offered")
                block = next(b for b in self.blocks(self.page("/")) if f"/slot/{sid}/pick" in b)
                button = re.search(r"<button[^>]*>(.*?)</button>", block, re.S).group(1)
                seen = as_read(re.sub(r'<span class="sr">.*?</span>', "", button))
                heard = as_read(re.sub(r'<span aria-hidden="true">.*?</span>', "", button))
                called = english.name(offered.data["name"]) or offered.data["name"]
                self.assertEqual(seen, f"Swap for {called}, {words}")
                self.assertEqual(heard, f"Swap for {called}, {read_out}")

    def test_one_tap_chooses_it_and_undo_comes_back_to_the_same_page(self):
        for back in ("outfit", "wardrobe", "list", "buy"):
            with self.subTest(place=back):
                self.setUp()
                outfit, view = self.sell_out()
                sid, name = view.slot["id"], view.slot["name"]
                url = {"outfit": f"/outfits?at={outfit.sig}", "wardrobe": "/", "list": "/list",
                       "buy": f"/outfits/buy?at={outfit.sig}"}[back]
                home = url.split("?")[0]
                block = next(b for b in self.blocks(self.page(url)) if f"/slot/{sid}/pick" in b)
                where = self.press(self.swap_form(block))
                self.assertTrue(where.startswith(home + "?"), where)
                now = selection.build().get(sid)
                self.assertEqual((now.chosen.id, now.state, now.sold_out), (view.swap.id, "locked", False))
                page = self.page(where)
                self.assertEqual(status_line(page), f"{name} changed in all your outfits: {view.swap.data['name']}, "
                                 f"{eur(view.swap.price)} (was {eur(view.chosen.price)}). It stays when you change the "
                                 "price level. Undo")
                self.assertFalse([b for b in self.blocks(page) if f"/slot/{sid}/pick" in b], "still said to be sold out")

                again = self.undo(page)
                self.assertTrue(again == home or again.startswith(home + "?"), again)
                after = selection.build().get(sid)
                self.assertEqual((after.chosen.id, after.state, after.sold_out), (view.chosen.id, "locked", True))
                page = self.page(again)
                self.assertTrue(any(f"{name}: back to {view.chosen.data['name']}" in said for said in flashes(page)), flashes(page))
                self.assertTrue([b for b in self.blocks(page) if f"/slot/{sid}/pick" in b], "the swap is offered again")

    def test_nothing_else_in_your_size_is_said_with_the_way_to_add_one(self):
        outfit, view = self.sell_out(leave=0)
        sid = view.slot["id"]
        self.assertIsNone(view.swap)
        for url in (f"/outfits?at={outfit.sig}", "/", "/list", f"/outfits/buy?at={outfit.sig}"):
            with self.subTest(place=url):
                block = next((b for b in self.blocks(self.page(url)) if f"/slot/{sid}" in b), None)
                self.assertIsNotNone(block, f"{url} does not say the piece is sold out")
                self.assertEqual(as_read(block).split(" at ", 1)[0], "Sold out in M")
                self.assertIn("Nothing else for this piece is in stock in your size. Add one you found yourself", as_read(block))
                self.assertNotIn("<form", block)
                link = re.search(r'<a class="no-print" href="([^"]+)">Add one you found yourself</a>', block)
                self.assertTrue(link.group(1).startswith(f"/slot/{sid}") and link.group(1).endswith("#add"), link.group(1))
                self.assertIn('id="add"', self.page(link.group(1).split("#")[0].replace("&amp;", "&")))

    def test_products_whose_sizes_were_not_checked_are_not_called_nothing(self):
        # Every other product of the piece is out of his size, except two whose store gave no sizes: they may well
        # be in stock (the automatic pick would take one). "Nothing else is in stock" would be untrue.
        outfit, view = self.sell_out(leave=0)
        sid = view.slot["id"]
        self.unchecked(sid, view.chosen.id, 2)
        view = selection.build().get(sid)
        self.assertIsNone(view.swap, "one whose sizes were not checked is never offered as in stock in his size")
        self.assertEqual(view.n_not_checked, 2)
        wanted = "Nothing else is known to be in stock in your size. 2 more at COS: sizes not checked. See all options"
        popup = self.client.get("/outfits/piece", query_string={"at": outfit.sig, "slot": sid}, headers=HX).data.decode()
        pages = {url: self.page(url) for url in (f"/outfits?at={outfit.sig}", "/", "/list", f"/outfits/buy?at={outfit.sig}")}
        for url, page in {**pages, "the pop-up": popup}.items():
            with self.subTest(place=url):
                block = next((b for b in self.blocks(page) if f"/slot/{sid}" in b), None)
                self.assertIsNotNone(block, f"{url} does not say the piece is sold out")
                said = as_read(re.sub(r'<span class="sr">.*?</span>', "", block))
                self.assertIn(wanted, said)
                self.assertNotIn("Nothing else for this piece", said)
                self.assertNotIn("Add one you found yourself", said)
                link = re.search(r'<a class="no-print" href="([^"#]+)">See all options', block)
                self.assertTrue(link and link.group(1).startswith(f"/slot/{sid}"), block)
                listed = self.page(link.group(1).replace("&amp;", "&"))
                self.assertEqual(listed.count("Sizes not checked at COS"), 2, "the options it points to are on that page")
        text = export.to_markdown(export.build(selection.build()))
        self.assertIn("  - Nothing else is known to be in stock in your size. 2 more at COS: sizes not checked. "
                      "See them on the piece's page.", text)
        self.assertNotIn("Nothing else for this piece", text)
        # The piece's own page says it too, and there the options are right below.
        own = next(b for b in self.blocks(self.page(f"/slot/{sid}")))
        self.assertIn("Nothing else is known to be in stock in your size. 2 more at COS: sizes not checked. "
                      "They are listed below.", as_read(own))

    def test_one_in_your_size_without_a_price_is_not_called_nothing_either(self):
        outfit, view = self.sell_out(leave=1)
        sid = view.slot["id"]
        catalog.update(lambda cat: [c.update(price=0) for c in cat["candidates"]
                                    if c.get("slot_id") == sid and c.get("id") == view.swap.id])
        now = selection.build().get(sid)
        self.assertIsNone(now.swap)
        self.assertEqual(now.no_swap, ("Nothing else in stock in your size has a price yet",
                                       "1 more in stock in your size: no price yet", True))
        self.assertIn("See all options", as_read(next(b for b in self.blocks(self.page("/")) if f"/slot/{sid}" in b)))

    def test_on_paper_the_product_offered_is_named_without_the_button(self):
        # The printed Shopping list hides the button (no-print). The sentence under it must name the product itself.
        outfit, view = self.sell_out()
        block = next(b for b in self.blocks(self.page("/list")) if f"/slot/{view.slot['id']}/pick" in b)
        paper = re.sub(r'<(form|p|a) class="[^"]*no-print[^"]*".*?</\1>', "", block, flags=re.S)
        self.assertNotIn("<button", paper)
        called = english.name(view.swap.data["name"]) or view.swap.data["name"]
        self.assertEqual(as_read(paper), f"Sold out in M at {programmes.label(view.chosen.data['store'])} "
                         f"In stock in {view.swap.size.label}: {called}, {eur(view.swap.price)} at "
                         f"{programmes.label(view.swap.data['store'])}.")
        on_paper = re.search(r'<p class="soldout-more print-only">', block)
        self.assertIsNotNone(on_paper)
        css = (__import__("pathlib").Path(selection.__file__).parent / "static" / "app.css").read_text()
        self.assertRegex(css, r"@media screen \{ \.print-only \{ display: none !important; \} \}")

    def test_the_pieces_own_page_offers_the_same_swap_and_stays_itself(self):
        outfit, view = self.sell_out()
        sid = view.slot["id"]
        page = self.page(f"/slot/{sid}")
        block = self.blocks(page)
        self.assertEqual(len(block), 1)
        self.assertTrue(as_read(block[0]).startswith("Sold out in M at "))
        form = self.swap_form(block[0])
        self.assertEqual((form["candidate"], form["back"]), (view.swap.id, "slot"))
        where = self.press(form)
        self.assertEqual(where.split("?")[0], f"/slot/{sid}")
        now = selection.build().get(sid)
        self.assertEqual((now.chosen.id, now.sold_out), (view.swap.id, False))
        self.assertEqual(self.blocks(self.page(f"/slot/{sid}")), [])
        # It says what changed, with Undo, like every other page that offers the swap.
        name = view.slot["name"]
        page = self.page(where)
        self.assertEqual(status_line(page), f"{name} changed in all your outfits: {view.swap.data['name']}, "
                         f"{eur(view.swap.price)} (was {eur(view.chosen.price)}). It stays when you change the "
                         "price level. Undo")
        self.assertNotIn("changed in all your outfits", self.page(f"/slot/{sid}"), "said once, not at every later visit")
        again = self.undo(page)
        self.assertEqual(again, f"/slot/{sid}", "Undo comes back to the piece's own page")
        after = selection.build().get(sid)
        self.assertEqual((after.chosen.id, after.state, after.sold_out), (view.chosen.id, "locked", True))
        page = self.page(again)
        self.assertTrue(any(f"{name}: back to {view.chosen.data['name']}" in said for said in flashes(page)), flashes(page))
        self.assertEqual(len(self.blocks(page)), 1, "the swap is offered again")

    def test_the_pieces_own_page_opened_from_an_outfit_keeps_its_way_back_through_swap_and_undo(self):
        outfit, view = self.sell_out()
        sid = view.slot["id"]
        way = f"from=outfit&at={outfit.sig}"
        form = self.swap_form(self.blocks(self.page(f"/slot/{sid}?{way}"))[0])
        where = self.press(form)
        self.assertTrue(where.startswith(f"/slot/{sid}?"), where)
        page = self.page(where)
        self.assertIn("Back to the outfit", page)
        undo = re.search(r'<form method="post" action="(/slot/[^"]+/restore\?[^"]+)">(.*?)</form>', page, re.S)
        self.assertIsNotNone(undo, "no Undo that keeps the way back")
        r = self.client.post(undo.group(1).replace("&amp;", "&"), data=dict(re.findall(r'name="(\w+)" value="([^"]*)"', undo.group(2))))
        self.assertTrue(r.headers["Location"].startswith(f"/slot/{sid}?from=outfit"), r.headers["Location"])
        self.assertIn("Back to the outfit", self.page(r.headers["Location"]))
        self.assertTrue(selection.build().get(sid).sold_out)

    def test_the_popup_says_add_one_you_found_yourself_once(self):
        # A piece with one product only, sold out in his size: the lines about that end with the link, and the
        # pop-up's own last line ("No other option for this piece yet") would say it a second time.
        outfit, view = self.sell_out(leave=0)
        sid = view.slot["id"]

        def only_the_chosen(cat):
            cat["candidates"][:] = [c for c in cat["candidates"] if c.get("slot_id") != sid or c.get("id") == view.chosen.id]

        catalog.update(only_the_chosen)
        self.assertEqual(len(selection.build().get(sid).cands), 1)
        popup = self.client.get("/outfits/piece", query_string={"at": outfit.sig, "slot": sid}, headers=HX).data.decode()
        self.assertEqual(popup.count("Add one you found yourself"), 1, as_read(popup))
        self.assertNotIn("No other option for this piece yet", as_read(popup))
        self.assertIn("Nothing else for this piece is in stock in your size. Add one you found yourself", as_read(popup))

    def test_the_outfit_has_one_price_the_one_buy_this_outfit_shows(self):
        outfit, view = self.sell_out()
        sl = export.build(selection.build(), only=outfit.slots)
        page = self.page(f"/outfits?at={outfit.sig}")
        slide = page[page.index(f'id="outfit-{outfits.find_by_sig(selection.build(), outfit.sig).key}"'):]
        slide = slide[:slide.index("</article>")]
        self.assertEqual(as_read(re.search(r'<b class="board-cost"[^>]*>(.*?)</b>', slide).group(1)), eur(sl.total))
        self.assertEqual(as_read(re.search(r'<p class="about-less">(.*?)</p>', slide).group(1)),
                         f"Not counted: {view.slot['name']}, sold out in M")
        self.assertIn(f"<s>{eur(view.chosen.price)}</s><span class=\"sr\"> (not counted in the outfit's price)</span>"
                      .replace("\xa0", "&nbsp;"), slide.replace("\xa0", "&nbsp;"))
        # An outfit without the piece says nothing of the kind.
        other = next(o for o in outfits.all_outfits(selection.build()) if view.slot["id"] not in o.slots)
        page = self.page(f"/outfits?at={other.sig}")
        slide = page[page.index(f'id="outfit-{other.key}"'):]
        self.assertNotIn("about-less", slide[:slide.index("</article>")])

    def test_a_piece_bought_twice_says_the_difference_for_both_where_both_are_bought(self):
        # The white tee is in the plan twice. The Wardrobe and the Shopping list buy two, so the swap there changes
        # the total by twice the difference; an outfit wears one, and Buy this outfit buys one.
        tee = next(s for s in selection.build().slots if s.qty == 2)
        sid, cand, size = tee.slot["id"], tee.chosen.id, tee.chosen.size.label
        self.client.post(f"/slot/{sid}/pick", data={"candidate": cand})
        catalog.update(lambda cat: [c.update(sizes_in_stock=[s for s in c["sizes_in_stock"] if s != size])
                                    for c in cat["candidates"] if c.get("slot_id") == sid and c.get("id") == cand])
        w = selection.build()
        view = w.get(sid)
        self.assertTrue(view.sold_out and view.swap is not None)
        catalog.update(lambda cat: [c.update(price=view.chosen.price + 3) for c in cat["candidates"]
                                    if c.get("slot_id") == sid and c.get("id") == view.swap.id])
        w = selection.build()
        view = w.get(sid)
        self.assertEqual(view.swap_cents, 300)
        outfit = next(o for o in outfits.all_outfits(w) if sid in o.slots)
        for url, words in (("/", f"+{eur(6)} for 2"), ("/list", f"+{eur(6)} for 2"),
                           (f"/outfits?at={outfit.sig}", f"+{eur(3)}"), (f"/outfits/buy?at={outfit.sig}", f"+{eur(3)}")):
            with self.subTest(place=url):
                block = next(b for b in self.blocks(self.page(url)) if f"/slot/{sid}/pick" in b)
                button = re.search(r"<button[^>]*>(.*?)</button>", block, re.S).group(1)
                seen = as_read(re.sub(r'<span class="sr">.*?</span>', "", button))
                # (In English where every word of the store's name for it is known, as on every card.)
                called = english.name(view.swap.data["name"]) or view.swap.data["name"]
                self.assertEqual(seen, f"Swap for {called}, {words}")
                self.assertIn(f"{eur(view.swap.price)}{' each' if 'for 2' in words else ''} at ", as_read(block))
        self.assertIn(f"{export._eur(view.swap.price)} each ({export._eur(6)} more for 2)", export.to_markdown(export.build(w)))
        # And that is what the total does: the swap brings the piece back into it, at twice the new price.
        before = w.total
        self.client.post(f"/slot/{sid}/pick", data={"candidate": view.swap.id, "back": "wardrobe"})
        self.assertAlmostEqual(selection.build().total, before + 2 * view.swap.price, places=2)

    def test_a_product_not_made_in_your_size_says_that(self):
        outfit, view = self.sell_out()
        sid, cand = view.slot["id"], view.chosen.id
        catalog.update(lambda cat: [c.update(sizes_all=["XS", "S"], sizes_in_stock=["XS", "S"]) for c in cat["candidates"]
                                    if c.get("slot_id") == sid and c.get("id") == cand])
        now = selection.build().get(sid)
        self.assertTrue(now.sold_out)
        self.assertEqual(now.sold_words, "Not made in your size")
        page = self.page("/")
        block = next(b for b in self.blocks(page) if f"/slot/{sid}/pick" in b)
        self.assertTrue(as_read(block).startswith("Not made in your size at "), as_read(block))
        # ... and is not counted under the words "sold out": the bar, the list's heading and totals, Buy, the file.
        w = selection.build()
        self.assertEqual(w.unfilled_words, ["1 piece not made in your size"])
        self.assertIn("1 piece not made in your size", as_read(page))
        self.assertNotIn("sold out in your size", as_read(page).lower())
        page = self.page("/list")
        head = re.search(r'<section class="card store-list sold-list">(.*?)</header>', page, re.S)
        self.assertEqual(as_read(head.group(1)), "Not made in your size 1 piece not counted")
        self.assertIn("Not made in your size1 piece, not counted", as_read(page))
        self.assertNotIn("sold out in your size", as_read(page).lower())
        head = as_read(re.search(r'<p class="buy-head">(.*?)</p>', self.page(f"/outfits/buy?at={outfit.sig}"), re.S).group(1))
        self.assertIn("1 not made in your size, not counted", head)
        text = export.to_markdown(export.build(w))
        self.assertIn("(1 more is not made in your size and not counted)", text)
        self.assertIn("## Not made in your size (not counted above)", text)
        # With one of each, both are named.
        other = next(s for s in w.slots if s.slot["id"] != sid and s.state == "auto" and s.chosen
                     and s.chosen.size.label and s.qty == 1)
        oid, pick, label = other.slot["id"], other.chosen.id, other.chosen.size.label
        self.client.post(f"/slot/{oid}/pick", data={"candidate": pick})
        catalog.update(lambda cat: [c.update(sizes_in_stock=[s for s in c["sizes_in_stock"] if s != label])
                                    for c in cat["candidates"] if c.get("slot_id") == oid and c.get("id") == pick])
        self.assertEqual(selection.build().unfilled_words, ["2 pieces sold out or not made in your size"])
        head = re.search(r'<section class="card store-list sold-list">(.*?)</header>', self.page("/list"), re.S)
        self.assertEqual(as_read(head.group(1)), "Sold out or not made in your size 2 pieces not counted")

    def test_a_saved_outfit_says_it_while_the_piece_is_still_that_product(self):
        outfit, view = self.sell_out()
        sid = view.slot["id"]
        self.client.post("/outfits/save", data={"key": outfit.key, "want": "save"}, headers=HX)
        page = self.page("/outfits?occasion=saved")
        block = next(b for b in self.blocks(page) if f"/slot/{sid}/pick" in b)
        form = self.swap_form(block)
        self.assertEqual(form["back"], "saved")
        where = self.press(form)
        self.assertTrue(where.startswith("/outfits?occasion=saved"), where)
        page = self.page(where)
        self.assertIn(f"{view.slot['name']} changed in all your outfits", status_line(page))
        self.assertEqual(self.undo(page), "/outfits?occasion=saved")

    def test_a_piece_you_own_or_one_in_stock_says_nothing(self):
        outfit, view = self.sell_out()
        self.assertEqual(len(self.blocks(self.page("/"))), 1)
        self.post(f"/slot/{view.slot['id']}/own")
        self.assertFalse(selection.build().get(view.slot["id"]).sold_out)
        for url in ("/", "/list", f"/outfits?at={outfit.sig}"):
            self.assertEqual(self.blocks(self.page(url)), [], url)


class NeverCountedAsBuyable(SoldOutCase):
    def test_the_shopping_list_leaves_it_out_of_every_total_and_says_so(self):
        before = export.build(selection.build())
        outfit, view = self.sell_out()
        sl = export.build(selection.build())
        self.assertEqual([line.slot for line in sl.sold_out], [view.slot["name"]])
        self.assertEqual((sl.pieces, sl.pieces_sold_out), (before.pieces - view.qty, view.qty))
        self.assertAlmostEqual(sl.total, before.total - view.price, places=2)
        self.assertAlmostEqual(sum(g.subtotal for g in sl.groups), sl.total, places=2)
        self.assertNotIn(view.slot["name"], [line.slot for g in sl.groups for line in g.lines])

        page = self.page("/list")
        said = as_read(page)
        self.assertIn(f"Total for {sl.pieces} pieces you can buy{eur(sl.total)}", said)
        self.assertIn("Sold out in your size1 piece, not counted", said)
        head = re.search(r'<section class="card store-list sold-list">(.*?)</header>', page, re.S)
        self.assertEqual(as_read(head.group(1)), "Sold out in your size 1 piece not counted")
        self.assertIn(f"<s>{eur(view.price)}</s><span class=\"sr\"> (not counted in the total)</span>".replace("\xa0", "&nbsp;"),
                      page.replace("\xa0", "&nbsp;"))
        # The Wardrobe card strikes its price out the same way.
        card = self.page("/")
        card = card[card.index(f'id="card-{view.slot["id"]}"'):]
        self.assertIn('<span class="sr"> (not counted in the total)</span>', card[:card.index("</article>")])

    def test_the_files_say_it_too_and_the_spreadsheet_has_only_what_can_be_bought(self):
        outfit, view = self.sell_out()
        sl = export.build(selection.build())
        text = export.to_markdown(sl)
        self.assertIn(f"for {sl.pieces} pieces (1 more is sold out in your size and not counted)", text)
        self.assertIn("## Sold out in your size (not counted above)", text)
        self.assertIn(f"- **{view.slot['name']}** — {view.chosen.data['name']} — Sold out in M at ", text)
        self.assertIn(f"  - In stock in your size: {view.swap.data['name']}, ", text)
        rows = list(csv.DictReader(io.StringIO(export.to_csv(sl))))
        self.assertNotIn(view.slot["name"], [row["slot"] for row in rows])
        self.assertAlmostEqual(sum(float(row["total_eur"]) for row in rows), sl.total, places=2)
        self.assertEqual(self.client.get("/list.md").status_code, 200)
        # With nothing else in his size, the file says that instead of naming a product.
        self.setUp()
        outfit, view = self.sell_out(leave=0)
        self.assertIn("  - Nothing else for this piece is in stock in your size.", export.to_markdown(export.build(selection.build())))

    def test_buy_this_outfit_counts_only_what_can_be_bought_and_says_so(self):
        outfit, view = self.sell_out()
        sl = export.build(selection.build(), only=outfit.slots)
        self.assertAlmostEqual(sl.total, outfit.cost - view.chosen.price, places=2)
        page = self.page(f"/outfits/buy?at={outfit.sig}")
        self.assertIn(f'<p class="buy-head"><b>{eur(sl.total)}</b>', page.replace("&nbsp;", "\xa0"))
        head = as_read(re.search(r'<p class="buy-head">(.*?)</p>', page, re.S).group(1))
        self.assertIn(f"{sl.pieces} {'piece' if sl.pieces == 1 else 'pieces'} to buy · 1 sold out in your size, not counted", head)

    def test_an_outfit_with_nothing_else_to_buy_says_why(self):
        outfit, view = self.sell_out()
        for slot_id in outfit.slots:
            if slot_id != view.slot["id"]:
                db.update_slot(slot_id, owned=True)
        page = self.page(f"/outfits/buy?at={outfit.sig}")
        self.assertIn("Nothing to buy right now: the piece you do not own is sold out in your size.", as_read(page))
        self.assertNotIn("you own every piece", page)
        self.assertEqual(len(self.blocks(page)), 1, "the swap is still offered")


class OnTheExampleSizes(SoldOutCase):
    """Until he says the sizes are his, M is our example size, and every line about it says so, as the pop-up's own
    size line does."""

    def setUp(self):
        super().setUp()
        db.set_setting("sizes_confirmed", False)
        self.assertTrue(profile_mod.sizes_unconfirmed(profile_mod.load()))

    def test_the_size_is_said_to_be_the_example_size_everywhere(self):
        outfit, view = self.sell_out()
        sid = view.slot["id"]
        self.assertEqual(view.sold_words, "Sold out in M (example size)")
        popup = self.client.get("/outfits/piece", query_string={"at": outfit.sig, "slot": sid}, headers=HX).data.decode()
        pages = {url: self.page(url) for url in (f"/outfits?at={outfit.sig}", "/", "/list", f"/outfits/buy?at={outfit.sig}",
                                                 f"/slot/{sid}")}
        for url, page in {**pages, "the pop-up": popup}.items():
            with self.subTest(place=url):
                said = as_read(next(b for b in self.blocks(page) if f"/slot/{sid}/pick" in b))
                self.assertTrue(said.startswith("Sold out in M (example size) at "), said)
                self.assertIn(f"in stock in {view.swap.size.label} (example size). It takes", said)
                self.assertNotIn("your size", said)
        self.assertIn("1 piece sold out in the example size", as_read(pages["/"]))
        self.assertIn("Sold out in the example size1 piece, not counted", as_read(pages["/list"]))
        head = re.search(r'<section class="card store-list sold-list">(.*?)</header>', pages["/list"], re.S)
        self.assertEqual(as_read(head.group(1)), "Sold out in the example size 1 piece not counted")
        self.assertIn("1 sold out in the example size, not counted", as_read(pages[f"/outfits/buy?at={outfit.sig}"]))
        self.assertIn(f"Not counted: {view.slot['name']}, sold out in M (example size)", as_read(pages[f"/outfits?at={outfit.sig}"]))
        text = export.to_markdown(export.build(selection.build()))
        self.assertIn("## Sold out in the example size (not counted above)", text)
        self.assertIn("Sold out in M (example size) at ", text)
        self.assertIn("  - In stock in the example size: ", text)

    def test_nothing_else_is_said_of_the_example_size_too(self):
        outfit, view = self.sell_out(leave=0)
        said = as_read(next(b for b in self.blocks(self.page("/")) if f"/slot/{view.slot['id']}" in b))
        self.assertIn("Nothing else for this piece is in stock in the example size. Add one you found yourself", said)


class BestForBudget(SoldOutCase):
    def test_the_money_for_a_sold_out_piece_is_kept_for_its_swap(self):
        # At "best for budget" what is left pays for upgrades. A sold-out piece counts nothing in the total, but
        # its price is not spent on other pieces: the swap costs about as much, and would take those upgrades back.
        self.set_mode("budget")
        cheapest = selection.build().levels["cheapest"]
        profile_mod.save({**profile_mod.load(), "budget": round(cheapest * 1.15)})
        db.set_setting("sizes_confirmed", True)
        before = selection.build()
        self.assertGreater(before.total, cheapest, "there is money for upgrades")
        outfit, view = self.sell_out(size=None)
        w = selection.build()
        self.assertLessEqual(w.total + view.price, w.budget + 0.005, "the piece's price was spent on other pieces")
        picks = lambda wardrobe: {s.slot["id"]: s.chosen.id for s in wardrobe.slots
                                  if s.chosen and s.slot["id"] != view.slot["id"]}
        self.assertEqual(picks(w), picks(before), "the other pieces stay as they were")
        self.assertFalse(w.note)
