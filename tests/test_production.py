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
        back = self.post(ada, "/login", email="ada@example.com", password=PASSWORD, next="/outfits")
        self.assertEqual((back.status_code, back.headers["Location"]), (302, "/outfits"))
        elsewhere = self.post(self.app.test_client(), "/login", email="ada@example.com", password=PASSWORD,
                              next="https://evil.example/")
        self.assertEqual(elsewhere.headers["Location"], "/")         # never redirects off the site

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
        self.assertIn(b"Something went wrong", response.data)
        self.assertNotIn(b"secret internals", response.data)
        self.assertEqual(ada.get("/no-such-page").status_code, 404)

    def test_new_accounts_per_connection_are_limited(self):
        with mock.patch.object(settings, "SIGNUPS_PER_IP_PER_HOUR", 2):
            self.member("one@example.com")
            self.member("two@example.com")
            third = self.post(self.app.test_client(), "/signup", email="three@example.com", password=PASSWORD)
        self.assertEqual(third.status_code, 400)
        self.assertIsNone(db.get_user_by_email("three@example.com"))


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
