"""The pop-up for one piece of an outfit (tap a dot on the model, or a piece in the list).

What it promises: first what the piece is, as every card says it (the piece and its price, the store and the quality,
the product's name in English with the store's own under it, the fabric and the fit, then your size), then the quick
changes to this one outfit, then the other products for the piece with what each costs next to it, and the way to
compare them all on the piece's own page, which leads back to the same outfit. It is named by the piece's name, and
while the sizes are still our example's it says so.
"""
import html
import json
import re

from wardrobe import catalog, db, english, export, outfits, paths, programmes, selection
from wardrobe.app import eur

from .test_app import HX, AppCase


class PiecePopUp(AppCase):
    OLD_START = True        # a big wardrobe: the start every account had until 19 Nov 2026 (having.the_old_start)
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

    def test_the_piece_names_the_pop_up_and_the_quick_changes_come_before_the_other_products(self):
        outfit, coat = self.outfit_with("outer")
        page = self.popup(outfit, coat.view.slot["id"])
        chosen = coat.view.chosen
        name, said_in_english = chosen.data["name"], english.name(chosen.data["name"])
        # The dialog is named by the title the pop-up brings: the piece's name, with its price beside it in the top row.
        self.assertIn('aria-labelledby="piece-title"', self.client.get("/outfits").data.decode())
        self.assertNotIn('aria-label="This piece"', self.client.get("/outfits").data.decode())
        self.assertRegex(page, r'<div class="piece-top">\s*<h2 id="piece-title">' + re.escape(coat.view.slot["name"])
                         + r'</h2>\s*<b class="sheet-price">' + re.escape(str(html.escape(eur(chosen.price)))) + "</b>")
        # The store's name for the product in English, then the store's own words in small print, marked German.
        self.assertTrue(said_in_english, f"the demo coat {name!r} has a name the word list knows")
        self.assertRegex(page, r'<p class="en" lang="en">' + re.escape(html.escape(said_in_english, quote=False))
                         + r'</p>\s*<p class="orig" lang="de">' + re.escape(html.escape(name, quote=False)) + "</p>")
        said = self.read(page)
        # Its parts in this order: what it is, then this outfit, then the other products, then comparing them all.
        order = [said.index(words) for words in ("Open at", "In this outfit", "Swap it for", "Choosing one uses it",
                                                 "Compare all")]
        self.assertEqual(order, sorted(order), said)
        self.assertIn("Choosing one uses it in all your outfits and keeps it when you change the price level or the "
                      "minimum quality.", said)
        self.assertNotIn("locks it", said)
        # Whether it is in his wardrobe (none of his outfits wears it yet), and how many outfits it could be worn in.
        self.assertRegex(said, r"Not in your wardrobe yet: it joins with the first outfit you add that wears it\. "
                               r"It could be worn in \d+ of the \d+ outfits your plan makes\.")
        # Each option's name is in one language: English where every word is known, else the store's own words.
        others = [c for c in coat.view.cands if c.id != chosen.id][:6]
        rest = page.split("Swap it for", 1)[1]
        options = re.findall(r'<b lang="(en|de)">([^<]+)</b>', rest)
        self.assertEqual(options, [("en", html.escape(english.name(c.data["name"]), quote=False))
                                   if english.name(c.data["name"]) else ("de", html.escape(c.data["name"], quote=False))
                                   for c in others])
        # The store and the quality come first, then the name; the store's own words beside an English name are on
        # that product's own card, not in this list.
        rows = re.findall(r'<span class="swap-text">(.*?)<span class="swap-price">', rest, re.S)
        self.assertEqual(len(rows), len(others))
        for row, c in zip(rows, others):
            at = [row.find('<span class="by">'), row.find("<b lang=")]
            self.assertTrue(-1 < at[0] < at[1], f"the store and quality come before the name: {row}")
            if english.name(c.data["name"]):
                self.assertNotIn(html.escape(c.data["name"], quote=False), row, "one language per name in the list")

    def test_the_title_follows_the_pieces_name(self):
        # A piece that took a new colour in one tap is renamed ("Black wool coat" becomes "Navy wool coat"): the
        # pop-up's title is the piece's name as it is now.
        outfit, coat = self.outfit_with("outer")
        sid = coat.view.slot["id"]
        db.update_slot(sid, name="Navy wool coat")
        self.assertIn('<h2 id="piece-title">Navy wool coat</h2>', self.popup(outfit, sid))

    def test_quality_is_named_next_to_its_number_beside_the_store(self):
        # Seen as "WEEKDAY · Quality 73/100", heard as "Weekday, Quality 73 out of 100".
        outfit, coat = self.outfit_with("outer")
        score, store = coat.view.chosen.score, programmes.label(coat.view.chosen.data["store"])
        page = self.popup(outfit, coat.view.slot["id"])
        # The dot is the quality's, so that it never hangs at the end of the store's line (app.css, .by-in).
        self.assertIn(f'<p class="by"><span class="by-in"><span class="store">{store}</span> <span class="quality"><span '
                      f'class="sep" aria-hidden="true">·</span>Quality <span class="pill {score.band}">{score.total}'
                      f'<span class="of" aria-hidden="true">/100</span></span><span class="sr"> out of 100</span></span>'
                      f'</span></p>', page)
        heard = self.read(re.sub(r'<span[^>]*aria-hidden="true">[^<]*</span>', "", page))
        self.assertIn(f"{store} Quality {score.total} out of 100", heard)

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

    def test_the_fit_is_shown_as_a_caution(self):
        outfit, coat = self.outfit_with("outer")
        check = coat.view.chosen.check
        self.assertEqual(check.fit, "oversized, runs large. Size down for a regular fit.")   # the demo coat is cut large
        page = self.popup(outfit, coat.view.slot["id"])
        self.assertRegex(page, r'<p class="fit caution"><svg[^>]*>.*?</svg> Fit: oversized, runs large\. Size down for a '
                               r'regular fit\.</p>')
        self.assertEqual(self.read(page).count("runs large"), 1, "said once")

    def test_no_sizes_from_the_store_is_said_once(self):
        # A piece whose options all come without sizes (as COS's did): the size line says, with the store's name, that
        # the sizes were not checked and where to look, and the note saying the same is left out.
        outfit, top = self.outfit_with("top")
        sid = top.view.slot["id"]
        catalog.update(lambda cat: [c.update(sizes_all=[], sizes_in_stock=[]) for c in cat["candidates"]
                                    if c.get("slot_id") == sid])
        view = selection.build().get(sid)
        self.assertFalse(view.chosen.size.known)
        store = programmes.label(view.chosen.data["store"])
        page = self.popup(outfit, sid)
        said = self.read(page)
        # A size to check: amber (.unk), as plain words with the small flag before them.
        self.assertRegex(page, rf'<span class="unk"><svg class="ic"[^>]*>.*?</svg> Sizes not checked at {store}: look '
                               r'on its page before you buy</span>')
        self.assertEqual(said.count("Sizes not checked at"), 1, said)
        self.assertNotIn("gave no sizes", said)
        self.assertNotIn("Your size", said, "nothing is said to be in your size")
        self.assertNotIn('#sizes">Change', page, "no size is said, so there is no example size to change here")

    def test_each_product_says_its_own_day_and_a_page_of_several_the_oldest(self):
        # The stores are collected on different days (COS on 11 Nov, others later), and a price holds as of its own
        # day: the pop-up says its product's, a page of several products the oldest of theirs, not the list's newest.
        outfit, coat = self.outfit_with("outer")
        with paths.CATALOG_PATH.open(encoding="utf-8") as f:
            data = json.load(f)
        for cand in data["candidates"]:
            if cand["id"] == coat.view.chosen.id:
                cand["collected_at"] = "2026-11-01T09:30:00+01:00"
        data["collected_at"] = "2026-11-22T22:59:00+01:00"
        paths.CATALOG_PATH.write_text(json.dumps(data), encoding="utf-8")
        catalog._cache = None
        w = selection.build()
        coat_said = self.read(self.popup(outfit, coat.view.slot["id"]))
        self.assertIn("Prices and stock as of 1 Nov 2026, 09:30", coat_said)
        other = next(p for p in outfit.pieces if p.view.chosen and p.view.chosen.id != coat.view.chosen.id)
        other_said = self.read(self.popup(outfit, other.view.slot["id"]))
        self.assertIn(f"Prices and stock as of {other.view.chosen.collected}", other_said)
        self.assertNotIn("1 Nov 2026", other_said)
        self.assertEqual(w.as_of, "1 Nov 2026, 09:30", "the oldest of the products shown")
        self.assertEqual(export.build(w.mine).collected, "1 Nov 2026, 09:30",
                         "an empty shopping list says the day its wardrobe's pieces say")
        self.assertIn(" · prices of 1 Nov · ", self.read(self.client.get("/outfits").data.decode()))
        self.post("/outfits/save", key=outfit.key)            # a yes: the coat's outfit joins his wardrobe
        bought = export.build(selection.build().mine)
        on_list = [line.cand.id for group in bought.groups for line in group.lines]
        self.assertIn(coat.view.chosen.id, on_list)
        self.assertEqual(bought.collected, "1 Nov 2026, 09:30", "the shopping list: the oldest of its products")
        self.assertIn("Prices and stock as of 1 Nov 2026, 09:30", self.read(self.client.get("/list").data.decode()))

    def test_a_day_without_its_offset_is_compared_with_the_others(self):
        days = [{"collected_at": "2026-11-22T22:59:00+01:00"}, {"collected_at": "2026-11-11T17:00:00"}, {}]
        self.assertEqual(catalog.oldest_label(days, "never"), "11 Nov 2026, 17:00")
        self.assertEqual(catalog.oldest_label([{}, {"collected_at": "yesterday"}], "never"), "never")

    def test_the_day_of_the_prices_and_stock_sits_with_the_size_line(self):
        # "In stock" holds as of the day the products were collected: that day is said right under the size line, on
        # the pop-up's first screen, in the words used everywhere else, and not again at the pop-up's end.
        outfit, coat = self.outfit_with("outer")
        when = coat.view.chosen.collected        # the day its own product was collected
        self.assertTrue(when)
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
        # Red (.no), as plain words with the small flag before them.
        self.assertRegex(page, r'<span class="no"><svg class="ic"[^>]*>.*?</svg> Your size: M sold out '
                               r'\(example&nbsp;size\)</span>')
        self.post("/profile/sizes-ok")
        self.assertRegex(self.popup(outfit, sid), r'<span class="no"><svg class="ic"[^>]*>.*?</svg> Your size: M sold out</span>')

    def test_a_chosen_piece_says_locked_and_one_you_have_says_so(self):
        outfit, coat = self.outfit_with("outer")
        sid = coat.view.slot["id"]
        self.assertNotIn("Locked", self.read(self.popup(outfit, sid)))
        other = next(c for c in coat.view.cands if c.id != coat.view.chosen.id and c.price > 0)
        self.client.post(f"/slot/{sid}/pick", data={"candidate": other.id, "outfit": outfit.sig})
        # Said in the words of the piece's own page: kept when the price level or the minimum quality changes.
        locked = "Locked: kept when you change the price level or the minimum quality"
        self.assertIn(locked, self.read(self.popup(outfit, sid)))
        self.assertIn(locked + ".", self.read(self.client.get(f"/slot/{sid}").data.decode()))

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

    def test_without_javascript_the_piece_page_keeps_its_way_back_to_the_outfit(self):
        """Without JavaScript every button on a piece page posts a plain form and the page comes back. Opened from an
        outfit, it comes back with its way back to that outfit and the Outfits tab lit: after choosing, locking,
        unlocking, marking it owned, adding a product by its link, typing in details or removing one, and sorting."""
        outfit, coat = self.outfit_with("outer")
        sid = coat.view.slot["id"]
        link = re.search(r'<a class="link" href="([^"]+)">Compare all', self.popup(outfit, sid, occasion="office"))
        assert link is not None
        opened = html.unescape(link.group(1))
        crumb = r'<p class="crumb"><a href="([^"]+)">.*?</svg> Back to the outfit</a></p>'
        first = re.search(crumb, self.client.get(opened).data.decode(), re.S)
        assert first is not None
        expected_back = html.unescape(first.group(1))       # the outfit the pop-up was opened from (the test above)
        self.assertIn(f"at={outfit.sig}", expected_back)
        self.assertIn("occasion=office", expected_back)

        def way_back(address: str) -> str:
            """The piece page at this address, after checking it still leads back to the same outfit."""
            self.assertTrue(address.startswith(f"/slot/{sid}?"), address)
            page = self.client.get(address).data.decode()
            back = re.search(crumb, page, re.S)
            self.assertIsNotNone(back, f"{address} lost its way back to the outfit")
            assert back is not None
            self.assertEqual(html.unescape(back.group(1)), expected_back, address)
            self.assertIn('<a href="/outfits" class="on" aria-current="page">Outfits</a>', page, address)
            return page

        def action(page: str, button: str) -> str:
            """Where the form whose button says `button` posts to."""
            found = re.search(rf'<form[^>]*? action="([^"]+)"[^>]*>(?:(?!</form>).)*?{button}', page, re.S)
            self.assertIsNotNone(found, f"no form with a button saying {button!r}")
            assert found is not None
            return html.unescape(found.group(1))

        def plain_post(page: str, button: str, **data) -> str:
            """Press the button with JavaScript off (no HX-Request header): the page it comes back to."""
            response = self.client.post(action(page, button), data=data)
            self.assertEqual(response.status_code, 302, button)
            return way_back(response.headers["Location"])

        page = way_back(opened)
        assert coat.view.chosen is not None
        other = next(c for c in coat.view.cands if c.id != coat.view.chosen.id and c.price > 0)
        page = plain_post(page, rf'<input type="hidden" name="candidate" value="{other.id}">\s*<button[^>]*>Choose this',
                          candidate=other.id)
        self.assertEqual(self.view(sid).chosen.id, other.id)
        page = plain_post(page, "Unlock")
        self.assertEqual(self.view(sid).state, "auto")
        page = plain_post(page, "Lock this choice")
        self.assertEqual(self.view(sid).state, "locked")
        page = plain_post(page, "I already own this")
        page = plain_post(page, "I don’t own this after all")
        self.assertEqual(self.view(sid).state, "locked")
        page = plain_post(page, ">Add<", urls="")                                    # nothing pasted: said, and back
        page = plain_post(page, ">Add<", urls="https://www.cos.com/de-de/x/product/another-coat-1234567890")
        self.assertIn("added by you", page)
        added = re.search(r'name="candidate" value="([^"]+)">\s*<button class="link">Remove', page)
        assert added is not None
        # "Add details" is not shown on demo data: its form posts to the page's own address arguments, as the others.
        details = opened.replace(f"/slot/{sid}?", f"/slot/{sid}/details?sort=price&")
        response = self.client.post(details, data={"candidate": added.group(1), "price": "120"})
        self.assertEqual(response.status_code, 302)
        way_back(response.headers["Location"])
        page = plain_post(page, rf'value="{added.group(1)}">\s*<button class="link">Remove', candidate=added.group(1))
        self.assertNotIn("added by you", page)
        for sort in ("By price", "By quality"):         # links, not forms: sorting keeps the way back too
            sorting = re.search(rf'<a class="chip-link[^"]*" href="([^"]+)"[^>]*>{sort}</a>', page)
            assert sorting is not None
            way_back(html.unescape(sorting.group(1)))
        self.assertIn(f'action="/slot/{sid}/pick?view=slot&amp;sort=score&amp;from=outfit', self.client.get(
            html.unescape(sorting.group(1))).data.decode(), "sorted, its buttons keep the way back")

    def test_a_piece_page_opened_from_the_saved_outfits_leads_back_to_them(self):
        # The Outfits page takes "saved" (the Saved outfits) as it takes an occasion. A piece's page opened with it
        # leads back to the Saved outfits, with "Saved" lit, and every button and link on it keeps it.
        outfit, coat = self.outfit_with("outer")
        sid = coat.view.slot["id"]
        page = self.client.get(f"/slot/{sid}", query_string={"from": "outfit", "at": outfit.sig, "occasion": "saved"})
        page = page.data.decode()
        back = re.search(r'<p class="crumb"><a href="([^"]+)">.*?</svg> Back to the outfit</a></p>', page, re.S)
        assert back is not None, "no way back to the outfit"
        self.assertEqual(html.unescape(back.group(1)), f"/outfits?at={outfit.sig}&occasion=saved")
        self.assertIn('<a href="/outfits" class="on" aria-current="page">Outfits</a>', page)
        kept = re.findall(r'(?:action|href)="(/slot/[^"]*from=outfit[^"]*)"', page)
        self.assertGreaterEqual(len(kept), 4, "the page's buttons and links")
        self.assertEqual([a for a in kept if "occasion=saved" not in a], [], "a button or link drops 'saved'")
        lands = self.client.get(html.unescape(back.group(1))).data.decode()
        self.assertRegex(lands, r'<a class="chip-link on" href="/outfits\?occasion=saved" aria-current="page">')

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
