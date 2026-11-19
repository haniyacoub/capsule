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
from contextlib import closing, redirect_stderr, redirect_stdout
from html import unescape
from io import StringIO
from unittest import mock
from urllib.parse import parse_qs, urlsplit

from wardrobe import config, db, guests, imagegen, looks, mail, outfits, paths, person, programmes, selection, settings
from wardrobe import shared, videos, yes
from wardrobe import profile as profile_mod
from wardrobe.__main__ import main
from wardrobe.app import PUBLIC, create_app
from wardrobe.config import ConfigError

from .test_looks import PICTURE, WithPictures, photo_jpeg, some_outfits
from .test_production import HX, PASSWORD, ProductionCase, description, words
from .test_videos import CLIP, WithVideos
from .test_programmes import PUBLISHED, STORES, shaped

# Two of each for the pieces of the example's plans, the dearer at COS: enough for many outfits at its price level,
# each piece with a store, a name, a price, a link and a photo that must not reach a visitor. (The example is planned
# for config/site.toml's 600 € since 19 Nov 2026: a light jacket, a light blue shirt, a navy tee and stone chinos; the
# blazer and the coat are the 1,500 € plan's.)
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
    shaped("cos", "2000000110", "Leichte Jacke", 150.0, "Marineblau", "jacket"),
    shaped("weekday", "2000000210", "Leichte Jacke", 90.0, "Marineblau", "jacket"),
    shaped("cos", "2000000111", "Oxford-Hemd", 69.0, "Hellblau", "shirt"),
    shaped("weekday", "2000000211", "Hemd aus Oxford", 45.0, "Hellblau", "shirt"),
    shaped("cos", "2000000112", "T-Shirt aus schwerem Baumwolljersey", 35.0, "Marineblau", "tee"),
    shaped("weekday", "2000000212", "Standard T-Shirt", 25.0, "Marineblau", "tee"),
    shaped("cos", "2000000113", "Chino", 79.0, "Stein", "chinos"),
    shaped("weekday", "2000000213", "Chino-Hose", 55.0, "Stein", "chinos"),
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


def hint_of(outfit: str) -> str | None:
    """The words of an outfit's hint, as HTML (None where it has none)."""
    found = re.search(r'<div class="hint" role="note">\s*<p>(.*?)</p>', outfit, re.S)
    return unescape(found.group(1)) if found else None


def owner_command(*args) -> tuple[str, str]:
    """python -m wardrobe example-pictures, run as the owner does on the server: in a process of its own, where the
    site's start-up never ran (so guests.example_id knows of no example there). Returns (what it printed, the line it
    refused with, or "")."""
    said = StringIO()
    with mock.patch.object(guests, "_ready", False), redirect_stdout(said):
        try:
            main(["example-pictures", *args])
        except SystemExit as stop:
            return said.getvalue(), str(stop.code or "")
    return said.getvalue(), ""


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
        # The website's words (/about, test_production.py) lead to the outfits, the home page, with one main button.
        about = self.page("/about")
        cta = re.search(r'<p class="hero-cta">(.*?)</p>', about, re.S).group(1)
        self.assertEqual(re.findall(r'<a class="([^"]*)" href="([^"]*)">([^<]*)</a>', cta),
                         [("btn", "/", "Explore outfits"), ("btn ghost", "/signup", "Create a free account")],
                         "one main button, Explore outfits, beside Create a free account")
        self.assertIn("No account needed to look around.", words(about))
        page = self.page("/outfits")
        nav = re.search(r'<header class="top">.*?(<nav class="public-nav.*?</nav>)', page, re.S).group(1)
        self.assertEqual([(href, unescape(re.sub(r"<[^>]+>", "", text)).strip())
                          for href, text in re.findall(r'<a class="[^"]*" href="([^"]*)">(.*?)</a>', nav, re.S)],
                         [("/about", "About"), ("/login", "Log in"), ("/signup", "Create account")],
                         "the header for a visitor: what Stilsmith is, Log in, and Create account")
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
        # None of a customer's choices (another product, another piece in the outfit, all the options): only the way to
        # swap the piece, which is for an account and leads to "Create your account", saying so.
        for swap in ("Choose", "Swap it for", "Wear the", "Leave the", "Compare all", "Add one you found"):
            self.assertNotIn(swap, said)
        swap = re.findall(r'<a class="btn ghost" href="([^"]+)">.*?<span>([^<]+)</span></a>', said, re.S)
        self.assertEqual(swap, [("/signup?why=change", "Swap this piece")])
        why = re.search(r'<p class="signup-why" role="status">([^<]*)</p>', self.page(swap[0][0])).group(1)
        self.assertEqual(unescape(why), "Create a free account to swap pieces and choose products.")
        # Without JavaScript the piece is a link to "Create your account".
        self.assertRegex(first, r'<a class="tile" href="/signup\?why=shop" title="[^"]+"\s+hx-get="/outfits/piece')

    def test_stores_prices_links_and_photos_are_left_out_on_the_server(self):
        # Every page a visitor can reach from the home page (the outfits), followed link by link: each answers, and none
        # holds a price, an address of another site or any of the products' photos, links, names or ids; the outfits
        # (at "/" too) and the pop-ups name no store either. (/about names the stores Stilsmith picks from, as the
        # landing page did: that is what the site is, not a product's store.) Nothing is written, no picture or video is
        # asked for, and no cookie is set, until the sign-up or log-in form, whose token needs one.
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
            self.left_out(page, url, stores=parts.path == "/" or parts.path.startswith("/outfits"))
            todo += [unescape(link) for link in LINKS.findall(page)]
        visited = {urlsplit(url).path for url in fetched}
        self.assertTrue({"/", "/about", "/outfits", "/outfits/piece", "/signup", "/login", "/legal/privacy"} <= visited,
                        visited)
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
            # The example profile (its sizes, no photo), with a budget of its own that it has given, fitted to it.
            self.assertEqual(profile_mod.load(), {**profile_mod.EXAMPLE, "budget": 600}, "the example profile")
            self.assertEqual(guests.example_budget(), 600, "config/site.toml")
            self.assertTrue(profile_mod.budget_known())
            self.assertEqual(selection.build().mode, "budget", "Best for budget")
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
            self.assertEqual(db.get_setting("mode"), "budget")
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
                self.assertNotIn('class="slide"', landing, "the landing page, as before: no outfits")
                self.assertNotIn("Explore outfits", self.page("/about"))
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


class WithExamplePictures(WithPictures, GuestCase):
    """AI pictures on (with the tests' stand-in for the image service), and a way to have pictures there already."""

    def setUp(self):
        super().setUp()
        self.switch_on()

    def key_of(self, outfit, owner=None) -> str:
        """The name of an outfit's front picture for the account the block runs as (or, with `owner`, of one drawn
        from that customer's photo)."""
        chosen, rules = looks.service(), looks.load_rules()
        who = person.current(rules["pictures"]["photos"])
        mark = f"{owner}:0123456789abcdef" if owner else who.mark
        return looks.fingerprint(chosen, looks.prompt(outfits.snapshot(outfit), rules, who), mark)

    def draw(self, outfit, owner=None) -> str:
        """The front picture of one of the example's outfits, as a customer with the same model got it: there already
        (or, with `owner`, drawn from that customer's photo). Returns its file's name."""
        key = self.key_of(outfit, owner)
        looks.folder().mkdir(parents=True, exist_ok=True)
        (looks.folder() / f"{key}-1.jpg").write_bytes(PICTURE)
        db.start_look(key, looks.service().tag, 0, 0, owner=owner)
        db.finish_look(key, f"{key}-1.jpg")
        return f"{key}-1.jpg"

    def shown(self, url="/outfits", client=None) -> list[tuple[str, str]]:
        """The outfits of a page in its order: each one's key, and the file of its AI picture ("" where it has none)."""
        out = []
        for outfit in slides(self.page(url, client)):
            picture = re.search(r'<img src="/(?:outfits/\w+/picture|looks)/([^"]+)" alt="AI-generated', outfit)
            out.append((re.search(r'id="outfit-(\w+)"', outfit).group(1), picture.group(1) if picture else ""))
        return out


class AnOutfitsPicture(WithExamplePictures):
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


class PicturesFirst(WithExamplePictures):
    """A visitor sees the outfits that have an AI picture first, each group in the row's own order. A customer's
    outfits keep their order."""

    def setUp(self):
        super().setUp()
        self.pictured: list[str] = []       # the outfits given a picture so far (draw_for)

    def usual(self, seed=0) -> list[str]:
        """The example's first twelve outfits in a customer's order (yes.offer), whatever pictures there are."""
        with db.as_user(guests.example_id()):
            return [o.key for o in yes.offer(selection.build(), "all", 12, seed)[0]]

    def with_pictures_first(self, keys: list[str]) -> list[str]:
        have = set(self.pictured)
        return [key for key in keys if key in have] + [key for key in keys if key not in have]

    def draw_for(self, *keys: str) -> None:
        with db.as_user(guests.example_id()):
            w = selection.build()
            for key in keys:
                self.pictured.append(key)
                self.draw(outfits.find(w, key))

    def test_a_visitor_sees_the_outfits_with_a_picture_first(self):
        usual = self.usual()
        self.assertEqual([key for key, _ in self.shown()], usual, "no pictures yet: the row's own order")
        self.draw_for(usual[3], usual[7])
        page = self.shown()
        self.assertEqual([key for key, _ in page], [usual[3], usual[7]] + usual[:3] + usual[4:7] + usual[8:])
        self.assertEqual([bool(file) for _, file in page], [True, True] + [False] * 10)

        # "Show more outfits": the twelve he has seen keep their places (the link names them in the order shown), and
        # of the twelve it adds, those with a picture come first.
        more = unescape(re.search(r'<a class="btn" href="([^"#]+)#outfit-\w+">Show more outfits</a>',
                                  self.page("/outfits")).group(1))
        self.assertEqual(parse_qs(urlsplit(more).query)["front"], [".".join(key for key, _ in page)])
        added = [key for key, _ in self.shown(more)][12:]
        self.draw_for(added[2], added[9])
        longer = self.shown(more)
        self.assertEqual([key for key, _ in longer][:12], [key for key, _ in page], "where he was, unchanged")
        self.assertEqual([key for key, _ in longer][12:], self.with_pictures_first(added))
        self.assertEqual([bool(file) for _, file in longer][12:14], [True, True])

        # Shuffle: another row of outfits, and the same rule in it.
        shuffled = self.usual(seed=5)
        self.assertNotEqual(shuffled, usual, "(another row)")
        self.draw_for(*[key for key in shuffled[5:7] if key not in self.pictured])
        self.assertEqual([key for key, _ in self.shown("/outfits?occasion=all&seed=5")],
                         self.with_pictures_first(shuffled))
        self.assertEqual(self.drawn, [], "nothing was drawn for a visitor")

    def test_a_customers_outfits_keep_their_order(self):
        ada = self.member("ada@example.com")
        before = [key for key, _ in self.shown(client=ada)]
        with db.as_user(self.user_id("ada@example.com")):
            w = selection.build()
            files = [self.draw(outfits.find(w, before[i])) for i in (3, 7)]
        after = self.shown(client=ada)
        self.assertEqual([key for key, _ in after], before, "his own order, pictures or not")
        self.assertEqual([file for _, file in after if file], files, "(the pictures are there)")


class ExamplePictures(WithExamplePictures):
    """python -m wardrobe example-pictures: the owner draws the AI pictures visitors see, by hand on the server, after
    it has said how many are there and what the rest would cost."""

    def command(self, *args) -> tuple[str, str]:
        return owner_command(*args)

    def first_page(self) -> list[str]:
        return [key for key, _ in self.shown()]

    def test_it_says_what_is_there_and_what_the_rest_would_cost_and_stops_without_yes(self):
        first = self.first_page()
        with db.as_user(guests.example_id()):
            w = selection.build()
            for key in first[:5]:
                self.draw(outfits.find(w, key))
            busy = self.key_of(outfits.find(w, first[5]))      # one the site is drawing right now, for a customer
        db.start_look(busy, looks.service().tag, 0, 0)
        before = everything_in()
        said, refused = self.command()
        self.assertEqual(refused, "")
        self.assertIn("The example wardrobe: its first 12 outfits, as a visitor sees them.\n5 of 12 already there.\n"
                      "1 is being drawn already: left alone.\n"
                      "6 to draw: about $0.30 (6 pictures at $0.05, price_each_usd in config/looks.toml).\n"
                      "Nothing was drawn. To draw them, run this again with --yes.\n", said)
        self.assertEqual(self.drawn, [], "nothing was sent")
        self.assertEqual(everything_in(), before, "nothing was written")

    def test_sample_draws_the_first_missing_ones_and_a_visitor_then_sees_exactly_those(self):
        first = self.first_page()
        said, refused = self.command("--sample", "3", "--yes")
        self.assertEqual(refused, "")
        self.assertIn("12 missing; --sample 3 draws the first 3 of them: about $0.15", said)
        self.assertIn("Done: 3 drawn.\nSpent, by this command's estimate: about $0.15 (3 pictures at $0.05).\n", said)
        self.assertEqual(len(self.drawn), 3, "one at a time, three")
        house_model = looks.load_rules()["text"]["model"]
        for sent in self.drawn:
            self.assertEqual((sent["photo"], sent["references"]), (None, []), "nobody's photo goes with it")
            self.assertIn(house_model, sent["prompt"], "Stilsmith's house model")
        # The visitor's Outfits page shows exactly those three pictures, on the first three outfits it showed.
        shown = self.shown()
        self.assertEqual([key for key, file in shown if file], first[:3])
        self.assertEqual([key for key, _ in shown], first, "(they were first already)")
        with closing(sqlite3.connect(paths.DB_PATH)) as con:
            kept = con.execute("SELECT user_id, file FROM looks").fetchall()
        self.assertEqual(sorted(file for _, file in kept), sorted(file for _, file in shown if file))
        self.assertEqual({user for user, _ in kept}, {None}, "the pictures belong to no account")
        self.assertEqual(rows("look_requests"), 0, "not counted in the day's limits")
        for key, file in shown[:3]:
            response = self.visitor.get(f"/outfits/{key}/picture/{file}")
            self.assertEqual(response.status_code, 200)
            response.close()

    def test_running_it_again_draws_only_what_is_missing(self):
        said, _ = self.command("--yes")
        self.assertIn("12 to draw: about $0.60", said)
        self.assertIn("Done: 12 drawn.", said)
        self.assertEqual(len(self.drawn), 12)
        self.assertTrue(all(file for _, file in self.shown()), "every outfit of a visitor's first page has its picture")
        said, refused = self.command("--yes")
        self.assertEqual(refused, "")
        self.assertIn("12 of 12 already there.\nNothing to draw.\n", said)
        self.assertEqual(len(self.drawn), 12, "nothing was sent the second time")
        # The next twelve are the ones "Show more outfits" adds.
        said, _ = self.command("--outfits", "24")
        self.assertIn("its first 24 outfits, as a visitor sees them.\n12 of 24 already there.\n12 to draw", said)

    def test_a_ceiling_it_never_goes_over(self):
        said, refused = self.command("--max-cost", "0.50", "--yes")
        self.assertIn("12 to draw: about $0.60", said)
        self.assertEqual(refused, "That is more than --max-cost ($0.50), so nothing was drawn. "
                                  "Draw fewer with --sample, or allow more with --max-cost.")
        self.assertEqual(self.drawn, [])
        said, refused = self.command("--max-cost", "0.60")      # 12 pictures at 0.05 are exactly 0.60: not above
        self.assertEqual(refused, "")
        self.assertIn("run this again with --yes", said)
        with redirect_stderr(StringIO()) as error, self.assertRaises(SystemExit):
            main(["example-pictures", "--max-cost", "lots"])
        self.assertIn("an amount in US dollars, like 1.00", error.getvalue())

    def test_a_failure_is_said_and_what_would_fail_the_same_way_is_not_sent(self):
        self.refuse = imagegen.DrawError("refused", "the outfit was not drawn")       # this one, not the next
        said, _ = self.command("--sample", "1", "--yes")
        self.assertIn("#1, the outfit with the ", said)
        self.assertIn(": failed. The AI declined to draw this outfit. the outfit was not drawn\n", said)
        self.assertIn("Done: 0 drawn, 1 failed.\nSpent, by this command's estimate: about $0.05 (1 picture at $0.05, "
                      "counting those that failed after reaching the image service: it may bill them).", said)
        self.refuse = imagegen.DrawError("key", "API key not valid", free=True)      # the next ones would fail too
        said, _ = self.command("--yes")
        self.assertEqual(len(self.drawn), 2, "after that answer, the others were not sent")
        self.assertIn("failed. The image service did not accept the key. API key not valid\n"
                      "Stopped: the other 11 were not sent.", said)
        self.assertIn("about $0.00 (0 pictures at $0.05)", said)
        self.refuse = None
        self.time_passes()
        said, _ = self.command("--yes")
        self.assertIn("Done: 12 drawn.", said, "put right, it draws them all, those that failed too")

    def test_it_refuses_in_one_plain_line(self):
        refusals = []
        with mock.patch.object(settings, "OPENAI_API_KEY", ""):
            refusals.append(self.command("--yes")[1])
        self.assertIn("Nothing was drawn: AI pictures are off", refusals[-1])
        with mock.patch.object(settings, "PRODUCTION", False):
            refusals.append(self.command("--yes")[1])
        self.assertIn("There is no example wardrobe on your own machine", refusals[-1])
        with mock.patch.object(guests, "EXAMPLE_EMAIL", "nobody@stilsmith.invalid"):
            refusals.append(self.command("--yes")[1])
        self.assertIn("There is no example wardrobe here yet", refusals[-1])
        for line in refusals:
            self.assertNotIn("\n", line)
        self.assertEqual(self.drawn, [])

    def test_nothing_is_drawn_at_start_up_or_for_a_visitor(self):
        create_app()                        # the site starts again, with AI pictures on
        self.assertTrue(slides(self.page("/outfits")))
        self.assertEqual(self.drawn, [])
        self.assertEqual(rows("looks"), 0)

    def test_never_a_picture_of_a_person(self):
        # Run as an account with a photo of its own, the drawing refuses before anything is sent: this way draws only
        # Stilsmith's house model, never a picture of a person.
        self.member("ada@example.com")
        with db.as_user(self.user_id("ada@example.com")):
            self.assertIsNone(person.save_photo(photo_jpeg()))
            with self.assertRaises(ValueError):
                looks.draw_front_now(outfits.snapshot(some_outfits(1)[0]))
        self.assertEqual(self.drawn, [])
        self.assertEqual(rows("looks"), 0)


# ── the home page: no landing page for visitors (round FD-2) ──────────────────

class TheHomePage(GuestCase):
    """"/" for a visitor is the example wardrobe's outfits; the website's words are at /about."""

    def test_home_is_the_example_wardrobes_outfits(self):
        before = everything_in()
        response = self.visitor.get("/")
        home = response.get_data(as_text=True)
        self.assertNotIn("Set-Cookie", response.headers)
        keys = [re.search(r'id="outfit-(\w+)"', outfit).group(1) for outfit in slides(home)]
        self.assertEqual(keys, [re.search(r'id="outfit-(\w+)"', outfit).group(1)
                                for outfit in slides(self.page("/outfits"))], "the very outfits of /outfits")
        self.assertGreaterEqual(len(keys), 3)
        self.assertIn('<section class="looks guest"', home)
        self.assertNotIn("A small menswear wardrobe where everything goes with everything.", home, "no landing page")
        self.left_out(home, "/")
        # A true title and description for search results and shared links: the example's own numbers, no price,
        # budget or store.
        with db.as_user(guests.example_id()):
            every = outfits.all_outfits(selection.build())
        worn = {slot_id for o in every for slot_id in o.slots}
        self.assertIn("<title>Stilsmith — menswear outfits from one small wardrobe</title>", home)
        self.assertEqual(unescape(description(home)),
                         f"Look through {len(every)} menswear outfits made from {len(worn)} pieces of one example "
                         "wardrobe. Create a free account to plan your own, sized to your budget.")
        self.assertIn(f"12 of {len(every)} outfits from an example wardrobe", words(home), "the same count as below")
        self.assertEqual(description(self.page("/outfits")), "", "(/outfits keeps its own title)")
        self.assertIn("<title>Outfits · Stilsmith</title>", self.page("/outfits"))
        self.assertEqual(everything_in(), before, "nothing a visitor reads is written down")
        head = self.visitor.head("/")
        self.assertEqual((head.status_code, head.headers.get("Set-Cookie")), (200, None))

    def test_about_has_the_websites_words_and_the_legal_links(self):
        about = self.page("/about")
        text = words(about)
        self.assertIn("A small menswear wardrobe where everything goes with everything.", text)
        self.assertIn("from the high-street stores COS and Weekday", text, "it may name the stores")
        self.assertIn("<title>Stilsmith — menswear: a small wardrobe that works together</title>", about)
        self.assertTrue(description(about))
        foot = re.search(r'<footer class="site-foot">(.*?)</footer>', about, re.S).group(1)
        self.assertEqual(re.findall(r'<a href="([^"]+)"', foot),
                         ["/about", "/legal/impressum", "/legal/privacy", "/legal/terms"], "the legal links stay")
        self.assertIn('<a href="/about" aria-current="page">About</a>', foot)
        # Every page's foot leads there; on a visitor's outfits the header does too.
        for url in ("/", "/outfits", "/login", "/legal/privacy"):
            page = self.page(url)
            self.assertIn('<a href="/about"', re.search(r'<footer class="site-foot">.*?</footer>', page, re.S).group(0),
                          url)
        self.assertIn('<a class="about-link" href="/about">', self.page("/"))
        # A customer reading it has his own outfits to go back to: no account to create.
        ada = self.member("ada@example.com")
        mine = self.page("/about", ada)
        self.assertEqual(re.findall(r'<p class="hero-cta">(.*?)</p>', mine, re.S),
                         ['<a class="btn" href="/outfits">Open my outfits</a>'])
        self.assertNotIn("No account needed", mine)

    def test_a_customers_home_is_as_before(self):
        ada = self.member("ada@example.com")
        home = self.page("/", ada)
        self.assertIn('<a href="/" class="on" aria-current="page">Wardrobe</a>', home, "his Wardrobe, as before")
        for visitor in ('class="looks guest"', 'class="hint"', "menswear outfits from one small wardrobe"):
            self.assertNotIn(visitor, home)

    def test_on_your_own_machine_there_is_no_website(self):
        with mock.patch.object(settings, "PRODUCTION", False):
            app = create_app()
            self.assertEqual(app.test_client().get("/about").status_code, 404)


class TheHints(WithExamplePictures):
    """One hint on each of a visitor's first three outfits: what the example is, a piece, the picture."""

    def pictures_for(self, keys) -> None:
        with db.as_user(guests.example_id()):
            w = selection.build()
            for key in keys:
                self.draw(outfits.find(w, key))

    def test_one_hint_on_each_of_the_first_three_outfits(self):
        self.pictures_for([key for key, _ in self.shown()][:3])
        home = self.page("/")
        found = slides(home)
        # 1. The stores line, in the example's real numbers: no price, no budget, no store's name.
        with db.as_user(guests.example_id()):
            w = selection.build()
            every = outfits.all_outfits(w)
            worn = {slot_id for o in every for slot_id in o.slots}
            stores = {w.get(slot_id).chosen.data["store"] for slot_id in worn}
        self.assertEqual(stores, {"cos", "weekday"})
        self.assertEqual(hint_of(found[0]), f"{len(worn)} pieces from 2 stores, combined into {len(every)} outfits.")
        # 2. A piece: tap it (or, with a mouse, click it) to see what it is; swapping it needs an account.
        self.assertEqual(hint_of(found[1]), '<span class="by-touch">Tap a piece to see what it is.</span>'
                                            '<span class="by-mouse">Click a piece to see what it is.</span> '
                                            'With an account you can swap it.')
        # 3. The picture, on an outfit that shows one; the photo while photos may be uploaded.
        self.assertEqual(hint_of(found[2]), "Drawn by AI on a model. Add your photo and it's you.")
        self.assertEqual([hint_of(outfit) for outfit in found[3:]], [None] * (len(found) - 3), "three hints, no more")
        for outfit in found[:3]:
            # On the picture's box, before the picture and the pieces: read with its outfit. Its × to put it away is
            # shown by app.js (none without JavaScript).
            stage = re.search(r'<div class="stage">\s*(<div class="hint".*?</div>)', outfit, re.S)
            self.assertIsNotNone(stage, "the hint comes first in the outfit's picture box")
            self.assertIn('<button class="hint-x" type="button" data-hint-close aria-label="Hide this hint" hidden>',
                          stage.group(1))
        self.left_out(home, "/")
        self.assertEqual([hint_of(outfit) for outfit in slides(self.page("/outfits"))][:3],
                         [hint_of(outfit) for outfit in found[:3]], "on /outfits too, the same row")

    def test_the_photo_and_the_picture_only_where_they_are_true(self):
        keys = [key for key, _ in self.shown()]
        self.pictures_for(keys[:2])                     # the third outfit shows no picture
        found = slides(self.page("/"))
        self.assertIsNotNone(hint_of(found[0]))
        self.assertIsNotNone(hint_of(found[1]))
        self.assertNotIn("look-pic", found[2])
        self.assertIsNone(hint_of(found[2]), "no picture, so nothing said about one")
        self.pictures_for(keys[2:3])
        self.with_rules(photos=False)                   # no photos may be uploaded: none is promised
        self.assertEqual(hint_of(slides(self.page("/"))[2]), "Drawn by AI on a model.")
        with mock.patch.object(settings, "OPENAI_API_KEY", ""):      # no pictures at all
            found = slides(self.page("/"))
        self.assertEqual([hint is not None for hint in map(hint_of, found[:4])], [True, True, False, False])

    def test_only_on_the_row_a_visitor_first_opens(self):
        self.pictures_for([key for key, _ in self.shown()][:3])
        first = slides(self.page("/"))
        more = unescape(re.search(r'<a class="btn" href="([^"#]+)#outfit-\w+">Show more outfits</a>',
                                  self.page("/")).group(1))
        for url in ("/outfits?occasion=all", "/outfits?occasion=office", "/outfits?seed=5", more):
            self.assertEqual([hint_of(outfit) for outfit in slides(self.page(url))].count(None),
                             len(slides(self.page(url))), f"{url}: he has moved on from his first row")
        self.assertEqual(sum(hint_of(outfit) is not None for outfit in first), 3)

    def test_never_for_a_customer(self):
        ada = self.member("ada@example.com")
        for url in ("/outfits", "/"):
            self.assertNotIn('class="hint"', self.page(url, ada), url)


class TheHintsOnTheDemo(ProductionCase):
    """While no product list is published the example's products are the invented demo ones: they come from no store."""

    def test_no_stores_are_counted(self):
        line = hint_of(slides(self.app.test_client().get("/").get_data(as_text=True))[0])
        self.assertRegex(line, r"^\d+ pieces, combined into \d+ outfits\.$")


# ── the first outfits are alive: the example's clips ──────────────────────────

class WithExampleClips(WithVideos, WithExamplePictures):
    """AI pictures and videos on (stand-ins for both services), and ways to have the example's pictures and clips."""

    def pictures_for(self, keys) -> dict[str, str]:
        """The front pictures of these outfits of the example, there already. Returns their files by outfit."""
        with db.as_user(guests.example_id()):
            w = selection.build()
            return {key: self.draw(outfits.find(w, key)) for key in keys}

    def board(self, key) -> dict:
        """One of the example's outfits with its pictures and its clip, as a visitor's page has it."""
        with db.as_user(guests.example_id()):
            board = {"key": key, "pieces": outfits.snapshot(outfits.find(selection.build(), key))}
            looks.attach([board])
            videos.example_clips([board])
        return board

    def clip_for(self, key) -> str:
        """The example clip of this outfit's picture, made as the owner's command makes it. Returns its file."""
        with db.as_user(guests.example_id()):
            result, problem = videos.make_example_now(self.board(key)["photos"][0].look)
        self.assertEqual((result, problem), ("ready", None))
        return self.board(key)["clip"]

    def first_keys(self) -> list[str]:
        return [key for key, _ in self.shown()]


class AnOutfitsClip(WithExampleClips):
    def test_a_visitor_sees_the_clip_in_place_of_the_picture(self):
        keys = self.first_keys()
        files = self.pictures_for(keys[:2])
        clip = self.clip_for(keys[0])
        self.assertEqual(len(self.made), 1)
        before = everything_in()
        found = slides(self.page("/"))
        address = f"/outfits/{keys[0]}/clip/{clip}"
        box = re.search(r'<div class="clip" data-clip hidden>(.*?)</div>\s*</div>', found[0], re.S).group(1)
        video = re.search(r"<video [^>]*>", box, re.S).group(0)
        self.assertIn(f'src="{address}"', video)
        self.assertIn(f'poster="/outfits/{keys[0]}/picture/{files[keys[0]]}"', video, "the picture is its poster")
        for attribute in ("muted", "loop", "playsinline", 'preload="none"', 'aria-hidden="true"'):
            self.assertIn(attribute, video.rstrip(">").split(), attribute)
        self.assertNotIn("autoplay", video, "app.js plays the clip of the outfit on screen only")
        self.assertIn('<span class="ai-chip">AI video</span>', box)
        self.assertIn('<span class="sr">Pause the video</span>', box)
        self.assertIn('<span class="sr">Play the video</span>', box)
        self.assertIn('<span class="ai-chip">AI picture</span>', found[0], "without JavaScript: the picture, labelled")
        self.assertNotIn('class="clip"', found[1], "its picture, no clip: the picture alone")
        # Its own address, as the pictures': the file, in parts to a phone that asks for a range of it.
        response = self.visitor.get(address)
        self.assertEqual((response.status_code, response.mimetype), (200, "video/mp4"))
        self.assertEqual(response.get_data(), CLIP)
        self.assertIn("private", response.headers["Cache-Control"])
        response.close()
        part = self.visitor.get(address, headers={"Range": "bytes=0-99"})
        self.assertEqual((part.status_code, len(part.get_data())), (206, 100))
        part.close()
        self.left_out(self.page("/"), "/")
        self.assertEqual(everything_in(), before, "nothing a visitor sees is written down")
        self.assertEqual(len(self.made), 1, "nothing is made for a visitor")
        self.assertEqual(rows("video_requests"), 0)

    def test_only_the_examples_own_finished_clips_have_an_address(self):
        ada = self.member("ada@example.com")
        keys = self.first_keys()
        self.pictures_for(keys[:3])
        clip = self.clip_for(keys[0])
        address = f"/outfits/{keys[0]}/clip/{clip}"
        # A clip being made is not shown; nor is the clip of a picture drawn from a customer's photo.
        with db.as_user(guests.example_id()):
            w = selection.build()
            theirs = self.draw(outfits.find(w, keys[3]), owner=self.user_id("ada@example.com"))
        chosen, kind = videos.service(), videos.example()
        busy = videos.fingerprint(chosen, kind.text, self.board(keys[1])["photos"][0].look.file, kind.seconds)
        db.start_video(busy, "x.jpg", chosen.tag, None, 0)
        personal = videos.fingerprint(chosen, kind.text, theirs, kind.seconds)
        db.start_video(personal, theirs, chosen.tag, self.user_id("ada@example.com"), 0)
        db.finish_video(personal, f"{personal}-1.mp4", None)
        (videos.folder() / f"{personal}-1.mp4").write_bytes(CLIP)
        page = self.page("/")
        self.assertEqual(page.count('class="clip"'), 1, "the one finished clip of the example's own pictures")
        self.assertNotIn(personal, page)
        for client, url, status in ((self.visitor, address, 200),
                                    (self.visitor, f"/outfits/{keys[1]}/clip/{clip}", 404),     # another outfit's
                                    (self.visitor, f"/outfits/{keys[0]}/clip/nothing-1.mp4", 404),
                                    (self.visitor, f"/outfits/{keys[3]}/clip/{personal}-1.mp4", 404),
                                    (self.visitor, f"/outfits/{keys[1]}/clip/{busy}-1.mp4", 404),
                                    (self.visitor, f"/videos/{clip}", 302),          # /videos/ stays for accounts
                                    (ada, f"/videos/{clip}", 200),
                                    (ada, address, 404)):                            # the visitors' address is theirs
            response = client.get(url)
            self.assertEqual(response.status_code, status, url)
            response.close()
        # While videos are off, the pictures show, and the clips have no address.
        with mock.patch.object(videos, "service", return_value=None):
            self.assertNotIn('class="clip"', self.page("/"))
            self.assertEqual(self.visitor.get(address).status_code, 404)

    def test_never_a_clip_of_a_picture_of_a_person(self):
        self.member("ada@example.com")
        with db.as_user(self.user_id("ada@example.com")):
            self.assertIsNone(person.save_photo(photo_jpeg()))
            outfit = some_outfits(1)[0]
            looks.request(outfits.snapshot(outfit))
            board = {"key": outfit.key, "pieces": outfits.snapshot(outfit)}
            looks.attach([board])
            with self.assertRaises(ValueError):
                videos.make_example_now(board["photos"][0].look)
        self.assertEqual(self.made, [])


class ExampleClips(WithExampleClips):
    """python -m wardrobe example-pictures --clips K: the clips of the first K outfits visitors see, made by the owner
    after the command has said what they would cost."""

    def test_it_says_what_the_clips_would_cost_and_stops_without_yes(self):
        self.pictures_for(self.first_keys())
        before = everything_in()
        said, refused = owner_command("--clips", "3")
        self.assertIn("12 of 12 already there.\nNothing to draw.\nAI videos: on — made by Google, model "
                      "gemini-omni-flash-preview\nClips of the first 3 outfits: 0 already there.\n"
                      "3 clips to make: about $1.50 (3 clips of 5 seconds at $0.10 a second, price_per_second_usd in "
                      "config/looks.toml).\n", said)
        self.assertEqual(refused, "That is more than --max-cost ($1.00), so nothing was drawn or made. Ask for fewer "
                                  "with --sample or --clips, or allow more with --max-cost.")
        said, refused = owner_command("--clips", "3", "--max-cost", "1.50")      # exactly the estimate: not above it
        self.assertEqual(refused, "")
        self.assertTrue(said.endswith("Nothing was drawn or made. To go ahead, run this again with --yes.\n"), said)
        self.assertEqual((self.drawn, self.made), ([], []), "nothing was sent")
        self.assertEqual(everything_in(), before, "nothing was written")

    def test_yes_makes_them_and_running_it_again_makes_only_what_is_missing(self):
        keys = self.first_keys()
        files = self.pictures_for(keys)
        said, refused = owner_command("--clips", "3", "--max-cost", "2", "--yes")
        self.assertEqual(refused, "")
        self.assertIn("Making 3 clips, one at a time", said)
        self.assertIn("Clips done: 3 made.\nSpent on clips, by this command's estimate: about $1.50 (3 clips of 5 "
                      "seconds at $0.10 a second).\nVisitors see the new clips from their next page load.\n", said)
        rules = looks.load_rules()["videos"]
        for sent, key in zip(self.made, keys):
            self.assertEqual(sent["seconds"], 5)
            self.assertEqual(sent["prompt"], f"{rules['start']} {rules['motion']['example']} {rules['keep']}")
            self.assertEqual(sent["picture"], (looks.folder() / files[key]).read_bytes(), "made from its picture")
        self.assertEqual([bool(re.search(r'class="clip"', outfit)) for outfit in slides(self.page("/"))][:4],
                         [True, True, True, False], "the first three outfits a visitor sees")
        self.assertEqual(rows("video_requests"), 0, "not counted in the day's video limits")
        with closing(sqlite3.connect(paths.DB_PATH)) as con:
            self.assertEqual({row[0] for row in con.execute("SELECT user_id FROM videos")}, {None},
                             "the clips belong to no account")
        said, refused = owner_command("--clips", "3", "--max-cost", "2", "--yes")
        self.assertIn("Clips of the first 3 outfits: 3 already there.\nNo clip to make.\n", said)
        self.assertEqual(len(self.made), 3, "nothing was sent the second time")

    def test_pictures_and_clips_in_one_run_of_the_outfits_a_visitor_will_see_first(self):
        # Two outfits further down the row have their pictures, so a visitor sees them first today. Once this run has
        # drawn the others, he sees the row's own order again: the clips are of the first outfits of that order, and
        # the estimate counts exactly those.
        keys = self.first_keys()
        self.pictures_for([keys[5], keys[7]])
        said, refused = owner_command("--clips", "2", "--max-cost", "2")
        self.assertIn("10 to draw: about $0.50 (10 pictures at $0.05, price_each_usd in config/looks.toml).\n", said)
        self.assertIn("2 clips to make: about $1.00 (2 clips of 5 seconds at $0.10 a second, price_per_second_usd in "
                      "config/looks.toml).\nIn all: about $1.50.\n", said)
        said, refused = owner_command("--clips", "2", "--max-cost", "2", "--yes")
        self.assertEqual(refused, "")
        self.assertIn("Done: 10 drawn.\n", said)
        self.assertIn("Clips done: 2 made.\n", said)
        self.assertIn("Visitors see the new pictures and clips from their next page load.", said)
        shown = slides(self.page("/"))
        self.assertEqual([re.search(r'id="outfit-(\w+)"', outfit).group(1) for outfit in shown], keys)
        self.assertEqual([bool(re.search(r'class="clip"', outfit)) for outfit in shown][:3], [True, True, False])

    def test_it_refuses_in_one_plain_line_while_videos_are_off(self):
        self.pictures_for(self.first_keys())
        rules = looks.load_rules()

        def changed(**videos_part):
            return mock.patch.object(looks, "load_rules", lambda: {**rules, "videos": {**rules["videos"], **videos_part}})

        refusals = []
        with changed(on=False):
            refusals.append(owner_command("--clips", "3", "--yes")[1])
        self.assertEqual(refusals[-1], "Nothing was drawn or made: AI videos are off — [videos] on = false in "
                                       "config/looks.toml.")
        with mock.patch.object(settings, "GEMINI_API_KEY", ""):
            refusals.append(owner_command("--clips", "3", "--yes")[1])
        self.assertEqual(refusals[-1], "Nothing was drawn or made: AI videos are off — set GEMINI_API_KEY.")
        with changed(motion={key: words for key, words in rules["videos"]["motion"].items() if key != "example"}):
            refusals.append(owner_command("--clips", "3", "--yes")[1])
        self.assertIn("the clips need their movement, example under [videos.motion]", refusals[-1])
        with mock.patch.object(looks, "load_rules", lambda: {**rules, "videos": {
                key: value for key, value in rules["videos"].items() if key != "price_per_second_usd"}}):
            refusals.append(owner_command("--clips", "3", "--yes")[1])
        self.assertIn("the estimate needs price_per_second_usd under [videos]", refusals[-1])
        for line in refusals:
            self.assertNotIn("\n", line)
        self.assertEqual((self.drawn, self.made), ([], []))

    def test_a_failure_is_said_and_the_rest_are_not_sent(self):
        self.pictures_for(self.first_keys())
        self.refuse_video = imagegen.DrawError("key", "API key not valid", free=True)
        said, _ = owner_command("--clips", "3", "--max-cost", "2", "--yes")
        self.assertIn(": failed. Google did not accept the key (GEMINI_API_KEY). API key not valid\n"
                      "Stopped: the other 2 were not sent.", said)
        self.assertIn("Clips done: 0 made, 1 failed.\nSpent on clips, by this command's estimate: about $0.00 (0 clips "
                      "of 5 seconds at $0.10 a second).\n", said)
        self.assertEqual(len(self.made), 1)
        self.refuse_video = None
        said, _ = owner_command("--clips", "3", "--max-cost", "2", "--yes")
        self.assertIn("Clips done: 3 made.", said, "put right, it makes them all")

    def test_nothing_is_made_at_start_up_or_for_a_visitor(self):
        self.pictures_for(self.first_keys()[:3])
        create_app()
        for url in ("/", "/outfits"):
            self.assertTrue(slides(self.page(url)))
        self.assertEqual(self.made, [])
        self.assertEqual(rows("videos"), 0)
