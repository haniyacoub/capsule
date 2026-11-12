"""Production mode: customer accounts, isolation between customers, and the guards around them."""
import json
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import closing
from html import unescape
from pathlib import Path
from unittest import mock

from wardrobe import catalog, db, mail, paths, selection, settings, shared
from wardrobe.app import create_app

PASSWORD = "correct horse battery"
HX = {"HX-Request": "true"}


def fresh_files():
    for path in (paths.DB_PATH, paths.CATALOG_PATH, paths.DATA_DIR / shared.POOL_NAME):
        path.unlink(missing_ok=True)
    catalog._cache = shared._cache = None


def words(html: str) -> str:
    """What a visitor reads on a page: its text, without the tags and without the head."""
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html.split("</head>", 1)[-1])).strip()


def description(html: str) -> str:
    """The page's description for search results and shared links ("" when it has none)."""
    found = re.search(r'<meta name="description" content="([^"]*)">', html)
    return found.group(1) if found else ""


class ProductionCase(unittest.TestCase):
    def setUp(self):
        fresh_files()
        self._before = (settings.PRODUCTION, settings.SECRET_KEY, settings.SITE_URL)
        settings.PRODUCTION, settings.SECRET_KEY = True, "t" * 48
        mail.OUTBOX.clear()
        self.app = create_app()

    def tearDown(self):
        settings.PRODUCTION, settings.SECRET_KEY, settings.SITE_URL = self._before
        fresh_files()

    def token(self, client) -> str:
        client.get("/login")                         # any page gives the visitor a session
        with client.session_transaction() as session:
            return session["csrf"]

    def post(self, client, url, headers=None, **data):
        return client.post(url, data={**data, "csrf_token": self.token(client)}, headers=headers or {})

    def member(self, email, password=PASSWORD):
        """A browser that has signed up and is logged in."""
        client = self.app.test_client()
        response = self.post(client, "/signup", email=email, password=password)
        self.assertEqual(response.status_code, 302, response.data[:300])
        return client

    def user_id(self, email) -> int:
        return db.get_user_by_email(email)["id"]


class PublicSite(ProductionCase):
    def test_visitors_see_the_website_not_the_app(self):
        visitor = self.app.test_client()
        home = visitor.get("/")
        self.assertEqual(home.status_code, 200)
        self.assertIn(b"Create a free account", home.data)
        self.assertNotIn(b"Minimum quality", home.data)
        for url in ("/legal/impressum", "/legal/privacy", "/legal/terms", "/login", "/signup", "/forgot",
                    "/robots.txt", "/static/app.css"):
            self.assertEqual(visitor.get(url).status_code, 200, url)
        self.assertEqual(visitor.get("/legal/nonsense").status_code, 404)
        self.assertEqual(visitor.get("/healthz").get_json(), {"status": "ok"})

    def test_the_typefaces_come_from_this_site_with_their_licences(self):
        # Fetching fonts from Google's servers is unlawful in Germany (LG München, 2022). Capsule serves its
        # two typefaces itself, each with its open licence next to it, and its stylesheet asks no other site.
        visitor = self.app.test_client()
        for name in ("instrument-sans-latin-wght-normal.woff2", "instrument-serif-latin-400-normal.woff2"):
            response = visitor.get(f"/static/fonts/{name}")
            self.assertEqual(response.status_code, 200, name)
            self.assertEqual(response.get_data()[:4], b"wOF2", f"{name} is not a web font")
            response.close()
        for name in ("OFL-InstrumentSans.txt", "OFL-InstrumentSerif.txt"):
            response = visitor.get(f"/static/fonts/{name}")
            self.assertIn(b"SIL Open Font License", response.get_data(), name)
            response.close()
        response = visitor.get("/static/app.css")
        addresses = re.findall(r"url\(([^)]*)\)", response.get_data(as_text=True))
        response.close()
        self.assertIn('"fonts/instrument-sans-latin-wght-normal.woff2"', addresses)
        self.assertEqual([a for a in addresses if "//" in a], [], "the stylesheet loads something from another site")
        # The text font is asked for with the page, not only once the stylesheet has arrived.
        self.assertIn('<link rel="preload" href="/static/fonts/instrument-sans-latin-wght-normal.woff2" as="font"',
                      visitor.get("/").get_data(as_text=True))

    def test_the_app_needs_a_login(self):
        visitor = self.app.test_client()
        for url in ("/outfits", "/list", "/slots", "/profile", "/account", "/slot/white-tee", "/list.csv"):
            response = visitor.get(url)
            self.assertEqual(response.status_code, 302, url)
            self.assertIn("/login?next=", response.headers["Location"])
        button = self.post(visitor, "/settings", headers=HX, mode="cheapest")
        self.assertEqual(button.status_code, 401)
        self.assertEqual(button.headers["HX-Redirect"], "/login")

    def test_security_headers_and_cookie_flags(self):
        settings.SITE_URL = "https://capsule.example"
        app = create_app()
        response = app.test_client().get("/login")
        for header in ("Content-Security-Policy", "X-Content-Type-Options", "X-Frame-Options", "Referrer-Policy"):
            self.assertIn(header, response.headers)
        self.assertIn("script-src 'self'", response.headers["Content-Security-Policy"])
        cookie = response.headers["Set-Cookie"]
        for flag in ("Secure", "HttpOnly", "SameSite=Lax"):
            self.assertIn(flag, cookie)

    def test_it_will_not_start_without_a_real_secret(self):
        settings.SECRET_KEY = "short"
        with self.assertRaises(SystemExit):
            create_app()

    def test_it_will_not_start_on_the_values_the_example_file_comes_with(self):
        # deploy/app.env.example is public: whoever forgets to change a line must not end up running on it.
        example = (paths.ROOT / "deploy" / "app.env.example").read_text()
        given = dict(line.split("=", 1) for line in example.splitlines() if line and not line.startswith("#"))
        self.assertGreaterEqual(len(given["SECRET_KEY"]), 32, "long enough to pass the length check, so it needs its own")
        settings.SECRET_KEY = given["SECRET_KEY"]
        with self.assertRaises(SystemExit) as stop:
            create_app()
        self.assertIn("placeholder", str(stop.exception))
        settings.SECRET_KEY = "t" * 48
        with mock.patch.object(settings, "INVITE_CODE", given["INVITE_CODE"]), self.assertRaises(SystemExit) as stop:
            create_app()
        self.assertIn("placeholder", str(stop.exception))

    def test_the_landing_page_says_what_capsule_is_in_plain_words(self):
        # A stranger gives the page a few seconds. It says who Capsule is for, in the customer's words rather than
        # the planner's; it has one way to log in (the header's) and no drawings from the demo data; search results
        # and shared links get a description. AI pictures are off here (no key), so no model is promised.
        page = self.app.test_client().get("/").get_data(as_text=True)
        text = words(page)
        self.assertRegex(text, r"\bmen's wardrobe\b")
        for planner in ("slot", "candidate", "score"):
            self.assertNotIn(planner, text.lower())
        self.assertEqual(text.count("Log in"), 1, "one way to log in: the header's")
        self.assertIn("Create a free account", text)
        self.assertIn("Free. You buy straight from the stores, in your sizes. Capsule never takes payment.", text)
        self.assertNotIn("/mock/img", page)
        self.assertNotIn("<img", page)
        self.assertEqual(description(page), "Plan a men's wardrobe where everything goes with everything: "
                                            "about 18 pieces fitted to your budget. Free.")
        self.assertNotIn("model", text + description(page))
        self.assertEqual(description(self.app.test_client().get("/login").get_data(as_text=True)), "",
                         "the description belongs to the landing page")

    def test_the_public_pages_lead_a_customer_to_the_outfits(self):
        ada = self.member("ada@example.com")
        for url in ("/legal/impressum", "/legal/privacy", "/legal/terms"):
            nav = re.search(r'<nav class="public-nav"[^>]*>(.*?)</nav>', ada.get(url).get_data(as_text=True), re.S).group(1)
            self.assertEqual(re.findall(r'href="([^"]*)">([^<]*)</a>', nav), [("/outfits", "Open my outfits")], url)

    def test_reading_the_website_sets_no_cookie(self):
        # A visitor who only reads (the landing page, the legal pages, a page that isn't there, the icon) is given no
        # cookie, so there is nothing to ask consent for. The forms that need one for their token (sign-up, log-in, a
        # forgotten password) still set it through their hidden field, and a customer's buttons still carry the token.
        for url in ("/", "/legal/impressum", "/legal/privacy", "/legal/terms", "/no-such-page", "/favicon.ico"):
            visitor = self.app.test_client()
            for ask in (visitor.get, visitor.head):
                response = ask(url)
                self.assertNotIn("Set-Cookie", response.headers, f"{ask.__name__.upper()} {url}")
                response.close()
            self.assertIsNone(visitor.get_cookie("session"), url)
        for url in ("/signup", "/login", "/forgot"):
            for ask in ("get", "head"):
                response = getattr(self.app.test_client(), ask)(url)
                self.assertEqual(response.status_code, 200, f"{ask.upper()} {url}")
                self.assertIn("session=", response.headers.get("Set-Cookie", ""), f"{ask.upper()} {url}")
        self.assertNotIn("hx-headers", self.app.test_client().get("/").get_data(as_text=True))
        ada = self.member("ada@example.com")
        self.assertIn("hx-headers", ada.get("/legal/privacy").get_data(as_text=True), "a customer's pages carry the token")

    def test_asking_with_head_is_never_taken_for_a_sent_form(self):
        # Link checkers and "curl -I" ask with HEAD. It gets the page, as GET does: it is not a failed log-in (enough of
        # those lock the address out), it asks for no reset link and it doesn't use one up.
        visitor = self.app.test_client()
        for url in ("/login", "/signup", "/forgot"):
            self.assertEqual(visitor.head(url).status_code, 200, url)
        self.assertEqual(db.failed_logins("", "127.0.0.1", settings.LOGIN_WINDOW_SECONDS), (0, 0))
        self.assertNotIn("reset link", visitor.get("/login").get_data(as_text=True), "HEAD /forgot sent the form")
        self.member("ada@example.com")
        self.post(visitor, "/forgot", email="ada@example.com")
        reset = re.search(r"/reset/[\w-]+", mail.OUTBOX[-1]["body"]).group(0)
        self.assertEqual(visitor.head(reset).status_code, 200)
        self.assertEqual(visitor.get(reset).status_code, 200, "the link still works after a HEAD")

    def test_capsule_has_its_own_icons(self):
        # Browsers and search engines ask for /favicon.ico by themselves (Google wants a multiple of 48 px); an iPhone
        # puts the 180 px square on its home screen; Android installs Capsule from the manifest's PNGs, opening the
        # outfits, in the colour of the page. Every file is the size it says it is.
        visitor = self.app.test_client()

        def fetch(url):
            response = visitor.get(url)
            self.assertEqual(response.status_code, 200, url)
            data, kind = response.get_data(), response.mimetype
            response.close()
            return data, kind

        def png_size(data: bytes) -> str:
            self.assertEqual(data[:8], b"\x89PNG\r\n\x1a\n", "not a PNG")
            return f"{int.from_bytes(data[16:20], 'big')}x{int.from_bytes(data[20:24], 'big')}"

        icon, kind = fetch("/favicon.ico")
        self.assertEqual((kind, icon[:4]), ("image/x-icon", b"\x00\x00\x01\x00"), "an ICO file")
        self.assertEqual(png_size(icon[22:]), "48x48")
        touch, kind = fetch("/static/apple-touch-icon.png")
        self.assertEqual((kind, png_size(touch)), ("image/png", "180x180"))

        page = visitor.get("/").get_data(as_text=True)
        for link in ('<link rel="icon" href="/favicon.ico" sizes="48x48">',
                     '<link rel="icon" href="/static/icon.svg" type="image/svg+xml">',
                     '<link rel="apple-touch-icon" href="/static/apple-touch-icon.png">'):
            self.assertIn(link, page)
        self.assertNotIn('rel="icon" href="data:', page)
        manifest = json.loads(fetch("/static/app.webmanifest")[0])
        self.assertEqual(manifest["start_url"], "/outfits", "the installed app opens on the outfits, Capsule's home")
        light = re.search(r'<meta name="theme-color" content="([^"]+)" media="\(prefers-color-scheme: light\)">', page)
        self.assertEqual(manifest["theme_color"], light.group(1))
        pngs = {(i["sizes"], i["purpose"]): i["src"] for i in manifest["icons"] if i["type"] == "image/png"}
        self.assertEqual(set(pngs), {("192x192", "any"), ("512x512", "any"), ("512x512", "maskable")})
        for (sizes, _), src in pngs.items():
            data, kind = fetch(src)
            self.assertEqual((kind, png_size(data)), ("image/png", sizes), src)

    def test_unfinished_pages_and_log_in_stay_out_of_search_results(self):
        # The legal pages say 'Not written yet', and log-in, a forgotten password and a reset link are nothing to find
        # in a search engine. The landing page and sign-up are.
        noindex = '<meta name="robots" content="noindex">'
        visitor = self.app.test_client()
        for url in ("/legal/impressum", "/legal/privacy", "/legal/terms"):
            page = visitor.get(url).get_data(as_text=True)
            self.assertIn(noindex, page, url)
            self.assertIn("Not written yet", page, "the tag goes with the placeholder")
        for url in ("/login", "/forgot"):
            self.assertIn(noindex, visitor.get(url).get_data(as_text=True), url)
        for url in ("/", "/signup"):
            self.assertNotIn(noindex, visitor.get(url).get_data(as_text=True), url)
        self.member("ada@example.com")
        self.post(visitor, "/forgot", email="ada@example.com")
        reset = re.search(r"/reset/[\w-]+", mail.OUTBOX[-1]["body"]).group(0)
        self.assertIn(noindex, visitor.get(reset).get_data(as_text=True))


class Accounts(ProductionCase):
    def test_signing_up_lands_in_your_own_capsule(self):
        ada = self.member("ada@example.com")
        page = ada.get("/")
        self.assertEqual(page.status_code, 200)
        self.assertIn(b"Minimum quality", page.data)
        self.assertIn(b"Demo data", page.data)
        with db.as_user(self.user_id("ada@example.com")):
            self.assertTrue(15 <= len(db.list_slots()) <= 20)
        stored = db.get_user_by_email("ADA@example.com")          # addresses are case-insensitive
        self.assertNotIn(PASSWORD, stored["password_hash"])
        self.assertTrue(stored["password_hash"].startswith(("scrypt:", "pbkdf2:")))

    def test_sign_up_checks_what_it_is_given(self):
        visitor = self.app.test_client()
        self.assertEqual(self.post(visitor, "/signup", email="not-an-address", password=PASSWORD).status_code, 400)
        self.assertEqual(self.post(visitor, "/signup", email="a@example.com", password="short").status_code, 400)
        self.assertEqual(self.post(visitor, "/signup", email="a@example.com", password="a@example.com").status_code, 400)
        self.member("taken@example.com")
        again = self.post(self.app.test_client(), "/signup", email="Taken@Example.com", password=PASSWORD)
        self.assertEqual(again.status_code, 400)
        self.assertIsNone(db.get_user_by_email("a@example.com"))

    def test_log_out_and_back_in(self):
        ada = self.member("ada@example.com")
        self.post(ada, "/logout")
        self.assertEqual(ada.get("/outfits").status_code, 302)
        wrong = self.post(ada, "/login", email="ada@example.com", password="wrong password")
        self.assertEqual(wrong.status_code, 401)
        unknown = self.post(ada, "/login", email="nobody@example.com", password=PASSWORD)
        self.assertEqual(unknown.status_code, 401)
        self.assertIn(b"Email or password is wrong", unknown.data)   # the same answer for both
        back = self.post(ada, "/login", email="ada@example.com", password=PASSWORD, next="/list")
        self.assertEqual((back.status_code, back.headers["Location"]), (302, "/list"))   # back to the page asked for
        elsewhere = self.post(self.app.test_client(), "/login", email="ada@example.com", password=PASSWORD,
                              next="https://evil.example/")
        self.assertEqual(elsewhere.headers["Location"], "/outfits")  # never redirects off the site

    def test_logging_in_opens_the_outfits_and_never_another_site(self):
        self.member("ada@example.com")

        def lands(**next_page) -> str:
            client = self.app.test_client()
            return self.post(client, "/login", email="ada@example.com", password=PASSWORD, **next_page).headers["Location"]

        self.assertEqual(lands(), "/outfits", "the outfits on the model are Capsule's home")
        self.assertEqual(lands(next="/slot/white-tee?sort=score"), "/slot/white-tee?sort=score")
        # Browsers read "\" as "/" and drop tabs and line breaks from an address: each of these leaves the site.
        for elsewhere in ("https://evil.example/", "//evil.example", "/\\evil.example", "\\\\evil.example",
                          "/\t/evil.example", "/\n/evil.example", "javascript:alert(1)", ""):
            self.assertEqual(lands(next=elsewhere), "/outfits", repr(elsewhere))
        bob = self.member("bob@example.com")
        self.assertEqual(bob.get("/login").headers["Location"], "/outfits", "already logged in: straight home")

    def test_guessing_a_password_is_slowed_down(self):
        self.member("ada@example.com")
        guesser = self.app.test_client()
        for _ in range(settings.LOGIN_MAX_FAILURES_PER_EMAIL):
            self.assertEqual(self.post(guesser, "/login", email="ada@example.com", password="guess").status_code, 401)
        locked = self.post(guesser, "/login", email="ada@example.com", password=PASSWORD)
        self.assertEqual(locked.status_code, 429, "even the right password waits once the limit is hit")

    def test_a_forgotten_password_can_be_reset_once(self):
        ada = self.member("ada@example.com")
        visitor = self.app.test_client()
        self.post(visitor, "/forgot", email="nobody@example.com")
        self.assertEqual(mail.OUTBOX, [], "no mail, and the same answer, for an unknown address")
        self.post(visitor, "/forgot", email="ada@example.com")
        link = re.search(r"/reset/[\w-]+", mail.OUTBOX[-1]["body"]).group(0)
        self.assertEqual(visitor.get(link).status_code, 200)
        self.assertEqual(self.post(visitor, link, password="tiny").status_code, 400)
        self.assertEqual(self.post(visitor, link, password="a brand new password").status_code, 302)
        self.assertEqual(visitor.get(link).status_code, 302, "the link works once")
        self.assertEqual(ada.get("/outfits").status_code, 302, "the old session was signed out")
        self.assertEqual(self.post(visitor, "/login", email="ada@example.com", password=PASSWORD).status_code, 401)
        self.assertEqual(self.post(visitor, "/login", email="ada@example.com",
                                   password="a brand new password").status_code, 302)

    def test_changing_the_password_signs_out_other_devices(self):
        laptop = self.member("ada@example.com")
        phone = self.app.test_client()
        self.post(phone, "/login", email="ada@example.com", password=PASSWORD)
        self.assertEqual(phone.get("/outfits").status_code, 200)
        self.post(laptop, "/account/password", current=PASSWORD, password="another long password")
        self.assertEqual(laptop.get("/outfits").status_code, 200, "the device that changed it stays in")
        self.assertEqual(phone.get("/outfits").status_code, 302)
        self.post(laptop, "/account/password", current="wrong", password="yet another password")
        self.assertEqual(self.post(self.app.test_client(), "/login", email="ada@example.com",
                                   password="another long password").status_code, 302)

    def test_a_copy_of_your_data_and_deleting_it_all(self):
        ada = self.member("ada@example.com")
        uid = self.user_id("ada@example.com")
        copy = json.loads(ada.get("/account/export").data)
        self.assertEqual(copy["account"]["email"], "ada@example.com")
        self.assertIn("profile", copy["settings"])
        self.assertTrue(copy["slots"])
        self.assertNotIn("password", json.dumps(copy).lower())

        self.post(ada, "/account/delete", current="wrong password")
        self.assertIsNotNone(db.get_user(uid), "the wrong password deletes nothing")
        self.post(ada, "/account/delete", current=PASSWORD)
        self.assertIsNone(db.get_user(uid))
        with closing(sqlite3.connect(paths.DB_PATH)) as con:
            for table in ("settings", "slots", "saved_outfits", "catalogs", "reset_tokens"):
                rows = con.execute(f"SELECT COUNT(*) FROM {table} WHERE user_id = ?", (uid,)).fetchone()[0]
                self.assertEqual(rows, 0, table)
        self.assertEqual(ada.get("/outfits").status_code, 302)
        self.assertEqual(self.post(ada, "/login", email="ada@example.com", password=PASSWORD).status_code, 401)


class OutfitsIsHome(ProductionCase):
    """The outfits on the AI model are Capsule's home: the first tab, and where log-in and the wordmark lead.
    The plan has no tab: the Wardrobe page, and every message that sends you to it, link to it."""

    BRAND = re.compile(r'<a class="brand" href="([^"]*)">Capsule</a>')
    GONE = ("Slots page", "under Slots", "open Outfits")     # pointers to tabs that no longer exist

    @staticmethod
    def tabs(html: str) -> list[tuple[str, str, bool]]:
        """The tab bar, in order: (name, address, marked as the current page)."""
        nav = re.search(r'<nav class="tabs"[^>]*>(.*?)</nav>', html, re.S).group(1)
        return [(name, href, 'aria-current="page"' in more)
                for href, more, name in re.findall(r'<a href="([^"]*)"([^>]*)>([^<]*)</a>', nav)]

    def test_four_plain_tabs_with_the_outfits_first(self):
        ada = self.member("ada@example.com")
        tabs = [("Outfits", "/outfits"), ("Wardrobe", "/"), ("Shopping", "/list"), ("Profile", "/profile")]
        # The plan and a piece's page belong to the Wardrobe, so its tab stays lit there.
        for url, lit in (("/outfits", "Outfits"), ("/", "Wardrobe"), ("/slots", "Wardrobe"), ("/slot/white-tee", "Wardrobe"),
                         ("/list", "Shopping"), ("/profile", "Profile")):
            shown = self.tabs(ada.get(url).data.decode())
            self.assertEqual([(name, href) for name, href, _ in shown], tabs, url)
            self.assertEqual([name for name, _, on in shown if on], [lit], url)
        account = ada.get("/account").data.decode()
        self.assertEqual([name for name, _, on in self.tabs(account) if on], [], "no tab is lit on Account")
        self.assertRegex(account, r'<a class="account-link on" [^>]*aria-current="page"[^>]*>Account</a>')

    def test_the_wordmark_leads_home(self):
        visitor = self.app.test_client()
        for url in ("/", "/login", "/signup", "/legal/privacy"):
            self.assertEqual(self.BRAND.search(visitor.get(url).data.decode()).group(1), "/", url)
        ada = self.member("ada@example.com")
        for url in ("/", "/outfits", "/list", "/slots", "/slot/white-tee", "/profile", "/account", "/legal/privacy"):
            self.assertEqual(self.BRAND.search(ada.get(url).data.decode()).group(1), "/outfits", url)

    def test_one_main_heading_on_every_main_page(self):
        ada = self.member("ada@example.com")
        for url, heading in (("/outfits", "Outfits"), ("/", "Your wardrobe"), ("/list", "Shopping list"),
                             ("/slots", "Your plan"), ("/profile", "About you"), ("/account", "Your account")):
            self.assertEqual(re.findall(r"<h1[^>]*>([^<]*)</h1>", ada.get(url).data.decode()), [heading], url)
        plan = ada.get("/slots").data.decode()
        self.assertIn("<title>Your plan · Capsule</title>", plan)
        self.assertRegex(plan, re.compile(r'<p class="crumb"><a href="/">.*?Wardrobe</a></p>', re.S))

    def test_edit_the_plan_is_one_tap_from_the_wardrobe(self):
        ada = self.member("ada@example.com")
        with db.as_user(self.user_id("ada@example.com")):
            pieces = sum(s["qty"] for s in db.list_slots())     # a white tee ×2 is two pieces, as in the bar
        self.assertIn(f'{pieces} pieces in your plan · <a href="/slots">Edit the plan</a>', ada.get("/").data.decode())
        with db.as_user(self.user_id("ada@example.com")):
            db.replace_slots([])
        empty = ada.get("/").data.decode()
        self.assertIn('No pieces in your plan yet. <a href="/slots">Edit the plan</a> to add some', empty)
        self.assertNotIn("in your plan ·", empty)
        for gone in self.GONE:
            self.assertNotIn(gone, empty)

    def test_messages_that_send_you_to_the_plan_carry_the_link(self):
        ada = self.member("ada@example.com")
        form = {"top_size": "M", "waist": "32", "length": "32", "shoe": "43", "height_cm": "180", "weight_kg": "75",
                "budget": "1500", "liked": "black, grey, white", "refused": "", "use": "both", "shoes": "on",
                "outerwear": "on", "owned": "<b>lucky</b> charm"}
        saved = self.post(ada, "/profile", **form)
        self.assertEqual(saved.headers["Location"], "/outfits", "the rebuilt plan is shown on the model")
        rebuilt = ada.get("/outfits").data.decode()
        with db.as_user(self.user_id("ada@example.com")):
            pieces = sum(s["qty"] for s in db.list_slots())
            first = db.list_slots()[0]
        self.assertIn(f"Your plan now has {pieces} pieces in your colours.", rebuilt)
        self.assertIn('“&lt;b&gt;lucky&lt;/b&gt; charm” is: add it to your plan by hand. <a href="/slots">Edit the plan</a>',
                      rebuilt, "what the customer typed is shown as text, the link as a link")
        self.assertNotIn("<b>lucky</b>", rebuilt)

        # A plan changed on the plan page is not rebuilt without asking; the message leads to the plan.
        self.post(ada, f"/slots/{first['id']}/save", name="My own name", category=first["category"],
                  colour=first["colour"], qty=str(first["qty"]))
        self.post(ada, "/profile", **{**form, "liked": "navy, grey", "owned": ""})
        kept = ada.get("/profile").data.decode()
        self.assertIn('To rebuild it from these answers, use “Start over from my profile” on '
                      '<a href="/slots">the plan page</a>.', kept)
        self.assertIn("Start over from my profile</button>", ada.get("/slots").data.decode(), "the button it names")
        for page in (rebuilt, kept):
            for gone in self.GONE:
                self.assertNotIn(gone, page)


class Isolation(ProductionCase):
    def test_two_customers_never_see_each_others_wardrobe(self):
        ada, bob = self.member("ada@example.com"), self.member("bob@example.com")
        a, b = self.user_id("ada@example.com"), self.user_id("bob@example.com")

        self.post(ada, "/slots/add", name="Ada's secret scarf slot", category="cardigan", colour="burgundy", qty="1")
        self.post(ada, "/slot/white-tee/own")
        with db.as_user(a):
            ada_slots = {s["id"] for s in db.list_slots()}
            ada_total = selection.build().total
            self.assertTrue(db.get_slot("white-tee")["owned"])
        with db.as_user(b):
            bob_slots = {s["id"] for s in db.list_slots()}
            self.assertFalse(db.get_slot("white-tee")["owned"])
            self.assertNotEqual(selection.build().total, ada_total)
        secret = (ada_slots - bob_slots).pop()

        self.assertNotIn(b"secret scarf", bob.get("/slots").data)
        self.assertEqual(bob.get(f"/slot/{secret}").status_code, 404)
        self.assertEqual(self.post(bob, f"/slots/{secret}/delete").status_code, 404)
        self.assertEqual(self.post(bob, f"/slot/{secret}/own").status_code, 404)
        with db.as_user(a):
            self.assertIsNotNone(db.get_slot(secret), "still there for its owner")

        export = json.loads(bob.get("/account/export").data)
        self.assertNotIn("secret scarf", json.dumps(export))

    def test_saved_outfits_and_added_items_are_private_too(self):
        ada, bob = self.member("ada@example.com"), self.member("bob@example.com")
        with db.as_user(self.user_id("ada@example.com")):
            knit = next(s["id"] for s in db.list_slots() if s["category"] == "knit")
        link = "https://www.cos.com/de-de/x/product/slim-merino-wool-crew-neck-jumper-black-1260173010"
        self.post(ada, f"/slot/{knit}/import", urls=link)
        self.assertIn(b"Slim merino wool crew neck jumper", ada.get(f"/slot/{knit}").data)
        self.assertNotIn(b"Slim merino wool crew neck jumper", bob.get(f"/slot/{knit}").data)

        key = re.search(r'id="outfit-(\w+)"', ada.get("/outfits").data.decode()).group(1)
        self.assertEqual(self.post(ada, "/outfits/save", headers=HX, key=key).status_code, 200)
        self.assertIn(b"Saved 1", ada.get("/outfits").data)
        self.assertNotIn(b"Saved 1", bob.get("/outfits").data)

    def test_the_database_refuses_to_guess_whose_data_is_meant(self):
        with self.assertRaises(RuntimeError):
            db.list_slots()                      # no request, no signed-in user: nothing is returned
        with self.assertRaises(RuntimeError):
            db.set_setting("mode", "cheapest")


class Guards(ProductionCase):
    def test_every_change_needs_the_pages_own_token(self):
        ada = self.member("ada@example.com")
        self.assertEqual(ada.post("/settings", data={"mode": "cheapest"}).status_code, 400)
        self.assertEqual(ada.post("/settings", data={"mode": "cheapest", "csrf_token": "made-up"}).status_code, 400)
        self.assertEqual(ada.post("/logout").status_code, 400)
        with_header = ada.post("/settings", data={"mode": "cheapest", "threshold": "70"},
                               headers={**HX, "X-CSRF-Token": self.token(ada)})
        self.assertEqual(with_header.status_code, 200)
        page = ada.get("/").data.decode()
        self.assertIn(f'"X-CSRF-Token": "{self.token(ada)}"', page.replace("&#34;", '"'))
        self.assertEqual(page.count('name="csrf_token"'), page.count("<form"), "every form carries the token")
        other_site = ada.post("/settings", data={"mode": "good", "csrf_token": self.token(ada)},
                              headers={"Origin": "https://evil.example"})
        self.assertEqual(other_site.status_code, 403)

    def test_no_browser_is_ever_opened_on_the_server(self):
        ada = self.member("ada@example.com")
        with db.as_user(self.user_id("ada@example.com")):
            knit = next(s["id"] for s in db.list_slots() if s["category"] == "knit")
        with mock.patch("wardrobe.collect.manual.Session", side_effect=AssertionError("a browser was started")):
            response = self.post(ada, f"/slot/{knit}/import",
                                 urls="https://www.zara.com/de/de/pullover-regular-fit-100-wolle-p05755370.html")
        self.assertEqual(response.status_code, 302)
        self.assertIn(b"Pullover regular fit 100 wolle", ada.get(f"/slot/{knit}").data)

        from wardrobe.__main__ import main
        for command in (["refresh"], ["mock"], ["serve"]):
            with self.assertRaises(SystemExit) as stop:
                main(command)
            self.assertIn("production", str(stop.exception))

    def test_a_crash_shows_a_plain_page_not_a_stack_trace(self):
        ada = self.member("ada@example.com")
        with mock.patch("wardrobe.selection.build", side_effect=ValueError("secret internals")):
            response = ada.get("/outfits")
        self.assertEqual(response.status_code, 500)
        text = unescape(words(response.get_data(as_text=True)))
        self.assertIn("Something went wrong on our side It's not you. Try again in a minute. Go to your outfits", text)
        self.assertNotIn(b"secret internals", response.data)
        self.assertNotIn(b"Traceback", response.data)
        self.assertEqual(ada.get("/no-such-page").status_code, 404)

    def test_new_accounts_per_connection_are_limited(self):
        with mock.patch.object(settings, "SIGNUPS_PER_IP_PER_HOUR", 2):
            self.member("one@example.com")
            self.member("two@example.com")
            third = self.post(self.app.test_client(), "/signup", email="three@example.com", password=PASSWORD)
        self.assertEqual(third.status_code, 400)
        self.assertIsNone(db.get_user_by_email("three@example.com"))


class ErrorPages(ProductionCase):
    """An error page says what happened in Capsule's words, never in Werkzeug's sentences for developers, with the
    wordmark, the way home and the legal links."""

    LEGAL = [("/legal/impressum", "Impressum"), ("/legal/privacy", "Privacy policy"), ("/legal/terms", "Terms of use")]

    @staticmethod
    def links(html: str) -> list[tuple[str, str]]:
        return [(href, unescape(name)) for href, name in re.findall(r'<a [^>]*href="([^"]*)"[^>]*>([^<]*)</a>', html)]

    def test_a_page_that_is_not_there_says_so_in_capsules_words(self):
        missing = self.app.test_client().get("/no-such-page")
        self.assertEqual(missing.status_code, 404)
        page = missing.get_data(as_text=True)
        text = unescape(words(page))
        self.assertIn("We can't find that page The link may be old, or the page may have moved.", text)
        self.assertIn("<title>We can&#39;t find that page · Capsule</title>", page)
        for werkzeug in ("requested URL", "on the server", "check your spelling"):
            self.assertNotIn(werkzeug, text)
        self.assertEqual(self.links(page), [("/", "Capsule"), ("/", "Go to the home page"), *self.LEGAL])
        self.assertRegex(page, r'<a class="brand" href="/">Capsule</a>', "the wordmark, as on every page")

        ada = self.member("ada@example.com")
        mine = ada.get("/no-such-page").get_data(as_text=True)
        self.assertEqual(self.links(mine), [("/outfits", "Capsule"), ("/outfits", "Go to your outfits"), *self.LEGAL])
        # An address that only takes a form, opened as a page, is one that isn't there for the customer.
        self.assertIn("We can't find that page", unescape(words(ada.get("/logout").get_data(as_text=True))))

    def test_a_form_that_did_not_go_through_says_so_in_capsules_words(self):
        ada = self.member("ada@example.com")
        # Sent without the page's token (a page kept open too long): Capsule's own message is shown.
        stale = ada.post("/settings", data={"mode": "cheapest"})
        self.assertEqual(stale.status_code, 400)
        self.assertIn("That didn't go through This page was open for too long or was not sent from Capsule. "
                      "Reload it and try again. Go to your outfits", unescape(words(stale.get_data(as_text=True))))
        # A form from another website: Capsule's line in place of Werkzeug's "You don't have the permission to…".
        foreign = ada.post("/settings", data={"mode": "cheapest", "csrf_token": self.token(ada)},
                           headers={"Origin": "https://evil.example"})
        self.assertEqual(foreign.status_code, 403)
        text = unescape(words(foreign.get_data(as_text=True)))
        self.assertIn("That didn't go through Reload the page and try again.", text)
        self.assertNotIn("permission", text)
        # Capsule's own words given to abort() take the place of the line.
        gone = self.post(ada, "/outfits/save", key="no-such-outfit")
        self.assertEqual(gone.status_code, 409)
        self.assertIn("That changed in the meantime That outfit no longer exists — reload the page.",
                      unescape(words(gone.get_data(as_text=True))))


CODE = "by-invitation-2026"


class ByInvitation(ProductionCase):
    """INVITE_CODE is set: the website is open to all, creating an account needs the code."""

    def setUp(self):
        super().setUp()
        invited = mock.patch.object(settings, "INVITE_CODE", CODE)
        invited.start()
        self.addCleanup(invited.stop)

    def join(self, email, **more):
        return self.post(self.app.test_client(), "/signup", email=email, password=PASSWORD, **more)

    def test_the_pages_say_so(self):
        visitor = self.app.test_client()
        self.assertIn(b"by invitation", visitor.get("/").data)
        self.assertIn(b'name="code"', visitor.get("/signup").data)

    def test_no_account_without_the_code(self):
        for attempt in ({}, {"code": ""}, {"code": "by-invitation-2025"}, {"code": CODE.upper()}):
            refused = self.join("eve@example.com", **attempt)
            self.assertEqual(refused.status_code, 400, attempt)
            self.assertIn(b"invitation code is not right", refused.data)
        self.assertIsNone(db.get_user_by_email("eve@example.com"))

    def test_the_code_lets_you_in(self):
        self.assertEqual(self.join("ada@example.com", code=f" {CODE} ").status_code, 302)      # pasted with spaces around it
        self.assertIsNotNone(db.get_user_by_email("ada@example.com"))

    def test_an_invitation_link_fills_the_code_in(self):
        page = self.app.test_client().get(f"/signup?code={CODE}")
        self.assertIn(f'value="{CODE}"'.encode(), page.data)

    def test_the_code_cannot_be_tried_at_speed(self):
        with mock.patch.object(settings, "SIGNUPS_PER_IP_PER_HOUR", 3):
            for guess in range(3):
                self.assertEqual(self.join("eve@example.com", code=f"guess-number-{guess}").status_code, 400)
            late = self.join("eve@example.com", code=CODE)
        self.assertEqual(late.status_code, 400, "the right code, after too many wrong ones from the same connection")
        self.assertIn(b"Too many", late.data)
        self.assertIsNone(db.get_user_by_email("eve@example.com"))

    def test_what_is_not_counted_says_nothing_about_the_code(self):
        # A form that is refused before it is counted (here: a password too short) must be refused
        # the same way with the right code and with a wrong one.
        wrong = self.post(self.app.test_client(), "/signup", email="eve@example.com", password="short", code="a-wrong-guess")
        right = self.post(self.app.test_client(), "/signup", email="eve@example.com", password="short", code=CODE)
        self.assertEqual((wrong.status_code, right.status_code), (400, 400))
        for answer in (wrong, right):
            self.assertNotIn(b"invitation code is not right", answer.data)

    def test_those_who_have_an_account_log_in_as_before(self):
        with mock.patch.object(settings, "INVITE_CODE", ""):
            self.member("ada@example.com")
        back = self.post(self.app.test_client(), "/login", email="ada@example.com", password=PASSWORD)
        self.assertEqual(back.status_code, 302)

    def test_a_code_too_short_to_keep_anybody_out_stops_the_start(self):
        with mock.patch.object(settings, "INVITE_CODE", "abc"), self.assertRaises(SystemExit) as stop:
            create_app()
        self.assertIn("INVITE_CODE", str(stop.exception))

    def test_without_a_code_anybody_may_join(self):
        with mock.patch.object(settings, "INVITE_CODE", ""):
            visitor = self.app.test_client()
            self.assertNotIn(b'name="code"', visitor.get("/signup").data)
            self.assertNotIn(b"by invitation", visitor.get("/").data)
            self.assertEqual(self.join("ada@example.com").status_code, 302)


class BehindCloudflare(ProductionCase):
    """TRUSTED_PROXY_HOPS=1: the app sits behind one proxy (Cloudflare's tunnel) that passes on who
    is asking and whether they came by https. Every request then arrives from the proxy's own address."""

    def setUp(self):
        super().setUp()
        proxied = mock.patch.object(settings, "TRUSTED_PROXY_HOPS", 1)
        proxied.start()
        self.addCleanup(proxied.stop)
        self.app = create_app()

    def join(self, email, came_from):
        """A sign-up as the proxy hands it over: its own note of the visitor's address comes last."""
        client = self.app.test_client()
        headers = {"X-Forwarded-For": came_from, "X-Forwarded-Proto": "https"}
        client.get("/login", headers=headers)
        with client.session_transaction() as session:
            token = session["csrf"]
        return client.post("/signup", data={"email": email, "password": PASSWORD, "csrf_token": token}, headers=headers)

    def test_limits_count_the_visitor_not_the_proxy(self):
        with mock.patch.object(settings, "SIGNUPS_PER_IP_PER_HOUR", 2):
            self.assertEqual(self.join("one@example.com", "203.0.113.7").status_code, 302)
            self.assertEqual(self.join("two@example.com", "203.0.113.7").status_code, 302)
            self.assertEqual(self.join("three@example.com", "203.0.113.7").status_code, 400, "the third from one visitor")
            self.assertEqual(self.join("four@example.com", "198.51.100.9").status_code, 302, "another visitor is not held up")

    def test_a_visitor_cannot_pose_as_somebody_else(self):
        # Whatever a visitor writes into the header themselves comes before the proxy's own entry.
        with mock.patch.object(settings, "SIGNUPS_PER_IP_PER_HOUR", 2):
            self.assertEqual(self.join("one@example.com", "10.0.0.1, 203.0.113.7").status_code, 302)
            self.assertEqual(self.join("two@example.com", "10.0.0.2, 203.0.113.7").status_code, 302)
            self.assertEqual(self.join("three@example.com", "10.0.0.3, 203.0.113.7").status_code, 400)

    def test_https_at_the_proxy_counts_as_https(self):
        visitor = self.app.test_client()
        by_https = visitor.get("/login", headers={"X-Forwarded-For": "203.0.113.7", "X-Forwarded-Proto": "https"})
        self.assertIn("max-age", by_https.headers.get("Strict-Transport-Security", ""))
        plain = visitor.get("/login", headers={"X-Forwarded-For": "203.0.113.7", "X-Forwarded-Proto": "http"})
        self.assertNotIn("Strict-Transport-Security", plain.headers)

    def test_without_a_proxy_the_header_is_not_believed(self):
        with mock.patch.object(settings, "TRUSTED_PROXY_HOPS", 0), mock.patch.object(settings, "SIGNUPS_PER_IP_PER_HOUR", 2):
            self.app = create_app()
            self.assertEqual(self.join("one@example.com", "203.0.113.7").status_code, 302)
            self.assertEqual(self.join("two@example.com", "198.51.100.9").status_code, 302)
            self.assertEqual(self.join("three@example.com", "192.0.2.44").status_code, 400, "all three came from one connection")


def product(store, sku, name, price, colour, hex_=None, **more):
    return {"id": f"{store}-{sku}", "slot_id": more.pop("slot_id", "grey-merino-jumper"), "store": store, "name": name,
            "slug": name.lower().replace(" ", "-"), "price": price, "colour": colour, "colour_hex": hex_,
            "composition_text": more.pop("fabric", ""), "fit": "regular", "sizes_all": ["S", "M", "L"],
            "sizes_in_stock": ["S", "M", "L"], "url": f"https://www.example.com/{sku}", "image_url": "",
            "source": more.pop("source", "collected"), **more}


class SharedStoreCatalogue(ProductionCase):
    """Real products for customers: published once, matched to each customer's own slots."""

    def publish(self, extra=()):
        """What `python -m wardrobe publish <this service's folder>` does on the operator's machine."""
        settings.PRODUCTION = False
        try:
            db.ensure_local_user()
            db.replace_slots([
                {"id": "grey-merino-jumper", "name": "Grey merino jumper", "category": "knit", "colour": "grey"},
                {"id": "white-tee", "name": "White tee", "category": "tee", "colour": "white"}])
            catalog.save({"source": "collected", "collected_at": "2026-11-11T17:00:00+01:00", "stores": {}, "candidates": [
                product("zara", "1", "Pullover aus Merinowolle", 49.95, "Grau", fabric="100% Merinowolle"),
                product("cos", "2", "Merino jumper", 89.0, "GREY", "#8d8e91"),
                product("zara", "3", "Pullover", 29.95, "Marineblau"),
                product("zara", "4", "Basic T-Shirt", 12.95, "Weiß", slot_id="white-tee", fabric="100% Baumwolle"),
                product("cos", "5", "My own find", 10.0, "Grau", source="manual"),
                *extra]})
            return shared.publish(paths.DATA_DIR)
        finally:
            settings.PRODUCTION = True
            catalog._cache = None

    def knit(self, email, slot="grey-merino-jumper"):
        with db.as_user(self.user_id(email)):
            return [c.id for c in selection.build().get(slot).cands]

    def test_new_customers_start_on_real_products(self):
        self.assertEqual(self.publish(), 4, "your own additions are not published")
        ada = self.member("ada@example.com")
        page = ada.get("/").data
        self.assertNotIn(b"Demo data", page)
        self.assertIn(b"Pullover aus Merinowolle", page)
        self.assertEqual(sorted(self.knit("ada@example.com")), ["cos-2", "zara-1"], "grey ones only, from both stores")
        self.assertEqual(self.knit("ada@example.com", "white-tee"), ["zara-4"])
        with db.as_user(self.user_id("ada@example.com")):
            w = selection.build()
            self.assertEqual(w.source, "collected")
            self.assertGreater(w.n_unfilled, 0, "slots nobody collected stay empty rather than invented")
        self.assertNotIn(b"python -m wardrobe", ada.get("/").data, "customers are not told to run commands")

    def test_products_follow_the_garment_and_colour_not_the_slots_name(self):
        self.publish()
        ada = self.member("ada@example.com")
        self.post(ada, "/slots/add", name="A second grey knit", category="knit", colour="grey", qty="1")
        self.assertEqual(sorted(self.knit("ada@example.com", "a-second-grey-knit")), ["cos-2", "zara-1"])
        self.post(ada, "/slots/grey-merino-jumper/save", name="Navy jumper", category="knit", colour="navy", qty="1")
        self.assertEqual(self.knit("ada@example.com"), ["zara-3"], "recolouring a slot changes what fits it")

    def test_customers_on_demo_data_move_to_real_data_when_it_is_published(self):
        ada = self.member("ada@example.com")
        self.assertIn(b"Demo data", ada.get("/").data)
        self.publish()
        self.assertNotIn(b"Demo data", ada.get("/").data)
        self.assertEqual(sorted(self.knit("ada@example.com")), ["cos-2", "zara-1"])

    def test_a_newer_catalogue_keeps_what_the_customer_added_and_typed(self):
        self.publish()
        ada = self.member("ada@example.com")
        self.post(ada, "/slot/grey-merino-jumper/details", candidate="cos-2", composition="100% Merinowolle")
        self.post(ada, "/slot/grey-merino-jumper/import", urls="https://www.cos.com/de-de/x/product/another-jumper-grey-1234567890")
        self.publish(extra=[product("weekday", "9", "Wollpullover", 59.99, "Grau")])
        ada.get("/")
        self.assertEqual(sorted(self.knit("ada@example.com")), ["cos-1234567890", "cos-2", "weekday-9", "zara-1"])
        with db.as_user(self.user_id("ada@example.com")):
            cos = next(c for c in selection.build().get("grey-merino-jumper").cands if c.id == "cos-2")
            self.assertEqual(cos.score.fabric_source, "listed", "the fabric she typed in is still there")

    def test_a_piece_nothing_was_found_for_links_to_the_plan(self):
        self.publish()
        ada = self.member("ada@example.com")
        with db.as_user(self.user_id("ada@example.com")):
            empty = next(s.slot["id"] for s in selection.build().slots if not s.cands and s.state != "owned")
        page = ada.get(f"/slot/{empty}").data.decode()
        self.assertIn(f'<a href="/slots#slot-{empty}">Edit the plan</a> to give it another colour', page)
        self.assertNotIn("Slots page", page)

    def test_customers_are_never_told_to_run_a_command(self):
        # On your own machine a new piece that nothing was collected for says to run "python -m wardrobe refresh".
        # A customer can't, so a customer never reads it, even when the shared store list can't be read just then.
        self.publish()
        ada = self.member("ada@example.com")
        with mock.patch.object(shared, "build_catalog", return_value=None):
            added = self.post(ada, "/slots/add", name="A burgundy cardigan", category="cardigan", colour="burgundy", qty="1")
        page = ada.get(added.headers["Location"].split("#")[0]).get_data(as_text=True)
        self.assertIn("A burgundy cardigan", page)
        self.assertNotIn("python -m wardrobe", page)

    def test_publishing_is_done_from_your_own_machine(self):
        from wardrobe.__main__ import main
        with self.assertRaises(SystemExit) as stop:
            main(["publish", str(paths.DATA_DIR)])
        self.assertIn("production", str(stop.exception))


class StartedTheWayTheGuideSays(unittest.TestCase):
    """PRODUCTION.md starts the service with WARDROBE_DATA_DIR=./data-production: a folder named
    from where you stand, not by its full path. The other tests all name theirs in full."""

    ASK_FOR_A_PICTURE = """
import time
from wardrobe import db, looks, paths
from wardrobe.app import create_app

app = create_app()
db.init()
key = "ab" * 12
name = f"{key}-{int(time.time())}.png"
looks.folder().mkdir(parents=True, exist_ok=True)
(looks.folder() / name).write_bytes(b"a picture")
db.start_look(key, "a test", 0, 0)
db.touch_look(key)
db.finish_look(key, name)
print(paths.DATA_DIR)
print(app.test_client().get(f"/looks/{name}").status_code)
"""

    def test_a_drawn_picture_is_found_again_when_the_data_folder_is_named_from_where_you_stand(self):
        # It was drawn, saved and announced on the page, and then could not be sent: Flask took
        # "data-production/looks/…" as lying inside the app's own folder (a 500 for every picture).
        settings_of_a_first_start = {name: value for name, value in os.environ.items()
                                     if name not in ("CAPSULE_ENV", "SECRET_KEY", "SITE_URL")}
        with tempfile.TemporaryDirectory() as where:
            ran = subprocess.run(
                [sys.executable, "-c", self.ASK_FOR_A_PICTURE], cwd=where, capture_output=True, text=True,
                env={**settings_of_a_first_start, "WARDROBE_DATA_DIR": "./data-production", "PYTHONPATH": str(paths.ROOT)})
            self.assertEqual(ran.returncode, 0, ran.stderr[-2000:])
            folder, status = ran.stdout.splitlines()[-2:]
            self.assertEqual(Path(folder), Path(where).resolve() / "data-production")
            self.assertEqual(status, "200", ran.stderr[-2000:])


class LocalModeStillWorks(unittest.TestCase):
    """On your own machine nothing changes: no login, one implicit user, and old data is carried over."""

    def setUp(self):
        fresh_files()

    def test_no_accounts_on_your_own_machine(self):
        client = create_app().test_client()
        self.assertEqual(client.get("/").status_code, 200)
        self.assertIn(b"Minimum quality", client.get("/").data)
        self.assertEqual(client.get("/login").status_code, 404)
        self.assertEqual(client.post("/settings", data={"mode": "cheapest", "threshold": "70"}).status_code, 302)
        self.assertNotIn(b"csrf_token", client.get("/slots").data)

    def test_the_outfits_are_home_here_too(self):
        client = create_app().test_client()
        self.assertIn('<a class="brand" href="/outfits">Capsule</a>', client.get("/").data.decode())
        self.assertIn('<a href="/outfits" class="on" aria-current="page">Outfits</a>', client.get("/outfits").data.decode())
        client.post("/profile/model", data={"build": "athletic"})
        profile = client.get("/profile").data.decode()
        self.assertRegex(profile, r'Model saved\.[^<]* <a href="/outfits">See your outfits</a></p>')
        self.assertEqual(re.findall(r"<h1[^>]*>([^<]*)</h1>", profile), ["About you"], "'Your model' is a section of it")

    def test_a_database_from_before_accounts_is_carried_over(self):
        paths.DATA_DIR.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(paths.DB_PATH)) as con:  # the single-user layout of version 1
            con.executescript("""
                CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE slots (id TEXT PRIMARY KEY, position INTEGER NOT NULL, name TEXT NOT NULL,
                    category TEXT NOT NULL, colour TEXT NOT NULL, keywords TEXT NOT NULL DEFAULT '',
                    qty INTEGER NOT NULL DEFAULT 1, owned INTEGER NOT NULL DEFAULT 0,
                    locked INTEGER NOT NULL DEFAULT 0, pick TEXT);
                CREATE TABLE saved_outfits (key TEXT PRIMARY KEY, saved_at TEXT NOT NULL, label TEXT NOT NULL,
                    pieces TEXT NOT NULL);
                INSERT INTO settings VALUES ('mode', '"cheapest"'), ('slots_initialised', 'true');
                INSERT INTO slots VALUES ('white-tee', 0, 'White tee', 'tee', 'white', 'heavyweight', 2, 1, 0, NULL);
                INSERT INTO saved_outfits VALUES ('abc', '2026-11-11T12:00:00+01:00', 'Everyday', '[]');
            """)
        db.init()
        self.assertEqual(db.get_setting("mode"), "cheapest")
        slot = db.get_slot("white-tee")
        self.assertEqual((slot["name"], slot["qty"], slot["owned"]), ("White tee", 2, True))
        self.assertEqual(db.saved_keys(), {"abc"})
        with closing(sqlite3.connect(paths.DB_PATH)) as con:
            tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
            self.assertFalse({t for t in tables if t.endswith("_v1")}, "the old tables are gone")
            self.assertEqual(con.execute("PRAGMA user_version").fetchone()[0], db.SCHEMA_VERSION)
        db.init()                                            # running it again changes nothing
        self.assertEqual(len(db.list_slots()), 1)


if __name__ == "__main__":
    unittest.main()
