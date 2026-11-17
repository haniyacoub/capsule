"""A piece's card that reads at a glance, the same wherever it is shown.

What it promises: the Wardrobe card, the pop-up, the piece's own page and Buy say the same things about a product in
the same order (the piece and its price, the store and "Quality 73/100", the store's name for the product in English
with its own words under it, "Fabric: …", "Fit: …"), and the fabric line says no more than the store did: shares
the store never gave are not shown as figures, and "the rest not stated" is said only when a label stops short.
"""
import html
import re
import unittest
from pathlib import Path

from wardrobe import catalog, composition, english, outfits, programmes, scoring, selection, sizecheck, sizes
from wardrobe.app import eur

from . import having
from .test_app import HX, AppCase

RULES = scoring.load_rules()


def read(part: str) -> str:
    """What the customer sees in a piece of a page: words for screen readers only dropped, words inside a line kept
    together ("Quality 71/100"), lines apart, spaces collapsed."""
    part = re.sub(r'<span class="sr">[^<]*</span>', "", part)
    part = re.sub(r"</?(?:span|b|small|u|s)\b[^>]*>", "", part)
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", part)).split())


def fabric(name: str, label: str | None = None, category: str = "coat", store: str = "weekday") -> scoring.Score:
    return scoring.score({"store": store, "price": 159, "name": name, "composition_text": label}, category, RULES)


class FabricLine(unittest.TestCase):
    def test_a_label_is_said_as_it_is(self):
        self.assertEqual(fabric("Mantel", "80 % Wolle, 20 % Polyamid").fabric_words, "80% wool, 20% polyamide")
        self.assertEqual(fabric("Mantel", "60 % Wolle, 40 % Sonstige Fasern").fabric_words, "60% wool, 40% other fibres")

    def test_the_rest_not_stated_only_when_the_label_stops_short(self):
        self.assertEqual(fabric("Mantel", "50 % Wolle").fabric_words, "50% wool (the rest not stated)")
        self.assertEqual(fabric("Mantel", "50 % Wolle, 50 % Polyester").fabric_words, "50% wool, 50% polyester")
        self.assertNotIn("not stated", fabric("Mantel", "100 % Wolle").fabric_words)

    def test_a_name_says_its_fibres_and_no_figures(self):
        # The 11 Nov shapes: COS and Weekday gave no fabric, so it is read off the name. The score assumes shares
        # ("≈ 50% wool · 50% other"); the card never shows them as if the store had said them.
        cases = {
            "Einreihiger Oversize-Mantel aus Wollmischung": "wool blend (the mix is not stated)",
            "Pullover aus Merinowoll-Kaschmir-Mix": "cashmere and merino blend (the mix is not stated)",
            "Rundhalspullover aus Reinem Kaschmir": "pure cashmere",
            "Jacke mit Wollanteil": "some wool (how much is not stated)",
            "Oxford-Hemd aus Baumwolle": "cotton (how much is not stated)",
            "Schmales T-Shirt aus Baumwolle, Leinen & Wolle": "cotton, wool and linen (how much is not stated)",
            "Sneaker in Lederoptik": "faux leather (how much is not stated)",
        }
        for name, said in cases.items():
            with self.subTest(name):
                score = fabric(name)
                self.assertEqual(score.fabric_source, "name")
                self.assertEqual(score.fabric_words, said)
                self.assertNotRegex(score.fabric_words, r"\d|about half")
        self.assertTrue(fabric("Einreihiger Oversize-Mantel aus Wollmischung").fabric_text.startswith("≈ 50% wool"),
                        "the score's own working still shows its assumption, marked ≈")

    def test_a_label_with_parts_says_its_parts_never_a_made_up_mix(self):
        # The score counts a label whose figures add up to more than 100 as shares of the whole (composition.parse:
        # "Vorderteil: 100 %; Rückenteil: 100 %" counts 50 + 50); the card says the label as it is.
        cases = {
            "Vorderteil: 100 % Baumwolle; Rückenteil: 100 % Polyester": "front 100% cotton, back 100% polyester",
            "Außen: 70 % Wolle, 30 % Polyamid; Ärmel: 100 % Wolle": "body 70% wool, 30% polyamide; sleeves 100% wool",
            "Oben: 60 % Wolle, 40 % Kaschmir; Unten: 55 % Wolle, 45 % Seide":
                "top 60% wool, 40% cashmere; bottom 55% wool, 45% silk",
            "100 % Baumwolle; 100 % Baumwolle; 100 % Polyester": "mixed (see the label)",
            "51 % Baumwolle, 50 % Polyester": "51% cotton, 50% polyester",      # a store's own rounding, as written
        }
        for label, said in cases.items():
            with self.subTest(label):
                score = fabric("Hemd", label, category="shirt")
                self.assertEqual(score.fabric_source, "listed")
                self.assertEqual(score.fabric_words, said)
                self.assertNotIn("50% cotton, 50% polyester", score.fabric_words)
                self.assertIn("counted as shares of the whole", score.parts[0].lines[0], "How it's rated says why")
        self.assertEqual(composition.parse("Vorderteil: 100 % Baumwolle; Rückenteil: 100 % Polyester"),
                         [("cotton", 50.0), ("polyester", 50.0)], "the score still counts it as before")
        for label in ("80 % Wolle, 20 % Polyamid", "50 % Wolle", "", None):
            with self.subTest(label):
                self.assertEqual(composition.as_labelled(label), "")
        plain = fabric("Mantel", "80 % Wolle, 20 % Polyamid")
        self.assertFalse([line for line in plain.parts[0].lines if "shares of the whole" in line])

    def test_suede_from_one_word_is_suede(self):
        # "Veloursleder" is suede, which is leather: with "leather" in the store's English slug, it is still suede.
        score = scoring.score({"store": "cos", "price": 135, "name": "Penny Loafers aus Veloursleder",
                               "slug": "leather-penny-loafers-brown-1358390001"}, "loafers", RULES)
        self.assertEqual(score.fabric_words, "suede (how much is not stated)")
        self.assertEqual(composition.guess("Sneaker aus Leder und Wildleder")[0][0][0], "suede")
        self.assertEqual(fabric("Schmale Loafers aus Leder", category="loafers").fabric_words,
                         "leather (how much is not stated)")

    def test_an_assumed_fabric_says_it_was_not_stated(self):
        jeans = fabric("Galaxy Loose Straight Leg Jeans", category="jeans")
        self.assertEqual(jeans.fabric_source, "assumed")
        self.assertEqual(jeans.fabric_words, "not stated (jeans are usually 99% cotton, 1% elastane)")
        self.assertEqual(fabric("Lässige Bomberjacke", category="jacket").fabric_words, "not stated")
        self.assertEqual(composition.in_words([("cotton", 99.0)], "assumed"), "not stated")


class SameCardEverywhere(AppCase):
    """A card says everything; a row in a list is short and leads to the card."""
    def setUp(self):
        super().setUp()
        having.the_whole_plan()     # the coat is in his wardrobe: its card is on the Wardrobe page and the list
        w = selection.build()
        self.outfit = next(o for o in outfits.all_outfits(w) if any(p.layer == "outer" for p in o.pieces))
        self.piece = next(p for p in self.outfit.pieces if p.layer == "outer").view
        self.c = self.piece.chosen

    def places(self) -> dict[str, str]:
        """The coat's card as the customer reads it, in each of the four places."""
        sid, c = self.piece.slot["id"], self.c
        popup = self.client.get("/outfits/piece", query_string={"at": self.outfit.sig, "slot": sid}, headers=HX)
        wardrobe = self.client.get("/").data.decode()
        piece_page = self.client.get(f"/slot/{sid}").data.decode()
        buy = self.client.get("/outfits/buy", query_string={"at": self.outfit.sig}).data.decode()
        card = re.search(rf'<article class="slot[^"]*" id="card-{sid}">(.*?)</article>', wardrobe, re.S)
        option = piece_page[piece_page.index(f'id="cand-{c.id}"'):]
        line = next(li for li in re.findall(r'<li class="buy">(.*?)</li>', buy, re.S) if self.piece.slot["name"] in li)
        self.assertIsNotNone(card)
        return {"pop-up": read(popup.data.decode().split("In this outfit")[0]), "Wardrobe": read(card.group(1)),
                "piece page": read(option.split("How it's rated")[0]), "Buy": read(line)}

    def test_a_card_says_everything_in_the_same_order(self):
        # Where the product is looked at (the pop-up, the piece's own page): every line, in the same order.
        c, check = self.c, self.c.check
        said = english.name(c.data["name"])
        self.assertTrue(said and check.fit, "the demo coat has an English name and a cut to tell")
        lines = [programmes.label(c.data["store"]), f"Quality {c.score.total}/100", said, c.data["name"],
                 f"Fabric: {c.score.fabric_words}", f"Fit: {check.fit}"]
        price = " ".join(html.unescape(eur(c.price)).split())       # read() writes its no-break space as a space
        places = self.places()
        for place in ("pop-up", "piece page"):
            text = places[place]
            with self.subTest(place):
                at = [text.find(words) for words in lines]
                self.assertNotIn(-1, at, f"{place} leaves out {[w for w, i in zip(lines, at) if i < 0]}: {text}")
                self.assertEqual(at, sorted(at), f"{place} says them in another order: {text}")
                self.assertIn(price, text, place)
                self.assertLess(text.find(price), at[2], f"{place}: the price comes before the product's name")
                if place != "piece page":    # there the piece's name is the page's title, above every option
                    self.assertLess(text.find(self.piece.slot["name"]), text.find(price), place)
                self.assertEqual(text.count("Fabric:"), 1, place)
                self.assertEqual(text.count("Fit:"), 1, place)

    def test_a_row_in_a_list_is_short_and_leads_to_the_card(self):
        # In a list (the Wardrobe, Buy this outfit): the piece and its price, the store and the product's name in one
        # language, the size, and only what there is to act on about this product's size (the cut runs large). The
        # quality, the fabric and the store's own words are on the card, which the row leads to.
        c, check = self.c, self.c.check
        said = english.name(c.data["name"])
        self.assertTrue(check.fit_flag, "the demo coat's cut is one to act on")
        price = " ".join(html.unescape(eur(c.price)).split())
        lines = [self.piece.slot["name"], price, programmes.label(c.data["store"]).upper(), said, "Size:", f"Fit: {check.fit}"]
        places = self.places()
        for place in ("Wardrobe", "Buy"):
            text = places[place]
            with self.subTest(place):
                at = [text.upper().find(words.upper()) if words.isupper() else text.find(words) for words in lines]
                self.assertNotIn(-1, at, f"{place} leaves out {[w for w, i in zip(lines, at) if i < 0]}: {text}")
                self.assertEqual(at, sorted(at), f"{place} says them in another order: {text}")
                for card_only in (c.data["name"], "Quality", "Fabric:"):
                    self.assertNotIn(card_only, text, f"{place}: {card_only} is on the card, not the row")
        sid = self.piece.slot["id"]
        wardrobe = self.client.get("/").data.decode()
        self.assertIn(f'<a class="slot-main" href="/slot/{sid}"', wardrobe)
        buy = self.client.get("/outfits/buy", query_string={"at": self.outfit.sig}).data.decode()
        self.assertIn(f'<span class="buy-slot"><a href="/slot/{sid}?from=outfit&amp;at={html.escape(self.outfit.sig)}">', buy)

    def test_a_product_with_no_fabric_is_said_once_for_its_store_and_in_full_on_its_card(self):
        # On Buy this outfit, the shopping list and the Wardrobe, that a product's fabric is not stated is said once,
        # over its store's rows, never on every row. Its own page says "Fabric: not stated"; the file says it too.
        sid = self.piece.slot["id"]
        catalog.update(lambda cat: [c.update(name="Mantel", slug="mantel", composition_text="")
                                    for c in cat["candidates"] if c["slot_id"] == sid])
        jacket = selection.build().get(sid)
        self.assertEqual(jacket.chosen.score.fabric_source, "none")
        store = programmes.label(jacket.chosen.data["store"])
        for place, url in (("Buy", f"/outfits/buy?at={self.outfit.sig}"), ("shopping list", "/list"), ("Wardrobe", "/")):
            with self.subTest(place):
                page = self.client.get(url).data.decode()
                once = re.findall(r'<ul class="once">(.*?)</ul>', page, re.S)
                self.assertTrue(once, place)
                said = read(" ".join(once))
                self.assertRegex(said, r"Fabric is (estimated for \d+ of the \d+ products here and )?not stated for "
                                       r"(this product|1|\d+ of the \d+ products here)[^.]*: check the label on the product page\.")
                rows = re.findall(r'<li class="buy">(.*?)</li>', page, re.S) or \
                    re.findall(r'<article class="slot[^"]*" id="card-[^"]+">(.*?)</article>', page, re.S)
                self.assertTrue(rows, place)
                self.assertFalse([r for r in rows if "Fabric" in r], f"{place}: a row repeats it")
                if place == "Wardrobe":
                    self.assertIn(store, said, "named, as the Wardrobe is not grouped by store")
        self.assertIn('<p class="fabric">Fabric: not stated</p>', self.client.get(f"/slot/{sid}").data.decode())
        self.assertIn("Fabric not stated: check the product page.", self.client.get("/list.csv").data.decode())

    def test_an_estimated_fabric_says_so_on_the_card_and_once_on_the_list(self):
        sid = self.piece.slot["id"]
        catalog.update(lambda cat: [c.update(name="Mantel aus Wollmischung", slug="mantel", composition_text="")
                                    for c in cat["candidates"] if c["slot_id"] == sid])
        self.assertEqual(selection.build().get(sid).chosen.score.fabric_source, "name")
        card = self.client.get(f"/slot/{sid}").data.decode()
        self.assertIn('<span class="est">, estimated</span>', card)
        self.assertIn("Fabric: wool blend (the mix is not stated), estimated", read(card))
        self.assertRegex(read(self.client.get("/").data.decode()), r"Fabric is estimated for [^.:]+: check the label")

    def test_the_quality_is_a_plain_number_with_no_tooltip_and_is_heard_once(self):
        # Wherever a product's quality is shown (its card in the pop-up and its other options, a piece's page), the
        # word Quality is beside the number, so the number has no tooltip: a tooltip would have a screen reader say
        # the number twice, and say "score". It is heard as "Quality 73 out of 100". The rows of a list leave it to
        # the card.
        sid = self.piece.slot["id"]
        said = {"piece page": self.client.get(f"/slot/{sid}").data.decode()}
        said["pop-up"] = self.client.get("/outfits/piece", query_string={"at": self.outfit.sig, "slot": sid},
                                         headers=HX).data.decode()
        quality = re.compile(r'<span class="quality"><span class="sep" aria-hidden="true">·</span>Quality <span '
                             r'class="pill [a-z]*">(\d+)<span class="of" aria-hidden="true">/100</span></span><span '
                             r'class="sr"> out of 100</span></span>')
        for place, page in said.items():
            with self.subTest(place):
                pills = re.findall(r'<span class="pill\b[^>]*>', page)
                self.assertTrue(pills, f"no quality shown on the {place}")
                self.assertEqual(len(quality.findall(page)), len(pills), f"a quality on the {place} is said otherwise")
                self.assertFalse([p for p in pills if "title=" in p], f"a quality on the {place} has a tooltip")
                titles = re.findall(r'title="([^"]*)"', page)
                self.assertFalse([t for t in titles if re.search(r"\bscore|^quality \d", t, re.I)], titles)
                heard = " ".join(html.unescape(re.sub(r"<[^>]+>", "", re.sub(
                    r'<span[^>]*aria-hidden="true">[^<]*</span>', "", page))).split())
                for total in quality.findall(page):
                    self.assertIn(f"Quality {total} out of 100", heard)
                self.assertNotRegex(heard, r"Quality \d+ \d+", "a number heard twice")
        css = (Path(__file__).parent.parent / "wardrobe/static/app.css").read_text()
        rule = re.search(r"\n\.pill \{([^}]*)\}", css).group(1)
        self.assertNotIn("border-radius", rule, "a plain number, not a pill")
        self.assertNotIn("background", rule, "a plain number, not a pill")

    def test_the_english_name_on_a_row_and_the_stores_own_words_on_the_card_are_marked(self):
        name, said = self.c.data["name"], english.name(self.c.data["name"])
        page = self.client.get("/").data.decode()
        self.assertIn(f'<span lang="en">{html.escape(said, quote=False)}</span>', page)
        self.assertNotIn(html.escape(name, quote=False), page, "one language on the row")
        card = self.client.get(f"/slot/{self.piece.slot['id']}").data.decode()
        self.assertIn(f'<span lang="de">{html.escape(name, quote=False)}</span>', card)

    def test_the_price_levels_speak_of_pieces(self):
        # The tooltips on the price levels, and the name of the group they are in, say "piece", never "slot".
        page = self.client.get("/").data.decode()
        levels = re.search(r'<div class="seg levels"(.*?)</div>', page, re.S).group(0)
        tips = re.findall(r'title="([^"]*)"', levels)
        self.assertEqual(len(tips), len(selection.MODES))
        self.assertFalse([t for t in tips if "slot" in t.lower()], tips)
        self.assertIn("each piece", html.unescape(" ".join(tips)))
        self.assertIn('aria-label="Which option fills each piece: a price level, or the best your budget buys"', levels)


class SaidOnceForAStore(unittest.TestCase):
    """What is true of a whole store's products on a list is said once over its rows (selection.said_once), and a
    row keeps only what is to act on about that very product's size (Cand.size_cautions)."""

    def cand(self, store: str, known: bool = True, fabric_text: str | None = "100 % Wolle", name: str = "Mantel",
             fit: str = "") -> selection.Cand:
        data = {"store": store, "price": 100, "name": name, "composition_text": fabric_text, "fit": fit}
        size = sizes.SizeStatus(available=True, label="M" if known else None, text="", known=known)
        check = sizecheck.Check(usual="M", fit=sizecheck.FITS.get(fit, ""), fit_flag=fit in ("oversized", "slim"))
        if not known:
            check.notes.append(sizes.not_checked(store) + ".")
        return selection.Cand(data=data, score=scoring.score(data, "coat", RULES), size=size, fabric="",
                              colour_hex="#000", check=check)

    def test_a_store_none_of_whose_sizes_were_checked_says_so_once_in_the_words_of_every_card(self):
        said = selection.said_once([self.cand("cos", known=False), self.cand("cos", known=False)])
        self.assertEqual(len(said), 1)
        self.assertEqual(said[0].sizes, sizes.not_checked("cos") + ".")
        self.assertEqual(said[0].fabric, "")

    def test_some_unchecked_are_counted_and_the_others_say_nothing(self):
        said = selection.said_once([self.cand("cos", known=False), self.cand("cos")])
        self.assertEqual(said[0].sizes, f"Sizes not checked for 1 of the 2 products here at {programmes.label('cos')}, "
                                        "marked “check”: look on its page before you buy.")
        self.assertEqual(selection.said_once([self.cand("weekday"), self.cand("weekday")]), [], "nothing to say")

    def test_fabric_estimated_and_not_stated_are_counted(self):
        estimated = self.cand("weekday", fabric_text="", name="Mantel aus Wollmischung")
        unstated = self.cand("weekday", fabric_text="", name="Mantel")
        self.assertEqual(estimated.score.fabric_source, "name")
        self.assertEqual(unstated.score.fabric_source, "none")
        one = selection.said_once([estimated])[0].fabric
        self.assertTrue(one.startswith("Fabric is estimated for this product: check the label"), one)
        both = selection.said_once([estimated, unstated, self.cand("weekday")])[0].fabric
        self.assertTrue(both.startswith("Fabric is estimated for 1 of the 3 products here and not stated for 1"), both)
        alone = selection.said_once([unstated, unstated])[0].fabric
        self.assertTrue(alone.startswith("Fabric is not stated for both products here"), alone)

    def test_stores_come_in_the_order_the_stores_are_listed(self):
        order = [key for key in programmes.offered() if key in ("cos", "weekday")]
        said = selection.said_once([self.cand("weekday", known=False), self.cand("cos", known=False)])
        self.assertEqual([s.store for s in said], order)

    def test_a_row_keeps_the_cut_and_the_chart_but_not_what_is_true_of_the_whole_store(self):
        c = self.cand("cos", known=False, fit="oversized")
        c.check.notes.insert(0, "Between sizes at COS: a 100 cm chest is on the border of M and L.")
        self.assertEqual(c.size_cautions, ["Fit: oversized, runs large.",
                                           "Between sizes at COS: a 100 cm chest is on the border of M and L."])
        self.assertEqual(self.cand("weekday", fit="relaxed").size_cautions, [], "a relaxed cut is nothing to act on")
