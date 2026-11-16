"""The dots on an outfit's AI picture (app.css ".spot", app.js 6d): small, easy to tap, and with a mouse only there
when the pointer is over the picture or the list of pieces beside it.

The walk-through (tests/browser_check.py, "the dots: small, there when pointed at") looks at them in a real browser.
These read the stylesheet and the script, so that a later change keeps to the same promises.
"""
import re
import unittest
from pathlib import Path

STATIC = Path(__file__).resolve().parent.parent / "wardrobe" / "static"
CSS = re.sub(r"/\*.*?\*/", "", (STATIC / "app.css").read_text(), flags=re.S)
JS = (STATIC / "app.js").read_text()


def rule(selector: str) -> str:
    """What the stylesheet says for exactly this selector."""
    found = re.search(r"(?m)^\s*" + re.escape(selector) + r"\s*\{([^}]*)\}", CSS)
    assert found, f"no rule for {selector}"
    return found.group(1)


def pixels(text: str, name: str) -> float:
    return float(re.search(r"(?<![\w-])" + name + r":\s*(\d+(?:\.\d+)?)px", text).group(1))


class TheDots(unittest.TestCase):
    def test_a_dot_is_small(self):
        dot = rule(".spot")
        self.assertLessEqual(pixels(dot, "width"), 16)
        self.assertEqual(pixels(dot, "width"), pixels(dot, "height"))

    def test_a_dot_has_44_pixels_to_tap(self):
        target = rule(".spot::after")
        self.assertGreaterEqual(pixels(target, "width"), 44)
        self.assertGreaterEqual(pixels(target, "height"), 44)

    def test_with_a_mouse_the_dots_wait_for_the_pointer_or_the_keyboard(self):
        start = CSS.index("@media (hover: hover) {\n  .spot { opacity: 0; }")
        block = CSS[start:CSS.index("\n}", start)]
        shown = re.search(r"\.slide:has\(([^{]*)\) \.spot, \.spot\.lit \{ opacity: 1; \}", block)
        self.assertTrue(shown, block)
        for when in (".stage:hover", ".pieces:hover", ":focus-visible"):
            self.assertIn(when, shown.group(1))
        # Nowhere else are they hidden at rest: on a touch screen they are always there.
        self.assertEqual(CSS.count(".spot { opacity: 0; }"), 1)

    def test_a_dots_label_lets_the_pointer_through_to_the_dot_under_it(self):
        self.assertIn("pointer-events: none", rule(".spot .tip"))

    def test_on_a_computer_with_a_touch_screen_a_touch_brings_the_dots_out_first(self):
        start = CSS.index("@media (hover: hover) {\n  .spot { opacity: 0; }")
        self.assertIn(".slide.touched .spot { opacity: 1; }", CSS[start:CSS.index("\n}", start)])
        self.assertIn("slide.classList.add('touched')", JS)
        self.assertIn("e.pointerType !== 'touch'", JS)

    def test_a_picture_kept_while_a_new_one_is_drawn_does_not_fade_in_again(self):
        self.assertIn("opacity: 1", rule(".look-pic.kept, .look-pic.kept.htmx-added"))
        self.assertIn("img.replaceWith(was)", JS)

    def test_a_dot_and_its_line_in_the_list_mark_each_other(self):
        self.assertIn(".piece-row.lit", CSS)
        self.assertIn(".spot.lit", CSS)
        self.assertIn("other.classList.toggle('lit', on)", JS)

    def test_a_video_left_showing_goes_back_to_the_picture_when_the_row_moves_on(self):
        self.assertIn("if (!inRow(vid)) shut(vid);", JS)


if __name__ == "__main__":
    unittest.main()
