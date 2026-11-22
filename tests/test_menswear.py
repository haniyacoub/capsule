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

from .having import the_old_start

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
                (None, None, "Baby > Strampler", "children"),
                # A children's word inside a brand's or a product's name is not a folder: these are for men.
                ("male", None, "Herren > Marken > Billionaire Boys Club", None),
                ("male", None, "Marken > Billionaire Boys Club", None),
                (None, None, "Herren > Jeans > Teen Spirit", None),
                ("male", "adult", "Skate > Girl", None),
                ("M", None, None, None),
                ("männlich", None, None, None),
                (None, None, "Sale > Menswear", None),
                # Women's words as German, Dutch and English stores also write them.
                ("weiblich", None, None, "women"),
                ("W", None, None, "women"),
                ("F", None, "Jacken", "women"),
                (None, None, "Sale > Womenswear", "women"),
                (None, None, "Dames > Jassen", "women"),
                (None, None, "Kids & Teens > Jacken", "children")):
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
                # A brand or a product with a children's word in its name is not a children's product.
                ("https://www.breuninger.com/de/herren/billionaire-boys-club-hoodie/1001234777/p/", None),
                ("https://www.blue-tomato.com/de-DE/product/Girl-OG+T+Shirt-612388/", None),
                ("https://www.otto.de/p/herren-jeans-teen-spirit-C9000011/", None),
                ("https://www.hirmer.de/herren/kids-see-ghosts-hoodie/p/9000012", None),
                ("https://www.breuninger.com/de/womenswear/jacken/steppjacke/p/9000013", "women"),
                ("https://www.blue-tomato.com/nl-NL/dames/product/hoodie-9000014/", "women"),
                ("https://www.blue-tomato.com/de-DE/kids/product/hoodie-9000015/", "children"),
                ("https://www.otto.de/kids-boys/p/hoodie-C9000016/", "children"),
                ("https://www.tom-tailor.de/damen/jacken/steppjacke-1041235_10668", "women"),
                ("https://www.blue-tomato.com/de-DE/products/categories/Women-00000002/product/hoodie-9000009/", "women"),
                ("https://www.bergfreunde.de/kinder/jacken/regenjacke-9000010/", "children"),
                ("https://www.breuninger.com/de/kindermode/jungen/hemd/p/9000011", "children"),
                ("https://www.otto.de/baby/p/beispielmarke-strickjacke-C9000100/", "children"),      # the babies' folder
                # Only the product's own name says it: not refused (asked about: the next test).
                ("https://www.otto.de/p/beispielmarke-damenjacke-C1689044822/", None),
                ("https://www.otto.de/p/beispielmarke-maedchen-kleid-C1689044823/", None)):
            self.assertEqual(says(link), verdict, link)

    def test_a_word_in_a_products_name_in_a_link_is_asked_about_never_refused(self):
        """A folder says it plainly ("/kinder/"): refused. The product's name alone is not reliable: a word for
        children or women in it, as a word of its own or joined to a word for clothes, is asked about."""
        for link, word, whom in (
                ("https://www.otto.de/p/beispielmarke-jungen-mantel-C9000041/", "jungen", "children"),
                ("https://www.blue-tomato.com/de-DE/product/Beispielmarke-Girls+Jacket-9000042/", "girls", "children"),
                ("https://www.bergfreunde.de/beispielmarke-kids-hoodie-9000043/", "kids", "children"),
                ("https://www.otto.de/p/beispielmarke-boys-t-shirt-C9000044/", "boys", "children"),
                ("https://www.otto.de/p/beispielmarke-kinder-regenjacke-C9000045/", "kinder", "children"),
                ("https://www.otto.de/p/beispielmarke-jungenmantel-C9000046/", "jungenmantel", "children"),
                ("https://www.bergfreunde.de/beispielmarke-kidswear-set-9000047/", "kidswear", "children"),
                ("https://www.otto.de/p/beispielmarke-M%C3%A4dchen-Kleid-C9000040/", "mädchen", "children"),
                ("https://www.otto.de/p/beispielmarke-maedchen-kleid-C1689044823/", "maedchen", "children"),
                ("https://www.otto.de/p/beispielmarke-damen-mantel-C9000048/", "damen", "women"),
                ("https://www.otto.de/p/beispielmarke-damen-slim-fit-jeans-C9000049/", "damen", "women"),
                ("https://www.blue-tomato.com/de-DE/product/Beispielmarke-Womens+Jacket-9000050/", "womens", "women"),
                ("https://www.tom-tailor.de/ladies-blazer-1049051_10668", "ladies", "women"),
                ("https://www.otto.de/p/beispielmarke-frauen-pullover-C9000052/", "frauen", "women"),
                ("https://www.otto.de/p/beispielmarke-damenmantel-C9000053/", "damenmantel", "women"),
                ("https://www.otto.de/p/beispielmarke-damenjacke-C1689044822/", "damenjacke", "women"),
                # the word need not stand right before the clothes: the shapes real store links have
                ("https://www.bergfreunde.de/beispielmarke-kids-down-sweater-daunenjacke-9000081/", "kids", "children"),
                ("https://www.blue-tomato.com/de-DE/product/Beispielmarke-Girls+Elodie+Jacket-9000082/", "girls", "children"),
                ("https://www.otto.de/p/beispielmarke-kids-air-max-90-C9000083/", "kids", "children"),
                ("https://www.otto.de/p/beispielmarke-mantel-fuer-jungen-C9000084/", "jungen", "children"),
                ("https://www.otto.de/p/beispielmarke-hoodie-kids-C9000085/", "kids", "children"),
                ("https://www.otto.de/p/beispielmarke-boys-blue-jacket-C9000086/", "boys", "children"),
                ("https://www.otto.de/p/beispielmarke-girls-wool-coat-C9000087/", "girls", "children"),
                ("https://www.otto.de/p/beispielmarke-junior-steppjacke-C9000088/", "junior", "children"),
                ("https://www.otto.de/p/kids-only-jeans-C9000089/", "kids", "children"),
                # (these were kept without a question)
                ("https://www.otto.de/p/beispielmarke-jugend-jacke-C9000102/", "jugend", "children"),
                ("https://www.otto.de/p/beispielmarke-youth-hoodie-C9000103/", "youth", "children"),
                # a word for one person counts right before the clothes
                ("https://www.otto.de/p/beispielmarke-teen-jacke-C9000090/", "teen", "children"),
                ("https://www.otto.de/p/beispielmarke-girl-jacket-C9000091/", "girl", "children"),
                ("https://www.otto.de/p/beispielmarke-boy-jacket-C9000092/", "boy", "children"),
                ("https://www.otto.de/p/beispielmarke-baby-jacke-C9000093/", "baby", "children"),
                ("https://www.otto.de/p/beispielmarke-woman-coat-C9000094/", "woman", "women"),
                # "unisex" says for women too, not for children too
                ("https://www.otto.de/p/beispielmarke-unisex-kids-hoodie-C9000101/", "kids", "children"),
                # A band, a series, a brand or a sweet with such a word in its name, on a men's shirt: these were
                # refused as children's or women's products. Now the customer is asked, and adds them with one tap.
                ("https://www.otto.de/p/beastie-boys-shirt-C9000075/", "boys", "children"),
                ("https://www.otto.de/p/pet-shop-boys-shirt-C9000076/", "boys", "children"),
                ("https://www.blue-tomato.com/de-DE/product/Backstreet+Boys+Tshirt-9000077/", "boys", "children"),
                ("https://www.otto.de/p/bad-boys-hoodie-C9000078/", "boys", "children"),
                ("https://www.otto.de/p/gilmore-girls-sweatshirt-C9000079/", "girls", "children"),
                ("https://www.otto.de/p/cool-kids-sweater-C9000080/", "kids", "children"),
                ("https://www.otto.de/p/kinder-bueno-tshirt-C9000095/", "kinder", "children"),
                ("https://www.breuninger.com/de/billionaire-boys-club-hoodie/9000066/p/", "boys", "children"),
                ("https://www.hirmer.de/kids-see-ghosts-hoodie/p/9000067", "kids", "children"),
                ("https://www.otto.de/p/les-femmes-tee-C9000096/", "femmes", "women"),
                ("https://www.otto.de/p/women-crush-tee-C9000097/", "women", "women")):
            self.assertIsNone(menswear.link_not_for_men(link), f"refused: {link}")
            self.assertEqual(menswear.link_name_says(link), (word, whom), link)

    def test_a_brand_or_an_ordinary_word_in_a_links_name_is_neither_refused_nor_asked_about(self):
        for link in ("https://www.otto.de/p/frau-holle-t-shirt-C9000061/",              # a brand, a fairy tale
                     "https://www.otto.de/p/beispielmarke-lady-like-hemd-C9000062/",
                     "https://www.otto.de/p/womensecret-pyjama-C9000063/",                # one word, a brand
                     "https://www.breuninger.com/de/marken/womensecret/pyjama/p/9000064",
                     "https://www.blue-tomato.com/de-DE/product/Girl-Hand+Shakers+Hoodie-9000065/",    # the skate brand "Girl"
                     "https://www.otto.de/p/teen-spirit-jeans-C9000068/",
                     "https://www.otto.de/p/boyfriend-jeans-C9000069/",
                     "https://www.otto.de/p/beispielmarke-jacke-fuer-junggebliebene-C9000070/",
                     "https://www.otto.de/p/beispielmarke-baby-blue-jacke-C9000074/",          # a colour
                     "https://www.otto.de/p/beispielmarke-damenhaft-eleganter-schal-C9000071/",
                     "https://www.otto.de/p/beispielmarke-langarmhemd-C1689044821/",
                     # a men's word anywhere in the link wins: kept, and not asked about either
                     "https://www.otto.de/p/beispielmarke-herren-und-damen-jacke-C9000098/",   # for both
                     "https://www.otto.de/p/beispielmarke-unisex-damen-herren-schal-C9000102/",
                     "https://www.otto.de/p/beispielmarke-ladies-unisex-beanie-C9000103/",     # unisex: for women too
                     "https://www.otto.de/p/herren-jacke-im-boys-look-C9000072/",
                     "https://www.breuninger.com/de/herren/beispielmarke-girls-jacket/9000073/p/",
                     "https://www.breuninger.com/de/herren/billionaire-boys-club-hoodie/1001234777/p/"):
            self.assertIsNone(menswear.link_not_for_men(link), link)
            self.assertIsNone(menswear.link_name_says(link), link)


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
        # offered since 19 Nov 2026 (streetwear): its links are taken like the others'
        "jd-sports": ("https://www.jdsports.de/product/beispielmarke-flanellhemd-kariert/9000006/",
                      "Beispielmarke flanellhemd kariert"),
    }

    def setUp(self):
        for path in (paths.DB_PATH, paths.CATALOG_PATH):
            path.unlink(missing_ok=True)
        catalog._cache = None
        self.client = create_app().test_client()
        the_old_start()             # a big wardrobe (a coat): as every account started until 19 Nov 2026
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
        return [html.unescape(m) for m in re.findall(r'<p [^>]*role="status"[^>]*>(.*?)</p>', section, re.S)]

    def asked(self) -> list[tuple[str, str]]:
        """The questions on the piece's page now, each as (its words, the link its "Add it anyway" button sends)."""
        shown = self.client.get(f"/slot/{self.sid}").get_data(as_text=True)
        return [(html.unescape(words), html.unescape(link)) for link, words in re.findall(
            r'<form class="flash ask" method="post" action="/slot/[^"]+/import">.*?<input type="hidden" name="urls" value="([^"]*)">'
            r'\s*<input type="hidden" name="anyway" value="1">\s*<p role="status" id="ask-\d+">(.*?)</p>'
            r'\s*<button class="btn small" aria-describedby="ask-\d+">Add it anyway</button>', shown, re.S)]

    def asked_after(self, answer) -> list[tuple[str, str]]:
        """The questions on the page a paste leads to (see asked)."""
        assert answer.status_code == 302, answer.status_code
        return self.asked()

    def add_anyway(self, link: str, saved: str | None = None) -> list[str]:
        """Tap "Add it anyway" under the question about a link: that link again, with the answer yes."""
        data: dict = {"urls": link, "anyway": "1"}
        if saved is not None:
            data["page"] = (io.BytesIO(saved.encode()), "page.html")
        answer = self.client.post(f"/slot/{self.sid}/import", data=data, content_type="multipart/form-data",
                                  follow_redirects=True).get_data(as_text=True)
        section = re.search(r'<section class="card add" id="add">(.*?)</section>', answer, re.S).group(1)
        return [html.unescape(m) for m in re.findall(r'<p [^>]*role="status"[^>]*>(.*?)</p>', section, re.S)]

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

    def test_two_products_of_one_store_are_two_options(self):
        # Tom Tailor ends a link "article_colour": two products in the same colour are still two products.
        self.sid = next(s for s in db.list_slots() if s["category"] == "coat")["id"]
        coat = "https://www.tom-tailor.de/herren/jacken/wollmantel-1041111_10668"
        parka = "https://www.tom-tailor.de/herren/jacken/parka-1042222_10668"
        only_link = "only the link could be read — add the price, fabric and sizes under “Add details”."
        self.assertEqual(self.add(coat), [f"Added “Wollmantel”: {only_link}"])
        self.assertEqual(self.add(parka), [f"Added “Parka”: {only_link}"])
        self.assertEqual(sorted((c["id"], c["name"]) for c in catalog.stored()["candidates"] if c["store"] == "tom-tailor"),
                         [("tom-tailor-1041111-10668", "Wollmantel"), ("tom-tailor-1042222-10668", "Parka")])
        # And for each of the six: a second product never takes the first one's place.
        for store, (link, _) in self.LINKS.items():
            other = re.sub(r"\d{5,}", lambda m: str(int(m.group()) + 1), link, count=1)
            self.assertNotEqual(manual._article(link), manual._article(other), store)
        for link in ("https://www.breuninger.com/de/herren/billionaire-boys-club-hoodie/1001234777/p/",
                     "https://www.blue-tomato.com/de-DE/product/Girl-OG+T+Shirt-612388/",
                     "https://www.otto.de/p/herren-jeans-teen-spirit-C9000011/"):
            self.assertRegex(self.add(link)[0], "^Added “", link)

    def test_a_link_whose_name_says_another_kind_of_garment_is_added_with_a_warning(self):
        only_link = "only the link could be read — add the price, fabric and sizes under “Add details”"
        move = "If it belongs to another piece, remove it here and paste the link there."
        # Jeans pasted on the shirt: added, and the answer says what its name says and what to do.
        self.assertEqual(self.add("https://www.otto.de/p/beispielmarke-slim-fit-jeans-C9000021/"), [
            f"Added “Beispielmarke slim fit jeans”: {only_link}. Check the kind: its name says “Jeans”, and this "
            f"piece is “Shirt”. {move}"])
        # A shirt pasted on the coat, with the page he saved: the name comes from the page, and is read the same.
        self.sid = next(s for s in db.list_slots() if s["category"] == "coat")["id"]
        said = self.add(self.LINKS["hirmer"][0], page("mens-shirt.html"))
        self.assertEqual(len(said), 1)
        self.assertTrue(said[0].endswith(f". Check the kind: its name says “Shirt”, and this piece is “Coat”. {move}"),
                        said)
        # Nothing is said when the name says the piece's own kind, a kind worn in the same place, a word that
        # only holds another kind ("Jeansjacke" on a coat or jacket), or no kind at all.
        # Denim is a cloth: a denim jacket on the coat is a jacket, however its name is written, never "Jeans".
        for link in ("https://www.tom-tailor.de/herren/jacken/wollmantel-1041111_10668",
                     "https://www.tom-tailor.de/herren/jacken/parka-1042222_10668",
                     "https://www.bergfreunde.de/beispielmarke-jeans-jacke-9000031/",
                     "https://www.bergfreunde.de/beispielmarke-jeansjacke-9000033/",
                     "https://www.bergfreunde.de/beispielmarke-denimjacke-9000034/",
                     "https://www.bergfreunde.de/beispielmarke-denim-jacket-9000035/",
                     "https://www.bergfreunde.de/beispielmarke-denim-trucker-9000036/",
                     "https://www.hirmer.de/herren/beispielmarke-modell-nord/p/9000032"):
            said = self.add(link)[0]
            self.assertRegex(said, "^Added “", link)
            self.assertNotIn("Check the kind", said, link)
            self.assertNotIn("Jeans”", said, link)
        # A denim shirt on the coat is still a shirt on a coat, and jeans are still jeans.
        self.assertIn("its name says “Shirt”, and this piece is “Coat”",
                      self.add("https://www.bergfreunde.de/beispielmarke-jeanshemd-9000037/")[0])
        self.assertIn("its name says “Jeans”, and this piece is “Coat”",
                      self.add("https://www.bergfreunde.de/beispielmarke-slim-jeans-9000038/")[0])

    def test_pasting_a_link_again_keeps_what_was_known_about_it(self):
        link = self.LINKS["hirmer"][0]
        self.add(link, page("mens-shirt.html"))
        self.client.post(f"/slot/{self.sid}/details", data={"candidate": "hirmer-9000001", "sizes": "M, L"})
        self.assertEqual(self.add(link), ["Added “Oxford-Hemd Regular Fit”: you added this link before, and what was "
                                          "known about it was kept."])
        cand = self.stored("hirmer-9000001")
        self.assertEqual((cand["name"], cand["price"], cand["colour"], cand["composition_text"]),
                         ("Oxford-Hemd Regular Fit", 49.99, "Hellblau", "100% Baumwolle"))
        self.assertEqual(cand["manual"]["sizes_in_stock"], ["M", "L"], "what he typed in is kept too")
        self.assertEqual(len([c for c in catalog.stored()["candidates"] if c["id"] == "hirmer-9000001"]), 1)
        # With the page again, it is read again, and nothing is asked for that he already gave.
        self.assertEqual(self.add(link, page("mens-shirt.html")), [
            "Added “Oxford-Hemd Regular Fit”: its name, price, colour and fabric were read from the page you saved."])
        self.assertEqual(self.stored("hirmer-9000001")["manual"]["sizes_in_stock"], ["M", "L"])

    def test_a_product_with_no_price_yet_is_not_called_cheap(self):
        self.add(self.LINKS["hirmer"][0])
        shown = html.unescape(self.client.get(f"/slot/{self.sid}").get_data(as_text=True))
        self.assertIn("No price yet, so the price counts as neutral, 70, until you type it in under “Add details”", shown)
        self.assertNotIn("0 € is far below", shown)
        self.assertNotIn("0,00 € is far below", shown)

    def test_a_womens_or_childrens_link_is_refused_with_a_plain_sentence(self):
        women = "https://www.tom-tailor.de/damen/jacken/steppjacke-1041235_10668"
        kids = "https://www.bergfreunde.de/kinder/jacken/regenjacke-9000010/"
        self.assertEqual(self.add(f"{women}\n{kids}\n{self.LINKS['hirmer'][0]}"), [
            f"Not added: “{women}” looks like a women's product, and Stilsmith is for menswear only.",
            f"Not added: “{kids}” looks like a children's product, and Stilsmith is for menswear only.",
            "Added “Oxford hemd regular fit hellblau”: only the link could be read — add the price, fabric and sizes "
            "under “Add details”."])
        self.assertEqual([c["id"] for c in catalog.stored()["candidates"] if c.get("source") == "manual"], ["hirmer-9000001"])
        # The same for COS and Weekday, the stores Stilsmith has products from.
        cos = "https://www.cos.com/de-de/women/womenswear/knitwear/product/merino-jumper-black-4100000999"
        self.assertEqual(self.add(cos), [f"Not added: “{cos[:79]}…” looks like a women's product, and Stilsmith is for "
                                         "menswear only."])

    def test_a_link_whose_name_says_kids_or_damen_is_asked_about_and_added_with_one_tap(self):
        manual_ids = lambda: [c["id"] for c in catalog.stored()["candidates"] if c.get("source") == "manual"]   # noqa: E731
        # The shapes real store links have, and a band's shirt: none is refused, each is asked about by its word.
        kids = "https://www.bergfreunde.de/beispielmarke-kids-down-sweater-daunenjacke-9000081/"
        girls = "https://www.blue-tomato.com/de-DE/product/Beispielmarke-Girls+Elodie+Jacket-9000082/"
        band = "https://www.otto.de/p/beastie-boys-shirt-C9000075/"
        damen = "https://www.otto.de/p/beispielmarke-damen-slim-fit-jeans-C9000049/"
        self.assertGreater(len(girls), 80)          # a long link is shortened in the sentence, never in the button
        self.assertEqual(self.add(f"{kids}\n{girls}\n{band}\n{damen}\n{self.LINKS['hirmer'][0]}"), [
            f"“{kids}” is not added yet. Its name says “kids”: this may be a children's product. Add it anyway?",
            f"“{girls[:79]}…” is not added yet. Its name says “girls”: this may be a children's product. Add it anyway?",
            f"“{band}” is not added yet. Its name says “boys”: this may be a children's product. Add it anyway?",
            f"“{damen}” is not added yet. Its name says “damen”: this may be a women's product. Add it anyway?",
            "Added “Oxford hemd regular fit hellblau”: only the link could be read — add the price, fabric and sizes "
            "under “Add details”."])
        self.assertEqual(manual_ids(), ["hirmer-9000001"], "nothing he was asked about is added before his answer")
        # Each question has its own button, which sends that one link (whole, not shortened) with the answer yes.
        answer = self.client.post(f"/slot/{self.sid}/import", data={"urls": f"{girls}\n{band}"})
        self.assertEqual([link for _, link in self.asked_after(answer)], [girls, band])
        # One tap on "Add it anyway": added, like any other link.
        self.assertEqual(self.add_anyway(band), ["Added “Beastie boys shirt”: only the link could be read — add the "
                                                 "price, fabric and sizes under “Add details”."])
        self.assertEqual(manual_ids(), ["hirmer-9000001", "otto-9000075"])
        # The other question of that paste is asked again after the tap, not dropped without a word: its button
        # carries it along. (It vanished: the girls' jacket was neither added nor asked about any more.)
        answer = self.client.post(f"/slot/{self.sid}/import", data={"urls": f"{girls}\n{kids}"})
        page = self.client.get(f"/slot/{self.sid}").get_data(as_text=True)
        kids_form = re.search(r'<form class="flash ask"[^>]*>(?:(?!</form>).)*?name="urls" value="' + re.escape(kids)
                              + r'".*?</form>', page, re.S).group(0)
        self.assertIn(f'<input type="hidden" name="still" value="{html.escape(girls)}">', kids_form)
        self.client.post(f"/slot/{self.sid}/import", data={"urls": kids, "anyway": "1", "still": girls})
        self.assertIn("bergfreunde-9000081", manual_ids())
        self.assertEqual([link for _, link in self.asked()], [girls], "the other question vanished")
        # He is not asked twice: pasting the link again, once it is on this piece, adds it as before.
        self.assertRegex(self.add(band)[0], "^Added “Beastie boys shirt”")
        self.assertRegex(self.add(girls)[0], "Add it anyway\\?$", "another link is still asked about")

    def test_the_question_never_opens_what_the_store_says_plainly(self):
        # A women's or children's folder, or the saved page's own word, is refused, with the answer yes too.
        women = "https://www.tom-tailor.de/damen/jacken/steppjacke-1041235_10668"
        refused = [f"Not added: “{women}” looks like a women's product, and Stilsmith is for menswear only."]
        self.assertEqual(self.add(women), refused)
        self.assertEqual(self.add_anyway(women), refused)
        hoodie = "https://www.blue-tomato.com/de-DE/product/beispielmarke-kapuzenpullover-9000003/"
        refused = [f"Not added: “{hoodie}” looks like a children's product, and Stilsmith is for menswear only."]
        self.assertEqual(self.add_anyway(hoodie, page("kids-hoodie.html")), refused)
        self.assertEqual([c for c in catalog.stored()["candidates"] if c.get("source") == "manual"], [])

    def test_the_question_says_where_the_word_is_and_that_a_saved_page_was_not_kept(self):
        # The word stands in a folder that also holds other words, not in the product's name: "Its link says".
        link = "https://www.otto.de/damen-jacken/beispielmarke-steppjacke-C9000099/"
        self.assertEqual(self.add(link), [f"“{link}” is not added yet. Its link says “damen”: this may be a women's "
                                          "product. Add it anyway?"])
        # With a page he saved that does not say whom the product is for: it cannot be kept while he is asked, and
        # that is said.
        band = "https://www.hirmer.de/beastie-boys-shirt/p/9000001"
        self.assertEqual(self.add(band, page("says-nothing.html")), [
            f"“{band}” is not added yet. Its name says “boys”: this may be a children's product. Add it anyway? "
            "The page you saved was not kept: once the link is added, send it again with the link."])
        self.assertEqual([c for c in catalog.stored()["candidates"] if c.get("source") == "manual"], [])

    def test_a_saved_page_filed_under_mens_needs_no_question(self):
        # The page he saved shows the store filing the product under "Herren": the store says it plainly, so a
        # word in the product's name is not asked about, and what the page says is read at once.
        band = "https://www.hirmer.de/beastie-boys-shirt/p/9000001"
        self.assertTrue(menswear.filed_for_men("Herren > Hemden"))
        self.assertFalse(menswear.filed_for_men("Unisex > Hoodies") or menswear.filed_for_men("Hemden", None))
        self.assertEqual(self.add(band, page("mens-shirt.html")), [
            "Added “Oxford-Hemd Regular Fit”: its name, price, colour and fabric were read from the page you saved — "
            "add the sizes under “Add details”."])
        self.assertEqual(self.asked(), [])
        # A page that files it under children's is refused as before, whatever the name says.
        kids = "https://www.blue-tomato.com/de-DE/product/marke-kids-kapuzenpullover-9000003/"
        self.assertEqual(self.add(kids, page("kids-hoodie.html")),
                         [f"Not added: “{kids}” looks like a children's product, and Stilsmith is for menswear only."])

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
                          "the fabric and sizes under “Add details”. Check the kind: its name says “Chinos”, and this "
                      "piece is “Shirt”. If it belongs to another piece, remove it here and paste the link there."])

    def test_a_saved_page_whose_breadcrumbs_say_women_or_children_is_refused(self):
        # Neither link says whom the product is for; the page does.
        jacket = "https://www.bergfreunde.de/beispielmarke-steppjacke-9000002/"
        hoodie = "https://www.blue-tomato.com/de-DE/product/beispielmarke-kapuzenpullover-9000003/"
        self.assertIsNone(menswear.link_not_for_men(jacket) or menswear.link_not_for_men(hoodie))
        self.assertEqual(self.add(jacket, page("womens-jacket.html")),
                         [f"Not added: “{jacket}” looks like a women's product, and Stilsmith is for menswear only."])
        self.assertEqual(self.add(hoodie, page("kids-hoodie.html")),
                         [f"Not added: “{hoodie}” looks like a children's product, and Stilsmith is for menswear only."])
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
        self.assertIn("Paste product page addresses from COS, Weekday, Tom Tailor, OTTO, Hirmer, Breuninger, Blue Tomato, "
                      "Bergfreunde or JD Sports, one per line. Menswear only. Stilsmith does not open the page:", text)
        self.assertIn('enctype="multipart/form-data"', section)
        self.assertIn('<input type="file" name="page" accept=".html,.htm,text/html" aria-describedby="page-help">', section)
        self.assertIn("The product's page, saved from your browser (optional)", text)
        # Promised only where the page states them: a page may carry no such data.
        self.assertIn("Its name, price, colour and fabric are filled in where the page states them.", text)
