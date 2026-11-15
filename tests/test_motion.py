"""Motion (app.css "Motion", app.js 16): short, and nothing at all for people who ask their device for less motion.

The walk-through (tests/browser_check.py, "motion: quick, never in the way, still if asked") watches it move in a real
browser. These read the stylesheet itself, so that a rule added later keeps to the same promises.
"""
import re
import unittest
from pathlib import Path

CSS = (Path(__file__).resolve().parent.parent / "wardrobe" / "static" / "app.css").read_text()
JS = (Path(__file__).resolve().parent.parent / "wardrobe" / "static" / "app.js").read_text()


def milliseconds(value: str) -> float:
    number, unit = re.fullmatch(r"(\d*\.?\d+)(ms|s)", value).groups()
    return float(number) * (1 if unit == "ms" else 1000)


def tokens() -> dict[str, float]:
    """The motion tokens (--dur-…) and how long each is."""
    return {name: milliseconds(value) for name, value in re.findall(r"(--dur-[\w-]+):\s*(\d*\.?\d+m?s)\s*;", CSS)}


def block(text: str, start: int) -> str:
    """The text of the {…} block whose opening brace is the first one at or after `start`."""
    opened = text.index("{", start)
    depth = 0
    for at in range(opened, len(text)):
        depth += {"{": 1, "}": -1}.get(text[at], 0)
        if depth == 0:
            return text[opened + 1:at]
    raise ValueError("unbalanced braces")


def without_comments(text: str) -> str:
    return re.sub(r"/\*.*?\*/", "", text, flags=re.S)


class MotionIsShort(unittest.TestCase):
    def test_the_tokens_after_a_tap_are_at_most_300_ms(self):
        found = tokens()
        self.assertTrue({"--dur-press", "--dur-quick", "--dur-fade", "--dur-slow", "--dur-loop"} <= set(found), found)
        for name, ms in found.items():
            if name != "--dur-loop":            # the light over something loading: it repeats until the thing is there
                self.assertLessEqual(ms, 300, f"{name} is {ms:.0f} ms")

    def test_every_transition_and_animation_ends_within_300_ms(self):
        # Its delay and its length together, whether written as a token or as a time. A loop (the spinner, the light
        # over something loading) has no end, and is left out.
        lengths = tokens()
        for declaration in re.findall(r"(?:transition|animation)(?:-duration|-delay)?\s*:\s*([^;}]+)", without_comments(CSS)):
            if "infinite" in declaration:
                continue
            for part in declaration.split(","):
                times = [milliseconds(t) for t in re.findall(r"(?<![\w-])(\d*\.?\d+m?s)\b", part)]
                times += [lengths[name] for name in re.findall(r"var\((--dur-[\w-]+)\)", part)]
                self.assertLessEqual(sum(times), 300, f"{part.strip()!r} takes {sum(times):.0f} ms")


class NothingMovesForLessMotion(unittest.TestCase):
    def motion_section(self) -> str:
        start = CSS.index("/* ── Motion ──")
        end = CSS.index("/* ──", start + 10)
        return without_comments(CSS[start:end])

    def test_everything_that_moves_in_the_motion_section_is_for_those_who_did_not_ask_for_less(self):
        section = self.motion_section()
        at = section.index("@media (prefers-reduced-motion: no-preference)")
        moving = block(section, at)
        rest = section.replace(moving, "")
        rest = re.sub(r"@keyframes[^{]+\{(?:[^{}]*\{[^{}]*\})*[^{}]*\}", "", rest)     # what a move is, not when it runs
        for word in ("transition", "animation", "@view-transition", "@starting-style", ":active"):
            self.assertNotIn(word, rest, f"{word} outside the block for people who did not ask for less motion")
        self.assertIn("@view-transition { navigation: auto; }", moving)
        self.assertEqual(CSS.count("@view-transition {"), 1, "a page slides only where motion is welcome")

    def test_the_script_moves_nothing_itself_for_less_motion(self):
        # app.js 16 draws only the budget bar's line with a script; it asks the device first. Everything else it does
        # is a class or an attribute that app.css moves, or not.
        motion = JS[JS.index("// 16. Motion"):]
        self.assertEqual(motion.count(".animate("), 1)
        self.assertIn("less.matches) return;", motion)
        self.assertIn("matchMedia('(prefers-reduced-motion: reduce)')", motion)

    def test_the_script_takes_its_times_from_the_stylesheet(self):
        motion = JS[JS.index("// 16. Motion"):]
        self.assertIn("ms('--dur-slow')", motion)
        self.assertNotRegex(motion, r"setTimeout\([^,]+,\s*(?!10000\))\d+\)", "a time written into the script")


if __name__ == "__main__":
    unittest.main()
