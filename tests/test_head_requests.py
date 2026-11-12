"""A page asked for with HEAD is answered like GET, never as a form that was sent.

Link checkers, browser add-ons and "curl -I" ask for a page with HEAD. Flask answers HEAD with the GET handler, so
a handler that treats "anything but GET" as a sent form used to run the form with nothing filled in: on Profile that
saved an empty profile (every liked colour gone, the plan rebuilt), on the log-in pages a failed log-in or a used-up
reset link.
"""
import re
import unittest

from wardrobe import db, mail, profile as profile_mod, settings

from .test_production import ProductionCase


class HeadIsNeverASentForm(ProductionCase):
    def test_head_on_profile_leaves_the_profile_as_it_was(self):
        ada = self.member("ada@example.com")
        with db.as_user(self.user_id("ada@example.com")):
            before = profile_mod.load()
            slots_before = [slot["id"] for slot in db.list_slots()]
        self.assertTrue(before["liked"], "the starting profile has liked colours to lose")

        response = ada.head("/profile")
        self.assertEqual(response.status_code, 200, "HEAD /profile is answered like GET, not as a sent form")

        with db.as_user(self.user_id("ada@example.com")):
            self.assertEqual(profile_mod.load(), before)
            self.assertEqual([slot["id"] for slot in db.list_slots()], slots_before, "the plan was rebuilt")
        self.assertNotIn("Profile saved", ada.get("/profile").get_data(as_text=True))

    def test_head_on_the_log_in_pages_sends_no_form(self):
        visitor = self.app.test_client()
        for url in ("/login", "/signup", "/forgot"):
            self.assertEqual(visitor.head(url).status_code, 200, url)
        # Not a failed log-in (enough of those lock the address out), and no reset link asked for.
        self.assertEqual(db.failed_logins("", "127.0.0.1", settings.LOGIN_WINDOW_SECONDS), (0, 0))
        self.assertNotIn("reset link", visitor.get("/login").get_data(as_text=True), "HEAD /forgot sent the form")

        self.member("ada@example.com")
        self.post(visitor, "/forgot", email="ada@example.com")
        reset = re.search(r"/reset/[\w-]+", mail.OUTBOX[-1]["body"]).group(0)
        self.assertEqual(visitor.head(reset).status_code, 200)
        self.assertEqual(visitor.get(reset).status_code, 200, "the reset link still works after a HEAD")


if __name__ == "__main__":
    unittest.main()
