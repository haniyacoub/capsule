"""Stilsmith is for men only, and takes pasted links from stores it has no reader for.

Menswear only (wardrobe/menswear.py): every feed import and every pasted link keeps only men's products. A product
its feed, its link or its saved page says is for women or for children is refused, with a plain sentence; one that
says nothing is kept. There is no switch.

The generic reader (wardrobe/collect/generic.py) reads a product page's own description of its product, for any
store. Stilsmith never opens a store's page: the page is one the customer saved from his own browser and sent with
the link. Every page in tests/fixtures/pages/ is invented; no store was visited to write these tests.
"""
import html
import io
import re
import unittest
from collections import Counter
from pathlib import Path

from wardrobe import catalog, db, menswear, paths, selection
from wardrobe.app import SAVED_PAGE, create_app
from wardrobe.collect import generic, manual
from wardrobe.feeds import awin_csv, google, rows, tradedoubler

PAGES = Path(__file__).parent / "fixtures" / "pages"
FEEDS = Path(__file__).parent / "fixtures" / "feeds"


def page(name: str) -> str:
    return (PAGES / name).read_text(encoding="utf-8")


class WhoAProductIsFor(unittest.TestCase):
    def test_the_products_own_word_its_age_group_and_where_it_is_filed(self):
        says = menswear.not_for_men
        for gender, age, filed, verdict in (
                ("male", None, "Herren > Hemden", None),
                ("Male", "adult", None, None),
                ("Herren", None, None, None),
                ("unisex", None, "Damen > Mützen", None),               # the product's own word counts most
                (None, None, None, None),                               # says nothing: kept
                (None, None, "Apparel & Accessories > Clothing > Shirts & Tops", None),
                (None, None, "Herrenmode", None),
                (None, None, "Damen & Herren > Accessoires", None),     # for both: kept
                (None, None, "Men's Clothing > Jackets", None),
                ("female", None, None, "women"),
                ("Damen", None, "Jacken", "women"),
                ("women", "adult", "Clothing", "women"),
                (None, None, "Damen > Jacken", "women"),
                (None, None, "Damenmode", "women"),
                (None, None, "Women's Clothing > Jackets", "women"),
                (None, None, "Bekleidung > Frauen > Hosen", "women"),
                ("male", "kids", None, "children"),
                ("male", None, "Kinder > Jungen > Jacken", "children"),
                ("boys", None, None, "children"),
                (None, "toddler", None, "children"),
                (None, None, "Kinderschuhe", "children"),
                (None, None, "Mädchen > Kleider", "children"),
                ("female", "kids", None, "children"),
                (None, None, "Baby > Strampler", "children")):
            self.assertEqual(says(gender, age, filed), verdict, (gender, age, filed))

    def test_what_a_links_own_words_say(self):
        says = menswear.link_not_for_men
        for link, verdict in (
                ("https://www.tom-tailor.de/herren/hemden/regular-fit-hemd-1041234_10668", None),
                ("https://www.otto.de/p/beispielmarke-langarmhemd-C1689044821/", None),
                ("https://www.cos.com/de-de/men/menswear/knitwear/product/merino-jumper-black-4100000902", None),
                ("https://www.bergfreunde.de/beispielmarke-hemd-babyblau-9000007/", None),      # a colour, not a baby
                ("https://www.bergfreunde.de/beispielmarke-baby-blue-shirt-9000007/", None),
                ("https://www.blue-tomato.com/de-DE/product/boyfriend-fit-jeans-9000008/", None),
                ("https://www.otto.de/p/hemd-C1/?gender=damen", None),                # only the path is read
                ("https://www.tom-tailor.de/damen/jacken/steppjacke-1041235_10668", "women"),
                ("https://www.otto.de/p/beispielmarke-damenjacke-C1689044822/", "women"),
                ("https://www.blue-tomato.com/de-DE/products/categories/Women-00000002/product/hoodie-9000009/", "women"),
                ("https://www.bergfreunde.de/kinder/jacken/regenjacke-9000010/", "children"),
                ("https://www.breuninger.com/de/kindermode/jungen/hemd/p/9000011", "children"),
                ("https://www.otto.de/p/beispielmarke-maedchen-kleid-C1689044823/", "children")):
            self.assertEqual(says(link), verdict, link)


class FeedsKeepOnlyMenswear(unittest.TestCase):
    """Every feed format goes through rows.product, so the rule is the same for Awin, Tradedoubler and the rest."""

    GOOD = {"product_id": "A1", "name": "Hemd", "price": "39,95 EUR", "buy_link": "https://www.example.com/a1"}

    def test_a_row_for_women_or_children_is_skipped_with_its_reason(self):
        self.assertEqual(rows.product(**self.GOOD, gender="male", category="Herren > Hemden")["gender"], "male")
        self.assertEqual(rows.product(**self.GOOD)["name"], "Hemd", "a feed that says nothing: kept")
        for more, reason in (({"gender": "female"}, "for women"),
                             ({"category": "Damen > Blusen"}, "for women"),
                             ({"gender": "male", "age_group": "kids"}, "for children"),
                             ({"category": "Kinder > Jungen > Hemden"}, "for children"),
                             # said first, also of a row that has no price: one reason per row
                             ({"gender": "female", "price": None}, "for women")):
            with self.assertRaises(rows.Skip) as skipped:
                rows.product(**{**self.GOOD, **more})
            self.assertEqual(str(skipped.exception), reason, more)

    def test_each_format_reads_whom_a_product_is_for(self):
        # Google's format (Awin's JSON Lines, Webgains' CSV): gender, age_group and the store's own category.
        base = {"id": "G1", "title": "Jacke", "price": "99.00 EUR", "link": "https://www.example.com/g1"}
        records = [{**base, "gender": "male", "age_group": "adult", "product_type": "Herren > Jacken"},
                   {**base, "id": "G2", "gender": "female"},
                   {**base, "id": "G3", "gender": "unisex", "age_group": "kids"},
                   {**base, "id": "G4", "google_product_category": "Apparel & Accessories > Clothing > Dresses",
                    "product_type": "Damen > Kleider"},
                   {**base, "id": "G5"}]
        result = rows.collect(records, google.product)
        self.assertEqual([r["product_id"] for r in result.rows], ["G1", "G5"])
        self.assertEqual(result.skipped, Counter({"for women": 2, "for children": 1}))
        self.assertEqual(result.summary(), "3 skipped: 2 for women, 1 for children")
        # Awin's own CSV: Fashion:suitable_for and merchant_category.
        base = {"aw_product_id": "W1", "product_name": "Pullover", "search_price": "59.00",
                "aw_deep_link": "https://www.example.com/w1"}
        records = [{**base, "Fashion:suitable_for": "Male"},
                   {**base, "aw_product_id": "W2", "Fashion:suitable_for": "Female"},
                   {**base, "aw_product_id": "W3", "merchant_category": "Kinder > Pullover"},
                   {**base, "aw_product_id": "W4", "Fashion:suitable_for": "Unisex", "merchant_category": "Mützen"}]
        result = rows.collect(records, awin_csv.product)
        self.assertEqual([r["product_id"] for r in result.rows], ["W1", "W4"])
        self.assertEqual(result.skipped, Counter({"for women": 1, "for children": 1}))
        # Tradedoubler: a store's own "gender" field and the product's first category.
        def td(sku, gender=None, category=None):
            return {"name": "Chino", "identifiers": {"sku": sku},
                    "fields": [{"name": "gender", "value": gender}] if gender else [],
                    "categories": [{"name": category}] if category else [],
                    "offers": [{"productUrl": "https://www.example.com/" + sku,
                                "price": {"value": "49.95", "currency": "EUR"}}]}
        result = rows.collect([td("T1", "male", "Herren > Hosen"), td("T2", "female"), td("T3", None, "Damen > Hosen"),
                               td("T4")], tradedoubler.product)
        self.assertEqual([r["product_id"] for r in result.rows], ["T1", "T4"])
        self.assertEqual(result.skipped, Counter({"for women": 2}))

    def test_the_sample_feeds_are_all_menswear(self):
        for read, name in ((google.read, "musterhaus.jsonl"), (awin_csv.read, "nordfaden.csv"),
                           (tradedoubler.read, "kleiderwerk.json")):
            result = read(FEEDS / name)
            self.assertTrue(result.rows, name)
            self.assertFalse([why for why in result.skipped if why.startswith("for ")], name)


class TheGenericReader(unittest.TestCase):
    def test_a_page_with_schema_org_data(self):
        self.assertEqual(generic.read(page("mens-shirt.html")), {
            "name": "OXFORD-HEMD REGULAR FIT", "price": 49.99, "currency": "EUR", "colour": "Hellblau",
            "material": "100% Baumwolle", "gender": "male", "breadcrumbs": ["Herren", "Hemden", "Oxford-Hemd Regular Fit"],
            "address": "https://www.hirmer.de/herren/hemden/oxford-hemd-regular-fit-hellblau/p/9000001"})

    def test_a_list_of_blocks_an_aggregate_offer_and_breadcrumbs_named_inside_their_items(self):
        self.assertEqual(generic.read(page("womens-jacket.html")), {
            "name": "Steppjacke", "price": 129.95, "currency": "EUR", "colour": "Schwarz",
            "breadcrumbs": ["Damen", "Jacken"], "address": "https://www.bergfreunde.de/beispielmarke-steppjacke-9000002/"})

    def test_a_page_with_open_graph_tags_only_and_breadcrumbs_as_plain_html(self):
        # A block that is not JSON costs only that block; "39,95" is a German price.
        self.assertEqual(generic.read(page("kids-hoodie.html")), {
            "name": "Kapuzenpullover", "price": 39.95, "currency": "EUR", "colour": "Grau",
            "breadcrumbs": ["Start", "Kinder", "Hoodies & Sweatshirts"],
            "address": "https://www.blue-tomato.com/de-DE/product/beispielmarke-kapuzenpullover-9000003/"})
        self.assertEqual(generic.read(page("mens-chinos-plain.html")), {
            "name": "Chino Slim Fit", "price": 49.99, "currency": "EUR", "colour": "Beige", "material": "sehr angenehm",
            "breadcrumbs": ["Herren", "Hosen", "Chino Slim Fit"]})

    def test_a_page_that_says_nothing_and_text_that_is_no_page(self):
        self.assertEqual(generic.read(page("says-nothing.html")), {})
        self.assertEqual(generic.read(""), {})
        self.assertEqual(generic.read("%PDF-1.7 \x00\x01 <<< not html >>>"), {})
        self.assertEqual(generic.read('<script type="application/ld+json">[1, "two", null, {"@type": "Product", '
                                      '"name": {"x": 1}, "offers": "soon"}]</script><title> A  title </title>'),
                         {"name": "A title"})

    def test_the_photo_and_the_description_are_never_read(self):
        for name in ("mens-shirt.html", "womens-jacket.html", "kids-hoodie.html"):
            said = generic.read(page(name))
            self.assertNotIn(".jpg", str(said), name)
            self.assertFalse({"image", "image_url", "description"} & set(said), name)


class PastedLinksFromTheSixStores(unittest.TestCase):
    """Through the app, on your own machine: a piece's page, "Add a product by link"."""

    LINKS = {   # invented addresses in shapes such stores use; the name each link alone gives
        "tom-tailor": ("https://www.tom-tailor.de/herren/hemden/regular-fit-hemd-aus-baumwolle-1041234_10668",
                       "Regular fit hemd aus baumwolle"),
        "otto": ("https://www.otto.de/p/beispielmarke-langarmhemd-oxford-C1689044821/#variationId=1689044822",
                 "Beispielmarke langarmhemd oxford"),
        "hirmer": ("https://www.hirmer.de/herren/hemden/oxford-hemd-regular-fit-hellblau/p/9000001",
                   "Oxford hemd regular fit hellblau"),
        "breuninger": ("https://www.breuninger.com/de/marken/beispielmarke/hemd-slim-fit/p/1001234567/",
                       "Hemd slim fit"),
        "blue-tomato": ("https://www.blue-tomato.com/de-DE/product/Beispielmarke-Flanell-Overshirt-9000004/",
                        "Beispielmarke Flanell Overshirt"),
        "bergfreunde": ("https://www.bergfreunde.de/beispielmarke-merino-shirt-9000005/", "Beispielmarke merino shirt"),
    }

    def setUp(self):
        for path in (paths.DB_PATH, paths.CATALOG_PATH):
            path.unlink(missing_ok=True)
        catalog._cache = None
        self.client = create_app().test_client()
        self.slot = next(s for s in db.list_slots() if s["category"] == "shirt")
        self.sid = self.slot["id"]
        catalog.update(catalog.start_collected)     # real data, not the demo's: the invented demo items are gone

    def tearDown(self):
        paths.CATALOG_PATH.unlink(missing_ok=True)
        catalog._cache = None

    def add(self, link: str, saved: str | bytes | None = None, name: str = "page.html") -> list[str]:
        """Paste a link (with the page as he saved it, if any); the messages inside "Add a product by link"."""
        data: dict = {"urls": link}
        if saved is not None:
            data["page"] = (io.BytesIO(saved.encode() if isinstance(saved, str) else saved), name)
        answer = self.client.post(f"/slot/{self.sid}/import", data=data, content_type="multipart/form-data",
                                  follow_redirects=True).get_data(as_text=True)
        section = re.search(r'<section class="card add" id="add">(.*?)</section>', answer, re.S).group(1)
        return [html.unescape(m) for m in re.findall(r'<p class="flash[^"]*" role="status">(.*?)</p>', section, re.S)]

    def stored(self, cand_id: str) -> dict | None:
        return catalog.find(catalog.stored(), self.sid, cand_id)

    def test_a_link_from_each_of_the_six_is_taken_and_named_from_the_link(self):
        for store, (link, name) in self.LINKS.items():
            self.assertEqual(manual.store_of(link), store)
            self.assertEqual(self.add(link), [f"Added “{name}”: only the link could be read — add the price, fabric "
                                              "and sizes under “Add details”."], store)
        mine = [c for c in catalog.stored()["candidates"] if c["store"] in self.LINKS]
        self.assertEqual([c["store"] for c in mine], list(self.LINKS))
        for cand in mine:
            self.assertEqual((cand["source"], cand["price"], cand["image_url"]), ("manual", 0.0, ""), cand["store"])
        self.assertEqual(self.stored("hirmer-9000001")["url"], self.LINKS["hirmer"][0])
        # Each is one of the piece's options, told apart as the customer's own, and never picked without a price.
        view = selection.build().get(self.sid)
        self.assertLessEqual({c["id"] for c in mine}, {c.id for c in view.cands})
        self.assertNotIn(view.chosen.id if view.chosen else None, {c["id"] for c in mine})
        shown = html.unescape(self.client.get(f"/slot/{self.sid}").get_data(as_text=True))
        self.assertIn("Open at Hirmer", shown)
        self.assertIn("Stilsmith has not rated Hirmer yet, so its brand counts as the middle, 50/100", shown)

    def test_a_womens_or_childrens_link_is_refused_with_a_plain_sentence(self):
        women = "https://www.tom-tailor.de/damen/jacken/steppjacke-1041235_10668"
        kids = "https://www.bergfreunde.de/kinder/jacken/regenjacke-9000010/"
        self.assertEqual(self.add(f"{women}\n{kids}\n{self.LINKS['hirmer'][0]}"), [
            f"Not added: “{women}” is a women's product, and Stilsmith is for menswear only.",
            f"Not added: “{kids}” is a children's product, and Stilsmith is for menswear only.",
            "Added “Oxford hemd regular fit hellblau”: only the link could be read — add the price, fabric and sizes "
            "under “Add details”."])
        self.assertEqual([c["id"] for c in catalog.stored()["candidates"] if c.get("source") == "manual"], ["hirmer-9000001"])
        # The same for COS and Weekday, the stores Stilsmith has products from.
        cos = "https://www.cos.com/de-de/women/womenswear/knitwear/product/merino-jumper-black-4100000999"
        self.assertEqual(self.add(cos), [f"Not added: “{cos[:79]}…” is a women's product, and Stilsmith is for "
                                         "menswear only."])

    def test_with_the_page_he_saved_its_name_price_colour_and_fabric_are_filled_in(self):
        link = self.LINKS["hirmer"][0]
        self.assertEqual(self.add(link, page("mens-shirt.html")), [
            "Added “Oxford-Hemd Regular Fit”: its name, price, colour and fabric were read from the page you saved — "
            "add the sizes under “Add details”."])
        cand = self.stored("hirmer-9000001")
        self.assertEqual((cand["name"], cand["price"], cand["currency"], cand["colour"], cand["composition_text"]),
                         ("Oxford-Hemd Regular Fit", 49.99, "EUR", "Hellblau", "100% Baumwolle"))
        self.assertEqual((cand["image_url"], cand["description"], cand["url"]), ("", "", link),
                         "never the store's photo or its text; the link is the one he pasted")
        view = next(c for c in selection.build().get(self.sid).cands if c.id == "hirmer-9000001")
        self.assertEqual(view.gaps, ["sizes"])
        # A page that gives no fabric a label would: the fabric is left for him to type in.
        self.assertEqual(self.add("https://www.tom-tailor.de/herren/hosen/chino-slim-fit-1041236_10668",
                                  page("mens-chinos-plain.html")),
                         ["Added “Chino Slim Fit”: its name, price and colour were read from the page you saved — add "
                          "the fabric and sizes under “Add details”."])

    def test_a_saved_page_whose_breadcrumbs_say_women_or_children_is_refused(self):
        # Neither link says whom the product is for; the page does.
        jacket = "https://www.bergfreunde.de/beispielmarke-steppjacke-9000002/"
        hoodie = "https://www.blue-tomato.com/de-DE/product/beispielmarke-kapuzenpullover-9000003/"
        self.assertIsNone(menswear.link_not_for_men(jacket) or menswear.link_not_for_men(hoodie))
        self.assertEqual(self.add(jacket, page("womens-jacket.html")),
                         [f"Not added: “{jacket}” is a women's product, and Stilsmith is for menswear only."])
        self.assertEqual(self.add(hoodie, page("kids-hoodie.html")),
                         [f"Not added: “{hoodie}” is a children's product, and Stilsmith is for menswear only."])
        self.assertEqual([c for c in catalog.stored()["candidates"] if c.get("source") == "manual"], [])

    def test_a_saved_page_that_cannot_help_never_stops_the_link(self):
        link, name = self.LINKS["otto"]
        only_link = "only the link could be read — add the price, fabric and sizes under “Add details”"
        # Another store's page, a page that says nothing, a file that is no page at all, two links with one page.
        self.assertEqual(self.add(link, page("mens-shirt.html")),
                         [f"Added “{name}”: {only_link}. The page you saved is not this store's, so it was not read."])
        self.assertEqual(self.add(link, page("says-nothing.html")),
                         [f"Added “{name}”: the page you saved says nothing about the product, so {only_link}."])
        self.assertEqual(self.add(link, b"\x89PNG\r\n\x1a\n\x00\x00\xff\xfe", "photo.png"),
                         [f"Added “{name}”: the page you saved says nothing about the product, so {only_link}."])
        both = self.add(f"{link}\n{self.LINKS['hirmer'][0]}", page("mens-shirt.html"))
        self.assertEqual(both, [f"Added “{name}”: {only_link}. The saved page was not read: send it with one link at a time.",
                                f"Added “Oxford hemd regular fit hellblau”: {only_link}. The saved page was not read: "
                                "send it with one link at a time."])
        self.assertEqual(self.stored("hirmer-9000001")["price"], 0.0)
        # Larger than 3 MB: nothing is added, and the page says what to do instead.
        self.assertEqual(self.add(self.LINKS["bergfreunde"][0], b"<html>" + b"x" * SAVED_PAGE),
                         ["Not added: the saved page is larger than 3 MB. Paste the link alone and type in the price."])
        self.assertIsNone(self.stored("bergfreunde-9000005"))
        # Far larger still (the server stops reading it): the same answer, on the piece's page, not an error page.
        self.assertEqual(self.add(self.LINKS["bergfreunde"][0], b"x" * (SAVED_PAGE + 300_000)),
                         ["Not added: the saved page is larger than 3 MB. Paste the link alone and type in the price."])
        self.assertIsNone(self.stored("bergfreunde-9000005"))

    def test_the_form_says_menswear_only_and_offers_the_saved_page(self):
        shown = html.unescape(self.client.get(f"/slot/{self.sid}").get_data(as_text=True))
        section = re.search(r'<section class="card add" id="add">(.*?)</section>', shown, re.S).group(1)
        text = " ".join(re.sub(r"<[^>]+>", " ", section).split())
        self.assertIn("Paste product page addresses from COS, Weekday, Tom Tailor, OTTO, Hirmer, Breuninger, Blue Tomato "
                      "or Bergfreunde, one per line. Menswear only. Stilsmith does not open the page:", text)
        self.assertIn('enctype="multipart/form-data"', section)
        self.assertIn('<input type="file" name="page" accept=".html,.htm,text/html" aria-describedby="page-help">', section)
        self.assertIn("The product's page, saved from your browser (optional)", text)
