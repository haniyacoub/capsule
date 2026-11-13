"""The pop-up for one piece of an outfit (tap a dot on the model, or a piece in the list).

What it promises: first what the piece is (the store's own name for the product, its price, store and quality, the
fabric, your size and how it fits), then the quick changes to this one outfit, then the other products for the piece
with what each costs next to it, and the way to compare them all on the piece's own page, which leads back to the
same outfit. It is named by the product's name, and while the sizes are still our example's it says so.
"""
import html
import re

from wardrobe import catalog, db, outfits, selection

from .test_app import HX, AppCase


class PiecePopUp(AppCase):
    def outfit_with(self, layer="outer"):
        """The first outfit that has a piece of this layer, and that piece."""
        w = selection.build()
        outfit = next(o for o in outfits.all_outfits(w) if any(p.layer == layer for p in o.pieces))
        return outfit, next(p for p in outfit.pieces if p.layer == layer)

    def popup(self, outfit, slot_id, **extra) -> str:
        r = self.client.get("/outfits/piece", query_string={"at": outfit.sig, "slot": slot_id, **extra}, headers=HX)
        self.assertEqual(r.status_code, 200)
        return r.data.decode()

    @staticmethod
    def read(page: str) -> str:
        """What the customer reads: tags dropped, spaces collapsed."""
        return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", page)).split())

    def test_the_product_names_the_pop_up_and_the_quick_changes_come_before_the_other_products(self):
        outfit, coat = self.outfit_with("outer")
        page = self.popup(outfit, coat.view.slot["id"])
        name = coat.view.chosen.data["name"]
        # The dialog is named by the title the pop-up brings: the store's own name for the product, marked German.
        self.assertIn('aria-labelledby="piece-title"', self.client.get("/outfits").data.decode())
        self.assertNotIn('aria-label="This piece"', self.client.get("/outfits").data.decode())
        self.assertIn(f'<h2 id="piece-title" lang="de">{html.escape(name, quote=False)}</h2>', page)
        self.assertIn(f'<p class="piece-top piece-slot">{coat.view.slot["name"]}</p>', page, "the piece's name, small")
        said = self.read(page)
        # Its parts in this order: what it is, then this outfit, then the other products, then comparing them all.
        order = [said.index(words) for words in ("Open at", "In this outfit", "Swap it for", "Choosing one uses it",
                                                 "Compare all")]
        self.assertEqual(order, sorted(order), said)
        self.assertIn("Choosing one uses it in all your outfits and keeps it when you change the price level.", said)
        self.assertNotIn("locks it", said)
        self.assertRegex(said, r"In \d+ of the \d+ outfits your pieces make")
        # Each option's name is the store's own words too.
        options = re.findall(r"<b( lang=\"de\")?>[^<]+</b>", page.split("Swap it for", 1)[1])
        self.assertEqual(options, [' lang="de"'] * min(6, len(coat.view.cands) - 1))

    def test_the_small_label_follows_the_pieces_name(self):
        # A piece that took a new colour in one tap is renamed ("Black wool coat" becomes "Navy wool coat"): the
        # pop-up's small label is the piece's name as it is now.
        outfit, coat = self.outfit_with("outer")
        sid = coat.view.slot["id"]
        db.update_slot(sid, name="Navy wool coat")
        self.assertIn('<p class="piece-top piece-slot">Navy wool coat</p>', self.popup(outfit, sid))

    def test_quality_is_named_next_to_its_number(self):
        outfit, coat = self.outfit_with("outer")
        said = self.read(self.popup(outfit, coat.view.slot["id"]))
        self.assertIn(f"Quality {coat.view.chosen.score.total} out of 100", said)

    def test_each_option_says_what_it_costs_next_to_the_piece_in_the_outfit(self):
        outfit, coat = self.outfit_with("outer")
        current = coat.view.chosen.price
        others = [c for c in coat.view.cands if c.id != coat.view.chosen.id][:6]
        said = self.read(self.popup(outfit, coat.view.slot["id"]))
        self.assertGreaterEqual(len(others), 2)
        for option in others:
            cents = round((option.price - current) * 100)
            amount = f"{abs(cents) / 100:,.2f}".removesuffix(".00") + " €"
            if cents == 0:
                self.assertIn("same price", said)
            else:
                # Seen as "−69.05 €" or "+20 €", heard as "69.05 € less" or "20 € more".
                self.assertIn(("−" if cents < 0 else "+") + amount, said, option.data["name"])
                self.assertIn(f"{amount} {'less' if cents < 0 else 'more'}", said, option.data["name"])

    def test_the_first_fit_note_is_shown(self):
        outfit, coat = self.outfit_with("outer")
        notes = coat.view.chosen.check.notes
        self.assertTrue(notes[0].startswith("Oversized cut"), notes)     # the demo coat is cut large
        self.assertIn(notes[0], self.read(self.popup(outfit, coat.view.slot["id"])))

    def test_no_sizes_from_the_store_is_said_once(self):
        # A product whose store gave no sizes: the size line says to check, and the note saying the same is left out.
        outfit, top = self.outfit_with("top")
        sid, cand = top.view.slot["id"], top.view.chosen.id
        catalog.update(lambda cat: [c.update(sizes_all=[], sizes_in_stock=[]) for c in cat["candidates"]
                                    if c.get("slot_id") == sid and c.get("id") == cand])
        view = selection.build().get(sid)
        self.assertFalse(view.chosen.size.known)
        said = self.read(self.popup(outfit, sid))
        self.assertIn("Check that your size is in stock", said)
        self.assertNotIn("gave no sizes", said)

    def test_the_day_of_the_prices_and_stock_sits_with_the_size_line(self):
        # "In stock" holds as of the day the products were collected: that day is said right under the size line, on
        # the pop-up's first screen, in the words used everywhere else, and not again at the pop-up's end.
        outfit, coat = self.outfit_with("outer")
        when = selection.build().collected
        page = self.popup(outfit, coat.view.slot["id"])
        said = self.read(page)
        self.assertIn(f"Prices and stock as of {when}", said)
        self.assertEqual(said.count("as of"), 1, said)
        self.assertLess(said.index("Your size"), said.index("Prices and stock as of"))
        self.assertLess(said.index("Prices and stock as of"), said.index("Open at"))
        self.assertRegex(page, r'(?s)<p class="sizeline">.*?</p>\s*<p class="as-of">Prices and stock as of <span>'
                         + re.escape(html.escape(when)) + "</span></p>")
        foot = re.search(r'<p class="muted small sheet-foot">(.*?)</p>', page, re.S)
        self.assertIsNotNone(foot)
        self.assertNotIn("as of", foot.group(1))

    def test_example_sizes_are_said_until_they_are_confirmed(self):
        outfit, coat = self.outfit_with("outer")
        page = self.popup(outfit, coat.view.slot["id"])
        self.assertIn("Your size: M in stock (example size)", self.read(page))
        self.assertIn('<a href="/profile#sizes">Change<span class="sr"> your sizes</span></a>', page)
        self.client.post("/profile/sizes-ok")
        said = self.read(self.popup(outfit, coat.view.slot["id"]))
        self.assertIn("Your size: M in stock", said)
        self.assertNotIn("example size", said)

    def test_a_sold_out_size_stays_red_also_in_the_example_size(self):
        # A chosen coat whose size M sold out since: that is said in red (not the amber of a mere caution), and the
        # size is still said to be the example's.
        outfit, coat = self.outfit_with("outer")
        sid, cand = coat.view.slot["id"], coat.view.chosen.id
        self.client.post(f"/slot/{sid}/pick", data={"candidate": cand, "outfit": outfit.sig})
        catalog.update(lambda cat: [c.update(sizes_in_stock=[s for s in c.get("sizes_in_stock") or [] if s != "M"])
                                    for c in cat["candidates"] if c.get("slot_id") == sid and c.get("id") == cand])
        self.assertFalse(selection.build().get(sid).chosen.available)
        page = self.popup(outfit, sid)
        self.assertIn('<span class="no">Your size: M sold out (example&nbsp;size)</span>', page)
        self.post("/profile/sizes-ok")
        self.assertIn('<span class="no">Your size: M sold out</span>', self.popup(outfit, sid))

    def test_a_chosen_piece_says_locked_and_one_you_have_says_so(self):
        outfit, coat = self.outfit_with("outer")
        sid = coat.view.slot["id"]
        self.assertNotIn("Locked", self.read(self.popup(outfit, sid)))
        other = next(c for c in coat.view.cands if c.id != coat.view.chosen.id and c.price > 0)
        self.client.post(f"/slot/{sid}/pick", data={"candidate": other.id, "outfit": outfit.sig})
        self.assertIn("Locked: kept when you change the price level", self.read(self.popup(outfit, sid)))

        self.post(f"/slot/{sid}/own")
        page = self.popup(outfit, sid)
        self.assertIn(f'<h2 class="piece-top" id="piece-title">{coat.view.slot["name"]}</h2>', page, "named by the piece")
        said = self.read(page)
        self.assertIn("You have this", said)
        self.assertNotIn("Swap it for", said)
        self.assertNotIn("stock as of", said)      # no product, so no day for its price and stock

    def test_compare_all_options_leads_to_the_piece_page_and_back_to_the_same_outfit(self):
        outfit, coat = self.outfit_with("outer")
        sid = coat.view.slot["id"]
        page = self.popup(outfit, sid, occasion="office")
        link = re.search(r'<a class="link" href="([^"]+)">Compare all (\d+) options</a>', page)
        self.assertIsNotNone(link, "no 'Compare all N options'")
        self.assertEqual(int(link.group(2)), len(coat.view.cands))
        address = html.unescape(link.group(1))
        self.assertTrue(address.startswith(f"/slot/{sid}?"), address)
        self.assertIn("from=outfit", address)
        self.assertIn("occasion=office", address)

        piece_page = self.client.get(address).data.decode()
        back = re.search(r'<p class="crumb"><a href="([^"]+)">.*?</svg> Back to the outfit</a></p>', piece_page, re.S)
        self.assertIsNotNone(back, "the piece page's way back does not say 'Back to the outfit'")
        self.assertIn('<a href="/outfits" class="on" aria-current="page">Outfits</a>', piece_page)
        outfits_page = self.client.get(html.unescape(back.group(1))).data.decode()
        self.assertIn(f'id="outfit-{outfit.key}"', outfits_page)
        self.assertLess(outfits_page.index(f'id="outfit-{outfit.key}"'), outfits_page.index("2 / "), "not the first outfit")
        self.assertIn("occasion=office", back.group(1))

    def test_the_piece_page_on_its_own_still_belongs_to_the_wardrobe(self):
        _, coat = self.outfit_with("outer")
        sid = coat.view.slot["id"]
        for query in ({}, {"at": "a~b"}, {"from": "outfit"}, {"from": "elsewhere", "at": "a~b"}):
            page = self.client.get(f"/slot/{sid}", query_string=query).data.decode()
            self.assertIn(f'<a href="/#card-{sid}">', page, query)
            self.assertNotIn("Back to the outfit", page, query)
            self.assertIn('<a href="/" class="on" aria-current="page">Wardrobe</a>', page, query)
        # An occasion that is not one is left out of the way back.
        page = self.client.get(f"/slot/{sid}", query_string={"from": "outfit", "at": "a~b", "occasion": "<x>"}).data.decode()
        self.assertIn('href="/outfits?at=a~b"', page)
