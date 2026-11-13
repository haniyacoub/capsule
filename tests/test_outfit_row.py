"""The outfit row by keyboard and screen reader: what the page must carry for it (app.js does the rest, and the
browser walk-through, tests/browser_check.py, presses the keys)."""
import re

from wardrobe import outfits, selection

from .test_app import AppCase
from .test_looks import WithPictures


def opening_tag(page: str, start: str) -> str:
    """The whole opening tag that begins with `start` (the first one)."""
    return re.search(re.escape(start) + r"[^>]*>", page).group(0)


def said(html: str) -> str:
    """The words in a piece of HTML, as plain text."""
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).strip()


class TheRowByKeyboard(AppCase):
    def test_the_arrows_come_before_the_outfits_and_the_row_is_no_tab_stop(self):
        # Next is reached in a few Tab presses instead of after every outfit, and the row itself is not a stop on
        # the way: the arrow keys work anywhere on the page.
        page = self.client.get("/outfits").data.decode()
        self.assertLess(page.index('class="reel-nav prev"'), page.index('id="reel"'))
        self.assertLess(page.index('class="reel-nav next"'), page.index('id="reel"'))
        self.assertNotIn("tabindex", opening_tag(page, '<div class="reel"'))

    def test_the_heart_keeps_its_id_and_its_name_whether_saved_or_not(self):
        # Pressing the heart swaps it for its other state: with the same id, focus stays on it (HTMX), and a screen
        # reader hears the same name both times, with pressed or not pressed for the state.
        key = outfits.generate(selection.build(), limit=4)[0][0].key
        page = self.client.get("/outfits").data.decode()
        for pressed, html in (("false", page),
                              ("true", self.post("/outfits/save", key=key).data.decode()),
                              ("false", self.post("/outfits/save", key=key).data.decode())):
            button = re.search(rf'<button class="heart[^"]*" id="save-{key}"[^>]*>(.*?)</button>', html, re.S)
            self.assertIsNotNone(button, f"no heart with the id save-{key}")
            self.assertIn(f'aria-pressed="{pressed}"', button.group(0))
            self.assertNotIn("aria-label", button.group(0))
            self.assertEqual(said(button.group(1)), "Save outfit")
        self.assertEqual(len(set(re.findall(r'id="(save-[0-9a-f]+)"', page))), page.count('class="heart'),
                         "two hearts on the page with the same id")

    def test_one_quiet_live_region_on_every_page(self):
        # One place, there from the start, where app.js writes what changed ("Outfit 2 of 12, …", "Picture ready"):
        # a screen reader reads out what is written there. It is empty until then.
        for url in ("/outfits", "/", "/profile", "/list"):
            page = self.client.get(url).data.decode()
            self.assertEqual(page.count('id="announce"'), 1, url)
            region = re.search(r'<p id="announce"[^>]*>(.*?)</p>', page, re.S)
            self.assertIn('role="status"', region.group(0), url)
            self.assertIn('aria-live="polite"', region.group(0), url)
            self.assertIn('class="sr"', region.group(0), url)
            self.assertEqual(region.group(1), "", url)


class TheDots(WithPictures, AppCase):
    def setUp(self):
        super().setUp()
        self.switch_on()

    def test_a_dot_is_named_by_its_piece_store_and_price_with_no_tooltip_over_its_label(self):
        # The label over a dot shows on hover and focus (and Escape hides it); a screen reader hears it as the
        # dot's name, "Charcoal wool coat, Weekday, 159 €". A tooltip (title) would show over that label, so the
        # dots have none. The photos and the piece rows keep theirs.
        page = self.client.get("/outfits").data.decode()
        first = page[page.index("<article"):page.index("</article>")]
        spots = re.findall(r'<button class="spot"[^>]*>', first)
        rows = re.findall(r'<button class="piece-row"[^>]*title="([^"]+)"[^>]*>.*?<span class="piece-price">([^<]+)<small>([^<·]+)',
                          first, re.S)
        self.assertGreaterEqual(len(spots), 3)
        self.assertEqual(len(spots), len(rows))
        for spot, (name, price, store) in zip(spots, rows):
            self.assertNotIn("title=", spot)
            self.assertIn(f'aria-label="{name}, {store.strip()}, {price.strip()}"', spot)
        self.assertEqual(first.count('class="tile" type="button" title="'), len(spots))
        self.assertTrue(re.search(r'aria-label="[^",]+, (COS|Weekday|Zara), [\d.,]+\s€"', first))

    def test_a_dot_on_a_piece_you_own_says_so(self):
        coat = next(s for s in selection.build().slots if s.garment.key == "coat")
        self.post(f"/slot/{coat.slot['id']}/own")
        page = self.client.get("/outfits", query_string={"n": 60}).data.decode()
        name = coat.slot["name"]
        self.assertIn(f'aria-label="{name}, owned"', page)
