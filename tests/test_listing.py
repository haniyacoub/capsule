"""The generic listing reader (wardrobe/collect/listing.py) on invented category pages, one for each way a store's page
can carry its products: schema.org data, microdata, Next.js data (both kinds), React Router's streamed data, a script's
own object, and the JSON a page fetched while it loaded. Names, prices, numbers and addresses are made up."""
import json
import unittest

from wardrobe.collect import listing, pages, readers
from wardrobe.collect.browser import Blocked

BASE = "https://www.musterhaus.example"


def script(kind: str, data) -> str:
    return f'<script type="{kind}">{json.dumps(data)}</script>'


def page(*parts: str, filler: int = 20_000) -> str:
    """A page with the given parts in its body, and enough else to be the size of a real one."""
    return "<html><head><title>Herren</title></head><body>" + "".join(parts) + "<p>" + "x" * filler + "</p></body></html>"


SCHEMA = script("application/ld+json", {"@context": "https://schema.org", "@type": "ItemList", "itemListElement": [
    {"@type": "ListItem", "position": 1, "item": {
        "@type": "Product", "name": "Oxford-Hemd", "url": "/p/oxford-hemd-100001.html", "color": "Hellblau",
        "material": "100% Baumwolle", "image": ["https://img.musterhaus.example/100001.jpg"],
        "offers": {"@type": "Offer", "price": "49.95", "priceCurrency": "EUR",
                   "availability": "https://schema.org/InStock"}}},
    {"@type": "ListItem", "position": 2, "item": {
        "@type": "Product", "name": "Popeline-Hemd", "url": "/p/popeline-hemd-100002.html", "color": "Weiß",
        "image": "//img.musterhaus.example/100002.jpg",
        "offers": {"@type": "Offer", "price": "39.95", "priceCurrency": "EUR",
                   "availability": "https://schema.org/OutOfStock"}}}]})

MICRODATA = """
<div itemscope itemtype="https://schema.org/Product"><meta itemprop="name" content="NORDFADEN T-Shirt NF4711/02">
  <meta itemprop="sku" content="P200001"><span itemprop="brand" itemscope itemtype="https://schema.org/Brand">
  <meta itemprop="name" content="NORDFADEN"></span>
  <span itemprop="offers" itemscope itemtype="https://schema.org/Offer"><meta itemprop="price" content="29.9">
  <meta itemprop="priceCurrency" content="EUR"><link itemprop="url" href="/nordfaden-t-shirts-200001"></span>
  <a href="/nordfaden-t-shirts-200001"><img alt="T-Shirt, Baumwolle, dunkelblau" src="https://cdn.example/200001.jpg"></a>
</div>"""


def next_data(products, carousel=()) -> str:
    return ('<script id="__NEXT_DATA__" type="application/json">'
            + json.dumps({"props": {"pageProps": {"grid": {"hits": products}, "recentlyViewed": list(carousel)}}})
            + "</script>")


TEE = {"id": "300001001", "productName": "T-Shirt in Regular Fit", "url": "/p/300001001.html",
       "prices": [{"price": 9.99, "priceType": "redPrice"}, {"price": 12.99, "priceType": "whitePrice"}],
       "colorName": "Schwarz", "colorCode": "1B1B1B", "images": [{"url": "https://img.example/300001001.jpg"}],
       "sizes": [{"label": "S", "stock": 2}, {"label": "M", "stock": 0}],
       "swatches": [{"articleId": "300001001", "colorName": "Schwarz", "url": "/p/300001001.html"},
                    {"articleId": "300001002", "colorName": "Weiß", "colorCode": "FFFFFF", "url": "/p/300001002.html",
                     "productImage": "https://img.example/300001002.jpg"}]}


def tee(n: int, colour: str = "Grau") -> dict:
    return {"id": f"30000{n}001", "productName": f"T-Shirt Nummer {n}", "url": f"/p/30000{n}001.html",
            "prices": [{"price": 10.0 + n}], "colorName": colour, "images": [{"url": f"https://img.example/{n}.jpg"}]}


class ReadingTheGrid(unittest.TestCase):
    def test_schema_org_products_with_their_offers(self):
        found = listing.parse_listing(page(SCHEMA), BASE, (), "musterhaus")
        self.assertEqual([i["name"] for i in found], ["Oxford-Hemd", "Popeline-Hemd"])
        shirt = found[0]
        self.assertEqual((shirt["store"], shirt["sku"], shirt["price"], shirt["colour"]),
                         ("musterhaus", "100001", 49.95, "Hellblau"))
        self.assertEqual(shirt["url"], BASE + "/p/oxford-hemd-100001.html")
        self.assertEqual(shirt["composition_text"], "100% Baumwolle", "the fibres with their shares count as stated")
        self.assertEqual(found[1]["image_url"], "https://img.musterhaus.example/100002.jpg")
        self.assertFalse(found[1]["in_stock"])

    def test_microdata_with_the_colour_and_fabric_its_picture_names(self):
        found = listing.parse_listing(page(MICRODATA), BASE, (), "musterhaus")
        self.assertEqual(len(found), 1)
        t = found[0]
        self.assertEqual((t["name"], t["sku"], t["price"], t["colour"]),
                         ("Nordfaden T-Shirt", "P200001", 29.9, "dunkelblau"),
                         "in ordinary letters, without its article code")
        self.assertEqual(t["url"], BASE + "/nordfaden-t-shirts-200001")
        self.assertEqual((t["composition_text"], t["fabric_words"]), ("", "Baumwolle"),
                         "a fibre named without its share is no composition")

    def test_embedded_json_keeps_the_grid_in_every_colour_and_not_the_carousel(self):
        grid = [TEE, tee(2), tee(3), tee(4)]
        found = listing.parse_listing(page(next_data(grid, carousel=[tee(8), tee(9)])), BASE, (), "musterhaus")
        skus = [i["sku"] for i in found]
        self.assertEqual(sorted(skus), sorted(["300001001", "300001002", "300002001", "300003001", "300004001"]))
        black = next(i for i in found if i["sku"] == "300001001")
        self.assertEqual((black["price"], black["price_before"], black["colour_hex"]), (9.99, 12.99, "#1B1B1B"))
        self.assertEqual((black["sizes_all"], black["sizes_in_stock"]), (["S", "M"], ["S"]))
        white = next(i for i in found if i["sku"] == "300001002")
        self.assertEqual((white["colour"], white["url"], white["image_url"]),
                         ("Weiß", BASE + "/p/300001002.html", "https://img.example/300001002.jpg"))
        self.assertIsNone(white["price"], "shown only as a swatch: no price of its own, never the first colour's")

    def test_a_colour_says_only_what_the_page_says_of_it(self):
        swatches = [{"articleId": "300001002", "colorName": "Weiß", "url": "/p/300001002.html", "price": 7.99},
                    {"articleId": "300001003", "colorName": "Beige", "url": "/p/300001003.html"}]
        first = {**TEE, "brandName": "Nordfaden", "swatches": swatches,
                 "images": [{"url": "https://img.example/black-front.jpg"}]}      # (a picture not by its number)
        grid = [first, tee(2), tee(3)]
        found = {i["sku"]: i for i in listing.parse_listing(page(next_data(grid)), BASE, (), "musterhaus")}
        self.assertEqual(found["300001002"]["price"], 7.99, "a price of its own is kept")
        self.assertIsNone(found["300001003"]["price"])
        for sku in ("300001002", "300001003"):
            self.assertEqual(found[sku]["image_url"], "", "no picture of its own: none, not the first colour's")
        self.assertEqual(found["300001001"]["brand"], "Nordfaden", "the brand, where the page names it")
        self.assertEqual(found["300002001"]["brand"], "")

    def test_the_colour_its_own_link_names(self):
        said = listing.link_colour
        olymp_like = BASE + "/Hemden/Casual/Kent/{}/p/40001/"
        self.assertEqual(said("Hemd", olymp_like.format("Bordeaux"), "Rot"), "Bordeaux",
                         "the link's one colour over the listing's broader family")
        self.assertEqual(said("Hemd", olymp_like.format("Off-White"), "White"), "Off-White")
        self.assertEqual(said("Hemd", olymp_like.format("Wei%C3%9F"), "Weiß"), "Weiß")
        self.assertEqual(said("Hemd", olymp_like.format("Schwarz-Braun"), "Braun"), "Braun", "two colours: not one")
        self.assertEqual(said("Hemd", olymp_like.format("Nougat"), "Braun"), "Braun", "one Stilsmith does not know")
        self.assertEqual(said("Hemd", BASE + "/p/40001/", "Rot"), "Rot")
        named = BASE + "/p/l-s-nordfaden-shirt-salt-4711"
        self.assertEqual(said("L/S Nordfaden Shirt", named, ""), "Salt", "the words between its name and number")
        self.assertEqual(said("L/S Nordfaden Shirt", BASE + "/p/l-s-nordfaden-shirt-dark-fir-4712", ""), "Dark Fir")
        self.assertEqual(said("L/S Nordfaden Shirt", named, "Schwarz"), "Schwarz", "only where the listing says none")
        self.assertEqual(said("Nordfaden Sakko", BASE + "/nordfaden-sakko-beige-4711-0815", ""), "Beige")
        self.assertEqual(said("L/S Nordfaden Shirt", BASE + "/p/l-s-nordfaden-shirt-black-white-4713", ""), "",
                         "two colours are not one colour")
        self.assertEqual(said("Nordfaden Sakko", BASE + "/nordfaden-sakko-4711x-0815", ""), "")

    def test_newer_nextjs_flight_data(self):
        rows = json.dumps([tee(n) for n in range(1, 5)])
        flight = "".join(f'<script>self.__next_f.push([1,{json.dumps(chunk)}])</script>'
                         for chunk in (f"1a:{{\"items\":{rows[:40]}", f"{rows[40:]}}}\n"))
        self.assertEqual(len(listing.parse_listing(page(flight), BASE, (), "s")), 4)

    def test_a_scripts_own_object_and_links_found_by_article_number(self):
        state = {"search": {"products": [
            {"sku": f"40000{n}", "name": f"Sneaker {n}", "price": {"value": 99.99}, "originalPrice": {"value": 120},
             "images": [{"url": f"https://img.example/40000{n}"}],
             "baseOptions": [{"selected": {"style": "Black-Black" if n % 2 else "Black-White"}}]} for n in range(1, 4)]}}
        links = "".join(f'<a href="/product/sneaker-{n}/40000{n}.html">x</a>' for n in range(1, 4))
        html = page(f"<script>window.store = {{ STATE: {json.dumps(state)} }};</script>", links)
        found = listing.parse_listing(html, BASE, (), "s")
        self.assertEqual([i["url"] for i in found], [f"{BASE}/product/sneaker-{n}/40000{n}.html" for n in range(1, 4)])
        self.assertEqual([i["colour"] for i in found], ["Black", "Black / White", "Black"])
        self.assertEqual(found[0]["price_before"], 120)

    def test_a_sale_price_with_its_old_price_written_out(self):
        rows = [{**tee(n), "originalFormattedPrice": "39,95 €"} for n in range(1, 4)]
        found = listing.parse_listing(page(next_data(rows)), BASE, (), "s")
        self.assertEqual([(i["price"], i["price_before"]) for i in found], [(10.0 + n, 39.95) for n in range(1, 4)])

    def test_react_routers_streamed_data(self):
        flat = [{"_1": 2}, "products", [3], {"_4": 5, "_6": 7, "_8": 9, "_10": 11}, "title", "Wollhose",
                "priceRange", {"_12": 13}, "id", "gid://shopify/Product/555001", "color", {"_14": 15},
                "minVariantPrice", {"_16": 17}, "value", "Grau", "amount", "149.0"]
        stream = f'<script>window.__reactRouterContext.streamController.enqueue({json.dumps(json.dumps(flat))});</script>'
        links = '<a href="/de-de/herren/hosen/graue-wollhose/555001.html">x</a>'
        found = listing.parse_listing(page(stream, links), BASE, (), "s")
        self.assertEqual([(i["name"], i["price"], i["colour"], i["sku"]) for i in found],
                         [("Wollhose", 149.0, "Grau", "555001")])

    def test_the_json_the_page_fetched_when_the_page_itself_holds_no_products(self):
        answer = {"data": {"products": [tee(n) for n in range(1, 6)]}}
        found = listing.parse_listing(page(""), BASE, [answer, {"recommendations": [tee(7)]}], "s")
        self.assertEqual(len(found), 5)

    def test_a_womens_product_beside_the_mens_grid_is_left_out(self):
        women = {**tee(5), "url": "/damen/p/300005001.html"}
        found = listing.parse_listing(page(next_data([tee(1), tee(2), tee(3), women])), BASE, (), "s")
        self.assertEqual(len(found), 3)


class FakeSession:
    def __init__(self, html, landed=None, fetched=()):
        self.html, self.landed, self.fetched = html, landed, list(fetched)

    def fetch_listing(self, store, base, url):
        return self.html, self.fetched, self.landed or url


class WhatAPageCanDoInstead(unittest.TestCase):
    def test_an_almost_empty_page_is_a_refusal(self):
        for html in ("<html><body></body></html>", "<html><body>" + "<script>check()</script>" * 100 + "</body></html>"):
            with self.assertRaises(Blocked):
                readers.read_page(FakeSession(html), "s", BASE, BASE + "/men/t-shirts", listing)

    def test_a_big_page_without_products_is_not(self):
        items, _ = readers.read_page(FakeSession(page("<p>Keine Produkte</p>")), "s", BASE, BASE + "/men/x", listing)
        self.assertEqual(items, [])

    def test_a_category_that_opens_the_home_page_has_moved(self):
        with self.assertRaises(readers.Moved):
            readers.read_page(FakeSession(page(SCHEMA), landed=BASE + "/de-de/"), "s", BASE, BASE + "/de-de/men/tees/",
                              listing)
        self.assertFalse(readers.moved(BASE + "/men/tees", BASE + "/men/tees/?sort=new"))
        self.assertFalse(readers.moved(BASE + "/men/tees/", BASE + "/Men/Tees"))
        self.assertFalse(readers.moved(BASE + "/men/tees", BASE + "/de_de/men/tees"), "below a language folder")
        self.assertFalse(readers.moved(BASE + "/men/tees", BASE + "/men/tees/basic"))

    def test_a_category_that_opens_another_category_beside_it_has_moved(self):
        # Its products would be sorted as the garments of the page asked for: the oversize shirts' address opened the
        # T-shirts, and its T-shirts were sorted as shirts. It is an address to fix.
        self.assertTrue(readers.moved(BASE + "/men/shirts/oversize", BASE + "/men/t-shirts"))
        self.assertTrue(readers.moved(BASE + "/men/tees", BASE + "/men/t-shirts-and-tops"))
        with self.assertRaises(readers.Moved):
            readers.read_page(FakeSession(page(SCHEMA), landed=BASE + "/men/t-shirts"), "s", BASE,
                              BASE + "/men/shirts/oversize", listing)

    def test_the_next_page_by_its_rel_next_link(self):
        html = '<link rel="next" href="/men/tees?p=2"><a href="/men/tees?p=1">1</a>'
        self.assertEqual(pages.next_page_url(html, BASE + "/men/tees"), BASE + "/men/tees?p=2")
        self.assertIsNone(pages.next_page_url('<link rel="next" href="https://other.example/x">', BASE + "/men/tees"))
        self.assertEqual(pages.next_page_url('<a href="?page=2">2</a>', BASE + "/men/tees"), BASE + "/men/tees?page=2")


class PagesThatAreNotFound(unittest.TestCase):
    def test_a_page_not_found_said_in_an_ordinary_page_is_an_address_to_fix(self):
        from wardrobe.collect.browser import PageMissing
        html = page("<h1>Die gesuchte Seite wurde leider nicht gefunden</h1>")
        with self.assertRaises(PageMissing):
            readers.read_page(FakeSession(html), "s", BASE, BASE + "/men/old-address", listing)


class PullAndBearsOwnReader(unittest.TestCase):
    """Pull&Bear's list comes as the product data its page fetches: colours, each with its sizes and their prices in
    cents, fibres with their shares and pictures (invented values in that shape)."""

    ANSWER = {"products": [{"id": 900001, "name": "Basic T-Shirt", "productUrl": "basic-tshirt-l0001",
                            "bundleProductSummaries": [{"id": 900002, "productUrl": "basic-tshirt-l0001", "detail": {
                                "colors": [
                                    {"id": "250", "name": "Weiss", "composition": [{"part": "1", "composition": [
                                        {"name": "baumwolle", "percentage": "100"}]}],
                                     "sizes": [{"name": "S", "price": "999", "oldPrice": "1299", "isBuyable": True},
                                               {"name": "M", "price": "999", "oldPrice": "1299", "isBuyable": False}]},
                                    {"id": "800", "name": "Schwarz", "sizes": [{"name": "M", "price": "999"}]}],
                                "xmedia": [{"path": "/250", "xmediaItems": [{"medias": [{"extraInfo": {
                                    "deliveryUrl": "https://static.example/250.jpg"}}]}]}]}}]}]}

    def test_every_colour_with_its_sizes_and_fabric(self):
        from wardrobe.collect import pullandbear
        white, black = pullandbear.parse_listing("", "https://www.pullandbear.com", [self.ANSWER])
        self.assertEqual((white["sku"], white["price"], white["price_before"], white["colour"]),
                         ("l0001-250", 9.99, 12.99, "Weiss"))
        self.assertEqual((white["sizes_all"], white["sizes_in_stock"]), (["S", "M"], ["S"]))
        self.assertEqual(white["composition_text"], "100% Baumwolle")
        self.assertEqual(white["url"], "https://www.pullandbear.com/de/basic-tshirt-l0001?cS=250")
        self.assertEqual(white["image_url"], "https://static.example/250.jpg")
        self.assertEqual((black["colour"], black["in_stock"]), ("Schwarz", False))
        self.assertIs(readers.reader("pull-and-bear"), pullandbear)

    def test_one_article_under_two_product_numbers_is_one_product(self):
        """Pull&Bear lists an article once for each bundle it belongs to: the same link and colour, another number."""
        from wardrobe.collect import pullandbear
        bundle = self.ANSWER["products"][0]
        again = {**bundle, "id": 900077, "bundleProductSummaries": [
            {**bundle["bundleProductSummaries"][0], "id": 900078}]}
        doubled = {"id": "250", "name": "Weiss", "sizes": [{"name": "S", "price": "999", "isBuyable": True}] * 2}
        twice = {**bundle, "id": 900099, "productUrl": "other-tshirt-l0002", "bundleProductSummaries": [
            {"id": 900100, "productUrl": "other-tshirt-l0002", "detail": {"colors": [doubled]}}]}
        found = pullandbear.parse_listing("", "https://www.pullandbear.com",
                                          [{"products": [bundle, again, twice]}])
        self.assertEqual(sorted(p["sku"] for p in found), ["l0001-250", "l0001-800", "l0002-250"])
        self.assertEqual(next(p for p in found if p["sku"] == "l0002-250")["sizes_all"], ["S"], "each size once")


class ColoursListedWithTheProduct(unittest.TestCase):
    def test_the_product_among_its_own_colours_and_a_colour_in_its_link(self):
        # (OLYMP's shape, invented values: each product lists the colours of its article, its own among them, and
        # its link names its colour)
        products = [{"code": f"5000{n}L", "title": f"Polo Nummer {n}", "price": {"value": 59.95},
                     "url": f"/Polos/Casual/Marine/p/5000{n}/",
                     "prvMainImages": [{"key": "product", "value": {"url": f"/medias/5000{n}-main.jpeg?context=x"}}],
                     "otherColorsFromSolr": [
                         {"code": f"5000{n}", "colorName": "Marine", "colorHex": "1f2a44", "productUrl": f"/p/5000{n}/"},
                         {"code": f"6000{n}", "colorName": "Weiß", "colorHex": "ffffff", "productUrl": f"/p/6000{n}/",
                          "imageUrl": f"/medias/6000{n}-main.jpeg?context=x"}]} for n in range(1, 4)]
        pictures = "".join(f'<img src="https://api.musterhaus.example/medias/5000{n}-main.jpeg?context=x">'
                           for n in range(1, 4))
        found = listing.parse_listing(page(pictures), BASE, [{"products": products}], "s")
        first = next(i for i in found if i["sku"] == "50001L")
        self.assertEqual((first["colour"], first["colour_hex"]), ("Marine", "#1F2A44"), "its own colour, from its list")
        self.assertEqual(first["image_url"], "https://api.musterhaus.example/medias/50001-main.jpeg?context=x",
                         "a picture given by its path, from where the page loads it")
        white = next(i for i in found if i["sku"] == "60001")
        self.assertEqual((white["colour"], white["url"]), ("Weiß", BASE + "/p/60001/"))
        self.assertIsNone(white["price"], "a colour listed without a price of its own has none")
        self.assertEqual(len(found), 6, "each colour once")
        bare = [{**p, "otherColorsFromSolr": [], "code": p["code"] + "X"} for p in products]
        self.assertEqual({i["colour"] for i in listing.parse_listing(page(""), BASE, [{"products": bare}], "s")},
                         {"Marine"}, "else the colour its link names")
