"""Visitors without an account (guests.py, config/site.toml): an open door to one example wardrobe.

Most websites open without an account. On Stilsmith's public site a visitor opens Outfits and swipes through the
outfits of one example wardrobe, the same for every visitor; he taps a piece to see what it is, and sees an outfit's AI
picture where one has been drawn already. The stores, prices, links and the stores' photos are left out on the server,
not hidden in the browser: grey bars and one line per outfit stand in their place. Everything that would change or
save something leads to "Create your account", saying why. Nothing a visitor does is written down.

These run in production mode on a small published list of products shaped as COS's and Weekday's were on 11 Nov (the
products themselves are invented), so that there are store names, prices, links and photos to leave out.
"""
import json
import re
import sqlite3
from contextlib import closing, redirect_stderr
from html import unescape
from io import StringIO
from unittest import mock
from urllib.parse import parse_qs, urlsplit

from wardrobe import config, db, guests, looks, mail, outfits, paths, person, programmes, selection, settings, shared
from wardrobe import videos
from wardrobe import profile as profile_mod
from wardrobe.app import PUBLIC, create_app
from wardrobe.config import ConfigError

from .test_looks import PICTURE, WithPictures
from .test_production import HX, PASSWORD, ProductionCase, words
from .test_programmes import PUBLISHED, STORES, shaped

# Two of each for nine of the example plan's pieces, the dearer at COS: enough for many outfits at the price level
# Medium, each piece with a store, a name, a price, a link and a photo that must not reach a visitor.
LIST = [
    shaped("cos", "2000000101", "T-Shirt aus schwerem Baumwolljersey", 35.0, "Weiß", "tee"),
    shaped("weekday", "2000000201", "Standard T-Shirt", 25.0, "Weiß", "tee"),
    shaped("cos", "2000000102", "Oxford-Hemd", 69.0, "Weiß", "shirt"),
    shaped("weekday", "2000000202", "Hemd aus Oxford", 45.0, "Weiß", "shirt"),
    shaped("cos", "2000000103", "Pullover aus Merinowolle", 89.0, "Grau", "knit"),
    shaped("weekday", "2000000203", "Pullover aus Wollmischung", 59.0, "Grau", "knit"),
    shaped("cos", "2000000104", "Gerade Jeans", 85.0, "Blau", "jeans"),
    shaped("weekday", "2000000204", "Space Jeans", 60.0, "Blau", "jeans", sizes=["31/32", "32/32", "33/32"]),
    shaped("cos", "2000000105", "Hose aus Wolle", 115.0, "Grau", "trousers"),
    shaped("weekday", "2000000205", "Anzughose aus Wollmischung", 70.0, "Grau", "trousers"),
    shaped("cos", "2000000106", "Blazer aus Wolle", 225.0, "Marineblau", "blazer"),
    shaped("weekday", "2000000206", "Einreihiger Blazer", 120.0, "Marineblau", "blazer"),
    shaped("cos", "2000000107", "Mantel aus Wolle", 290.0, "Dunkelgrau", "coat"),
    shaped("weekday", "2000000207", "Mantel aus Wollmischung", 160.0, "Dunkelgrau", "coat"),
    shaped("cos", "2000000108", "Derby-Schuhe aus Leder", 150.0, "Dunkelbraun", "shoes"),
    shaped("weekday", "2000000208", "Loafer aus Leder", 110.0, "Dunkelbraun", "shoes"),
    shaped("cos", "2000000109", "Sneaker aus Leder", 120.0, "Weiß", "sneakers"),
    shaped("weekday", "2000000209", "Ledersneaker", 90.0, "Weiß", "sneakers"),
]
LOCK = "Create a free account to see the stores, prices and links."
LINKS = re.compile(r'(?:href|src|hx-get)="(/[^"]*)"')


def everything_in(path=None) -> list[str]:
    """Every row of every table, as SQL: what "nothing was written" is checked against."""
    with closing(sqlite3.connect(path or paths.DB_PATH)) as con:
        return list(con.iterdump())


def rows(table: str) -> int:
    with closing(sqlite3.connect(paths.DB_PATH)) as con:
        return con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]   # nosec B608 - the tests' own table names


def slides(page: str) -> list[str]:
    """Each outfit of a page, as its part of the HTML."""
    return re.findall(r'<article class="slide" id="outfit-\w+".*?</article>', page, re.S)


class GuestCase(ProductionCase):
    """A public site with a published list, started after it was published (as after a restart)."""

    def setUp(self):
        super().setUp()
        (paths.DATA_DIR / shared.POOL_NAME).write_text(json.dumps(
            {"published_at": PUBLISHED, "collected_at": "2026-11-11T17:00:18+01:00", "stores": STORES,
             "products": LIST}, ensure_ascii=False), encoding="utf-8")
        self.app = create_app()         # the start-up brings the example wardrobe onto the published list
        self.visitor = self.app.test_client()

    def page(self, url, client=None) -> str:
        response = (client or self.visitor).get(url)
        self.assertEqual(response.status_code, 200, url)
        return response.get_data(as_text=True)

    def left_out(self, page: str, where: str, stores: bool = True) -> None:
        """Nothing of the stores in a page a visitor can reach: no price, no address of another site, none of the
        products' photos, links, names or ids. `stores`: an outfit or a piece, which names no store either
        (programmes.OFFERED), says nothing of sizes or of what a yes would add, and offers nothing to draw."""
        self.assertNotIn("€", page, where)
        self.assertIsNone(re.search(r"https?:|//[\w.-]+\.\w", page), f"{where}: an address of another site")
        for product in LIST:
            for value in (product["image_url"], product["url"], product["id"], product["name"]):
                self.assertNotIn(value, page, f"{where}: {value}")
        if not stores:
            return
        for name in programmes.OFFERED.values():
            self.assertIsNone(re.search(rf"\b{re.escape(name)}\b", page), f"{where}: the store {name}")
        for word in ("new piece", "already in your wardrobe", "Your size", "example size", "Open at", "Buy this outfit",
                     "csrf_token", "See it worn", "More photos", "See it move", "Draw again"):
            self.assertNotIn(word, page, where)


class TheOpenDoor(GuestCase):
    def test_a_visitor_explores_the_outfits_of_an_example_wardrobe(self):
        landing = self.page("/")
        cta = re.search(r'<p class="hero-cta">(.*?)</p>', landing, re.S).group(1)
        self.assertEqual(re.findall(r'<a class="([^"]*)" href="([^"]*)">([^<]*)</a>', cta),
                         [("btn", "/outfits", "Explore outfits"), ("btn ghost", "/signup", "Create a free account")],
                         "one main button, Explore outfits, beside Create a free account")
        self.assertIn("No account needed to look around.", words(landing))
        page = self.page("/outfits")
        nav = re.search(r'<header class="top">(.*?)</header>', page, re.S).group(1)
        self.assertEqual(re.findall(r'<a class="btn[^"]*" href="([^"]*)">([^<]*)</a>', nav),
                         [("/login", "Log in"), ("/signup", "Create account")], "the header for a visitor")
        for customer in ('class="tabs"', 'id="summary"', "account-link", "My outfits", "Set a budget"):
            self.assertNotIn(customer, page)
        found = slides(page)
        self.assertGreaterEqual(len(found), 3, "outfits to swipe through")
        with db.as_user(guests.example_id()):
            plan = {slot["id"]: slot for slot in db.list_slots()}
        for outfit in found:
            # Its title, its pieces by their names, one line about an account with the way to create one, and the two
            # answers, which lead to "Create your account" saying why.
            self.assertRegex(outfit, r"<h2>(Everyday|Office|Smart casual)")
            names = re.findall(r'<span class="piece-text"><b>([^<]+)</b>', outfit)
            self.assertGreaterEqual(len(names), 3)
            for slot_id in re.findall(r'slot=([\w-]+)"', outfit):
                self.assertIn(slot_id, plan, "only the example plan's pieces")
            self.assertEqual(words(outfit).count(LOCK), 1, "one line per outfit")
            self.assertEqual(re.findall(r'href="(/signup[^"]*)"[^>]*>\s*(?:<svg.*?</svg>\s*)?<span>Add to my wardrobe',
                                        outfit, re.S), ["/signup?why=save"])
            self.assertIn('href="/signup?why=no" id="no-', outfit)
            # The pieces as the app draws them, in the plan's colours: no store's photo.
            pictures = re.findall(r'<img src="([^"]+)"', outfit)
            self.assertTrue(pictures)
            for src in pictures:
                self.assertRegex(unescape(src), r"^/mock/img/[a-z]+\.svg\?c=[0-9a-fA-F]{6}&ground=0$")
            drawing = self.visitor.get(unescape(pictures[0]))
            self.assertEqual(drawing.mimetype, "image/svg+xml")
            self.assertNotIn("<rect", drawing.get_data(as_text=True), "on the box's own ground, not a photo's")
            # Grey bars where the stores, the products' names and the prices would be, not the words blurred.
            self.assertEqual(outfit.count('class="row-product veiled" aria-hidden="true"><i class="blur-bar'),
                             len(names))
            self.assertEqual(outfit.count('class="piece-price veiled" aria-hidden="true"><i class="blur-bar'),
                             len(names))
        self.assertIn("from an example wardrobe", words(page))
        for occasion in ("all", "everyday", "office"):
            self.assertTrue(slides(self.page(f"/outfits?occasion={occasion}")), occasion)
        self.assertEqual(self.visitor.get("/outfits?occasion=saved").headers["Location"], "/signup?why=save",
                         "My outfits are his own: his account comes first")

    def test_a_tap_on_a_piece_says_what_it_is(self):
        page = self.page("/outfits")
        first = slides(page)[0]
        url = unescape(re.search(r'hx-get="(/outfits/piece\?[^"]*)"', first).group(1))
        slot_id = parse_qs(urlsplit(url).query)["slot"][0]
        pop_up = self.visitor.get(url, headers=HX)
        self.assertEqual(pop_up.status_code, 200)
        said = pop_up.get_data(as_text=True)
        with db.as_user(guests.example_id()):
            view = selection.build().get(slot_id)
        name = unescape(re.search(r'<h2 id="piece-title">([^<]+)</h2>', said).group(1))
        listed = re.search(rf'title="([^"]+)"\s+hx-get="[^"]*slot={slot_id}"', first).group(1)
        self.assertEqual(name, unescape(listed), "the piece's own name, as the outfit lists it")
        self.assertTrue(name.lower().startswith(view.colour.label.lower()), name)
        self.assertIn(f"Colour: {view.colour.label.lower()}", words(said))
        self.assertIn(LOCK, words(said))
        self.assertIn('href="/signup?why=shop">Create a free account</a>', said)
        self.left_out(said, url)
        for swap in ("Choose", "Swap it for", "Wear the", "Leave the", "Compare all", "Add one you found"):
            self.assertNotIn(swap, said)
        # Without JavaScript the piece is a link to "Create your account".
        self.assertRegex(first, r'<a class="tile" href="/signup\?why=shop" title="[^"]+"\s+hx-get="/outfits/piece')

    def test_stores_prices_links_and_photos_are_left_out_on_the_server(self):
        # Every page a visitor can reach from the landing page, followed link by link: each answers, and none holds a
        # price, an address of another site or any of the products' photos, links, names or ids; the outfits and the
        # pop-ups name no store either. (The landing page names the stores Stilsmith picks from, as it did before:
        # that is what the site is, not a product's store.) Nothing is written, no picture or video is asked for, and
        # no cookie is set, until the sign-up or log-in form, whose token needs one.
        before = everything_in()
        seen, todo, fetched = set(), ["/"], []
        while todo:
            url = todo.pop(0)
            parts = urlsplit(url)
            query = parse_qs(parts.query)
            # One shuffle, each piece's pop-up once, and the rest of the row page by page: a page is known by what
            # it shows, not by the random number of its shuffle.
            known = (parts.path, tuple(sorted((k, v[0] if k != "seed" else "") for k, v in query.items()
                                              if k not in ("front", "at"))))
            if known in seen or parts.path.startswith("/static/") or parts.path == "/favicon.ico" \
                    or int(query.get("n", ["12"])[0]) > 24:
                continue
            seen.add(known)
            response = self.visitor.get(url, headers=HX if parts.path == "/outfits/piece" else {})
            fetched.append(url)
            self.assertEqual(response.status_code, 200, url)
            if parts.path not in ("/signup", "/login", "/forgot"):
                self.assertNotIn("Set-Cookie", response.headers, url)
            if response.mimetype != "text/html":
                self.assertIn(response.mimetype, ("image/svg+xml", "image/jpeg", "image/png"), url)
                continue
            page = response.get_data(as_text=True)
            self.left_out(page, url, stores=parts.path.startswith("/outfits"))
            todo += [unescape(link) for link in LINKS.findall(page)]
        visited = {urlsplit(url).path for url in fetched}
        self.assertTrue({"/", "/outfits", "/outfits/piece", "/signup", "/login", "/legal/privacy"} <= visited, visited)
        self.assertGreater(sum(1 for url in fetched if url.startswith("/outfits/piece")), 8, "the pop-ups")
        self.assertTrue(any("seed=" in url for url in fetched) and any("n=24" in url for url in fetched),
                        "a shuffle and the next outfits")
        self.assertEqual(everything_in(), before, "nothing a visitor reads is written down")
        self.assertEqual((rows("look_requests"), rows("video_requests"), rows("looks"), rows("videos")), (0, 0, 0, 0))

    def test_every_button_leads_to_sign_up_and_changes_nothing(self):
        # Every route that changes something, asked by a visitor without an account (with or without a page's token):
        # nothing happens, and he lands on "Create your account", which says why where the button is one he sees.
        # The Account page's own buttons (log out, a new password, deleting the account) are for someone whose login
        # ran out: they lead to "Log in", as before.
        before = everything_in()
        routes = [(rule.endpoint, rule.rule.replace("<slot_id>", "white-tee").replace("<int:step>", "2")
                   .replace("<token>", "x")) for rule in self.app.url_map.iter_rules()
                  if rule.methods & {"POST", "PUT", "PATCH", "DELETE"} and rule.endpoint not in PUBLIC
                  and not rule.endpoint.startswith("owner.")]
        self.assertGreater(len(routes), 25)
        for endpoint, url in routes:
            account = endpoint.startswith("auth.")
            plain = self.visitor.post(url, data={"want": "save", "key": "x"})
            by_script = self.visitor.post(url, headers=HX)
            if account:
                self.assertEqual((plain.status_code, plain.headers["Location"]), (302, "/login"), url)
                self.assertEqual((by_script.status_code, by_script.headers["HX-Redirect"]), (401, "/login"), url)
                continue
            self.assertEqual(plain.status_code, 302, url)
            to = plain.headers["Location"]
            self.assertTrue(to.startswith("/signup"), f"{url} leads to {to}")
            self.assertEqual((by_script.status_code, by_script.headers.get("HX-Redirect")), (401, to), url)
            self.assertNotIn("Set-Cookie", plain.headers, url)
            self.assertIn(endpoint, guests.BY_ENDPOINT, f"{url}: no line says why it needs an account")
            self.assertEqual(to, f"/signup?why={guests.BY_ENDPOINT[endpoint]}", url)
        for url, why in (("/outfits/save", "Create a free account to save outfits."),
                         ("/outfits/no", "Create a free account to hide the outfits you don't like."),
                         ("/slot/white-tee/pick", "Create a free account to swap pieces and choose products."),
                         ("/settings", "Create a free account to set your sizes, budget and price level."),
                         ("/profile", "Create a free account to set your sizes, budget and price level.")):
            to = self.visitor.post(url).headers["Location"]
            said = re.search(r'<p class="signup-why" role="status">([^<]*)</p>', self.page(to)).group(1)
            self.assertEqual(unescape(said), why, url)
        # The pages of the app stay pages to log in to; the owner's stay pages that do not exist.
        for url in ("/list", "/slots", "/profile", "/account", "/outfits/buy?at=x", "/slot/white-tee"):
            response = self.visitor.get(url)
            self.assertEqual((response.status_code, response.headers["Location"].split("?")[0]), (302, "/login"), url)
        self.assertEqual(self.visitor.get("/stores").status_code, 404)
        self.assertEqual(self.visitor.get("/signup?why=nonsense").get_data(as_text=True).count("signup-why"), 0,
                         "only Stilsmith's own lines, never words from the address")
        self.assertEqual(everything_in(), before)
        self.assertEqual((rows("look_requests"), rows("video_requests")), (0, 0))

    def test_the_line_about_pictures_promises_only_what_is_switched_on(self):
        def said(**on) -> str:
            with mock.patch.object(looks, "service", return_value=object() if on.get("pictures") else None), \
                    mock.patch.object(videos, "service", return_value=object() if on.get("videos") else None):
                page = self.page(self.visitor.post("/outfits/look").headers["Location"])
            found = re.search(r'<p class="signup-why" role="status">([^<]*)</p>', page)
            return unescape(found.group(1)) if found else ""
        self.assertEqual(said(pictures=True, videos=True),
                         "Create a free account for more photos and videos of the outfits.")
        self.assertEqual(said(pictures=True), "Create a free account for more photos of the outfits.")
        self.assertEqual(said(), "", "no AI pictures here: none promised")

    def test_an_example_wardrobe_nobody_can_use_or_change(self):
        example = guests.example_id()
        self.assertIsNotNone(example)
        user = db.get_user(example)
        self.assertEqual((user["email"], user["password_hash"]), (guests.EXAMPLE_EMAIL, ""))
        with db.as_user(example):
            self.assertEqual(profile_mod.load(), {**profile_mod.EXAMPLE}, "the example profile: its sizes, no photo")
            self.assertEqual(selection.build().mode, "medium", "the middle price level")
            self.assertIsNone(person.photo())
            self.assertEqual(selection.build().source, "collected", "its pieces from the published list")
        # Nobody logs in to it, gets a reset link for it, or signs up with its address.
        self.assertEqual(self.post(self.visitor, "/login", email=guests.EXAMPLE_EMAIL, password="").status_code, 401)
        self.assertEqual(self.post(self.visitor, "/login", email=guests.EXAMPLE_EMAIL, password=PASSWORD).status_code,
                         401)
        self.post(self.visitor, "/forgot", email=guests.EXAMPLE_EMAIL)
        self.assertEqual(mail.OUTBOX, [])
        self.assertEqual(self.post(self.visitor, "/signup", email=guests.EXAMPLE_EMAIL, password=PASSWORD).status_code,
                         400)
        # A visitor's request is read-only: SQLite itself refuses any write, and the next request is not.
        self.visitor.get("/outfits")
        self.assertFalse(db.is_read_only(), "nothing of a visitor's request is left for the next one")
        with self.assertRaises(RuntimeError):
            db.uid()
        with db.as_user(example):
            token = db.set_read_only(True)
            try:
                with self.assertRaises(sqlite3.OperationalError):
                    db.set_setting("mode", "top")
            finally:
                db.reset_read_only(token)
            self.assertEqual(db.get_setting("mode"), "medium")
        # Started again, it is still the same, and nothing is written.
        before = everything_in()
        create_app()
        self.assertEqual(everything_in(), before)
        self.assertEqual(guests.example_id(), example)

    def test_a_customer_with_the_examples_address_is_never_shown_to_visitors(self):
        # Should a customer have this address before the example wardrobe was made (with a password: his account),
        # his wardrobe is never the example: visitors are sent to log in, as before the door opened.
        for path in (paths.DB_PATH, paths.DATA_DIR / shared.POOL_NAME):
            path.unlink(missing_ok=True)
        db.init()
        db.create_user(guests.EXAMPLE_EMAIL, "a password hash")
        with redirect_stderr(StringIO()) as said:
            app = create_app()
        self.assertIn("cannot be the example wardrobe", said.getvalue())
        self.assertIsNone(guests.example_id())
        visitor = app.test_client()
        self.assertEqual(visitor.get("/outfits").headers["Location"], "/login?next=/outfits")
        self.assertNotIn("Explore outfits", visitor.get("/").get_data(as_text=True))

    def test_a_fault_in_the_example_never_keeps_the_site_from_starting(self):
        # Should setting up the example wardrobe fail at start-up (a typo in a config file, a locked database), the
        # site starts all the same: customers sign up and see their own outfits, and visitors are sent to log in, as
        # before the door opened, until a start-up sets it up.
        paths.DB_PATH.unlink(missing_ok=True)
        with mock.patch.object(guests.capsule, "propose", side_effect=RuntimeError("boom")), \
                redirect_stderr(StringIO()) as said:
            self.app = create_app()
        self.assertIn("the example wardrobe for visitors could not be set up (RuntimeError: boom)", said.getvalue())
        self.assertIsNone(guests.example_id())
        visitor = self.app.test_client()
        self.assertEqual(visitor.get("/outfits").headers["Location"], "/login?next=/outfits")
        self.assertNotIn("Explore outfits", self.page("/", visitor))
        ada = self.member("ada@example.com")
        self.assertIn('class="tabs"', self.page("/outfits", ada), "customers are not held up")
        self.app = create_app()         # the next start-up sets it up
        self.assertIsNotNone(guests.example_id())
        self.assertEqual(self.app.test_client().get("/outfits").status_code, 200)

    def test_a_customer_still_has_his_own_outfits(self):
        ada = self.member("ada@example.com")
        page = self.page("/outfits", ada)
        self.assertIn('class="tabs"', page)
        self.assertNotIn("Create a free account", page)
        self.assertNotIn("guest", re.search(r'<section class="looks[^"]*"', page).group(0))
        key = re.search(r'id="outfit-(\w+)"', page).group(1)
        self.assertEqual(self.post(ada, "/outfits/save", key=key, want="save").status_code, 302, "a yes is written")
        with db.as_user(self.user_id("ada@example.com")):
            self.assertEqual(len(db.list_saved()), 1)
        with db.as_user(guests.example_id()):
            self.assertEqual(db.list_saved(), [], "the example wardrobe is not his")


class TheSwitch(GuestCase):
    def closed(self, value):
        """config/site.toml as it reads with the door closed: `value` for `guests`, or an error (a broken file)."""
        load = config.load

        def site(name, check=None):
            if name != "site.toml":
                return load(name, check)
            if isinstance(value, Exception):
                raise value
            return {"guests": value}
        return mock.patch.object(config, "load", site)

    def test_guests_false_closes_the_door_as_before(self):
        self.assertTrue(guests.door_open(), "config/site.toml opens it")
        for value in (False, "true", ConfigError("config/site.toml has a syntax error")):
            with self.closed(value):
                self.assertFalse(guests.door_open(), value)
                landing = self.page("/")
                self.assertNotIn("Explore outfits", landing)
                self.assertIn('<a class="btn" href="/signup">Create a free account</a>', landing)
                # The app needs a login again, exactly as before the switch (test_production: the app needs a login).
                response = self.visitor.get("/outfits")
                self.assertEqual((response.status_code, response.headers["Location"]), (302, "/login?next=/outfits"))
                button = self.post(self.visitor, "/outfits/save", headers=HX, key="x")
                self.assertEqual((button.status_code, button.headers["HX-Redirect"]), (401, "/login"))
                self.assertEqual(self.visitor.post("/outfits/save").status_code, 400, "no token: refused, as before")
        with self.closed(True):
            self.assertTrue(guests.door_open())

    def test_on_your_own_machine_nothing_changes(self):
        with mock.patch.object(settings, "PRODUCTION", False):
            self.assertFalse(guests.door_open(), "no login there, so no visitors without one")


class AnOutfitsPicture(WithPictures, GuestCase):
    def setUp(self):
        super().setUp()
        self.switch_on()

    def draw(self, outfit, owner=None) -> str:
        """The front picture of one of the example's outfits, as a customer with the same model got it: there already
        (or, with `owner`, drawn from that customer's photo). Returns its file's name."""
        chosen, rules = looks.service(), looks.load_rules()
        who = person.current(rules["pictures"]["photos"])
        mark = f"{owner}:0123456789abcdef" if owner else who.mark
        key = looks.fingerprint(chosen, looks.prompt(outfits.snapshot(outfit), rules, who), mark)
        looks.folder().mkdir(parents=True, exist_ok=True)
        (looks.folder() / f"{key}-1.jpg").write_bytes(PICTURE)
        db.start_look(key, chosen.tag, 0, 0, owner=owner)
        db.finish_look(key, f"{key}-1.jpg")
        return f"{key}-1.jpg"

    def test_only_a_picture_that_is_there_already_and_never_one_of_a_persons_photo(self):
        ada = self.member("ada@example.com")
        keys = [re.search(r'id="outfit-(\w+)"', outfit).group(1) for outfit in slides(self.page("/outfits"))]
        with db.as_user(guests.example_id()):
            w = selection.build()
            first, second = outfits.find(w, keys[0]), outfits.find(w, keys[1])
            file = self.draw(first)
            theirs = self.draw(second, owner=self.user_id("ada@example.com"))
        before = everything_in()
        page = self.page("/outfits")
        shown = {re.search(r'id="outfit-(\w+)"', outfit).group(1): outfit for outfit in slides(page)}
        mine = shown[first.key]
        address = f"/outfits/{first.key}/picture/{file}"
        self.assertIn(f'<img src="{address}" alt="AI-generated picture of a model wearing this outfit"', mine)
        self.assertIn('<span class="ai-chip">AI picture</span>', mine)
        self.assertIn("Look and fit will differ on the real pieces.", mine)
        # A dot on each piece, named by the piece alone.
        dots = re.findall(r'<a class="spot[^"]*" href="/signup\?why=shop" aria-label="([^"]+)"', mine)
        self.assertEqual(dots, re.findall(r'<span class="piece-text"><b>([^<]+)</b>', mine))
        self.assertNotIn("look-pic", shown[second.key], "drawn from someone's photo: never shown to a visitor")
        self.assertNotIn(theirs, page)
        for outfit in shown.values():
            self.assertNotIn("data-auto-look", outfit, "nothing is drawn for a visitor")
            self.assertNotIn("hx-post", outfit)
        # The example's own pictures have an address of their own, for visitors; every other picture, at /looks/,
        # still needs an account (test_looks: the pictures need a login), and one of someone's photo is his alone.
        for client, url, status in ((self.visitor, address, 200), (self.visitor, f"/looks/{file}", 302),
                                    (self.visitor, f"/outfits/{second.key}/picture/{theirs}", 404),
                                    (self.visitor, f"/outfits/{first.key}/picture/{theirs}", 404),
                                    (self.visitor, f"/outfits/{first.key}/picture/nothing-1.jpg", 404),
                                    (ada, f"/looks/{theirs}", 200), (ada, address, 404)):
            response = client.get(url)
            self.assertEqual(response.status_code, status, url)
            response.close()
        self.left_out(page, "/outfits")
        self.assertEqual(self.drawn, [], "nothing was sent to the image service")
        self.assertEqual(everything_in(), before)
        self.assertEqual(rows("look_requests"), 0)
