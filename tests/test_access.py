"""Behind Cloudflare Access (wardrobe/access.py): whoever Cloudflare has checked needs no password.

A private trial sits behind Cloudflare Access: Cloudflare asks each visitor for his email address, sends a code to it,
and lets through only the addresses on the owner's list. It then says whose address it checked, in a signed token on
every request. With ACCESS_TEAM and ACCESS_AUD set, Stilsmith reads that token: one button makes such a visitor's
account, with no password, and Cloudflare's check opens it from then on.

Everything here is invented: the team, its tag, every address. The tests make key pairs of their own, sign tokens
with them as Cloudflare signs its own, and stand in for the team's address, so no test opens a network connection.
"""
import base64
import contextlib
import hashlib
import hmac
import io
import json
import logging
import sqlite3
import subprocess
import sys
import time
import unittest
import urllib.request
from contextlib import closing
from pathlib import Path
from unittest import mock

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from wardrobe import access, db, guests, mail, paths, settings
from wardrobe.__main__ import main
from wardrobe.app import create_app

from .test_production import HX, PASSWORD, ProductionCase, words

TEAM = "example-team"
AUD = "0a1b2c3d" * 8               # as Cloudflare's tags are: 64 letters and digits
ISSUER = f"https://{TEAM}.cloudflareaccess.com"
PAGE = {"Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"}     # as a browser opens a page

_PAIRS: dict = {}


def pair(kid: str):
    """The key pair with this id: made once for the whole run (making one takes a moment)."""
    if kid not in _PAIRS:
        _PAIRS[kid] = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return _PAIRS[kid]


def listed(*kids: str) -> bytes:
    """What the team's address answers: its public keys, in the shape Cloudflare lists them."""
    keys = [{**jwt.algorithms.RSAAlgorithm.to_jwk(pair(kid).public_key(), as_dict=True),
             "kid": kid, "alg": "RS256", "use": "sig"} for kid in kids]
    certs = [{"kid": kid, "cert": "-----BEGIN CERTIFICATE-----\n…\n-----END CERTIFICATE-----"} for kid in kids]
    return json.dumps({"keys": keys, "public_cert": certs[0], "public_certs": certs}).encode()


def claims(email: str | None = "ada@example.com", **changes) -> dict:
    """What Cloudflare's token says about someone it has checked. A value of None leaves that claim out."""
    now = int(time.time())
    said = {"aud": [AUD], "email": email, "exp": now + 3600, "iat": now, "nbf": now, "iss": ISSUER, "type": "app",
            "identity_nonce": "6ei69kawdKzMIAPF", "sub": "7335d417-61da-459d-899c-0a01c76a2f94", "country": "DE"}
    said.update(changes)
    return {name: value for name, value in said.items() if value is not None}


def token(email: str | None = "ada@example.com", kid: str = "key-1", signed_with: str | None = None, **changes) -> str:
    """A token as Cloudflare signs one: with the key `kid` names (or, for a forgery, with another)."""
    return jwt.encode(claims(email, **changes), pair(signed_with or kid), algorithm="RS256", headers={"kid": kid})


def raw(header: dict, said: dict, signature: bytes = b"") -> str:
    """A token put together by hand, for the ones no library would sign."""
    def part(value) -> str:
        data = value if isinstance(value, bytes) else json.dumps(value).encode()
        return base64.urlsafe_b64encode(data).rstrip(b"=").decode()
    return f"{part(header)}.{part(said)}.{part(signature)}"


def by(email: str | None = "ada@example.com", **changes) -> dict:
    """The headers of a page opened by someone Cloudflare has checked as `email`."""
    return {access.HEADER: token(email, **changes), **PAGE}


class BehindAccess(ProductionCase):
    """The public site with Cloudflare Access in front, and a stand-in for the team's address."""

    def setUp(self):
        for name, value in (("ACCESS_TEAM", TEAM), ("ACCESS_AUD", AUD)):
            patch = mock.patch.object(settings, name, value)
            patch.start()
            self.addCleanup(patch.stop)
        self.kids, self.down, self.asked = ["key-1"], False, []
        self.now = 1000.0
        for target, name, stand_in in ((access._opener, "open", self.team_answers), (access, "_clock", lambda: self.now)):
            patch = mock.patch.object(target, name, side_effect=stand_in)
            patch.start()
            self.addCleanup(patch.stop)
        access.forget_keys()
        self.addCleanup(access.forget_keys)
        # Refusals are written to the log, one line per kind. Here they are meant: kept off the screen, except
        # where a test reads them (assertLogs).
        log = logging.getLogger("capsule.access")
        log.setLevel(logging.CRITICAL)
        self.addCleanup(log.setLevel, logging.NOTSET)
        super().setUp()

    def team_answers(self, address, timeout=None):
        self.asked.append(address)
        self.assertEqual(timeout, access.TIMEOUT, "a page waits for this: it must give up soon")
        if self.down:
            raise OSError("the team's address cannot be reached")
        return io.BytesIO(self.down_answer if hasattr(self, "down_answer") else listed(*self.kids))

    def press(self, client, email: str | None = "ada@example.com", headers=None, **form):
        """The one button, pressed by someone Cloudflare has checked as `email`."""
        return self.post(client, "/checked", headers=headers if headers is not None else by(email), **form)

    def newcomer(self, email: str = "ada@example.com"):
        """A browser whose user Cloudflare has checked, and who has made his account with the one button."""
        client = self.app.test_client()
        answer = self.press(client, email)
        self.assertEqual((answer.status_code, answer.headers["Location"]), (302, "/welcome"), answer.data[:300])
        return client

    def who(self, client) -> str | None:
        """The address of the account this browser is logged in to, by its cookie."""
        with client.session_transaction() as session:
            user = db.get_user(session["uid"]) if "uid" in session else None
        return user["email"] if user else None

    def said(self, client, address: str = "/login") -> str:
        """The words of the next page: the message a redirect left is on it."""
        return words(client.get(address).get_data(as_text=True))


class WhatATokenIsWorth(BehindAccess):
    def test_cloudflares_own_token_names_the_address(self):
        self.assertEqual(access.email_in(token("Ada@Example.com ")), "ada@example.com", "in small letters, as accounts are")
        self.assertEqual(self.asked, [f"{ISSUER}/cdn-cgi/access/certs"], "the keys come from the team's own address")
        # The tag may stand alone, or among others (Cloudflare sends a list of one).
        self.assertEqual(access.email_in(token(aud=AUD)), "ada@example.com")
        self.assertEqual(access.email_in(token(aud=["another-application", AUD])), "ada@example.com")

    def test_a_token_for_another_site_another_team_or_another_time_is_not_believed(self):
        now = int(time.time())
        late = access.LEEWAY + 30
        for why, changes in (
            ("made for another application of the same team", {"aud": ["f" * 64]}),
            ("made by another team", {"iss": "https://another-team.cloudflareaccess.com"}),
            ("made by a look-alike of this team", {"iss": ISSUER + ".example.com"}),
            ("run out", {"exp": now - late}),
            ("not valid yet", {"nbf": now + late}),
            ("without an end", {"exp": None}),
            ("without a start", {"iat": None}),
            ("made for nobody", {"aud": None}),
            ("made by nobody", {"iss": None}),
        ):
            self.assertIsNone(access.email_in(token(**changes)), why)
        self.assertEqual(access.email_in(token(exp=now - 5)), "ada@example.com", "a clock may be a few seconds off")

    def test_only_the_teams_own_signature_counts(self):
        self.assertIsNone(access.email_in(token(signed_with="somebody-elses-key")), "key-1's name on another key's work")
        self.assertIsNone(access.email_in(token(kid="a-key-of-their-own")), "a key the team does not list")
        self.assertIsNone(access.email_in(jwt.encode(claims(), pair("key-1"), algorithm="RS256")), "no key named")
        # No signature at all, said to be fine by the token itself.
        self.assertIsNone(access.email_in(raw({"alg": "none", "kid": "key-1", "typ": "JWT"}, claims())))
        # Signed with the team's public key, which everyone can fetch, as if it were a shared secret.
        public = pair("key-1").public_key().public_bytes(serialization.Encoding.PEM,
                                                         serialization.PublicFormat.SubjectPublicKeyInfo)
        unsigned = raw({"alg": "HS256", "kid": "key-1", "typ": "JWT"}, claims()).rsplit(".", 1)[0]
        forged = hmac.new(public, unsigned.encode(), hashlib.sha256).digest()
        self.assertIsNone(access.email_in(raw({"alg": "HS256", "kid": "key-1", "typ": "JWT"}, claims(), forged)))
        # The right key, and one letter of what it signed changed afterwards.
        head, said, signature = token().split(".")
        other = raw({}, claims("eve@example.com")).split(".")[1]
        self.assertIsNone(access.email_in(f"{head}.{other}.{signature}"))
        for nothing in ("", "ada@example.com", "a.b.c", "....", "\x00", "é" * 40):
            self.assertIsNone(access.email_in(nothing), repr(nothing))

    def test_a_token_that_names_nobody_logs_nobody_in(self):
        # A service token (a program's, such as the owner's page check): Cloudflare lets it through and names no one.
        service = token(None, common_name="0123456789abcdef.access", sub="", nbf=None, identity_nonce=None, country=None)
        self.assertIsNone(access.email_in(service))
        self.assertIsNone(access.email_in(token(type="org")), "the team's own session, not this application's")
        for nobody in ("", "   ", 7, ["ada@example.com"], {"address": "ada@example.com"}):
            self.assertIsNone(access.email_in(token(email=nobody)), repr(nobody))

    def test_the_log_says_what_kind_of_refusal_and_never_the_token(self):
        refused = token(aud=["f" * 64])
        with self.assertLogs("capsule.access", level="INFO") as log:
            self.assertIsNone(access.email_in(refused))
            self.assertIsNone(access.email_in(refused))                 # the same kind again: not a second line
            self.assertIsNone(access.email_in(token(exp=1)))            # another kind: its own line
            self.assertEqual(access.email_in(token()), "ada@example.com")
            self.assertEqual(access.email_in(token()), "ada@example.com")
            self.now += access.SAY_AGAIN_SECONDS + 1
            self.assertIsNone(access.email_in(refused))                 # a minute on, it is said again
            self.assertEqual(access.email_in(token()), "ada@example.com")
        lines = [record.getMessage() for record in log.records]
        self.assertEqual([line.split("(")[1].split(")")[0] for line in lines if "not believed" in line],
                         ["InvalidAudienceError", "ExpiredSignatureError", "InvalidAudienceError"])
        self.assertEqual(sum("the first token was checked and believed" in line for line in lines), 1)
        self.assertIn("check ACCESS_TEAM and ACCESS_AUD", lines[0])
        for line in lines:
            for secret in (refused, refused.split(".")[1], "ada@example.com"):
                self.assertNotIn(secret, line)


class TheTeamsKeys(BehindAccess):
    def test_the_keys_are_fetched_once_and_then_kept(self):
        for _ in range(5):
            self.assertEqual(access.email_in(token()), "ada@example.com")
        self.assertEqual(len(self.asked), 1)
        self.now += access.KEYS_SECONDS - 1
        self.assertEqual(access.email_in(token()), "ada@example.com")
        self.assertEqual(len(self.asked), 1)
        self.now += 2                           # old now: fetched again
        self.assertEqual(access.email_in(token()), "ada@example.com")
        self.assertEqual(len(self.asked), 2)

    def test_a_new_key_at_cloudflare_is_picked_up_but_not_asked_for_at_every_request(self):
        self.assertEqual(access.email_in(token()), "ada@example.com")
        # Cloudflare has changed its keys (it does every six weeks), and lists the one before for a while.
        self.kids = ["key-2", "key-1"]
        self.assertIsNone(access.email_in(token(kid="key-2")), "the keys were asked for a moment ago")
        self.assertIsNone(access.email_in(token(kid="made-up-1")))
        self.assertIsNone(access.email_in(token(kid="made-up-2")))
        self.assertEqual(len(self.asked), 1, "tokens with made-up key names must not make Stilsmith ask each time")
        self.now += access.ASK_AGAIN_SECONDS + 1
        self.assertEqual(access.email_in(token(kid="key-2")), "ada@example.com")
        self.assertEqual(access.email_in(token()), "ada@example.com", "the one before still counts while it is listed")
        self.assertEqual(len(self.asked), 2)
        self.kids = ["key-2"]                   # ... and then no longer
        self.now += access.KEYS_SECONDS + 1
        self.assertIsNone(access.email_in(token()))
        self.assertEqual(access.email_in(token(kid="key-2")), "ada@example.com")

    def test_while_the_teams_address_cannot_be_reached_nobody_is_believed_and_nothing_breaks(self):
        self.down = True
        with self.assertLogs("capsule.access", level="WARNING") as log:
            self.assertIsNone(access.email_in(token()))
            self.assertIsNone(access.email_in(token()))
        self.assertEqual(len(self.asked), 1, "not asked again at once")
        self.assertIn("the team's keys could not be fetched", log.records[0].getMessage())
        self.assertIn("people log in with a password", log.records[0].getMessage())
        self.down = False
        self.now += access.ASK_AGAIN_SECONDS + 1
        self.assertEqual(access.email_in(token()), "ada@example.com", "back again, and so is the check")

    def test_keys_fetched_before_go_on_being_used_for_a_day_at_most(self):
        self.assertEqual(access.email_in(token()), "ada@example.com")
        self.down = True
        self.now += access.KEYS_SECONDS + 1
        self.assertEqual(access.email_in(token()), "ada@example.com", "a fetch failed: the keys from before still count")
        self.now += access.KEYS_LAST
        self.assertIsNone(access.email_in(token()), "a day without the team's word: its old keys are let go")

    def test_an_answer_that_is_not_a_list_of_keys_counts_as_none(self):
        for answer in (b"<html>Sign in</html>", b"{}", b'{"keys": []}', b'{"keys": [{"kty": "RSA", "kid": "key-1"}]}',
                       b'{"keys": [{"kty": "EC", "kid": "key-1"}]}', b"[" * 100):
            access.forget_keys()
            self.down_answer = answer
            self.assertIsNone(access.email_in(token()), answer[:30])
        del self.down_answer
        self.now += access.ASK_AGAIN_SECONDS + 1
        self.assertEqual(access.email_in(token()), "ada@example.com")

    def test_the_fetch_follows_no_redirect_and_never_asks_the_computer_for_its_proxy_settings(self):
        # Asking macOS for its proxy settings inside a web-server worker kills the worker (imagegen.py, and
        # tests/test_looks.py for the same rule there). Only the environment may name a proxy.
        code = ("import urllib.request as u\n"
                "def trap(*a, **k): raise SystemExit('the system proxy settings were asked for')\n"
                "u.getproxies = u.getproxies_macosx_sysconf = u.proxy_bypass = trap\n"
                "from wardrobe import access\n"
                "access.issuer = lambda: 'http://127.0.0.1:9'\n"         # nothing listens there
                "try:\n"
                "    access._fetch()\n"
                "except OSError:\n"
                "    pass\n"
                "else:\n"
                "    raise SystemExit('the fetch did not fail')\n")
        done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60,
                              cwd=Path(__file__).resolve().parent.parent)
        self.assertEqual((done.returncode, done.stderr.strip()), (0, ""))
        proxies = [h for h in access._opener.handlers if isinstance(h, urllib.request.ProxyHandler)]
        self.assertTrue(all(h.proxies == urllib.request.getproxies_environment() for h in proxies))
        self.assertIn("_NoRedirect", {type(handler).__name__ for handler in access._opener.handlers})
        self.assertIsNone(access._NoRedirect().redirect_request("request", "answer", 302, "Found", {}, "http://x"))


class OneButton(BehindAccess):
    def test_a_checked_visitor_makes_his_account_with_one_button_and_no_password(self):
        visitor = self.app.test_client()
        page = visitor.get("/signup", headers=by("Ada@Example.com"))
        self.assertEqual(page.status_code, 200)
        html = page.get_data(as_text=True)
        self.assertIn("You have already shown that ada@example.com is your email address", words(html))
        self.assertIn("So you need no password here.", words(html))
        self.assertIn('action="/checked"', html)
        self.assertIn(">Create my account</button>", html)
        for field in ('name="password"', 'name="email"', 'name="code"'):
            self.assertNotIn(field, html)
        # What he agrees to is said as on the form.
        self.assertIn("By creating an account you agree to the terms of use and confirm you are 18 or over.", words(html))
        self.assertIn('href="/legal/terms"', html)
        self.assertIn('href="/legal/privacy"', html)
        self.assertIsNone(db.get_user_by_email("ada@example.com"), "looking at the page makes nothing")

        answer = self.press(visitor, "Ada@Example.com")
        self.assertEqual((answer.status_code, answer.headers["Location"]), (302, "/welcome"), "the welcome, as after the form")
        account = db.get_user_by_email("ada@example.com")
        self.assertEqual(account["password_hash"], access.NO_PASSWORD)
        self.assertEqual(self.who(visitor), "ada@example.com")
        self.assertIn("Logged in as ada@example.com", self.said(visitor, "/account"))
        self.assertEqual(visitor.get("/welcome").status_code, 200)

    def test_the_button_is_a_form_of_this_site_like_any_other(self):
        visitor = self.app.test_client()
        self.assertEqual(visitor.post("/checked", headers=by()).status_code, 400, "without the form's token")
        elsewhere = {**by(), "Origin": "https://evil.example"}
        self.assertEqual(self.post(visitor, "/checked", headers=elsewhere).status_code, 403, "pressed on another site")
        self.assertEqual(visitor.get("/checked", headers=by()).status_code, 405, "an address to open, not a button")
        self.assertIsNone(db.get_user_by_email("ada@example.com"))
        self.assertIsNone(self.who(visitor))

    def test_no_password_opens_such_an_account(self):
        self.newcomer()
        stranger = self.app.test_client()
        for guess in ("", access.NO_PASSWORD, "!", PASSWORD, "not a real password"):
            answer = self.post(stranger, "/login", email="ada@example.com", password=guess)
            self.assertEqual(answer.status_code, 401, repr(guess))
        self.assertIsNone(self.who(stranger))

    def test_until_he_presses_it_he_is_a_visitor_like_any_other(self):
        visitor = self.app.test_client()
        home = visitor.get("/", headers=by())
        self.assertEqual(home.status_code, 200)
        self.assertIn(b"Create a free account", home.data)
        self.assertIsNone(self.who(visitor))
        self.assertIsNone(db.get_user_by_email("ada@example.com"))

    def test_from_then_on_cloudflares_check_opens_his_account(self):
        self.newcomer()
        another_day = self.app.test_client()                            # no cookie of Stilsmith's
        account = another_day.get("/account", headers=by())
        self.assertEqual(account.status_code, 200, "no log-in page in between")
        self.assertIn("Logged in as ada@example.com", words(account.get_data(as_text=True)))
        self.assertEqual(self.who(another_day), "ada@example.com")
        # From there on the cookie carries him, with its own token for the forms.
        self.assertEqual(another_day.post("/outfits/save", data={"key": "x"}, headers=HX).status_code, 400)
        self.assertEqual(self.post(another_day, "/logout").status_code, 302)
        # And "Log in" leads him where he was going, without asking for anything.
        third = self.app.test_client()
        answer = third.get("/login?next=/profile", headers=by())
        self.assertEqual((answer.status_code, answer.headers["Location"]), (302, "/profile"))

    def test_without_cloudflares_word_nothing_opens_it(self):
        self.newcomer()
        stranger = self.app.test_client()
        for headers in (PAGE, {**PAGE, access.HEADER: "ada@example.com"}, {**PAGE, access.HEADER: token(exp=1)},
                        {**PAGE, access.HEADER: token(signed_with="somebody-elses-key")},
                        {**PAGE, "Cf-Access-Authenticated-User-Email": "ada@example.com"}):
            answer = stranger.get("/account", headers=headers)
            self.assertEqual((answer.status_code, answer.headers["Location"]), (302, "/login?next=/account"), headers)
            self.assertIsNone(self.who(stranger))

    def test_only_opening_a_page_logs_him_in(self):
        # A form being sent, a page's own script and a picture do not: logging in starts a new cookie and a new token
        # for the forms, which a page that is open already would not have.
        self.newcomer()
        browser = self.app.test_client()
        checked = {access.HEADER: token()}
        self.assertEqual(browser.get("/account", headers=checked).status_code, 302, "no page asked for: no Accept")
        self.assertEqual(browser.get("/account", headers={**checked, "Accept": "image/avif,image/webp,*/*"}).status_code, 302)
        self.assertEqual(browser.get("/account", headers={**checked, **PAGE, **HX}).status_code, 401)
        self.assertEqual(browser.post("/outfits/save", data={"key": "x"}, headers={**checked, **PAGE}).status_code, 302)
        self.assertEqual(browser.post("/outfits/save", data={"key": "x"}, headers={**checked, **PAGE, **HX}).status_code, 401)
        stylesheet = browser.get("/static/app.css", headers={**checked, **PAGE})
        self.assertEqual(stylesheet.status_code, 200)
        stylesheet.close()
        self.assertIsNone(self.who(browser))
        self.assertEqual(browser.get("/account", headers={**checked, **PAGE}).status_code, 200)
        self.assertEqual(self.who(browser), "ada@example.com")

    def test_logging_out_sticks_until_he_asks_to_come_back(self):
        ada = self.newcomer()
        answer = self.post(ada, "/logout")      # (even if this one request carried no token: the team's address down)
        self.assertEqual(answer.status_code, 302)
        for address in ("/", "/outfits", "/account"):
            ada.get(address, headers=by())
            self.assertIsNone(self.who(ada), f"{address} logged him in again by itself")
        self.assertEqual(ada.get("/account", headers=by()).headers["Location"], "/login?next=/account")
        page = ada.get("/login?next=/account", headers=by())
        html = page.get_data(as_text=True)
        self.assertIn(">Continue as ada@example.com</button>", html)
        self.assertIn('<input type="hidden" name="next" value="/account">', html)
        self.assertIn('name="password"', html, "the form is still there, for any other account")
        # "Create account" has nothing to make for him: it leads to that button.
        answer = ada.get("/signup", headers=by())
        self.assertEqual((answer.status_code, answer.headers["Location"]), (302, "/login"))
        answer = self.press(ada, next="/account")
        self.assertEqual((answer.status_code, answer.headers["Location"]), (302, "/account"))
        self.assertEqual(self.who(ada), "ada@example.com")
        # In again: the next time his cookie has gone, Cloudflare's check opens his account as before.
        with ada.session_transaction() as session:
            self.assertNotIn("left", session)

    def test_coming_back_before_the_welcome_was_finished_offers_it_once_more(self):
        ada = self.newcomer()                                           # at the welcome, and gone
        self.post(ada, "/logout", headers=by())
        answer = self.press(ada)
        self.assertEqual((answer.status_code, answer.headers["Location"]), (302, "/welcome"))

    def test_an_account_with_a_password_is_never_opened_by_the_check(self):
        # Whoever chose that password may be somebody else: the sign-up form checks nobody's address.
        self.member("ada@example.com")
        browser = self.app.test_client()
        answer = browser.get("/account", headers=by())
        self.assertEqual((answer.status_code, answer.headers["Location"]), (302, "/login?next=/account"))
        login = browser.get("/login", headers=by()).get_data(as_text=True)
        self.assertNotIn("Continue as", login)
        signup = browser.get("/signup", headers=by()).get_data(as_text=True)
        self.assertIn('name="password"', signup, "the form: there is nothing the button could make")
        self.assertNotIn("Create my account", signup)
        answer = self.press(browser)
        self.assertEqual((answer.status_code, answer.headers["Location"]), (302, "/login"))
        self.assertIn("This email address already has an account with a password. Log in with that password.",
                      self.said(browser))
        self.assertIsNone(self.who(browser))
        self.assertNotEqual(db.get_user_by_email("ada@example.com")["password_hash"], access.NO_PASSWORD)
        # Its password opens it, as always, whatever Cloudflare says.
        answer = self.post(browser, "/login", headers=by(), email="ada@example.com", password=PASSWORD)
        self.assertEqual(answer.status_code, 302)
        self.assertEqual(self.who(browser), "ada@example.com")
        self.assertIn("Change password", self.said(browser, "/account"))

    def test_the_check_opens_only_the_account_of_the_address_it_names(self):
        self.newcomer("ada@example.com")
        eve = self.app.test_client()
        self.assertEqual(eve.get("/account", headers=by("eve@example.com")).status_code, 302)
        self.assertIsNone(self.who(eve))
        self.assertNotIn("Continue as", eve.get("/login", headers=by("eve@example.com")).get_data(as_text=True))
        # Sending Ada's address along changes nothing: only the token's address counts.
        answer = self.post(eve, "/checked", headers=by("eve@example.com"), email="ada@example.com")
        self.assertEqual(answer.headers["Location"], "/welcome")
        self.assertEqual(self.who(eve), "eve@example.com")

    def test_when_somebody_else_sits_down_at_the_browser_the_account_closes(self):
        ada = self.newcomer("ada@example.com")
        self.newcomer("eve@example.com")
        self.assertEqual(ada.get("/account", headers=by("ada@example.com")).status_code, 200)
        # Cloudflare now vouches for Eve in the same browser (Ada's Cloudflare session ended, Eve typed her code).
        page = ada.get("/account", headers=by("eve@example.com"))
        self.assertIn("Logged in as eve@example.com", words(page.get_data(as_text=True)))
        self.assertEqual(self.who(ada), "eve@example.com")
        # For someone without an account, Ada's simply closes. A button of the page that was open does nothing.
        ada.get("/account", headers=by("ada@example.com"))
        self.assertEqual(self.who(ada), "ada@example.com")
        answer = ada.post("/outfits/save", data={"key": "x"}, headers={access.HEADER: token("bob@example.com"), **HX})
        self.assertEqual(answer.status_code, 401)
        self.assertIsNone(self.who(ada))

    def test_a_request_without_a_token_leaves_him_logged_in(self):
        # No token, or one that is not believed (the team's address down, say), is not somebody else.
        ada = self.newcomer()
        for headers in ({}, PAGE, {**PAGE, access.HEADER: token(exp=1)}, {**PAGE, access.HEADER: token(None, sub="")}):
            self.assertEqual(ada.get("/account", headers=headers).status_code, 200, headers)
        self.assertEqual(self.who(ada), "ada@example.com")
        # An account with a password stays open whoever Cloudflare names: its password was the proof.
        bea = self.member("bea@example.com")
        self.assertEqual(bea.get("/account", headers=by("eve@example.com")).status_code, 200)
        self.assertEqual(self.who(bea), "bea@example.com")

    def test_without_a_token_the_forms_are_as_they_were(self):
        # A program with a service token (the owner's page check), or a token that is not believed.
        for headers in (PAGE, {**PAGE, access.HEADER: token(None, common_name="0123.access", sub="")},
                        {**PAGE, access.HEADER: token(exp=1)}):
            visitor = self.app.test_client()
            html = visitor.get("/signup", headers=headers).get_data(as_text=True)
            self.assertIn('name="password"', html)
            self.assertNotIn("Create my account", html)
            self.assertNotIn("Continue as", visitor.get("/login", headers=headers).get_data(as_text=True))
            answer = self.press(visitor, headers=headers)
            self.assertEqual((answer.status_code, answer.headers["Location"]), (302, "/login"))
            self.assertIn("The check of your email address has run out. Reload the page and try again.", self.said(visitor))
        self.assertEqual(db.get_user_by_email("ada@example.com"), None)
        cy = self.member("cy@example.com")                              # the form, with a password
        self.assertEqual(self.who(cy), "cy@example.com")
        self.assertNotEqual(db.get_user_by_email("cy@example.com")["password_hash"], access.NO_PASSWORD)

    def test_the_form_is_one_link_away_for_another_address_or_a_password_of_his_own(self):
        visitor = self.app.test_client()
        self.assertIn('href="/signup?password=1"', visitor.get("/signup", headers=by()).get_data(as_text=True))
        form = visitor.get("/signup?password=1", headers=by()).get_data(as_text=True)
        self.assertIn('name="password"', form)
        self.assertNotIn("Create my account", form)
        answer = self.post(visitor, "/signup", headers=by(), email="ada.work@example.com", password=PASSWORD)
        self.assertEqual(answer.status_code, 302)
        self.assertEqual(self.who(visitor), "ada.work@example.com")

    def test_by_invitation_the_form_asks_for_the_code_and_the_button_makes_nothing(self):
        with mock.patch.object(settings, "INVITE_CODE", "a-code-of-our-own"):
            visitor = self.app.test_client()
            html = visitor.get("/signup", headers=by()).get_data(as_text=True)
            self.assertIn('name="code"', html)
            self.assertNotIn("Create my account", html)
            answer = self.press(visitor)
            self.assertEqual((answer.status_code, answer.headers["Location"]), (302, "/signup?password=1"))
            self.assertIn("Stilsmith is open by invitation for now. Create your account with the form and your code.",
                          self.said(visitor, "/signup?password=1"))
            self.assertIsNone(db.get_user_by_email("ada@example.com"))
        # Someone who made his account before the code was set still gets in with the check.
        ada = self.newcomer()
        with mock.patch.object(settings, "INVITE_CODE", "a-code-of-our-own"):
            self.post(ada, "/logout", headers=by())
            self.assertEqual(self.press(ada).status_code, 302)
            self.assertEqual(self.who(ada), "ada@example.com")

    def test_stilsmiths_own_account_is_not_one_of_them(self):
        # The example wardrobe's account has no password either, in its own way (an empty one): nothing opens it.
        own = guests.EXAMPLE_EMAIL
        self.assertEqual(db.get_user_by_email(own)["password_hash"], "")
        browser = self.app.test_client()
        self.assertEqual(browser.get("/account", headers=by(own)).status_code, 302)
        self.assertEqual(self.press(browser, own).headers["Location"], "/login")
        self.assertIsNone(self.who(browser))
        self.assertEqual(db.get_user_by_email(own)["password_hash"], "")

    def test_pressing_twice_makes_one_account(self):
        first, second = self.app.test_client(), self.app.test_client()
        self.assertEqual(self.press(first).headers["Location"], "/welcome")
        self.assertEqual(self.press(second).headers["Location"], "/welcome", "he had not finished the welcome")
        with closing(sqlite3.connect(paths.DB_PATH)) as con:
            self.assertEqual(con.execute("SELECT COUNT(*) FROM users WHERE email = 'ada@example.com'").fetchone()[0], 1)
        # The other press arrived while the first was making the account: it finds it made.
        with mock.patch.object(db, "get_user_by_email", side_effect=[None, db.get_user_by_email("ada@example.com")]):
            third = self.app.test_client()
            self.assertEqual(self.press(third).status_code, 302)
        self.assertEqual(self.who(third), "ada@example.com")
        # Someone who is logged in already just goes on.
        self.assertEqual(self.press(first, next="/profile").headers["Location"], "/profile")


class HisAccountPage(BehindAccess):
    def test_it_has_no_password_to_change_and_asks_for_none(self):
        ada = self.newcomer()
        html = ada.get("/account", headers=by()).get_data(as_text=True)
        self.assertIn("This account has no password. Your email address is checked with a code before the site opens, "
                      "and that logs you in.", words(html))
        self.assertNotIn("Change password", html)
        self.assertNotIn('type="password"', html)
        self.assertIn(">Delete my account</button>", html)
        answer = self.post(ada, "/account/password", headers=by(), current="x", password="a new password of mine")
        self.assertEqual(answer.status_code, 302)
        self.assertIn("This account has no password: the check of your email address logs you in.",
                      self.said(ada, "/account"))
        self.assertEqual(db.get_user_by_email("ada@example.com")["password_hash"], access.NO_PASSWORD)

    def test_deleting_it_takes_cloudflares_check_in_place_of_the_password(self):
        ada = self.newcomer()
        answer = self.post(ada, "/account/delete")                      # the check has run out: no token
        self.assertEqual((answer.status_code, answer.headers["Location"]), (302, "/account"))
        self.assertIn("The check of your email address has run out, so nothing was deleted.", self.said(ada, "/account"))
        self.assertIsNotNone(db.get_user_by_email("ada@example.com"))
        answer = self.post(ada, "/account/delete", headers=by(), current="whatever is typed")
        self.assertEqual(answer.status_code, 302)
        self.assertIsNone(db.get_user_by_email("ada@example.com"))
        self.assertIn("Your account and everything in it have been deleted.", self.said(ada, "/"))
        # An account with a password is asked for it, as always.
        bea = self.member("bea@example.com")
        self.post(bea, "/account/delete", headers=by("bea@example.com"), current="wrong")
        self.assertIsNotNone(db.get_user_by_email("bea@example.com"))

    def test_a_reset_link_gives_it_a_password_for_the_day_cloudflare_access_is_taken_away(self):
        self.newcomer()
        visitor = self.app.test_client()
        self.post(visitor, "/forgot", email="ada@example.com")
        link = mail.OUTBOX[-1]["body"].split(settings.SITE_URL)[1].split()[0]
        self.assertEqual(self.post(visitor, link, password="a password of my own").status_code, 302)
        self.assertEqual(self.post(visitor, "/login", email="ada@example.com", password="a password of my own").status_code, 302)
        self.assertEqual(self.who(visitor), "ada@example.com")
        # It is an account with a password now: the check no longer opens it by itself.
        other = self.app.test_client()
        self.assertEqual(other.get("/account", headers=by()).status_code, 302)


class WithoutCloudflareAccess(ProductionCase):
    """ACCESS_TEAM and ACCESS_AUD not set: a server with nothing in front, or the owner's own machine."""

    def setUp(self):
        patch = mock.patch.object(access._opener, "open", side_effect=AssertionError("a network connection was opened"))
        patch.start()
        self.addCleanup(patch.stop)
        access.forget_keys()
        super().setUp()

    def test_no_token_is_read_at_all(self):
        self.assertEqual((settings.ACCESS_TEAM, settings.ACCESS_AUD), ("", ""))
        self.assertFalse(access.on())
        visitor = self.app.test_client()
        html = visitor.get("/signup", headers=by()).get_data(as_text=True)
        self.assertIn('name="password"', html)
        self.assertNotIn("Create my account", html)
        answer = self.post(visitor, "/checked", headers=by())
        self.assertEqual((answer.status_code, answer.headers["Location"]), (302, "/login"))
        self.assertIsNone(db.get_user_by_email("ada@example.com"))
        # An account from the days behind Cloudflare Access stays shut until its owner chooses a password (a reset link).
        user_id = db.create_user("ada@example.com", access.NO_PASSWORD)
        self.assertEqual(visitor.get("/account", headers=by()).status_code, 302)
        self.assertEqual(self.post(visitor, "/login", email="ada@example.com", password=access.NO_PASSWORD).status_code, 401)
        self.assertIsNotNone(user_id)

    def test_logging_out_leaves_nothing_behind(self):
        cy = self.member("cy@example.com")
        self.post(cy, "/logout", headers=by("cy@example.com"))
        with cy.session_transaction() as session:
            self.assertNotIn("left", session)

    def test_the_start_up_line_says_which_it_is(self):
        self.assertEqual(access.status(), "off (ACCESS_TEAM and ACCESS_AUD are not set): everyone logs in with a password")
        with mock.patch.object(settings, "ACCESS_TEAM", TEAM), mock.patch.object(settings, "ACCESS_AUD", AUD):
            self.assertEqual(access.status(), "on. Whoever example-team.cloudflareaccess.com has checked creates an "
                                              "account with one button and needs no password")
            with mock.patch.object(settings, "PRODUCTION", False):
                self.assertFalse(access.on(), "on your own machine there is no login at all")
                self.assertIsNone(access.checked_email())
        self.assertLess(access._clock(), access._clock() + 1, "seconds, going forward")


class TheTwoSettings(ProductionCase):
    def start_with(self, team: str, aud: str) -> str:
        """What the app says when it refuses to start with these two settings."""
        with mock.patch.object(settings, "ACCESS_TEAM", team), mock.patch.object(settings, "ACCESS_AUD", aud), \
                self.assertRaises(SystemExit) as stopped:
            create_app()
        return str(stopped.exception)

    def test_one_without_the_other_stops_the_start(self):
        self.assertIn("ACCESS_TEAM is set and ACCESS_AUD is not", self.start_with(TEAM, ""))
        self.assertIn("ACCESS_AUD is set and ACCESS_TEAM is not", self.start_with("", AUD))

    def test_a_value_that_cannot_be_one_stops_the_start(self):
        self.assertIn("ACCESS_TEAM is not a Cloudflare Access team's name", self.start_with("my team", AUD))
        self.assertIn("ACCESS_TEAM is not a Cloudflare Access team's name", self.start_with("evil.example/x#", AUD))
        for tag in ("short", "replace-me-with-the-audience-tag-of-your-application", "0a1b2c3d " * 8):
            self.assertIn("ACCESS_AUD is not an audience tag", self.start_with(TEAM, tag), tag)

    def test_the_team_may_be_given_as_its_name_its_domain_or_its_address(self):
        for given in ("example-team", " Example-Team ", "example-team.cloudflareaccess.com",
                      "https://example-team.cloudflareaccess.com", "https://example-team.cloudflareaccess.com/"):
            self.assertEqual(settings._team(given), "example-team", given)
        self.assertEqual(settings._team(""), "")

    def test_without_the_packages_that_check_a_token_it_stops_and_says_which(self):
        with mock.patch("importlib.util.find_spec", return_value=None):
            said = self.start_with(TEAM, AUD)
        self.assertIn("needs the packages PyJWT and cryptography", said)
        self.assertIn("pip install -r requirements-prod.txt", said)

    def test_with_both_it_starts(self):
        with mock.patch.object(settings, "ACCESS_TEAM", TEAM), mock.patch.object(settings, "ACCESS_AUD", AUD):
            self.assertEqual(create_app().test_client().get("/healthz").status_code, 200)


class OwnersNamedAhead(BehindAccess):
    """`python -m wardrobe owner add EMAIL` for an address that has no account yet (owner.py)."""

    def cli(self, *argv: str) -> str:
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            main(list(argv))
        return out.getvalue()

    def test_the_address_is_noted_and_its_account_is_an_owner_from_its_first_page(self):
        said = self.cli("owner", "add", " Olga@Example.com ")
        self.assertIn("olga@example.com has no account yet: noted.", said)
        self.assertIn('with the one button ("Create my account", no password)', said)
        self.assertRegex(self.cli("owner", "list"), r"olga@example\.com\s+no account yet: an owner from the moment")
        self.assertNotIn("No owners yet", self.cli("owner"))
        self.assertIn("it was noted before", self.cli("owner", "add", "olga@example.com"))
        olga = self.newcomer("olga@example.com")
        self.assertTrue(db.is_owner(db.get_user_by_email("olga@example.com")["id"]))
        self.assertEqual(olga.get("/stores", headers=by("olga@example.com")).status_code, 200)
        self.assertIn("Open the store catalogues", self.said(olga, "/account"))
        self.assertEqual(db.owners_to_be(), [], "the note is used up")
        self.assertRegex(self.cli("owner", "list"), r"olga@example\.com\s+owner since ")
        self.assertIn("olga@example.com is an owner already", self.cli("owner", "add", "olga@example.com"))

    def test_an_account_made_with_the_form_never_takes_a_note_up(self):
        # The form checks nobody's address: anyone inside could type Olga's. Only Cloudflare's check of it counts.
        self.cli("owner", "add", "olga@example.com")
        someone = self.member("olga@example.com")
        self.assertFalse(db.is_owner(db.get_user_by_email("olga@example.com")["id"]))
        self.assertEqual(someone.get("/stores").status_code, 404)
        self.assertEqual([row["email"] for row in db.owners_to_be()], ["olga@example.com"])
        # Nor does the note pass to whoever else makes an account with the button.
        self.newcomer("eve@example.com")
        self.assertFalse(db.is_owner(db.get_user_by_email("eve@example.com")["id"]))
        # The owner can still mark that account by hand, knowing whose it is.
        self.assertIn("olga@example.com is now an owner", self.cli("owner", "add", "olga@example.com"))

    def test_a_note_can_be_taken_back(self):
        self.cli("owner", "add", "olga@example.com")
        self.assertIn("olga@example.com had no account yet: it will not become an owner when it makes one.",
                      self.cli("owner", "remove", "olga@example.com"))
        self.assertEqual(db.owners_to_be(), [])
        self.newcomer("olga@example.com")
        self.assertFalse(db.is_owner(db.get_user_by_email("olga@example.com")["id"]))
        with self.assertRaises(SystemExit) as refused:
            self.cli("owner", "remove", "nobody@example.com")
        self.assertIn("nobody@example.com is not an owner", str(refused.exception))

    def test_without_cloudflare_access_an_owner_needs_his_account_first_as_before(self):
        with mock.patch.object(settings, "ACCESS_AUD", ""), self.assertRaises(SystemExit) as refused:
            self.cli("owner", "add", "olga@example.com")
        self.assertIn("There is no account with the address olga@example.com. Sign up on the site with it first",
                      str(refused.exception))
        self.assertEqual(db.owners_to_be(), [])

    def test_a_database_from_before_gains_the_table_and_nothing_else_changes(self):
        with closing(sqlite3.connect(paths.DB_PATH)) as con:
            con.executescript("DROP TABLE owners_to_be; PRAGMA user_version = 11;")
            before = set(con.execute("SELECT type, name, tbl_name, sql FROM sqlite_master"))
            users = con.execute("SELECT * FROM users").fetchall()
        db.init()
        with closing(sqlite3.connect(paths.DB_PATH)) as con:
            after = set(con.execute("SELECT type, name, tbl_name, sql FROM sqlite_master"))
            self.assertEqual({row[1] for row in after - before}, {"owners_to_be", "sqlite_autoindex_owners_to_be_1"})
            self.assertEqual(before - after, set())
            self.assertEqual(con.execute("SELECT * FROM users").fetchall(), users)
            self.assertEqual(con.execute("PRAGMA user_version").fetchone()[0], 12)
        self.assertTrue(db.expect_owner("olga@example.com"))


if __name__ == "__main__":
    unittest.main()
