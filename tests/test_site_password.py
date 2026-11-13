"""SITE_PASSWORD: a private trial on the internet, where every page first asks for one password.

The owner can put the app on a real domain to try it before it is ready for customers (no Impressum address yet,
no licensed product data). With SITE_PASSWORD set nothing of it is public: not the landing page, not a stylesheet,
not a form. Only /healthz answers, for the container's health check.
"""
import base64
import unittest
from unittest import mock

from wardrobe import settings
from wardrobe.app import create_app

from .test_production import ProductionCase

PASSWORD = "a-trial-password-of-our-own"


def basic(password: str, user: str = "anyone") -> dict:
    return {"Authorization": "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode()}


class SitePassword(ProductionCase):
    def setUp(self):
        patch = mock.patch.object(settings, "SITE_PASSWORD", PASSWORD)
        patch.start()
        self.addCleanup(patch.stop)
        super().setUp()

    def test_nothing_is_shown_without_the_password(self):
        visitor = self.app.test_client()
        for address in ("/", "/outfits", "/login", "/signup", "/legal/impressum", "/legal/privacy", "/robots.txt",
                        "/static/app.css", "/no-such-page", "/stores"):
            for headers in ({}, basic("wrong password"), basic(PASSWORD[:-1]), {"Authorization": "Bearer " + PASSWORD}):
                answer = visitor.get(address, headers=headers)
                self.assertEqual(answer.status_code, 401, (address, headers))
                self.assertIn('Basic realm="', answer.headers["WWW-Authenticate"])
                self.assertEqual(answer.headers["Cache-Control"], "no-store")
                self.assertNotIn(b"<html", answer.data.lower(), address)
        self.assertEqual(visitor.post("/signup", data={"email": "eve@example.com", "password": "x" * 12}).status_code,
                         401, "a form is refused before it is read")
        self.assertIsNone(settings_user("eve@example.com"))

    def test_the_password_opens_the_site_with_any_user_name(self):
        visitor = self.app.test_client()
        for user in ("anyone", "", "owner"):
            home = visitor.get("/", headers=basic(PASSWORD, user))
            self.assertEqual(home.status_code, 200, user)
            self.assertIn(b"<html", home.data.lower())
        stylesheet = visitor.get("/static/app.css", headers=basic(PASSWORD))
        self.assertEqual(stylesheet.status_code, 200)
        stylesheet.close()

    def test_the_health_check_needs_no_password(self):
        self.assertEqual(self.app.test_client().get("/healthz").status_code, 200)

    def test_a_password_that_keeps_nobody_out_stops_the_start(self):
        for weak in ("short", settings.PLACEHOLDER + "-with-a-long-tail"):
            with mock.patch.object(settings, "SITE_PASSWORD", weak), self.assertRaises(SystemExit) as stopped:
                create_app()
            self.assertIn("SITE_PASSWORD", str(stopped.exception))


class NoSitePassword(ProductionCase):
    def test_without_it_the_site_is_open_as_before(self):
        self.assertEqual(settings.SITE_PASSWORD, "")
        visitor = self.app.test_client()
        self.assertEqual(visitor.get("/").status_code, 200)
        self.assertNotIn("WWW-Authenticate", visitor.get("/").headers)


def settings_user(email: str):
    from wardrobe import db
    return db.get_user_by_email(email)


if __name__ == "__main__":
    unittest.main()
