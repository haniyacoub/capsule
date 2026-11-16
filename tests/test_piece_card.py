"""A piece's card that reads at a glance, the same wherever it is shown.

What it promises: the Wardrobe card, the pop-up, the piece's own page and Buy say the same things about a product in
the same order (the piece and its price, the store and "Quality 73/100", the store's name for the product in English
with its own words under it, "Fabric: …", "Fit: …"), and the fabric line says no more than the store did: shares
the store never gave are not shown as figures, and "the rest not stated" is said only when a label stops short.
"""
import html
import re
import unittest

from wardrobe import catalog, composition, english, outfits, programmes, scoring, selection
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

    def test_the_same_lines_in_the_same_order(self):
        c, check = self.c, self.c.check
        said = english.name(c.data["name"])
        self.assertTrue(said and check.fit, "the demo coat has an English name and a cut to tell")
        lines = [programmes.label(c.data["store"]), f"Quality {c.score.total}/100", said, c.data["name"],
                 f"Fabric: {c.score.fabric_words}", f"Fit: {check.fit}"]
        price = " ".join(html.unescape(eur(c.price)).split())       # read() writes its no-break space as a space
        for place, text in self.places().items():
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

    def test_buying_a_product_with_no_fabric_says_to_check_it(self):
        # On Buy this outfit and the shopping list, a product with no fabric at all is a caution to act on before
        # ordering: in amber with its flag. Elsewhere the card says "Fabric: not stated", as every card does.
        sid = self.piece.slot["id"]
        catalog.update(lambda cat: [c.update(name="Mantel", slug="mantel", composition_text="")
                                    for c in cat["candidates"] if c["slot_id"] == sid])
        jacket = selection.build().get(sid)
        self.assertEqual(jacket.chosen.score.fabric_source, "none")
        for place, url in (("Buy", f"/outfits/buy?at={self.outfit.sig}"), ("shopping list", "/list")):
            with self.subTest(place):
                page = self.client.get(url).data.decode()
                line = next(li for li in re.findall(r'<li class="buy">(.*?)</li>', page, re.S)
                            if self.piece.slot["name"] in li)
                self.assertRegex(line, r'<span class="fabric caution"><svg class="ic"[^>]*>.*?</svg> Fabric not stated: '
                                       r'check the product page</span>')
                self.assertNotIn("Fabric: not stated", line)
        card = re.search(rf'id="card-{sid}">(.*?)</article>', self.client.get("/").data.decode(), re.S).group(1)
        self.assertIn('<span class="fabric">Fabric: not stated</span>', card)
        self.assertIn("Fabric not stated: check the product page.", self.client.get("/list.csv").data.decode())

    def test_the_estimated_chip_is_a_word_of_its_own(self):
        # Not glued to the word before it by a no-break space: on a narrow card it goes onto the next line whole.
        sid = self.piece.slot["id"]
        catalog.update(lambda cat: [c.update(name="Mantel aus Wollmischung", slug="mantel", composition_text="")
                                    for c in cat["candidates"] if c["slot_id"] == sid])
        self.assertEqual(selection.build().get(sid).chosen.score.fabric_source, "name")
        page = self.client.get("/").data.decode()
        self.assertIn(' <span class="est">estimated</span>', page)
        self.assertNotIn('&nbsp;<span class="est">', page)

    def test_the_price_levels_speak_of_pieces(self):
        # The tooltips on the price levels, and the name of the group they are in, say "piece", never "slot".
        page = self.client.get("/").data.decode()
        levels = re.search(r'<div class="seg levels"(.*?)</div>', page, re.S).group(0)
        tips = re.findall(r'title="([^"]*)"', levels)
        self.assertEqual(len(tips), len(selection.MODES))
        self.assertFalse([t for t in tips if "slot" in t.lower()], tips)
        self.assertIn("each piece", html.unescape(" ".join(tips)))
        self.assertIn('aria-label="Which option fills each piece: a price level, or the best your budget buys"', levels)

    def test_the_quality_number_has_no_tooltip_and_is_heard_once(self):
        # Wherever a product's quality is shown (the Wardrobe, the pop-up and its other options, a piece's page, Buy and
        # the shopping list), the word Quality is beside the number, so the number has no tooltip: a tooltip would
        # have a screen reader say the number twice, and say "score". It is heard as "Quality 73 out of 100".
        sid = self.piece.slot["id"]
        pages = {"Wardrobe": "/", "piece page": f"/slot/{sid}", "Buy": f"/outfits/buy?at={self.outfit.sig}",
                 "shopping list": "/list"}
        said = {place: self.client.get(url).data.decode() for place, url in pages.items()}
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

    def test_the_english_line_and_the_stores_own_words_are_marked(self):
        name, said = self.c.data["name"], english.name(self.c.data["name"])
        page = self.client.get("/").data.decode()
        self.assertIn(f'<span class="item" lang="en">{html.escape(said, quote=False)}</span>', page)
        self.assertIn(f'<span class="item orig" lang="de">{html.escape(name, quote=False)}</span>', page)
