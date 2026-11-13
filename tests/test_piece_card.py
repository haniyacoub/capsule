"""A piece's card that reads at a glance, the same wherever it is shown.

What it promises: the Wardrobe card, the pop-up, the piece's own page and Buy say the same things about a product in
the same order (the piece and its price, the store and "Quality 73/100", the store's name for the product in English
with its own words under it, "Fabric: …", "Fit: …"), and the fabric line says no more than the store did: shares
the store never gave are not shown as figures, and "the rest not stated" is said only when a label stops short.
"""
import html
import re
import unittest

from wardrobe import composition, english, outfits, programmes, scoring, selection
from wardrobe.app import eur

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

    def test_an_assumed_fabric_says_it_was_not_stated(self):
        jeans = fabric("Galaxy Loose Straight Leg Jeans", category="jeans")
        self.assertEqual(jeans.fabric_source, "assumed")
        self.assertEqual(jeans.fabric_words, "not stated (jeans are usually 99% cotton, 1% elastane)")
        self.assertEqual(fabric("Lässige Bomberjacke", category="jacket").fabric_words, "not stated")
        self.assertEqual(composition.in_words([("cotton", 99.0)], "assumed"), "not stated")


class SameCardEverywhere(AppCase):
    def setUp(self):
        super().setUp()
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

    def test_the_english_line_and_the_stores_own_words_are_marked(self):
        name, said = self.c.data["name"], english.name(self.c.data["name"])
        page = self.client.get("/").data.decode()
        self.assertIn(f'<span class="item" lang="en">{html.escape(said, quote=False)}</span>', page)
        self.assertIn(f'<span class="item orig" lang="de">{html.escape(name, quote=False)}</span>', page)
