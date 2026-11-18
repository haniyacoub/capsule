"""The app driven through a real browser: what the unit tests cannot see.

    python tests/browser_check.py

Needs the packages in requirements.txt and, once, `python -m playwright install chromium`.

It starts the app in production mode on a spare port, with a throwaway data folder and
stand-ins for the image service and Google's video model (nothing is sent anywhere and nothing is billed), then does
what a new customer would: signs up, is asked three short things he may skip (no bar, no total, nothing filled in for
him) and lands on the outfits with an empty wardrobe (the bar says so; the Wardrobe and the shopping list say so and
lead to the outfits; the whole picture above the tab bar on three phones, with "Add to my wardrobe" where the screen
is 800px tall or more). From then on this customer has the whole plan in his wardrobe, as someone has who was a customer
before the wardrobe became the outfits he said yes to. He changes the price level, watches an outfit's picture
arrive (said to be drawing inside its box, then labelled 'AI picture' on itself, without the
page on a phone jumping), taps "More photos" (told first what it costs; five more pictures made from the front
picture, each showing as it arrives), looks at one large (no dots on it), taps a small picture while another answer is
under way (no late answer undoes the tap) and
does all of it with JavaScript off (the page comes back showing the picture tapped), makes the outfit's AI video with "See it move" (told
first, under the picture and on five phones, that it is his one video today), watches it play under the caption 'Look
and fit will differ', drags it round and turns it with the arrow keys, then finds the day's video used up on
the next outfit, makes the video of the Café picture (the offer names that picture; the clip starts from it, with the
café's own movement, 5 seconds, muted, not dragged round) and finds each picture's clip kept with its picture, opens a piece from its dot, swaps it (said over the outfit, with Undo, which puts back the
product and its lock state), leaves a layer off (said, with 'Put it back'), opens a piece on a phone
(named by its product, the quick changes on the first screen, the page behind it staying put, and back from
comparing all options to the same outfit), opens a piece with JavaScript off (its page, and back to the same outfit)
and with Space, tabs up and down a pop-up that scrolls (nothing with keyboard focus
hidden under its top row, no focus ring cut off at its bottom), sees that with scrollbars shown the page behind
the pop-up does not move sideways,
sees the label 'AI picture' clear of every dot on a picture as narrow as 124px,
moves between outfits (by keyboard too: Next among the first Tab stops, focus going with the outfit shown, which a
screen reader hears named, Tab leading into the outfit shown and Next keeping focus at the end of the row, "Add to my
wardrobe" and its Undo by Enter, Escape hiding a dot's label),
adds an outfit to his wardrobe and "buys" it (keeping the example sizes as his own). Customers of their own build a
wardrobe outfit by outfit (after answering the welcome: yes to an outfit, what the next ones add and their order, what
would go over the budget, "Not for me" with Undo, taking an outfit out under "My outfits" with Undo; on a phone, a
computer and without JavaScript; each is deleted when his part ends). Another chooses a product that is sold out in his size and finds it said wherever the piece shows,
left out of every total, with the next best in his size one tap away and Undo after it (another customer of the
step's own, deleted too), prints the shopping list,
logs in again and lands on the outfits, puts a model together on Profile's character screen (its tabs, the figure
in the middle that follows every height, build, skin and hair choice at once, by mouse, keyboard and links, on a phone,
a computer and without JavaScript, and "Your model" drawn by AI there), uploads a photo, sees Profile ask before
changes not saved would be lost, unticks a store on Profile's Stores tab (its pieces picked again, said in one line;
the last store with products stays ticked, and the six with none yet are listed apart) and ticks it again, sees a
new customer go from the welcome's last step to the style chat by "Or describe your style in your own words" (what he
ticked saved, the welcome over, the message field on the screen, no sum said to someone with an empty wardrobe), ticks a
style and describes his style to the style chat (a stand-in answers, the keyboard stays in the message field and a
screen reader hears the answer; the brief it suggests changes nothing until he presses "Use this brief"; then the
outfits that are his style as a whole say so and the others say nothing, never "Street" on an Office outfit; what the
brief did to his pieces and total is said on the screen the page comes back to, on a phone, a computer and with
JavaScript off; his account deleted after), saves new colours (the plan is rebuilt,
keeping the swapped piece), sees that a phone's first
screen shows the outfit on the model with its price (and every chip over it, whole,
by keyboard), tabs through three pages to see that nothing with keyboard focus is hidden under the
budget bar or the tab bar, locks and chooses on a piece's page by keyboard (focus stays where it was) and pastes
a link that is not a store's (answered inside that section, on a phone's screen, with JavaScript on and off), then a
link from Hirmer, a store with no products yet, with its page as he saved it (name and price filled in, no photo, no
store asked for anything) and a women's link (refused: menswear only),
sees an option's "Choose this" and "Open at COS" side by side wherever they fit, on three phones, adds and saves a
piece of the plan (answered inside that piece, on a phone's screen), and deletes the account. On the way it watches
everything that moves (app.css "Motion"): a tab slides the page forward or back and a tap while it slides is not lost,
the pop-up slides up and lets a tap through as it closes, the AI picture comes up whole over the
pieces' photos (never blank, never half-loaded, on a slow connection too), all within 300 ms and without a layout
shift; and with less motion asked for, the same taps move nothing.

On the way a second customer, on a small product list published for that step alone, skips the welcome, finds on
his Profile what he has not given said in plain lines, and fills a piece the list has nothing for with one tap.
A third picks his colours on a phone by tapping swatches (and by keyboard), sees his first liked colour that is not a
neutral become the plan's accent, and then types colours into the two text fields with JavaScript switched off.
And with the invented sample stores' feeds imported, the customer finds no store catalogues (/stores) until he is
marked as an owner; then his Account page leads to them, on a phone and on a computer: every store with a partner
programme, grouped by network, each with its programme's page as a link, and the samples' products; on a small
laptop (960-1150px) too, with every store's notes in view and no table scrolling sideways.

It exits with an error if a step fails, if any request to the app fails, or if a script on
a page throws. The GitHub checks run it on every push (.github/workflows/checks.yml).
"""
from __future__ import annotations

import csv
import io
import json
import os
import re
import secrets
import shutil
import struct
import sys
import tempfile
import threading
import time
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Started the way PRODUCTION.md says: from a folder, with the data folder named from there
# ("./data-production"), not by its full path. Pictures once could not be shown when started so.
HOME = Path(tempfile.mkdtemp(prefix="capsule-browser-")).resolve()
os.chdir(HOME)
DATA = HOME / "data-production"

# The app reads its settings when it is imported, so they are set first.
os.environ.update(CAPSULE_ENV="production", SECRET_KEY=secrets.token_urlsafe(48), WARDROBE_DATA_DIR="./data-production",
                  OPENAI_API_KEY="stand-in", SITE_URL="http://127.0.0.1",
                  GEMINI_API_KEY="stand-in")     # for the videos ("See it move"); OpenAI still draws the pictures
for name in ("GOOGLE_API_KEY", "SMTP_URL"):
    os.environ.pop(name, None)
sys.path.insert(0, str(ROOT))

from playwright.sync_api import expect, sync_playwright  # noqa: E402
from werkzeug.serving import make_server  # noqa: E402

from wardrobe import colours, db, imagegen, looks, mockchat, person, settings, stylechat, videogen, videos  # noqa: E402
from wardrobe import profile as profile_mod  # noqa: E402
from wardrobe.app import create_app  # noqa: E402
# With an SQLite that can deadlock (db.sqlite_problem) the walk-through's first pages would wait for ever, and every
# step after them fail on a timeout: it stops at once instead, saying why.
if db.sqlite_problem():
    os.chdir(ROOT)
    shutil.rmtree(HOME, ignore_errors=True)
    sys.exit(f"The walk-through cannot run on this Python. {db.sqlite_problem()}")


def picture(width: int = 240, height: int = 360, tint: tuple[int, int, int] = (120, 124, 130)) -> bytes:
    """A small valid PNG: a grey card standing in for a drawn outfit."""
    row = b"\x00" + bytes(tint) * width
    raw = row * height

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))


asked: list[dict] = []      # what the "image service" was asked to draw
slow: list[float] = []      # how many seconds the next drawing is to take instead (draw_again_keeps_the_picture)


finished: list[str] = []    # … and each picture it has sent back
# One of an outfit's further pictures (made from its front picture, `references`) comes back in a colour of its own.
TINTS = {"He walks towards the camera": (150, 150, 110), "He stands turned": (110, 150, 150),
         "city street": (100, 130, 160), "café": (170, 130, 100), "library": (130, 110, 90)}


def stand_in(service, prompt, photo=None, references=()):
    asked.append({"prompt": prompt, "photo": photo, "references": list(references)})
    time.sleep(slow.pop() if slow else 1.5)         # long enough for the page to show that it is waiting
    tint = (90, 120, 170) if photo else (120, 124, 130)
    if references:
        tint = next((colour for words, colour in TINTS.items() if words in prompt.split("\n")[0]), (60, 60, 60))
    finished.append(prompt)
    return picture(tint=tint), "png"


imagegen.draw = stand_in

made: list[str] = []        # what the "video model" was asked to make
refuse: list[imagegen.DrawError] = []   # a problem the "video model" is to have instead, next time (nothing made)
CLIP = (ROOT / "tests" / "fixtures" / "test-pattern.mp4").read_bytes()     # 8 s of ffmpeg's test pattern, no person


made_from: list[tuple[bytes, int]] = []     # … and for each: the picture it starts from, and its length in seconds


def video_stand_in(service, picture, prompt, seconds=8):
    if refuse:
        time.sleep(0.5)
        raise refuse.pop(0)
    made.append(prompt)
    made_from.append((picture, seconds))
    time.sleep(1.5)         # long enough for the page to show that it is being made
    return CLIP


def never(*args, **kwargs):
    raise AssertionError("the walk-through never calls Google")


videogen.make = video_stand_in
imagegen._send = never
stylechat.ask = mockchat.answer     # the style chat's text model: a stand-in that spots a few words (mockchat.py)
# The walk-through's customers all sign up from one address within minutes: more of them than one connection may
# make in an hour (ten; that limit has its own tests in test_production.py). Lifted here, as on the night previews.
settings.SIGNUPS_PER_IP_PER_HOUR = 1_000

failures: list[str] = []
swapped: dict[str, str] = {}    # the piece swapped inside an outfit: its slot and the product chosen
heard: list[str] = []           # every address the server was asked for, in order (see main)
PASSWORD = "only for this check 123"
# Nothing that moves with an end of its own is still moving (see motion_ended() in run).

# Everything that moves on a page, written down as it starts (motion_quick_and_still): what moved, on what, how long it
# takes from the moment it starts (its delay and all its runs), whether it loops (a spinner, the light over something
# loading) or follows a scroll (the outfit row) rather than a clock; whether the page arrived with a view transition
# (a page change that slides), and which way; and the page's layout shifts, every one, those just after a tap too.
MOTION_RECORDER = """(() => {
  window.moved = []; window.change = null; window.jumps = 0;
  const known = new WeakSet();
  const write = () => document.getAnimations().forEach((a) => {
    if (known.has(a) || !a.effect) return;
    known.add(a);
    const t = a.effect.getComputedTiming(), on = a.effect.target;
    window.moved.push({what: a.animationName || a.transitionProperty || 'script',
                       on: (on ? on.id || on.getAttribute('class') || on.tagName : '') + (a.effect.pseudoElement || ''),
                       total: Math.round(t.delay + t.activeDuration), loop: t.iterations === Infinity,
                       scroll: !(a.timeline instanceof DocumentTimeline)});
  });
  ['animationstart', 'transitionrun'].forEach((kind) => document.addEventListener(kind, write, true));
  const tick = () => { write(); requestAnimationFrame(tick); };
  requestAnimationFrame(tick);
  addEventListener('pagereveal', (e) => {
    window.change = {slides: !!e.viewTransition};
    if (e.viewTransition) e.viewTransition.ready.then(() => { window.change.types = [...e.viewTransition.types];
                                                               window.change.ready = true; write(); }, () => {});
  });
  new PerformanceObserver((list) => list.getEntries().forEach((e) => { window.jumps += e.value; }))
    .observe({type: 'layout-shift', buffered: true});
})();"""
# Every frame of an outfit's picture box from now on: the picture in it shown before its file has arrived (a picture
# that builds up in front of you), or the box showing neither the picture nor the pieces' photos (a blank box).
PICTURE_FRAMES = """s => { window.frames = []; const stage = document.querySelector(s + ' .stage');
  const look = () => {
    const pic = stage.querySelector('.look-pic'), img = pic && pic.querySelector('img');
    const photos = getComputedStyle(stage.querySelector('.collage')).visibility === 'visible';
    const before = !!stage.querySelector('.look-was'), shown = pic ? +getComputedStyle(pic).opacity : 0;
    const whole = !!(img && img.complete && img.naturalWidth);
    if (pic) window.frames.push({half: shown > 0.02 && !whole, blank: !photos && !before && (shown < 0.02 || !whole)});
    if (!pic || window.frames.length < 120) requestAnimationFrame(look);
  };
  requestAnimationFrame(look); }"""
STILL = """() => document.getAnimations().every(a => a.playState !== 'running' || !(a.timeline instanceof DocumentTimeline)
                                                  || a.effect.getComputedTiming().iterations === Infinity)"""
EMAIL = f"check-{secrets.token_hex(4)}@example.com"


def run(base: str) -> None:
    first = "#reel .slide:first-child"
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_context(viewport={"width": 1280, "height": 860}).new_page()
        page.set_default_timeout(15000)
        confirmed: list[str] = []     # what the browser asked before going on (deleting the account), each said yes to
        page.on("dialog", lambda d: (confirmed.append(d.message), d.accept()))
        # (The demo catalogue has one picture that is missing on purpose, to show the fallback.)
        page.on("response", lambda r: failures.append(f"{r.status} {r.request.method} {r.url.replace(base, '')[:100]}")
                if r.status >= 400 and r.url.startswith(base) and "does-not-exist" not in r.url else None)
        page.on("pageerror", lambda e: failures.append(f"script error: {e}"))

        def total() -> str:
            return page.locator("#summary .num b").nth(0).inner_text()

        # "More photos" and "See it move" are offered only on the outfits he said yes to (config/looks.toml,
        # more_only_on_yes). The steps that try them use outfits he said yes to: `said_yes` has their sigs.
        said_yes: dict[str, str] = {}

        def say_yes(where_page, slide: str = first) -> str:
            """'Add to my wardrobe' on an outfit of the page showing, sent as a tap sends it (a plain form: the page
            comes back). Returns the outfit's sig, for ?at=, where an outfit he said yes to is shown first in the row
            (as "See it with today's products" leads there)."""
            form = where_page.locator(f"{slide} form.save").first
            assert form.locator("input[name=want]").get_attribute("value") == "save", f"{slide} is in his wardrobe already"
            sig = form.locator("input[name=sig]").get_attribute("value")
            with where_page.expect_navigation(wait_until="networkidle"):
                form.locator("button").click()
            return sig

        def take_out(where_page, sig: str) -> None:
            """'Take out of my wardrobe' on the outfit with this sig: his wardrobe as it was before the yes."""
            where_page.goto(base + f"/outfits?at={sig}", wait_until="networkidle")
            form = where_page.locator(f"{first} form.save").first
            assert form.locator("input[name=sig]").get_attribute("value") == sig and \
                form.locator("input[name=want]").get_attribute("value") == "remove", f"the outfit {sig} is not his to take out"
            with where_page.expect_navigation(wait_until="networkidle"):
                form.locator("button").click()

        def yes_page(more: str = "") -> str:
            """The outfits, with the one he said yes to for the steps on "More photos" and "See it move" first."""
            return f"/outfits?at={said_yes['first']}" + (f"&{more}" if more else "")

        def shows(selector: str, what: str) -> None:
            """The picture itself is on the page, not only the place for it."""
            page.wait_for_function("s => { const i = document.querySelector(s); return i && i.complete; }", arg=selector)
            assert page.eval_on_selector(selector, "i => i.naturalWidth") > 0, f"{what} has its place on the page but did not load"

        def motion_ended(where_page) -> None:
            """What moves after a tap (app.css "Motion": the page sliding in, the pop-up sliding up, the picture coming
            up) has come to rest, as it has for a person's eye before he reads or taps: a step that measures where
            things are, or what is under a point, waits for it. It takes at most 300 ms, so 2 s is a failure. Loops (a
            spinner, the light over something loading) and what follows the outfit row as it scrolls have no end of
            their own and are not waited for."""
            where_page.wait_for_function(STILL, timeout=2000)

        def in_view(selector: str, words: str) -> None:
            """A message is where the eye is after the page has jumped: on the screen, with nothing over it."""
            page.wait_for_selector(selector)
            motion_ended(page)
            assert words in page.locator(selector).first.inner_text(), f"no message saying {words!r} at {selector}"
            where = page.eval_on_selector(selector, """el => {
                const box = el.getBoundingClientRect();
                if (box.bottom <= 0 || box.top >= window.innerHeight) return 'off the screen';
                const top = document.elementFromPoint(box.left + box.width / 2, box.top + Math.min(box.height / 2, 12));
                return top && (top === el || el.contains(top)) ? 'in view' : 'covered';
            }""")
            assert where == "in view", f"the message {words!r} is {where} after the page has jumped to it"

        def top_bar(where_page) -> dict:
            """The bar at the top of a page (his wardrobe's total against his budget), and the messages under it."""
            return where_page.evaluate("""() => {
                const bar = document.getElementById('summary');
                return {words: bar ? bar.innerText.replace(/\\s+/g, ' ').trim() : null,
                        height: bar ? bar.getBoundingClientRect().height : null,
                        starter: !!document.querySelector('.starter') || /Make them mine|Starter outfits/.test(document.body.innerText),
                        flashes: [...document.querySelectorAll('main > .flash')].map(f => f.textContent.trim())};
            }""")

        def skip_the_welcome(where_page) -> None:
            """A customer who has just signed up taps "Skip" on each of the welcome's three steps and is on the outfits."""
            where_page.wait_for_url(base + "/welcome")
            for step in (1, 2, 3):
                assert f"STEP {step} OF 3" in where_page.locator("main").inner_text().upper(), f"the welcome's step {step} does not say which it is"
                where_page.click("button:has-text('Skip')")
                where_page.wait_for_load_state("networkidle")
            where_page.wait_for_url(base + "/outfits")

        def the_whole_plan_is_his(email: str = "", his: bool = True) -> None:
            """This customer (or, with no address, the one who signed up last) has every piece of his plan in his
            wardrobe, each on its own account, and a budget he gave: as someone has who was a customer before the
            wardrobe became the outfits he said yes to and had chosen every piece by hand (db.py, version 9). The steps
            written before then walk the Wardrobe page, the shopping list and the bar with all those pieces on them. How
            a wardrobe is built outfit by outfit is walked by a step of its own (yes_and_no_build_the_wardrobe), with
            nothing set from here. With his=False his wardrobe is emptied again."""
            with db.connect() as con:
                found = (con.execute("SELECT id FROM users WHERE email = ?", (email,)) if email
                         else con.execute("SELECT MAX(id) FROM users")).fetchone()[0]
            with db.as_user(found):
                db.set_setting("kept_pieces", [slot["id"] for slot in db.list_slots()] if his else [])
                # … with the spare of each piece the plan has twice, as such a customer has after the upgrade.
                db.set_setting("spares", [slot["id"] for slot in db.list_slots() if slot["qty"] > 1] if his else [])
                profile_mod.answer("budget")

        def a_customer_from_before(where_page) -> None:
            """What the other steps' customers do after signing up: skip the welcome; and what they have (above)."""
            skip_the_welcome(where_page)
            the_whole_plan_is_his()
            where_page.reload(wait_until="networkidle")

        def example_notes(where_page) -> list[str]:
            """Every line on the Profile page that speaks of example values."""
            return where_page.evaluate("""() => [...document.querySelectorAll('main p')]
                .map(p => p.textContent.replace(/\\s+/g, ' ').trim()).filter(t => /example/i.test(t))""")

        def open_tab(where_page, name: str) -> None:
            """A tab of Profile opened the way a customer does: by tapping it. Its controls then show, the others not."""
            where_page.locator(f"#tab-{name.lower()}").click()
            expect(where_page.locator(f"#tab-{name.lower()}")).to_have_attribute("aria-selected", "true")
            expect(where_page.locator(f"#panel-{name.lower()}")).to_be_visible()

        def pick_colours(where_page, liked=(), avoided=()) -> None:
            """Colours chosen on Profile the way a customer does: by tapping their swatches (in the Colours tab).
            Whatever is chosen already is cleared first (a liked colour takes two taps, one to avoid a single tap),
            then each liked colour is tapped once, most important first, and each to avoid twice. The two hidden
            fields the taps fill in must then name them in that order, as typing them would."""
            if where_page.locator("#tab-colours").get_attribute("aria-selected") != "true":
                open_tab(where_page, "colours")
            for _ in range(60):
                chosen = where_page.locator(".swatch[aria-pressed=true]")
                if not chosen.count():
                    break
                chosen.first.click()
            for key, taps in [(key, 1) for key in liked] + [(key, 2) for key in avoided]:
                for _ in range(taps):
                    where_page.locator(f".swatch[data-colour='{colours.get(key).label.lower()}']").click()
            names = [", ".join(colours.get(key).label.lower() for key in keys) for keys in (liked, avoided)]
            seen = [where_page.input_value("input[name=liked]"), where_page.input_value("input[name=refused]")]
            assert seen == names, f"tapping {list(liked)} once and {list(avoided)} twice wrote {seen}, not {names}"

        def sign_up():
            # A new customer is asked three short things first (his sizes; colours and budget; what he dresses for), each
            # of which he may skip, with no bar, no total and no price on the way. Then the outfits: the bar says his
            # wardrobe is empty, nothing calls the outfits "starter outfits" or asks him to make example values his, and
            # each outfit says what it would add, with "Add to my wardrobe" and a quiet "Not for me". Before any yes the
            # Wardrobe and the shopping list say so plainly and lead to the outfits.
            page.goto(base + "/signup", wait_until="networkidle")
            page.fill("input[name=email]", EMAIL)
            page.fill("input[name=password]", PASSWORD)
            page.click("button:has-text('Create account')")
            page.wait_for_url(base + "/welcome")
            for step, title in ((1, "Your sizes"), (2, "Colours and budget"), (3, "What you dress for")):
                said = page.locator("main").inner_text()
                assert f"STEP {step} OF 3" in said.upper() and title in said, f"the welcome's step {step} reads {said[:120]!r}"
                assert not page.locator("#summary").count(), f"a budget bar on the welcome's step {step}, before he chose anything"
                assert "€" not in page.locator("body").inner_text(), f"a price on the welcome's step {step}"
                assert not page.locator("nav.tabs a").count(), f"tabs to leave by on the welcome's step {step}"
                filled = page.evaluate("""() => [...document.querySelectorAll('main input, main select')]
                    .filter(f => f.type !== 'hidden' && (f.type === 'checkbox' || f.type === 'radio' ? f.checked : f.value))
                    .map(f => f.name)""")
                assert not filled, f"the welcome's step {step} comes with answers filled in for him: {filled}"
                page.click("button:has-text('Skip')")
                page.wait_for_load_state("networkidle")
            page.wait_for_url(base + "/outfits")
            seen = top_bar(page)
            assert seen["words"] and seen["words"].startswith("Your wardrobe: nothing yet"), f"a new customer's bar reads {seen['words']!r}"
            assert "€" not in seen["words"], f"a new customer's bar shows a sum: {seen['words']!r}"
            assert not seen["starter"], "the outfits still speak of starter outfits or 'Make them mine'"
            assert not seen["flashes"], f"a message to read before the outfits: {seen['flashes']}"
            assert page.locator(f"{first} .collage .tile").count() >= 2, "no outfit to answer"
            adds = page.locator(f"{first} .adds").first.inner_text()
            assert re.fullmatch(r"\d+ new pieces [\d.,]+\s€( \(2 × [^)]+\))?", adds), f"the first outfit says of what it adds: {adds!r}"
            answers = page.locator(f"{first} .answer")
            assert answers.locator("button.btn.yes").inner_text().startswith("Add to my wardrobe"), "no 'Add to my wardrobe' on the first outfit"
            assert answers.locator("button.quiet").inner_text() == "Not for me", "no 'Not for me' on the first outfit"
            for url, words in (("/", "Your wardrobe is empty. It holds the pieces of the outfits you say yes to."),
                               ("/list", "Nothing on your list yet. It lists the pieces of the outfits you say yes to.")):
                page.goto(base + url, wait_until="networkidle")
                said = page.locator("main").inner_text()
                assert words in said, f"before any yes, {url} says {said[:200]!r}"
                assert "€" not in page.locator("body").inner_text(), f"before any yes, {url} shows a sum"
                page.click("main a.btn:has-text('See the outfits')")
                page.wait_for_url(base + "/outfits")
            # From here on this customer has the whole plan in his wardrobe (see the_whole_plan_is_his).
            the_whole_plan_is_his()
            page.goto(base + "/outfits", wait_until="networkidle")

        def the_yes_is_on_a_phones_first_screen():
            # On a phone the two answers are always in reach: what a yes adds, "Add to my wardrobe" and "Not for me"
            # stand in a bar above the tab bar, for the outfit that is showing (app.js 17a), whole on the first screen
            # of six phones, the short ones included (a phone's browser with its own bars showing leaves 640 to 664px).
            # The outfit's title and price (above the picture on a phone) are above that bar, and so is the whole
            # picture, its lowest dot included, where the screen is 740px high or more. The bar follows the outfit on screen, and the page
            # still ends below it: its last line can be scrolled clear of the bar.
            for width, height in ((390, 844), (375, 667), (360, 740), (390, 664), (360, 640), (412, 785)):
                context = browser.new_context(viewport={"width": width, "height": height}, is_mobile=True, has_touch=True)
                other = context.new_page()
                other.goto(base + "/login", wait_until="networkidle")
                other.fill("input[name=email]", EMAIL)
                other.fill("input[name=password]", PASSWORD)
                other.click("button:has-text('Log in')")
                other.wait_for_url(base + "/outfits")
                other.wait_for_selector(f"{first} .look-pic img")
                # Invented products here, so the page opens with the "Demo data" notice that customers never see.
                other.evaluate("() => document.querySelectorAll('main .demo').forEach(notice => notice.remove())")
                measure = """() => {
                    const reel = document.getElementById('reel'), slides = [...reel.querySelectorAll('.slide')];
                    const slide = slides[Math.round(reel.scrollLeft / reel.clientWidth)], box = el => el.getBoundingClientRect();
                    const dock = document.getElementById('dock'), inside = sel => dock.querySelector(sel);
                    // (The outfit swiped to has no picture yet: then the box the picture will lie in.)
                    return {bottom: Math.max(box(slide.querySelector('.look-pic') || slide.querySelector('.stage')).bottom,
                                             ...[...slide.querySelectorAll('.spot')].map(d => box(d).bottom)),
                            line: Math.max(...[...slide.querySelectorAll('.about-head h2, .count, .board-cost')].map(el => box(el).bottom)),
                            dock: [box(dock).top, box(dock).bottom], fixed: getComputedStyle(dock).position,
                            adds: inside('.adds') && [box(inside('.adds')).top, box(inside('.adds')).bottom, inside('.adds').textContent.trim()],
                            yes: inside('.btn.yes') && [box(inside('.btn.yes')).top, box(inside('.btn.yes')).bottom],
                            no: inside('form.no button') && [box(inside('form.no button')).top, box(inside('form.no button')).bottom],
                            key: (inside('input[name=key]') || {}).value, slide: slide.id, left_in_outfit: slide.querySelectorAll('[data-answer]').length,
                            tabs: box(document.querySelector('nav.tabs')).top, wide: document.documentElement.scrollWidth};
                }"""
                seen = {**top_bar(other), **other.evaluate(measure)}
                size = f"at {width} x {height}"
                assert seen["height"] <= 96, f"{size} the bar at the top is {seen['height']:.0f}px tall"
                assert seen["fixed"] == "fixed" and seen["dock"][1] <= seen["tabs"] + 1 and seen["dock"][0] > 0, \
                    f"{size} the bar with the answers is not above the tab bar ({seen['tabs']:.0f}px): {seen['dock']} ({seen['fixed']})"
                # An outfit of pieces that are all his already has no "Not for me" (review N6): it is his to save.
                yours = bool(seen["adds"]) and seen["adds"][2].startswith("You can already wear this")
                assert not (yours and seen["no"]), f"{size} 'Not for me' under an outfit he can already wear"
                for what, name in (("adds", "what a yes adds"), ("yes", "'Add to my wardrobe'"), ("no", "'Not for me'")):
                    if what == "no" and yours:
                        continue
                    assert seen[what] and seen["dock"][0] <= seen[what][0] and seen[what][1] <= seen["tabs"], \
                        f"{size} {name} is not on the first screen above the tab bar ({seen['tabs']:.0f}px): {seen[what]}"
                assert re.fullmatch(r"(\d+ new pieces? [\d.,]+\s€.*|You can already wear this: .+ yours)", seen["adds"][2]), \
                    f"{size} the bar says of what a yes adds: {seen['adds'][2]!r}"
                assert seen["slide"] == f"outfit-{seen['key']}" and not seen["left_in_outfit"], \
                    f"{size} the bar's answers are not those of the outfit on screen, or they are there twice: {seen}"
                assert seen["wide"] <= width, f"{size} the page is {seen['wide']}px wide"
                if height >= 740:       # (on the shortest phones the bar may cover the picture's foot until he scrolls)
                    assert seen["bottom"] <= seen["dock"][0] + 1, \
                        f"{size} the picture ends at {seen['bottom']:.0f}px, under the bar with the answers at {seen['dock'][0]:.0f}px"
                if height >= 640:       # the name and price stand above the picture on a phone: never under the bar
                    assert seen["line"] <= seen["dock"][0] + 1, \
                        f"{size} the outfit's title and price end at {seen['line']:.0f}px, under the bar with the answers at {seen['dock'][0]:.0f}px"
                # Swipe to the next outfit: the bar now holds that outfit's answers, and the first one's are back in it.
                other.evaluate("() => { const r = document.getElementById('reel'); r.scrollTo({left: r.clientWidth, behavior: 'instant'}); }")
                other.wait_for_function("() => { const r = document.getElementById('reel'), d = document.querySelector('#dock input[name=key]');"
                                        " return d && r.querySelectorAll('.slide')[1].id === 'outfit-' + d.value; }")
                moved = other.evaluate(measure)
                assert moved["key"] != seen["key"] and other.locator(f"{first} [data-answer] .btn.yes").count() == 1, \
                    f"{size} after a swipe the bar's answers did not follow the outfit: {moved}"
                # Scrolled to its end, the page's last line is clear of the bar.
                other.evaluate("() => window.scrollTo(0, document.documentElement.scrollHeight)")
                other.wait_for_timeout(100)
                end = other.evaluate("""() => { const last = document.querySelector('footer.site-foot') || [...document.querySelectorAll('main > *')].filter(el => el.getClientRects().length && getComputedStyle(el).position !== 'fixed').pop();
                    return {last: last.getBoundingClientRect().bottom, dock: document.getElementById('dock').getBoundingClientRect().top}; }""")
                assert end["last"] <= end["dock"] + 1, f"{size} the page's last line ends at {end['last']:.0f}px, behind the bar with the answers ({end['dock']:.0f}px)"
                context.close()

        def own_typefaces():
            # The one typeface, Archivo, comes from Stilsmith itself. It must really load, under the site's own
            # security policy: a font that fails is replaced by another without any error to see. Text is set at
            # the normal width; the wordmark is the site's name in capitals (by the stylesheet), wide and bold; no
            # font is fetched from another site.
            fonts: list[str] = []
            listen = lambda r: fonts.append(r.url) if r.resource_type == "font" else None  # noqa: E731
            page.on("request", listen)
            page.goto(base + "/profile", wait_until="networkidle")
            loaded = page.evaluate("() => document.fonts.ready.then(() => [...document.fonts]"
                                   ".filter(f => f.status === 'loaded').map(f => f.family.replace(/\"/g, '')))")
            page.remove_listener("request", listen)
            assert set(loaded) == {"Archivo"}, f"Stilsmith's font did not load, or another did: {loaded}"
            assert fonts and all(url.startswith(base + "/static/fonts/archivo-") for url in fonts), \
                f"fonts fetched: {fonts}"
            assert page.evaluate("() => getComputedStyle(document.body).fontFamily").startswith('Archivo'), \
                "the text is not set in Archivo"
            mark = page.evaluate("""() => { const el = document.querySelector('.brand'), s = getComputedStyle(el);
                return {family: s.fontFamily, stretch: s.fontStretch, weight: s.fontWeight, caps: s.textTransform,
                        typed: el.textContent.trim(), shown: el.innerText.trim()}; }""")
            assert mark["family"].startswith("Archivo") and mark["stretch"] == "125%" and mark["weight"] == "600", \
                f"the wordmark is not wide Archivo in the one heavier weight (600): {mark}"
            assert mark["caps"] == "uppercase" and mark["typed"] != mark["typed"].upper() \
                and mark["shown"] == mark["typed"].upper(), f"the wordmark is not the site's name put in capitals: {mark}"
            title = page.evaluate("""() => { const s = getComputedStyle(document.querySelector('main h1'));
                return {family: s.fontFamily, stretch: s.fontStretch, weight: s.fontWeight}; }""")
            assert title == {"family": mark["family"], "stretch": "125%", "weight": "600"}, \
                f"the page's title is not wide, semi-bold Archivo: {title}"
            assert page.evaluate("() => getComputedStyle(document.body).fontVariantNumeric") == "tabular-nums", \
                "digits are not the same width"

        def nothing_scrolls_sideways():
            # A page wider than the screen makes a phone zoom out until everything on it is tiny, and lets
            # a computer scroll sideways into nothing. It happened to Outfits: hidden labels inside the row
            # of outfits were placed against the page instead of the row, and stretched it to twelve outfits.
            wide: list[str] = []
            for width, phone in ((390, True), (1280, False)):
                context = browser.new_context(viewport={"width": width, "height": 844}, is_mobile=phone, has_touch=phone)
                other = context.new_page()

                def measure(path: str) -> None:
                    other.goto(base + path, wait_until="networkidle")
                    other.wait_for_timeout(300)
                    seen = other.evaluate("() => [innerWidth, document.documentElement.scrollWidth]")
                    if seen[0] != width or seen[1] > width + 1:
                        wide.append(f"{path} at {width}px is {seen[1]}px wide")

                for path in ("/", "/signup", "/login"):        # as a visitor
                    measure(path)
                other.goto(base + "/login", wait_until="networkidle")
                other.fill("input[name=email]", EMAIL)
                other.fill("input[name=password]", PASSWORD)
                other.click("button:has-text('Log in')")
                other.wait_for_load_state("networkidle")
                other.goto(base + "/", wait_until="networkidle")      # log-in opens the outfits; the pieces are listed here
                slot = other.locator("a[href^='/slot/']").first.get_attribute("href")
                for path in ("/", "/slots", slot, "/outfits", "/outfits?occasion=saved", "/list", "/profile", "/account"):
                    measure(path)
                context.close()
            assert not wide, "wider than the screen: " + "; ".join(wide)

        def outfits_are_home():
            # The outfits on the model are the heart of Stilsmith: logging in, the first tab and the wordmark
            # lead to them. The plan has no tab of its own: it is one tap from the Wardrobe page.
            for width, phone in ((390, True), (1280, False)):
                context = browser.new_context(viewport={"width": width, "height": 844}, is_mobile=phone, has_touch=phone)
                other = context.new_page()
                other.goto(base + "/login", wait_until="networkidle")
                other.fill("input[name=email]", EMAIL)
                other.fill("input[name=password]", PASSWORD)
                other.click("button:has-text('Log in')")
                other.wait_for_load_state("networkidle")
                assert other.url == base + "/outfits", f"logging in at {width}px opens {other.url}, not the outfits"
                tabs = other.locator("nav.tabs a")
                names = [name.strip() for name in tabs.all_inner_texts()]
                lefts = [tabs.nth(i).bounding_box()["x"] for i in range(tabs.count())]
                assert names == ["Outfits", "Wardrobe", "Shopping", "Profile"] and lefts == sorted(lefts), \
                    f"the tabs at {width}px read {names}"
                tabs.filter(has_text="Wardrobe").click()
                other.wait_for_url(base + "/")
                other.locator("main a", has_text="Edit the plan").click()
                other.wait_for_url(base + "/slots")
                lit = other.locator("nav.tabs a[aria-current=page]").all_inner_texts()
                assert lit == ["Wardrobe"], f"on the plan the tab marked as current is {lit}, not Wardrobe"
                other.locator(".brand").click()
                other.wait_for_url(base + "/outfits")
                context.close()

        def the_landing_page():
            # A stranger gives the page a few seconds. It says what Stilsmith is and who it is for, in plain words,
            # with the way in on a phone's first screen and one 'Log in' there (the header's), the headline in
            # Stilsmith's wide Archivo, no text cut off, nothing drawn from the demo data, and a description for search
            # results. A customer back on the public pages is one tap from the outfits.
            for width, phone in ((390, True), (1280, False)):
                context = browser.new_context(viewport={"width": width, "height": 844}, is_mobile=phone, has_touch=phone)
                visitor = context.new_page()
                fetched: list[str] = []
                visitor.on("request", lambda r: fetched.append(r.url))
                visitor.goto(base + "/", wait_until="networkidle")
                seen = visitor.evaluate("""() => document.fonts.ready.then(() => {
                    const shown = el => { const b = el.getBoundingClientRect(); return b.width > 0 && b.bottom > 0 && b.top < innerHeight; };
                    const join = [...document.querySelectorAll('main a')].find(a => a.textContent.trim() === 'Create a free account');
                    return {text: document.querySelector('main').innerText.toLowerCase(),
                            log_in: [...document.querySelectorAll('a, button')].filter(el => el.textContent.trim() === 'Log in' && shown(el)).length,
                            join: !!join && shown(join) && join.getBoundingClientRect().bottom <= innerHeight,
                            title: getComputedStyle(document.querySelector('main h1')).fontFamily,
                            wide: getComputedStyle(document.querySelector('main h1')).fontStretch,
                            loaded: [...document.fonts].filter(f => f.status === 'loaded').map(f => f.family.replace(/"/g, '')),
                            description: (document.querySelector('meta[name=description]') || {}).content || '',
                            picture: (() => { const box = document.querySelector('.hero-pic-box'), img = box && box.querySelector('img');
                                if (!box) return null; const b = box.getBoundingClientRect(), h = document.querySelector('main h1').getBoundingClientRect();
                                return {top: b.top, bottom: b.bottom, left: b.left, height: b.height, loaded: img.complete && img.naturalWidth > 0,
                                        label: box.querySelector('.ai-chip').textContent, words_right: h.right};})(),
                            cut: [...document.querySelectorAll('main h1, main h2, main p, main .btn')]
                                 .filter(el => el.scrollWidth > el.clientWidth + 1).map(el => el.textContent.trim().slice(0, 30))};
                })""")
                context.close()
                assert "men's" in seen["text"].split(), f"at {width}px the page does not say who Stilsmith is for"
                planner = [word for word in ("slot", "candidate", "score") if word in seen["text"]]
                assert not planner, f"the planner's words on the landing page: {planner}"
                assert seen["log_in"] == 1, f"'Log in' is on the first screen {seen['log_in']} times at {width}px"
                assert seen["join"], f"'Create a free account' is not on the first screen at {width}px"
                # Archivo, and no other font. (With the picture on the first screen the browser may show the page a moment
                # before Archivo has arrived, in Archivo's own stand-ins, made from the device's Arial to Archivo's
                # measurements so that nothing moves when it comes: app.css. Those are the device's, fetched from nowhere.)
                assert seen["title"].startswith("Archivo") and seen["wide"] == "125%" and "Archivo" in seen["loaded"] \
                    and set(seen["loaded"]) <= {"Archivo", "Archivo Fallback", "Archivo Wide Fallback"}, \
                    f"the headline is not set in wide Archivo at {width}px: {seen['title']}, {seen['wide']}, {seen['loaded']}"
                assert not [url for url in fetched if "font" in url and not url.startswith(base + "/static/fonts/")], \
                    f"the landing page fetches a font from elsewhere at {width}px"
                assert not seen["cut"], f"text cut off at {width}px: {seen['cut']}"
                assert seen["description"], "no description for search results and shared links"
                assert not [url for url in fetched if "/mock/img/" in url], "the landing page still loads the demo drawings"
                assert not [url for url in fetched if "htmx" in url], f"the landing page loads htmx at {width}px"
                # The house model's AI picture (review N12), labelled, loaded, the whole of it on the first screen: under
                # the headline and big on a phone (the way in still under it, above), beside the words on a computer.
                shown = seen["picture"]
                assert shown and shown["loaded"] and shown["label"] == "AI picture", f"no labelled picture at {width}px: {shown}"
                assert shown["top"] >= 0 and shown["bottom"] <= 844, f"the picture is not whole on the first screen at {width}px: {shown}"
                if phone:
                    assert shown["height"] >= 400, f"the picture is {shown['height']:.0f}px tall on a 390 x 844 phone"
                else:
                    assert shown["left"] >= shown["words_right"], f"the picture is not beside the words at {width}px: {shown}"
            page.goto(base + "/legal/privacy", wait_until="networkidle")    # the customer is logged in here
            page.locator(".public-nav a", has_text="Open my outfits").click()
            page.wait_for_url(base + "/outfits")

        def public_pages_and_errors():
            # A visitor who only reads the website is given no cookie (nothing to ask consent for); the log-in form
            # sets the one its token needs. A page that isn't there says so in Stilsmith's words, with the wordmark, the
            # way home and the legal links, on a phone and on a computer. Stilsmith's icon is there for browsers to find.
            for width, phone in ((390, True), (1280, False)):
                context = browser.new_context(viewport={"width": width, "height": 844}, is_mobile=phone, has_touch=phone)
                visitor = context.new_page()
                for path in ("/", "/legal/privacy", "/does-not-exist"):     # (the 404 at the end is expected)
                    visitor.goto(base + path, wait_until="networkidle")
                assert not context.cookies(), f"reading the website set a cookie: {[c['name'] for c in context.cookies()]}"
                seen = visitor.evaluate("""() => ({
                    title: document.querySelector('main h1').textContent.trim(),
                    text: document.body.innerText,
                    links: [...document.querySelectorAll('a')].map(a => [a.textContent.trim(), a.getAttribute('href')]),
                    wide: document.documentElement.scrollWidth,
                    cut: [...document.querySelectorAll('main h1, main p, main .btn')].filter(el => el.scrollWidth > el.clientWidth + 1).length})""")
                assert seen["title"] == "We can't find that page", f"a missing page at {width}px says {seen['title']!r}"
                assert "requested URL" not in seen["text"], "a missing page still shows Werkzeug's sentence"
                assert seen["links"][:2] == [["Stilsmith", "/"], ["Go to the home page", "/"]], f"the way home: {seen['links']}"
                assert ["Privacy policy", "/legal/privacy"] in seen["links"], "no legal links on a missing page"
                assert seen["wide"] <= width + 1 and not seen["cut"], f"the missing page does not fit {width}px"
                icon = context.request.get(base + "/favicon.ico")
                assert icon.ok and icon.headers["content-type"].startswith("image/"), "no /favicon.ico"
                visitor.goto(base + "/login", wait_until="networkidle")
                assert [c["name"] for c in context.cookies()] == ["session"], "the log-in form has no cookie for its token"
                context.close()
            page.goto(base + "/does-not-exist", wait_until="networkidle")      # the customer is logged in here
            page.locator("main a", has_text="Go to your outfits").click()
            page.wait_for_url(base + "/outfits")

        def the_wordmark_fits():
            # The name is Stilsmith, two letters longer than the old one. On the narrowest phone (320px), a usual one
            # (390px) and a computer, for a visitor and for a customer: every page's title and the wordmark say
            # Stilsmith, the wordmark is on one line, whole, and touches nothing else in the header, and "Log in",
            # "Create account", "Account" and the tabs keep their words on one line each.
            measure = """() => document.fonts.ready.then(() => {
                const lines = el => { const range = document.createRange(); range.selectNodeContents(el);
                    return new Set([...range.getClientRects()].filter(r => r.width > 0).map(r => Math.round(r.top))).size; };
                const brand = document.querySelector('header.top .brand'), b = brand.getBoundingClientRect();
                const others = [...document.querySelectorAll('header.top .public-nav a, header.top .account-link, nav.tabs a')]
                    .filter(el => el.getBoundingClientRect().width > 0);
                return {title: document.title, text: brand.textContent.trim(), lines: lines(brand),
                        cut: brand.scrollWidth > brand.clientWidth + 1,
                        touching: others.filter(el => { const r = el.getBoundingClientRect();
                            return r.left < b.right && r.right > b.left && r.top < b.bottom && r.bottom > b.top; })
                            .map(el => el.textContent.trim()),
                        wrapped: others.filter(el => lines(el) > 1).map(el => el.textContent.trim())};
            })"""
            for width in (320, 390, 1280):
                phone = width < 760
                context = browser.new_context(viewport={"width": width, "height": 800}, is_mobile=phone, has_touch=phone)
                other = context.new_page()
                seen = {}
                for path in ("/", "/login", "/does-not-exist"):     # as a visitor (the 404 is expected)
                    other.goto(base + path, wait_until="networkidle")
                    seen["visitor " + path] = other.evaluate(measure)
                other.goto(base + "/login", wait_until="networkidle")
                other.fill("input[name=email]", EMAIL)
                other.fill("input[name=password]", PASSWORD)
                other.click("button:has-text('Log in')")
                other.wait_for_url(base + "/outfits")
                for path in ("/outfits", "/account", "/"):
                    other.goto(base + path, wait_until="networkidle")
                    seen["customer " + path] = other.evaluate(measure)
                context.close()
                for where, s in seen.items():
                    assert s["text"] == "Stilsmith", f"at {width}px the wordmark on {where} says {s['text']!r}"
                    assert re.fullmatch(r"Stilsmith — .+|.+ · Stilsmith", s["title"]), \
                        f"at {width}px the title of {where} is {s['title']!r}"
                    assert s["lines"] == 1 and not s["cut"], f"at {width}px the wordmark on {where} is not one whole line"
                    assert not s["touching"], f"at {width}px the wordmark on {where} touches {s['touching']}"
                    assert not s["wrapped"], f"at {width}px on {where} these break onto two lines: {s['wrapped']}"

        def tabs_fetch_only_the_page():
            # The browser keeps the stylesheet, the scripts and the fonts for a year (their addresses change when they do),
            # so moving between tabs asks the server for the page alone: on a slow phone connection, a round trip less
            # before anything shows. Counted where the server hears it: Playwright also reports the files the browser
            # took from its own cache.
            page.goto(base + "/outfits", wait_until="networkidle")
            heard.clear()
            for name in ("Wardrobe", "Shopping", "Profile", "Outfits"):
                page.locator("nav.tabs a", has_text=name).click()
                page.wait_for_load_state("networkidle")
            kept = ("/static/app.css", "/static/app.js", "/static/vendor/", "/static/fonts/")
            again = sorted({path for path in heard if path.startswith(kept)})
            assert "/list" in heard and "/profile" in heard, f"the tabs were not followed: {heard}"
            assert not again, f"moving between tabs asked the server again for {again}"

        def price_levels():
            page.goto(base + "/", wait_until="networkidle")
            assert page.locator(".levels small").count() == 6, "six choices, each with its total"
            cheapest = total()
            page.locator(".levels label", has_text="Top").click()
            page.wait_for_function("t => document.querySelector('#summary .num b').textContent !== t", arg=cheapest)
            assert total() == page.locator("#level-top").inner_text(), "the total and the level's total disagree"
            page.locator(".levels label", has_text="Best for budget").click()
            page.wait_for_function("() => document.querySelector('#summary .num b').textContent === "
                                   "document.querySelector('#level-budget').textContent")
            assert "over" not in page.locator("#summary .num.left .lbl").inner_text().lower(), "over the budget"
            page.locator(".levels label", has_text="Cheapest").first.click()
            page.wait_for_function("t => document.querySelector('#summary .num b').textContent === t", arg=cheapest)

        def levels_fit_every_screen():
            # The six price levels with what the wardrobe costs at each: three by two on the smallest phones, one
            # row of six on a computer, the quality slider below them, every name and amount inside its cell, and
            # the amounts in full colour (faded, they read at 2.9:1, under the 4.5:1 that small text needs).
            page.goto(base + "/", wait_until="networkidle")
            for width, shape in ((320, [3, 2]), (1280, [6, 1])):
                page.set_viewport_size({"width": width, "height": 860})
                seen = page.evaluate("""() => {
                    const cells = [...document.querySelectorAll('.levels label')].map(l => l.getBoundingClientRect());
                    const words = [...document.querySelectorAll('.levels span, .levels small')];
                    return {shape: [new Set(cells.map(c => Math.round(c.left))).size, new Set(cells.map(c => Math.round(c.top))).size],
                            below: document.querySelector('.thr').getBoundingClientRect().top >=
                                   document.querySelector('.levels').getBoundingClientRect().bottom,
                            spills: words.filter(w => w.scrollWidth > w.clientWidth + 1).map(w => w.textContent.trim()),
                            faded: [...document.querySelectorAll('.levels small')].filter(s => getComputedStyle(s).opacity !== '1').length};
                }""")
                assert seen["shape"] == shape, f"at {width}px the price levels are {seen['shape']} (columns, rows), not {shape}"
                assert seen["below"], f"at {width}px the quality slider is not below the price levels"
                assert not seen["spills"], f"at {width}px a price level does not fit its cell: {seen['spills']}"
                assert not seen["faded"], "the price levels' amounts are faded"
            page.set_viewport_size({"width": 1280, "height": 860})

        def out_of_size_fades_only_the_photo():
            # An option that is not in your size can still be chosen, so only its photo fades. Its words keep their
            # full strength, and so does the colour swatch with the colour's name that shows where the store's photo
            # is missing: faded with the photo, the name 'Dark Grey' read at 2.6:1, under the 4.5:1 small text needs.
            # Which options are in your size depends on the day's stock, so the check makes one so itself.
            page.goto(base + "/", wait_until="networkidle")
            page.goto(base + page.locator("a[href^='/slot/']").first.get_attribute("href"), wait_until="networkidle")
            seen = page.evaluate("""() => {
                const strength = (el) => { let o = 1; for (; el; el = el.parentElement) o *= +getComputedStyle(el).opacity; return o; };
                const option = document.querySelector('.cand .pic img').closest('.cand');
                option.classList.add('out');                       // not in your size
                const pic = option.querySelector('.pic'), name = pic.querySelector('.fb');
                pic.classList.remove('noimg');                     // with the store's photo
                const photo = strength(pic.querySelector('img')), words = strength(option.querySelector('.cand-body'));
                pic.classList.add('noimg');                        // and where the photo did not load
                return {photo, words, swatch: strength(pic), name: strength(name),
                        name_shown: getComputedStyle(name).display !== 'none' && name.textContent.trim() !== ''};
            }""")
            assert seen["name_shown"], "a missing photo does not show the colour's name on its swatch"
            assert seen["swatch"] == 1 and seen["name"] == 1, f"the swatch and colour name of an option not in your size are faded: {seen}"
            assert seen["words"] == 1, f"the words of an option not in your size are faded: {seen}"
            assert seen["photo"] < 1, "the photo of an option not in your size is not faded"

        def drawing_status(where_page) -> dict:
            """What the first outfit says while its picture is drawn, and whether that is inside the picture's box."""
            return where_page.evaluate("""s => {
                const band = document.querySelector(s + ' .look-bar.wait'), box = el => el.getBoundingClientRect();
                if (!band) return {words: null};
                const b = box(band), p = box(document.querySelector(s + ' .collage'));
                return {words: band.textContent.replace(/\\s+/g, ' ').trim(), top: b.top, bottom: b.bottom,
                        inside: b.left >= p.left - 0.5 && b.right <= p.right + 0.5 && b.top >= p.top - 0.5 && b.bottom <= p.bottom + 0.5};
            }""", first)

        def labelled(where_page, where: str) -> dict:
            """The picture carries the words 'AI picture', on the picture itself."""
            label = where_page.evaluate("""s => {
                const chip = document.querySelector(s + ' .look-pic .ai-chip'), box = el => el.getBoundingClientRect();
                if (!chip) return null;
                const c = box(chip), p = box(chip.closest('.look-pic')), style = getComputedStyle(chip);
                return {words: chip.textContent.trim(), bottom: c.bottom,
                        shown: style.visibility === 'visible' && style.display !== 'none' && c.width > 0 && c.height > 0,
                        on: c.left >= p.left && c.right <= p.right && c.top >= p.top && c.bottom <= p.bottom};
            }""", first)
            assert label and label["words"] == "AI picture" and label["shown"] and label["on"], \
                f"{where}: the picture does not carry the words 'AI picture' on itself: {label}"
            return label

        def label_and_dots(where_page) -> dict:
            """The label 'AI picture' and the dots on the first outfit's picture: how many dots meet the label, and the
            button 'See it move' (its words, read out, and its width)."""
            return where_page.evaluate("""s => {
                const slide = document.querySelector(s), box = el => el.getBoundingClientRect();
                const pic = box(slide.querySelector('.look-pic')), chip = box(slide.querySelector('.look-pic .ai-chip'));
                const meet = (a, b) => a.left < b.right && b.left < a.right && a.top < b.bottom && b.top < a.bottom;
                const dots = [...slide.querySelectorAll('.spot')].map(box).filter(d => d.width);
                const pill = slide.querySelector('.vid-pill');
                return {width: Math.round(pic.width), met: dots.filter(d => meet(chip, d)).length, dots: dots.length,
                        label_h: Math.round(chip.height),
                        chip_on: chip.left >= pic.left && chip.bottom <= pic.bottom + .5 && chip.width > 0,
                        pill: pill && {words: pill.textContent.trim(), width: box(pill).width}};
            }""", first)

        def the_label_never_meets_a_dot(where_page, where: str) -> None:
            # The label 'AI picture' and the dots never meet: on the picture as this screen has it, and on pictures 150
            # to 240px wide (a phone's picture is never narrower than 150px, under the longest message on the shortest
            # phone: app.css, "Outfits on a phone"). Under 200px "See it move" is its play sign alone, so that its
            # words do not cover the head; they are still read out.
            seen = label_and_dots(where_page)
            assert seen["dots"] and not seen["met"] and seen["chip_on"], f"{where}: the label 'AI picture' meets a dot: {seen}"
            for width in (150, 160, 170, 180, 186, 190, 198, 200, 220, 240):
                where_page.evaluate("w => document.querySelector('.looks').style.setProperty('--stage-w', w + 'px')", width)
                seen = label_and_dots(where_page)
                assert not seen["met"] and seen["chip_on"], f"{where}, a picture {width}px wide: the label meets a dot: {seen}"
                # On most phones in a browser the picture is 198px wide, and 186px after his first yes: there the
                # label is still one line, 'AI PICTURE', not 'AI' over 'PICTURE' (which is for pictures narrower still).
                assert width < 186 or seen["label_h"] <= 26, \
                    f"{where}, a picture {width}px wide: the label 'AI picture' is on two lines ({seen['label_h']}px high)"
                if width < 200 and seen["pill"]:
                    assert seen["pill"]["width"] <= 44 and seen["pill"]["words"] == "See it move", \
                        f"{where}, a picture {width}px wide: 'See it move' covers the head, or is not read out: {seen}"
            where_page.evaluate("() => document.querySelector('.looks').style.removeProperty('--stage-w')")

        def picture_arrives():
            page.goto(base + "/outfits", wait_until="networkidle")
            assert page.locator(f"{first} .collage .tile").count() >= 2, "no pieces on the first outfit"
            page.wait_for_selector(f"{first} .look-bar.wait")              # asked for by itself, then waited for
            status = drawing_status(page)
            # It asks the server again every 3 s: a screen reader must not read it out each time (the page's one live
            # region says 'Picture ready' instead, once).
            assert page.eval_on_selector(f"{first} .look-bar.wait", "el => !el.closest('[role=status], [aria-live]')"), \
                "the drawing status, asked for again every few seconds, is read out by screen readers each time"
            # Nothing else is being drawn, so it is drawn at once: it must not be said to be waiting its turn.
            assert status["words"] and status["words"].startswith("Drawing this outfit") and status["inside"], \
                f"while the only picture is drawn, the status is not 'Drawing this outfit…' inside the picture's box: {status}"
            page.wait_for_selector(f"{first} .look-pic img")
            shows(f"{first} .look-pic img", "the picture of the outfit")
            # The pieces' photos stay under the picture while it comes up over them (280 ms), and not a moment after.
            expect(page.locator(f"{first} .collage"), "the product photos still show under the picture").to_be_hidden(timeout=1000)
            assert page.locator(f"{first} .spot").count() == page.locator(f"{first} .piece-row").count(), "a dot per piece"
            labelled(page, "1280 x 860")

        def a_picture_arrives_on_a_phone_without_a_jump():
            # On a phone (390 x 844), an outfit whose picture is not drawn yet. While it is drawn, what is going on is
            # said on the first screen, inside the picture's box; when it arrives it carries the words 'AI picture' on
            # itself, on the first screen too, and nothing on the page jumps: the layout shift browsers measure
            # (CLS) stays at most 0.05. The first outfit's picture is then fetched before anything else on the page.
            context = browser.new_context(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
            other = context.new_page()
            other.goto(base + "/login", wait_until="networkidle")
            other.fill("input[name=email]", EMAIL)
            other.fill("input[name=password]", PASSWORD)
            other.click("button:has-text('Log in')")
            other.wait_for_load_state("networkidle")
            for seed in range(101, 141):                # a shuffle whose first outfit has no picture yet
                other.goto(base + f"/outfits?seed={seed}", wait_until="domcontentloaded")
                if not other.locator(f"{first} .look-pic").count():
                    break
            else:
                raise AssertionError("the first outfit of every shuffle tried already has its picture")
            other.wait_for_load_state("load")
            other.evaluate("() => document.fonts.ready")
            # Invented products here, so the page opens with the "Demo data" notice that customers never see.
            other.evaluate("() => document.querySelectorAll('main .demo').forEach(notice => notice.remove())")
            other.evaluate("""() => { window.jumps = 0; new PerformanceObserver(list => list.getEntries()
                .forEach(e => { if (!e.hadRecentInput) window.jumps += e.value; })).observe({type: 'layout-shift'}); }""")
            other.wait_for_selector(f"{first} .look-bar.wait")
            tabs = other.evaluate("() => document.querySelector('nav.tabs').getBoundingClientRect().top")
            status = drawing_status(other)
            assert status["words"] and status["inside"] and 0 <= status["top"] and status["bottom"] <= tabs, \
                f"at 390 x 844 the drawing status is not on the first screen inside the picture's box: {status}"
            other.wait_for_selector(f"{first} .look-pic img")
            other.wait_for_function("s => document.querySelector(s).complete", arg=f"{first} .look-pic img")
            other.wait_for_timeout(500)                 # the picture fades in
            label = labelled(other, "390 x 844")
            assert label["bottom"] <= tabs, f"at 390 x 844 the label 'AI picture' ends at {label['bottom']:.0f}px, under the tab bar"
            jumps = other.evaluate("() => window.jumps")
            assert jumps <= 0.05, f"the page jumped when the picture arrived: a layout shift of {jumps:.3f}"
            other.reload(wait_until="domcontentloaded")
            fetched = other.evaluate("""() => [...document.querySelectorAll('#reel .slide .look-pic img')].map(img => ({
                first: img.closest('.slide') === document.querySelector('#reel .slide'), priority: img.getAttribute('fetchpriority'),
                lazy: img.getAttribute('loading') === 'lazy', sized: !!(img.getAttribute('width') && img.getAttribute('height'))}))""")
            top = [img for img in fetched if img["first"]]
            assert top and top[0]["priority"] == "high" and not top[0]["lazy"] and top[0]["sized"], \
                f"the first outfit's picture is not fetched first, or has no size: {top}"
            assert all(img["lazy"] for img in fetched if not img["first"]), f"another outfit's picture is not fetched lazily: {fetched}"
            context.close()

        def more_only_on_a_yes():
            # The front picture of every outfit looked at is drawn by itself; "More photos" and "See it move" are
            # offered only on an outfit he has said yes to. On one he has not: neither, and in their place under the
            # picture one short line says what a yes brings ("Add it to your wardrobe for more photos and a video.").
            # After "Add to my wardrobe" (the page comes back) the same outfit, shown first by its address, has both,
            # and no such line. A second outfit is added too, for "See it move" on another outfit. The steps that try
            # them use these two; both are taken out again after them (take_them_out_again).
            page.goto(base + "/outfits", wait_until="networkidle")
            page.wait_for_selector(f"{first} .look-pic img")
            line = page.locator(f"{first} .shots-yes-first")
            assert line.count() == 1 and line.inner_text() == looks.NOT_YET_SHORT, \
                f"an outfit not said yes to does not say what a yes brings: {line.all_inner_texts()}"
            assert not page.locator(f"{first} .shots .btn").count() and not page.locator(f"{first} .vid-pill").count(), \
                "'More photos' or 'See it move' is offered on an outfit he has not said yes to"
            said_yes["first"] = say_yes(page)
            page.goto(base + yes_page(), wait_until="networkidle")
            page.wait_for_selector(f"{first} .look-pic img")
            assert page.locator(f"{first} .shots .btn").inner_text() == "More photos" and page.locator(f"{first} .vid-pill").count() \
                and not page.locator(f"{first} .shots-yes-first").count(), \
                "after his yes the outfit does not offer 'More photos' and 'See it move', or still says to add it"
            page.goto(base + "/outfits", wait_until="networkidle")
            said_yes["second"] = say_yes(page)

        def take_them_out_again():
            # The two outfits said yes to for the steps on "More photos" and "See it move" are taken out again: the
            # steps after them start from his wardrobe as it was. Their photos and videos stay, and are still shown.
            def photos(sig: str) -> list[str]:
                page.goto(base + f"/outfits?at={sig}", wait_until="networkidle")
                page.wait_for_selector(f"{first} .look-pic img")
                return page.eval_on_selector_all(f"{first} .shots-row img", "imgs => imgs.map(i => i.getAttribute('src'))")

            kept = {sig: photos(sig) for sig in (said_yes["second"], said_yes["first"])}
            before = len(asked), len(made)
            for sig in kept:
                take_out(page, sig)
                assert photos(sig) == kept[sig], f"taken out, the outfit's photos are not those it had: {kept[sig]}"
                assert not page.locator(f"{first} .shots .btn").count() and not page.locator(f"{first} .vid-pill:not([data-vid-open])").count(), \
                    "taken out, the outfit still offers 'More photos' or a new video"
                assert page.locator(f"{first} .shots-yes-first").count() == (len(kept[sig]) < 6), \
                    "taken out, the outfit does not say that a yes brings more photos (or says it with all six there)"
            assert (len(asked), len(made)) == before, "taking outfits out drew or made something"
            page.goto(base + "/outfits", wait_until="networkidle")

        def more_photos_of_the_outfit():
            # Under each outfit's picture, a row of its small pictures. At first the front picture alone (the one drawn
            # by itself, on white, with the dots), and "More photos", with what it costs said beside it before the tap:
            # "5 pictures". Tapped (here by keyboard), it has five more pictures made FROM the front
            # picture, which goes to the image service with the words: walking, turned, on a street, in a café, in a
            # library. The large picture stays as it is meanwhile; each small picture shows as it arrives; keyboard
            # focus goes to the picture shown. Tapping a small picture shows it large, without dots (they are placed for
            # the front picture's pose), and costs nothing; back on the front picture the dots are there again. On a
            # phone and a computer, light and dark, the row lies under the line under the picture, whole on the screen,
            # each picture 48 by 64px (large enough to tell the six apart) with its name under it (Front, Walking,
            # Turned, Street, Café, Library), the one shown framed so that it can be told (3:1); on a phone the
            # outfit's title and price still end above the tab bar. On a short phone (390 x 664, 320 x 568:
            # the browser's own bars showing) the pictures are 30 by 40px without names, as before they had names,
            # so nothing is pushed off the first screen, and the six fit. Where six of 48px do not fit (a laptop's
            # window, 1366 x 650, where the picture is narrower than that; a tall phone only 320px wide), the six are
            # narrower, whole in their row with their names. The row never scrolls sideways: a mouse could not reach
            # a picture cut off, Tab reaches the last one whole, and a sideways swipe that starts on the row moves on
            # to the next outfit, like a swipe anywhere else on the outfit. "Draw again" on the front picture, right
            # after "More photos", asks first, under the picture, because the other five would go with it.
            row = f"{first} .shots"
            cells = ("s => [...document.querySelectorAll(s + ' .shots-row button[aria-pressed]')].map(b => ({"
                     "name: b.id.split('-').pop(), pressed: b.getAttribute('aria-pressed'), label: b.getAttribute('aria-label'),"
                     "picture: !!b.querySelector('img'), drawing: !!b.querySelector('.spin')}))")
            rules = looks.load_rules()
            changes = {name: shot["change"] for group in ("poses", "scenes") for name, shot in rules[group].items()}
            order = ["front", *changes]
            assert order == ["front", "walking", "turned", "street", "cafe", "library"], f"an outfit's pictures are {order}"
            names = dict(zip(order, ("Front", "Walking", "Turned", "Street", "Café", "Library")))

            def swipe(session, other, selector: str, distance: int = -250) -> None:
                """A sideways swipe by touch that starts on `selector` in the first outfit (at its right end when
                swiping left). On a phone it is first scrolled clear of the bar with the answers, if that covers it
                (the line under the picture and the small pictures may be under it on the first screen)."""
                other.evaluate("""s => { const el = document.querySelector(s), dock = document.getElementById('dock');
                    if (!el || !dock || dock.hidden) return;
                    const below = el.getBoundingClientRect().bottom + 8 - dock.getBoundingClientRect().top;
                    if (below > 0) window.scrollBy({top: below, behavior: 'instant'}); }""", f"{first} {selector}")
                box = other.locator(f"{first} {selector}").bounding_box()
                session.send("Input.synthesizeScrollGesture", {
                    "x": int(box["x"] + (box["width"] - 30 if distance < 0 else 30)), "y": int(box["y"] + box["height"] / 2),
                    "xDistance": distance, "yDistance": 0, "gestureSourceType": "touch", "speed": 800})
                other.wait_for_timeout(900)

            at = "() => document.getElementById('reel').scrollLeft"       # how far the outfits have moved

            def narrow_phone() -> None:
                # A tall phone under 360px wide: six pictures of 48px do not fit. They are narrower there (41px, 3 wide
                # by 4 high), all six whole in one row with their names, and the row does not scroll: the last one is
                # whole when Tab reaches it, and a sideways swipe that starts on the row moves on to the next outfit.
                # (Some headless browsers ignore a synthesized swipe: then one that starts on the line above is
                # ignored too, and only the row's style is checked.)
                context, other = logged_in_on(browser, viewport={"width": 320, "height": 844}, is_mobile=True, has_touch=True)
                other.goto(base + yes_page(), wait_until="networkidle")
                other.wait_for_selector(f"{first} .look-pic img")
                seen = other.evaluate("""s => {
                    const shots = document.querySelector(s + ' .shots'), row = shots.querySelector('.shots-row'), box = el => el.getBoundingClientRect();
                    const pics = [...row.querySelectorAll('.shot-pic')], r = box(shots), words = [...row.querySelectorAll('.shot-name')];
                    return {count: pics.length, rows: new Set(pics.map(p => Math.round(box(p).top))).size,
                            sizes: pics.map(p => [box(p).width, box(p).height]),
                            inside: pics.every(p => box(p).left >= r.left - 0.5 && box(p).right <= r.right + 0.5) && r.left >= 0 && r.right <= innerWidth,
                            names: words.map(w => w.textContent.trim()),
                            apart: words.map(box).every((w, i, all) => w.height >= 11 && w.height <= 17 && (i === 0 || w.left >= all[i - 1].right + 2)),
                            overflow: getComputedStyle(row).overflowX, scrolls: row.scrollWidth > row.clientWidth + 1,
                            page: document.documentElement.scrollWidth}; }""", first)
                # By keyboard: Tab from the first picture to the last, which is whole in the row.
                other.focus(f"{first} .shots-row button[aria-pressed=true]")
                for _ in range(5):
                    other.keyboard.press("Tab")
                tabbed = other.evaluate("""() => { const cell = document.activeElement, c = cell.getBoundingClientRect(),
                    r = cell.closest('.shots').getBoundingClientRect();
                    return {id: cell.id, whole: c.left >= r.left - 0.5 && c.right <= r.right + 0.5 && c.right <= innerWidth}; }""")
                # By touch: a swipe that starts on the row moves on to the next outfit.
                other.evaluate("() => document.activeElement.blur()")
                touch = context.new_cdp_session(other)
                swipe(touch, other, ".shots-row")
                on_row = other.evaluate(at)
                other.goto(base + yes_page(), wait_until="networkidle")
                other.wait_for_selector(f"{first} .look-pic img")
                swipe(touch, other, ".look-line")
                on_line = other.evaluate(at)
                context.close()
                assert seen["count"] == 6 and seen["rows"] == 1 and seen["inside"] and seen["page"] <= 320, \
                    f"at 320 x 844 one of the six small pictures is cut off at the end of its row, or the page is wider than the screen: {seen}"
                assert all(38 <= w <= 48 and abs(h - w * 4 / 3) < 0.5 for w, h in seen["sizes"]), \
                    f"at 320 x 844 a small picture is under 38px wide, or not 3 wide by 4 high: {seen['sizes']}"
                assert seen["names"] == [names[name] for name in order] and seen["apart"], \
                    f"at 320 x 844 the small pictures' names are missing, on two lines, or run into each other: {seen}"
                assert seen["overflow"] == "visible" and not seen["scrolls"], \
                    f"at 320 x 844 the row of small pictures is a scrolling box: it swallows a swipe ({seen})"
                assert tabbed["id"].endswith("-library") and tabbed["whole"], \
                    f"at 320px the last small picture, reached by Tab, is cut off at the row's edge: {tabbed}"
                assert on_row >= 320 or on_line < 320, \
                    f"at 320 x 844 a swipe that starts on the row of small pictures does not move to the next outfit ({on_row}px; from the line above: {on_line}px)"

            def short_phones() -> None:
                # A phone under 820px of visible height: the row as it was before the pictures had names. 40px, six
                # pictures of 30 by 40px that fit without scrolling (at 320px too), no names shown, but each still
                # says its name to a screen reader. The row is no scrolling box, so a swipe on it moves the outfits.
                for width, height in ((390, 664), (320, 568), (360, 740)):
                    context, other = logged_in_on(browser, viewport={"width": width, "height": height}, is_mobile=True, has_touch=True)
                    other.goto(base + yes_page(), wait_until="networkidle")
                    other.wait_for_selector(f"{first} .look-pic img")
                    seen = other.evaluate("""s => {
                        const shots = document.querySelector(s + ' .shots'), row = shots.querySelector('.shots-row'), box = el => el.getBoundingClientRect();
                        const cells = [...row.querySelectorAll('button[aria-pressed]')], r = box(shots);
                        return {height: r.height, sizes: cells.map(c => [box(c.querySelector('.shot-pic')).width, box(c.querySelector('.shot-pic')).height]),
                                inside: cells.every(c => box(c).left >= r.left - 0.5 && box(c).right <= r.right + 0.5 && box(c).right <= innerWidth),
                                names: [...row.querySelectorAll('.shot-name')].filter(n => box(n).height > 0).length,
                                tall: cells.map(c => box(c).height),
                                labels: cells.map(c => c.getAttribute('aria-label')), overflow: getComputedStyle(row).overflowX,
                                scrolls: row.scrollWidth > row.clientWidth + 1, page: document.documentElement.scrollWidth}; }""", first)
                    where = f"at {width} x {height}"
                    assert seen["height"] == 40 and seen["sizes"] == [[30, 40]] * 6 and seen["inside"] and not seen["names"] \
                        and seen["tall"] == [40] * 6, \
                        f"{where} the small pictures are not one 40px row of six 30 by 40px pictures without names: {seen}"
                    assert seen["labels"] == [names[name] for name in order], f"{where} a small picture does not say its name: {seen['labels']}"
                    assert seen["overflow"] == "visible" and not seen["scrolls"] and seen["page"] <= width, \
                        f"{where} the row scrolls or is a scrolling box, or the page is wider than the screen: {seen}"
                    if width == 390:
                        other.evaluate("s => document.querySelector(s + ' .shots-row').scrollIntoView({block: 'center', behavior: 'instant'})", first)
                        other.wait_for_timeout(300)
                        touch = context.new_cdp_session(other)
                        swipe(touch, other, ".shots-row")
                        on_row = other.evaluate(at)
                        other.evaluate("() => document.getElementById('reel').scrollTo({left: 0, behavior: 'instant'})")
                        other.wait_for_timeout(300)
                        swipe(touch, other, ".look-line")
                        on_line = other.evaluate(at)
                        assert on_row >= width or on_line < width, \
                            f"{where} a swipe that starts on the row of small pictures does not move to the next outfit ({on_row}px; from the line above: {on_line}px)"
                    context.close()

            def laptops() -> None:
                # A computer's window under about 840px high (most laptops): the picture is narrower than six
                # pictures of 48px. None of the six is cut off and the row does not scroll: each is narrower (38px
                # at the least, 3 wide by 4 high), with its name under it, and no name runs into the next.
                for width, height in ((1366, 650), (1280, 720), (1440, 780)):
                    context, other = logged_in_on(browser, viewport={"width": width, "height": height})
                    other.goto(base + yes_page(), wait_until="networkidle")
                    other.wait_for_selector(f"{first} .look-pic img")
                    seen = other.evaluate("""s => {
                        const shots = document.querySelector(s + ' .shots'), row = shots.querySelector('.shots-row'), box = el => el.getBoundingClientRect();
                        const cells = [...row.querySelectorAll('button[aria-pressed]')], r = box(shots);
                        const words = cells.map(c => box(c.querySelector('.shot-name')));
                        return {row: [r.left, r.right], picture: box(document.querySelector(s + ' .look-pic')).width,
                                sizes: cells.map(c => [box(c.querySelector('.shot-pic')).width, box(c.querySelector('.shot-pic')).height]),
                                inside: cells.every(c => box(c.querySelector('.shot-pic')).left >= r.left - 0.5 && box(c.querySelector('.shot-pic')).right <= r.right + 0.5),
                                rows: new Set(cells.map(c => Math.round(box(c).top))).size,
                                names: cells.map(c => c.querySelector('.shot-name').textContent.trim()),
                                apart: words.every((w, i) => w.width > 0 && w.height <= 17 && (i === 0 || w.left >= words[i - 1].right + 2)),
                                overflow: getComputedStyle(row).overflowX, scrolls: row.scrollWidth > row.clientWidth + 1,
                                page: document.documentElement.scrollWidth}; }""", first)
                    context.close()
                    where = f"at {width} x {height}"
                    assert len(seen["sizes"]) == 6 and seen["rows"] == 1 and seen["inside"], \
                        f"{where} one of the six small pictures is cut off at the end of its row: {seen}"
                    assert seen["overflow"] == "visible" and not seen["scrolls"] and seen["page"] <= width, \
                        f"{where} the row of small pictures scrolls sideways, which a mouse cannot do: {seen}"
                    assert all(38 <= w <= 48 and abs(h - w * 4 / 3) < 0.5 for w, h in seen["sizes"]), \
                        f"{where} a small picture is under 38px wide, or not 3 wide by 4 high: {seen['sizes']}"
                    assert seen["names"] == [names[name] for name in order] and seen["apart"], \
                        f"{where} the small pictures' names are missing, on two lines, or run into each other: {seen}"

            def a_swipe_on_the_row_moves_on() -> None:
                # On a 390px phone the six fit, so the row scrolls nothing: a sideways swipe that starts on it moves on
                # to the next outfit, like one that starts anywhere else on the outfit. (Some headless browsers ignore
                # a synthesized swipe: then one on the line above is ignored too, and only the row's style is checked.)
                context, other = logged_in_on(browser, viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
                touch = context.new_cdp_session(other)

                def swiped(selector: str) -> float:
                    other.goto(base + yes_page(), wait_until="networkidle")
                    other.wait_for_selector(f"{first} .look-pic img")
                    motion_ended(other)
                    swipe(touch, other, selector)
                    return other.evaluate(at)

                on_row, on_line = swiped(".shots-row"), swiped(".look-line")
                style = other.evaluate("s => getComputedStyle(document.querySelector(s + ' .shots-row')).overflowX", first)
                # "OK" beside why "More photos" stopped (shown only once a day's pictures ran out): 24px high at least.
                ok = other.evaluate("""s => { const row = document.querySelector(s + ' .shots');
                    row.insertAdjacentHTML('beforeend', '<form class="shots-said"><p class="look-msg">Today&#39;s pictures are used up. <button type="button" class="link">OK</button></p></form>');
                    const link = row.querySelector('.shots-said .link'), high = link.getBoundingClientRect().height,
                        target = parseFloat(getComputedStyle(link, '::after').height);
                    row.querySelector('.shots-said').remove();
                    return {high, target}; }""", first)
                context.close()
                assert style == "visible", f"at 390px, where the six small pictures fit, their row is a scrolling box ({style}): it swallows a swipe"
                assert on_row >= 390 or on_line < 390, \
                    f"a swipe that starts on the row of small pictures does not move to the next outfit ({on_row}px; from the line above: {on_line}px)"
                assert ok["high"] >= 24 and ok["target"] >= 44, f"'OK' under the row is {ok['high']}px high, a {ok['target']}px target"

            def layout(state: str) -> None:
                for width, height, touch in ((390, 844, True), (1280, 860, False)):
                    for scheme in ("light", "dark"):
                        context, other = logged_in_on(browser, viewport={"width": width, "height": height}, is_mobile=touch,
                                                      has_touch=touch, color_scheme=scheme)
                        other.goto(base + yes_page(), wait_until="networkidle")
                        other.wait_for_selector(f"{first} .look-pic img")
                        other.evaluate("() => document.querySelectorAll('main .demo').forEach(notice => notice.remove())")
                        seen = other.evaluate("""s => {
                            const slide = document.querySelector(s), box = el => el.getBoundingClientRect();
                            const row = slide.querySelector('.shots'), r = box(row), line = box(slide.querySelector('.look-line'));
                            const rgb = c => c.match(/[\\d.]+/g).slice(0, 3).map(Number);
                            const lum = c => { const [r, g, b] = rgb(c).map(v => { v /= 255;
                                return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; }); return 0.2126 * r + 0.7152 * g + 0.0722 * b; };
                            const ratio = (a, b) => { const [x, y] = [lum(a), lum(b)].sort((m, n) => n - m); return (x + 0.05) / (y + 0.05); };
                            const inside = el => { const b = box(el); return b.width > 0 && b.left >= r.left - 0.5 && b.right <= r.right + 0.5
                                                   && b.top >= r.top - 0.5 && b.bottom <= r.bottom + 0.5; };
                            const cells = [...row.querySelectorAll('.shots-row button[aria-pressed]')].map(b => {
                                const pic = box(b.querySelector('.shot-pic')), name = b.querySelector('.shot-name'), n = box(name);
                                return {name: b.id.split('-').pop(), width: box(b).width, height: box(b).height, inside: inside(b),
                                        picture: [pic.width, pic.height], words: name.textContent.trim(), top: Math.round(pic.top),
                                        named: n.top >= pic.bottom - 0.5 && n.left >= pic.left - 0.5 && n.right <= pic.right + 0.5
                                               && parseFloat(getComputedStyle(name).fontSize) >= 11,
                                        loaded: !b.querySelector('img') || (b.querySelector('img').complete && b.querySelector('img').naturalWidth > 0)}; });
                            const shown = row.querySelector('[aria-pressed="true"] .shot-pic');
                            const frame = shown ? getComputedStyle(shown, '::after') : null;
                            const more = row.querySelector('.btn'), note = row.querySelector('.shots-note');
                            const meta = [...slide.querySelectorAll('.about-head h2, .count, .board-cost')].map(el => box(el).bottom);
                            return {cells, height: r.height, left: r.left, right: r.right, under: Math.abs(r.top - line.bottom) < 1,
                                    same_width: r.width >= line.width - 1 && Math.abs((r.left + r.right) - (line.left + line.right)) < 2,
                                    screen: innerWidth,
                                    frame: frame && parseFloat(frame.borderTopWidth) >= 2
                                           ? Math.round(ratio(frame.borderTopColor, getComputedStyle(document.body).backgroundColor) * 100) / 100 : 0,
                                    more: more && {words: more.textContent.trim(), height: box(more).height, inside: inside(more)},
                                    note: note && {words: note.textContent.trim(), inside: inside(note),
                                                   contrast: Math.round(ratio(getComputedStyle(note).color, getComputedStyle(document.body).backgroundColor) * 100) / 100},
                                    line_end: Math.max(...meta), tabs: box(document.querySelector('nav.tabs')).top,
                                    page: document.documentElement.scrollWidth};
                        }""", first)
                        where = f"{width} x {height}, {scheme}, {state}"
                        assert seen["under"] and seen["same_width"] and seen["height"] == 84 and 0 <= seen["left"] \
                            and seen["right"] <= seen["screen"], \
                            f"{where}: the small pictures are not one 84px row right under the line under the picture, whole on the screen: {seen}"
                        assert len({cell["top"] for cell in seen["cells"]}) == 1, f"{where}: the small pictures are not one row: {seen['cells']}"
                        assert seen["page"] <= width, f"{where}: the page is {seen['page']}px wide"
                        assert [cell["name"] for cell in seen["cells"]] == (order if state == "six" else ["front"]), f"{where}: {seen['cells']}"
                        for cell in seen["cells"]:
                            assert cell["picture"] == [48, 64] and cell["inside"] and cell["loaded"], \
                                f"{where}: the small picture {cell['name']!r} is not 48 by 64px, is outside its row, or did not load: {cell}"
                            assert cell["words"] == names[cell["name"]] and cell["named"], \
                                f"{where}: the small picture {cell['name']!r} does not have its name {names[cell['name']]!r} under it: {cell}"
                        assert seen["frame"] >= 3, f"{where}: the picture shown is not framed so that it can be told ({seen['frame']}:1)"
                        if state == "six":
                            assert not seen["more"], f"{where}: 'More photos' is still offered: {seen}"
                        else:
                            assert seen["more"] and seen["more"]["words"] == "More photos" and seen["more"]["inside"] \
                                and seen["more"]["height"] >= 40, f"{where}: 'More photos' is not a finger-sized button in the row: {seen}"
                            assert seen["note"] and seen["note"]["inside"] and seen["note"]["contrast"] >= 4.5, \
                                f"{where}: what 'More photos' costs is cut off or hard to read: {seen}"
                        if touch:
                            assert seen["line_end"] <= seen["tabs"], \
                                f"{where}: with the small pictures, the outfit's title and price end under the tab bar: {seen}"
                        context.close()

            page.goto(base + yes_page(), wait_until="networkidle")
            page.wait_for_selector(f"{first} .look-pic img")
            front = page.get_attribute(f"{first} .look-pic img", "src")
            group = f"{row} form[role=group]"
            assert page.get_attribute(group, "aria-label") == "Photos of this outfit", \
                "the small pictures are not one group named 'Photos of this outfit' for screen readers"
            at_first = page.evaluate(cells, first)
            assert [(cell["name"], cell["pressed"], cell["picture"]) for cell in at_first] == [("front", "true", True)], \
                f"before 'More photos', the row is not the front picture alone, shown: {at_first}"
            assert not any(sent["references"] for sent in asked), "a picture was made from a front picture without 'More photos'"
            assert all("Seamless pure white studio background" in sent["prompt"] for sent in asked), \
                "a front picture was not asked for on a white studio background"
            # What it draws; the day's allowance only once it is nearly used up (review N14): here 30 a day, unsaid.
            cost = "5 pictures"
            assert rules['pictures']['per_customer_per_day'] > 5 + 5, "the walk-through's allowance is nearly used up"
            said = page.inner_text(f"{row} .shots-note")
            assert said == cost, f"beside 'More photos' the cost reads {said!r}, not {cost!r}"
            described = page.get_attribute(f"{row} .btn", "aria-describedby")
            assert described and page.inner_text(f"#{described}") == cost, "a screen reader does not hear the cost with 'More photos'"
            layout("front only")

            before, done_before = len(asked), len(finished)
            page.evaluate("s => { document.querySelector(s + ' .look-pic').dataset.kept = 'yes'; }", first)
            page.focus(f"{row} .btn")                                   # by keyboard
            page.keyboard.press("Enter")
            page.wait_for_function(f"s => ({cells})(s).length === 6", arg=first)
            started = page.evaluate(cells, first)
            assert [cell["name"] for cell in started] == order and all(cell["drawing"] for cell in started[1:]), \
                f"after 'More photos' the row does not show the five pictures being drawn: {started}"
            assert all(cell["label"].endswith("being drawn") for cell in started[1:]), f"a screen reader is not told they are being drawn: {started}"
            focused = page.evaluate("() => document.activeElement.id")
            assert focused.startswith("shot-") and focused.endswith("-front"), \
                f"'More photos' is gone, and keyboard focus went to {focused!r}, not to the picture shown"
            arriving: set[int] = set()
            for _ in range(150):                                        # each shows as it arrives
                there = sum(1 for cell in page.evaluate(cells, first) if cell["picture"])
                arriving.add(there)
                if there == 6:
                    break
                page.wait_for_timeout(200)
            assert 6 in arriving, f"the five pictures never all arrived: {sorted(arriving)}"
            assert arriving & {2, 3, 4, 5}, f"the pictures did not show one by one as they arrived: {sorted(arriving)}"
            assert not page.locator(f"{row} .btn").count(), "'More photos' is still offered once all six are there"
            assert page.evaluate("s => document.querySelector(s + ' .look-pic').dataset.kept", first) == "yes" \
                and page.get_attribute(f"{first} .look-pic img", "src") == front, \
                "the large picture was sent again while the small ones arrived"
            sent = asked[before:]
            assert len(sent) == 5 and len(finished) == done_before + 5, f"'More photos' asked for {len(sent)} pictures"
            anchor = {bytes(reference) for one in sent for reference in one["references"]}
            assert all(len(one["references"]) == 1 for one in sent) and len(anchor) == 1, \
                "each of the five was not made from the one front picture"
            assert anchor == {picture()}, "what went to the image service is not the outfit's front picture"
            # (Two are drawn at a time and the rest wait their turn, so they reach the service in no fixed order.)
            assert all("Make a new photograph of the same man in the same outfit" in one["prompt"] for one in sent), \
                "one of the five was not asked for as a new photograph of the same man"
            for name in order[1:]:
                assert sum("Change only this: " + changes[name] in one["prompt"] for one in sent) == 1, \
                    f"the {name} picture was not asked for in its own words, once"
            for _ in range(30):                                         # the row has stopped asking
                if not page.locator(f"{row}[hx-get]").count():
                    break
                page.wait_for_timeout(100)
            assert not page.locator(f"{row}[hx-get]").count(), "all six are there, and the row still asks for news"
            # "Draw again" on the front picture, right now: no reload, no small picture tapped since "More photos"
            # (which replaced only the row). It asks first, saying that the other five will be removed; nothing is
            # drawn or removed until he answers; keyboard focus is on the answer. "Keep them": all as it was.
            before = len(asked)
            page.click(f"{first} .look-line button:has-text('Draw again')")
            page.wait_for_selector(f"{first} .look-ask")
            question = page.inner_text(f"{first} .look-ask p")
            assert question == ("Draw the front picture again? The other 5 photos of this outfit are made from it, so they "
                                "will be removed. “More photos” draws them again."), \
                f"'Draw again' on the front picture, right after 'More photos', asks {question!r}"
            answers = page.evaluate("s => [...document.querySelectorAll(s + ' .look-ask button')].map(b => [b.textContent.trim(), b.getBoundingClientRect().height])", first)
            assert [words for words, _ in answers] == ["Draw again", "Keep them"] and all(height >= 40 for _, height in answers), \
                f"the answers to the question are {answers}"
            assert page.evaluate("() => document.activeElement.textContent.trim()") == "Draw again" \
                and page.evaluate("() => !!document.activeElement.closest('.look-ask')"), "keyboard focus is not on the question's answer"
            assert len(asked) == before and sum(1 for cell in page.evaluate(cells, first) if cell["picture"]) == 6, \
                "'Draw again' on the front picture drew or removed something before it was answered"
            page.click(f"{first} .look-ask button:has-text('Keep them')")
            page.wait_for_selector(f"{first} .look-ask", state="detached")
            assert len(asked) == before and sum(1 for cell in page.evaluate(cells, first) if cell["picture"]) == 6 \
                and page.get_attribute(f"{first} .look-pic img", "src") == front, "'Keep them' did not leave everything as it was"
            # Without JavaScript the same tap leads to the outfits page asking it, under that outfit's picture, with
            # nothing drawn or removed; "Keep them" leads back to the outfit as it was.
            context, plain = logged_in_on(browser, viewport={"width": 390, "height": 844}, java_script_enabled=False)
            plain.goto(base + yes_page(), wait_until="networkidle")
            plain.click(f"{first} .look-line button:has-text('Draw again')")
            plain.wait_for_load_state("networkidle")
            asks = plain.locator(".look-ask p").all_inner_texts()
            assert "ask=again" in plain.url and asks == [question] and plain.locator(f"{first} .look-ask").count() == 1, \
                f"without JavaScript 'Draw again' on the front picture leads to {plain.url}, which asks {asks}"
            assert len(asked) == before and plain.locator(f"{first} .shots-row img").count() == 6, \
                "without JavaScript 'Draw again' drew or removed something before it was answered"
            plain.click(f"{first} .look-ask button:has-text('Keep them')")
            plain.wait_for_load_state("networkidle")
            assert "ask" not in plain.url and not plain.locator(".look-ask").count() \
                and plain.locator(f"{first} .shots-row img").count() == 6 and len(asked) == before, \
                f"without JavaScript 'Keep them' did not leave everything as it was ({plain.url})"
            context.close()
            layout("six")
            narrow_phone()
            short_phones()
            laptops()
            a_swipe_on_the_row_moves_on()

            dots = "s => getComputedStyle(document.querySelector(s + ' .spots')).display"
            assert page.evaluate(dots, first) != "none", "the front picture has no dots"
            before = len(asked)
            page.focus(f"{row} button[id$='-street']")                  # by keyboard
            page.keyboard.press("Enter")
            page.wait_for_function("([s, old]) => { const i = document.querySelector(s + ' .look-pic.more img');"
                                   " return i && i.getAttribute('src') !== old && i.complete; }", arg=[first, front])
            shows(f"{first} .look-pic img", "the Street picture")
            labelled(page, "1280 x 860, Street")
            alt = page.get_attribute(f"{first} .look-pic img", "alt")
            assert alt.endswith("photo: Street"), f"the Street picture's words for a screen reader: {alt!r}"
            assert [cell["name"] for cell in page.evaluate(cells, first) if cell["pressed"] == "true"] == ["street"], \
                "Street is not shown as the picture pressed"
            focused = page.evaluate("() => document.activeElement.id")
            assert focused.startswith("shot-") and focused.endswith("-street"), f"keyboard focus left Street for {focused!r}"
            assert page.evaluate(dots, first) == "none", "the dots, placed for the front picture's pose, show on the Street picture"
            page.click(f"{row} button[id$='-front']")
            page.wait_for_function("([s, src]) => { const i = document.querySelector(s + ' .look-pic img');"
                                   " return i && i.getAttribute('src') === src; }", arg=[first, front])
            assert page.evaluate(dots, first) != "none", "back on the front picture the dots are gone"
            assert page.locator(f"{first} .spot").count() == page.locator(f"{first} .piece-row").count(), "a dot per piece"
            assert len(asked) == before and not page.locator(f"{first} .look-bar.wait").count(), \
                "looking at pictures that are there drew one again"

        def a_tap_on_a_small_picture_is_kept():
            # A small picture tapped is never undone by another answer coming back late. The row's own question (asked
            # every 3 s while pictures are drawn) is held here until Street has been tapped and shown, then let go: the
            # box stays on Street. The same for "Draw again" under the street picture, answered after the front picture
            # was tapped: the front picture stays. Without JavaScript, "See it worn", "More photos" and a small picture
            # each come back to the outfits with that outfit in view, and the picture tapped shown. A customer of his
            # own, so that these pictures leave the first customer's day as it was.
            who = "photos-" + EMAIL
            pressed = ("s => { const b = document.querySelector(s + ' .shots-row [aria-pressed=true]');"
                       " return b && b.id.split('-').pop(); }")
            context = browser.new_context(viewport={"width": 1280, "height": 860})
            try:
                tapper = context.new_page()
                tapper.on("response", lambda r: failures.append(f"{r.status} {r.request.method} {r.url.replace(base, '')[:100]}")
                          if r.status >= 400 and r.url.startswith(base) and "does-not-exist" not in r.url else None)
                tapper.on("pageerror", lambda e: failures.append(f"script error: {e}"))
                tapper.goto(base + "/signup", wait_until="networkidle")
                tapper.fill("input[name=email]", who)
                tapper.fill("input[name=password]", PASSWORD)
                tapper.click("button:has-text('Create account')")
                a_customer_from_before(tapper)
                for seed in range(141, 200):            # a shuffle whose first outfit has only its front picture, or none
                    tapper.goto(base + f"/outfits?seed={seed}", wait_until="domcontentloaded")
                    if tapper.locator(f"{first} .shots-row button[aria-pressed]").count() <= 1:
                        break
                else:
                    raise AssertionError("the first outfit of every shuffle tried already has all its pictures")
                tapper.goto(base + f"/outfits?at={say_yes(tapper)}&seed={seed}", wait_until="domcontentloaded")    # his yes
                tapper.wait_for_selector(f"{first} .shots .btn", timeout=30000)      # the front picture, drawn by itself
                held: list = []
                tapper.route("**/outfits/photos*", lambda route: held.append(route))  # the row's question waits
                done_before = len(finished)
                tapper.click(f"{first} .shots .btn")                                  # More photos
                tapper.wait_for_selector(f"{first} .shots-row .spin")
                for _ in range(100):                                                  # … and its question is asked
                    if held:
                        break
                    tapper.wait_for_timeout(100)
                assert held, "the row of small pictures never asked how the drawing is going"
                for _ in range(150):                                                  # all five drawn meanwhile
                    if len(finished) >= done_before + 5:
                        break
                    tapper.wait_for_timeout(100)
                tapper.click(f"{first} .shots-row button[id$='-street']")             # still a spinner in the row
                tapper.wait_for_function("s => { const i = document.querySelector(s + ' .look-pic.more img');"
                                         " return i && i.alt.endsWith('photo: Street') && i.complete; }", arg=first)
                for route in held:                                                    # the row's answer, late
                    try:
                        route.continue_()
                    except Exception:  # noqa: BLE001 - the browser gave up on it already: that is the point
                        pass
                tapper.wait_for_timeout(1500)
                late = tapper.evaluate(pressed, first)
                assert late == "street", f"the row's late answer put {late!r} back over the Street tapped"
                assert tapper.locator(f"{first} .look-pic.more").count() == 1 \
                    and tapper.locator(f"{first} .shots-row img").count() == 6, "the Street picture, or the row under it, went"
                tapper.unroute("**/outfits/photos*")

                def until(sent: list, what: str) -> None:
                    for _ in range(60):
                        if sent:
                            return
                        tapper.wait_for_timeout(100)
                    raise AssertionError(what)

                # "Draw again" under the street picture, answered after the front picture was tapped: the front stays.
                again_asked: list = []
                tapper.route("**/outfits/look", lambda route: again_asked.append(route)
                             if "again=1" in (route.request.post_data or "") else route.continue_())
                tapper.click(f"{first} .look-line button:has-text('Draw again')")
                until(again_asked, "Draw again asked for nothing")
                tapper.click(f"{first} .shots-row button[id$='-front']")
                tapper.wait_for_function(f"s => ({pressed})(s) === 'front'", arg=first)
                for route in again_asked:
                    try:
                        route.continue_()
                    except Exception:  # noqa: BLE001 - the browser gave up on it already: that is the point
                        pass
                tapper.wait_for_timeout(1500)
                late = tapper.evaluate(pressed, first)
                assert late == "front", f"the late answer to Draw again on the street put {late!r} back over the front picture tapped"
                tapper.unroute("**/outfits/look")
                tapper.wait_for_function("s => { const i = document.querySelector(s + ' .look-pic:not(.more) img');"
                                         " return i && !i.alt.includes('photo:') && i.complete; }", arg=first)
            finally:
                context.close()

            context = browser.new_context(viewport={"width": 390, "height": 844}, java_script_enabled=False)
            try:
                other = context.new_page()
                other.goto(base + "/login", wait_until="networkidle")
                other.fill("input[name=email]", who)
                other.fill("input[name=password]", PASSWORD)
                other.click("button:has-text('Log in')")
                other.wait_for_load_state("networkidle")
                other.goto(base + "/outfits?n=12", wait_until="networkidle")
                keys = other.evaluate("() => [...document.querySelectorAll('[data-slide]')].filter(s => !s.querySelector('.look-pic')).map(s => s.id.slice(7))")
                assert keys, "every outfit already has its picture"
                key = keys[0]

                def reload_until(what: str, there: str) -> None:
                    for _ in range(40):                 # drawn meanwhile: the same address shows it
                        if other.evaluate(there, f"#look-{key}"):
                            return
                        other.wait_for_timeout(500)
                        other.reload(wait_until="networkidle")
                    raise AssertionError(f"without JavaScript, {what}")

                other.goto(base + f"/outfits?at={say_yes(other, f'#outfit-{key}')}", wait_until="networkidle")   # his yes
                other.click(f"#look-{key} button:has-text('See it worn')")
                other.wait_for_load_state("networkidle")
                assert other.url.endswith(f"#outfit-{key}"), f"without JavaScript, 'See it worn' leads back to {other.url}"
                reload_until("the front picture never showed", "s => !!document.querySelector(s + ' .shots .btn')")
                before = len(asked)
                other.click(f"#look-{key} .shots .btn")                              # More photos
                other.wait_for_load_state("networkidle")
                assert other.url.endswith(f"#outfit-{key}") and "shot=" not in other.url, \
                    f"without JavaScript, 'More photos' leads back to {other.url}"
                reload_until("the five more photos never showed", "s => document.querySelectorAll(s + ' .shots-row img').length === 6")
                assert len(asked) == before + 5, f"without JavaScript, 'More photos' asked for {len(asked) - before} pictures"
                other.click(f"#look-{key} .shots-row button[id$='-library']")
                other.wait_for_load_state("networkidle")
                address = other.url.replace(base, "")
                assert "shot=library" in address and f"shot_of={key}" in address and address.endswith(f"#outfit-{key}"), \
                    f"without JavaScript, Library leads back to {address}"
                shown = other.evaluate(pressed, f"#look-{key}")
                alt = other.get_attribute(f"#look-{key} .look-pic.more img", "alt")
                assert shown == "library" and alt.endswith("photo: Library"), \
                    f"without JavaScript, the page came back showing {shown!r} ({alt!r}), not the library picture"
            finally:
                context.close()

        def see_it_move():
            # Under a finished picture, "See it move": a button on the picture, at its top right, clear of every dot.
            # Tapped, it says under the picture what a video is and how many are left today ("1 video left today"), with
            # the button that makes one beside "Not now", in place of the picture's line and the small pictures: the picture
            # stays whole. The button has keyboard focus; nothing is made until it is pressed. While the video is made the
            # picture's box says so (and "Making the video" is said once); then the video lies over the picture,
            # labelled 'AI video', plays once and rests on its last frame, with keyboard focus on it and "Video ready"
            # said once, and the picture's caption 'Look and fit will differ' still under it, above "Drag to turn",
            # "Play again" and "Show picture". Dragging across it, or the arrow keys, turn the model (a slider, its
            # value in degrees) without moving on to another outfit; "Play again" plays it from the start; "Show
            # picture" brings back the picture and its dots. Reloaded, playing it again is free. The customer's one
            # video a day is then used: another outfit says "No videos left today: more tomorrow", which a screen reader
            # hears with its only button, Close. Nothing below the picture's line and small pictures moves at any point. On a
            # short phone, where the line and the small pictures are below the tab bar, the page goes up as the offer opens,
            # so that the whole offer and the button with keyboard focus show above the tab bar: for a first offer, for
            # "No videos left today", and for a video that could not be made (said when the customer is still looking
            # at its picture; the page stays where it is when he has read on past it). Places are measured on the
            # page, not on the screen, so that a page that went up is not taken for one whose parts moved.
            page.goto(base + yes_page(), wait_until="networkidle")
            page.wait_for_selector(f"{first} .look-pic img")
            on_page = """const box = el => { if (!el) return null; const r = el.getBoundingClientRect();
                return {left: r.left, right: r.right, width: r.width, height: r.height, top: r.top + scrollY, bottom: r.bottom + scrollY}; };"""
            geometry = """s => { const slide = document.querySelector(s); """ + on_page + """
                const pic = box(slide.querySelector('.look-pic')), pill = box(slide.querySelector('.vid-pill'));
                const dots = [...slide.querySelectorAll('.spot')].map(box).filter(d => d.width);
                const clear = pill && dots.every(d => d.right + 10 <= pill.left || d.left - 10 >= pill.right
                                                     || d.bottom + 10 <= pill.top || d.top - 10 >= pill.bottom);
                return {pill: pill && {left: pill.left, right: pill.right, top: pill.top, bottom: pill.bottom},
                        on_picture: !!pill && pill.left >= pic.left && pill.right <= pic.right && pill.top >= pic.top
                                    && pill.bottom <= pic.top + pic.height / 6 && pill.right > pic.left + pic.width * .8,
                        clear, words: slide.querySelector('.vid-pill') && slide.querySelector('.vid-pill').textContent.trim(),
                        scenes: box(slide.querySelector('.shots')).top, scenes_end: box(slide.querySelector('.shots')).bottom,
                        title: box(slide.querySelector('.about-head')).top}; }"""
            offer_place = """s => { const slide = document.querySelector(s); """ + on_page + """
                const tabs = document.querySelector('nav.tabs');
                const bar = tabs && getComputedStyle(tabs).position === 'fixed' ? tabs.getBoundingClientRect().top : innerHeight;
                const shows = el => { const r = el.getBoundingClientRect(); return r.height > 0 && r.top >= -.5 && r.bottom <= bar + .5; };
                const form = slide.querySelector('.vid-bar.ask'), focused = document.activeElement;
                const o = box(form), p = box(slide.querySelector('.look-pic'));
                const buttons = [...slide.querySelectorAll('.vid-bar.ask button')].map(box);
                const words = slide.querySelector('.vid-bar.ask > span');
                return {covers: Math.max(0, Math.min(o.bottom, p.bottom) - Math.max(o.top, p.top)) / p.height,
                        // right under the picture, and on a phone under the row of words that lies right under it
                        under: Math.abs(o.top - p.bottom - parseFloat(getComputedStyle(slide.querySelector('.collage')).marginBottom)) < 1, height: o.height, end: o.bottom, page: document.documentElement.scrollWidth,
                        side_by_side: buttons.length === 2 && Math.abs(buttons[0].top - buttons[1].top) < 1,
                        whole: words.scrollWidth <= words.clientWidth + 1 && o.left >= 0 && o.right <= innerWidth,
                        instead: [...slide.querySelectorAll('.look > .look-line, .look > .shots')].every(el => !el.getClientRects().length),
                        title: box(slide.querySelector('.about-head')).top,
                        shows: shows(form) && [...form.querySelectorAll('button')].every(shows),
                        focus: form.contains(focused) ? focused.textContent.trim() : null, focus_shows: shows(focused),
                        bottom: Math.round(form.getBoundingClientRect().bottom), bar: Math.round(bar), scrolled: Math.round(scrollY)}; }"""
            # Where the page comes to rest once it has stopped moving (it glides where more motion is allowed).
            at_rest = """() => new Promise(done => { let last = NaN, same = 0;
                const look = () => { if (scrollY === last) { if (++same >= 10) return done(scrollY); } else { last = scrollY; same = 0; }
                                     requestAnimationFrame(look); };
                look(); })"""
            before = page.evaluate(geometry, first)
            assert before["words"] == "See it move" and before["on_picture"] and before["clear"], \
                f"'See it move' is not at the top right of the picture, clear of the dots: {before}"
            # A key pressed before HTMX has hooked up what it just put in would send the form without it (see SETTLED in
            # the piece page's step): the walk-through waits for that, as a person always does.
            settled = "() => !document.querySelector('.htmx-request, .htmx-swapping, .htmx-settling')"
            # On phones from 320 to 390px, light and dark, the offer covers none of the picture: its words on two lines at
            # most, whole, and its two buttons side by side, in the room of the picture's line and the small pictures. All of it
            # shows above the tab bar once the page has come to rest (where less motion is asked for too: 375 x 667), the
            # button with keyboard focus too.
            for width, height, scheme in ((320, 568, "light"), (360, 740, "light"), (375, 667, "dark"), (390, 664, "light"),
                                          (390, 844, "dark")):
                context, other = logged_in_on(browser, viewport={"width": width, "height": height}, is_mobile=True,
                                              has_touch=True, color_scheme=scheme,
                                              reduced_motion="reduce" if height == 667 else "no-preference")
                other.goto(base + yes_page(), wait_until="networkidle")
                other.wait_for_selector(f"{first} .look-pic img")
                other.evaluate("() => document.querySelectorAll('main .demo').forEach(notice => notice.remove())")
                shut = other.evaluate(geometry, first)
                other.click(f"{first} .vid-pill")
                other.wait_for_selector(f"{first} .vid-bar.ask")
                other.wait_for_function(settled)
                other.evaluate(at_rest)
                placed = other.evaluate(offer_place, first)
                where = f"{width} x {height}, {scheme}"
                assert "1 video left today" in other.inner_text(f"{first} .vid-bar.ask"), f"{where}: the offer is not the first one"
                assert placed["covers"] == 0 and placed["under"] and placed["side_by_side"] and placed["instead"] \
                    and placed["whole"] and placed["page"] <= width, f"{where}: the offer does not fit under the picture: {placed}"
                assert placed["end"] <= shut["scenes_end"] + 0.5 and placed["title"] == shut["title"], \
                    f"{where}: the offer took more room than the line and the small pictures: {placed}, {shut}"
                assert placed["shows"], f"{where}: after the tap the offer, or one of its buttons, is under the tab bar: {placed}"
                assert placed["focus"] == "Make the video" and placed["focus_shows"], \
                    f"{where}: keyboard focus is not on 'Make the video' where it can be seen: {placed}"
                context.close()
            # A video that could not be made, on a 320 x 568 phone (the AI busy, before Google took anything: the day's
            # video is given back). While it is made the band is on the picture; when the box learns that it failed, the
            # offer says why with "Try again", and keyboard focus is on "Try again". The customer had gone back up to the
            # top of the page meanwhile, still looking at the picture: the page goes up again, until the offer and "Try
            # again" show above the tab bar. Tried again, and this time he has read on past the picture when it fails:
            # the page stays where he is. The failure is then forgotten (as after a restart), for the steps after.
            context, other = logged_in_on(browser, viewport={"width": 320, "height": 568}, is_mobile=True, has_touch=True)
            try:
                other.goto(base + yes_page(), wait_until="networkidle")
                other.wait_for_selector(f"{first} .look-pic img")
                other.evaluate("() => document.querySelectorAll('main .demo').forEach(notice => notice.remove())")
                other.click(f"{first} .vid-pill")
                other.wait_for_selector(f"{first} .vid-bar.ask")
                other.wait_for_function(settled)
                other.evaluate(at_rest)
                for read_on in (False, True):
                    refuse.append(imagegen.DrawError("busy", "the stand-in was told to be busy", free=True))
                    other.locator(f"{first} .vid-bar.ask button.btn").press("Enter")       # Make the video, then Try again
                    other.wait_for_selector(f"{first} .vid-bar.wait")
                    if read_on:
                        other.evaluate("s => window.scrollTo(0, document.querySelector(s + ' .about').getBoundingClientRect().top"
                                       " + scrollY)", first)
                    else:
                        other.evaluate("() => window.scrollTo(0, 0)")
                    # What he reads where he is: the outfit's line under the picture, on the screen. (The browser keeps
                    # it still when the box above it grows by a line: the page's scroll may change, the screen does not.)
                    reading = "s => Math.round(document.querySelector(s + ' .about').getBoundingClientRect().top)"
                    other.evaluate(at_rest)
                    before_answer = other.evaluate(reading, first)
                    other.wait_for_selector(f"{first} .vid-bar.ask .look-msg", timeout=20000)
                    other.wait_for_function(settled)
                    other.evaluate(at_rest)
                    after_answer = other.evaluate(reading, first)
                    placed = other.evaluate(offer_place, first)
                    told = " ".join(other.inner_text(f"{first} .vid-bar.ask").split())
                    assert told.startswith("The AI is busy or did not answer in time. Try again in a minute.") \
                        and "1 video left today" in told, f"a video that could not be made is said as {told!r}"
                    assert placed["focus"] == "Try again", f"keyboard focus is not on 'Try again': {placed}"
                    if read_on:
                        assert abs(after_answer - before_answer) <= 1, \
                            f"read on past the picture, what he reads moved when the video failed: {before_answer} -> {after_answer}"
                    else:
                        assert placed["shows"] and placed["focus_shows"], \
                            f"a video that could not be made is said under the tab bar, out of sight: {placed}"
                assert refuse == [] and made == [], "the stand-in was not asked, or a video was made"
            finally:
                context.close()
                videos.STARTED = time.time()                    # its failure is forgotten, as after a restart
            assert made == [], "opening the offer made a video"
            page.click(f"{first} .vid-pill")
            page.wait_for_selector(f"{first} .vid-bar.ask")
            page.wait_for_function(settled)
            offer = page.inner_text(f"{first} .vid-bar.ask")
            assert "1 video left today" in offer and "Make the video" in offer, f"the offer says {offer!r}"
            placed = page.evaluate(offer_place, first)
            assert placed["covers"] == 0 and placed["under"] and placed["side_by_side"] and placed["instead"], \
                f"the offer is not under the picture, its two buttons side by side, in place of the line and the small pictures: {placed}"
            assert placed["end"] <= before["scenes_end"] + 0.5 and placed["title"] == before["title"], \
                f"the offer took more room than the line and the small pictures, and what is under them moved: {placed}, {before}"
            assert page.evaluate("() => document.activeElement.textContent.trim()") == "Make the video", \
                "keyboard focus is not on 'Make the video'"
            assert made == [], "a video was made before 'Make the video' was pressed"
            page.keyboard.press("Enter")
            page.wait_for_selector(f"{first} .vid-bar.wait")
            status = page.evaluate("""s => { const b = document.querySelector(s + ' .vid-bar.wait').getBoundingClientRect(),
                p = document.querySelector(s + ' .look-pic').getBoundingClientRect();
                return {words: document.querySelector(s + ' .vid-bar.wait').textContent.replace(/\\s+/g, ' ').trim(),
                        inside: b.top >= p.top - .5 && b.bottom <= p.bottom + .5 && b.left >= p.left - .5 && b.right <= p.right + .5}; }""", first)
            assert status["words"].startswith("Making the video") and status["inside"], \
                f"while the video is made the picture's box does not say so: {status}"
            page.wait_for_function("() => document.getElementById('announce').textContent === 'Making the video'")
            page.wait_for_selector(f"{first} .vid.on")
            page.wait_for_function("s => { const v = document.querySelector(s + ' .vid-clip'); return v.currentTime > 0.3; }",
                                   arg=first)
            seen = page.evaluate("""s => { const slide = document.querySelector(s); """ + on_page + """
                const v = slide.querySelector('.vid-clip'), chip = slide.querySelector('.vid-box .ai-chip'), p = box(slide.querySelector('.look-pic'));
                const b = box(slide.querySelector('.vid-box')), line = box(slide.querySelector('.vid-line'));
                return {muted: v.muted, same_box: Math.abs(b.top - p.top) < 1 && Math.abs(b.height - p.height) < 1 && Math.abs(b.width - p.width) < 1,
                        chip: chip.textContent.trim(), chip_on: box(chip).bottom <= b.bottom && box(chip).left >= b.left,
                        dots: [...slide.querySelectorAll('.spot')].filter(d => d.getClientRects().length).length,
                        line_under: Math.abs(line.top - p.bottom - parseFloat(getComputedStyle(slide.querySelector('.collage')).marginBottom)) < 1, line: slide.querySelector('.vid-line').innerText.replace(/\\s+/g, ' ').trim(),
                        caption: {top: box(slide.querySelector('.vid-line .vid-row')).top, width: box(slide.querySelector('.vid-line .look-note')).width},
                        focus: document.activeElement.getAttribute('role'), heard: document.getElementById('announce').textContent.trim(),
                        line_end: line.bottom, title: box(slide.querySelector('.about-head')).top}; }""", first)
            assert seen["muted"] and seen["same_box"] and seen["chip"] == "AI video" and seen["chip_on"], \
                f"the video does not lie over the picture, muted and labelled 'AI video': {seen}"
            assert seen["dots"] == 0 and seen["line_under"], f"while the video shows, the dots stay or its lines are not under it: {seen}"
            assert re.fullmatch(r"Look and fit will differ( on the real pieces)?\. Drag to turn Play again Show picture", seen["line"]) \
                and seen["caption"]["width"] > 0 and abs(seen["caption"]["top"] - before["scenes"] + 40) < 1, \
                f"while the video shows, the caption 'Look and fit will differ' is not where it was, above its controls: {seen}"
            assert seen["focus"] == "slider" and seen["heard"] == "Video ready", f"focus or what is heard: {seen}"
            assert abs(seen["line_end"] - before["scenes_end"]) < 1 and seen["title"] == before["title"], \
                f"something under the picture moved: {before} -> {seen}"
            assert len(made) == 1 and made[0] == videos.clip_of("front").text and made_from[0][1] == 8, \
                "the video was not asked for once, in the front picture's words (the 8-second turn)"
            page.wait_for_function("s => document.querySelector(s + ' .vid-clip').ended", arg=first, timeout=20000)
            rest = page.evaluate("s => { const v = document.querySelector(s + ' .vid-clip'); return v.duration - v.currentTime; }", first)
            assert rest < 0.2, f"it does not rest on its last frame ({rest:.2f} s before the end)"

            row = "() => document.getElementById('reel').scrollLeft"
            at = page.evaluate(row)
            turn = page.locator(f"{first} .vid-turn").bounding_box()
            page.mouse.move(turn["x"] + 10, turn["y"] + turn["height"] / 2)
            page.mouse.down()
            page.mouse.move(turn["x"] + 10 + turn["width"] / 2, turn["y"] + turn["height"] / 2, steps=6)
            page.mouse.up()
            degrees = int(page.get_attribute(f"{first} .vid-turn", "aria-valuenow"))
            assert 165 <= degrees <= 195 and page.get_attribute(f"{first} .vid-turn", "aria-valuetext") == f"{degrees} degrees", \
                f"a drag across half the video turned it to {degrees} degrees"
            page.wait_for_function("""s => { const v = document.querySelector(s + ' .vid-drag:not([hidden])')
                || document.querySelector(s + ' .vid-clip'); return v.readyState >= 1 && v.currentTime > 2; }""", arg=first)
            for key, wanted in (("ArrowRight", degrees + 15), ("ArrowRight", degrees + 30), ("ArrowLeft", degrees + 15),
                                ("Home", 0), ("End", 360), ("PageDown", 270)):
                page.keyboard.press(key)
                got = int(page.get_attribute(f"{first} .vid-turn", "aria-valuenow"))
                assert got == wanted, f"{key} turned it to {got} degrees, not {wanted}"
            assert page.evaluate(row) == at, "dragging or the arrow keys on the video moved on to another outfit"
            page.click(f"{first} [data-vid-again]")
            page.wait_for_function("s => { const v = document.querySelector(s + ' .vid-clip'); return !v.hidden && !v.paused; }",
                                   arg=first)
            page.click(f"{first} [data-vid-close]")
            assert not page.locator(f"{first} .vid.on").count() and page.locator(f"{first} .spot:visible").count() > 0, \
                "'Show picture' did not bring back the picture and its dots"
            assert page.evaluate("() => document.activeElement.classList.contains('vid-pill')"), "focus is not back on 'See it move'"

            page.reload(wait_until="networkidle")
            page.wait_for_selector(f"{first} .look-pic img")
            page.click(f"{first} .vid-pill")
            page.wait_for_selector(f"{first} .vid.on")
            assert len(made) == 1, "playing the video again made another"
            page.click(f"{first} [data-vid-close]")
            # Another outfit he said yes to (only those offer "See it move"), shown first by its address.
            page.goto(base + f"/outfits?at={said_yes['second']}", wait_until="networkidle")
            second = first
            page.wait_for_selector(f"{second} .look-pic img", timeout=20000)
            page.wait_for_timeout(400)
            page.click(f"{second} .vid-pill")
            page.wait_for_selector(f"{second} .vid-bar.ask")
            page.wait_for_function(settled)
            used = page.inner_text(f"{second} .vid-bar.ask")
            assert "No videos left today: more tomorrow" in used and "Make the video" not in used, \
                f"with the day's video used, another outfit offers {used!r}"
            placed = page.evaluate(offer_place, second)
            assert placed["covers"] == 0 and placed["under"] and placed["instead"] and placed["whole"], \
                f"'No videos left today' is not said under the picture, in place of the line and the small pictures: {placed}"
            heard = page.evaluate("""() => { const button = document.activeElement;
                const words = (button.getAttribute('aria-describedby') || '').split(' ').map(id => document.getElementById(id));
                return {button: button.textContent.trim(), described: words.map(w => w ? w.textContent : '').join(' ')}; }""")
            assert heard["button"] == "Close" and "No videos left today: more tomorrow" in heard["described"], \
                f"a screen reader is not told that no videos are left: {heard}"
            page.keyboard.press("Enter")                    # its one button, with keyboard focus: Close
            page.wait_for_selector(f"{second} .vid-pill")
            assert len(made) == 1
            # On a short phone (390 x 664) the same words and Close, with keyboard focus, show above the tab bar.
            context, other = logged_in_on(browser, viewport={"width": 390, "height": 664}, is_mobile=True, has_touch=True)
            other.goto(base + f"/outfits?at={said_yes['second']}", wait_until="networkidle")
            other.evaluate("() => document.querySelectorAll('main .demo').forEach(notice => notice.remove())")
            other.wait_for_selector(f"{second} .look-pic img")
            other.wait_for_timeout(400)
            other.click(f"{second} .vid-pill")
            other.wait_for_selector(f"{second} .vid-bar.ask")
            other.wait_for_function(settled)
            other.evaluate(at_rest)
            placed = other.evaluate(offer_place, second)
            assert "No videos left today: more tomorrow" in other.inner_text(f"{second} .vid-bar.ask"), placed
            assert placed["shows"] and placed["focus"] == "Close" and placed["focus_shows"], \
                f"on a short phone, 'No videos left today' or its Close is under the tab bar: {placed}"
            context.close()
            page.goto(base + yes_page(), wait_until="networkidle")     # the next steps start from the first outfit
            page.wait_for_selector(f"{first} .look-pic img")

            for width, height, touch in ((390, 844, True), (1280, 860, False)):
                for scheme in ("light", "dark"):
                    context, other = logged_in_on(browser, viewport={"width": width, "height": height}, is_mobile=touch,
                                                  has_touch=touch, color_scheme=scheme, reduced_motion="reduce")
                    other.goto(base + yes_page(), wait_until="networkidle")
                    other.wait_for_selector(f"{first} .look-pic img")
                    other.evaluate("() => document.querySelectorAll('main .demo').forEach(notice => notice.remove())")
                    where = f"{width} x {height}, {scheme}"
                    shut = other.evaluate(geometry, first)
                    assert shut["on_picture"] and shut["clear"], f"{where}: 'See it move' is not on the picture, clear of the dots: {shut}"
                    pill = other.evaluate("""s => { const b = document.querySelector(s + ' .vid-pill'), style = getComputedStyle(b);
                        const rgba = style.backgroundColor.match(/[\\d.]+/g).map(Number), ground = [236, 235, 231];   // --photo
                        const mix = rgba.slice(0, 3).map((c, i) => c * rgba[3] + ground[i] * (1 - rgba[3]));
                        const lum = c => { const [r, g, b] = c.map(v => { v /= 255; return v <= .03928 ? v / 12.92 : ((v + .055) / 1.055) ** 2.4; });
                            return .2126 * r + .7152 * g + .0722 * b; };
                        const reach = -parseFloat(getComputedStyle(b, '::after').top);       // its tap area, above and below
                        return {contrast: Math.round((1.05 / (lum(mix) + .05)) * 100) / 100, height: b.getBoundingClientRect().height,
                                target: b.getBoundingClientRect().height + 2 * reach}; }""", first)
                    assert pill["contrast"] >= 4.5 and pill["target"] >= 44, f"{where}: 'See it move' is hard to read or to tap: {pill}"
                    other.click(f"{first} .vid-pill")
                    other.wait_for_selector(f"{first} .vid.on")
                    other.wait_for_function("s => document.querySelector(s + ' .vid-clip').readyState >= 1", arg=first)
                    other.wait_for_timeout(300)
                    still = other.evaluate("""s => { const slide = document.querySelector(s), v = slide.querySelector('.vid-clip'),
                        box = el => el.getBoundingClientRect(), meta = [...slide.querySelectorAll('.about-head h2, .board-cost')];
                        return {paused: v.paused, rest: v.duration - v.currentTime, page: document.documentElement.scrollWidth,
                                line_end: Math.max(...meta.map(el => box(el).bottom)), tabs: box(document.querySelector('nav.tabs')).top}; }""", first)
                    assert still["paused"] and still["rest"] < 0.2, f"{where}: with less motion asked for, the video played by itself: {still}"
                    assert still["page"] <= width, f"{where}: the page is {still['page']}px wide"
                    if touch:
                        assert still["line_end"] <= still["tabs"], f"{where}: the outfit's line ends under the tab bar: {still}"
                    context.close()

        def see_it_move_from_the_picture_showing():
            # "See it move" starts from whichever of the outfit's pictures is showing. With the Café picture large, the
            # offer names it ("AI video of the Café picture, 5 seconds: he moves naturally.") and says what is left today; the clip is
            # made from exactly that stored picture, with the café's own movement, 5 seconds long; it plays muted over
            # the café picture and is not a slider (only the front picture's turn is dragged round). Each picture
            # keeps its own clip: back on Front, the turn made earlier plays again; on Café, the café's; nothing is
            # made or counted again.
            with db.connect() as con:                       # a new day: the customer's one video is his again
                con.execute("DELETE FROM video_requests")
            page.goto(base + yes_page(), wait_until="networkidle")
            page.wait_for_selector(f"{first} .look-pic img")
            row = f"{first} .shots"
            before = len(made)

            def show(name):
                page.click(f"{row} button[id$='-{name}']")
                page.wait_for_function("([s, name]) => { const b = document.querySelector(s + ` button[id$='-${name}']`);"
                                       " return b && b.getAttribute('aria-pressed') === 'true'"
                                       " && !document.querySelector('.htmx-request, .htmx-swapping, .htmx-settling'); }",
                                       arg=[row, name])
                page.wait_for_function("s => { const i = document.querySelector(s + ' .look-pic img'); return i && i.complete; }",
                                       arg=first)

            show("cafe")
            picture = page.get_attribute(f"{first} .look-pic.more img", "src")
            page.click(f"{first} .vid-pill")
            page.wait_for_selector(f"{first} .vid-bar.ask")
            offer = " ".join(page.inner_text(f"{first} .vid-bar.ask").split())
            assert offer.startswith("AI video of the Café picture, 5 seconds: he moves naturally. 1 video left today."), \
                f"on the Café picture the offer says {offer!r}"
            assert len(made) == before, "opening the offer made a video"
            # (A key pressed before HTMX has hooked up the offer it just put in sends the form without it: wait.)
            page.wait_for_function("() => !document.querySelector('.htmx-request, .htmx-swapping, .htmx-settling')")
            page.locator(f"{first} .vid-bar.ask button.btn").press("Enter")           # Make the video
            page.wait_for_selector(f"{first} .vid.on", timeout=20000)
            assert len(made) == before + 1 and made[-1] == videos.clip_of("cafe").text and "lifts the cup" in made[-1], \
                f"the Café picture's video was not asked for in the café's words: {made[before:]}"
            sent, seconds = made_from[-1]
            stored = looks.folder() / picture.rsplit("/", 1)[-1]
            assert sent == stored.read_bytes() and seconds == 5, \
                f"the clip was not made from the picture showing ({stored.name}), 5 seconds long: {len(sent)} bytes, {seconds} s"
            page.wait_for_function("s => { const v = document.querySelector(s + ' .vid-clip'); return v.currentTime > 0.3; }",
                                   arg=first, timeout=20000)
            seen = page.evaluate("""s => { const slide = document.querySelector(s), v = slide.querySelector('.vid-clip'),
                turn = slide.querySelector('.vid-turn');
                return {muted: v.muted, poster: v.getAttribute('poster'), src: v.getAttribute('src'), role: turn.getAttribute('role'),
                        label: turn.getAttribute('aria-label'), cursor: getComputedStyle(turn).cursor,
                        ground: getComputedStyle(slide.querySelector('.vid-box')).backgroundColor,
                        focus: document.activeElement === turn, drag: !!slide.querySelector('.vid-drag'),
                        line: slide.querySelector('.vid-line').innerText.replace(/\\s+/g, ' ').trim()}; }""", first)
            assert seen["muted"] and seen["poster"] == picture, f"the café's clip is not muted over the café picture: {seen}"
            assert seen["role"] == "group" and not seen["drag"] and seen["cursor"] != "grab" and "Café picture, 5 seconds" in seen["label"], \
                f"a clip that only plays is offered as something to drag round: {seen}"
            assert seen["ground"] not in ("rgba(0, 0, 0, 0)", "transparent"), \
                f"beside the café's clip the still picture shows through, a seam once he moves: {seen}"
            assert re.fullmatch(r"Look and fit will differ( on the real pieces)?\. Café, moving Play again Show picture", seen["line"]), \
                f"under the café's clip: {seen['line']!r}"
            cafe_clip = seen["src"]
            page.wait_for_function("s => document.querySelector(s + ' .vid-clip').ended", arg=first, timeout=20000)
            turn = page.locator(f"{first} .vid-turn").bounding_box()
            page.mouse.move(turn["x"] + 20, turn["y"] + turn["height"] / 2)
            page.mouse.down()
            page.mouse.move(turn["x"] + turn["width"] / 2, turn["y"] + turn["height"] / 2, steps=5)
            page.mouse.up()
            rest = page.evaluate("s => { const v = document.querySelector(s + ' .vid-clip'); return v.duration - v.currentTime; }", first)
            assert rest < 0.2 and page.get_attribute(f"{first} .vid-turn", "aria-valuenow") is None, \
                f"dragging across a clip that only plays moved it ({rest:.2f} s before its end)"
            page.click(f"{first} [data-vid-close]")

            show("front")                                   # the front picture has its own clip, made earlier: the turn
            page.click(f"{first} .vid-pill")
            page.wait_for_selector(f"{first} .vid.on[data-turns] .vid-turn[role=slider]")
            front_clip = page.get_attribute(f"{first} .vid-clip", "src")
            assert front_clip != cafe_clip, "the front picture shows the café's clip"
            page.click(f"{first} [data-vid-close]")
            show("cafe")                                    # … and the café's is kept with the café picture
            page.click(f"{first} .vid-pill")
            page.wait_for_selector(f"{first} .vid.on:not([data-turns])")
            assert page.get_attribute(f"{first} .vid-clip", "src") == cafe_clip, "the café picture lost its clip"
            page.click(f"{first} [data-vid-close]")
            show("street")                                  # a picture without a clip: the day's video is used
            page.click(f"{first} .vid-pill")
            page.wait_for_selector(f"{first} .vid-bar.ask")
            used = " ".join(page.inner_text(f"{first} .vid-bar.ask").split())
            assert used.startswith("AI video of the Street picture, 5 seconds") and "No videos left today: more tomorrow" in used \
                and "Make the video" not in used, f"with the day's video used, the Street picture offers {used!r}"
            assert len(made) == before + 1, "looking at clips that are kept made another"
            page.goto(base + yes_page(), wait_until="networkidle")     # the next steps start from the front picture
            page.wait_for_selector(f"{first} .look-pic img")

        def the_dots_small_and_there_when_pointed_at():
            # The dots on the AI picture, one per piece. They are small (at most 18px across, ring and all), yet a tap
            # anywhere within 22px of a dot's middle is a tap on it (44px to aim at). With a mouse they are out of sight
            # until the pointer is over the picture or over the list of pieces beside it, or the keyboard is in either;
            # pointing at a line of the list marks that piece's dot, and pointing at a dot marks its line. On a phone
            # (no pointer to hover with) they are always there. And a video left showing does not leave the model
            # without his dots when the row comes back to that outfit: it goes back to the picture.
            dots = """s => [...document.querySelectorAll(s + ' .spot')].map(d => { const b = d.getBoundingClientRect(), style = getComputedStyle(d);
                const x = b.x + b.width / 2, y = b.y + b.height / 2, ring = parseFloat(style.boxShadow.split('px')[3]) || 0;
                const hit = (dx, dy) => { const el = document.elementFromPoint(x + dx, y + dy); return !!el && (el === d || d.contains(el)); };
                return {across: b.width + 2 * ring, seen: +style.opacity, lit: d.classList.contains('lit'),
                        aim: hit(0, 0) && hit(-21, 0) && hit(21, 0) && hit(0, -21) && hit(0, 21)}; })"""

            def small_with_room_to_tap(where_page, where: str) -> list:
                found = where_page.evaluate(dots, first)
                assert found and len(found) == where_page.locator(f"{first} .piece-row").count(), f"{where}: not a dot per piece: {found}"
                big = [d["across"] for d in found if d["across"] > 18]
                assert not big, f"{where}: dots {big} px across, not small"
                assert found[0]["aim"], f"{where}: a tap 21px from the first dot's middle misses it: {found}"
                return found

            page.goto(base + yes_page(), wait_until="networkidle")
            page.wait_for_selector(f"{first} .look-pic img")
            assert page.evaluate("() => matchMedia('(hover: hover)').matches"), "this browser has no pointer to hover with: the step checks nothing"
            page.mouse.move(2, 2)
            page.evaluate("() => document.activeElement && document.activeElement.blur()")
            motion_ended(page)
            found = small_with_room_to_tap(page, "with a mouse")
            assert not any(d["seen"] for d in found), f"with the pointer elsewhere the dots show: {found}"
            page.hover(f"{first} .look-pic img", position={"x": 20, "y": 80})
            motion_ended(page)
            found = page.evaluate(dots, first)
            assert all(d["seen"] == 1 for d in found), f"with the pointer over the picture the dots do not show: {found}"
            page.mouse.move(2, 2)
            motion_ended(page)
            assert not any(d["seen"] for d in page.evaluate(dots, first)), "the dots stay after the pointer has left the picture"
            page.hover(f"{first} .pieces li:nth-child(2) .piece-row")
            motion_ended(page)
            found = page.evaluate(dots, first)
            assert all(d["seen"] == 1 for d in found), f"with the pointer over the list of pieces the dots do not show: {found}"
            assert [d["lit"] for d in found] == [i == 1 for i in range(len(found))], f"pointing at the second piece marks these dots: {found}"
            page.hover(f"{first} .spot:nth-child(1)")
            lit = page.evaluate("s => [...document.querySelectorAll(s + ' .piece-row')].map(r => r.classList.contains('lit'))", first)
            assert lit == [i == 0 for i in range(len(lit))], f"pointing at the first dot marks these lines of the list: {lit}"
            assert not any(d["lit"] for d in page.evaluate(dots, first)), "a dot stays marked after the pointer has left its line"
            # The dot's label (the piece, its store and price) stands over the picture above the dot, where another
            # dot may be: the pointer goes through the label to what is under it.
            through = page.evaluate("""s => { const tip = document.querySelector(s + ' .spot:hover .tip');
                if (!tip || !tip.getClientRects().length) return null;
                const b = tip.getBoundingClientRect(), under = document.elementFromPoint(b.x + b.width / 2, b.y + b.height / 2);
                return !(under && under.closest('.tip')); }""", first)
            assert through is not None, "pointing at a dot shows no label"
            assert through, "a dot's label takes the pointer itself: a dot the label lies over cannot be reached with the mouse"
            page.mouse.move(2, 2)
            page.focus(f"{first} .pieces li:nth-child(1) .piece-row")
            page.keyboard.press("Tab")                                   # by keyboard, onto the second piece
            motion_ended(page)
            found = page.evaluate(dots, first)
            assert all(d["seen"] == 1 for d in found) and found[1]["lit"], f"with the keyboard in the list the dots do not show, or the piece's is not marked: {found}"
            page.evaluate("() => document.activeElement.blur()")

            # A video left showing: on to the next outfit and back, the picture and its dots are there again.
            page.click(f"{first} .vid-pill")
            page.wait_for_selector(f"{first} .vid.on")
            page.locator(".reel-nav.next").click()
            page.wait_for_function("() => { const r = document.getElementById('reel'); return Math.round(r.scrollLeft / r.clientWidth) === 1; }")
            page.wait_for_function("s => !document.querySelector(s + ' .vid.on')", arg=first, timeout=3000)
            page.locator(".reel-nav.prev").click()
            page.wait_for_function("() => document.getElementById('reel').scrollLeft < 1")
            page.wait_for_timeout(400)
            page.hover(f"{first} .look-pic img", position={"x": 20, "y": 80})
            motion_ended(page)
            assert not page.locator(f"{first} .vid.on").count() and all(d["seen"] == 1 for d in page.evaluate(dots, first)), \
                "back on an outfit whose video was left showing, the model stands there without his dots"
            page.mouse.move(2, 2)

            # On a phone: always there, as small, as easy to tap.
            context, other = logged_in_on(browser, viewport={"width": 390, "height": 844}, has_touch=True, is_mobile=True)
            try:
                other.goto(base + yes_page(), wait_until="networkidle")
                other.wait_for_selector(f"{first} .look-pic img")
                motion_ended(other)
                found = small_with_room_to_tap(other, "on a phone")
                assert all(d["seen"] == 1 for d in found), f"on a phone, where nothing can be pointed at, the dots do not show: {found}"
            finally:
                context.close()

        def a_touch_on_a_computer_shows_the_dots_first():
            # A computer with a mouse and a touch screen: the dots are out of sight until pointed at, and a finger does
            # not point. A touch on a dot nobody can see must not open its piece: it brings the dots out, and the next
            # touch on a dot opens the piece. A touch on the picture beside the dots brings them out too; a touch
            # elsewhere on the page puts them away again. (The test browser with a touch screen switched on says it
            # has no mouse at all, like a phone; so this is the computer's browser as it is, touched for real.)
            context, other = logged_in_on(browser, viewport={"width": 1280, "height": 860})
            finger = context.new_cdp_session(other)

            def touch(x: float, y: float) -> None:
                finger.send("Input.dispatchTouchEvent", {"type": "touchStart", "touchPoints": [{"x": x, "y": y}]})
                finger.send("Input.dispatchTouchEvent", {"type": "touchEnd", "touchPoints": []})

            try:
                other.goto(base + yes_page(), wait_until="networkidle")
                other.wait_for_selector(f"{first} .look-pic img")
                other.wait_for_function("s => document.querySelector(s).complete", arg=f"{first} .look-pic img")
                motion_ended(other)
                assert other.evaluate("() => matchMedia('(hover: hover)').matches"), \
                    "this browser has no pointer to hover with: the step checks nothing"
                seen = "s => [...document.querySelectorAll(s + ' .spot')].map(d => +getComputedStyle(d).opacity)"
                popup = "() => document.querySelector('dialog#piece').open"
                at = other.evaluate("s => { const b = document.querySelector(s + ' .spot').getBoundingClientRect();"
                                    " return [b.x + b.width / 2, b.y + b.height / 2]; }", first)
                beside = other.evaluate("s => { const b = document.querySelector(s + ' .look-pic').getBoundingClientRect();"
                                        " return [b.x + 20, b.y + 80]; }", first)
                away = other.evaluate("s => { const b = document.querySelector(s + ' .about-head h2').getBoundingClientRect();"
                                      " return [b.x + 4, b.y + b.height / 2]; }", first)
                assert not any(other.evaluate(seen, first)), "the dots show before anything was touched or pointed at"
                for where, spot in (("on a dot that is out of sight", at), ("on the picture", beside)):
                    touch(*spot)
                    other.wait_for_timeout(500)
                    assert not other.evaluate(popup), f"a first touch {where} opened a piece, on a dot nobody could see"
                    motion_ended(other)
                    shown = other.evaluate(seen, first)
                    assert shown and all(one == 1 for one in shown), f"after a touch {where} the dots do not show: {shown}"
                    touch(*at)                                       # now that it can be seen, a touch on a dot opens it
                    other.wait_for_selector("dialog#piece[open]")
                    motion_ended(other)
                    touch(*other.evaluate("() => { const b = document.querySelector('dialog#piece [data-close]').getBoundingClientRect();"
                                          " return [b.x + b.width / 2, b.y + b.height / 2]; }"))
                    other.wait_for_function(f"() => !({popup})()")
                    motion_ended(other)
                    touch(*away)
                    other.wait_for_function(f"s => !({seen})(s).some(Boolean)", arg=first, timeout=3000)
            finally:
                context.close()

        def draw_again_keeps_the_picture():
            # "Draw again" takes about 20 seconds (8 here). Until the new picture has arrived, the one that was there
            # stays under the band "Drawing this outfit…", with its dots: not the pieces' photos again. The band asks
            # every 3 seconds how it is going, and the picture must not be put in anew each time (a blink): it is one
            # and the same picture, in every frame, until the new one comes up over it.
            page.goto(base + yes_page(), wait_until="networkidle")
            page.wait_for_selector(f"{first} .look-pic img")
            page.wait_for_function("s => document.querySelector(s).complete", arg=f"{first} .look-pic img")
            motion_ended(page)
            earlier = page.get_attribute(f"{first} .look-pic img", "src")
            answers: list[int] = []

            def note(response) -> None:
                if "/outfits/look/" in response.url:
                    answers.append(response.status)

            page.on("response", note)
            slow.append(8.0)
            page.evaluate("""s => { const stage = document.querySelector(s + ' .stage'), pictures = new Set();
                window.again = {frames: 0, gone: 0, drawing: 0, pictures: 0, dotless: 0, stop: false};
                const look = () => {
                    const pic = stage.querySelector('.look-pic'), img = pic && pic.querySelector('img');
                    const whole = !!(img && img.complete && img.naturalWidth) && +getComputedStyle(pic).opacity > 0.98;
                    window.again.frames += 1;
                    if (!whole && !stage.querySelector('.look-was')) window.again.gone += 1;
                    if (stage.querySelector('.look-bar.wait')) {
                        window.again.drawing += 1;
                        if (img) pictures.add(img);
                        window.again.pictures = pictures.size;
                        if (getComputedStyle(stage.querySelector('.spots')).display === 'none') window.again.dotless += 1;
                    }
                    if (!window.again.stop) requestAnimationFrame(look);
                };
                requestAnimationFrame(look); }""", first)
            # The other five photos are made from the front picture, so they go with it: that is said first.
            page.click(f"{first} .look-line button:has-text('Draw again')")
            page.wait_for_selector(f"{first} .look-ask")
            said_first = page.inner_text(f"{first} .look-ask p")
            # (Videos were made of these pictures earlier in the walk-through: they go too, and that is said as well.)
            assert re.fullmatch(r"Draw the front picture again\? The other 5 photos of this outfit are made from it, so they "
                                r"will be removed(, and with them the (video|\d videos) made from these pictures)?\. “More photos” "
                                r"draws them again\.( “See it move” makes a new (one|video), as one of your videos for the day\.)?",
                                said_first), \
                f"'Draw again' on the front picture did not say first that the other five go: {said_first!r}"
            page.click(f"{first} .look-ask button:has-text('Draw again')")
            page.wait_for_selector(f"{first} .look-bar.wait")
            kept = page.evaluate("s => { const i = document.querySelector(s + ' .look-pic img'); return i && i.getAttribute('src'); }", first)
            assert kept == earlier, "while 'Draw again' draws, the picture that was there is gone: the pieces' photos show under the band"
            page.hover(f"{first} .stage", position={"x": 20, "y": 200})
            motion_ended(page)
            dots_seen = page.evaluate("s => [...document.querySelectorAll(s + ' .spot')].map(d => d.getClientRects().length && +getComputedStyle(d).opacity)", first)
            assert dots_seen and all(one == 1 for one in dots_seen), f"while 'Draw again' draws, the kept picture has no dots when pointed at: {dots_seen}"
            page.mouse.move(2, 2)
            page.wait_for_function("([s, old]) => { const i = document.querySelector(s + ' .look-pic img');"
                                   " return i && i.getAttribute('src') !== old && i.complete && !document.querySelector(s + ' .look-bar.wait'); }",
                                   arg=[first, earlier], timeout=25000)
            motion_ended(page)
            page.wait_for_timeout(100)
            watched = page.evaluate("() => { window.again.stop = true; return window.again; }")
            page.remove_listener("response", note)
            assert watched["drawing"] > 100, f"the drawing was not watched for long enough to see a refresh: {watched}"
            assert watched["gone"] == 0, f"during 'Draw again' the box was without a whole picture for {watched['gone']} of {watched['frames']} frames"
            assert watched["dotless"] == 0, f"during 'Draw again' the dots were taken away for {watched['dotless']} frames"
            assert answers.count(204) >= 2 and answers[-1] == 200, f"the band did not ask at least twice while drawing, then get the picture: {answers}"
            assert watched["pictures"] == 1, \
                f"while drawing, the kept picture was put into the page {watched['pictures']} times: it blinks each time the band asks how it is going"
            assert set(answers[:-1]) == {204}, f"while nothing had changed the server sent the box again, to be replaced: {answers}"
            assert page.locator(f"{first} .look-line button:has-text('Draw again')").count() == 1, "no 'Draw again' under the new picture"
            # This step's drawing is not to count towards the customer's ten pictures a day: the steps after it need them.
            from wardrobe import db
            with db.connect() as con:
                con.execute("DELETE FROM look_requests WHERE id = (SELECT MAX(id) FROM look_requests)")

        def dot_opens_the_piece():
            spot = page.locator(f"{first} .spot").nth(0)
            spot.hover()
            assert spot.locator(".tip").is_visible(), "no label on hover"
            spot.click()
            page.wait_for_selector("dialog#piece[open]")
            assert page.locator("#piece-body h2").inner_text().strip(), "an empty pop-up"
            said = page.locator("#piece-body").inner_text()
            assert "outfits your plan makes" in said and ("of your outfits" in said or "your wardrobe" in said), \
                f"the pop-up does not say whether the piece is in his wardrobe and how many outfits could wear it: {said[-200:]!r}"

        def said_over_the_outfits(where_page) -> str:
            """The words of the line over the outfits that says what a change did (outfits.html), as read."""
            line = where_page.locator("main > .said")
            assert line.count() == 1, f"no line says what changed: {where_page.locator('main > .flash').all_inner_texts()}"
            return " ".join(line.first.evaluate("el => el.textContent").replace("\xa0", " ").split())

        def swap_from_the_popup():
            # 'Choose' in the pop-up changes the piece in every outfit and locks it. The page it comes back to says so
            # over the outfit: the piece, the new product and its price, the old price, and Undo. The picture of the
            # outfit before the change is never shown over it. Undo brings back the product it had and its lock state
            # (an automatic piece is automatic again, as its Wardrobe card shows). Then it is chosen again, for the
            # steps after this one. On a short phone the line is whole on the first screen, with the outfit's whole
            # picture under it, above the bar with the answers (the picture gives up the room the line takes), under
            # the starter banner too.
            choose = page.locator("#piece-body .swap li:not(.out) button", has_text="Choose")
            assert choose.count() > 0, "nothing to swap for"
            # The store's own name for the option (lang=de: under its English name where there is one), which is
            # what the outfit's list of pieces shows.
            wanted = page.locator("#piece-body .swap li:not(.out)").nth(0).locator("[lang=de]").first.inner_text()
            swapped.update(choose.nth(0).evaluate("b => ({slot: b.form.getAttribute('action').split('/')[2], "
                                                  "product: b.closest('li').querySelector('b[lang]').textContent.trim()})"))   # its name, in one language
            was = page.evaluate("""() => { const body = document.querySelector('#piece-body'), text = el => el.textContent.trim();
                const option = body.querySelector('.swap li:not(.out) form').closest('li');
                return {piece: text(body.querySelector('#piece-title')), name: text(body.querySelector('.piece-facts [lang=de]')), shown: text(body.querySelector('.piece-facts .en')),
                        price: text(body.querySelector('.sheet-price')), locked: !!body.querySelector('.piece-state'),
                        new_price: option.querySelector('.swap-price').firstChild.textContent.trim()}; }""")
            was = {key: value.replace("\xa0", " ") if isinstance(value, str) else value for key, value in was.items()}
            earlier = page.evaluate("s => { const i = document.querySelector(s); return i && i.getAttribute('src'); }",
                                    f"{first} .look-pic img")
            choose.nth(0).click()
            page.wait_for_url("**/outfits?at=**")
            page.wait_for_load_state("networkidle")
            changed_at = page.url
            names = page.locator(f"{first} .piece-text span").all_inner_texts()
            # (A message that explains why it is not, such as an outfit that no longer passes the rules: not the line
            # that says what changed, which is always there now.)
            explained = page.locator("main > .flash:not(.said)").all_inner_texts()
            assert wanted in names or explained, f"{wanted!r} is not in the outfit and nothing says why"
            line = said_over_the_outfits(page)
            assert line == (f"{was['piece']} changed in all your outfits: {wanted}, {was['new_price']} (was {was['price']}). "
                            "It stays when you change the price level. Undo"), f"after Choose the line over the outfit reads {line!r}"
            now = page.evaluate("s => { const i = document.querySelector(s); return i && i.getAttribute('src'); }",
                                f"{first} .look-pic img")
            assert not earlier or now != earlier, "the picture of the outfit before the change is shown over the changed one"

            for width, height in ((375, 667), (390, 664)):      # under the starter banner and this line: a narrow picture
                context, other = logged_in_on(browser, viewport={"width": width, "height": height}, is_mobile=True, has_touch=True)
                other.goto(changed_at, wait_until="networkidle")
                other.evaluate("() => document.querySelectorAll('main .demo').forEach(notice => notice.remove())")
                other.wait_for_selector(f"{first} .look-pic img", timeout=20000)
                the_label_never_meets_a_dot(other, f"{width} x {height} after Choose")
                context.close()
            context, other = logged_in_on(browser, viewport={"width": 390, "height": 664}, is_mobile=True, has_touch=True)
            other.goto(changed_at, wait_until="networkidle")
            other.evaluate("() => document.querySelectorAll('main .demo').forEach(notice => notice.remove())")  # (invented products)
            seen = other.evaluate("""() => { const box = el => el.getBoundingClientRect();
                const line = box(document.querySelector('main > .said')), undo = document.querySelector('main > .said button');
                return {top: line.top, bottom: line.bottom, starter: !!document.querySelector('.starter'),
                        picture: [box(document.querySelector('#reel .slide:first-child .look-pic')).top, box(document.querySelector('#reel .slide:first-child .look-pic')).bottom],
                        dock: box(document.getElementById('dock')).top,
                        tabs: box(document.querySelector('nav.tabs')).top,
                        height: box(undo).height, target: parseFloat(getComputedStyle(undo, '::after').height)}; }""")
            context.close()
            assert 0 <= seen["top"] and seen["bottom"] <= seen["picture"][0] and seen["picture"][1] <= seen["dock"] + 0.5 <= seen["tabs"] + 0.5, \
                f"at 390 x 664 the line after Choose is not whole on the first screen, or the picture under it runs under the bar with the answers: {seen}"
            assert seen["height"] >= 24, f"Undo is {seen['height']}px high: under 24px"
            assert seen["target"] >= 44, f"Undo is a {seen['target']}px tall target"

            with page.expect_navigation(url="**/outfits?at=**"):     # (the address it leaves matches that too)
                page.locator("main > .said button", has_text="Undo").click()
            page.wait_for_load_state("networkidle")
            names = page.locator(f"{first} .piece-text span").all_inner_texts()
            # The row beside the picture names the product in one language: the card's first name line (.en).
            assert was["shown"] in names, f"after Undo the outfit shows {names}, not {was['shown']!r}"
            again = page.evaluate("s => { const i = document.querySelector(s); return i && i.getAttribute('src'); }",
                                  f"{first} .look-pic img")
            assert not earlier or again == earlier, f"after Undo the outfit's picture is {again}, not its own {earlier}"
            back = " ".join(page.locator("main > .said").first.inner_text().replace("\xa0", " ").split())
            assert back.startswith(f"{was['piece']}: back to {was['name']}, {was['price']}, in all your outfits."), \
                f"after Undo the line reads {back!r}"
            page.goto(base + "/", wait_until="networkidle")
            lock = page.locator(f"#lock-{swapped['slot']}").get_attribute("aria-pressed")
            assert lock == ("true" if was["locked"] else "false"), \
                f"after Undo the piece is {'locked' if lock == 'true' else 'automatic'}; it was {'locked' if was['locked'] else 'automatic'}"

            page.goto(changed_at.split("&changed=")[0], wait_until="networkidle")      # chosen again: the steps after build on it
            page.locator(f"{first} .piece-row[hx-get*='slot={swapped['slot']}&']").evaluate("row => row.click()")
            page.wait_for_selector("dialog#piece[open] #piece-title")
            page.wait_for_load_state("networkidle")
            with page.expect_navigation(url="**/outfits?at=**"):
                page.evaluate("""wanted => [...document.querySelectorAll('#piece-body .swap li')]
                    .find(li => li.querySelector('b').textContent.trim() === wanted).querySelector('form button').click()""", wanted)
            page.wait_for_load_state("networkidle")
            assert said_over_the_outfits(page).startswith(f"{was['piece']} changed in all your outfits: {wanted}, ")

        def leave_a_layer_off():
            # An outfit with a coat or jacket: the wardrobe page lists them first, so their slot leads its address.
            # Leaving it off shows the outfit without it, said over it with 'Put it back', which shows it with it.
            page.goto(base + "/outfits?n=60", wait_until="networkidle")
            slide = page.locator("#reel .slide:has(.piece-row:nth-child(1))").filter(has=page.locator(".pieces li:nth-child(5)")).first
            rows = slide.locator(".piece-row")
            before = rows.count()
            outer = rows.nth(0).locator(".piece-text b").inner_text()
            rows.nth(0).evaluate("row => row.click()")
            page.wait_for_selector("dialog#piece[open]")
            off = page.locator("#piece-body a", has_text="Leave the")
            assert off.count() == 1, "a five-piece outfit whose first piece cannot be left off"
            label = re.fullmatch(r"Leave the (.+) off", off.inner_text().strip()).group(1)
            off.click()
            page.wait_for_url("**/outfits?at=**")
            page.wait_for_load_state("networkidle")
            assert page.locator(f"{first} .piece-row").count() == before - 1, "the piece is still there"
            line = said_over_the_outfits(page)
            assert line == f"Showing this outfit without the {label}. Put it back", f"after leaving it off the line reads {line!r}"
            with page.expect_navigation(url="**/outfits?at=**"):
                page.locator("main > .said a", has_text="Put it back").click()
            page.wait_for_load_state("networkidle")
            rows = page.locator(f"{first} .piece-row")
            assert rows.count() == before and rows.nth(0).locator(".piece-text b").inner_text() == outer, \
                f"'Put it back' shows {rows.count()} pieces, the first {rows.nth(0).locator('.piece-text b').inner_text()!r}, not {outer!r}"

        def the_piece_pop_up_on_a_phone():
            # Tapping a dot on a phone (390 x 844): the pop-up is named by the piece, says 'Quality' next to the
            # number and what each option costs next to the piece, and shows the quick changes to this outfit ('In
            # this outfit') on its first screen. Swiping inside it never moves the page behind it, and its close
            # button is a 44px target. 'Compare all N options' leads to the piece's page, whose way back returns to
            # the same outfit with the Outfits tab lit.
            context = browser.new_context(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
            other = context.new_page()
            other.goto(base + "/login", wait_until="networkidle")
            other.fill("input[name=email]", EMAIL)
            other.fill("input[name=password]", PASSWORD)
            other.click("button:has-text('Log in')")
            other.wait_for_load_state("networkidle")
            other.goto(base + "/outfits", wait_until="networkidle")
            other.wait_for_selector(f"{first} .look-pic img")
            other.evaluate("() => window.scrollTo(0, 120)")
            other.wait_for_timeout(300)
            still = other.evaluate("scrollY")
            coat = other.locator(f"{first} .spot[aria-label*=coat i]")         # the tallest pop-up: the coat's
            spot = coat.first if coat.count() else other.locator(f"{first} .spot").first
            sig = re.search(r"at=([^&]+)", spot.get_attribute("hx-get")).group(1)
            spot.tap()
            other.wait_for_selector("dialog#piece[open] #piece-title")
            motion_ended(other)
            sheet = other.locator("dialog#piece")
            expect(sheet, "the pop-up is not named by the piece").to_have_accessible_name(
                other.locator("#piece-title").inner_text().strip())
            said = other.locator("#piece-body").inner_text()
            assert re.search(r"Quality\s+\d+", said), f"no 'Quality' next to the number: {said[:200]!r}"
            priced = other.locator("#piece-body .swap li form").count()      # an option without a price has no Choose
            differences = re.findall(r"[−+]\d[\d,.]*\s€|same price", said)
            assert priced and len(differences) == priced, f"{priced} options with a price, {len(differences)} price differences"
            seen = other.evaluate("""() => {
                const sheet = document.querySelector('dialog#piece'), box = sheet.getBoundingClientRect();
                const heads = [...sheet.querySelectorAll('h3')].map(h => h.textContent.trim());
                const chips = [...sheet.querySelectorAll('.chips a')], close = sheet.querySelector('.sheet-close').getBoundingClientRect();
                return {heads, scrolled: sheet.scrollTop, bottom: box.bottom, close: [close.width, close.height],
                        chips: chips.length ? chips[chips.length - 1].getBoundingClientRect().bottom : null};
            }""")
            assert seen["heads"][:2] == ["In this outfit", "Swap it for"], f"the pop-up's parts are {seen['heads']}"
            assert seen["scrolled"] == 0 and seen["chips"] <= seen["bottom"], \
                f"'In this outfit' ends at {seen['chips']:.0f}px, under the sheet's first screen ({seen['bottom']:.0f}px)"
            assert min(seen["close"]) >= 44, f"the close button is {seen['close'][0]:.0f} x {seen['close'][1]:.0f}px"
            touch, box = context.new_cdp_session(other), sheet.bounding_box()
            for _ in range(3):
                touch.send("Input.synthesizeScrollGesture", {"x": 195, "y": int(box["y"] + box["height"] - 60), "xDistance": 0,
                                                            "yDistance": -300, "speed": 1200, "gestureSourceType": "touch"})
                other.wait_for_timeout(300)
            # Some headless browsers (GitHub's, for one) ignore a synthesized touch swipe inside a dialog: the sheet
            # does not move at all. Then it is scrolled to its end directly, so the promise below (scrolled to its end,
            # the close button stays at its top) is still checked, never skipped.
            if other.evaluate("() => { const s = document.querySelector('dialog#piece'); return s.scrollTop === 0 && s.scrollHeight > s.clientHeight }"):
                other.evaluate("() => { const s = document.querySelector('dialog#piece'); s.scrollTop = s.scrollHeight }")
                other.wait_for_timeout(300)
            # Swiped to its end, the sheet keeps its close button where it was: at its top, whole and on top.
            kept = other.evaluate("""() => {
                const sheet = document.querySelector('dialog#piece'), s = sheet.getBoundingClientRect();
                const close = sheet.querySelector('.sheet-close'), c = close.getBoundingClientRect();
                return {scrollable: sheet.scrollHeight > sheet.clientHeight, scrolled: sheet.scrollTop, top: c.top - s.top,
                        on_top: close.contains(document.elementFromPoint(c.left + c.width / 2, c.top + c.height / 2))};
            }""")
            assert (kept["scrolled"] > 0 or not kept["scrollable"]) and 0 <= kept["top"] <= 12 and kept["on_top"], \
                f"once the pop-up is swiped, its close button is not whole at its top: {kept}"
            other.locator("dialog#piece .sheet-close").tap()
            other.wait_for_selector("dialog#piece:not([open])", state="attached")
            assert other.evaluate("scrollY") == still, f"swiping inside the pop-up moved the page from {still} to {other.evaluate('scrollY')}"
            spot.tap()
            other.wait_for_selector("dialog#piece[open] #piece-title")
            other.locator("#piece-body a", has_text=re.compile(r"^Compare all \d+ options$")).click()
            other.wait_for_load_state("networkidle")
            crumb = other.locator(".crumb a")
            assert crumb.inner_text().strip() == "Back to the outfit", f"the piece page's way back reads {crumb.inner_text()!r}"
            assert other.locator(".tabs a[aria-current=page]").inner_text() == "Outfits", "the Outfits tab is not lit"
            crumb.click()
            other.wait_for_load_state("networkidle")
            back = re.search(r"at=([^&]+)", other.locator(f"{first} .piece-row").first.get_attribute("hx-get")).group(1)
            assert back == sig, f"back on {back}, not on the outfit the pop-up was opened from ({sig})"
            context.close()

        def a_piece_without_javascript():
            # Each piece of an outfit (its photo, its dot, its line in the list) is a link to the piece's own page,
            # opened from that outfit. With JavaScript off on a phone, tapping a line, and then a dot (or the photo, while
            # the outfit has no picture), opens that page, in the Outfits tab, and its way back shows the same outfit
            # first. With JavaScript on the same pieces are buttons: a screen reader calls them so, Space opens the
            # pop-up, and the address stays.
            context = browser.new_context(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True,
                                          java_script_enabled=False)
            try:
                other = context.new_page()
                other.on("response", lambda r: failures.append(f"{r.status} {r.request.method} {r.url.replace(base, '')[:100]}")
                         if r.status >= 400 and r.url.startswith(base) and "does-not-exist" not in r.url else None)
                other.goto(base + "/login", wait_until="networkidle")
                other.fill("input[name=email]", EMAIL)
                other.fill("input[name=password]", PASSWORD)
                other.click("button:has-text('Log in')")
                other.wait_for_load_state("networkidle")
                other.goto(base + "/outfits?occasion=office", wait_until="networkidle")
                outfit = other.locator(first).get_attribute("id")
                pieces = other.evaluate(f"""() => [...document.querySelectorAll('{first} :is(.tile, .spot, .piece-row)')].map(el => ({{
                    tag: el.tagName.toLowerCase(), href: el.getAttribute('href') || '', pop_up: el.getAttribute('hx-get') || ''}}))""")
                sig = re.search(r"at=([^&]+)", pieces[0]["pop_up"]).group(1)
                for piece in pieces:
                    slot = re.search(r"slot=([^&]+)", piece["pop_up"]).group(1)
                    assert piece["tag"] == "a" and piece["href"] == f"/slot/{slot}?from=outfit&at={sig}&occasion=office", \
                        f"a piece of the outfit is not a link to its page from this outfit: {piece}"
                pictured = other.locator(f"{first} .look-pic img").count() > 0
                for kind in (".piece-row", ".spot" if pictured else ".tile"):
                    tapped = other.locator(f"{first} {kind}").last
                    address = tapped.get_attribute("href")
                    with other.expect_navigation():
                        tapped.tap()
                    other.wait_for_load_state("networkidle")
                    assert other.url == base + address, f"tapping a {kind} without JavaScript opened {other.url}, not {address}"
                    crumb = other.locator(".crumb a")
                    assert crumb.inner_text().strip() == "Back to the outfit", f"the piece page's way back reads {crumb.inner_text()!r}"
                    assert other.locator(".tabs a[aria-current=page]").inner_text() == "Outfits", "the Outfits tab is not lit"
                    with other.expect_navigation():
                        crumb.tap()
                    other.wait_for_load_state("networkidle")
                    assert other.url == f"{base}/outfits?at={sig}&occasion=office", f"the way back leads to {other.url}"
                    assert other.locator(first).get_attribute("id") == outfit, "the way back shows another outfit first"
            finally:
                context.close()

            page.goto(base + "/outfits?occasion=office", wait_until="networkidle")
            for kind in (".tile", ".spot", ".piece-row"):
                expect(page.locator(f"{first} {kind}").first, f"with JavaScript a {kind} is not a button").to_have_role("button")
            address = page.url
            page.locator(f"{first} .piece-row").first.focus()
            page.keyboard.press("Space")
            page.wait_for_selector("dialog#piece[open] #piece-title")
            assert page.url == address, f"Space on a piece's line left the page for {page.url}"
            page.keyboard.press("Escape")
            page.wait_for_selector("dialog#piece:not([open])", state="attached")
            assert page.evaluate("() => document.activeElement.matches('#reel .slide:first-child .piece-row')"), \
                "after the pop-up is closed, focus is not back on the piece's line"

        def logged_in_on(where_browser, **screen):
            """A page of its own, logged in as the customer, in a context with these settings (viewport, touch...)."""
            context = where_browser.new_context(**screen)
            other = context.new_page()
            other.goto(base + "/login", wait_until="networkidle")
            other.fill("input[name=email]", EMAIL)
            other.fill("input[name=password]", PASSWORD)
            other.click("button:has-text('Log in')")
            other.wait_for_load_state("networkidle")
            return context, other

        def open_the_coat(other) -> None:
            """The coat's pop-up from the first outfit's list of pieces (the tallest pop-up), or the first piece's."""
            other.goto(base + "/outfits", wait_until="networkidle")
            coat = other.locator(f"{first} .piece-row[title*=coat i]")
            (coat.first if coat.count() else other.locator(f"{first} .piece-row").first).click()
            other.wait_for_selector("dialog#piece[open] #piece-title")
            other.wait_for_load_state("networkidle")
            motion_ended(other)

        def a_pieces_card_reads_the_same_everywhere():
            # A piece's card says the same lines in the same order in the pop-up and on its own page: the store and
            # 'Quality 73/100', the store's name for the product in English (lang=en) with its own words under it
            # (lang=de, smaller, or on a card where the English is already 13px, greyer), 'Fabric: …' and 'Fit: …'.
            # Its row in a list (the Wardrobe, Buy) is short: the same English name and the cut to act on, nothing
            # more. Every line inside its card, on a phone (light) and a computer (dark). The piece: the first of the
            # first outfit whose name the word list knows and whose cut is said.
            LINES = """root => {
                const box = root.getBoundingClientRect(), lines = {};
                const found = {by: root.querySelector('.by'), en: root.querySelector('[lang=en]'),
                               orig: root.querySelector('[lang=de]:not(.colour-name, .buy-meta [lang=de])'),
                               fabric: root.querySelector('.fabric'), fit: root.querySelector('.fit')};
                for (const [kind, el] of Object.entries(found)) {
                    if (!el) { lines[kind] = null; continue; }
                    const r = el.getBoundingClientRect(), cs = getComputedStyle(el);
                    lines[kind] = {text: el.textContent.replace(/\\s+/g, ' ').trim(), top: Math.round(r.top),
                                   size: parseFloat(cs.fontSize), colour: cs.color, shown: r.width > 0 && r.height > 0,
                                   inside: r.left >= box.left - 1 && r.right <= box.right + 1};
                }
                const fit = [...root.querySelectorAll('.row-caution')].find(e => e.textContent.includes('Fit:'));
                return {lines, wide: document.documentElement.scrollWidth,
                        caution: fit ? fit.textContent.replace(/\\s+/g, ' ').trim() : null};
            }"""
            ORDER = ["by", "en", "orig", "fabric", "fit"]
            for width, height, scheme in ((390, 844, "light"), (1280, 800, "dark")):
                phone = width < 760
                context, other = logged_in_on(browser, viewport={"width": width, "height": height}, color_scheme=scheme,
                                              is_mobile=phone, has_touch=phone)
                other.goto(base + "/outfits", wait_until="networkidle")
                rows, place = other.locator(f"{first} .piece-row"), {}
                for i in range(rows.count()):
                    rows.nth(i).click()
                    other.wait_for_selector("dialog#piece[open] #piece-title")
                    other.wait_for_load_state("networkidle")
                    if other.locator("#piece-body .piece-facts [lang=en]").count() and other.locator("#piece-body .fit").count():
                        place["pop-up"] = other.locator("#piece-body .piece-facts").evaluate(LINES)
                        break
                    other.locator("dialog#piece .sheet-close").click()
                    other.wait_for_selector("dialog#piece:not([open])", state="attached")
                assert place, "no piece of the first outfit has an English name and a cut to tell"
                name = other.locator("#piece-title").inner_text().strip()
                slot = other.locator("#piece-body a[href^='/slot/']").first.get_attribute("href").split("?")[0].split("/")[2]
                sig = re.search(r"at=([^&]+)", rows.nth(i).get_attribute("hx-get")).group(1)
                other.goto(base + "/", wait_until="networkidle")
                place["Wardrobe"] = other.locator(f"#card-{slot} .slot-text").evaluate(LINES)
                other.goto(base + f"/slot/{slot}", wait_until="networkidle")
                place["piece page"] = other.locator(".cand.chosen .cand-body").evaluate(LINES)
                other.goto(base + f"/outfits/buy?at={sig}", wait_until="networkidle")
                line = other.locator("li.buy").filter(has=other.locator(".buy-slot", has_text=re.compile("^" + re.escape(name))))
                assert line.count() == 1, f"{name!r} is not one line on Buy"
                place["Buy"] = line.locator(".buy-main").evaluate(LINES)
                context.close()
                said, rows_said = {}, {}
                for where, seen in place.items():
                    assert seen["wide"] <= width + 1, f"at {width}px the {where} is wider than the screen"
                    lines = seen["lines"]
                    if where in ("Wardrobe", "Buy"):
                        # A row in a list: the product's name in one language (the card's first name line), and of
                        # the rest only the cut to act on, as a caution; the quality, the store's own words and the
                        # fabric are on the card.
                        assert lines["en"] and lines["en"]["shown"] and lines["en"]["inside"], f"at {width}px the {where} row has no name: {lines}"
                        assert not (lines["by"] or lines["orig"] or lines["fabric"]), f"at {width}px the {where} row repeats the card: {lines}"
                        rows_said.setdefault("en", {})[where] = lines["en"]["text"]
                        rows_said.setdefault("fit", {})[where] = seen["caution"]
                        continue
                    assert all(lines[k] and lines[k]["shown"] for k in ORDER), f"at {width}px the {where} leaves out a line: {lines}"
                    tops = [lines[k]["top"] for k in ORDER]
                    assert tops == sorted(tops) and len(set(tops)) == len(tops), \
                        f"at {width}px the {where} says its lines in another order: {dict(zip(ORDER, tops))}"
                    assert all(lines[k]["inside"] for k in ORDER), f"at {width}px a line runs out of the {where}'s card: {lines}"
                    en, orig = lines["en"], lines["orig"]
                    assert orig["size"] < en["size"] or (orig["size"] == en["size"] == 13 and orig["colour"] != en["colour"]), \
                        f"at {width}px the {where}'s original name is not in small print: {orig} under {en}"
                    for k in ORDER:
                        said.setdefault(k, {})[where] = lines[k]["text"]
                for k in ORDER:
                    assert len(set(said[k].values())) == 1, f"at {width}px the two cards say the {k} line differently: {said[k]}"
                for where in ("Wardrobe", "Buy"):
                    assert rows_said["en"][where] == said["en"]["pop-up"], f"at {width}px the {where} row names it otherwise: {rows_said}"
                    assert rows_said["fit"][where] == said["fit"]["pop-up"], f"at {width}px the {where} row does not say the cut: {rows_said}"

        def a_pieces_words_tidy_at_320():
            # On the smallest phone (320px), a card's lines stay tidy. The dot between the store and its quality never
            # hangs at a line's end: where the quality goes onto a line of its own its dot is out of sight, and a dot
            # in sight is on one line with both (Wardrobe, with a card for two tees, every piece's page and the pop-up).
            # The 'estimated' chip goes onto the next line whole, inside the card. The pop-up's other options say the
            # store and quality, then the English name, then the original, as every card; "No other option for this
            # piece yet." stands 12px under the chips. On the shopping list a product with no fabric at all says
            # "Fabric not stated: check the product page" in amber.
            DOTS = """root => {
                const out = {hanging: [], hidden: 0, seen: 0, outside: [], split: [], overlap: []};
                const box = root.getBoundingClientRect();
                for (const by of root.querySelectorAll('.by')) {
                    const sep = by.querySelector('.sep'), st = by.querySelector('.store'), q = by.querySelector('.quality');
                    const b = by.getBoundingClientRect(), s = sep.getBoundingClientRect(), ss = st.getBoundingClientRect();
                    const range = document.createRange(); range.selectNodeContents(q);
                    const rects = [...range.getClientRects()].filter(r => r.width > 0);
                    const word = rects.find(r => r.left >= s.right - 1) || rects[0];   // "Quality", after the dot
                    const shown = s.left >= b.left - 0.5;
                    if (word.left < b.left - 1) out.outside.push(by.textContent.trim());
                    if (shown) {
                        out.seen++;
                        if (Math.abs(s.top - ss.top) > 3 || Math.abs(word.top - s.top) > 5) out.hanging.push(by.textContent.trim());
                    } else {
                        out.hidden++;
                        if (Math.abs(ss.top - s.top) < 3) out.hanging.push('hidden between: ' + by.textContent.trim());
                    }
                    const each = by.closest('.slot-text') && by.closest('.slot-text').querySelector('.each');
                    if (each) {
                        const e = each.getBoundingClientRect();
                        for (const part of [st, q]) {
                            const r = part.getBoundingClientRect();
                            if (r.right > e.left && r.left < e.right && r.bottom > e.top && r.top < e.bottom) out.overlap.push(by.textContent.trim());
                        }
                    }
                }
                // (The store's and the quality's left edges are the dot's room, out of sight at a line's start: the
                // store's word, and the quality's word and number, are measured instead.)
                for (const el of root.querySelectorAll('.by .store, .by .pill, .by .quality, .fabric, .est, .fit')) {
                    const card = el.closest('.slot-text, .cand-body, .buy-main, .piece-facts, .swap-text') || root;
                    const words = document.createRange(); words.selectNodeContents(el);
                    const r = el.matches('.store') ? words.getBoundingClientRect() : el.getBoundingClientRect();
                    const c = card.getBoundingClientRect(), left = el.matches('.quality') ? c.left : r.left;
                    if (r.width && (left < c.left - 1 || r.right > c.right + 1)) out.outside.push(el.textContent.trim());
                    if (el.matches('.est') && el.getClientRects().length > 1) out.split.push(el.parentElement.textContent.trim());
                }
                out.box = [box.left, box.right];
                return out;
            }"""

            def tidy(seen: dict, where: str) -> None:
                assert not seen["hanging"], f"at 320px a dot hangs at a line's end on the {where}: {seen['hanging']}"
                assert not seen["outside"], f"at 320px a line runs out of its card on the {where}: {seen['outside']}"
                assert not seen["split"], f"at 320px the 'estimated' chip breaks in two on the {where}: {seen['split']}"
                assert not seen["overlap"], f"at 320px the store or quality runs into '2 × …' on the {where}: {seen['overlap']}"

            context, other = logged_in_on(browser, viewport={"width": 320, "height": 640}, is_mobile=True, has_touch=True)
            listed = DATA / "store_catalog.json"
            try:
                other.goto(base + "/", wait_until="networkidle")
                assert other.locator(".slot-text .each").count(), "no card for two of a piece on the Wardrobe"
                seen = other.locator("#wardrobe-body").evaluate(DOTS)
                tidy(seen, "Wardrobe")
                # A row on the Wardrobe leaves the quality to the piece's card (its own page, the pop-up), which
                # the loop below measures at 320px.
                assert not other.locator("#wardrobe-body .by").count(), "a Wardrobe row repeats the card's quality"
                slots = sorted({h.split("?")[0] for h in other.eval_on_selector_all(
                    "#wardrobe-body a.slot-main", "els => els.map(e => e.getAttribute('href'))")})
                for path in slots:
                    other.goto(base + path, wait_until="networkidle")
                    tidy(other.locator("main").evaluate(DOTS), f"page {path}")
                # An option added by its link says "added by you" after its quality: whole, on one line (on a line of
                # its own where the card is narrow), inside the card, never over the store, the quality or the price,
                # and 4px from the quality where it sits beside it; at 320, 390 and 1280. It is removed again.
                TAG = """cand => {
                    const box = e => e.getBoundingClientRect(), tag = cand.querySelector('.by > .tag');
                    const t = box(tag), c = box(cand.querySelector('.cand-body')), pill = box(cand.querySelector('.by .pill'));
                    const words = document.createRange(); words.selectNodeContents(tag);
                    const lines = new Set([...words.getClientRects()].filter(r => r.width).map(r => Math.round(r.top))).size;
                    const over = [...cand.querySelectorAll('.by .store, .by .quality, .by .pill, .cand-top .price')]
                        .filter(e => { const r = box(e); return r.right > t.left && r.left < t.right && r.bottom > t.top && r.top < t.bottom; })
                        .map(e => e.textContent.trim());
                    return {lines, over, inside: t.left >= c.left - 1 && t.right <= c.right + 1,
                            beside: Math.abs(t.top - pill.top) < 3, gap: t.left - pill.right};
                }"""
                other.goto(base + slots[0], wait_until="networkidle")
                other.fill("#add textarea[name=urls]", "https://www.cos.com/de-de/men/product/wool-jumper-grey-1234567001.html")
                with other.expect_navigation():
                    other.locator("#add button", has_text="Add").click()
                other.wait_for_load_state("networkidle")
                mine = other.locator(".cand:has(.by > .tag)")
                assert mine.count() == 1, f"the option added by its link is not marked 'added by you' ({mine.count()})"
                for width in (320, 390, 1280):
                    other.set_viewport_size({"width": width, "height": 800})
                    seen = mine.evaluate(TAG)
                    assert seen["lines"] == 1 and not seen["over"] and seen["inside"], \
                        f"at {width}px 'added by you' is broken or runs into its card: {seen}"
                    assert not seen["beside"] or seen["gap"] >= 3.5, f"at {width}px 'added by you' touches the quality: {seen}"
                    if width < 400:
                        tidy(other.locator("main").evaluate(DOTS), f"page {slots[0]} with an option added by you")
                other.set_viewport_size({"width": 320, "height": 640})
                other.once("dialog", lambda d: d.accept())         # "Remove “…” from this piece's options?"
                with other.expect_navigation():
                    mine.locator("button", has_text="Remove").click()
                other.wait_for_load_state("networkidle")
                assert not other.locator(".by > .tag").count(), "the option added by its link was not removed"
                other.goto(base + "/outfits", wait_until="networkidle")
                rows, gaps, swaps = other.locator(f"{first} .piece-row"), [], 0
                for i in range(rows.count()):
                    rows.nth(i).click()
                    other.wait_for_selector("dialog#piece[open] #piece-title")
                    other.wait_for_load_state("networkidle")
                    tidy(other.locator("#piece-body").evaluate(DOTS), "pop-up")
                    for row in other.eval_on_selector_all("#piece-body .swap-text", """els => els.map(t => {
                            const top = s => { const e = t.querySelector(s); return e ? e.getBoundingClientRect().top : null; };
                            return [top('.by'), top('b'), top('.orig')]; })"""):
                        swaps += 1
                        assert row[0] < row[1] and (row[2] is None or row[1] < row[2]), \
                            f"an option in the pop-up is not said as every card: store and quality, name, original {row}"
                    gap = other.evaluate("""() => { const p = [...document.querySelectorAll('#piece-body .sheet-more')]
                        .find(e => e.textContent.includes('No other option')); const c = p && p.previousElementSibling;
                        return p && c && c.matches('.chips') ? p.getBoundingClientRect().top - c.getBoundingClientRect().bottom : null; }""")
                    if gap is not None:
                        gaps.append(round(gap))
                    other.locator("dialog#piece .sheet-close").click()
                    other.wait_for_selector("dialog#piece:not([open])", state="attached")
                assert swaps, "no other option in the first outfit's pop-ups"
                assert all(g == 12 for g in gaps), f"'No other option for this piece yet.' is not 12px under the chips: {gaps}"
                context.close()
                # Two products with no fabric on their label, published the way the operator does: indigo jeans (the
                # fabric jeans usually have, 'estimated', the longest fabric line) and a grey jumper (nothing at all).
                # Every signed-in page picks up a list as soon as it is published, and keeps what it picked: so a
                # second customer looks at it, and it is taken away again at the end (as in one_tap_colour).
                product = {"store": "cos", "currency": "EUR", "composition_text": "", "fit": "regular", "sizes_all": [],
                           "sizes_in_stock": [], "image_url": "", "source": "collected", "colour_hex": None}
                products = [{**product, "id": "cos-81", "category": "jeans", "name": "Weite Jeans", "slug": "weite-jeans",
                             "price": 59, "colour": "Indigoblau", "url": "https://www.example.com/de/81"},
                            {**product, "id": "cos-82", "category": "knit", "name": "Pullover", "slug": "pullover",
                             "price": 49, "colour": "Grau", "url": "https://www.example.com/de/82"}]
                listed.write_text(json.dumps({"published_at": "2026-11-12T12:00:00+01:00",
                                              "collected_at": "2026-11-11T17:00:00+01:00", "stores": {}, "products": products}))
                context = browser.new_context(viewport={"width": 320, "height": 640}, is_mobile=True, has_touch=True)
                other = context.new_page()
                other.on("response", lambda r: failures.append(f"{r.status} {r.request.method} {r.url.replace(base, '')[:100]}")
                         if r.status >= 400 and r.url.startswith(base) else None)
                other.on("pageerror", lambda e: failures.append(f"script error: {e}"))
                other.goto(base + "/signup", wait_until="networkidle")
                other.fill("input[name=email]", "words-" + EMAIL)
                other.fill("input[name=password]", PASSWORD)
                other.click("button:has-text('Create account')")
                a_customer_from_before(other)
                other.goto(base + "/", wait_until="networkidle")
                # What is true of the store's products is said once over the rows, not on each: the jeans' fabric
                # is estimated and the jumper's not stated, in plain grey; COS's sizes were not checked, in amber.
                once = " ".join(other.locator("#wardrobe-body .once").all_inner_texts())
                assert "Fabric is estimated for 1 of the 2 products here and not stated for 1" in once, \
                    f"the Wardrobe does not say once what is known of the fabrics: {once!r}"
                assert not other.locator("#wardrobe-body .slot-text .fabric, #wardrobe-body .slot-text .est").count(), \
                    "a Wardrobe row repeats its fabric"
                tidy(other.locator("#wardrobe-body").evaluate(DOTS), "Wardrobe with the published jeans")
                other.goto(base + "/list", wait_until="networkidle")
                tidy(other.locator("main").evaluate(DOTS), "shopping list")
                assert not other.locator(".buy-main .fabric").count(), "a shopping list row repeats its fabric"
                said = other.locator(".store-list .once .fabric-once")
                assert said.count() == 1 and "not stated for 1" in said.inner_text(), \
                    f"the shopping list does not say once that a fabric is not stated: {said.all_inner_texts()}"
                colours = other.evaluate("""() => { const c = s => getComputedStyle(document.querySelector(s)).color;
                    const e = document.createElement('i'); document.body.append(e); const of = v => { e.style.color = v;
                    return getComputedStyle(e).color; }; const out = {fabric: c('.once .fabric-once'), sizes: c('.once .sizes'),
                    muted: of('var(--muted)'), ok: of('var(--ok)')}; e.remove(); return out; }""")
                assert colours["fabric"] == colours["muted"] and colours["sizes"] == colours["ok"], \
                    f"amber is for a size to check only, the fabric is plain grey: {colours}"
            finally:
                listed.unlink(missing_ok=True)
                context.close()

        def pop_up_never_hides_the_focus():
            # The pop-up's top row (the piece's name and Close) stays while the sheet scrolls, and what has keyboard
            # focus is never hidden under it (WCAG 2.4.11). On a small phone and a short computer screen, where the
            # coat's pop-up scrolls, Tab goes from Close to the last control, then from the sheet's end Shift+Tab
            # comes back up to Close, so that each new focus comes in from below and from above. At least one of
            # five points of each must be inside the sheet with neither the top row nor Close over it, and its focus
            # ring must reach no further down than the sheet's bottom edge, where it would be cut off.
            hidden: list[str] = []
            cut: list[str] = []
            for width, height, phone in ((320, 568, True), (1280, 640, False)):
                context, other = logged_in_on(browser, viewport={"width": width, "height": height}, is_mobile=phone, has_touch=phone)
                open_the_coat(other)
                assert other.evaluate("() => { const s = document.querySelector('dialog#piece'); return s.scrollHeight > s.clientHeight; }"), \
                    f"at {width} x {height} the pop-up does not scroll, so this step would check nothing"
                for key in ("Tab", "Shift+Tab"):
                    if key == "Shift+Tab":          # from the sheet's end, its last control first
                        other.evaluate("""() => { const sheet = document.querySelector('dialog#piece');
                            const all = [...sheet.querySelectorAll('#piece-body a[href], #piece-body button')].filter(e => e.offsetParent);
                            sheet.scrollTop = sheet.scrollHeight; all[all.length - 1].focus(); }""")
                    stops = 0
                    for _ in range(60):
                        if key == "Tab" or stops:
                            other.keyboard.press(key)
                        focus = other.evaluate("""() => {
                            const sheet = document.querySelector('dialog#piece'), el = document.activeElement;
                            const row = sheet.querySelector('.piece-top'), close = sheet.querySelector('.sheet-close');
                            if (!sheet.contains(el) || el === sheet || el === close) return null;     // round to Close, or out
                            const s = sheet.getBoundingClientRect(), r = el.getBoundingClientRect();
                            const points = [[r.left + r.width / 2, r.top + r.height / 2], [r.left + 1, r.top + 1],
                                            [r.right - 1, r.top + 1], [r.left + 1, r.bottom - 1], [r.right - 1, r.bottom - 1]];
                            const seen = points.filter(([x, y]) => {
                                if (x < s.left || y < s.top || x >= s.right || y >= s.bottom) return false;
                                const top = document.elementFromPoint(x, y);
                                return top && !((row.contains(top) || close.contains(top)) && !el.contains(top));
                            }).length;
                            const style = getComputedStyle(el);     // how far the ring reaches outside the box
                            const ring = style.outlineStyle === 'none' ? 0
                                : Math.max(0, parseFloat(style.outlineOffset) + parseFloat(style.outlineWidth));
                            const below = r.bottom + ring - (s.top + sheet.clientTop + sheet.clientHeight);
                            return {seen, below, name: (el.innerText || el.getAttribute('aria-label') || el.tagName).replace(/\\s+/g, ' ').trim().slice(0, 50)};
                        }""")
                        if focus is None:
                            break
                        stops += 1
                        if not focus["seen"]:
                            hidden.append(f"{width} x {height} {key}: {focus['name']}")
                        if focus["below"] > 0.5:
                            cut.append(f"{width} x {height} {key}: {focus['name']} ({focus['below']:.1f}px)")
                    assert stops >= 4, f"at {width} x {height}, {key} met only {stops} things to focus in the pop-up"
                context.close()
            assert not hidden, "hidden under the pop-up's top row while it had keyboard focus: " + "; ".join(hidden[:6])
            assert not cut, "a focus ring cut off by the pop-up's bottom edge: " + "; ".join(cut[:6])

        def the_page_behind_the_pop_up_stays_put():
            # On a computer set to always show scrollbars, their room is kept on every page, so that the page behind
            # the pop-up does not move sideways when the pop-up opens or closes, even on a page that does not scroll.
            # The browsers here hide scrollbars, so this step has one of its own that shows them, in a window taller
            # than the outfits page (whose picture grows with the window, up to its largest).
            shown = p.chromium.launch(ignore_default_args=["--hide-scrollbars"], args=["--disable-features=OverlayScrollbar"])
            try:
                context, other = logged_in_on(shown, viewport={"width": 1280, "height": 1400})
                other.goto(base + "/outfits", wait_until="networkidle")
                for _ in range(3):
                    tall = other.evaluate("document.documentElement.scrollHeight")
                    if tall <= other.evaluate("innerHeight"):
                        break
                    other.set_viewport_size({"width": 1280, "height": tall + 100})
                    other.wait_for_timeout(100)
                where = """() => {
                    const probe = document.createElement('div');            // a box that always has a scrollbar
                    probe.style.cssText = 'position:absolute; top:0; width:100px; height:100px; overflow:scroll';
                    document.body.append(probe);
                    const bar = probe.offsetWidth - probe.clientWidth;
                    probe.remove();
                    return {bar, scrolls: document.documentElement.scrollHeight > innerHeight,
                            edges: ['header.top', 'nav.tabs', 'main'].map(s => {
                                const b = document.querySelector(s).getBoundingClientRect();
                                return s + ' ' + b.left.toFixed(1) + '-' + b.right.toFixed(1); })};
                }"""
                shut = other.evaluate(where)
                assert shut["bar"] >= 10 and not shut["scrolls"], f"no scrollbar shown, or the page scrolls, so this step would check nothing: {shut}"
                other.locator(f"{first} .piece-row").first.click()
                other.wait_for_selector("dialog#piece[open] #piece-title")
                opened = other.evaluate(where)
                other.locator("dialog#piece .sheet-close").click()
                other.wait_for_selector("dialog#piece:not([open])", state="attached")
                closed = other.evaluate(where)
                assert opened["edges"] == shut["edges"] == closed["edges"], \
                    f"the page behind the pop-up moved sideways: shut {shut['edges']}, open {opened['edges']}, closed again {closed['edges']}"
                context.close()
            finally:
                shown.close()

        def arrows_move():
            def shown() -> int:
                return page.evaluate("() => { const r = document.getElementById('reel'); return Math.round(r.scrollLeft / r.clientWidth); }")

            def wait_for_outfit(index: int):
                try:
                    page.wait_for_function("i => { const r = document.getElementById('reel'); "
                                           "return Math.round(r.scrollLeft / r.clientWidth) === i; }", arg=index, timeout=5000)
                except Exception:  # noqa: BLE001
                    raise AssertionError(f"outfit {index + 1} should be on screen; it is outfit {shown() + 1}") from None

            page.goto(base + "/outfits", wait_until="networkidle")
            assert page.locator(".reel-nav.prev").is_disabled(), "the back arrow is live on the first outfit"
            page.locator(".reel-nav.next").click()
            wait_for_outfit(1)
            page.keyboard.press("ArrowRight")
            wait_for_outfit(2)
            page.locator(".reel-nav.prev").click()
            wait_for_outfit(1)

        def arrows_for_every_mouse_and_your_place_kept():
            # With a mouse the arrows show at every width (a touch screen swipes, see the phone's first screen), and on a
            # computer they sit beside the outfit: within 48px of the picture's left edge and of the list's right edge,
            # centred on the picture. With "reduce motion" asked for, Next shows the next outfit at once, without
            # sliding, and no outfit fades as the row moves. The outfit on screen is kept in the address without a new
            # step in the history, so Back from 'Buy this outfit' and a reload come back to it.
            def shown() -> int:
                return page.evaluate("() => { const r = document.getElementById('reel'); return Math.round(r.scrollLeft / r.clientWidth); }")

            def wait_for_outfit(index: int, after: str):
                try:
                    page.wait_for_function("i => { const r = document.getElementById('reel'); "
                                           "return Math.round(r.scrollLeft / r.clientWidth) === i; }", arg=index, timeout=5000)
                except Exception:  # noqa: BLE001
                    raise AssertionError(f"{after}, outfit {index + 1} should be on screen; it is outfit {shown() + 1}") from None

            try:
                page.set_viewport_size({"width": 700, "height": 800})
                page.goto(base + "/outfits", wait_until="networkidle")
                both = page.evaluate("""() => [...document.querySelectorAll('.reel-nav')].map(b => { const r = b.getBoundingClientRect();
                    return getComputedStyle(b).display !== 'none' && r.width >= 44 && r.left >= 0 && r.right <= innerWidth; })""")
                assert both == [True, True], f"in a 700px window with a mouse the two arrows do not both show: {both}"
                page.locator(".reel-nav.next").click()
                wait_for_outfit(1, "in a 700px window, after Next")

                page.set_viewport_size({"width": 1280, "height": 900})
                page.goto(base + "/outfits", wait_until="networkidle")
                near = page.evaluate("""() => {
                    const box = s => document.querySelector(s).getBoundingClientRect(), middle = r => (r.top + r.bottom) / 2;
                    const picture = box('#reel .slide .collage'), list = box('#reel .slide .about');
                    const prev = box('.reel-nav.prev'), next = box('.reel-nav.next');
                    return {prev: picture.left - prev.right, next: next.left - list.right,
                            off_centre: Math.max(Math.abs(middle(prev) - middle(picture)), Math.abs(middle(next) - middle(picture)))};
                }""")
                assert 0 <= near["prev"] <= 48 and 0 <= near["next"] <= 48 and near["off_centre"] <= 2, \
                    f"at 1280 x 900 the arrows are not beside the outfit (px from the picture, from the list, off its middle): {near}"

                page.emulate_media(reduced_motion="reduce")
                seen = page.evaluate("""() => new Promise(done => {
                    const reel = document.getElementById('reel'), seen = [Math.round(reel.scrollLeft)];
                    document.querySelector('.reel-nav.next').click();
                    let n = 0;
                    const every = setInterval(() => { seen.push(Math.round(reel.scrollLeft)); if (++n === 25) { clearInterval(every); done(seen); } }, 30);
                })""")
                width = page.evaluate("() => document.getElementById('reel').clientWidth")
                assert sorted(set(seen)) == [0, width], \
                    f"with reduced motion Next slides the row (positions every 30 ms: {sorted(set(seen))}), not one step to {width}"
                # Nor does an outfit fade or step back as the row moves (app.css "Motion"), on either side of the move.
                faded = page.evaluate("() => [...document.querySelectorAll('#reel .slide > *')].filter(el => "
                                      "getComputedStyle(el).animationName !== 'none').length")
                assert faded == 0, f"with reduced motion {faded} parts of outfits still fade as the row moves"
            finally:
                page.emulate_media(reduced_motion="no-preference")
                page.set_viewport_size({"width": 1280, "height": 860})

            page.goto(base + "/outfits", wait_until="networkidle")
            steps = page.evaluate("history.length")
            for index in (1, 2):
                page.locator(".reel-nav.next").click()
                wait_for_outfit(index, "after Next")
            third = page.locator("#reel [data-slide]").nth(2)
            page.wait_for_function("id => location.hash === '#' + id", arg=third.get_attribute("id"))
            assert page.evaluate("history.length") == steps, "moving between outfits added steps to the browser's history"
            count = third.locator(".count").inner_text().strip()
            assert count.startswith("3 / "), f"the third outfit counts itself {count!r}"
            third.locator(".about-actions a").click()
            page.wait_for_url("**/outfits/buy?**")
            page.go_back(wait_until="networkidle")
            wait_for_outfit(2, "back from 'Buy this outfit'")
            assert page.locator("#reel [data-slide]").nth(2).locator(".count").inner_text().strip() == count, "Back shows another outfit"
            page.reload(wait_until="networkidle")
            wait_for_outfit(2, "after a reload")

        def the_outfit_row_by_keyboard():
            # By keyboard: from the top of the page, Tab reaches Next within 15 presses (the arrows come before the
            # outfits). With focus on outfit 1's 'Buy this outfit', → shows outfit 2 and focus goes with it, so that
            # Enter buys the outfit on screen, not the one left behind; a screen reader hears which outfit is shown,
            # from the page's live region. "Add to my wardrobe" pressed with Enter brings the page back saying what was
            # added, in view, and its Undo pressed with Enter takes the outfit out again. Escape hides a dot's label, until a dot is pointed at again.
            # Tab after moving the row leads into the outfit moved to, which stays on screen (only the outfit on screen
            # is in the Tab order; the browser would scroll the row back to an outfit that Tab reached), and so does
            # Shift+Tab from below the row. At the end of the row Next keeps focus: it says it can go no further
            # instead of being switched off, which would drop focus to the page.
            slides = page.locator("#reel [data-slide]")

            def where() -> dict:
                return page.evaluate("""() => { const all = [...document.querySelectorAll('#reel [data-slide]')];
                    const s = document.activeElement.closest('#reel [data-slide]'), r = document.getElementById('reel');
                    return {focus_in: s ? all.indexOf(s) + 1 : 0, shown: Math.round(r.scrollLeft / r.clientWidth) + 1}; }""")

            def at_rest(index: int, after: str):
                # The row is on outfit `index` (0 first), and stays there for longer than app.js waits to call it at rest.
                try:
                    page.wait_for_function("i => { const r = document.getElementById('reel'); "
                                           "return Math.round(r.scrollLeft / r.clientWidth) === i; }", arg=index, timeout=5000)
                except Exception:  # noqa: BLE001
                    raise AssertionError(f"{after}, outfit {index + 1} should be on screen; it is {where()}") from None
                page.wait_for_timeout(500)

            try:
                page.set_viewport_size({"width": 1280, "height": 900})
                page.goto(base + "/outfits", wait_until="networkidle")
                for presses in range(1, 16):
                    page.keyboard.press("Tab")
                    if page.evaluate("() => document.activeElement.matches('.reel-nav.next')"):
                        break
                else:
                    raise AssertionError("from the top of Outfits, 15 Tab presses do not reach Next")
                for index in (1, 2, 3):
                    page.keyboard.press("Enter")
                    at_rest(index, f"after Enter {index} times on Next")
                page.keyboard.press("Tab")
                at_rest(3, "after Next three times and then Tab")
                assert where() == {"focus_in": 4, "shown": 4}, \
                    f"after Next three times, Tab should lead into outfit 4 and keep it on screen: {where()}"
                assert page.evaluate("() => location.hash") == "#" + slides.nth(3).get_attribute("id"), \
                    "after Tab into outfit 4, the address no longer keeps outfit 4"
                page.locator(".site-foot a").first.focus()
                page.keyboard.press("Shift+Tab")
                at_rest(3, "after Shift+Tab from the footer")
                assert where() == {"focus_in": 4, "shown": 4}, \
                    f"Shift+Tab from below the row should lead into the outfit on screen, outfit 4: {where()}"
                last = slides.count() - 1
                page.evaluate("i => { const r = document.getElementById('reel'); r.style.scrollBehavior = 'auto'; "
                              "r.scrollLeft = i * r.clientWidth; r.style.scrollBehavior = ''; }", last - 1)
                at_rest(last - 1, "after the row was moved to the one before the last")
                page.locator(".reel-nav.next").focus()
                page.keyboard.press("Enter")
                at_rest(last, "after Next to the end of the row")
                end = page.evaluate("() => ({on_next: document.activeElement.matches('.reel-nav.next'), "
                                    "says: document.querySelector('.reel-nav.next').getAttribute('aria-disabled')})")
                assert end == {"on_next": True, "says": "true"}, \
                    f"at the end of the row Next should keep focus and say it can go no further: {end}"
                page.keyboard.press("Enter")
                page.keyboard.press("Tab")
                at_rest(last, "after Enter on Next at the end of the row, and Tab")
                assert where() == {"focus_in": last + 1, "shown": last + 1}, \
                    f"Tab from Next at the end of the row should lead into the last slide, on screen: {where()}"

                page.goto(base + "/outfits", wait_until="networkidle")
                buy_second = slides.nth(1).locator(".about-actions a").get_attribute("href")
                slides.nth(0).locator(".about-actions a").focus()
                page.keyboard.press("ArrowRight")
                inside = page.evaluate("""() => { const s = document.activeElement.closest('#reel [data-slide]');
                    return s ? [...document.querySelectorAll('#reel [data-slide]')].indexOf(s) + 1 : 0; }""")
                assert inside == 2, f"after → from outfit 1's 'Buy this outfit', focus is in outfit {inside or 'none'}, not in outfit 2"
                heard = page.wait_for_function("""() => { const words = document.getElementById('announce').textContent;
                    return words.startsWith('Outfit 2 of ') && words; }""").json_value()
                named = slides.nth(1).evaluate("""s => `${s.getAttribute('aria-label')}, ${s.querySelector('.about-head h2').firstChild.textContent.trim()}, `
                    + s.querySelector('.board-cost').textContent.trim()""")
                assert heard == named, f"after →, a screen reader hears {heard!r}, not the outfit on screen ({named!r})"
                assert page.evaluate("() => Math.round(reel.scrollLeft / reel.clientWidth)") == 1, "outfit 2 is not on screen"
                page.keyboard.press("Enter")
                page.wait_for_url("**/outfits/buy?**")
                assert page.url.endswith(buy_second), "Enter after → opened another outfit's Buy page than the one on screen"

                page.goto(base + "/outfits", wait_until="networkidle")
                # "Add to my wardrobe" pressed with Enter: the page comes back saying what was added, in view, and Undo
                # pressed with Enter takes the outfit out again (the walk-through adds one later). The button is called by
                # its own words.
                yes_button = page.locator(f"{first} .btn.yes")
                # ("Save to My outfits" where every piece of it is his already: review N6.)
                called = yes_button.inner_text().split("+")[0].strip()
                assert called in ("Add to my wardrobe", "Save to My outfits") and not yes_button.get_attribute("aria-label"), \
                    f"the yes is called {yes_button.inner_text()!r}, or by a label that says something else"
                yes_button.focus()
                page.keyboard.press("Enter")
                page.wait_for_url("**added=*")
                in_view("main > .said", "Added outfit " if called == "Add to my wardrobe" else "Saved outfit ")
                page.locator("main > .said button:has-text('Undo')").focus()
                page.keyboard.press("Enter")
                page.wait_for_url("**removed=*")
                in_view("main > .said", "Took the outfit with the ")
                assert page.locator(f"{first} .btn.yes").inner_text().startswith(called), "after Undo the outfit is not on offer again, first"
                page.goto(base + "/outfits", wait_until="networkidle")

                page.wait_for_selector(f"{first} .look-pic img")       # the dots show on the picture (drawn by itself)
                dot = page.locator(f"{first} .spot").first
                assert re.fullmatch(r"[^,]+, ((COS|Weekday|Zara), [\d.,]+\s€|owned)", dot.get_attribute("aria-label") or "") \
                    and dot.get_attribute("title") is None, f"a dot is named {dot.get_attribute('aria-label')!r}, with a tooltip"
                dot.focus()
                assert dot.locator(".tip").is_visible(), "a dot with keyboard focus shows no label"
                page.keyboard.press("Escape")
                assert not dot.locator(".tip").is_visible(), "Escape does not hide the label of a dot with keyboard focus"
                dot.hover()
                assert dot.locator(".tip").is_visible(), "after Escape, pointing at a dot does not show its label again"
            finally:
                page.set_viewport_size({"width": 1280, "height": 860})

        def save_and_buy():
            # "Add to my wardrobe" on an outfit; then, under "My outfits", its "Buy this outfit".
            page.goto(base + "/outfits", wait_until="networkidle")
            page.locator(f"{first} .btn.yes").click()
            page.wait_for_url("**added=*")
            page.goto(base + "/outfits?occasion=saved", wait_until="networkidle")
            page.locator(f"{first} .about-actions a").first.click()
            page.wait_for_load_state("networkidle")
            assert "/outfits/buy" in page.url, f"'Buy this outfit' under My outfits led to {page.url}"
            assert "not in your wardrobe yet" not in page.locator("main").inner_text(), "the Buy page of an outfit he added says it is not in his wardrobe"
            assert page.locator(".buy").count() >= 2, "the buy page lists nothing"
            words = page.locator("main").inner_text()
            assert "checkout" in words, "it does not say how buying works"
            assert "VAT" in words and "delivery" in words, "it does not say what the prices include and leave out"
            assert page.locator("#summary").count() == 0, "the wardrobe's budget bar is on the outfit's Buy page"
            assert page.locator(".buy").count() == page.locator(".buy .pic").count(), "a line has no photo or swatch"
            # He skipped his sizes in the welcome: the page says so in a plain line before he orders, with the sizes
            # every line is in, the way to give his, and a button to say these are his.
            sizes = page.locator(".your-sizes")
            assert "You have not given your sizes yet" in sizes.inner_text() and "our example size: Tops M" in sizes.inner_text() \
                and "Your sizes:" not in sizes.inner_text(), f"sizes he never gave are said as: {sizes.inner_text()!r}"
            assert not page.locator(".your-sizes.example").count(), "the line about his sizes is a coloured box again"
            change = sizes.locator("a[href$='#sizes']").bounding_box()
            assert change["height"] >= 24, f"'Give your sizes' is {change['height']:.1f}px tall: under 24px to tap"
            buy_page = page.url
            sizes.locator("button:has-text('These are my sizes')").click()
            page.wait_for_load_state("networkidle")
            assert page.url == buy_page, "keeping the sizes leaves the Buy page"
            assert "Your sizes: Tops M" in page.locator(".your-sizes").inner_text(), "the sizes are no longer said"
            assert "example size" not in page.locator("main").inner_text(), "the line about example sizes stays after 'These are my sizes'"
            page.goto(base + "/outfits?occasion=saved", wait_until="networkidle")
            assert page.locator("#reel .slide").count() == 1, "the outfit he added is not under My outfits"
            assert page.locator(".reel-nav").count() == 0, "a single saved outfit has arrows that lead nowhere"

        def a_stores_pages_open_one_by_one():
            # "Open all 2 at COS" opened the first page and lost the rest: a browser lets a site open one new tab per
            # tap and holds the others back as pop-ups (the test browser usually has that switched off: here it is
            # on, as it is for a customer). The button is a plain link to the next page not yet opened, so every tap
            # opens exactly one tab: the right one, its line ticked, and the count said. No store's site is asked.
            # The whole Chromium, not the cut-down one the other steps use: only it has a pop-up blocker to switch on.
            real = p.chromium.launch(channel="chromium", ignore_default_args=["--disable-popup-blocking"])
            context = real.new_context(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
            try:
                context.route(lambda url: not url.startswith(base), lambda route: route.fulfill(
                    body="<title>A store's page</title>", content_type="text/html"))
                other = context.new_page()
                other.set_default_timeout(15000)
                other.goto(base + "/login", wait_until="networkidle")
                other.fill("input[name=email]", EMAIL)
                other.fill("input[name=password]", PASSWORD)
                other.locator("main form button").click()
                other.wait_for_load_state("networkidle")
                other.goto(base + "/list", wait_until="networkidle")
                # The blocker really is on: a second tab asked for by script in one tap is held back.
                second = other.evaluate("() => { const one = window.open('about:blank'); const two = window.open('about:blank');"
                                        " if (one) one.close(); return Boolean(two); }")
                assert not second, "this browser lets a page open two tabs at once: the step proves nothing"
                # Said first, so that a failure here names its cause rather than a button waited for in vain.
                assert other.locator(".store-list [data-open-next]").count(), \
                    "no store has a button that opens its pages one by one: the page still opens them all in one tap (" \
                    + (other.locator(".open-all").first.inner_text().strip() if other.locator(".open-all").count() else "no button at all") \
                    + "), which a browser's pop-up blocker cuts down to the first page"
                store = other.locator(".store-list").filter(has=other.locator("[data-open-next]")).first
                button = store.locator("[data-open-next]").first     # under the store's name; the same again after its last line
                after = store.locator("[data-open-next]").last
                name = button.get_attribute("data-store")
                pages = store.locator("a.buy-go").evaluate_all("links => links.map(a => a.href)")
                total = len(pages)
                assert total >= 2, "the example list has no store with two products"
                assert "Open all" not in other.locator("main").inner_text(), "the page still promises to open all at once"
                assert button.inner_text().strip().startswith(f"Open the first of {total} at {name}"), \
                    f"the button says '{button.inner_text().strip()}'"
                assert store.locator(".buy-opened:visible").count() == 0, "a line is ticked before anything was opened"
                size = button.bounding_box()
                assert size["height"] >= 24, f"the button is {size['height']:.0f}px tall: under 24px to tap"
                # Each line's own main action (review N1): "Open at <store>, order <size>", an ink button at least 44px
                # tall across the whole row, under the store's own button, which comes again after the last line.
                rows = other.evaluate("""() => [...document.querySelectorAll('.store-list:not(.sold-list) .buy')].map(row => {
                    const go = row.querySelector('.buy-go'); if (!go) return null; const b = go.getBoundingClientRect(), r = row.getBoundingClientRect();
                    return {text: go.innerText.trim(), height: b.height, whole: Math.abs(b.width - r.width) < 1, ink: getComputedStyle(go).backgroundColor}; })""")
                assert rows and all(rows), f"a line of the list has no button to its store: {rows}"
                for row in rows:
                    assert re.match(r"Open at \w+, (order |choose your size)", row["text"]) and row["height"] >= 44 and row["whole"], \
                        f"a line's button: {row}"
                assert store.locator("[data-open-next]").count() == 2, "the store's 'Open the first of' is not there twice"
                for number, address in enumerate(pages, start=1):
                    before = len(context.pages)
                    with context.expect_page() as opened:
                        button.tap()
                    tab = opened.value
                    tab.wait_for_load_state()
                    assert tab.url == address, f"tap {number} opened {tab.url}, not {address}"
                    other.wait_for_timeout(300)
                    assert len(context.pages) == before + 1, f"tap {number} opened {len(context.pages) - before} tabs, not one"
                    other.bring_to_front()
                    other.wait_for_function("n => document.querySelectorAll('.store-list .buy-opened:not([hidden])').length >= n", arg=number)
                    ticks = store.locator(".buy").evaluate_all("lines => lines.map(line => !line.querySelector('.buy-opened').hidden)")
                    assert ticks == [at < number for at in range(total)], \
                        f"after tap {number} the ticked lines are {ticks}: not the first {number} and only those"
                    said = store.locator("[data-open-status]").first.inner_text()
                    assert after.inner_text() == button.inner_text(), "the store's two buttons say different things"
                    if number < total:
                        assert f"{number} of {total} opened" in said, f"after tap {number} it says '{said}'"
                        # Said for a finger and for a mouse alike: neither "tap" nor "click".
                        assert "Each press opens one more" in said and not re.search(r"\b(tap|click)", said, re.I), \
                            f"after tap {number} it says '{said}': not 'Each press opens one more', which fits a finger and a mouse"
                        assert button.inner_text().strip().startswith(f"Open the next at {name}"), "the button does not offer the next"
                    else:
                        assert f"All {total} opened" in said, f"after the last tap it says '{said}'"
                        # Nothing is left to open: the button says what it does now, and names no new tab.
                        assert button.inner_text().strip() == "Start again", \
                            f"after all {total} were opened the button says '{button.inner_text().strip()}', not 'Start again'"
                # A product's own link ticks its line too, and the ticks are still there after a look at another page.
                lone = other.locator(".store-list").filter(has_not=other.locator("[data-open-next]")).locator("a.buy-go").first
                if lone.count():
                    with context.expect_page():
                        lone.tap()
                    other.bring_to_front()
                    other.wait_for_function("n => document.querySelectorAll('.buy-opened:not([hidden])').length > n", arg=total)
                other.goto(base + "/outfits", wait_until="networkidle")
                other.goto(base + "/list", wait_until="networkidle")
                assert other.locator(".store-list").filter(has=other.locator("[data-open-next]")).first \
                    .locator(".buy-opened:visible").count() >= total, "the ticks are gone after a look at another page"
                wide, screen = other.evaluate("() => [document.documentElement.scrollWidth, innerWidth]")
                assert wide <= screen, f"the list with its ticks is {wide}px wide on a {screen}px phone"
                # "Start again" opens nothing: only then do that store's ticks go, and the button offers the first again.
                store = other.locator(".store-list").filter(has=other.locator("[data-open-next]")).first
                button = store.locator("[data-open-next]").first
                assert button.inner_text().strip() == "Start again", "back on the list, the button no longer says 'Start again'"
                before = len(context.pages)
                button.tap()
                other.wait_for_function("() => !document.querySelector('.store-list [data-open-next]').closest('.store-list')"
                                        ".querySelector('.buy-opened:not([hidden])')")
                other.wait_for_timeout(400)
                assert len(context.pages) == before, "'Start again' opened a store's page"
                assert button.inner_text().strip().startswith(f"Open the first of {total} at {name}"), \
                    f"after 'Start again' the button says '{button.inner_text().strip()}'"
                assert store.locator("[data-open-status]").first.inner_text().strip() == "", "after 'Start again' it still says how many are open"
                with context.expect_page() as opened:                 # and it works again from the first
                    button.tap()
                assert opened.value.url == pages[0], f"after 'Start again' the button opened {opened.value.url}, not the first page"
            finally:
                context.close()
                real.close()

        def list_prints_without_photos():
            # On paper the shopping list is words and links: the photos would only use ink.
            page.goto(base + "/list", wait_until="networkidle")
            lines = page.locator(".buy")
            assert lines.count() >= 2 and page.locator(".buy .pic").count() == lines.count(), "a line has no photo"
            assert page.locator(".buy .pic").first.is_visible(), "the list shows no photos on the screen"
            # On a phone every download and print button shows whole: none is squeezed beside the lead line or
            # cut off at the screen's edge (the Outfits toolbar's sideways-scrolling row once did that here).
            for width in (320, 390):
                page.set_viewport_size({"width": width, "height": 860})
                for button in page.locator(".list-tools .btn").all():
                    box = button.bounding_box()
                    assert box and box["x"] >= 0 and box["x"] + box["width"] <= width, \
                        f"{button.inner_text()!r} is cut off on a {width}px phone: {box}"
            page.set_viewport_size({"width": 1280, "height": 860})
            page.emulate_media(media="print")
            try:
                assert not any(pic.is_visible() for pic in page.locator(".buy .pic").all()), "photos are printed"
                assert page.locator(".buy .row-product").first.is_visible(), "the product names are not printed"
                assert "https://" in page.locator(".buy-go").first.evaluate("a => getComputedStyle(a, '::after').content"), \
                    "the product's address is not printed"
                assert not page.locator("#summary").is_visible(), "the budget bar is printed"
            finally:
                page.emulate_media(media="screen")

        def my_model():
            # The model is put together in Profile's Body tab and kept with the one Save. A change to the model alone
            # is saved as the model's own button did: said beside the model, the rest of the profile left as it was.
            page.goto(base + "/profile", wait_until="networkidle")
            open_tab(page, "body")
            for group, value in (("age", "30s"), ("build", "athletic"), ("hair", "brown"), ("cut", "short")):
                page.locator(f'.pick input[name="{group}"][value="{value}"]').check(force=True)
            assert page.locator("[data-figure-words]").inner_text() == "180 cm, athletic build, any skin tone, short brown hair", \
                f"the figure is said as {page.locator('[data-figure-words]').inner_text()!r}"
            page.click("button:has-text('Save profile')")
            page.wait_for_load_state("networkidle")
            assert page.url.endswith("/profile#model"), f"the model was saved to {page.url}"
            expect(page.locator("#tab-body")).to_have_attribute("aria-selected", "true")
            assert page.locator("[data-figure-words]").inner_text().startswith("180 cm, athletic build"), "the figure forgot the model"
            words = page.locator("#model").inner_text()
            assert "in his thirties" in words and "athletic build" in words, "the choices are not described back"
            in_view("#model .flash", "Model saved")
            before = len(asked)
            page.locator("#model .flash a", has_text="See your outfits").click()    # one tap from the message
            page.wait_for_url(base + "/outfits")
            page.wait_for_load_state("networkidle")
            page.wait_for_selector(f"{first} .look-pic img")
            assert len(asked) > before and "in his thirties" in asked[-1]["prompt"], "the new model was not drawn"

        def the_body_reaches_the_pictures():
            # The body on Profile (height, weight, chest, waist under Sizes) is what the AI pictures are asked for, in
            # words and never as numbers; the drawn figure takes the same build as it is typed, and is called a sketch.
            # A new body draws new pictures; back at the old body, the old pictures are there again without drawing.
            # (The customer of a_pieces_words_tidy_at_320, who has only looked at his wardrobe and list: his Profile
            # still holds the example's values, nobody else's Profile changes, and no sign-up is used up, of which
            # one address gets ten an hour.)
            context = browser.new_context(viewport={"width": 1280, "height": 860})
            try:
                other = context.new_page()
                other.on("response", lambda r: failures.append(f"{r.status} {r.request.method} {r.url.replace(base, '')[:100]}")
                         if r.status >= 400 and r.url.startswith(base) and "does-not-exist" not in r.url else None)
                other.on("pageerror", lambda e: failures.append(f"script error: {e}"))
                other.goto(base + "/login", wait_until="networkidle")
                other.fill("input[name=email]", "words-" + EMAIL)
                other.fill("input[name=password]", PASSWORD)
                other.click("button:has-text('Log in')")
                other.wait_for_url(base + "/outfits")
                other.wait_for_selector(f"{first} .look-pic img")
                old_picture = other.get_attribute(f"{first} .look-pic img", "src")

                other.goto(base + "/profile", wait_until="networkidle")
                figure_words = other.locator("[data-figure-words]")
                expect(figure_words).to_have_text("180 cm, any build, any skin tone, any hair")
                note = other.locator("[data-figure-note]")
                expect(note).to_be_visible()
                assert note.inner_text() == "This is a sketch. The AI pictures on Outfits follow the same body.", \
                    f"under the figure: {note.inner_text()!r}"
                box = other.evaluate("""() => { const n = document.querySelector('[data-figure-note]').getBoundingClientRect(),
                    w = document.querySelector('[data-figure-words]').getBoundingClientRect(),
                    s = document.querySelector('.cc-stage').getBoundingClientRect();
                    return {under: n.top > w.top + 10 && n.bottom > w.bottom, inside: n.bottom <= s.bottom + 1}; }""")
                assert box == {"under": True, "inside": True}, f"the sketch note's place: {box}"
                open_tab(other, "body")
                said = other.locator("#model").inner_text()
                assert "These words go to OpenAI with each picture" in said and "never as numbers" in said, \
                    "the Body tab does not say what goes to the image service"
                average = other.evaluate("document.querySelector('[data-figure] [data-part=tee]').getAttribute('d')")

                open_tab(other, "sizes")
                assert "They go to OpenAI with each picture as a few words about your body" in other.locator("#panel-sizes").inner_text(), \
                    "the measurements do not say that they reach the image service as words"
                other.fill("input[name=height_cm]", "172")
                other.fill("input[name=weight_kg]", "95")
                expect(figure_words).to_have_text("172 cm, heavy build, any skin tone, any hair")
                other.wait_for_function(STILL)
                other.wait_for_timeout(300)
                heavy = other.evaluate("document.querySelector('[data-figure] [data-part=tee]').getAttribute('d')")
                assert heavy != average, "the drawn figure did not take the build of the new weight"
                before = len(asked)
                other.click("button:has-text('Save profile')")
                other.wait_for_url(base + "/outfits")
                other.wait_for_load_state("networkidle")
                assert "Your model now follows your new measurements" in " ".join(other.locator("main > .flash").all_inner_texts()), \
                    "the save does not say that the pictures follow the new body"
                other.wait_for_selector(f"{first} .look-pic img")
                new_picture = other.get_attribute(f"{first} .look-pic img", "src")
                assert new_picture != old_picture, "the new body shows the old body's picture"
                sent = [one["prompt"].split("\n")[0] for one in asked[before:]]
                assert sent, "no picture was asked for with the new body"
                for line in sent:
                    assert "an adult man (a little shorter than average, heavy build with a full stomach)" in line, \
                        f"the picture was asked for as: {line[:200]!r}"
                    assert "172" not in line and "95" not in line, "a measurement was sent as a number"

                # The page drew the figure from the same rule as the server: after the save it says and draws the same.
                other.goto(base + "/profile", wait_until="networkidle")
                expect(figure_words).to_have_text("172 cm, heavy build, any skin tone, any hair")
                assert other.evaluate("document.querySelector('[data-figure] [data-part=tee]').getAttribute('d')") == heavy, \
                    "the server and the page draw different figures for the same body"
                open_tab(other, "body")
                assert "Described to the AI as: “an adult man (a little shorter than average, heavy build with a full stomach)”" \
                    in other.locator("#model").inner_text(), "the words that are sent are not shown"
                # A build chosen in the menu wins over the one worked out, in the figure at once.
                other.locator('.pick input[name="build"][value="slim"]').check(force=True)
                expect(figure_words).to_have_text("172 cm, slim build, any skin tone, any hair")
                other.locator('.pick input[name="build"][value=""]').check(force=True)
                expect(figure_words).to_have_text("172 cm, heavy build, any skin tone, any hair")

                # Back to the body he had: the picture he had, and nothing is drawn again.
                open_tab(other, "sizes")
                other.fill("input[name=height_cm]", "180")
                other.fill("input[name=weight_kg]", "78")
                expect(figure_words).to_have_text("180 cm, any build, any skin tone, any hair")
                before = len(asked)
                other.click("button:has-text('Save profile')")
                other.wait_for_load_state("networkidle")
                other.goto(base + "/outfits", wait_until="networkidle")
                other.wait_for_selector(f"{first} .look-pic img")
                assert other.get_attribute(f"{first} .look-pic img", "src") == old_picture, "the old body's picture is not back"
                again = [one["prompt"] for one in asked[before:] if one in asked[:before]]
                assert not again, "a picture he already had was drawn again"
            finally:
                context.close()

        def my_photo():
            chosen = "[data-photo-form] input[type=file]"
            note = "[data-photo-form] [data-photo-ready]"
            page.goto(base + "/profile", wait_until="networkidle")

            # A file the browser cannot open as a picture, named like an iPhone's photo: said at once, nothing sent.
            unreadable = HOME / "IMG_0042.HEIC"
            unreadable.write_bytes(os.urandom(4000))
            page.set_input_files(chosen, str(unreadable))
            page.wait_for_selector(f"{note}.bad")
            assert "HEIC" in page.locator(note).inner_text(), "it does not say why the photo cannot be used"
            assert page.eval_on_selector(chosen, "i => i.files.length") == 0, "the unreadable file is still chosen and would be sent"

            photo = HOME / "me.png"
            photo.write_bytes(picture(900, 1200, (180, 150, 130)))
            page.set_input_files(chosen, str(photo))
            page.wait_for_function("() => document.querySelector('[data-photo-form] input[type=file]').files[0].type === 'image/jpeg'")
            page.wait_for_selector(f"{note}:not(.bad) img:not([hidden])")
            assert "ready" in page.locator(note).inner_text(), "it does not say that the photo is ready to send"
            page.check("[data-photo-form] input[name=agree]")
            page.click("[data-photo-form] button")
            page.wait_for_load_state("networkidle")
            assert page.locator(".me img").count() == 1, "the photo is not shown back: " + " / ".join(page.locator(".flash").all_inner_texts())
            shows(".me img", "the photo")
            in_view("#photo .flash", "Photo saved")
            page.locator("#photo .flash a", has_text="See your outfits").click()
            page.wait_for_url(base + "/outfits")
            page.wait_for_load_state("networkidle")
            page.wait_for_selector(f"{first} .look-pic img")
            assert asked[-1]["photo"], "the photo did not go with the request"
            assert asked[-1]["photo"][:3] == b"\xff\xd8\xff", "the page did not turn the photo into a small JPEG first"

            # He added this photo under today's words, which say that an outfit's further photos are made from the AI
            # picture of him. A customer who added his photo under the older words (their date is put beside the
            # photo here, as it is stored for such a customer) is asked once, plainly, under the picture, before
            # the first "More photos" sends that picture to the image service again. Nothing is sent before his
            # yes; "Not now" leaves everything as it is, with keyboard focus back on "More photos"; after "Yes, draw
            # them" the five are made from the picture of him, not from his photo, and the question is gone.
            with db.connect() as con:
                con.execute("DELETE FROM look_requests")            # a new day: the five fit, whatever was drawn before
                con.execute("UPDATE settings SET value = ? WHERE key = 'photo_consent' "
                            "AND user_id = (SELECT id FROM users WHERE email = ?)", ('"2026-11-12"', EMAIL))
            mine = say_yes(page)        # "More photos" is offered on an outfit he said yes to
            page.goto(base + f"/outfits?at={mine}", wait_until="networkidle")
            page.wait_for_selector(f"{first} .look-pic img")
            before = len(asked)
            more = f"{first} .shots-row button:has-text('More photos')"
            page.click(more)
            page.wait_for_selector(f"{first} .look-ask")
            question = page.inner_text(f"{first} .look-ask p")
            assert question == (f"These photos are made from the AI picture of you, which goes to {looks.service().label} "
                                "again. Is that OK from now on, for all your outfits?"), \
                f"'More photos' of a photo added under the older words asks {question!r}"
            answers = page.evaluate("s => [...document.querySelectorAll(s + ' .look-ask button')].map(b => [b.textContent.trim(), b.getBoundingClientRect().height])", first)
            assert [words for words, _ in answers] == ["Yes, draw them", "Not now"] and all(height >= 40 for _, height in answers), \
                f"the answers to the question are {answers}"
            assert page.evaluate("() => document.activeElement.textContent.trim()") == "Yes, draw them", \
                "keyboard focus is not on the question's answer"
            expect(page.locator(f"{first} .look-ask button").last, "the question and its answers show on the screen").to_be_in_viewport()
            assert len(asked) == before and page.locator(f"{first} .shots-row img").count() == 1, \
                "'More photos' sent the picture of him before he answered"
            page.click(f"{first} .look-ask button:has-text('Not now')")
            page.wait_for_selector(f"{first} .look-ask", state="detached")
            assert len(asked) == before and page.locator(f"{first} .shots-row img").count() == 1, "'Not now' sent something"
            assert page.evaluate("() => document.activeElement.textContent.trim()") == "More photos", \
                "after 'Not now' keyboard focus is not back on 'More photos'"
            page.click(more)
            page.wait_for_selector(f"{first} .look-ask")
            page.click(f"{first} .look-ask button:has-text('Yes, draw them')")
            page.wait_for_selector(f"{first} .look-ask", state="detached")
            page.wait_for_function("s => document.querySelectorAll(s + ' .shots-row img').length === 6", arg=first, timeout=60000)
            sent = asked[before:]
            assert len(sent) == 5 and all(not one["photo"] and len(one["references"]) == 1 for one in sent), \
                f"after his yes the five were not each made from the picture of him: {[(bool(one['photo']), len(one['references'])) for one in sent]}"
            assert page.locator(f"{first} .look-pic img").count() == 1 and not page.locator(f"{first} .look-ask").count(), \
                "after his yes the large picture is gone, or the question is still there"
            take_out(page, mine)        # his wardrobe as it was
            page.goto(base + "/profile", wait_until="networkidle")
            page.click("button:has-text('Delete my photo')")
            page.wait_for_load_state("networkidle")
            assert page.locator(".me img").count() == 0, "the photo is still shown after deleting it"

        def unsaved_changes_are_not_lost_silently():
            # Everything on Profile is one form with one Save, the model's choices too; the photo has its own forms,
            # and sending one of them loads the page again, so a change in the form not yet saved would be lost without
            # a word. The page asks first, and only then; told no, it stays as it is. Save itself never asks, and
            # "Draw my model", which does not load the page, says beside it to save first. (A page of its own, to
            # answer the question.)
            question = "You changed your profile but didn't save it. Leave those changes unsaved?"
            said: list[str] = []
            reply = {"leave them": False}
            other = page.context.new_page()

            def answer(dialog):
                if dialog.message != question:          # "Delete your photo …?", the photo's own question
                    dialog.accept()
                    return
                said.append(dialog.message)
                dialog.accept() if reply["leave them"] else dialog.dismiss()

            other.on("dialog", answer)
            other.on("pageerror", lambda e: failures.append(f"script error: {e}"))
            photo = HOME / "me-again.png"
            photo.write_bytes(picture(600, 800, (150, 130, 120)))

            def choose_photo():
                open_tab(other, "you")
                other.set_input_files("[data-photo-form] input[type=file]", str(photo))
                other.wait_for_selector("[data-photo-form] [data-photo-ready]:not(.bad) img:not([hidden])")
                other.check("[data-photo-form] input[name=agree]")

            try:
                other.goto(base + "/profile", wait_until="networkidle")
                choose_photo()
                other.click("[data-photo-form] button")
                other.wait_for_load_state("networkidle")
                assert not said, f"'Use this photo' asked although nothing had changed: {said}"
                assert other.locator(".me img").count() == 1, "the photo was not saved"
                other.click("button:has-text('Delete my photo')")
                other.wait_for_load_state("networkidle")

                other.goto(base + "/profile", wait_until="networkidle")
                budget = other.input_value("#budget")
                open_tab(other, "budget")
                other.fill("#budget", str(int(budget) + 111))
                other.evaluate("() => { window.stayed = true; }")
                choose_photo()
                with other.expect_event("dialog"):
                    other.click("[data-photo-form] button")
                assert said == [question], f"with the budget changed, 'Use this photo' asked {said}"
                assert other.evaluate("() => window.stayed === true") and other.locator(".me img").count() == 0, \
                    "told no, the photo was sent all the same"
                assert other.input_value("#budget") == str(int(budget) + 111), "told no, the changed budget is gone"

                # A colour swatch tapped is a change too (the budget back as it was), and so is a choice of the model's.
                open_tab(other, "budget")
                other.fill("#budget", budget)
                pick_colours(other, profile_mod.EXAMPLE["liked"], ["mustard"])
                choose_photo()
                with other.expect_event("dialog"):
                    other.click("[data-photo-form] button")
                assert said == [question, question], f"with a colour changed, 'Use this photo' asked {said[1:]}"
                pick_colours(other, profile_mod.EXAMPLE["liked"])
                open_tab(other, "body")
                build = other.locator('.pick input[name="build"]:checked').get_attribute("value")
                other.locator('.pick input[name="build"][value="heavy"]').check(force=True)
                note = other.locator("[data-model-picture] [data-unsaved-note]")
                if note.count():           # beside "Draw my model", or under "Draw again": it says to save first
                    other.get_by_role("group", name="Show in the middle").get_by_role("button", name="Your model").click()
                    expect(note).to_be_visible()
                choose_photo()
                with other.expect_event("dialog"):
                    other.click("[data-photo-form] button")
                assert said == [question] * 3, f"with the model changed, 'Use this photo' asked {said[2:]}"
                assert other.evaluate("() => window.stayed === true") and other.locator(".me img").count() == 0, \
                    "told no, the photo was sent all the same"

                reply["leave them"] = True        # told yes: the photo is saved, the change above is left unsaved
                other.click("[data-photo-form] button")
                other.wait_for_load_state("networkidle")
                assert len(said) == 4 and other.locator(".me img").count() == 1, "told yes, the photo was not saved"
                assert other.locator('.pick input[name="build"]:checked').get_attribute("value") == build, \
                    "the change left unsaved was saved after all"
                assert other.input_value("#budget") == budget and other.input_value("input[name=refused]") == "", \
                    "the changes left unsaved were saved after all"
                other.click("button:has-text('Delete my photo')")
                other.wait_for_load_state("networkidle")

                # Save never asks: it keeps what was changed. (The model, so that his profile stays the example's,
                # which later steps rely on; a profile saved from a tab comes back to it, see the unit tests.)
                open_tab(other, "body")
                other.locator('.pick input[name="build"][value="slim"]').check(force=True)
                other.click("button:has-text('Save profile')")
                other.wait_for_load_state("networkidle")
                assert len(said) == 4, f"'Save profile' asked {said[4:]}"
                assert other.url.endswith("/profile#model"), f"after Save the page is at {other.url}"
                expect(other.locator("#tab-body")).to_have_attribute("aria-selected", "true")
                assert other.locator('.pick input[name="build"]:checked').get_attribute("value") == "slim", "Save did not keep the model"
                other.locator(f'.pick input[name="build"][value="{build}"]').check(force=True)
                other.click("button:has-text('Save profile')")
                other.wait_for_load_state("networkidle")
                assert len(said) == 4 and other.locator('.pick input[name="build"]:checked').get_attribute("value") == build
            finally:
                other.close()

        def profile_is_a_character_screen():
            # Profile is one screen, like a game's character screen: the model in the middle, the tabs (You, Body,
            # Sizes, Colours, Budget) beside it, one tab's controls at a time and one Save always in view. A new
            # customer (so that his model and his first outfit's picture are new) on a phone, a computer and without
            # JavaScript.
            figure_state = """() => {
                const svg = document.querySelector('[data-figure]'), man = svg.querySelector('.fig-man');
                const part = name => svg.querySelector('.fig-man [data-part="' + name + '"]');
                const box = man.getBoundingClientRect(), tee = part('tee').getBBox();
                return {transform: man.getAttribute('transform'), scale: Number(man.dataset.scale), height: box.height,
                        skin: part('skin').getAttribute('d'), teeWidth: tee.width, hair: part('hair').getAttribute('d'),
                        back: part('hair-back').getAttribute('d'), beard: part('beard').getAttribute('d'),
                        skinFill: getComputedStyle(part('skin')).fill, hairFill: getComputedStyle(part('hair')).fill,
                        words: document.querySelector('[data-figure-words]').textContent};
            }"""
            who = "character-" + EMAIL
            context = browser.new_context(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True,
                                          reduced_motion="reduce")
            try:
                phone = context.new_page()
                phone.on("pageerror", lambda e: failures.append(f"script error: {e}"))
                phone.on("response", lambda r: failures.append(f"{r.status} {r.request.method} {r.url.replace(base, '')[:100]}")
                         if r.status >= 400 and r.url.startswith(base) and "does-not-exist" not in r.url else None)
                phone.goto(base + "/signup", wait_until="networkidle")
                phone.fill("input[name=email]", who)
                phone.fill("input[name=password]", PASSWORD)
                phone.click("button:has-text('Create account')")
                a_customer_from_before(phone)
                phone.goto(base + "/profile", wait_until="networkidle")

                # The tabs: a tablist, the first open, the others' controls hidden.
                tabs = phone.get_by_role("tab")
                assert tabs.all_inner_texts() == ["You", "Body", "Sizes", "Colours", "Budget", "Stores"], \
                    f"the tabs: {tabs.all_inner_texts()}"
                expect(phone.get_by_role("tab", name="You")).to_have_attribute("aria-selected", "true")
                assert phone.locator(".cc-panel:visible").evaluate_all("ps => ps.map(p => p.dataset.tab)") == ["you", "you", "you"], \
                    "other tabs' controls show beside the first tab's"
                # By keyboard: the arrow keys move between the tabs and open them (round from the last to the first),
                # Home and End go to the ends, and Tab goes from the open tab into its controls.
                phone.focus("#tab-you")
                walked = []
                for key in ("ArrowRight", "ArrowRight", "End", "ArrowRight", "ArrowLeft", "Home", "ArrowLeft"):
                    phone.keyboard.press(key)
                    walked.append(phone.evaluate("""() => [document.activeElement.id,
                        document.querySelector('[role=tab][aria-selected=true]').id,
                        [...document.querySelectorAll('.cc-panel')].filter(p => !p.hidden).map(p => p.id).join(' ')]"""))
                expected = [("tab-body", "panel-body"), ("tab-sizes", "panel-sizes"), ("tab-stores", "panel-stores"),
                            ("tab-you", "panel-you style-panel photo-panel"), ("tab-stores", "panel-stores"),
                            ("tab-you", "panel-you style-panel photo-panel"), ("tab-stores", "panel-stores")]
                assert walked == [[tab, tab, panel] for tab, panel in expected], f"the arrow keys went {walked}"
                assert phone.evaluate("location.hash") == "#stores", "the address does not keep the open tab"
                phone.keyboard.press("Tab")
                assert phone.evaluate("() => document.activeElement.closest('.cc-panel').id") == "panel-stores", \
                    "Tab does not go from the open tab into its controls"
                assert phone.evaluate("() => [document.activeElement.name, document.activeElement.value]") == ["stores", "cos"]
                open_tab(phone, "budget")
                phone.keyboard.press("Tab")
                assert phone.evaluate("() => document.activeElement.id") == "budget", "Tab from the Budget tab"

                # On a phone the middle takes about 40% of the screen and stays at the top with the tabs under it while
                # the controls scroll (every tab reaches that far); Save is in view at the bottom, above the tab bar,
                # wherever the controls are: once the page is scrolled to them, and on the first screen whenever the
                # controls' card starts high enough for it. It is never over the tabs: on a first screen where the card
                # starts lower, Save rides on its top edge, under the tabs (a tab tapped there brings the controls up,
                # checked below on three phones).
                def placed() -> dict:
                    return phone.evaluate("""() => {
                        const box = s => document.querySelector(s).getBoundingClientRect();
                        const save = document.querySelector('.cc-save .btn'), b = save.getBoundingClientRect();
                        const top = document.elementFromPoint(b.left + b.width / 2, b.top + b.height / 2);
                        const card = document.querySelector('.cc-side'), bar = document.querySelector('.cc-save');
                        const room = box('.cc-side').top + parseFloat(getComputedStyle(card).borderTopWidth)
                            + parseFloat(getComputedStyle(card).paddingTop) + parseFloat(getComputedStyle(bar).marginTop)
                            + bar.getBoundingClientRect().height;      // where Save's foot is when it rides on the card's top
                        return {stageTop: box('.cc-stage').top, stage: box('.cc-stage').height, tabsTop: box('.cc-tabs').top,
                                tabsBottom: box('.cc-tabs').bottom, saveTop: box('.cc-save').top, saveBottom: b.bottom,
                                saveSeen: save.contains(top), bar: box('nav.tabs').top, h: innerHeight,
                                fits: room <= box('nav.tabs').top, past: scrollY >= document.querySelector('.cc').offsetTop};
                    }""")
                for name in ("you", "body", "sizes", "colours", "budget", "stores"):
                    open_tab(phone, name)
                    for scrolled in (0, 900):
                        phone.evaluate(f"() => window.scrollTo(0, {scrolled})")
                        seen = placed()
                        assert seen["saveTop"] >= seen["tabsBottom"] - 1, f"{name} at {scrolled}: Save is over the tabs {seen}"
                        if seen["past"] or seen["fits"]:
                            assert seen["saveSeen"] and seen["saveBottom"] <= seen["bar"] + 1, f"{name} at {scrolled}: Save is hidden {seen}"
                        if scrolled:
                            assert seen["past"], f"{name}: the page cannot be scrolled to where the middle stays at the top {seen}"
                        if seen["past"]:
                            assert seen["stageTop"] == 0 and abs(seen["tabsTop"] - seen["stage"]) < 1, \
                                f"{name}: the middle and the tabs do not stay at the top {seen}"
                    assert 0.35 * seen["h"] <= seen["stage"] <= 0.45 * seen["h"], f"the middle is {seen['stage']}px of {seen['h']}"
                phone.evaluate("() => window.scrollTo(0, 0)")

                # The figure changes at once for each height, build, skin and hair choice (with "reduce motion" asked
                # for, without moving): measured on the drawing itself.
                open_tab(phone, "body")
                pick = lambda group, value: phone.locator(f'.pick input[name="{group}"][value="{value}"]').check(force=True)  # noqa: E731
                start = phone.evaluate(figure_state)
                assert start["words"] == "180 cm, any build, any skin tone, any hair", f"a new customer's figure: {start['words']!r}"
                heights = {}
                for value in ("short", "medium", "tall"):
                    pick("height", value)
                    heights[value] = phone.evaluate(figure_state)
                assert heights["short"]["height"] < heights["medium"]["height"] < heights["tall"]["height"], \
                    f"the figure's height for Short, Average, Tall: {[heights[v]['height'] for v in heights]}"
                assert len({h["transform"] for h in heights.values()}) == 3
                assert heights["tall"]["words"].startswith("Tall, "), heights["tall"]["words"]
                pick("height", "")                                     # "Any": as tall as the height under Sizes
                open_tab(phone, "sizes")
                own = {}
                for cm in ("150", "180", "210"):
                    phone.fill("input[name=height_cm]", cm)
                    own[cm] = phone.evaluate(figure_state)
                assert own["150"]["height"] < own["180"]["height"] < own["210"]["height"], \
                    f"the figure's height at 150, 180, 210 cm: {[own[c]['height'] for c in own]}"
                assert [own[c]["scale"] for c in own] == [round(int(c) / 180, 4) for c in own], [own[c]["scale"] for c in own]
                assert own["210"]["words"].startswith("210 cm, "), own["210"]["words"]
                phone.fill("input[name=height_cm]", "180")
                open_tab(phone, "body")
                builds = {}
                for value in ("slim", "average", "athletic", "broad", "heavy"):
                    pick("build", value)
                    builds[value] = phone.evaluate(figure_state)
                assert len({b["skin"] for b in builds.values()}) == 5, "two builds draw the same body"
                widths = [round(builds[v]["teeWidth"], 1) for v in ("slim", "average", "athletic", "broad")]
                assert widths == sorted(widths) and len(set(widths)) == 4, f"the shoulders, slim to broad: {widths}"
                assert builds["athletic"]["words"] == "180 cm, athletic build, any skin tone, any hair", builds["athletic"]["words"]
                skins = {}
                for group, options in person.GROUPS.items():
                    if group not in ("skin", "hair"):
                        continue
                    for option in options[1]:
                        pick(group, option.key)
                        seen = phone.evaluate(figure_state)
                        rgb = "rgb({}, {}, {})".format(*(int(option.swatch[i:i + 2], 16) for i in (1, 3, 5)))
                        assert seen["skinFill" if group == "skin" else "hairFill"] == rgb, \
                            f"{group} {option.key}: drawn in {seen['skinFill' if group == 'skin' else 'hairFill']}, not {rgb}"
                        skins[(group, option.key)] = seen["words"]
                assert skins[("hair", "grey")] == "180 cm, heavy build, dark skin, grey hair", skins[("hair", "grey")]
                cuts = {}
                for option in person.GROUPS["cut"][1]:
                    pick("cut", option.key)
                    cuts[option.key] = phone.evaluate(figure_state)
                assert len({c["hair"] for c in cuts.values()}) == len(cuts), "two haircuts draw the same hair"
                assert cuts["long"]["back"] and not cuts["short"]["back"], "long hair does not fall behind the neck"
                assert cuts["shaved"]["words"].endswith("shaved head") and cuts["curly"]["words"].endswith("curly grey hair")
                pick("beard", "full")
                assert phone.evaluate(figure_state)["beard"], "no beard drawn"

                # With motion allowed, a new build is reached in a short eased change: in between at first, there by
                # a quarter of a second.
                moving = browser.new_context(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
                try:
                    eased = moving.new_page()
                    eased.goto(base + "/login", wait_until="networkidle")
                    eased.fill("input[name=email]", who)
                    eased.fill("input[name=password]", PASSWORD)
                    eased.click("button:has-text('Log in')")
                    eased.wait_for_load_state("networkidle")
                    eased.goto(base + "/profile#body", wait_until="networkidle")
                    frames = eased.evaluate("""() => new Promise(done => {
                        const path = document.querySelector('.fig-man [data-part="skin"]'), seen = [path.getAttribute('d')];
                        const start = performance.now();
                        document.querySelector('.pick input[name="build"][value="heavy"]').click();
                        const look = () => { seen.push(path.getAttribute('d'));
                            if (performance.now() - start < 400) requestAnimationFrame(look); else done(seen); };
                        requestAnimationFrame(look);
                    })""")
                    was, now = frames[0], frames[-1]
                    assert now != was and any(f not in (was, now) for f in frames), "the build changed without easing"
                    assert eased.evaluate("() => document.querySelector('.fig-man [data-part=skin]').getAttribute('d')") == now
                finally:
                    moving.close()

                # Links to a place on the page open its tab, also from the page itself (the budget bar on Profile).
                for anchor, tab in (("budget", "budget"), ("sizes", "sizes"), ("model", "body"), ("colours", "colours"),
                                    ("stores", "stores")):
                    phone.goto(base + "/outfits", wait_until="domcontentloaded")
                    phone.goto(base + f"/profile#{anchor}", wait_until="networkidle")
                    expect(phone.locator(f"#tab-{tab}"), f"#{anchor} does not open {tab}").to_have_attribute("aria-selected", "true")
                    expect(phone.locator(f"#panel-{tab}")).to_be_visible()
                open_tab(phone, "you")
                phone.locator("#summary a").click()
                expect(phone.locator("#tab-budget"), "the budget bar's link on Profile").to_have_attribute("aria-selected", "true")
                expect(phone.locator("#budget")).to_be_in_viewport()

                # "Your model": the model saved in the Body tab, drawn by AI in the first outfit, in the middle.
                phone.goto(base + "/profile#body", wait_until="networkidle")
                pick("build", "broad")
                phone.click("button:has-text('Save profile')")
                phone.wait_for_url(base + "/profile#model")
                switch = phone.get_by_role("group", name="Show in the middle")
                expect(phone.locator("[data-model-picture]"), "the picture shows over the drawn figure").to_be_hidden()
                switch.get_by_role("button", name="Your model").click()
                expect(switch.get_by_role("button", name="Your model")).to_have_attribute("aria-pressed", "true")
                expect(phone.locator("[data-figure]")).to_be_hidden()
                before = len(asked)
                phone.locator("[data-model-picture] button", has_text="Draw my model").click()
                expect(phone.locator("[data-model-picture] .cc-pic-wait")).to_contain_text("Drawing your model")
                phone.wait_for_selector("[data-model-picture] .cc-pic-img", timeout=20000)
                shown_pic = phone.evaluate("""() => { const i = document.querySelector('.cc-pic-img'), r = i.getBoundingClientRect(),
                    s = document.querySelector('.cc-stage').getBoundingClientRect();
                    return {loaded: i.complete && i.naturalWidth > 0, inside: r.top >= s.top - 1 && r.bottom <= s.bottom + 1,
                            said: document.getElementById('announce').textContent}; }""")
                assert shown_pic["loaded"] and shown_pic["inside"], f"the picture in the middle: {shown_pic}"
                assert shown_pic["said"] == "Your model is drawn", f"a screen reader heard {shown_pic['said']!r}"
                assert len(asked) == before + 1 and "broad, sturdy build" in asked[-1]["prompt"], "the saved model was not drawn"
                switch.get_by_role("button", name="Drawn figure").click()
                expect(phone.locator("[data-figure]")).to_be_visible()
                expect(phone.locator("[data-model-picture]"), "the picture shows over the drawn figure").to_be_hidden()
                phone.goto(base + "/outfits", wait_until="networkidle")
                phone.wait_for_selector(f"{first} .look-pic img")
                assert len(asked) == before + 1, "Outfits drew the same picture again"
            finally:
                context.close()

            # On a phone's first screen the row of tabs is in view, clear of Save and of the tab bar; and a tab tapped
            # there brings its controls up: the middle at the top of the screen, the tabs under it, and the tab's first
            # control under them, in view above Save. On three phones down to 360 x 640 with less motion asked for, and
            # once with motion allowed (a smooth scroll that ends in the same place).
            first_control = """name => {
                const panel = document.getElementById('panel-' + name);
                const field = panel.querySelector('input:not([type=hidden]), select, textarea, button, .seg label, .pick label');
                const control = field.closest('label') || field;
                const box = control.getBoundingClientRect(), save = document.querySelector('.cc-save').getBoundingClientRect();
                const bar = document.querySelector('nav.tabs').getBoundingClientRect();
                const top = document.elementFromPoint(box.left + Math.min(box.width / 2, 40), box.top + Math.min(box.height / 2, 12));
                return {stageTop: document.querySelector('.cc-stage').getBoundingClientRect().top,
                        tabsBottom: document.querySelector('.cc-tabs').getBoundingClientRect().bottom, top: box.top,
                        height: box.height, shown: Math.min(box.bottom, save.top, bar.top) - box.top,
                        seen: !!top && control.contains(top)};
            }"""
            settled = """() => new Promise(done => {          // the page has stopped scrolling (four frames alike)
                let last = -1, same = 0;
                const tick = () => { same = scrollY === last ? same + 1 : 0; last = scrollY;
                                     if (same > 3) done(true); else requestAnimationFrame(tick); };
                tick();
            })"""
            for width, height, less_motion in ((390, 844, True), (375, 667, True), (360, 640, True), (375, 667, False)):
                context = browser.new_context(viewport={"width": width, "height": height}, is_mobile=True, has_touch=True,
                                              reduced_motion="reduce" if less_motion else "no-preference")
                try:
                    small = context.new_page()
                    small.on("pageerror", lambda e: failures.append(f"script error: {e}"))
                    small.goto(base + "/login", wait_until="networkidle")
                    small.fill("input[name=email]", who)
                    small.fill("input[name=password]", PASSWORD)
                    small.click("button:has-text('Log in')")
                    small.wait_for_load_state("networkidle")
                    for name in ("you", "body", "sizes", "colours", "budget", "stores") if less_motion else ("sizes",):
                        small.goto(base + "/outfits", wait_until="domcontentloaded")
                        small.goto(base + "/profile", wait_until="networkidle")
                        chips = small.evaluate("""() => [...document.querySelectorAll('[role=tab]')].map(tab => {
                            const box = tab.getBoundingClientRect(), x = Math.min(innerWidth - 2, Math.max(1, box.left + box.width / 2));
                            const under = Math.min(document.querySelector('nav.tabs').getBoundingClientRect().top,
                                                   document.querySelector('.cc-save').getBoundingClientRect().top);
                            const whole = box.bottom <= under + 0.5 && [box.top + 3, box.top + box.height / 2, box.bottom - 3]
                                .every(y => { const top = document.elementFromPoint(x, y); return !!top && tab.contains(top); });
                            return [tab.id, whole];
                        })""")
                        if not all(clear for _, clear in chips):
                            above = small.evaluate("""() => [...document.querySelectorAll('header, #summary, main > *, .cc-head > *, .cc-stage, .cc-tabs')]
                                .map(el => `${el.id || el.className.split(' ')[0] || el.tagName.toLowerCase()} ${Math.round(el.getBoundingClientRect().top)}-${Math.round(el.getBoundingClientRect().bottom)}`).join(', ')""")
                            raise AssertionError(f"{width}x{height}: the first screen's tabs are covered ({above})")
                        small.locator(f"#tab-{name}").tap()
                        small.evaluate(settled)
                        seen = small.evaluate(first_control, name)
                        assert abs(seen["stageTop"]) < 1 and seen["top"] >= seen["tabsBottom"] - 1, \
                            f"{width}x{height}: {name} tapped on the first screen did not bring its controls up: {seen}"
                        assert seen["seen"] and seen["shown"] >= min(seen["height"], 40) - 0.5, \
                            f"{width}x{height}: {name}'s first control is not in view above Save: {seen}"
                finally:
                    context.close()

            # On a computer: the tabs in a column on the left, the middle in the centre, the controls on the right with
            # Save under them, in view; the arrow keys up and down move between the tabs too.
            context = browser.new_context(viewport={"width": 1280, "height": 900})
            try:
                desk = context.new_page()
                desk.on("pageerror", lambda e: failures.append(f"script error: {e}"))
                desk.goto(base + "/login", wait_until="networkidle")
                desk.fill("input[name=email]", who)
                desk.fill("input[name=password]", PASSWORD)
                desk.click("button:has-text('Log in')")
                desk.wait_for_load_state("networkidle")
                desk.goto(base + "/profile", wait_until="networkidle")
                for name in ("you", "body", "sizes", "colours", "budget", "stores"):
                    open_tab(desk, name)
                    seen = desk.evaluate("""() => {
                        const box = s => document.querySelector(s).getBoundingClientRect();
                        const tabs = box('.cc-tabs'), stage = box('.cc-stage'), side = box('.cc-side'), save = box('.cc-save .btn');
                        return {order: tabs.right <= stage.left && stage.right <= side.left, tabsColumn: box('#tab-you').left === box('#tab-budget').left,
                                stage: [stage.top, stage.bottom, innerHeight], save: [save.top, save.bottom], under: save.left >= side.left};
                    }""")
                    assert seen["order"] and seen["tabsColumn"] and seen["under"], f"{name}: the computer layout is {seen}"
                    assert seen["stage"][1] <= seen["stage"][2] and seen["save"][1] <= seen["stage"][2], f"{name}: not on the screen {seen}"
                desk.focus("#tab-budget")
                desk.keyboard.press("ArrowUp")
                expect(desk.locator("#tab-colours")).to_be_focused()
                desk.keyboard.press("ArrowDown")
                expect(desk.locator("#tab-budget")).to_have_attribute("aria-selected", "true")

                # In the You tab Save is the last stop by keyboard, after the photo's forms, as it is last on the screen:
                # Tab goes down the controls and never back up.
                desk.goto(base + "/profile#you", wait_until="networkidle")
                desk.focus("#tab-you")
                stops = []
                for _ in range(60):
                    desk.keyboard.press("Tab")
                    stop = desk.evaluate("""() => { const el = document.activeElement;
                        return el.closest('.cc-side') ? [el.getBoundingClientRect().top + scrollY, el.textContent.trim()] : null; }""")
                    if stop is None:
                        break
                    stops.append(stop)
                assert stops and stops[-1][1] == "Save profile", f"Save is not the last stop in the You tab: {stops[-3:]}"
                assert [y for y, _ in stops] == sorted(y for y, _ in stops), f"Tab goes back up the controls: {stops}"

                # Where the middle is narrow (a 900px window), the switch over it stays clear of the head of the
                # tallest figure the form takes (220 cm): a band at the top of the middle is kept for it.
                desk.set_viewport_size({"width": 900, "height": 700})
                desk.goto(base + "/profile#sizes", wait_until="networkidle")
                desk.fill("input[name=height_cm]", "220")
                desk.wait_for_function("() => document.querySelector('.fig-man').dataset.scale === (220 / 180).toFixed(4)")
                over = desk.evaluate("""() => { const a = document.querySelector('.cc-switch').getBoundingClientRect();
                    return ['hair', 'skin'].map(part => document.querySelector('.fig-man [data-part="' + part + '"]'))
                        .concat(document.querySelector('.fig-man .fig-face')).filter(el => { const b = el.getBoundingClientRect();
                            return !(a.bottom <= b.top || b.bottom <= a.top || a.right <= b.left || b.right <= a.left); })
                        .map(el => el.getAttribute('class')); }""")
                assert not over, f"the switch is over the figure at 220 cm, on a 900px window: {over}"
            finally:
                context.close()

            # Without JavaScript every tab's controls show one under another, as before, with the figure above them.
            context = browser.new_context(viewport={"width": 390, "height": 844}, java_script_enabled=False)
            try:
                plain = context.new_page()
                plain.goto(base + "/login", wait_until="networkidle")
                plain.fill("input[name=email]", who)
                plain.fill("input[name=password]", PASSWORD)
                plain.click("button:has-text('Log in')")
                plain.wait_for_load_state("networkidle")
                plain.goto(base + "/profile", wait_until="networkidle")
                assert not plain.locator("[data-cc-tabs]").is_visible(), "without JavaScript the tabs show, doing nothing"
                visible = plain.locator(".cc-panel").evaluate_all("ps => ps.map(p => [p.id, p.getBoundingClientRect().height > 0])")
                assert visible == [[pid, True] for pid in ("panel-you", "panel-body", "panel-sizes", "panel-colours",
                                                           "panel-budget", "panel-stores", "style-panel", "photo-panel")], \
                    f"without JavaScript: {visible}"
                assert plain.locator("[data-figure]").is_visible(), "the figure is not drawn without JavaScript"
                assert plain.locator("[data-figure-words]").inner_text() == "180 cm, broad build, any skin tone, any hair"
            finally:
                context.close()

        def the_store_picker():
            # Profile's Stores tab: every store offered, ticked to start with. Unticking Weekday takes it out of the
            # outfits, the Wardrobe and the shopping list, with one line saying what was picked again; the last store
            # cannot be unticked (said at once, and to a screen reader); ticking Weekday again brings it back. On a
            # phone, on a computer, and without JavaScript, where the save says that the last store stays.
            who = "picker-" + EMAIL
            # The stores Stilsmith has products from, and (apart, under their own line) those with none yet.
            stores_of = """() => [...document.querySelectorAll('input[name=stores]:not([data-empty])')].map(box =>
                [box.value, box.checked, box.closest('label').textContent.replace(/\\s+/g, ' ').trim()])"""
            empty_of = """() => [...document.querySelectorAll('.store-empty input[name=stores][data-empty]')].map(box =>
                [box.value, box.checked, box.closest('label').textContent.replace(/\\s+/g, ' ').trim()])"""
            six = [["tom-tailor", True, "Tom Tailor"], ["otto", True, "OTTO"], ["hirmer", True, "Hirmer"],
                   ["breuninger", True, "Breuninger"], ["blue-tomato", True, "Blue Tomato"], ["bergfreunde", True, "Bergfreunde"]]
            context = browser.new_context(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
            try:
                phone = context.new_page()
                phone.on("pageerror", lambda e: failures.append(f"script error: {e}"))
                phone.goto(base + "/signup", wait_until="networkidle")
                phone.fill("input[name=email]", who)
                phone.fill("input[name=password]", PASSWORD)
                phone.click("button:has-text('Create account')")
                a_customer_from_before(phone)
                phone.goto(base + "/list", wait_until="networkidle")
                assert "Weekday" in phone.locator("main").inner_text(), "the starter shopping list has nothing from Weekday"
                phone.goto(base + "/profile#stores", wait_until="networkidle")
                expect(phone.locator("#tab-stores")).to_have_attribute("aria-selected", "true")
                assert phone.evaluate(stores_of) == [["cos", True, "COS"], ["weekday", True, "Weekday"]], phone.evaluate(stores_of)
                # No programme has accepted Stilsmith yet: nothing on the tab calls a store a partner, as the page's
                # foot says ("Not affiliated with any retailer").
                assert "partner" not in phone.locator("#panel-stores").inner_text().lower(), \
                    "the Stores tab calls a store a partner before any programme has accepted Stilsmith"
                rows = phone.locator(".store-row").evaluate_all("rs => rs.map(r => r.getBoundingClientRect().height)")
                assert all(h >= 48 for h in rows), f"a store's row is under 48px to tap: {rows}"
                # The six stores with no products yet: apart, under a line that says what they are for, below the
                # stores with products, each a row to tick. Unticking one is no matter.
                assert phone.evaluate(empty_of) == six, f"the stores with no products yet: {phone.evaluate(empty_of)}"
                apart = phone.evaluate("""() => { const head = document.getElementById('stores-empty').getBoundingClientRect();
                    const rows = [...document.querySelectorAll('.store-row')].map(r => [r.querySelector('input').hasAttribute('data-empty'), r.getBoundingClientRect().top]);
                    return {words: document.getElementById('stores-empty').textContent.trim(),
                            below: rows.every(([empty, top]) => empty ? top > head.top : top < head.top),
                            wide: document.documentElement.scrollWidth > innerWidth}; }""")
                assert apart == {"words": "No products yet: paste a link on a piece's page", "below": True, "wide": False}, apart
                phone.get_by_role("checkbox", name="Hirmer").tap()
                expect(phone.get_by_role("checkbox", name="Hirmer")).not_to_be_checked()
                expect(phone.locator("[data-store-said]")).to_be_hidden()
                phone.get_by_role("checkbox", name="Hirmer").tap()
                phone.get_by_role("checkbox", name="Weekday", exact=True).tap()
                expect(phone.locator("[data-store-said]")).to_be_hidden()
                # The last store with products cannot be unticked, however many of the six are ticked.
                phone.get_by_role("checkbox", name="COS", exact=True).tap()
                expect(phone.get_by_role("checkbox", name="COS", exact=True)).to_be_checked()
                said = "At least one store with products must stay ticked: your pieces need a store to come from."
                expect(phone.locator("[data-store-said]")).to_have_text(said)
                expect(phone.locator("[data-store-said]")).to_be_in_viewport()
                assert phone.locator("#announce").text_content() == said, "a screen reader is not told"
                phone.focus("input[name=stores][value=cos]")
                phone.keyboard.press("Space")
                expect(phone.get_by_role("checkbox", name="COS", exact=True), "by keyboard too").to_be_checked()
                # The line goes away again with the next tick or untick of any other store.
                expect(phone.locator("[data-store-said]")).to_be_visible()
                phone.get_by_role("checkbox", name="Hirmer").tap()
                expect(phone.locator("[data-store-said]"), "the line stayed after another store was unticked").to_be_hidden()
                phone.get_by_role("checkbox", name="Hirmer").tap()
                expect(phone.locator("[data-store-said]")).to_be_hidden()
                phone.click("button:has-text('Save profile')")
                phone.wait_for_url(base + "/outfits")          # a first save shows the outfits
                told = phone.locator("main > .flash", has_text="Your pieces now come only from COS:")
                expect(told, "the line about the pieces picked again").to_be_in_viewport()
                for path in ("/outfits", "/", "/list"):
                    phone.goto(base + path, wait_until="networkidle")
                    assert "weekday" not in phone.locator("main").inner_text().lower(), f"{path} still shows Weekday"
                    assert not phone.locator("main a[href*='weekday']").count(), f"{path} still links to Weekday"
                phone.goto(base + "/profile#stores", wait_until="networkidle")
                assert [on for _, on, _ in phone.evaluate(stores_of)] == [True, False], "the unticked store is not kept"
                phone.get_by_role("checkbox", name="Weekday", exact=True).tap()
                phone.click("button:has-text('Save profile')")
                phone.wait_for_url(base + "/profile#stores")
                expect(phone.locator("#tab-stores")).to_have_attribute("aria-selected", "true")
                flashes = phone.locator("main > .flash").all_inner_texts()
                assert flashes == ["Profile saved. See your outfits"], f"ticking a store again said {flashes}"
                phone.goto(base + "/list", wait_until="networkidle")
                assert "Weekday" in phone.locator("main").inner_text(), "Weekday did not come back when ticked again"
            finally:
                context.close()

            # On a computer: the rows in the controls' card, each on one line, nothing over them.
            context = browser.new_context(viewport={"width": 1280, "height": 900})
            try:
                desk = context.new_page()
                desk.goto(base + "/login", wait_until="networkidle")
                desk.fill("input[name=email]", who)
                desk.fill("input[name=password]", PASSWORD)
                desk.click("button:has-text('Log in')")
                desk.wait_for_load_state("networkidle")
                desk.goto(base + "/profile#stores", wait_until="networkidle")
                seen = desk.evaluate("""() => [...document.querySelectorAll('.store-row')].map(row => {
                    const box = row.getBoundingClientRect(), card = document.querySelector('.cc-side').getBoundingClientRect();
                    const words = row.querySelector('span').getBoundingClientRect();
                    const top = document.elementFromPoint(box.left + 10, box.top + box.height / 2);
                    return {inside: box.left >= card.left && box.right <= card.right, oneLine: words.height < 30,
                            clear: !!top && row.contains(top)}; })""")
                assert seen and all(r["inside"] and r["oneLine"] and r["clear"] for r in seen), f"the rows on a computer: {seen}"
            finally:
                context.close()

            # Without JavaScript nothing stops the last store being unticked: the save keeps the stores and says why.
            context = browser.new_context(viewport={"width": 390, "height": 844}, java_script_enabled=False)
            try:
                plain = context.new_page()
                plain.goto(base + "/login", wait_until="networkidle")
                plain.fill("input[name=email]", who)
                plain.fill("input[name=password]", PASSWORD)
                plain.click("button:has-text('Log in')")
                plain.wait_for_load_state("networkidle")
                plain.goto(base + "/profile", wait_until="networkidle")
                # (Only the two with products are unticked: the six with none yet, left ticked, are not enough.)
                for box in plain.locator("input[name=stores]:not([data-empty])").all():
                    box.uncheck()
                plain.click("button:has-text('Save profile')")
                plain.wait_for_load_state("networkidle")
                flashes = plain.locator("main > .flash").all_inner_texts()
                assert "At least one store with products must stay ticked, so your stores stay as they were." in flashes, flashes
                assert [on for _, on in plain.locator("input[name=stores]").evaluate_all(
                    "bs => bs.map(b => [b.value, b.checked])")] == [True] * 8, "the stores did not stay as they were"
            finally:
                context.close()

        def one_tap_colour():
            # A piece the store list has nothing for says so and offers, in one tap, a colour Stilsmith has. The demo
            # data has something for every piece, so a small list is published first, the way the operator does:
            # jumpers in grey and navy only. A second customer who likes black, grey and white then has a black
            # jumper with nothing to buy. Every signed-in page picks up a list as soon as it is published, so it is
            # taken away again at the end: the first customer's steps stay on the demo data, whatever their order.
            jumper = {"category": "knit", "store": "cos", "currency": "EUR", "composition_text": "100% Wolle",
                      "fit": "regular", "sizes_all": ["S", "M", "L"], "sizes_in_stock": ["S", "M", "L"],
                      "image_url": "", "source": "collected"}
            products = [{**jumper, "id": f"cos-9{n}", "name": f"Pullover aus Wolle {n}", "slug": f"pullover-{n}",
                         "price": 39.95 + n, "colour": colour, "colour_hex": None, "url": f"https://www.example.com/de/{n}"}
                        for n, colour in enumerate(("Grau", "Marineblau"))]
            listed = DATA / "store_catalog.json"
            listed.write_text(json.dumps({"published_at": "2026-11-12T12:00:00+01:00",
                                          "collected_at": "2026-11-11T17:00:00+01:00", "stores": {}, "products": products}))
            context = browser.new_context(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
            try:
                phone = context.new_page()
                phone.on("response", lambda r: failures.append(f"{r.status} {r.request.method} {r.url.replace(base, '')[:100]}")
                         if r.status >= 400 and r.url.startswith(base) else None)
                phone.on("pageerror", lambda e: failures.append(f"script error: {e}"))
                phone.goto(base + "/signup", wait_until="networkidle")
                phone.fill("input[name=email]", "colours-" + EMAIL)
                phone.fill("input[name=password]", PASSWORD)
                phone.click("button:has-text('Create account')")
                skip_the_welcome(phone)
                seen = top_bar(phone)
                assert not seen["starter"] and seen["words"].startswith("Your wardrobe: nothing yet"), \
                    f"over the second customer's outfits: {seen}"
                # He skipped the welcome: his Profile says in plain lines what he has not given yet, with no box of
                # example values to make his.
                phone.goto(base + "/profile", wait_until="networkidle")
                assert not phone.locator("#example-note").count() and not example_notes(phone), \
                    f"a new account's Profile still speaks of example values: {example_notes(phone)}"
                notes = [note.text_content().strip() for note in phone.locator("main .not-given").all()]
                assert [note.split(".")[0] for note in notes] == ["You have not given your sizes yet", "You have not chosen colours yet",
                                                                  "You have not set a budget yet"], f"what he has not given: {notes}"
                pick_colours(phone, ("black", "grey", "white"))
                phone.click("button:has-text('Save profile')")
                phone.wait_for_url(base + "/outfits")
                phone.wait_for_load_state("networkidle")
                the_whole_plan_is_his("colours-" + EMAIL)       # the plan of his colours, in his wardrobe
                phone.reload(wait_until="networkidle")
                seen = top_bar(phone)
                assert not seen["starter"] and "€" in seen["words"], f"with pieces in his wardrobe the bar reads: {seen}"
                phone.goto(base + "/", wait_until="networkidle")
                seen = phone.evaluate("() => [innerWidth, document.documentElement.scrollWidth]")
                assert seen[1] <= seen[0] + 1, f"with colours on offer the Wardrobe is {seen[1]}px wide on a {seen[0]}px phone"

                def missing() -> int:
                    said = re.search(r"(\d+) pieces? not in the product list yet", phone.locator("#summary").text_content() or "")
                    return int(said.group(1)) if said else 0

                offer = phone.locator("article.slot .offer button").first
                assert offer.count(), "no piece with nothing to buy offers a colour Stilsmith has"
                card = offer.evaluate("b => b.closest('article').id")
                colour = colours.get(offer.evaluate("b => b.form.elements.colour.value"))
                name = phone.locator(f"#{card} .slot-name").inner_text()
                qty = phone.locator(f"#{card} .qty")
                pieces = int(qty.inner_text().lstrip("×")) if qty.count() else 1
                before = missing()
                assert phone.locator(f"#{card} .note").inner_text().startswith("Not in Stilsmith's product list in "), \
                    "the empty piece does not say what is missing"
                # The card's link is named by all it holds: a screen reader hears its note as well.
                link = phone.locator(f"#{card} .slot-main")
                expect(link, "a screen reader is not told why the piece is empty").to_have_accessible_name(
                    re.compile(r"Not in Stilsmith's product list in \w"))
                phone.evaluate("() => { window.stayed = true; }")
                offer.focus()
                phone.keyboard.press("Enter")
                phone.wait_for_function("id => !document.querySelector('#' + id + ' .offer')", arg=card)
                phone.wait_for_load_state("networkidle")
                assert phone.evaluate("() => window.stayed === true"), "the page was loaded again"
                assert phone.locator(f"#{card} .slot-price").inner_text().strip() != "—", f"{name!r} is still empty"
                renamed = phone.locator(f"#{card} .slot-name").inner_text()
                assert renamed.startswith(colour.label), f"{name!r} took {colour.label.lower()} but is now called {renamed!r}"
                assert missing() == before - pieces, f"the bar still counts {missing()} missing pieces, not {before - pieces}"
                assert phone.evaluate("id => document.activeElement === document.querySelector('#' + id + ' .slot-main')", card), \
                    "keyboard focus did not move to the piece once its button was gone"
                # Named by its piece first and its price too (no aria-label hides it), and by where it leads, last.
                expect(link, "the piece's link does not say what it leads to").to_have_accessible_name(
                    re.compile(r"^" + re.escape(colour.label) + r" .*\d[\d.,]*\s?€.*\. See all options$"))
            finally:
                listed.unlink(missing_ok=True)
                context.close()

        def colours_by_tapping_swatches():
            # Every colour Stilsmith knows is a swatch to tap, five to a row on a phone. Once: liked, numbered in the
            # order tapped (1 counts most); twice: to avoid; three times: neither. The taps fill in the two text
            # fields, hidden while the swatches work, so what is saved is what typing it would save. A third customer,
            # new, so that his first save rebuilds the plan from his colours.
            who = "swatches-" + EMAIL
            context = browser.new_context(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
            try:
                phone = context.new_page()
                # (The demo catalogue has one picture that is missing on purpose, to show the fallback.)
                phone.on("response", lambda r: failures.append(f"{r.status} {r.request.method} {r.url.replace(base, '')[:100]}")
                         if r.status >= 400 and r.url.startswith(base) and "does-not-exist" not in r.url else None)
                phone.on("pageerror", lambda e: failures.append(f"script error: {e}"))
                phone.goto(base + "/signup", wait_until="networkidle")
                phone.fill("input[name=email]", who)
                phone.fill("input[name=password]", PASSWORD)
                phone.click("button:has-text('Create account')")
                a_customer_from_before(phone)
                phone.goto(base + "/profile#colours", wait_until="networkidle")
                grid = phone.evaluate("""() => {
                    const swatches = [...document.querySelectorAll('.swatch')];
                    const top = Math.round(swatches[0].getBoundingClientRect().top);
                    return {names: swatches.map(s => s.dataset.colour),
                            firstRow: swatches.filter(s => Math.round(s.getBoundingClientRect().top) === top).length,
                            smallest: Math.min(...swatches.map(s => Math.min(s.offsetWidth, s.offsetHeight))),
                            colours: swatches.map(s => getComputedStyle(s.querySelector('i')).backgroundColor)};
                }""")
                assert grid["names"] == [c.label.lower() for c in colours.COLOURS.values()], f"the swatches: {grid['names']}"
                assert grid["colours"] == ["rgb({}, {}, {})".format(*(int(c.hex[i:i + 2], 16) for i in (1, 3, 5)))
                                           for c in colours.COLOURS.values()], "a swatch is not in the colour Stilsmith shows for it"
                assert grid["firstRow"] == 5 and grid["smallest"] >= 44, f"on a phone the swatches are laid out as {grid}"
                assert not phone.locator("input[name=liked]").is_visible() and not phone.locator("input[name=refused]").is_visible(), \
                    "the text fields are still shown beside the swatches"

                pick_colours(phone, ("navy", "olive"), ("black",))      # navy, olive, then black twice
                for name in ("Navy: liked, first", "Olive: liked, second", "Black: avoided"):
                    expect(phone.get_by_role("button", name=name, pressed=True), f"no swatch reads {name!r}").to_have_count(1)
                numbers = [phone.locator(f".swatch[data-colour={c}] b").inner_text() for c in ("navy", "olive")]
                assert numbers == ["1", "2"], f"navy and olive are numbered {numbers}"

                # By keyboard: from the Colours tab, Tab goes through every swatch in turn, and Space changes the one
                # with focus, which says what it is now.
                phone.focus("#tab-colours")
                reached: list[str] = []
                for _ in range(40):
                    phone.keyboard.press("Tab")
                    colour = phone.evaluate("() => document.activeElement.dataset.colour || null")
                    if colour is None and reached:
                        break
                    if colour:
                        reached.append(colour)
                assert reached == grid["names"], f"Tab reached the swatches {reached}"
                teal = phone.locator(".swatch[data-colour=teal]")
                teal.focus()
                said = []
                for _ in range(3):
                    phone.keyboard.press("Space")
                    said.append([teal.get_attribute("aria-pressed"), phone.locator("[data-swatch-said]").inner_text()])
                assert said == [["true", "Teal: liked, third"], ["true", "Teal: avoided"], ["false", "Teal"]], \
                    f"Space on teal three times: {said}"

                phone.click("button:has-text('Save profile')")
                phone.wait_for_url(base + "/outfits")
                phone.goto(base + "/profile#colours", wait_until="networkidle")
                saved = [phone.input_value("input[name=liked]"), phone.input_value("input[name=refused]")]
                assert saved == ["navy, olive", "black"], f"saved as {saved}"
                expect(phone.get_by_role("button", name="Navy: liked, first", pressed=True)).to_have_count(1)
                phone.goto(base + "/slots", wait_until="networkidle")
                palette = [" ".join(chip.split()) for chip in phone.locator(".palette .swatch-chip").all_inner_texts()]
                assert "Olive accent" in palette, f"the plan's colours are {palette}: olive is not its accent"
            finally:
                context.close()

            # Without JavaScript the swatches are not shown and the two text fields are typed in, as before.
            context = browser.new_context(viewport={"width": 390, "height": 844}, java_script_enabled=False)
            try:
                plain = context.new_page()
                plain.goto(base + "/login", wait_until="networkidle")
                plain.fill("input[name=email]", who)
                plain.fill("input[name=password]", PASSWORD)
                plain.click("button:has-text('Log in')")
                plain.wait_for_load_state("networkidle")
                plain.goto(base + "/profile", wait_until="networkidle")
                assert not plain.locator("[data-swatches]").is_visible(), "without JavaScript the swatches show, doing nothing"
                plain.fill("input[name=liked]", "olive, navy")
                plain.fill("input[name=refused]", "black, pink")
                plain.click("button:has-text('Save profile')")
                plain.wait_for_load_state("networkidle")
                plain.goto(base + "/profile", wait_until="networkidle")
                typed = [plain.input_value("input[name=liked]"), plain.input_value("input[name=refused]")]
                assert typed == ["olive, navy", "black, pink"], f"without JavaScript, typed colours were saved as {typed}"
            finally:
                context.close()

        def new_colours_rebuild_the_plan():
            # New colours and a new use rebuild the plan, although a piece was swapped inside an outfit
            # earlier: that swap is kept when the new plan has the same garment in the same colour.
            page.goto(base + "/profile", wait_until="networkidle")
            # He kept the example sizes as his on the Buy page: Profile no longer says he has not given his sizes; it
            # still says so of his colours, in a plain line, until this save.
            assert not page.locator("#sizes-not-given").count(), "after 'These are my sizes' the Profile says he gave no sizes"
            assert page.locator("#colours-not-given").count() == 1, "the Profile does not say he has chosen no colours yet"
            assert not example_notes(page), f"the Profile speaks of example values: {example_notes(page)}"
            # (A piece that is in his wardrobe stays through a rebuild, which tests/test_yes.py tests. Here his wardrobe
            # is empty, so the whole plan follows the new colours; afterwards the new plan's pieces are his again.)
            the_whole_plan_is_his(EMAIL, his=False)
            pick_colours(page, ("black", "grey", "white"))
            open_tab(page, "you")
            page.locator("input[name=use][value=office]").check(force=True)
            page.click("button:has-text('Save profile')")
            page.wait_for_url(base + "/outfits")
            in_view("main > .flash", "Your plan now has")
            the_whole_plan_is_his(EMAIL)
            assert not page.locator("#colours-not-given").count(), "after the save the Profile says he has chosen no colours"
            said = page.locator("main > .flash").first.inner_text()
            page.goto(base + "/slots", wait_until="networkidle")
            names = [name.strip() for name in page.locator(".slot-list .nm").all_inner_texts()]
            for colour in ("Black", "Grey", "White"):
                assert any(name.startswith(colour + " ") for name in names), f"no {colour.lower()} piece in the plan: {names}"
            # The pieces of the outfit he said yes to (save_and_buy) stay as they were, whatever their colour, and the
            # message says so; no other piece in the old colours is still planned.
            with db.connect() as con:
                me = con.execute("SELECT id FROM users WHERE email = ?", (EMAIL,)).fetchone()[0]
            with db.as_user(me):
                worn = {slot_id for sig in db.yes_sigs() for slot_id in sig.split("~")}
                stay = {slot["name"] for slot in db.list_slots() if slot["id"] in worn}
            assert worn and len(stay) == len(worn), f"a piece of the outfit he said yes to left the plan: {sorted(worn)} / {sorted(stay)}"
            old = [name for name in names if name.startswith(("Navy ", "Olive ")) and name not in stay]
            assert not old, f"the old colours are still planned: {old}"
            if any(name.startswith(("Navy ", "Olive ", "Indigo ", "Stone ", "Dark brown ")) for name in stay):
                counted = re.search(r"Your plan now has (\d+) pieces? in your colours\. (?:Kept [^.]+\. )?The (\d+) pieces? of your "
                                    r"wardrobe that the new plan has no place for (?:was kept as it was|were kept as they were): "
                                    r"(\d+) pieces in all\.", said)
                assert counted, f"pieces of his outfit stayed, and the message does not say so: {said!r}"
                fresh, kept, in_all = (int(number) for number in counted.groups())
                with db.as_user(me):
                    planned = sum(slot["qty"] for slot in db.list_slots())
                assert fresh + kept == in_all == planned, f"the message counts a piece twice or not at all ({planned} in the plan): {said!r}"
            page.goto(base + "/", wait_until="networkidle")
            lock = page.locator(f"#lock-{swapped['slot']}")
            if lock.count():            # the new plan has the swapped piece: its product and lock stay
                assert "Kept your 1 hand-picked piece" in said, f"the message does not count the kept piece: {said!r}"
                assert lock.get_attribute("aria-pressed") == "true", "the kept piece is no longer locked"
                card = page.locator(f"#card-{swapped['slot']} .row-product [lang]").inner_text()   # its name, in one language
                assert swapped["product"] in card, f"the kept piece shows {card!r}, not {swapped['product']!r}"
            else:
                assert "Not kept: " in said, f"the swapped piece is gone and the message does not say so: {said!r}"

        def yes_and_no_build_the_wardrobe():
            # The wardrobe is the outfits he said yes to. A customer of his own answers the welcome (sizes, colours and a
            # budget, what he dresses for) and is offered outfits. "Add to my wardrobe" on the first: the page says what
            # was added, with Undo; the bar counts that outfit's pieces against his budget; the chip says "My outfits 1";
            # the Wardrobe and the shopping list hold those pieces and no others, each card saying "In 1 of your
            # outfits". The outfits offered next say what is new and what he has ("1 new piece 59 €, 4 already in your
            # wardrobe"), the ones that reuse most come first and the page says why, and one that would take him over
            # his budget says by how much before he says yes. "Not for me": the outfit is not offered again, with Undo.
            # Taking an outfit out under "My outfits" removes only the pieces no other outfit of his wears, names them,
            # and Undo puts it back. A yes adds one of each piece, for the outfit's own price; the plan's second white
            # tee is a spare he adds on its card. After a yes or a no he goes on from where he was: the next outfit in
            # line, the page scrolled as it was. On a phone by touch, on a computer by mouse, and with JavaScript off.
            # His account is deleted when the step ends, passed or failed, so that the step leaves nothing behind.
            for where, phone, script in (("phone", True, True), ("computer", False, True), ("phone, no JavaScript", True, False)):
                customer = f"yes{'-nojs' if not script else '-phone' if phone else ''}-" + EMAIL
                screen = {"width": 390, "height": 844} if phone else {"width": 1280, "height": 860}
                context = browser.new_context(viewport=screen, is_mobile=phone, has_touch=phone, java_script_enabled=script)
                try:
                    view = context.new_page()
                    view.on("response", lambda r: failures.append(f"{r.status} {r.request.method} {r.url.replace(base, '')[:100]}")
                            if r.status >= 400 and r.url.startswith(base) and "does-not-exist" not in r.url else None)
                    view.on("pageerror", lambda e: failures.append(f"script error: {e}"))

                    def tap(selector: str) -> float:
                        """A tap on a button that sends a form: back when the page it leads to is there. Returns how
                        far down the page was scrolled when it was tapped."""
                        target = view.locator(selector).first
                        target.scroll_into_view_if_needed()
                        scrolled = view.evaluate("() => window.scrollY")
                        with view.expect_navigation(wait_until="networkidle"):
                            (target.tap() if phone else target.click())
                        return scrolled

                    def money(text: str) -> float:
                        if text == "":          # the yes of an outfit all his already says no sum: it adds 0 € (review N6)
                            return 0.0
                        return float(re.search(r"([\d.,]+)\s€", text).group(1).replace(",", ""))

                    def bar() -> dict:
                        """The bar's figures by their labels (they are in the page on a phone too, read out but not shown)."""
                        return view.evaluate("""() => Object.fromEntries([...document.querySelectorAll('#summary .num')].map(n =>
                            [n.querySelector('.lbl').textContent.trim(), (n.querySelector('b') || n).textContent.trim()]))""")

                    def chip() -> str:
                        return " ".join(view.locator(".chips a[href$='occasion=saved']").inner_text().split())

                    # On a phone the answers of the outfit on screen stand in the bar over the tab bar (app.js 17a);
                    # everywhere else, and without JavaScript, they are under their outfit.
                    docked = phone and script
                    BOXES = """const reel = document.getElementById('reel'), slides = [...reel.querySelectorAll('.slide')];
                        const on = slides[Math.round(reel.scrollLeft / reel.clientWidth)];
                        const box = slide => slide.querySelector('[data-answer]') || (slide === on ? document.querySelector('#dock [data-answer]') : null);"""

                    def offered() -> list[dict]:
                        """Every outfit on offer, in the order shown: its pieces, its price, what it says it adds."""
                        return view.evaluate("() => {" + BOXES + """
                            // (On offer: not yet in his wardrobe. An outfit of pieces all his has no "Not for me", review N6.)
                            return slides.filter(s => box(s) && box(s).querySelector('form.save input[name=want][value=save]')).map(slide => ({
                                pieces: box(slide).querySelector('form.save input[name=sig]').value.split('~'),
                                no: Boolean(box(slide).querySelector('form.no')),
                                cost: slide.querySelector('.board-cost').textContent.trim(),
                                adds: [...box(slide).querySelectorAll('.adds')].map(p => { const c = p.cloneNode(true);
                                    c.querySelectorAll('.over-short').forEach(x => x.remove()); return c.textContent.trim(); }),   // (its short form in the bar aside)
                                plus: (box(slide).querySelector('.btn.yes .plus') || {textContent: ''}).textContent.trim()})); }""")

                    def answer(what: str, index: int = 0) -> str:
                        """The button to tap for an answer ("yes" or "no") to the outfit at this place in the row, which is
                        on screen."""
                        button = ".btn.yes" if what == "yes" else "form.no button"
                        return f"#dock {button}" if docked else f"#reel .slide:nth-child({index + 1}) {button}"

                    def show(index: int) -> None:
                        """Bring the outfit at this place in the row on screen, as a swipe does, and let the row come to rest."""
                        view.evaluate("i => { const r = document.getElementById('reel'); r.scrollTo({left: i * r.clientWidth, behavior: 'instant'}); }", index)
                        view.wait_for_function("i => { const r = document.getElementById('reel'); return Math.round(r.scrollLeft / r.clientWidth) === i; }", arg=index)
                        view.wait_for_timeout(350)

                    def answers() -> dict:
                        """Where the answers of the outfit on screen stand: what a yes adds, the warning about his budget
                        (if any), the two buttons; where the screen ends for them (the tab bar's top on a phone); which
                        outfit is on screen; how far down the page is scrolled; what has the keyboard."""
                        return view.evaluate("() => {" + BOXES + """
                            const at = el => { if (!el) return null; const b = el.getBoundingClientRect(); return [b.top, b.bottom]; };
                            const tabs = document.querySelector('nav.tabs'), here = document.activeElement;
                            return {index: slides.indexOf(on), pieces: box(on).querySelector('form.save input[name=sig]').value.split('~'),
                                    in_bar: !!document.querySelector('#dock [data-answer]'),
                                    adds: at(box(on).querySelector('.adds:not(.over)')), over: at(box(on).querySelector('.adds.over')),
                                    yes: at(box(on).querySelector('.btn.yes')), no: at(box(on).querySelector('form.no button')),
                                    floor: getComputedStyle(tabs).position === 'fixed' ? tabs.getBoundingClientRect().top : window.innerHeight,
                                    scrolled: window.scrollY,
                                    keyboard: here === document.body ? 'nothing' : here.matches('.btn.yes') && box(on).contains(here) ? 'yes of the outfit on screen'
                                              : here.matches('[data-slide]') ? 'an outfit' : here.tagName + '.' + here.className}; }""")

                    def said() -> str:
                        line = view.locator("main > .said")
                        return " ".join(line.first.inner_text().split()) if line.count() else ""

                    def in_wardrobe() -> list[str]:
                        view.goto(base + "/", wait_until="networkidle")
                        return [card.get_attribute("id").removeprefix("card-") for card in view.locator("article.slot").all()]

                    # The welcome, answered: sizes, two colours and a budget of 700 €, dressing for both.
                    view.goto(base + "/signup", wait_until="networkidle")
                    view.fill("input[name=email]", customer)
                    view.fill("input[name=password]", PASSWORD)
                    view.click("button:has-text('Create account')")
                    view.wait_for_url(base + "/welcome")
                    view.select_option("select[name=top_size]", "L")
                    for name, size in (("shoe", "44"), ("waist", "34"), ("length", "32")):
                        view.fill(f"input[name={name}]", size)
                    tap("button:has-text('Continue')")
                    view.wait_for_url(base + "/welcome/2")
                    for colour in ("navy", "grey"):
                        view.locator(f"label.pick-colour:has(input[value={colour}])").click()
                    view.fill("input[name=budget]", "700")
                    tap("button:has-text('Continue')")
                    view.wait_for_url(base + "/welcome/3")
                    view.locator("label:has(input[name=use][value=both])").click()
                    tap("button:has-text('Show me outfits')")
                    view.wait_for_url(base + "/outfits")
                    assert top_bar(view)["words"].startswith("Your wardrobe: nothing yet"), f"{where}: after the welcome the bar reads {top_bar(view)['words']!r}"
                    assert chip() == "My outfits", f"{where}: before any yes the chip says {chip()!r}"
                    view.goto(base + "/profile", wait_until="networkidle")
                    assert not view.locator("main .not-given").count(), \
                        f"{where}: he answered the welcome, and Profile says he has not: {view.locator('main .not-given').all_inner_texts()}"
                    given = [view.input_value("select[name=top_size]"), view.input_value("input[name=shoe]"), view.input_value("#budget")]
                    assert given == ["L", "44", "700"], f"{where}: the welcome's answers on Profile: {given}"

                    # Yes to the first outfit.
                    view.goto(base + "/outfits", wait_until="networkidle")
                    before = offered()
                    one = before[0]
                    # It adds one of each piece it wears, for the outfit's own price: the line, the button and the
                    # price beside the outfit's name say the same sum.
                    assert re.fullmatch(rf"{len(one['pieces'])} new pieces [\d.,]+\s€", one["adds"][0]), \
                        f"{where}: the first outfit, of {len(one['pieces'])} pieces, adds {one['adds']}"
                    assert money(one["plus"]) == money(one["adds"][0]) == money(one["cost"]), \
                        f"{where}: the outfit costs {one['cost']!r}, its button says {one['plus']!r}, the line {one['adds'][0]!r}"
                    tap(answer("yes"))
                    assert "added=" in view.url, f"{where}: a yes led to {view.url}"
                    # The message names the outfit by its number and title, never by its title alone ("Everyday" is a
                    # filter, and dozens of outfits), and shows its pieces as a row of small photos (review N2).
                    assert re.match(r"Added outfit 1 \([A-Z][a-z ,]+\) to your wardrobe: ", said()) \
                        and " ".join(one["adds"][0].split())[1:] in said() and said().endswith("Undo") and "“" not in said(), \
                        f"{where}: after a yes the page says {said()!r}"
                    thumbs = view.locator("main > .said .answered-pieces .pic")
                    assert thumbs.count() == len(one["pieces"]) and all(t.is_visible() for t in thumbs.all()), \
                        f"{where}: after a yes the message shows {thumbs.count()} small photos for {len(one['pieces'])} pieces"
                    assert chip() == "My outfits 1", f"{where}: after a yes the chip says {chip()!r}"
                    figures = bar()
                    assert money(figures["Total"]) == money(one["adds"][0]), f"{where}: the outfit added {one['adds'][0]!r}, the bar's total is {figures['Total']}"
                    assert money(figures["Budget"]) == 700 and "Left" in figures, f"{where}: the bar's figures after a yes: {figures}"
                    after = offered()
                    assert one["pieces"] not in [o["pieces"] for o in after], f"{where}: the outfit he said yes to is offered again"
                    # What the next ones add, and their order.
                    mine = set(one["pieces"])
                    reused = [len(mine & set(o["pieces"])) for o in after]
                    assert reused == sorted(reused, reverse=True) and reused[0] > 0, f"{where}: outfits that reuse his pieces are not first: {reused}"
                    assert "outfits that use pieces you already have come first" in view.locator("p.lead").inner_text(), \
                        f"{where}: the page does not say why the outfits are in this order"
                    for outfit, n in zip(after, reused):
                        new = len(outfit["pieces"]) - n
                        if n and new:
                            wanted = rf"{new} new pieces? [\d.,]+\s€, {n} already in your wardrobe"
                            assert re.fullmatch(wanted, outfit["adds"][0]), f"{where}: an outfit with {new} new and {n} of his pieces says {outfit['adds'][0]!r}"
                            assert money(outfit["adds"][0]) < money(outfit["cost"]), \
                                f"{where}: an outfit that reuses his pieces adds {outfit['adds'][0]!r}, no less than its price {outfit['cost']}"
                        over = money(figures["Total"]) + money(outfit["plus"]) - 700
                        if over > 0.005 and money(outfit["plus"]) > 0:
                            assert len(outfit["adds"]) == 2 and f"{over:,.2f}".rstrip("0").rstrip(".") in outfit["adds"][1].replace("\xa0", " ") \
                                and outfit["adds"][1].endswith("over your budget."), \
                                f"{where}: an outfit that would take him {over:.2f} € over says {outfit['adds']}"
                        else:
                            assert len(outfit["adds"]) == 1, f"{where}: an outfit within his budget speaks of going over: {outfit['adds']}"
                    assert any(len(o["adds"]) == 2 for o in after), f"{where}: no outfit on offer would take him over 700 €, so nothing was checked"
                    # That warning is read before the yes: it stands above "Add to my wardrobe". On a phone both are
                    # on the first screen, in the bar over the tab bar, on a tall phone and on short ones.
                    over = next(i for i, o in enumerate(after) if len(o["adds"]) == 2)
                    for size in ((390, 844), (390, 664), (360, 640), (412, 785)) if docked else (None,):
                        if size:
                            view.set_viewport_size({"width": size[0], "height": size[1]})
                        view.evaluate("() => window.scrollTo(0, 0)")
                        show(over)
                        seen = answers()
                        assert seen["pieces"] == after[over]["pieces"] and seen["over"] and seen["over"][1] <= seen["yes"][0] + 1, \
                            f"{where}{size or ''}: the warning about his budget is not above 'Add to my wardrobe': {seen}"
                        if docked:
                            assert seen["in_bar"] and seen["scrolled"] == 0 and seen["adds"][0] >= 0 \
                                and max(seen["over"][1], seen["yes"][1], seen["no"][1]) <= seen["floor"], \
                                f"{where} {size}: what a yes adds, the warning and the two answers are not all on the first screen above the tab bar: {seen}"
                        else:
                            assert not seen["in_bar"], f"{where}: the answers are in the phone's bar: {seen}"
                    if docked:
                        view.set_viewport_size(screen)

                    # The Wardrobe and the shopping list hold that outfit's pieces and no others.
                    cards = in_wardrobe()
                    assert sorted(cards) == sorted(one["pieces"]), f"{where}: the Wardrobe shows {cards}, the outfit is {one['pieces']}"
                    notes = [" ".join(note.split()) for note in view.locator("article.slot .in-outfits").all_inner_texts()]
                    assert notes == ["In 1 of your outfits"] * len(cards), f"{where}: the cards say {notes}"
                    view.goto(base + "/list", wait_until="networkidle")
                    lines = view.locator("li.buy").count()
                    assert lines == len(one["pieces"]), f"{where}: {lines} lines on the shopping list for an outfit of {len(one['pieces'])} pieces"
                    doubled = view.locator("li.buy .qty").all_inner_texts()
                    assert not doubled, f"{where}: a yes put more than one of a piece on the shopping list: {doubled}"

                    # Yes to the third outfit on offer, with the page scrolled down a little. He goes on from where he
                    # was: the page comes back on the outfit now third in line (never back at the first), the two he
                    # had passed still in front of it, scrolled to where it was, and what it says was done is in sight.
                    # Behind the two, the outfits that reuse most of his pieces come first, and the page says from
                    # where. The bar gained what the button had said.
                    view.goto(base + "/outfits", wait_until="networkidle")
                    row = offered()
                    show(2)
                    view.evaluate("() => window.scrollTo(0, 140)")
                    two, total = row[2], money(bar()["Total"])
                    assert answers()["pieces"] == two["pieces"], f"{where}: the third outfit is not the one on screen: {answers()}"
                    was_at = tap(answer("yes", 2))
                    assert "added=" in view.url and "front=" in view.url and re.search(r"#outfit-[0-9a-f]{12}$", view.url), \
                        f"{where}: a yes to the third outfit led to {view.url}"
                    went_up = money(bar()["Total"]) - total
                    assert abs(went_up - money(two["plus"])) < 0.005, f"{where}: the button said {two['plus']!r}, the bar went up by {went_up:.2f} €"
                    now = offered()
                    assert [o["pieces"] for o in now[:2]] == [o["pieces"] for o in row[:2]], \
                        f"{where}: after a yes to the third outfit the two he had passed are not in front any more"
                    if script:
                        view.wait_for_function("() => document.readyState === 'complete'")
                        view.wait_for_timeout(150)
                    seen = answers()
                    assert seen["index"] == 2 and seen["pieces"] == now[2]["pieces"] and seen["pieces"] != two["pieces"], \
                        f"{where}: after a yes to the third outfit the page shows outfit {seen['index'] + 1}, not the next in line"
                    his = mine | set(two["pieces"])
                    reused = [len(his & set(o["pieces"])) for o in now[2:]]
                    assert reused == sorted(reused, reverse=True) and reused[0] > 0, \
                        f"{where}: behind the outfits he passed, those that reuse his pieces are not first: {reused}"
                    lead = " ".join(view.locator("p.lead").inner_text().split())
                    assert "from outfit 3 on, those that use pieces you already have come first" in lead, f"{where}: the page says of the order: {lead!r}"
                    if script:
                        assert was_at > 0 and abs(seen["scrolled"] - was_at) <= 1, \
                            f"{where}: he answered with the page scrolled {was_at:.0f}px down, and it came back at {seen['scrolled']:.0f}px"
                        line = view.locator("main > .said").bounding_box()
                        assert line["y"] >= 0 and line["y"] + line["height"] <= seen["floor"], \
                            f"{where}: the page came back scrolled, and the line with Undo is off the screen ({line})"
                        assert seen["keyboard"] == "nothing", f"{where}: after a tap the keyboard is on {seen['keyboard']}"
                    if docked:
                        assert seen["in_bar"] and max(seen["yes"][1], seen["no"][1]) <= seen["floor"], \
                            f"{where}: after a yes the next outfit's answers are not in reach above the tab bar: {seen}"
                    assert chip() == "My outfits 2", f"{where}: after two yeses the chip says {chip()!r}"
                    cards = in_wardrobe()
                    assert sorted(cards) == sorted(mine | set(two["pieces"])), f"{where}: after two yeses the Wardrobe shows {cards}"
                    shared = sorted(mine & set(two["pieces"]))
                    for piece in shared:
                        note = " ".join(view.locator(f"#card-{piece} .in-outfits").inner_text().split())
                        assert note == "In 2 of your outfits", f"{where}: a piece of both outfits says {note!r}"

                    # Not for me, on the fifth outfit: that one outfit is not offered again, and he goes on from where he
                    # was. The page comes back on the outfit that followed, the four he had passed still in front of it,
                    # scrolled to where it was, and it says what was done, with Undo.
                    view.goto(base + "/outfits", wait_until="networkidle")
                    listed = offered()
                    row = [o["pieces"] for o in listed]
                    # (The fifth, or the first after it with a "Not for me" and one after it: an outfit of pieces that
                    # are all his already has none, review N6, and those come first in the row.)
                    k = next(i for i in range(4, len(listed) - 1) if listed[i]["no"] and listed[i + 1]["no"])
                    show(k)
                    assert answers()["pieces"] == row[k], f"{where}: the fifth outfit is not the one on screen: {answers()}"
                    was_at = tap(answer("no", k))
                    assert "declined=" in view.url and re.search(r"#outfit-[0-9a-f]{12}$", view.url), f"{where}: 'Not for me' led to {view.url}"
                    assert re.fullmatch(rf"Outfit {k + 1} \([A-Z][a-z ,]+\)(?:, with(?:out)? the [^,]+,)? will not be offered again\. Its pieces: [^.]+\. Undo", said()), \
                        f"{where}: after 'Not for me' the page says {said()!r}"
                    assert view.locator("main > .said .answered-pieces .pic").count() == len(row[k]), \
                        f"{where}: after 'Not for me' the message does not show the outfit's pieces"
                    now = [o["pieces"] for o in offered()]
                    assert row[k] not in now, f"{where}: the outfit he said no to is offered again"
                    assert [o for o in now if o in row] == row[:k] + row[k + 1:], f"{where}: after a no the other outfits are not in the order they were in"
                    seen = answers()
                    assert seen["pieces"] == row[k + 1] and all(o in now[:seen["index"]] for o in row[:k]), \
                        f"{where}: after a no to the fifth outfit the page shows outfit {seen['index'] + 1}, not the one that followed it"
                    assert abs(seen["scrolled"] - (was_at if script else 0)) <= 1, \
                        f"{where}: he said no with the page scrolled {was_at:.0f}px down, and it came back at {seen['scrolled']:.0f}px"
                    line = view.locator("main > .said").bounding_box()
                    assert line["y"] >= 0 and line["y"] + line["height"] <= seen["floor"], f"{where}: the line with Undo is off the screen ({line})"
                    if script:      # he tapped or clicked: nothing is given the keyboard, and no ring is drawn around an outfit
                        view.wait_for_function("() => document.readyState === 'complete'")
                        view.wait_for_timeout(100)
                        assert answers()["keyboard"] == "nothing", f"{where}: after a tap the keyboard is on {answers()['keyboard']}"
                    if docked:
                        assert seen["in_bar"] and max(seen["yes"][1], seen["no"][1]) <= seen["floor"], \
                            f"{where}: after a no the next outfit's answers are not in reach above the tab bar: {seen}"
                    assert "You said no to 1 outfit" in view.locator("form.declined").inner_text(), f"{where}: no word of the outfit he said no to"
                    tap("main > .said button:has-text('Undo')")
                    assert [o["pieces"] for o in offered()] == row and answers()["pieces"] == row[k], \
                        f"{where}: Undo after 'Not for me' does not put the outfit back in its place and show it (outfit {answers()['index'] + 1} shows)"
                    assert not view.locator("form.declined").count(), f"{where}: after Undo the page still counts an outfit he said no to"

                    if script and not phone:
                        # With the keyboard: after an answer the keyboard is on "Add to my wardrobe" of the outfit that
                        # now shows (it was back at the page's top, some twenty presses of Tab away), and the line that
                        # says what was done is read out. Enter there answers that outfit.
                        view.goto(base + "/outfits", wait_until="networkidle")
                        listed = offered()
                        row = [o["pieces"] for o in listed]
                        # (The second, or the first after it with a "Not for me", as above.)
                        j = next(i for i in range(1, len(listed) - 1) if listed[i]["no"])
                        view.keyboard.press("Tab")
                        for _ in range(j):
                            view.keyboard.press("ArrowRight")
                            view.wait_for_timeout(120)
                        view.wait_for_function("j => { const r = document.getElementById('reel'); return Math.round(r.scrollLeft / r.clientWidth) === j; }", arg=j)
                        view.wait_for_timeout(350)
                        view.locator(answer("no", j)).focus()
                        with view.expect_navigation(wait_until="networkidle"):
                            view.keyboard.press("Enter")
                        view.wait_for_function("() => document.activeElement && document.activeElement.matches('.btn.yes')")
                        seen = answers()
                        assert seen["pieces"] == row[j + 1] and seen["keyboard"] == "yes of the outfit on screen", \
                            f"{where}: after a no given with the keyboard, the keyboard is on {seen['keyboard']} (outfit {seen['index'] + 1} shows)"
                        heard = view.wait_for_function("() => document.getElementById('announce').textContent").json_value()
                        assert re.fullmatch(r"Outfit \d+ \([A-Z][a-z ,]+\)(?:, with(?:out)? the [^,]+,)? will not be offered again\. Its pieces: [^.]+\. Undo is at the top of the page\.", heard), \
                            f"{where}: after a no given with the keyboard a screen reader hears {heard!r}"
                        tap("main > .said button:has-text('Undo')")

                        # "Best for budget": a yes adds what the outfit said here too, and he gets the products it
                        # showed. (The level is fitted for the whole plan, so a piece does not change its product when it
                        # joins his wardrobe; it did, and the bar went up by more than the button had said.)
                        view.goto(base + "/", wait_until="networkidle")
                        view.locator("label:has(input[name=mode][value=budget])").click()
                        view.wait_for_load_state("networkidle")
                        view.reload(wait_until="networkidle")
                        assert view.locator("input[name=mode][value=budget]").is_checked(), f"{where}: 'Best for budget' was not chosen"
                        for _ in range(2):
                            view.goto(base + "/outfits", wait_until="networkidle")
                            on_offer = offered()
                            index = next(i for i, o in enumerate(on_offer) if money(o["plus"]) > 0)
                            adding, total = on_offer[index], money(bar()["Total"])
                            show(index)
                            tap(answer("yes", index))
                            went_up = money(bar()["Total"]) - total
                            assert abs(went_up - money(adding["plus"])) < 0.005 and " ".join(adding["adds"][0].split())[1:] in said(), \
                                f"{where}: at 'Best for budget' the outfit said {adding['adds'][0]!r} and the bar went up by {went_up:.2f} €"
                            view.goto(base + "/outfits?occasion=saved", wait_until="networkidle")
                            marked = [text for text in view.locator(f"{first} .piece-price small").all_inner_texts() if "changed" in text]
                            assert not marked, f"{where}: at 'Best for budget' the outfit he just added has pieces marked {marked}"
                        # … and those two outfits are taken out again, so that what follows starts as it would have.
                        for _ in range(2):
                            view.goto(base + "/outfits?occasion=saved", wait_until="networkidle")
                            tap(f"{first} .btn.yes")
                        view.goto(base + "/", wait_until="networkidle")
                        view.locator("label:has(input[name=mode][value=cheapest])").click()
                        view.wait_for_load_state("networkidle")

                    # Take the first outfit out under "My outfits": only what the other does not wear goes, and Undo.
                    view.goto(base + "/outfits?occasion=saved", wait_until="networkidle")
                    assert view.locator("#reel .slide").count() == 2, f"{where}: two yeses, {view.locator('#reel .slide').count()} outfits under My outfits"
                    newest = view.locator(f"{first} .btn.yes")
                    assert newest.inner_text().strip() == "Take out of my wardrobe", f"{where}: under My outfits the button says {newest.inner_text()!r}"
                    tap(f"{first} .btn.yes")                 # (the newest is first: the second yes)
                    only_two = sorted(set(two["pieces"]) - mine)
                    line = said()
                    assert re.match(r"Took the outfit with the [a-z' -]+ and [a-z' -]+ out of your wardrobe\.", line) and line.endswith("Undo") and "“" not in line, \
                        f"{where}: after taking an outfit out: {line!r}"
                    if only_two:
                        assert f"no other outfit of yours wears {'them' if len(only_two) > 1 else 'it'}" in line, f"{where}: which pieces went: {line!r}"
                    else:
                        assert "All its pieces stay" in line, f"{where}: nothing went with it, and the page says {line!r}"
                    box = view.locator("main > .said").bounding_box()
                    assert box["y"] >= 0 and box["y"] + box["height"] <= screen["height"], f"{where}: the line with Undo is off the screen ({box})"
                    assert chip() == "My outfits 1", f"{where}: one of two taken out, the chip says {chip()!r}"
                    assert sorted(in_wardrobe()) == sorted(mine), f"{where}: with the second outfit out, the Wardrobe is not the first outfit's pieces"
                    view.go_back(wait_until="networkidle")
                    tap("main > .said button:has-text('Undo')")
                    assert chip() == "My outfits 2", f"{where}: after Undo the chip says {chip()!r}"
                    assert sorted(in_wardrobe()) == sorted(mine | set(two["pieces"])), f"{where}: Undo did not put the outfit's pieces back"

                    # A piece the plan has twice (two white tees). An outfit wears one, and a yes adds that one: its card
                    # says so and offers the second as a spare, with its price. "Add a spare": the page says what was
                    # added, the bar goes up by that price, the card and the shopping list count two and say that one
                    # is a spare. "Take the spare out" and Undo take it back and put it back.
                    view.goto(base + "/slots", wait_until="networkidle")
                    twice = view.evaluate("""() => { const row = [...document.querySelectorAll('li[id^=slot-]')].find(li => li.querySelector('summary .qty'));
                        return row ? row.id.replace('slot-', '') : ''; }""")
                    assert twice, f"{where}: the plan has no piece twice, so the spare was not walked"
                    if twice not in in_wardrobe():
                        view.goto(base + "/outfits?n=60", wait_until="networkidle")
                        on_offer = offered()
                        index = next(i for i, o in enumerate(on_offer) if twice in o["pieces"])
                        show(index)
                        total = money(bar()["Total"])
                        tap(answer("yes", index))
                        went_up = money(bar()["Total"]) - total
                        assert abs(went_up - money(on_offer[index]["plus"])) < 0.005, \
                            f"{where}: an outfit with a piece the plan has twice said {on_offer[index]['plus']!r}, and the bar went up by {went_up:.2f} €"
                        view.goto(base + "/", wait_until="networkidle")

                    def spare_line() -> str:
                        return " ".join(view.locator(f"#card-{twice} form.spare").inner_text().split())

                    def in_all() -> int:
                        return int(re.match(r"(\d+) pieces? in your wardrobe", " ".join(view.locator("p.plan-line").inner_text().split())).group(1))

                    assert re.fullmatch(r"Your outfits wear one\. The plan has 2\. Add a spare \+ [\d.,]+\s€", spare_line()), \
                        f"{where}: the card of a piece the plan has twice says {spare_line()!r}"
                    assert not view.locator(f"#card-{twice} .slot-name .qty").count(), f"{where}: one of the piece is his, and its card says ×2"
                    assert view.evaluate("() => document.documentElement.scrollWidth") <= screen["width"], f"{where}: the spare's line makes the Wardrobe wider than the screen"
                    total, pieces, price = money(bar()["Total"]), in_all(), money(spare_line())
                    tap(f"#spare-{twice}")
                    assert re.fullmatch(r"Added a spare “[^”]+” to your wardrobe: [\d.,]+\s€\. Undo", said()) and abs(money(said()) - price) < 0.005, \
                        f"{where}: after 'Add a spare' the page says {said()!r}"
                    assert abs(money(bar()["Total"]) - total - price) < 0.005 and in_all() == pieces + 1, \
                        f"{where}: a spare for {price} €: the total went from {total} to {bar()['Total']}, the pieces from {pieces} to {in_all()}"
                    assert spare_line() == "One of the 2 is a spare. Take the spare out", f"{where}: with its spare the card says {spare_line()!r}"
                    assert view.locator(f"#card-{twice} .slot-name .qty").inner_text().strip() == "×2", f"{where}: with its spare the card does not say ×2"
                    view.goto(base + "/list", wait_until="networkidle")
                    spares = [" ".join(text.split()) for text in view.locator("li.buy .buy-meta").all_inner_texts() if "spare" in text]
                    assert len(spares) == 1 and re.search(r"2 × [\d.,]+\s€ \(one is a spare\)$", spares[0]), \
                        f"{where}: the shopping list says of the spare: {spares}"
                    view.goto(base + "/", wait_until="networkidle")
                    tap(f"#spare-{twice}")
                    assert re.fullmatch(r"Took the spare “[^”]+” out of your wardrobe: [\d.,]+\s€ less\. Undo", said()), \
                        f"{where}: after 'Take the spare out' the page says {said()!r}"
                    assert abs(money(bar()["Total"]) - total) < 0.005 and in_all() == pieces, f"{where}: with the spare out the total is {bar()['Total']}, not {total}"
                    tap("main > .said button:has-text('Undo')")
                    assert abs(money(bar()["Total"]) - total - price) < 0.005 and spare_line().startswith("One of the 2 is a spare."), \
                        f"{where}: Undo did not put the spare back (total {bar()['Total']})"
                finally:
                    context.close()
                    delete_a_steps_customer(customer)       # passed or failed: no account is left behind
                # Gone: his address and password no longer log anyone in.
                context = browser.new_context()
                try:
                    gone = context.new_page()
                    gone.goto(base + "/login", wait_until="networkidle")
                    gone.fill("input[name=email]", customer)
                    gone.fill("input[name=password]", PASSWORD)
                    gone.click("button:has-text('Log in')")
                    gone.wait_for_load_state("networkidle")
                    assert "/login" in gone.url, f"the yes step's customer still has an account (now at {gone.url})"
                finally:
                    context.close()

        def delete_a_steps_customer(email: str) -> None:
            """Delete the account a step made for itself, the way a customer does: Account, "Delete my account"."""
            context = browser.new_context()
            try:
                leaving = context.new_page()
                leaving.on("dialog", lambda d: d.accept())
                leaving.goto(base + "/login", wait_until="networkidle")
                leaving.fill("input[name=email]", email)
                leaving.fill("input[name=password]", PASSWORD)
                leaving.click("button:has-text('Log in')")
                leaving.wait_for_load_state("networkidle")
                if "/login" in leaving.url:
                    return                                   # never made, or deleted already
                leaving.goto(base + "/account", wait_until="networkidle")
                leaving.locator("form[action$='/account/delete'] input[name=current]").fill(PASSWORD)
                leaving.click("button:has-text('Delete my account')")
                leaving.wait_for_load_state("networkidle")
            finally:
                context.close()

        def sold_out_in_his_size():
            # A product he chose by hand that is sold out in his size stays the piece's product, and the outfit stays.
            # Wherever the piece shows (the outfit's list and pop-up, the Wardrobe, the Shopping list, Buy this outfit)
            # it says "Sold out in M at Weekday", with the store's own label for his size, and offers the next best
            # product in his size in one tap, with what it costs more or less. No total counts the sold-out product,
            # and each total that leaves it out says so. The tap chooses the other product and comes back to the same
            # page, which says what changed, with Undo, which comes back there too: by touch on a phone, by mouse on a
            # computer, and with JavaScript off. A customer of his own, deleted when the step ends, passed or failed.
            # His sizes are still the example's, so every size is said to be the example size. The outfit's own price
            # is the one Buy this outfit shows. The tap is also made in the pop-up and under Saved. On paper, where
            # the button is gone, the sentence names the product. Last, with a size nothing is made in: "Not made in
            # your size", never counted as "sold out", and "Nothing else … is in stock in your size" with "Add one you
            # found yourself"; once he has added one by its link (its sizes are not checked) it says "Nothing else is
            # known to be in stock in your size. 1 more at COS: sizes not checked", with the way to all options.
            buyer = "soldout-" + EMAIL

            def as_buyer(**screen):
                context = browser.new_context(**screen)
                view = context.new_page()
                view.on("response", lambda r: failures.append(f"{r.status} {r.request.method} {r.url.replace(base, '')[:100]}")
                        if r.status >= 400 and r.url.startswith(base) and "does-not-exist" not in r.url else None)
                view.on("pageerror", lambda e: failures.append(f"script error: {e}"))
                view.goto(base + "/login", wait_until="networkidle")
                view.fill("input[name=email]", buyer)
                view.fill("input[name=password]", PASSWORD)
                view.click("button:has-text('Log in')")
                view.wait_for_load_state("networkidle")
                return context, view

            def euros(text: str) -> float:
                return float(re.sub(r"[^\d.]", "", text.replace(",", "")) or 0)

            def read(view, selector: str) -> str:
                return " ".join(view.locator(selector).first.evaluate("el => el.innerText").replace("\xa0", " ").split())

            context = browser.new_context(viewport={"width": 1280, "height": 860})
            try:
                signing = context.new_page()
                signing.goto(base + "/signup", wait_until="networkidle")
                signing.fill("input[name=email]", buyer)
                signing.fill("input[name=password]", PASSWORD)
                signing.click("button:has-text('Create account')")
                a_customer_from_before(signing)
                signing.wait_for_load_state("networkidle")
                rows = signing.locator(f"{first} .piece-row[hx-get]").evaluate_all("rs => rs.map(r => r.getAttribute('hx-get'))")
                at = re.search(r"at=([^&]+)", rows[0]).group(1)
                signing.goto(f"{base}/outfits/buy?at={at}", wait_until="networkidle")
                whole = euros(signing.locator(".buy-head b").inner_text())      # the outfit, all of it in stock
                slot = ""
                for row in rows:
                    piece = re.search(r"slot=([^&]+)", row).group(1)
                    signing.goto(f"{base}/slot/{piece}", wait_until="networkidle")
                    gone = signing.locator("li.cand.out:has(.sizeline:has-text('sold out'))", has=signing.locator("button:has-text('Choose this')"))
                    if gone.count():
                        # What the piece has cost in the outfit until now: the product picked for him, in stock.
                        price = euros(signing.locator("li.cand.chosen .cand-top .price").evaluate("el => el.firstChild.textContent"))
                        gone.first.locator("button:has-text('Choose this')").click()
                        signing.wait_for_load_state("networkidle")
                        signing.wait_for_selector("li.cand.out.chosen")
                        slot = piece
                        break
                assert slot, "no piece of the first outfit has an option that is sold out in the example size"
            finally:
                context.close()
            mine = f"{first} .pieces li:has(.piece-row[hx-get*='slot={slot}&']) .soldout"
            outfit, buy = f"{base}/outfits?at={at}", f"{base}/outfits/buy?at={at}"

            def said_and_offered(view, block: str, where: str) -> str:
                """The block says the fact and offers one button, whole on the screen's width; what the button says."""
                assert view.locator(block).count() == 1, f"{where}: the piece is not said to be sold out"
                fact = read(view, f"{block} .soldout-said")
                assert re.fullmatch(r"Sold out in \S+ \(example size\) at [\w &]+", fact), f"{where}: the piece says {fact!r}"
                assert view.locator(f"{block} form button").count() == 1, f"{where}: not one swap button"
                button = read(view, f"{block} form button")
                assert re.fullmatch(r"Swap for .+, (same price|[+−][\d.,]+ € ?[\d.,]+ € (more|less))( for \d+)?", button), \
                    f"{where}: the button reads {button!r}"
                more = read(view, f"{block} .soldout-more")
                assert re.search(r"€( each)? at .+, in stock in \S+ \(example size\)\. It takes this piece's place in all your outfits\.$", more), \
                    f"{where}: under the button: {more!r}"
                box = view.locator(f"{block} form button").bounding_box()
                wide = view.evaluate("() => [document.documentElement.scrollWidth, innerWidth]")
                assert box["height"] >= 44, f"{where}: the swap button is {box['height']:.0f}px tall"
                assert box["x"] >= 0 and box["x"] + box["width"] <= wide[1] and wide[0] <= wide[1], \
                    f"{where}: the swap button or the page is wider than the screen ({box}, {wide})"
                return button

            def not_counted(view, where: str) -> None:
                """The page's total is what its stores' baskets come to: the sold-out piece is in none of them."""
                baskets = view.locator(".store-list:not(.sold-list) .subtotal").all_inner_texts()
                assert read(view, ".sold-list .store-head") == "Sold out in the example size 1 piece not counted", \
                    f"{where}: the sold-out piece's section is headed {read(view, '.sold-list .store-head')!r}"
                total = euros(view.locator(".buy-head b, .grand .grand-row b").first.inner_text())
                assert abs(total - sum(euros(b) for b in baskets)) < 0.01, f"{where}: {total} is not the baskets' {baskets}"

            def pressed(view, selector: str, phone: bool) -> None:
                with view.expect_navigation():       # a plain form: the server answers with the page to go back to
                    (view.locator(selector).first.tap() if phone else view.locator(selector).first.click())
                view.wait_for_load_state("networkidle")

            try:
                for where, screen, phone in (("phone", {"width": 390, "height": 844}, True), ("computer", {"width": 1280, "height": 860}, False)):
                    context, view = as_buyer(viewport=screen, is_mobile=phone, has_touch=phone)
                    try:
                        # The outfit stays, with the product he chose; under the piece it says so and offers the swap.
                        view.goto(outfit, wait_until="networkidle")
                        now = view.locator(f"{first} .piece-row[hx-get]").evaluate_all("rs => rs.map(r => r.getAttribute('hx-get'))")
                        assert now == rows, f"{where}: the outfit did not stay as it was"
                        offered = said_and_offered(view, mine, f"{where}, the outfit's list")
                        # … and in the piece's pop-up, before the quick changes.
                        view.locator(f"{first} .piece-row[hx-get*='slot={slot}&']").evaluate("r => r.click()")
                        view.wait_for_selector("dialog#piece[open] .soldout")
                        motion_ended(view)
                        assert said_and_offered(view, "dialog#piece[open] .soldout", f"{where}, the pop-up") == offered
                        view.keyboard.press("Escape")
                        # The outfit has one price: what can be bought of it, as on Buy this outfit; said under it.
                        cost = euros(view.locator(f"{first} .board-cost").inner_text())
                        assert abs(cost - (whole - price)) < 0.01, f"{where}: the outfit says {cost}; without the sold-out piece it is {whole - price}"
                        less = read(view, f"{first} .about-less")
                        assert re.fullmatch(r"Not counted: .+, sold out in \S+ \(example size\)", less), f"{where}: under the outfit's price: {less!r}"
                        assert view.locator(f"{first} .pieces li:has(.piece-row[hx-get*='slot={slot}&']) .piece-price s").count() == 1, \
                            f"{where}: the sold-out piece's price in the outfit's list is not struck out"
                        # The Wardrobe: on the piece's card, its price struck out, and the bar says why one is not to buy.
                        view.goto(base + "/", wait_until="networkidle")
                        said_and_offered(view, f"#card-{slot} .soldout", f"{where}, the Wardrobe")
                        assert view.locator(f"#card-{slot} .slot-price s").count() == 1, f"{where}: the Wardrobe card's price is not struck out"
                        assert "sold out in the example size" in view.locator("#summary").evaluate("el => el.textContent"), \
                            f"{where}: the budget bar does not say a piece is sold out in his size"
                        # The Shopping list and Buy this outfit: apart from the baskets, in no total, and said.
                        view.goto(base + "/list", wait_until="networkidle")
                        said_and_offered(view, ".sold-list .soldout", f"{where}, the Shopping list")
                        not_counted(view, f"{where}, the Shopping list")
                        grand = read(view, ".grand")
                        assert "you can buy" in grand and "Sold out in the example size 1 piece, not counted" in grand, f"{where}: the list's total reads {grand!r}"
                        # On paper the button is gone, and the sentence under it names the product itself.
                        named = re.match(r"Swap for (.+), (?:same price|[+−])", read(view, ".sold-list .soldout form button")).group(1)
                        view.emulate_media(media="print")
                        try:
                            assert not view.locator(".sold-list .soldout form button").is_visible(), f"{where}: the swap button is printed"
                            printed = [" ".join(p.replace("\xa0", " ").split()) for p in view.locator(".sold-list .soldout p:visible").all_inner_texts()
                                       if p.strip()]
                            assert len(printed) == 2 and re.fullmatch(
                                r"In stock in \S+ \(example size\): " + re.escape(named) + r", [\d.,]+ € at [\w &]+\.", printed[1]), \
                                f"{where}: on paper the sold-out piece reads {printed}"
                        finally:
                            view.emulate_media(media="screen")
                        view.goto(buy, wait_until="networkidle")
                        said_and_offered(view, ".sold-list .soldout", f"{where}, Buy this outfit")
                        not_counted(view, f"{where}, Buy this outfit")
                        head = read(view, ".buy-head")
                        assert "1 sold out in the example size, not counted" in head, f"{where}: Buy this outfit is headed {head!r}"
                        assert abs(euros(view.locator(".buy-head b").inner_text()) - (whole - price)) < 0.01, \
                            f"{where}: Buy this outfit counts {head!r}; the outfit was {whole} with this piece at {price}"

                        # One tap, on each page that offers it: the other product is chosen, the same page says so
                        # with Undo, and Undo comes back to the same page with the product he had.
                        for page_name, address, block in (("Buy this outfit", buy, ".sold-list .soldout"),
                                                          ("the outfit's list", outfit, mine),
                                                          ("the pop-up", outfit, "dialog#piece[open] .soldout"),
                                                          ("the Wardrobe", base + "/", f"#card-{slot} .soldout"),
                                                          ("the Shopping list", base + "/list", ".sold-list .soldout")):
                            view.goto(address, wait_until="networkidle")
                            if page_name == "the pop-up":
                                view.locator(f"{first} .piece-row[hx-get*='slot={slot}&']").evaluate("r => r.click()")
                                view.wait_for_selector("dialog#piece[open] .soldout form button")
                                motion_ended(view)
                            name = re.match(r"Swap for (.+), (?:same price|[+−])", read(view, f"{block} form button")).group(1)
                            pressed(view, f"{block} form button", phone)
                            here = address.split("?")[0]
                            assert view.url.split("?")[0] == here and "changed=" + slot in view.url, \
                                f"{where}: the swap on {page_name} led to {view.url}"
                            line = said_over_the_outfits(view)
                            assert " changed in all your outfits: " in line and line.endswith("It stays when you change the price level. Undo"), \
                                f"{where}, {page_name}: after the swap the line reads {line!r}"
                            assert view.locator(".soldout").count() == 0, f"{where}, {page_name}: still said to be sold out after the swap"
                            motion_ended(view)
                            assert view.locator("main > .said").evaluate("""el => { const b = el.getBoundingClientRect();
                                return b.top >= 0 && b.bottom <= innerHeight; }"""), f"{where}, {page_name}: the line with Undo is off the screen"
                            if address == buy:      # the piece counts again, at the new product's price
                                assert "sold out" not in read(view, ".buy-head"), f"{where}: {read(view, '.buy-head')!r}"
                            if address == outfit:   # the outfit wears the new product (named in English on the button where known)
                                assert view.locator(f"{first} .piece-row[hx-get]").count() == len(rows), f"{where}: the outfit lost a piece"
                            pressed(view, "main > .said button", phone)
                            assert view.url.split("?")[0] == here, f"{where}: Undo on {page_name} led to {view.url}"
                            again = mine if page_name == "the pop-up" else block       # (Undo comes back to the outfit, the pop-up shut)
                            assert view.locator(again).count() == 1, f"{where}, {page_name}: after Undo the piece is not said to be sold out again"
                            back = [f for f in view.locator("main > .flash").all_inner_texts() if ": back to " in f]
                            assert back, f"{where}, {page_name}: nothing says the product is back: {view.locator('main > .flash').all_inner_texts()}"
                            assert name not in back[0], f"{where}, {page_name}: Undo says {back[0]!r}"

                        # Under Saved: the saved outfit says it while the piece is still that product, with the same
                        # tap; the swap and its Undo both come back to Saved.
                        view.goto(outfit, wait_until="networkidle")
                        # (On a phone the answers of the outfit on screen stand in the bar over the tabs, app.js 17a.)
                        yes_button = view.locator(f"#dock .btn.yes, {first} .btn.yes").first
                        if yes_button.inner_text().startswith(("Add", "Save to")):     # ("Save to My outfits": all his, review N6)
                            with view.expect_navigation(wait_until="networkidle"):
                                yes_button.click()
                        view.goto(base + "/outfits?occasion=saved", wait_until="networkidle")
                        kept = ".pieces li .soldout"
                        said_and_offered(view, kept, f"{where}, Saved")
                        pressed(view, f"{kept} form button", phone)
                        assert "/outfits?" in view.url and "occasion=saved" in view.url and "changed=" + slot in view.url, \
                            f"{where}: the swap under Saved led to {view.url}"
                        assert said_over_the_outfits(view).endswith("It stays when you change the price level. Undo"), \
                            f"{where}, Saved: after the swap the line reads {said_over_the_outfits(view)!r}"
                        assert view.locator(".soldout").count() == 0, f"{where}, Saved: still said to be sold out after the swap"
                        pressed(view, "main > .said button", phone)
                        assert "occasion=saved" in view.url, f"{where}: Undo under Saved led to {view.url}"
                        assert view.locator(kept).count() == 1, f"{where}, Saved: after Undo the piece is not said to be sold out again"
                    finally:
                        context.close()

                # With JavaScript off the same tap and the same Undo, on the Shopping list.
                context, plain = as_buyer(viewport={"width": 390, "height": 844}, java_script_enabled=False)
                try:
                    plain.goto(base + "/list", wait_until="networkidle")
                    said_and_offered(plain, ".sold-list .soldout", "no JavaScript, the Shopping list")
                    pressed(plain, ".sold-list .soldout form button", False)
                    assert plain.url.startswith(base + "/list?") and plain.locator(".soldout").count() == 0, \
                        f"without JavaScript the swap led to {plain.url}"
                    assert said_over_the_outfits(plain).endswith("Undo"), "without JavaScript: no Undo after the swap"
                    pressed(plain, "main > .said button", False)
                    assert plain.url == base + "/list" and plain.locator(".sold-list .soldout").count() == 1, \
                        f"without JavaScript Undo led to {plain.url}"
                finally:
                    context.close()

                # A size nothing is made in. The product he chose is "Not made in your size" (his own size now, no
                # longer the example's), which no count calls "sold out". Nothing else is in his size: said, with
                # "Add one you found yourself". Once he has added one by its link, whose sizes nobody checked, it is
                # no longer "nothing": it is counted, and the link leads to all the options.
                context, view = as_buyer(viewport={"width": 1280, "height": 860})
                try:
                    view.goto(base + "/profile#sizes", wait_until="networkidle")
                    view.select_option("select[name=top_size]", "XXS")        # (no demo product is made in it)
                    view.click("button:has-text('Save profile')")
                    view.wait_for_load_state("networkidle")
                    view.goto(base + "/", wait_until="networkidle")
                    card = f"#card-{slot} .soldout"
                    fact = read(view, f"{card} .soldout-said")
                    assert re.fullmatch(r"Not made in your size at [\w &]+", fact), f"a size nothing is made in: the piece says {fact!r}"
                    assert view.locator(f"{card} form").count() == 0, "a swap is offered although nothing is in his size"
                    more = read(view, f"{card} .soldout-more")
                    assert more == "Nothing else for this piece is in stock in your size. Add one you found yourself", \
                        f"with nothing else in his size the piece says {more!r}"
                    bar = " ".join(view.locator("#summary").evaluate("el => el.textContent").split())
                    assert "not made in your size" in bar and "sold out in your size" not in bar, \
                        f"the budget bar counts a product not made in his size as: {bar!r}"
                    view.locator(f"{card} .soldout-more a").click()
                    view.wait_for_load_state("networkidle")
                    assert f"/slot/{slot}" in view.url and view.url.endswith("#add"), f"'Add one you found yourself' led to {view.url}"
                    view.fill("#add textarea[name=urls]", f"https://www.cos.com/de-de/men/product/{slot}-1234567002.html")
                    with view.expect_navigation():
                        view.locator("#add button", has_text="Add").click()
                    view.wait_for_load_state("networkidle")
                    assert view.locator(".cand:has(.by > .tag)").count() == 1, "the product pasted by its link was not added"
                    for page_name, address, block in (("the Wardrobe", base + "/", card), ("the Shopping list", base + "/list", ".sold-list .soldout")):
                        view.goto(address, wait_until="networkidle")
                        more = read(view, f"{block} .soldout-more")
                        assert more.startswith("Nothing else is known to be in stock in your size. 1 more at COS: sizes not checked. "
                                               "See all options"), f"{page_name}: with one product whose sizes were not checked: {more!r}"
                        assert "Add one you found yourself" not in more, f"{page_name}: {more!r}"
                    head = read(view, ".sold-list .store-head")
                    assert head == "Not made in your size 1 piece not counted", f"the list's section is headed {head!r}"
                    view.locator(".sold-list .soldout .soldout-more a").click()
                    view.wait_for_load_state("networkidle")
                    assert f"/slot/{slot}" in view.url and view.locator(".cand:has(.by > .tag)").count() == 1, \
                        f"'See all options' led to {view.url}, without the product whose sizes were not checked"
                    own = read(view, ".slot-head .soldout .soldout-more")
                    assert own.endswith("1 more at COS: sizes not checked. They are listed below."), f"the piece's own page says {own!r}"
                finally:
                    context.close()
            finally:
                delete_a_steps_customer(buyer)       # (it deletes whichever customer it is given)
            context = browser.new_context()
            try:
                gone_page = context.new_page()
                gone_page.goto(base + "/login", wait_until="networkidle")
                gone_page.fill("input[name=email]", buyer)
                gone_page.fill("input[name=password]", PASSWORD)
                gone_page.click("button:has-text('Log in')")
                gone_page.wait_for_load_state("networkidle")
                assert "/login" in gone_page.url, f"the sold-out step's customer still has an account (now at {gone_page.url})"
            finally:
                context.close()

        def motion_quick_and_still():
            # Stilsmith moves to answer the customer (app.css "Motion"), on a phone (390 x 844, by touch) and a computer:
            # a tab changes the page with a slide, forward along the tabs and back again, and a tap made while it slides
            # is not lost; the pop-up slides up and, closing, lets a tap through to the page at once;
            # the AI picture, when it arrives, comes up whole over the pieces' photos (never a
            # blank box, never a half-loaded picture, on a slow connection too); a price level fills. Everything that
            # moves after a tap ends within 300 ms, keyboard focus is in full view once the pop-up is up, and nothing on
            # the page shifts (all layout shifts together, those just after a tap too, at most 0.05). For people who ask
            # their device for less motion, the same taps move nothing at all: no page slides, nothing fades or grows,
            # and the picture still shows only once it is whole.
            # A customer of its own, so that the two pictures drawn here count against his day's pictures, not the
            # first customer's (whose steps have spent most of theirs by now).
            mover = "motion-" + EMAIL
            context = browser.new_context()
            signing = context.new_page()
            signing.goto(base + "/signup", wait_until="networkidle")
            signing.fill("input[name=email]", mover)
            signing.fill("input[name=password]", PASSWORD)
            signing.click("button:has-text('Create account')")
            a_customer_from_before(signing)
            context.close()

            def recorded(motion: str, phone: bool):
                screen = {"width": 390, "height": 844} if phone else {"width": 1280, "height": 860}
                context = browser.new_context(viewport=screen, is_mobile=phone, has_touch=phone, reduced_motion=motion)
                context.add_init_script(MOTION_RECORDER)
                other = context.new_page()
                other.goto(base + "/login", wait_until="networkidle")
                other.fill("input[name=email]", mover)
                other.fill("input[name=password]", PASSWORD)
                other.click("button:has-text('Log in')")
                other.wait_for_url(base + "/outfits")
                other.wait_for_load_state("networkidle")
                other.wait_for_selector(f"{first} .look-pic img", timeout=20000)
                return context, other

            def tap(other, phone: bool, selector: str) -> None:
                (other.locator(selector).first.tap() if phone else other.locator(selector).first.click())

            def moved(other) -> list:
                return [m for m in other.evaluate("window.moved") if not m["scroll"]]

            def tab(other, phone: bool, name: str, path: str) -> dict:
                tap(other, phone, f"nav.tabs a:has-text('{name}')")
                other.wait_for_url(base + path)
                other.wait_for_function("() => window.change && (!window.change.slides || window.change.ready)")
                return other.evaluate("window.change")

            def arrives_whole(other, where: str, seeds) -> None:
                # On a slow connection: the picture's file comes 300 ms after it is asked for.
                other.route("**/looks/*", lambda route: (other.wait_for_timeout(300), route.continue_()))
                for seed in seeds:                       # a shuffle whose first outfit has no picture yet
                    other.goto(base + f"/outfits?seed={seed}", wait_until="domcontentloaded")
                    if not other.locator(f"{first} .look-pic").count():
                        break
                else:
                    raise AssertionError("the first outfit of every shuffle tried already has its picture")
                other.evaluate(PICTURE_FRAMES, first)
                other.wait_for_selector(f"{first} .look-pic img", timeout=20000)
                other.wait_for_function("s => document.querySelector(s + ' .look-pic img').complete", arg=first)
                motion_ended(other)
                other.wait_for_timeout(100)
                frames = other.evaluate("window.frames")
                other.unroute("**/looks/*")
                assert len(frames) >= 10, f"{where}: too few frames of the picture's arrival were seen: {len(frames)}"
                assert not any(f["blank"] for f in frames), \
                    f"{where}: the picture's box was blank in {sum(f['blank'] for f in frames)} of {len(frames)} frames"
                assert not any(f["half"] for f in frames), \
                    f"{where}: the picture showed before its file had arrived in {sum(f['half'] for f in frames)} of {len(frames)} frames"

            failed_slow: list[str] = []

            def quick(other, what: str) -> None:
                """Everything that moved for this ended within 300 ms (a loop and what follows a scroll aside)."""
                slow = [m for m in moved(other) if not m["loop"] and m["total"] > 300]
                if slow:
                    failed_slow.append(f"{what}: {slow[:3]}")
                other.evaluate("window.moved = []")

            # With motion, on a phone.
            context, other = recorded("no-preference", True)
            # The row: each outfit beside the one on screen fades as the row moves, and is exactly itself at rest.
            row = other.evaluate("""s => { const stage = document.querySelector(s + ' .stage'), style = getComputedStyle(stage);
                return {name: style.animationName, opacity: style.opacity, transform: style.transform,
                        can: CSS.supports('animation-timeline: view()')}; }""", first)
            assert not row["can"] or (row["name"] == "outfit-pass" and row["opacity"] == "1" and row["transform"] == "none"), \
                f"the outfit on screen does not follow the row as it moves, or is not itself at rest: {row}"
            change = tab(other, True, "Wardrobe", "/")
            assert change["slides"] and change.get("types") == ["forward"], f"Outfits to Wardrobe does not slide forward: {change}"
            motion_ended(other)
            quick(other, "Outfits to Wardrobe")
            tap(other, True, ".levels label:has-text('Top')")
            other.wait_for_function("() => document.querySelector('#summary .num b').textContent === document.querySelector('#level-top').textContent")
            motion_ended(other)
            quick(other, "a price level")
            # A tap made while the page slides in goes where it was meant to: here the next tab, Shopping.
            shopping = other.locator("nav.tabs a:has-text('Shopping')").bounding_box()
            tap(other, True, "nav.tabs a:has-text('Outfits')")
            other.wait_for_url(base + "/outfits")
            other.wait_for_function("() => window.change && window.change.ready")
            sliding = other.evaluate("() => document.getAnimations().some(a => (a.effect.pseudoElement || '').startsWith('::view-transition'))")
            other.touchscreen.tap(shopping["x"] + shopping["width"] / 2, shopping["y"] + shopping["height"] / 2)
            assert sliding, "the page had already stopped sliding, so this checks nothing"
            other.wait_for_url(base + "/list", timeout=3000)
            change = tab(other, True, "Outfits", "/outfits")
            assert change["slides"] and change.get("types") == ["back"], f"Shopping to Outfits does not slide back: {change}"
            other.wait_for_selector(f"{first} .look-pic img")
            motion_ended(other)
            other.evaluate("window.moved = []")
            # The pop-up: up within 300 ms, then in place, with keyboard focus (on Close) in full view.
            tap(other, True, f"{first} .spot")
            other.wait_for_selector("dialog#piece[open] #piece-title")
            motion_ended(other)
            sheet = other.evaluate("""() => { const sheet = document.querySelector('dialog#piece'), close = sheet.querySelector('.sheet-close');
                let seen = 1; for (let el = close; el; el = el.parentElement) seen *= +getComputedStyle(el).opacity;
                return {moved: [...document.getAnimations()].some(a => a.effect.target === sheet), transform: getComputedStyle(sheet).transform,
                        focus: document.activeElement === close, seen, bottom: sheet.getBoundingClientRect().bottom, height: innerHeight}; }""")
            assert sheet["moved"] or any(m["on"].startswith("piece") for m in moved(other)), "the pop-up did not slide up"
            assert sheet["transform"] == "none" and sheet["focus"] and sheet["seen"] == 1 and sheet["bottom"] <= sheet["height"] + 0.5, \
                f"once the pop-up is up it is not in place with Close in full view and focused: {sheet}"
            quick(other, "the pop-up opening")
            # Closing, it lets a tap through to the page at once (to the picture: on a phone the price lies on it and
            # lets taps through to it).
            tap(other, True, "dialog#piece .sheet-close")
            through = other.evaluate("""s => { const price = document.querySelector(s + ' .board-cost'), box = price.getBoundingClientRect();
                const under = document.elementFromPoint(box.left + box.width / 2, box.top + box.height / 2);
                return {open: document.querySelector('dialog#piece').open,
                        price: !!under && (price.contains(under) || document.querySelector(s + ' .stage').contains(under))}; }""", first)
            assert not through["open"] and through["price"], f"while the pop-up closes a tap does not reach the page: {through}"
            motion_ended(other)
            quick(other, "the pop-up closing")
            # (The heart that grew in as an outfit was saved is gone with the heart: a yes brings the whole page back,
            # with what was added said at its top.)
            assert other.evaluate("window.jumps") <= 0.05, f"the outfits page shifted: {other.evaluate('window.jumps'):.3f}"
            # The AI picture comes up whole, and its coming up is quick.
            arrives_whole(other, "390 x 844", range(201, 241))
            assert any(m["what"] == "develop" for m in moved(other)), "the picture did not come up: it just appeared"
            quick(other, "the picture coming up")
            assert other.evaluate("window.jumps") <= 0.05, f"the picture's arrival shifted the page: {other.evaluate('window.jumps'):.3f}"
            context.close()

            # With motion, on a computer: the pop-up fades in, and out.
            context, other = recorded("no-preference", False)
            other.evaluate("window.moved = []")
            tap(other, False, f"{first} .piece-row")
            other.wait_for_selector("dialog#piece[open] #piece-title")
            motion_ended(other)
            assert any(m["on"].startswith("piece") for m in moved(other)), "on a computer the pop-up did not fade in"
            quick(other, "the pop-up opening on a computer")
            other.keyboard.press("Escape")
            other.wait_for_selector("dialog#piece:not([open])", state="attached")
            motion_ended(other)
            quick(other, "the pop-up closing on a computer")
            context.close()
            assert not failed_slow, "took longer than 300 ms: " + "; ".join(failed_slow)

            # With less motion asked for: the same taps move nothing.
            context, other = recorded("reduce", True)
            stirred: list[str] = []

            def nothing_moved(what: str) -> None:
                other.wait_for_timeout(350)              # anything started by now would have shown
                if moved(other):
                    stirred.append(f"{what}: {moved(other)[:3]}")
                other.evaluate("window.moved = []")

            row = other.evaluate("s => getComputedStyle(document.querySelector(s + ' .stage')).animationName", first)
            assert row == "none", f"with less motion asked for, the outfits still fade as the row moves ({row})"
            change = tab(other, True, "Wardrobe", "/")
            assert not change["slides"], "with less motion asked for, the page slides"
            nothing_moved("Outfits to Wardrobe")
            tap(other, True, ".levels label:has-text('Top')")
            other.wait_for_function("() => document.querySelector('#summary .num b').textContent === document.querySelector('#level-top').textContent")
            nothing_moved("a price level")
            tab(other, True, "Outfits", "/outfits")
            other.wait_for_selector(f"{first} .look-pic img")
            nothing_moved("Wardrobe to Outfits")
            tap(other, True, f"{first} .spot")
            other.wait_for_selector("dialog#piece[open] #piece-title")
            nothing_moved("the pop-up opening")
            tap(other, True, "dialog#piece .sheet-close")
            other.wait_for_selector("dialog#piece:not([open])", state="attached")
            nothing_moved("the pop-up closing")
            arrives_whole(other, "390 x 844, less motion", range(241, 281))
            nothing_moved("the picture arriving")
            context.close()
            assert not stirred, "with less motion asked for, these moved: " + "; ".join(stirred)

        def the_outfit_on_a_phones_first_screen():
            # The model view is the heart of Stilsmith. On a phone the picture is the screen: right under the header, as
            # large as the screen allows above the bar with the two answers and the tab bar, the whole model in it (on
            # 390 x 664, Safari's, about 309 by 463px where the review measured 190 by 285), also under a message at
            # the top of the page. The budget bar is not over it. The outfit's title and price lie on the picture's
            # lower edge, readable on any picture (white on a dark veil, at least 4.5:1 even over white), clear of the
            # dots and of the label 'AI picture'. The chips and Shuffle are one row right under the picture (on a narrow phone the chips scroll sideways inside it, and a chip reached
            # by keyboard comes whole into it, ring and all), the chip that is on is marked, the line over the outfits
            # says how to see the next one (swipe on a touch screen, the arrows with a mouse), each outfit's title is a
            # heading that agrees with the chip, 'Buy this outfit' is the main button, and the outfit row does not cut
            # off the focus ring of 'Add to my wardrobe' or of 'Buy this outfit'.
            def opened(width: int, height: int, touch: bool, path: str = "/outfits", demo: bool = False):
                context = browser.new_context(viewport={"width": width, "height": height}, is_mobile=touch, has_touch=touch)
                other = context.new_page()
                other.goto(base + "/login", wait_until="networkidle")
                other.fill("input[name=email]", EMAIL)
                other.fill("input[name=password]", PASSWORD)
                other.click("button:has-text('Log in')")
                other.wait_for_load_state("networkidle")
                other.goto(base + path, wait_until="networkidle")
                other.wait_for_selector(f"{first} .look-pic img")
                # This check runs on invented products, so the page opens with the "Demo data" notice, which customers
                # of the real catalogue never see: it is taken away to measure the page as they get it (but see below).
                if not demo:
                    other.evaluate("() => document.querySelectorAll('main .demo').forEach(notice => notice.remove())")
                return context, other

            def screen(other) -> dict:
                return other.evaluate("""() => {
                    const slide = document.querySelector('#reel .slide:first-child'), box = el => el.getBoundingClientRect();
                    const picture = box(slide.querySelector('.look-pic'));
                    const words = [...slide.querySelectorAll('.about-head h2, .board-cost')].map(box);
                    // The contrast of white words on the veil behind them, the veil laid over a white picture (its worst).
                    const lum = c => { const v = c / 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; };
                    const veil = [...slide.querySelectorAll('.about-head h2, .board-cost')].map(el => {
                        const [r, g, b, a = 1] = getComputedStyle(el).backgroundColor.match(/[\\d.]+/g).map(Number);
                        const [tr, tg, tb] = getComputedStyle(el).color.match(/[\\d.]+/g).map(Number);
                        const over = [r, g, b].map(c => c * a + 255 * (1 - a)), L = c => 0.2126 * lum(c[0]) + 0.7152 * lum(c[1]) + 0.0722 * lum(c[2]);
                        const [hi, lo] = [L([tr, tg, tb]), L(over)].sort((x, y) => y - x);
                        return (hi + 0.05) / (lo + 0.05); });
                    const meet = (p, q) => p.left < q.right && q.left < p.right && p.top < q.bottom && q.top < p.bottom;
                    const chip = box(slide.querySelector('.look-pic .ai-chip')), dots = [...slide.querySelectorAll('.spot')].map(box);
                    return {top: picture.top, left: picture.left, right: picture.right, picture_bottom: picture.bottom,
                            bottom: Math.max(picture.bottom, ...dots.map(d => d.bottom)),
                            line: Math.max(...words.map(r => r.bottom)), line_top: Math.min(...words.map(r => r.top)),
                            on_picture: words.every(r => r.left >= picture.left && r.right <= picture.right && r.top >= picture.top && r.bottom <= picture.bottom + 0.5),
                            veil: Math.min(...veil), crossed: words.some(r => meet(r, chip) || dots.some(d => meet(r, d))),
                            header: box(document.querySelector('header.top')).bottom,
                            budget: !!document.getElementById('summary') && getComputedStyle(document.getElementById('summary')).display !== 'none',
                            row: box(document.querySelector('.toolbar')).top,
                            tabs: box(document.querySelector('nav.tabs')).top,
                            // The bar with the two answers stands over the tab bar on a phone (app.js 17a): its top.
                            dock: box(document.getElementById('dock')).top};
                }""")

            def rings_whole(other, where: str) -> None:
                # ('Add to my wardrobe' stands in the bar over the tab bar on a phone: its ring is whole inside the bar.)
                for what in (".btn.yes", ".about-actions a"):
                    other.keyboard.press("Tab")             # a key was pressed: focus from here on shows its ring
                    ring = other.evaluate("""([s, docked]) => {
                        const el = document.querySelector(s) || document.querySelector(docked);
                        el.focus();
                        el.scrollIntoView({block: 'center'});
                        const style = getComputedStyle(el), r = el.getBoundingClientRect();
                        const row = (el.closest('#dock') || document.getElementById('reel')).getBoundingClientRect();
                        const reach = parseFloat(style.outlineWidth) + parseFloat(style.outlineOffset);
                        return {shown: el.matches(':focus-visible') && style.outlineStyle !== 'none',
                                cut: [['left', r.left - reach < row.left], ['top', r.top - reach < row.top],
                                      ['right', r.right + reach > row.right], ['bottom', r.bottom + reach > row.bottom]]
                                     .filter(side => side[1]).map(side => side[0])};
                    }""", [f"{first} {what}", f"#dock {what}"])
                    assert ring["shown"] and not ring["cut"], f"{where}: the focus ring of {what} is cut off at {ring['cut']}"

            # At 390 x 844 the picture starts right under the header and is as wide as the page (358px), the whole model
            # above the bar with the answers; the title and price on its lower edge, the chips and Shuffle right under it.
            context, other = opened(390, 844, True)
            seen = screen(other)
            wide = other.locator(f"{first} .look-pic").bounding_box()["width"]
            assert seen["top"] <= seen["header"] + 8, f"at 390 x 844 something stands between the header and the picture: {seen}"
            assert wide >= 358 - 0.5, f"at 390 x 844 the picture is only {wide:.0f}px wide, not the page's 358px"
            assert seen["bottom"] <= seen["dock"] + 1 <= seen["tabs"] + 1, \
                f"at 390 x 844 the picture ends at {seen['bottom']:.0f}px, under the bar with the answers at {seen['dock']:.0f}px"
            assert not seen["budget"], "on a phone the budget bar still stands over the outfits"
            assert seen["on_picture"] and seen["line"] >= seen["picture_bottom"] - 60, \
                f"at 390 x 844 the outfit's title and price are not on the picture's lower edge: {seen}"
            assert seen["veil"] >= 4.5, f"at 390 x 844 the title or price on the picture is {seen['veil']:.1f}:1 over a white picture"
            assert not seen["crossed"], f"at 390 x 844 the title or price covers a dot or the label 'AI picture': {seen}"
            assert seen["picture_bottom"] <= seen["row"] <= seen["picture_bottom"] + 16, \
                f"at 390 x 844 the chips and Shuffle are not right under the picture: {seen}"
            chip = other.locator(f"{first} .look-pic .ai-chip").bounding_box()
            assert chip["height"] <= 26, f"at 390 x 844 the 'AI picture' label is {chip['height']:.0f}px high: two lines"
            row = other.evaluate("""() => {
                const chips = document.querySelector('.toolbar .chips'), items = [...chips.children, document.querySelector('.toolbar .shuffle')];
                const boxes = items.map(el => el.getBoundingClientRect()), shuffle = boxes[boxes.length - 1];
                return {rows: new Set(boxes.map(b => Math.round(b.top + b.height / 2))).size,
                        inside: boxes.every(b => b.left >= 0 && b.right <= innerWidth) && boxes.slice(0, -1).every(b => b.right <= shuffle.left),
                        group: chips.getAttribute('role'),
                        current: [...chips.querySelectorAll('[aria-current=page]')].map(a => a.classList.contains('on') && a.textContent.trim())};
            }""")
            assert row["rows"] == 1 and row["inside"], f"at 390px the chips and Shuffle are not one row on the screen: {row}"
            assert row["group"] == "group" and len(row["current"]) == 1 and row["current"][0], f"the chip that is on is not marked: {row}"
            lead = other.locator(".lead").inner_text()
            assert "swipe" in lead and "arrow" not in lead and "←" not in lead, f"on a touch screen the line over the outfits reads {lead!r}"
            assert not other.locator(".reel-nav").first.is_visible() and not other.locator(".reel-nav").last.is_visible(), \
                "on a touch screen the arrows show over the outfits, which are swiped"
            buy, pieces = other.locator(f"{first} .about-actions a").bounding_box(), other.locator(f"{first} .pieces").bounding_box()
            assert buy["height"] >= 48 and abs(buy["width"] - pieces["width"]) < 1, \
                f"at 390px 'Buy this outfit' is {buy['width']:.0f} x {buy['height']:.0f}px, the list {pieces['width']:.0f}px wide"
            rings_whole(other, "390 x 844")
            other.goto(base + "/outfits?occasion=office", wait_until="networkidle")
            heads = other.evaluate("""() => ({h1: document.querySelectorAll('h1').length,
                slides: document.querySelectorAll('#reel .slide:not(.more-slide)').length,
                titles: [...document.querySelectorAll('#reel .slide:not(.more-slide) .about-head > h2')].map(h => h.firstChild.textContent.trim())})""")
            assert heads["h1"] == 1 and len(heads["titles"]) == heads["slides"] > 0, f"one main heading and one per outfit: {heads}"
            assert "Smart casual" not in heads["titles"], f"under Office an outfit is titled only 'Smart casual': {heads['titles']}"
            context.close()

            # Shorter phones (360 x 740, 393 x 760, 390 x 664, 375 x 667, 360 x 640, 320 x 568: a phone with the
            # browser's bars showing). The picture is as large as the screen allows: as tall as the screen less 220px
            # (the header, the bar with the answers at its tallest, the tab bar and a little room), or as wide as the
            # page, so 296 by 444px at least on 390 x 664 (309 by 463px where no outfit on the page says it would take
            # him over his budget); the whole model and its lowest dot above the bar with the answers; the title and
            # price on the picture, with the label 'AI picture' on one line; the bar is compact (one line of what a yes
            # adds, two with the budget's words, then the answers), 'Add to my wardrobe' whole in it above the tab
            # bar; and the chips all show beside Shuffle.
            for width, height in ((360, 740), (393, 760), (390, 664), (375, 667), (360, 640), (320, 568)):
                context, other = opened(width, height, True)
                seen = screen(other)
                seen.update(other.evaluate("""() => {
                    const slide = document.querySelector('#reel .slide:first-child'), box = el => el.getBoundingClientRect();
                    return {picture: [box(slide.querySelector('.look-pic')).width, box(slide.querySelector('.look-pic')).height],
                            chip: box(slide.querySelector('.look-pic .ai-chip')).height,
                            yes: [box(document.querySelector('#dock .btn.yes')).top, box(document.querySelector('#dock .btn.yes')).bottom],
                            bar: box(document.getElementById('dock')).height,
                            chips: [document.querySelector('.toolbar .chips').scrollWidth, document.querySelector('.toolbar .chips').clientWidth],
                            last_chip: [...document.querySelectorAll('.toolbar .chip-link')].pop().textContent.trim().replace(/\\s+/g, ' ')}; }"""))
                context.close()
                where = f"at {width} x {height}"
                if width > 320:     # (at 320px the chips scroll sideways in their row: checked below)
                    assert seen["last_chip"].startswith("My outfits") and seen["chips"][0] <= seen["chips"][1], \
                        f"{where} the chip {seen['last_chip']!r} is cut off beside Shuffle: the chips need {seen['chips'][0]}px and have {seen['chips'][1]}px"
                least = min(width - 32, (height - 220) * 2 / 3) - 1
                assert seen["picture"][0] >= least and abs(seen["picture"][1] - seen["picture"][0] * 3 / 2) < 1, \
                    f"{where} the picture is {seen['picture'][0]:.0f} by {seen['picture'][1]:.0f}px, under {least:.0f}px wide or not 2 by 3"
                assert seen["top"] <= seen["header"] + 8 and seen["bottom"] <= seen["dock"] + 1, \
                    f"{where} the picture does not start under the header, or ends under the bar with the answers: {seen}"
                assert not seen["budget"] and seen["on_picture"] and seen["veil"] >= 4.5 and not seen["crossed"], \
                    f"{where} the budget bar shows, or the title and price are not on the picture, readable and clear: {seen}"
                assert seen["chip"] <= 26, f"{where} the 'AI picture' label is on two lines: {seen}"
                assert seen["dock"] <= seen["tabs"] + 1 and seen["dock"] <= seen["yes"][0] and seen["yes"][1] <= seen["tabs"], \
                    f"{where} 'Add to my wardrobe' is not whole in its bar above the tab bar: {seen}"
                assert seen["bar"] <= 100, f"{where} the bar with the answers is {seen['bar']:.0f}px high: not compact"

            # With the "Demo data" notice (invented products): on a phone it is one short line under the row of words,
            # "Demo data — invented items." (the rest still read out), and costs the picture nothing: the picture is as
            # large as without it, and the picture's own line comes after the notice.
            for width, height in ((390, 664), (320, 568)):
                context, other = opened(width, height, True, demo=True)
                seen = screen(other)
                seen.update(other.evaluate("""s => { const box = el => el.getBoundingClientRect(), demo = document.querySelector('main .demo');
                    // What shows: the notice without the part that only a screen reader reads (1px, clipped).
                    const shown = demo && demo.cloneNode(true), rest = demo && demo.querySelector('.demo-more');
                    if (rest && box(rest).width <= 1) shown.querySelector('.demo-more').remove();
                    return {demo: demo && [box(demo).top, box(demo).bottom, box(demo).height, shown.textContent.trim(), demo.textContent.trim()],
                            row_bottom: box(document.querySelector('.toolbar')).bottom, line_top: box(document.querySelector(s + ' .look-line')).top,
                            wide: box(document.querySelector(s + ' .look-pic')).width}; }""", first))
                context.close()
                where = f"at {width} x {height} with the demo notice"
                assert seen["demo"] and seen["demo"][3] == "Demo data — invented items." \
                    and seen["demo"][4] == "Demo data — invented items, not real products, prices or stock." and seen["demo"][2] <= 40, \
                    f"{where}: the notice is not one short line that still says it all to a screen reader: {seen['demo']}"
                assert seen["row_bottom"] <= seen["demo"][0] and seen["demo"][1] <= seen["line_top"], \
                    f"{where}: the notice is not under the row of words, above the picture's own line: {seen}"
                assert seen["wide"] >= min(width - 32, (height - 220) * 2 / 3) - 1 and seen["bottom"] <= seen["dock"] + 1, \
                    f"{where}: the notice took room from the picture, or the picture ends under the bar with the answers: {seen}"

            # The longest name, "Everyday, smart casual", on the narrowest phone: on the picture, clear of the dots and of
            # the label, readable.
            context, other = opened(320, 568, True, "/outfits?occasion=everyday")
            seen = screen(other)
            context.close()
            assert seen["on_picture"] and not seen["crossed"] and seen["veil"] >= 4.5, \
                f"at 320 x 568 under Everyday the title or price is off the picture, on a dot or the label, or hard to read: {seen}"

            context, other = opened(390, 664, True, "/outfits?at=no~such~outfit")
            seen = screen(other)
            message = other.locator("main > .flash").first.bounding_box()
            assert message and 0 <= message["y"] and message["y"] + message["height"] <= seen["dock"], \
                f"the message at the top of the outfits is not whole on the first screen: {message}"
            assert seen["line"] <= seen["dock"] and seen["bottom"] <= seen["dock"] + 1, \
                f"under a message the outfit's picture, or its name, ends under the bar with the answers: {seen}"
            context.close()

            context, other = opened(360, 800, True)
            narrow = other.evaluate("""() => {
                const chips = document.querySelector('.toolbar .chips'), last = chips.lastElementChild;
                const rows = new Set([...chips.children].map(c => Math.round(c.getBoundingClientRect().top))).size;
                chips.scrollLeft = chips.scrollWidth;
                const a = last.getBoundingClientRect(), b = chips.getBoundingClientRect();
                return {rows, last_in_reach: a.left >= b.left && a.right <= b.right, page: document.documentElement.scrollWidth};
            }""")
            assert narrow["rows"] == 1 and narrow["last_in_reach"] and narrow["page"] <= 360, \
                f"at 360px the chips do not scroll sideways in one row, or the page is wider than the screen: {narrow}"
            # By keyboard too: with the row back at its start, Tab to the last chip (Saved, partly outside the row),
            # then Shift+Tab back to the first: each comes whole into the row, its focus ring included.
            other.evaluate("() => { document.querySelector('.toolbar .chips').scrollLeft = 0; document.activeElement.blur(); }")
            for key, which in (("Tab", "lastElementChild"), ("Shift+Tab", "firstElementChild")):
                for _ in range(40):
                    other.keyboard.press(key)
                    if other.evaluate(f"() => document.activeElement === document.querySelector('.toolbar .chips').{which}"):
                        break
                ring = other.evaluate("""() => {
                    const el = document.activeElement, row = document.querySelector('.toolbar .chips');
                    if (!row.contains(el)) return {chip: null};
                    const style = getComputedStyle(el), r = el.getBoundingClientRect(), b = row.getBoundingClientRect();
                    const reach = parseFloat(style.outlineWidth) + parseFloat(style.outlineOffset);
                    return {chip: el.textContent.trim(), shown: el.matches(':focus-visible') && style.outlineStyle !== 'none',
                            cut: [['left', r.left - reach < b.left - 0.5], ['right', r.right + reach > b.right + 0.5],
                                  ['top', r.top - reach < b.top - 0.5], ['bottom', r.bottom + reach > b.bottom + 0.5]]
                                 .filter(side => side[1]).map(side => side[0])};
                }""")
                assert ring["chip"] and ring["shown"] and not ring["cut"], \
                    f"at 360px, after {key}, the focus ring of the chip {ring['chip']!r} is cut off by the chip row: {ring}"
            context.close()

            context, other = opened(1280, 900, False)
            lead = other.locator(".lead").inner_text()
            assert "arrows" in lead and "swipe" not in lead.lower(), f"with a mouse the line over the outfits reads {lead!r}"
            rings_whole(other, "1280 x 900")
            context.close()

        def budget_bar_never_hides_the_focus():
            # On a phone the budget bar is one line, and it sticks to the top only where that helps: not over the
            # outfits, and not on a screen under 520px tall. What has keyboard focus is never hidden under it or
            # under the tab bar (WCAG 2.4.11): three pages are tabbed through forwards on a phone and backwards on a
            # computer, so that each new focus comes in from below and from above, and at least one of five points
            # of it must be on the screen with neither bar over it. The bar's budget leads to the field on Profile,
            # which takes any whole number: with steps of 10 it refused 999 with a bubble of the browser's own.
            def logged_in(width: int, height: int, phone: bool):
                context = browser.new_context(viewport={"width": width, "height": height}, is_mobile=phone, has_touch=phone)
                other = context.new_page()
                other.goto(base + "/login", wait_until="networkidle")
                other.fill("input[name=email]", EMAIL)
                other.fill("input[name=password]", PASSWORD)
                other.click("button:has-text('Log in')")
                other.wait_for_load_state("networkidle")
                return context, other

            def sticks(other, path: str) -> bool:
                other.goto(base + path, wait_until="networkidle")
                other.evaluate("() => window.scrollTo(0, 400)")
                return other.evaluate("() => { const r = document.getElementById('summary').getBoundingClientRect(); return r.top === 0 && r.height > 0; }")

            hidden: list[str] = []
            # Profile shows one tab's controls at a time, with the middle, the tabs and Save staying in place: each tab.
            profile_tabs = ["/profile"] + [f"/profile#{name}" for name in ("body", "sizes", "colours", "budget")]

            def tab_through(other, path: str, key: str) -> None:
                address, _, tab = path.partition("#")
                other.goto("about:blank")              # (a new page each time, also for Profile's tabs one after another)
                other.goto(base + address, wait_until="networkidle")
                if tab:
                    # A tab of Profile opened as a tap opens it (a link to #sizes would start the keyboard at Sizes,
                    # past the top of the page); its scroll at once, so that nothing moves while the focus is measured.
                    other.emulate_media(reduced_motion="reduce")
                    other.evaluate("name => document.getElementById('tab-' + name).click()", tab)
                    other.emulate_media(reduced_motion="no-preference")
                stops = 0
                for _ in range(400):
                    other.keyboard.press(key)
                    focus = other.evaluate("""() => {
                        const el = document.activeElement;
                        if (!el || el === document.body) return null;          // out of the page, past its last stop
                        if (el.dataset.walked) return 'again';                 // all the way round
                        el.dataset.walked = '1';
                        // (On Profile the middle, its tabs and Save stay in place too, on a phone.)
                        const bars = [document.getElementById('summary'), document.querySelector('nav.tabs'),
                                      ...document.querySelectorAll('.cc-stage, .cc-tabs, .cc-save')].filter(Boolean);
                        const r = el.getBoundingClientRect();
                        const points = [[r.left + r.width / 2, r.top + r.height / 2], [r.left + 1, r.top + 1],
                                        [r.right - 1, r.top + 1], [r.left + 1, r.bottom - 1], [r.right - 1, r.bottom - 1]];
                        const seen = points.filter(([x, y]) => {
                            if (x < 0 || y < 0 || x >= innerWidth || y >= innerHeight) return false;
                            const top = document.elementFromPoint(x, y);
                            return top && !bars.some(bar => bar.contains(top) && !bar.contains(el));
                        }).length;
                        return {seen, name: (el.tagName.toLowerCase() + (el.id ? '#' + el.id : '') + ' '
                                             + (el.innerText || el.value || el.name || '')).trim().slice(0, 50)};
                    }""")
                    if focus == "again" or (focus is None and stops):
                        break
                    if focus:
                        stops += 1
                        if not focus["seen"]:
                            hidden.append(f"{path} {key}: {focus['name']}")
                assert stops >= 10, f"tabbing through {path} met only {stops} things to focus"

            context, other = logged_in(390, 844, True)
            other.goto(base + "/", wait_until="networkidle")
            bar = other.evaluate("""() => {
                const line = document.querySelector('#summary .nums').cloneNode(true);
                line.querySelectorAll('.lbl').forEach(label => label.remove());     // hidden on a phone, read out
                return {height: document.getElementById('summary').getBoundingClientRect().height,
                        line: line.textContent.replace(/[ \\n]+/g, ' ').trim().replace(/\\u00a0/g, ' ')};
            }""")
            assert bar["height"] <= 52, f"on a phone the budget bar is {bar['height']}px tall"
            assert re.fullmatch(r"[\d,.]+ € of [\d,.]+ € · ([\d,.]+ € left|Over by [\d,.]+ €)", bar["line"]), \
                f"on a phone the budget bar reads {bar['line']!r}"
            assert sticks(other, "/") and sticks(other, "/list"), "the budget bar does not stay at the top of Wardrobe and Shopping"
            assert not sticks(other, "/outfits"), "the budget bar stays over the outfits"
            other.set_viewport_size({"width": 390, "height": 480})
            assert not sticks(other, "/"), "the budget bar sticks on a screen 480px tall"
            other.set_viewport_size({"width": 390, "height": 844})
            for path in ("/", "/list", *profile_tabs):
                tab_through(other, path, "Tab")
            other.goto(base + "/", wait_until="networkidle")
            other.locator("#summary a").click()
            other.wait_for_url(base + "/profile#budget")
            other.fill("#budget", "999")
            assert other.eval_on_selector("#budget", "i => i.checkValidity()"), "the budget field refuses 999"
            other.click("button:has-text('Save profile')")
            other.wait_for_load_state("networkidle")
            assert "of 999 €" in other.locator("#summary").inner_text().replace("\xa0", " "), "a budget of 999 € was not saved"
            context.close()
            context, other = logged_in(1280, 900, False)
            for path in ("/", "/list", *profile_tabs):
                tab_through(other, path, "Shift+Tab")
            context.close()
            assert not hidden, "hidden under the bars or off the screen while it had keyboard focus: " + "; ".join(hidden[:6])

        def a_pieces_page_by_keyboard():
            # On a piece's page the buttons stay where they are and keep keyboard focus: after 'Lock this choice' it is
            # on the same button, now 'Unlock'; after 'Choose this' on the mark that replaces it, and the next Tab
            # goes on through that option, not to the footer. What pasted links came to is said inside the 'Add a
            # product by link' section the page comes back to, on the screen, with JavaScript on and off. The piece
            # used is one Stilsmith picks (not the one swapped earlier), and it is left that way.
            ACTIVE = "() => ({id: document.activeElement.id, text: document.activeElement.textContent.replace(/\\s+/g, ' ').trim()})"
            # HTMX puts the new part of the page in at once and hooks up its buttons a moment later (its "settle", about
            # 20 ms): a key pressed in between sends the form without HTMX. A person never presses that fast; the
            # walk-through waits for it, as it waits for the new words.
            SETTLED = "() => !document.querySelector('.htmx-request, .htmx-swapping, .htmx-settling')"
            page.goto(base + "/", wait_until="networkidle")
            pieces = [href for href in page.locator("a[href^='/slot/']").evaluate_all("as => as.map(a => a.getAttribute('href'))")
                      if href.split("?")[0].split("#")[0].split("/")[2] != swapped.get("slot")]
            for href in pieces:
                page.goto(base + href.split("#")[0], wait_until="networkidle")
                if page.locator("#slot-lock", has_text="Lock this choice").count() and page.locator("button[id^=choose-]").count():
                    break
            else:
                raise AssertionError("no piece that Stilsmith picks, with another option to choose")
            address = page.url
            page.locator("#slot-lock").focus()
            page.keyboard.press("Enter")
            page.wait_for_selector("#slot-lock:has-text('Unlock')")
            page.wait_for_function(SETTLED)
            page.wait_for_load_state("networkidle")
            seen = page.evaluate(ACTIVE)
            assert seen == {"id": "slot-lock", "text": "Unlock (back to automatic)"}, f"after Lock this choice focus is on {seen}"
            page.keyboard.press("Enter")
            page.wait_for_selector("#slot-lock:has-text('Lock this choice')")
            page.wait_for_function(SETTLED)
            page.wait_for_load_state("networkidle")
            seen = page.evaluate(ACTIVE)
            assert seen == {"id": "slot-lock", "text": "Lock this choice"}, f"after Unlock focus is on {seen}"
            choose = page.locator("button[id^=choose-]").first
            option = choose.get_attribute("id")
            choose.focus()
            page.keyboard.press("Enter")
            page.wait_for_selector(f"span#{option}")
            page.wait_for_function(SETTLED)
            page.wait_for_load_state("networkidle")
            seen = page.evaluate(ACTIVE)
            assert seen["id"] == option and seen["text"] in ("Current pick", "Chosen and locked"), \
                f"after Choose this focus is on {seen}, not on the mark that replaced it"
            page.keyboard.press("Tab")
            inside = page.evaluate("id => document.activeElement.closest('.cand') === document.getElementById(id).closest('.cand')", option)
            assert inside, f"the Tab after choosing leaves the option for {page.evaluate(ACTIVE)}"
            page.locator("#slot-lock").focus()                     # back to what Stilsmith picks
            page.keyboard.press("Enter")
            page.wait_for_selector("#slot-lock:has-text('Lock this choice')")
            page.wait_for_function(SETTLED)
            page.wait_for_load_state("networkidle")

            for javascript in (True, False):
                context = browser.new_context(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True,
                                              java_script_enabled=javascript)
                try:
                    phone = context.new_page()
                    # (As on the main page: one picture of the demo catalogue is missing on purpose.)
                    phone.on("response", lambda r: failures.append(f"{r.status} {r.request.method} {r.url.replace(base, '')[:100]}")
                             if r.status >= 400 and r.url.startswith(base) and "does-not-exist" not in r.url else None)
                    phone.goto(base + "/login", wait_until="networkidle")
                    phone.fill("input[name=email]", EMAIL)
                    phone.fill("input[name=password]", PASSWORD)
                    phone.click("button:has-text('Log in')")
                    phone.wait_for_load_state("networkidle")
                    phone.goto(address, wait_until="networkidle")
                    phone.fill("#add textarea[name=urls]", "https://shop.example.org/jumper")
                    phone.locator("#add button", has_text="Add").click()
                    phone.wait_for_load_state("networkidle")
                    said = phone.evaluate("""() => {
                        const bar = document.querySelector('#summary'), tabs = document.querySelector('nav.tabs');
                        const top = bar && getComputedStyle(bar).position === 'sticky' ? bar.getBoundingClientRect().bottom : 0;
                        const bottom = tabs && getComputedStyle(tabs).position === 'fixed' ? tabs.getBoundingClientRect().top : innerHeight;
                        return [...document.querySelectorAll('main .flash')].map(m => {
                            const b = m.getBoundingClientRect();
                            return {words: m.textContent.trim(), inside: !!m.closest('#add'), status: m.getAttribute('role'),
                                    shown: b.top >= top - 1 && b.bottom <= bottom + 1};
                        });
                    }""")
                    assert said == [{"words": "Not added: “https://shop.example.org/jumper” is not a link to one of the "
                                              "stores listed above.", "inside": True, "status": "status", "shown": True}], \
                        f"with JavaScript {'on' if javascript else 'off'} the rejected link is answered: {said}"
                finally:
                    context.close()

            # A link from Hirmer, a store with no products yet, with its page as the customer saved it (an invented
            # page, tests/fixtures/pages): its name and price are filled in from the file, the option shows no photo,
            # and no store is asked for anything. A women's link is refused in one sentence. Menswear only.
            context = browser.new_context(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
            try:
                phone = context.new_page()
                asked_of: list[str] = []
                phone.on("request", lambda r: asked_of.append(r.url))
                phone.on("dialog", lambda d: d.accept())
                phone.on("pageerror", lambda e: failures.append(f"script error: {e}"))
                phone.goto(base + "/login", wait_until="networkidle")
                phone.fill("input[name=email]", EMAIL)
                phone.fill("input[name=password]", PASSWORD)
                phone.click("button:has-text('Log in')")
                phone.wait_for_load_state("networkidle")
                phone.goto(address, wait_until="networkidle")
                words = " ".join(phone.locator("#add").inner_text().split())
                assert "Menswear only." in words and "Hirmer" in words, f"the link form does not name its stores: {words[:200]}"
                phone.fill("#add textarea[name=urls]", "https://www.hirmer.de/herren/hemden/oxford-hemd-regular-fit-hellblau/p/9000001")
                phone.set_input_files("#add input[name=page]", str(ROOT / "tests" / "fixtures" / "pages" / "mens-shirt.html"))
                phone.locator("#add button", has_text="Add").click()
                phone.wait_for_load_state("networkidle")
                said = phone.locator("#add .flash").all_inner_texts()
                # (On a piece that is not worn where a shirt is, such as the coat, the answer goes on to say that
                # its name says "Shirt" and how to move it: the link is added all the same. tests/test_menswear.py)
                read = ("Added “Oxford-Hemd Regular Fit”: its name, price, colour and fabric were read from the page "
                        "you saved — add the sizes under “Add details”.")
                kind = re.compile(r" Check the kind: its name says “Shirt”, and this piece is “[^”]+”\. If it belongs "
                                  r"to another piece, remove it here and paste the link there\.")
                assert len(said) == 1 and said[0].startswith(read) and (said[0] == read or kind.fullmatch(said[0][len(read):])), \
                    f"a Hirmer link with its saved page: {said}"
                expect(phone.locator("#add .flash")).to_be_in_viewport()
                card = phone.locator("#cand-hirmer-9000001")
                shown = " ".join(card.inner_text().split())
                assert "hirmer" in shown.lower() and "Oxford-Hemd Regular Fit" in shown and "49.99 €" in shown, \
                    f"the option shows: {shown[:200]}"
                assert not card.locator("img").count(), "an option added by its link shows a store's photo"
                assert phone.evaluate("document.documentElement.scrollWidth <= innerWidth"), "the piece's page is wider than the phone"
                women = "https://www.tom-tailor.de/damen/jacken/steppjacke-1041235_10668"
                phone.fill("#add textarea[name=urls]", women)
                phone.locator("#add button", has_text="Add").click()
                phone.wait_for_load_state("networkidle")
                said = phone.locator("#add .flash").all_inner_texts()
                assert said == [f"Not added: “{women}” looks like a women's product, and Stilsmith is for menswear only."], said
                expect(phone.locator("#add .flash")).to_be_in_viewport()
                # Only the product's name holds such a word (a band's shirt): not refused. The page asks, and one tap
                # on "Add it anyway" adds it.
                band = "https://www.hirmer.de/beastie-boys-shirt/p/9000077"
                phone.fill("#add textarea[name=urls]", band)
                phone.locator("#add button", has_text="Add").first.click()
                phone.wait_for_load_state("networkidle")
                said = phone.locator("#add .flash.ask p").all_inner_texts()
                assert said == [f"“{band}” is not added yet. Its name says “boys”: this may be a children's product. "
                                "Add it anyway?"], f"a link whose name says 'boys' is answered: {said} {phone.locator('#add .flash').all_inner_texts()}"
                assert not phone.locator("#cand-hirmer-9000077").count(), "the link was added before he answered"
                anyway = phone.locator("#add .flash.ask button", has_text="Add it anyway")
                expect(anyway).to_be_in_viewport()
                assert anyway.bounding_box()["height"] >= 40, f"'Add it anyway' is {anyway.bounding_box()['height']}px high"
                assert phone.evaluate("document.documentElement.scrollWidth <= innerWidth"), "the question makes the page wider than the phone"
                with phone.expect_navigation():
                    anyway.tap()
                phone.wait_for_load_state("networkidle")
                said = phone.locator("#add .flash").all_inner_texts()
                assert len(said) == 1 and said[0].startswith("Added “Beastie boys shirt”: only the link could be read"), \
                    f"'Add it anyway' is answered: {said}"
                assert phone.locator("#cand-hirmer-9000077").count() == 1, "'Add it anyway' did not add the product"
                phone.locator("#cand-hirmer-9000077 button", has_text="Remove").click()     # as it was, for the next steps
                phone.wait_for_load_state("networkidle")
                phone.locator("#cand-hirmer-9000001 button", has_text="Remove").click()
                phone.wait_for_load_state("networkidle")
                assert not phone.locator("#cand-hirmer-9000001, #cand-hirmer-9000077").count(), \
                    "the options added by their links were not removed"
                stores = ("hirmer.de", "tom-tailor.de", "otto.de", "breuninger.com", "blue-tomato.com", "bergfreunde.de")
                reached = [url for url in asked_of if any(store in url.split("/")[2] for store in stores)]
                assert not reached, f"a store was asked for something: {reached}"
            finally:
                context.close()

        def options_fit_three_phones():
            # On a piece's page, each option's "Choose this" and "Open at COS" sit on one line wherever the two and the
            # 8px between them fit the option's width ("Open at COS" does on a 390px phone), and on two lines where they
            # do not, never one over the other, and never out of the option's box: at 320, 360 and 390. The demo data
            # links to no store, so a small list is published for this step (as for the one-tap colour): three grey
            # jumpers, two at COS and one at Weekday, for a new customer whose starter plan has a grey jumper.
            jumper = {"category": "knit", "currency": "EUR", "composition_text": "100% Wolle", "fit": "regular",
                      "sizes_all": ["S", "M", "L"], "sizes_in_stock": ["S", "M", "L"], "image_url": "", "source": "collected",
                      "colour": "Grau", "colour_hex": None}
            products = [{**jumper, "id": f"{store}-8{n}", "store": store, "name": f"Pullover aus Wolle {n}",
                         "slug": f"pullover-8{n}", "price": 49.95 + 10 * n, "url": f"https://www.example.com/de/8{n}"}
                        for n, store in enumerate(("cos", "cos", "weekday"))]
            listed = DATA / "store_catalog.json"
            listed.write_text(json.dumps({"published_at": "2026-11-12T12:00:00+01:00",
                                          "collected_at": "2026-11-11T17:00:00+01:00", "stores": {}, "products": products}))
            ROWS = """() => [...document.querySelectorAll('.cand .cand-body > .cand-actions')].map(row => {
                const choose = row.querySelector('button.btn'), open = row.querySelector('a.extlink');
                if (!choose || !open) return null;
                const a = choose.getBoundingClientRect(), b = open.getBoundingClientRect();
                const card = row.closest('.cand').getBoundingClientRect();
                return {open: open.firstChild.textContent.trim(), fits: a.width + 8 + b.width <= row.clientWidth + 0.5,
                        one_line: b.top < a.bottom && a.top < b.bottom,
                        over: a.left < b.right && b.left < a.right && a.top < b.bottom && b.top < a.bottom,
                        inside: Math.max(a.right, b.right) <= card.right + 0.5 && Math.min(a.left, b.left) >= card.left - 0.5};
            }).filter(Boolean)"""
            who, problems = "options-" + EMAIL, []
            try:
                for width in (320, 360, 390):
                    context = browser.new_context(viewport={"width": width, "height": 800}, is_mobile=True, has_touch=True)
                    try:
                        phone = context.new_page()
                        phone.goto(base + ("/signup" if width == 320 else "/login"), wait_until="networkidle")
                        phone.fill("input[name=email]", who)
                        phone.fill("input[name=password]", PASSWORD)
                        phone.click("button:has-text('Create account')" if width == 320 else "button:has-text('Log in')")
                        if width == 320:
                            a_customer_from_before(phone)
                        phone.wait_for_url(base + "/outfits")
                        phone.goto(base + "/slot/grey-merino-jumper", wait_until="networkidle")
                        rows = phone.evaluate(ROWS)
                        assert len(rows) == 2 and {row["open"] for row in rows} == {"Open at COS", "Open at Weekday"}, \
                            f"at {width}px the grey jumper's other options are {rows}"
                        for row in rows:
                            if row["over"] or not row["inside"] or row["fits"] != row["one_line"]:
                                problems.append(f"{width}px {row}")
                        if width == 390:
                            assert any(row["one_line"] for row in rows if row["open"] == "Open at COS"), \
                                f"at 390px 'Open at COS' is not beside 'Choose this': {rows}"
                    finally:
                        context.close()
            finally:
                listed.unlink(missing_ok=True)
            assert not problems, "an option's two actions are laid out badly: " + "; ".join(problems[:4])

        def the_plan_answers_next_to_the_piece():
            # After adding a piece to the plan, or saving one, the plan page lands on that piece (#slot-<its id>): what
            # it came to is said inside that piece, on a phone's screen, not at the page's top. The piece added here
            # is removed again; that message is said at the top, as the piece has gone.
            context, phone = logged_in_on(browser, viewport={"width": 360, "height": 640}, is_mobile=True, has_touch=True)
            phone.on("dialog", lambda d: d.accept())       # "Remove … from your plan?"
            SAID = """() => {
                const bar = document.querySelector('#summary'), tabs = document.querySelector('nav.tabs');
                const top = bar && getComputedStyle(bar).position === 'sticky' ? bar.getBoundingClientRect().bottom : 0;
                const bottom = tabs && getComputedStyle(tabs).position === 'fixed' ? tabs.getBoundingClientRect().top : innerHeight;
                return [...document.querySelectorAll('main .flash')].map(m => {
                    const b = m.getBoundingClientRect(), piece = m.closest('li');
                    return {words: m.textContent.trim(), piece: piece ? '#' + piece.id : null, status: m.getAttribute('role'),
                            shown: b.top >= top - 1 && b.bottom <= bottom + 1};
                });
            }"""
            try:
                phone.goto(base + "/slots", wait_until="networkidle")
                add = phone.locator("form[action$='/slots/add']")
                add.locator("input[name=name]").fill("Weekend overshirt")
                add.locator("button", has_text="Add piece").click()
                phone.wait_for_load_state("networkidle")
                hash_ = phone.evaluate("location.hash")
                assert hash_.startswith("#slot-"), f"after adding a piece the page is at {phone.url}, not at the piece"
                said = phone.evaluate(SAID)
                assert said == [{"words": "Added “Weekend overshirt” to your plan.", "piece": hash_, "status": "status",
                                 "shown": True}], f"adding a piece is answered so: {said}"
                piece = phone.locator(hash_)
                piece.locator("summary").click()
                piece.locator("input[name=name]").fill("Olive weekend overshirt")
                piece.locator("button", has_text="Save").click()
                phone.wait_for_load_state("networkidle")
                said = phone.evaluate(SAID)
                assert said == [{"words": "Saved “Olive weekend overshirt”.", "piece": hash_, "status": "status",
                                 "shown": True}], f"saving a piece is answered so: {said}"
                piece = phone.locator(hash_)
                piece.locator("summary").click()
                piece.locator("button", has_text="Remove this piece").click()
                phone.wait_for_load_state("networkidle")
                said = phone.evaluate(SAID)
                assert [(m["words"], m["piece"]) for m in said] == [("Removed “Olive weekend overshirt” from your plan.", None)], \
                    f"removing the piece is answered so: {said}"
            finally:
                context.close()

        def delete_account():
            page.goto(base + "/account", wait_until="networkidle")
            page.locator("form[action$='/account/delete'] input[name=current]").fill(PASSWORD)
            page.click("button:has-text('Delete my account')")
            page.wait_for_load_state("networkidle")
            assert "deleted" in page.content(), "the account was not deleted"
            assert not any((DATA / "people").glob("*")) if (DATA / "people").exists() else True, "a photo was left behind"

        def owners_store_catalogues():
            # The owner's view of every store's catalogue (/stores, owner.py), with every store in config/feeds.toml
            # and the invented sample stores' feeds imported. A customer who is no owner gets the page that is not
            # there, and no link to it. Once marked as an owner, the Account page leads to it: the stores grouped by
            # network, each real one with its programme's page as a link that opens in a new tab, and the products,
            # no wider than a phone or a computer screen, every photo from the feed's own address and shown whole, a
            # filter that narrows the list. The samples' photo addresses (example.com, example.org) are answered here
            # with a stand-in, and no programme page is opened: nothing leaves this computer.
            from wardrobe import db
            from wardrobe.feeds import FORMATS, registry
            feeds = ROOT / "tests" / "fixtures" / "feeds"
            now = db.now_iso()
            listed = registry.load()
            real = [key for key, values in listed.items() if not values["rules"].get("sample")]
            for key, values in listed.items():     # (production leaves the samples out of `stores sync`)
                db.save_store(key, values)
                if key in real:
                    continue                         # a store with a programme, not applied to yet: no feed
                found = FORMATS[values["feed_format"]](feeds / Path(values["feed_location"]).name).rows
                for row in found:
                    row.update(imported_at=now, feed_updated_at=row["feed_updated_at"] or now)
                db.replace_products(key, found)
                db.note_store(key, error=None, feed_update=now, imported_at=now)
            stand_in_photo = picture(150, 200)

            def answered_here(route):
                if route.request.url.startswith(base):
                    return route.continue_()
                return route.fulfill(status=200, content_type="image/png", body=stand_in_photo)

            def logged_in_at(width: int, phone: bool):
                context = browser.new_context(viewport={"width": width, "height": 844}, is_mobile=phone, has_touch=phone)
                context.route("**/*", answered_here)
                other = context.new_page()
                other.goto(base + "/login", wait_until="networkidle")
                other.fill("input[name=email]", EMAIL)
                other.fill("input[name=password]", PASSWORD)
                other.click("button:has-text('Log in')")
                other.wait_for_load_state("networkidle")
                return context, other

            context, other = logged_in_at(1280, False)
            assert other.goto(base + "/stores").status == 404, "a customer who is no owner can open /stores"
            other.goto(base + "/account", wait_until="networkidle")
            assert not other.locator("a[href='/stores']").count(), "a customer who is no owner has a link to /stores"
            context.close()
            assert db.add_owner(EMAIL) == "added"
            try:
                for width, phone in ((390, True), (1280, False)):
                    context, other = logged_in_at(width, phone)
                    other.goto(base + "/account", wait_until="networkidle")
                    other.click("a:has-text('Open the store catalogues')")
                    other.wait_for_load_state("networkidle")
                    other.evaluate("() => document.querySelectorAll('img[loading=lazy]').forEach(i => i.loading = 'eager')")
                    other.wait_for_timeout(300)
                    seen = other.evaluate("""() => {
                        const imgs = [...document.querySelectorAll('.cat-pic img')];
                        const links = [...document.querySelectorAll('.cat-stores a.cat-link')];
                        const box = l => l.getBoundingClientRect();
                        return {path: location.pathname, wide: document.documentElement.scrollWidth,
                                stores: document.querySelectorAll('.cat-stores tbody tr').length,
                                groups: document.querySelectorAll('h3.cat-h3').length,
                                programmes: links.filter(l => l.target === '_blank' && l.rel.includes('noopener')
                                                              && l.href.startsWith('https://')).length,
                                tappable: links.every(l => box(l).height >= 24 && box(l).width >= 24),
                                rows: document.querySelectorAll('.cat-products tbody tr').length,
                                whole: imgs.every(i => getComputedStyle(i).objectFit === 'contain'),
                                loaded: imgs.filter(i => i.complete && i.naturalWidth > 0).length,
                                outside: imgs.filter(i => i.getAttribute('src').startsWith('/')).length};
                    }""")
                    assert seen.pop("wide") <= width + 1, f"the store catalogues are wider than {width}px"
                    assert seen == {"path": "/stores", "stores": len(listed), "groups": 8, "programmes": len(real),
                                    "tappable": True, "rows": 17, "whole": True, "loaded": 17, "outside": 0}, \
                        f"the store catalogues at {width}px: {seen}"
                    if not phone:
                        # A small laptop too: no store's table scrolls sideways in its box, and every store's notes
                        # are in view, whole and wide enough to read (at 960-1199px each under its store's row).
                        for narrow in (960, 1024, 1150, 1280):
                            other.set_viewport_size({"width": narrow, "height": 844})
                            fit = other.evaluate("""() => {
                                const boxes = [...document.querySelectorAll('.cat-scroll')];
                                const notes = [...document.querySelectorAll('.cat-stores .c-state')]
                                    .filter(n => n.querySelector('.cat-note'));
                                return {sideways: Math.max(...boxes.map(b => b.scrollWidth - b.clientWidth)),
                                        page: document.documentElement.scrollWidth,
                                        notes: notes.length,
                                        read: notes.filter(n => {
                                            const box = n.closest('.cat-scroll').getBoundingClientRect();
                                            const r = n.getBoundingClientRect();
                                            return r.left >= box.left && r.right <= box.right + 0.5 && r.width >= 240;
                                        }).length};
                            }""")
                            assert fit["sideways"] <= 0 and fit["page"] <= narrow and fit["notes"] > 20 \
                                and fit["read"] == fit["notes"], f"the stores' tables at {narrow}px: {fit}"
                        other.set_viewport_size({"width": width, "height": 844})
                    other.select_option("select[name=size]", "M")
                    other.click("button:has-text('Show')")
                    other.wait_for_load_state("networkidle")
                    shown = other.locator(".cat-products tbody tr").count()
                    assert shown == 5 and other.evaluate("document.documentElement.scrollWidth") <= width + 1, \
                        f"filtered to size M at {width}px: {shown} products (5 in the samples have M in stock)"
                    context.close()
            finally:
                db.remove_owner(EMAIL)

        def the_welcome_leads_to_the_style_chat():
            # Under the welcome's last step, "What you dress for", a plain line: "Or describe your style in your own
            # words" (the style chat is on here; a stand-in answers). It reads as a link, is large enough to tap, and
            # comes after "Show me outfits" and "Skip". Pressing it saves what he ticked, ends the welcome and opens
            # Profile at the chat, its message field on the screen: on a phone, on a computer and with JavaScript
            # off. Logging in later opens the outfits, not the welcome again. He has said yes to nothing, so when he
            # then uses a brief the page speaks of the pieces his outfits are made from and of no sum, and the bar at
            # the top still says his wardrobe is empty. Each customer is the step's own, deleted when it ends.
            words = "Or describe your style in your own words"
            for where, size, more in (("on a phone", (390, 844), {"is_mobile": True, "has_touch": True}),
                                      ("on a computer", (1280, 860), {}),
                                      ("without JavaScript", (390, 844), {"java_script_enabled": False})):
                who = f"welcome-chat-{size[0]}-{'plain' if 'java_script_enabled' in more else 'js'}-" + EMAIL
                context = browser.new_context(viewport={"width": size[0], "height": size[1]}, **more)
                try:
                    view = context.new_page()
                    view.on("pageerror", lambda e: failures.append(f"script error: {e}"))
                    view.on("response", lambda r: failures.append(f"{r.status} {r.request.method} {r.url.replace(base, '')[:100]}")
                            if r.status >= 400 and r.url.startswith(base) else None)
                    view.goto(base + "/signup", wait_until="networkidle")
                    view.fill("input[name=email]", who)
                    view.fill("input[name=password]", PASSWORD)
                    view.click("button:has-text('Create account')")
                    view.wait_for_url(base + "/welcome")
                    for step in (1, 2):
                        assert not view.get_by_text(words).count(), f"{where}: the welcome's step {step} offers the style chat"
                        if step == 2 and "has_touch" in more:
                            # The budget is on the first screen, above the colours: not below all 25 of them.
                            budget = view.evaluate("""() => { const b = document.querySelector('input[name=budget]').getBoundingClientRect();
                                return {bottom: b.bottom, colours: document.querySelector('.pick-colour').getBoundingClientRect().top,
                                        screen: innerHeight}; }""")
                            assert budget["bottom"] <= min(budget["colours"], budget["screen"]), \
                                f"{where}: the welcome's budget is under the colours or off the first screen: {budget}"
                        view.click("button:has-text('Skip')")
                        view.wait_for_load_state("networkidle")
                    view.wait_for_url(base + "/welcome/3")
                    line = view.get_by_role("button", name=words)
                    assert line.count() == 1, f"{where}: the welcome's last step does not offer the style chat"
                    seen = line.evaluate("""el => { const r = el.getBoundingClientRect(), style = getComputedStyle(el);
                        const go = document.querySelector('.welcome-go').getBoundingClientRect();
                        return {height: r.height, underlined: style.textDecorationLine.includes('underline'),
                                plain: style.backgroundColor === 'rgba(0, 0, 0, 0)' && style.borderTopWidth === '0px',
                                after: r.top >= go.bottom - 1, on_screen: r.top >= 0 && r.bottom <= innerHeight,
                                inside: r.left >= 0 && r.right <= innerWidth, wide: document.documentElement.scrollWidth}; }""")
                    assert seen["height"] >= 44, f"{where}: the line is {seen['height']:.0f}px high to tap"
                    assert seen["underlined"] and seen["plain"], f"{where}: the line does not read as a plain link: {seen}"
                    assert seen["after"] and seen["on_screen"] and seen["inside"] and seen["wide"] <= size[0], \
                        f"{where}: the line is not under the two buttons, whole on the first screen: {seen}"
                    assert "€" not in view.locator("body").inner_text(), f"{where}: a price on the welcome's last step"
                    view.locator("label:has(input[name=use][value=office])").click()
                    line.click()
                    view.wait_for_load_state("networkidle")
                    assert view.url == base + "/profile#style", f"{where}: the line leads to {view.url}"
                    field = view.locator("#style-chat .chat-say textarea")
                    expect(field).to_be_visible()
                    if "java_script_enabled" not in more:
                        expect(view.locator("#tab-you")).to_have_attribute("aria-selected", "true")
                        motion_ended(view)
                    at = field.evaluate("""el => { const r = el.getBoundingClientRect();
                        const over = document.elementFromPoint((r.left + r.right) / 2, (r.top + r.bottom) / 2);
                        return {top: Math.round(r.top), bottom: Math.round(r.bottom), screen: innerHeight,
                                reached: !!over && (over === el || el.contains(over))}; }""")
                    assert 0 <= at["top"] and at["bottom"] <= at["screen"] and at["reached"], \
                        f"{where}: the chat's message field is not on the screen he lands on, or something is over it: {at}"
                    assert view.locator("input[name=use][value=office]").is_checked(), f"{where}: what he ticked in the welcome was not saved"
                    bar = top_bar(view)["words"]
                    assert bar.startswith("Your wardrobe: nothing yet"), f"{where}: the bar on Profile reads {bar!r}"
                    if where == "on a phone":
                        # He describes his style and uses the brief. Nothing is in his wardrobe: no sum is said.
                        field.fill("street style, Berlin vibe")
                        view.locator("#style-chat .chat-say button").tap()
                        view.wait_for_selector("[data-brief=suggested]")
                        with view.expect_navigation(wait_until="networkidle"):
                            view.locator("button:has-text('Use this brief')").tap()
                        said = view.locator("#style-chat [data-style-said]").inner_text().replace("\xa0", " ")
                        assert re.fullmatch(r"Style brief saved\. Your brief changed \d+ of the pieces your outfits are made from\. "
                                            r"Your wardrobe is as it was\. See your outfits", " ".join(said.split())), \
                            f"a new customer who uses a brief is told: {said!r}"
                        assert "€" not in said, f"a sum for a customer with nothing in his wardrobe: {said!r}"
                        bar = top_bar(view)["words"]
                        assert bar.startswith("Your wardrobe: nothing yet"), f"after the brief the bar reads {bar!r}"
                    # The welcome is over: logging in again opens the outfits.
                    again = browser.new_context(viewport={"width": size[0], "height": size[1]})
                    try:
                        back = again.new_page()
                        back.goto(base + "/login", wait_until="networkidle")
                        back.fill("input[name=email]", who)
                        back.fill("input[name=password]", PASSWORD)
                        back.click("button:has-text('Log in')")
                        back.wait_for_load_state("networkidle")
                        assert back.url == base + "/outfits", f"{where}: after the line, logging in leads to {back.url}"
                    finally:
                        again.close()
                finally:
                    context.close()
                    delete_a_steps_customer(who)

        def the_style_chat():
            # Profile, "What do you dress for?": six styles to tick beside Everyday/Office/Both. Below, "Describe your
            # style": he writes in his own words, the assistant (a stand-in here) answers with one question back and a
            # suggested brief, and nothing changes until he presses "Use this brief". Then an outfit that is his style
            # as a whole says so in one line, and the others say nothing: no outfit titled Smart casual or Office is
            # called street. What "Use this brief", "Start again" and "Remove brief" did is said where the page comes
            # back to, on the screen without scrolling (a phone, a computer, and with JavaScript off), with what it did
            # to his pieces and his total. While a message is on its way the page says "Sending…"; after it the
            # keyboard is still in the message field, a screen reader hears the answer, and on a phone the answer, its
            # question and the field are on the screen together. A message that gets no answer back says so and
            # keeps his words. "No leather" leaves the leather shoes, says that they still go against the brief, and
            # no outfit with them says it fits. On a phone the line under an outfit's name is above the tab bar. What
            # he typed is shown as text, never as markup. On a phone and a computer nothing is wider than the screen.
            # A customer of his own, deleted when the step ends.
            who = "style-" + EMAIL
            whys = "() => [...document.querySelectorAll('[data-why]')].map(p => p.textContent.trim())"
            # Each outfit on the page: its title (Everyday, Smart casual, Office) and the line under it, if it has one.
            boards = """() => [...document.querySelectorAll('#reel [data-slide]')].filter(s => s.querySelector('.about-head h2')).map(s => ({
                title: s.querySelector('.about-head h2').firstChild.textContent.trim(),
                why: (s.querySelector('[data-why]') || {textContent: ''}).textContent.trim()}))"""
            # The sentence beside the brief that holds these words: whether all of it, and its link, are on the screen
            # as the page stands, with nothing over them (the tab bar, the Save bar, the figure that stays at the top).
            seen = """words => {
                const said = [...document.querySelectorAll('#style-chat [data-style-said]')].find(p => p.textContent.includes(words));
                if (!said) return {found: false, said: [...document.querySelectorAll('.flash')].map(p => p.textContent.trim())};
                const shows = el => { const r = el.getBoundingClientRect();
                    return r.top >= 0 && r.bottom <= innerHeight && r.left >= 0 && r.right <= innerWidth
                        && [[r.left + 3, r.top + 3], [r.right - 3, r.bottom - 3], [(r.left + r.right) / 2, (r.top + r.bottom) / 2]]
                            .every(([x, y]) => { const at = document.elementFromPoint(x, y); return !!at && said.contains(at); }); };
                const link = said.querySelector('a');
                return {found: true, text: said.innerText.replace(/\\s+/g, ' ').trim(), seen: shows(said),
                        link: link ? link.getAttribute('href') : '', link_seen: link ? shows(link) : null,
                        top: Math.round(said.getBoundingClientRect().top), screen: innerHeight, scrolled: Math.round(scrollY)}; }"""

            def log_in(view) -> None:
                view.goto(base + "/login", wait_until="networkidle")
                view.fill("input[name=email]", who)
                view.fill("input[name=password]", PASSWORD)
                view.click("button:has-text('Log in')")
                view.wait_for_url(base + "/outfits")

            def bought(view) -> dict[str, tuple[str, int, float]]:
                """What his pieces are picked as now, read from the shopping list's CSV file: for each piece its
                product, how many of it, and what they cost together."""
                text = view.request.get(base + "/list.csv").text().lstrip("﻿")
                return {row["slot"]: (row["link"] or row["product"], int(row["quantity"]), float(row["total_eur"]))
                        for row in csv.DictReader(io.StringIO(text))}

            def change(before: dict, after: dict, what: str, none: str) -> str:
                """The sentence that says what a change of the brief did, worked out here from the two shopping lists:
                "Your brief changed 2 pieces: +4 € 4 € more ." (the second amount is the screen reader's)."""
                pieces = sum(many for piece, (product, many, _) in after.items() if before.get(piece, ("",))[0] != product)
                cents = round(sum(cost for _, _, cost in after.values()) * 100) - round(sum(cost for _, _, cost in before.values()) * 100)
                if not pieces:
                    assert not cents, f"no piece changed, yet the total moved by {cents} cents"
                    return none
                lead = f"{what} changed {pieces} piece{'' if pieces == 1 else 's'}"
                if not cents:
                    return f"{lead}. Your total is the same."
                euros = abs(cents) / 100
                amount = (f"{euros:,.0f}" if cents % 100 == 0 else f"{euros:,.2f}") + " €"
                return f"{lead}: {'+' if cents > 0 else '−'}{amount} {amount} {'more' if cents > 0 else 'less'} ."

            def said_on_screen(view, words: str, link: str, where: str) -> str:
                """The sentence with these words stands beside the brief, whole and on the screen without scrolling,
                and so does its link, if it is to have one. Gives the sentence back."""
                found = view.evaluate(seen, words)
                assert found["found"], f"{where}: {words!r} is not said beside the brief; the page says {found['said']}"
                assert found["seen"], f"{where}: {words!r} is not on the screen as the page comes back: {found}"
                assert found["link"] == link, f"{where}: the sentence's link leads to {found['link']!r}, not {link!r}"
                assert not link or found["link_seen"], f"{where}: the link to the outfits is not on the screen: {found}"
                assert view.locator("main > .flash").count() == 0, f"{where}: it is said a second time at the top of the page"
                return found["text"]

            context = browser.new_context(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
            try:
                phone = context.new_page()
                phone.on("pageerror", lambda e: failures.append(f"script error: {e}"))
                phone.on("response", lambda r: failures.append(f"{r.status} {r.request.method} {r.url.replace(base, '')[:100]}")
                         if r.status >= 400 and r.url.startswith(base) and "does-not-exist" not in r.url else None)
                phone.goto(base + "/signup", wait_until="networkidle")
                phone.fill("input[name=email]", who)
                phone.fill("input[name=password]", PASSWORD)
                phone.click("button:has-text('Create account')")
                # (Every piece of his plan is in his wardrobe, so the shopping list holds them all and what the page
                # says a brief did to his pieces and his total can be worked out from it. What a new customer with
                # an empty wardrobe is told is walked by the step before this one.)
                a_customer_from_before(phone)
                phone.wait_for_url(base + "/outfits")
                assert phone.evaluate(whys) == [], "an outfit says why it fits a brief nobody gave"
                # The styles: six choices to tap, any number of them, beside the three that were there.
                phone.goto(base + "/profile", wait_until="networkidle")
                assert phone.locator("input[name=use]").count() == 3, "Everyday, Office and Both are not all there"
                styles = phone.locator("[data-styles] label").all_inner_texts()
                assert [text.strip() for text in styles] == ["Smart casual", "Street", "Minimal", "Tailored", "Workwear",
                                                              "Outdoor"], f"the styles to tick: {styles}"
                heights = phone.locator("[data-styles] label").evaluate_all("ls => ls.map(l => l.getBoundingClientRect().height)")
                assert all(h >= 24 for h in heights), f"a style is under 24px to tap: {heights}"
                phone.locator("[data-styles] label:has-text('Workwear')").tap()
                phone.locator("[data-styles] label:has-text('Street')").tap()
                with phone.expect_navigation(wait_until="networkidle"):
                    phone.locator(".cc-save button").tap()
                phone.goto(base + "/profile", wait_until="networkidle")
                ticked = phone.locator("[data-styles] input:checked").evaluate_all("bs => bs.map(b => b.value)")
                assert ticked == ["street", "workwear"], f"two styles ticked and saved, the page shows {ticked}"
                phone.goto(base + "/outfits", wait_until="networkidle")
                shown = phone.evaluate(boards)
                said = [board["why"] for board in shown]
                assert any(said), f"with two styles ticked no outfit says why it fits: {shown}"
                assert all(re.match(r"^(Street|Workwear): [a-z -]+(, [a-z -]+){1,4}$", line) for line in said if line), \
                    f"a line does not name a style and at least two pieces: {said}"
                # The line tells the outfits apart: only an outfit that is the style as a whole says so. Street and
                # workwear stop below Smart casual, so neither is ever said of a Smart casual or an Office outfit.
                assert not all(said), f"every outfit says it is his style, the formal ones too: {shown}"
                wrong = [board for board in shown if board["why"] and board["title"] != "Everyday"]
                assert not wrong, f"an outfit that is not an everyday one is called street or workwear: {wrong}"
                assert said[0], f"the first outfit offered is not one that is his style: {shown[:3]}"
                # The chat: his own words, an answer with one question back, and a suggestion that is not in use.
                phone.goto(base + "/profile#style", wait_until="networkidle")
                expect(phone.locator("#tab-you")).to_have_attribute("aria-selected", "true")
                expect(phone.locator("#style-chat textarea")).to_be_visible()
                note = phone.locator("[data-chat-sent]").inner_text()
                assert "goes to Google" in note and "Your name, email address, sizes, budget and photo are not sent" in note, \
                    f"beside the chat it does not say what is sent: {note!r}"
                phone.fill("#style-chat textarea", "street style, Berlin vibe <b>bold</b>")
                phone.evaluate("() => { document.getElementById('announce').dataset.before = 'the answer'; }")
                # While the message is on its way (held back here; with Google it can be many seconds) the page says
                # so: the button reads "Sending…" and is off, a line under the field says the answer can take a few
                # seconds, and a screen reader hears it.
                held: list = []
                phone.route("**/profile/style/say", lambda route: held.append(route))
                phone.locator("#style-chat .chat-say button").tap()
                try:
                    phone.wait_for_function("() => document.querySelector('#style-chat .chat-say button').textContent.trim() === 'Sending…'",
                                            timeout=5000)
                except Exception:
                    raise AssertionError("while a message is on its way the Send button does not say so") from None
                sending = phone.evaluate("""() => {
                    const form = document.querySelector('#style-chat .chat-say'), wait = form.querySelector('[data-chat-wait]');
                    const box = wait ? wait.getBoundingClientRect() : {height: 0, top: 0, bottom: 0};
                    return {off: form.querySelector('button').disabled, line: wait ? wait.textContent.trim() : '',
                            shown: !!wait && !wait.hidden && box.height > 0, heard: document.getElementById('announce').textContent.trim(),
                            kept: form.querySelector('textarea').value}; }""")
                assert sending["off"], "Send can be pressed a second time while the first message is on its way"
                assert sending["shown"] and sending["line"] == "Sending your message. The answer can take a few seconds.", \
                    f"while a message is on its way the page does not say so under the field: {sending}"
                assert sending["heard"] == sending["line"], f"a screen reader does not hear that the message is on its way: {sending}"
                assert len(held) == 1, f"{len(held)} requests were sent for one message"
                held[0].continue_()
                phone.unroute("**/profile/style/say")
                phone.wait_for_selector("[data-brief=suggested]")
                lines = phone.locator(".chat-lines li").all_inner_texts()
                assert len(lines) == 2 and "street style, Berlin vibe <b>bold</b>" in lines[0], f"the conversation: {lines}"
                assert phone.locator(".chat-lines b:not(.chat-q)").count() == 0, "what he typed became markup on the page"
                assert "I understood" in lines[1] and "dark colours" in lines[1] and "Should it stay all dark" in lines[1], f"the answer: {lines[1]!r}"
                # The answer is read out: by the live region that was on the page before it came, not by a new one.
                heard_it = phone.locator("#announce[data-before][aria-live=polite]").text_content() or ""
                assert "Style assistant:" in heard_it and "I understood" in heard_it and "Should it stay all dark" in heard_it \
                    and "A suggested style brief is below. It is not in use yet." in heard_it, \
                    f"a screen reader does not hear the new answer; the live region says {heard_it!r}"
                assert phone.evaluate("() => document.activeElement === document.querySelector('#style-chat .chat-say textarea')"), \
                    "after a message the keyboard is no longer in the message field"
                # On the phone the answer from its first line, the question it asks back, the field that holds the
                # keyboard and Send are on the screen together: nothing of them under the Save bar, the tab bar or
                # the figure and tabs that stay at the top.
                on_screen = phone.evaluate("""() => {
                    const shows = el => { const r = el.getBoundingClientRect();
                        return r.height > 0 && [[r.left + 4, r.top + 4], [r.right - 4, r.bottom - 4]].every(([x, y]) => {
                            const at = document.elementFromPoint(x, y); return !!at && el.contains(at); }); };
                    const chat = document.getElementById('style-chat'), box = el => { const r = el.getBoundingClientRect(); return [Math.round(r.top), Math.round(r.bottom)]; };
                    const parts = {answer: chat.querySelector('[data-chat-new]'), question: chat.querySelector('.chat-q'),
                                   field: chat.querySelector('.chat-say textarea'), send: chat.querySelector('.chat-say button')};
                    const save = document.querySelector('.cc-save'), tabs = document.querySelector('.cc-tabs');
                    return {hidden: Object.keys(parts).filter(name => !shows(parts[name])),
                            at: Object.fromEntries(Object.entries(parts).map(([name, el]) => [name, box(el)])),
                            save_bar: save ? box(save) : null, tabs: tabs ? box(tabs) : null, screen: innerHeight}; }""")
                assert not on_screen["hidden"], \
                    f"after the answer on a phone, not on the screen: {on_screen['hidden']} (where things are: {on_screen})"
                assert "Not in use yet." in phone.locator("[data-brief]").inner_text(), "the suggestion does not say it is not in use"
                assert phone.locator("[data-brief] input[name=fits]:checked").evaluate_all("bs => bs.map(b => b.value)") == ["relaxed"]
                assert phone.input_value("[data-brief] input[name=colours_like]") == "black, charcoal"
                assert "Weekday" in phone.locator("[data-brief-stores]").inner_text(), "no store named that suits street"
                # "Smart casual" is a style there, and only that: the levels of formality have names of their own.
                choices = [text.strip() for text in phone.locator("[data-brief] fieldset label").all_inner_texts()]
                assert choices.count("Smart casual") == 1, f"Smart casual stands in the brief more than once: {choices}"
                formal = phone.locator("[data-brief] fieldset:has(legend:text-is('How formal')) label").all_inner_texts()
                assert [text.strip() for text in formal] == ["Any", "Casual", "In between", "Formal"], f"How formal: {formal}"
                assert phone.evaluate("document.documentElement.scrollWidth") <= 391, "the chat is wider than a phone"
                phone.goto(base + "/outfits", wait_until="networkidle")
                assert phone.evaluate(whys) == [line for line in said if line], "a suggestion nobody confirmed changed the outfits"
                # Opened again later, the suggestion is still there; he corrects it and confirms. What that did is said
                # on the screen the page comes back to: the sentence, what changed, and the link to the outfits.
                phone.goto(base + "/profile#style", wait_until="networkidle")
                phone.wait_for_selector("[data-brief=suggested]")
                phone.locator("[data-brief] label:has-text('Workwear')").tap()        # not workwear after all
                phone.fill("[data-brief] input[name=not_wanted]", "logo")
                before = bought(phone)
                with phone.expect_navigation(wait_until="networkidle"):
                    phone.locator("button:has-text('Use this brief')").tap()
                in_use = phone.locator("[data-brief=in-use]")
                expect(in_use).to_be_attached()
                with_brief = bought(phone)
                sentence = said_on_screen(phone, "Style brief saved.", "/outfits", "Use this brief on a phone")
                expected = f"Style brief saved. {change(before, with_brief, 'Your brief', 'It changed none of your pieces.')} See your outfits"
                assert sentence == expected, f"after Use this brief the page says {sentence!r}, and the shopping list says {expected!r}"
                assert "Your brief changed" in sentence, "this brief changes pieces of the example plan, and that is not said"
                assert phone.locator("[data-styles] input:checked").evaluate_all("bs => bs.map(b => b.value)") == ["street"]
                with phone.expect_navigation(wait_until="networkidle"):
                    phone.locator("[data-style-said] a").tap()
                assert phone.url == base + "/outfits", f"See your outfits leads to {phone.url}"
                shown = phone.evaluate(boards)
                now = [board["why"] for board in shown if board["why"]]
                assert now and all(line.startswith("Street: ") for line in now), f"with the brief in use: {now}"
                assert shown[0]["why"], f"with the brief in use the first outfit is not a street one: {shown[:3]}"
                assert all(board["title"] == "Everyday" for board in shown if board["why"]), f"street is said of a formal outfit: {shown}"
                assert any("relaxed" in line for line in now), f"no outfit names a relaxed piece: {now}"
                # The line of the first outfit is on the phone's first screen, above the tab bar and above the bar
                # with the two answers that stands over it, not behind them. (The
                # "Demo data" notice over this page is not on the live site. The picture gives up room for it, so it is
                # taken away here: without it the picture is as large as it gets, and the line stood behind the bar.)
                phone.evaluate("() => document.querySelectorAll('main .demo').forEach(notice => notice.remove())")
                line = phone.evaluate("""() => { const r = document.querySelector('#reel [data-slide] [data-why]').getBoundingClientRect();
                    const dock = document.querySelector('#dock:not([hidden])');
                    return {top: Math.round(r.top), bottom: Math.round(r.bottom), scrolled: Math.round(scrollY),
                            bar: Math.round(document.querySelector('nav.tabs').getBoundingClientRect().top),
                            answers: dock ? Math.round(dock.getBoundingClientRect().top) : null}; }""")
                assert line["scrolled"] == 0 and line["top"] >= 0 and line["bottom"] <= line["bar"], \
                    f"on a phone the line under the outfit's name is not above the tab bar on the first screen: {line}"
                assert line["answers"] is not None and line["bottom"] <= line["answers"] <= line["bar"], \
                    f"on a phone the line under the outfit's name is behind the bar with the two answers: {line}"
                assert phone.evaluate("document.documentElement.scrollWidth") <= 391, "the outfits are wider than a phone"
            finally:
                context.close()
            try:
                # On a computer the chat and the brief fit. A message sent by keyboard leaves the keyboard in the message
                # field, and "Start again" deletes the conversation only.
                context = browser.new_context(viewport={"width": 1280, "height": 860})
                wide = context.new_page()
                wide.on("pageerror", lambda e: failures.append(f"script error: {e}"))
                log_in(wide)
                wide.goto(base + "/profile#style", wait_until="networkidle")
                assert wide.evaluate("document.documentElement.scrollWidth") <= 1281, "Profile with the chat is wider than the screen"
                assert wide.locator(".chat-lines li").count() == 2, "the conversation is gone on another device"
                # A message that gets no answer back (the connection is cut here): said under the field, read out,
                # his words still in the field and Send ready again.
                wide.route("**/profile/style/say", lambda route: route.abort())
                wide.fill("#style-chat .chat-say textarea", "no leather at all")
                wide.locator("#style-chat .chat-say button").click()
                expect(wide.locator("#style-chat [data-chat-wait]")).to_have_text(
                    "No answer came back. Check your connection and send it again.")
                expect(wide.locator("#style-chat [data-chat-wait]")).to_be_visible()
                expect(wide.locator("#style-chat .chat-say button")).to_have_text("Send")
                expect(wide.locator("#style-chat .chat-say button")).to_be_enabled()
                assert wide.input_value("#style-chat .chat-say textarea") == "no leather at all", "his words are gone"
                assert "No answer came back." in (wide.locator("#announce").text_content() or ""), "it is not read out"
                assert wide.locator(".chat-lines li").count() == 2, "a message that was not sent stands in the conversation"
                wide.unroute("**/profile/style/say")
                wide.fill("#style-chat .chat-say textarea", "")
                wide.locator("#style-chat .chat-say textarea").focus()
                wide.keyboard.type("no leather")
                wide.keyboard.press("Tab")
                assert wide.evaluate("() => document.activeElement.textContent.trim()") == "Send", "Tab from the message does not reach Send"
                wide.keyboard.press("Enter")
                wide.wait_for_function("() => document.querySelectorAll('.chat-lines li').length === 4")
                wide.wait_for_function("() => document.activeElement === document.querySelector('#style-chat .chat-say textarea')")
                wide.keyboard.type("and no wool")          # the next message can be typed at once
                assert wide.input_value("#style-chat .chat-say textarea") == "and no wool", "typing after a message goes nowhere"
                heard_it = wide.locator("#announce").text_content() or ""
                assert "I understood no leather" in heard_it, f"the second answer is not read out: {heard_it!r}"
                wide.fill("#style-chat .chat-say textarea", "")
                # He confirms "no leather". Every pair of shoes and sneakers the example plan can take is leather, so
                # they stay, and the page says that they still go against the brief. No outfit with them is said to fit
                # it, and every outfit has shoes: no line at all, where the same brief without the wish had lines.
                assert wide.input_value("[data-brief=suggested] input[name=not_wanted]") == "logo, leather", "the suggestion"
                before = bought(wide)
                with wide.expect_navigation(wait_until="networkidle"):
                    wide.click("button:has-text('Use this brief')")
                after = bought(wide)
                sentence = said_on_screen(wide, "Style brief saved.", "/outfits", "Use this brief with no leather")
                shoes = {piece: product for piece, (product, _, _) in after.items() if "sneakers" in piece or "shoes" in piece or "loafers" in piece}
                assert len(shoes) == 2 and all(before[piece][0] == product for piece, product in shoes.items()), \
                    f"no leather changed the shoes to other shoes: {[(before[piece][0], product) for piece, product in shoes.items()]}"
                expected = (f"Style brief saved. {change(before, after, 'Your brief', 'It changed none of your pieces.')} "
                            "2 pieces still go against it: White leather sneakers, Dark brown derby shoes. See your outfits")
                assert sentence == expected, f"after Use this brief with no leather the page says {sentence!r}, not {expected!r}"
                wide.goto(base + "/outfits", wait_until="networkidle")
                lines = wide.evaluate(whys)
                assert lines == [], f"he wants no leather, and outfits with leather shoes say they fit his brief: {lines}"
                wide.goto(base + "/profile#style", wait_until="networkidle")
                with wide.expect_navigation(wait_until="networkidle"):
                    wide.click("button:has-text('Start again')")
                sentence = said_on_screen(wide, "The conversation is deleted.", "", "Start again on a computer")
                assert sentence == "The conversation is deleted. Your style brief stays in use.", sentence
                assert wide.locator(".chat-lines li").count() == 0, "Start again left the conversation"
                expect(wide.locator("[data-brief=in-use]")).to_be_visible()
                context.close()
                # With JavaScript off: a message comes back to the chat on Profile, with its suggestion, and "Remove
                # brief" says what it did on the screen the page comes back to.
                context = browser.new_context(viewport={"width": 390, "height": 844}, java_script_enabled=False)
                plain = context.new_page()
                log_in(plain)
                plain.goto(base + "/profile", wait_until="networkidle")
                plain.fill("#style-chat textarea", "office, navy, no logos")
                plain.click("#style-chat .chat-say button")
                plain.wait_for_load_state("networkidle")
                assert plain.url.endswith("/profile#style"), f"without JavaScript a message leads to {plain.url}"
                suggested = plain.locator("[data-brief=suggested]")
                assert suggested.locator("input[name=styles]:checked").evaluate_all("bs => bs.map(b => b.value)") == ["street", "tailored"]
                assert "In use now: styles Street" in suggested.inner_text(), "it does not say which brief is in use meanwhile"
                before = bought(plain)
                plain.click("button:has-text('Remove brief')")
                plain.wait_for_load_state("networkidle")
                assert plain.locator("[data-brief]").count() == 0, "Remove brief left a brief on the page"
                sentence = said_on_screen(plain, "Style brief removed", "/outfits", "Remove brief without JavaScript")
                expected = f"Style brief removed, and the conversation with it. {change(before, bought(plain), 'Removing it', 'That changed none of your pieces.')} See your outfits"
                assert sentence == expected, f"after Remove brief the page says {sentence!r}, and the shopping list says {expected!r}"
                plain.goto(base + "/outfits", wait_until="networkidle")
                assert plain.locator("[data-why]").count() == 0, "without a brief an outfit still says why it fits one"
                context.close()
                # After an answer the message field and Send are on the screen, above the Save bar and the tab bar: on
                # short phones (360 x 740, 375 x 667) too, and in a laptop's short window (1366 x 650), where Profile's
                # tabs are a column beside the chat, not a bar above it (the page moved the wrong way there).
                for size, touch in (((360, 740), True), ((375, 667), True), ((1366, 650), False), ((844, 390), True)):
                    context = browser.new_context(viewport={"width": size[0], "height": size[1]}, is_mobile=touch, has_touch=touch)
                    view = context.new_page()
                    view.on("pageerror", lambda e: failures.append(f"script error: {e}"))
                    log_in(view)
                    view.goto(base + "/profile#style", wait_until="networkidle")
                    view.fill("#style-chat .chat-say textarea", "street style, Berlin vibe")
                    send = view.locator("#style-chat .chat-say button")
                    with view.expect_response("**/profile/style/say"):
                        send.tap() if touch else send.click()
                    view.wait_for_selector("#style-chat [data-chat-new], #style-chat [data-chat-said]")
                    view.wait_for_timeout(300)      # (the page moves once the answer is in: app.js 13d)
                    hidden = view.evaluate("""() => { const shows = el => { const r = el.getBoundingClientRect();
                        return r.height > 0 && [[r.left + 4, r.top + 4], [r.right - 4, r.bottom - 4]].every(([x, y]) => {
                            const at = document.elementFromPoint(x, y); return !!at && el.contains(at); }); };
                        const chat = document.getElementById('style-chat');
                        return ['.chat-say textarea', '.chat-say button'].filter(s => !shows(chat.querySelector(s))); }""")
                    assert not hidden, f"at {size[0]} x {size[1]}, after an answer, not on the screen: {hidden}"
                    context.close()
                # And on a phone, "Start again" and "Remove brief" are said on the screen the page comes back to as well.
                context = browser.new_context(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
                phone = context.new_page()
                phone.on("pageerror", lambda e: failures.append(f"script error: {e}"))
                log_in(phone)
                phone.goto(base + "/profile#style", wait_until="networkidle")
                phone.fill("#style-chat textarea", "street style, Berlin vibe")
                phone.locator("#style-chat .chat-say button").tap()
                phone.wait_for_selector("[data-brief=suggested]")
                with phone.expect_navigation(wait_until="networkidle"):
                    phone.locator("button:has-text('Use this brief')").tap()
                said_on_screen(phone, "Style brief saved.", "/outfits", "Use this brief on a phone, a second time")
                with phone.expect_navigation(wait_until="networkidle"):
                    phone.locator("button:has-text('Start again')").tap()
                said_on_screen(phone, "The conversation is deleted. Your style brief stays in use.", "", "Start again on a phone")
                before = bought(phone)
                with phone.expect_navigation(wait_until="networkidle"):
                    phone.locator("button:has-text('Remove brief')").tap()
                sentence = said_on_screen(phone, "Style brief removed.", "/outfits", "Remove brief on a phone")
                expected = f"Style brief removed. {change(before, bought(phone), 'Removing it', 'That changed none of your pieces.')} See your outfits"
                assert sentence == expected, f"after Remove brief the page says {sentence!r}, and the shopping list says {expected!r}"
                assert phone.locator("[data-brief]").count() == 0, "Remove brief left a brief on the page"
            finally:
                context.close()
                delete_a_steps_customer(who)

        def tile_captions_whole():
            # Each piece's photo in an outfit has a caption at its foot. On a narrow phone (320px) a tile is under 150px
            # wide, too narrow for "WEEKDAY · 180 €": it says the price alone (the list of pieces under the picture
            # names the store), never a store's name cut to "WEEKDA…". On a 390px phone, where the picture is the
            # screen, and on a computer it says both. No caption is cut off.
            # (A tile is narrow or wide by its own width: three pieces have one tile across the whole picture.)
            page.goto(base + "/outfits", wait_until="networkidle")
            for width in (320, 390, 1280):
                page.set_viewport_size({"width": width, "height": 860})
                page.wait_for_timeout(150)
                seen = page.evaluate("""() => [...document.querySelector('#reel .slide').querySelectorAll('.tile .cap')].map(c => {
                    const store = c.querySelector('.cap-store');
                    return {text: c.innerText.trim(), cut: c.scrollWidth > c.clientWidth + 1,
                            store: store ? getComputedStyle(store).display !== 'none' : null,
                            tile: c.closest('.tile').getBoundingClientRect().width}; })""")
                assert seen, "the first outfit has no tiles"
                assert not [s for s in seen if s["cut"]], f"at {width}px a tile's caption is cut off: {seen}"
                wrong = [s for s in seen if s["store"] is not None and s["store"] != (s["tile"] >= 150)]
                assert not wrong, f"at {width}px a tile names its store where it is too narrow, or not where it is wide: {wrong}"
                if width == 320:
                    assert [s for s in seen if s["store"] is False], f"no tile on a narrow phone says its price alone: {seen}"
                else:
                    assert [s for s in seen if s["store"]], f"no tile at {width}px names its store: {seen}"
            page.set_viewport_size({"width": 1280, "height": 860})

        def photos_full_screen_on_a_phone():
            # On a phone the small pictures under an outfit are small (30 by 40px on a short one): a tap on one opens the
            # outfit's photos full screen, at that one, and shows it large in the outfit as before. Each photo is whole
            # on the screen (2 by 3) and carries the words 'AI picture' on itself; the line at the top says which one
            # shows ("Street · 4 of 6"), and the arrow keys move between them; Close is 44px tall and has the keyboard.
            # Closing goes back to the outfit with the photo seen last shown large and the keyboard on its small
            # picture. Light and dark; nothing wider than the screen. On a computer a tap opens nothing.
            # (A swipe inside the viewer is not synthesized here: GitHub's headless browser ignores those in a dialog.)
            settled = "() => !document.querySelector('.htmx-request, .htmx-swapping, .htmx-settling')"
            viewer = """() => {
                const v = document.getElementById('viewer'), box = el => el.getBoundingClientRect();
                const shown = [...v.querySelectorAll('.viewer-pic')].find(f => Math.abs(box(f).left - (innerWidth - box(f).width) / 2) < 2);
                const chip = shown && shown.querySelector('.ai-chip'), close = v.querySelector('.viewer-close');
                const s = shown && box(shown), c = chip && box(chip);
                return {open: v.open, said: v.querySelector('.viewer-said').textContent.trim(),
                        photo: s && [s.left, s.top, s.width, s.height, s.bottom <= innerHeight + 0.5 && s.top >= -0.5],
                        alt: shown && shown.querySelector('img').alt, loaded: shown && shown.querySelector('img').complete,
                        chip: chip && [chip.textContent.trim(), c.left >= s.left && c.right <= s.right && c.top >= s.top && c.bottom <= s.bottom],
                        close: [close.textContent.trim(), box(close).height, document.activeElement === close],
                        page: document.documentElement.scrollWidth};
            }"""
            for scheme in ("light", "dark"):
                context, other = logged_in_on(browser, viewport={"width": 390, "height": 664}, is_mobile=True, has_touch=True,
                                              color_scheme=scheme)
                try:
                    other.goto(base + yes_page(), wait_until="networkidle")
                    other.wait_for_function("s => document.querySelectorAll(s + ' .shots-row img').length === 6", arg=first)
                    key = other.evaluate("s => document.querySelector(s).id.slice(7)", first)
                    other.locator(f"{first} .shots-row button[id$='-street']").tap()
                    other.wait_for_selector("#viewer[open]")
                    other.wait_for_function(settled)
                    other.wait_for_function("() => document.querySelector('#viewer .viewer-said').textContent.includes('Street')")
                    seen = other.evaluate(viewer)
                    where = f"390 x 664, {scheme}"
                    assert seen["said"] == "Street · 4 of 6", f"{where}: the full-screen photos say {seen['said']!r}"
                    assert seen["photo"] and seen["photo"][2] >= 389 and seen["photo"][4] \
                        and abs(seen["photo"][3] - seen["photo"][2] * 3 / 2) < 1, f"{where}: the photo is not whole and full width: {seen}"
                    assert seen["alt"].endswith("photo: Street") and seen["chip"] == ["AI picture", True], \
                        f"{where}: the full-screen photo is not Street, or does not carry the words 'AI picture' on itself: {seen}"
                    assert seen["close"][0] == "Close" and seen["close"][1] >= 44 and seen["close"][2] and seen["page"] <= 390, \
                        f"{where}: Close is not a 44px button with the keyboard on it, or the page is wider than the screen: {seen}"
                    shown = other.evaluate("s => document.querySelector(s + ' .shots-row [aria-pressed=true]').id", first)
                    assert shown.endswith("-street"), f"{where}: the tap did not also show Street large in the outfit ({shown})"
                    for press, words in (("ArrowRight", "Café · 5 of 6"), ("ArrowLeft", "Street · 4 of 6"), ("ArrowLeft", "Turned · 3 of 6")):
                        other.keyboard.press(press)
                        other.wait_for_function("w => document.querySelector('#viewer .viewer-said').textContent.trim() === w", arg=words)
                    other.wait_for_function("() => { const r = document.querySelector('#viewer .viewer-row');"   # come to rest
                                            " return Math.abs(r.scrollLeft - Math.round(r.scrollLeft / r.clientWidth) * r.clientWidth) < 1; }")
                    seen = other.evaluate(viewer)
                    assert seen["alt"].endswith("photo: Turned") and seen["chip"] == ["AI picture", True], f"{where}: after the arrow keys: {seen}"
                    other.keyboard.press("Escape")
                    other.wait_for_function("() => !document.getElementById('viewer').open")
                    other.wait_for_function("s => document.querySelector(s + ' .shots-row [aria-pressed=true]').id.endsWith('-turned')", arg=first)
                    other.wait_for_function(settled)
                    back = other.evaluate("s => ({focus: document.activeElement.id, alt: document.querySelector(s + ' .look-pic img').alt})", first)
                    assert back["focus"] == f"shot-{key}-turned" and back["alt"].endswith("photo: Turned"), \
                        f"{where}: after Close the outfit does not show Turned large, with the keyboard on its small picture: {back}"
                finally:
                    context.close()
            context, other = logged_in_on(browser, viewport={"width": 1280, "height": 860})
            try:
                other.goto(base + yes_page(), wait_until="networkidle")
                other.wait_for_function("s => document.querySelectorAll(s + ' .shots-row img').length === 6", arg=first)
                other.click(f"{first} .shots-row button[id$='-cafe']")
                other.wait_for_function("s => document.querySelector(s + ' .shots-row [aria-pressed=true]').id.endsWith('-cafe')", arg=first)
                other.wait_for_function(settled)
                other.wait_for_timeout(300)
                assert not other.evaluate("() => document.getElementById('viewer').open"), "on a computer a small picture tapped opens the full screen"
                other.click(f"{first} .shots-row button[id$='-front']")
                other.wait_for_function("s => document.querySelector(s + ' .shots-row [aria-pressed=true]').id.endsWith('-front')", arg=first)
                other.wait_for_function(settled)
            finally:
                context.close()

        steps = [("create an account", sign_up), ("Stilsmith's own typefaces load", own_typefaces),
                 ("price levels and best for budget", price_levels),
                 ("price levels fit a phone and a computer", levels_fit_every_screen),
                 ("an option not in your size fades only its photo", out_of_size_fades_only_the_photo),
                 ("the picture of an outfit arrives by itself", picture_arrives),
                 ("the yes is on a phone's first screen", the_yes_is_on_a_phones_first_screen),
                 ("on a phone it arrives labelled, without a jump", a_picture_arrives_on_a_phone_without_a_jump),
                 ("more photos and a video only on an outfit said yes to", more_only_on_a_yes),
                 ("more photos: five made from the front picture", more_photos_of_the_outfit),
                 ("the photos full screen on a phone", photos_full_screen_on_a_phone),
                 ("a small picture tapped: never undone, and without JavaScript", a_tap_on_a_small_picture_is_kept),
                 ("see it move: a video, played, dragged, limited", see_it_move),
                 ("see it move from the picture showing: its own movement, one clip each", see_it_move_from_the_picture_showing),
                 ("the dots: small, there when pointed at", the_dots_small_and_there_when_pointed_at),
                 ("a touch on a computer shows the dots first", a_touch_on_a_computer_shows_the_dots_first),
                 ("Draw again keeps the picture until the new one", draw_again_keeps_the_picture),
                 ("taken out, its photos stay and no new ones are offered", take_them_out_again),
                 ("a dot on the picture opens the piece", dot_opens_the_piece),
                 ("swap a piece from the pop-up", swap_from_the_popup), ("leave a layer off", leave_a_layer_off),
                 ("the piece pop-up on a phone", the_piece_pop_up_on_a_phone),
                 ("a piece's card reads the same in four places", a_pieces_card_reads_the_same_everywhere),
                 ("a piece's words stay tidy at 320px", a_pieces_words_tidy_at_320),
                 ("a piece from an outfit without JavaScript", a_piece_without_javascript),
                 ("the pop-up's top row never hides what has focus", pop_up_never_hides_the_focus),
                 ("the page behind the pop-up stays put", the_page_behind_the_pop_up_stays_put),
                 ("arrows and arrow keys", arrows_move),
                 ("arrows for every mouse, your place kept on Back", arrows_for_every_mouse_and_your_place_kept),
                 ("the outfit row by keyboard and screen reader", the_outfit_row_by_keyboard),
                 ("save an outfit and buy it", save_and_buy),
                 ("yes and no build the wardrobe, with Undo", yes_and_no_build_the_wardrobe),
                 ("a store's pages open one by one, each ticked", a_stores_pages_open_one_by_one),
                 ("sold out in his size: said, one tap swaps, Undo", sold_out_in_his_size),
                 ("the shopping list prints without photos", list_prints_without_photos),
                 ("log-in, first tab and wordmark lead to outfits", outfits_are_home),
                 ("the landing page says what Stilsmith is", the_landing_page),
                 ("public pages: no cookie, errors in plain words", public_pages_and_errors),
                 ("the wordmark Stilsmith fits at 320, 390 and 1280", the_wordmark_fits),
                 ("moving between tabs fetches only the page", tabs_fetch_only_the_page),
                 ("no page is wider than a phone or a computer screen", nothing_scrolls_sideways),
                 ("the owner's store catalogues, owners only", owners_store_catalogues),
                 ("put a model together", my_model), ("upload a photo, then delete it", my_photo),
                 ("the body on Profile reaches the pictures", the_body_reaches_the_pictures),
                 ("Profile asks before unsaved changes are lost", unsaved_changes_are_not_lost_silently),
                 ("Profile is a character screen", profile_is_a_character_screen),
                 ("the store picker: only the stores ticked", the_store_picker),
                 ("the welcome's last step leads to the style chat", the_welcome_leads_to_the_style_chat),
                 ("the style chat: his words, a brief he confirms", the_style_chat),
                 ("colours picked by tapping swatches", colours_by_tapping_swatches),
                 ("one tap fills a piece the list has nothing for", one_tap_colour),
                 ("new colours rebuild the plan, keeping the swap", new_colours_rebuild_the_plan),
                 ("the outfit on a phone's first screen", the_outfit_on_a_phones_first_screen),
                 ("an outfit's tiles say their price whole", tile_captions_whole),
                 ("motion: quick, never in the way, still if asked", motion_quick_and_still),
                 ("the budget bar never hides what has focus", budget_bar_never_hides_the_focus),
                 ("a piece's page by keyboard, links answered there", a_pieces_page_by_keyboard),
                 ("an option's two actions on three phones", options_fit_three_phones),
                 ("the plan answers inside the piece", the_plan_answers_next_to_the_piece),
                 ("delete the account", delete_account)]
        for name, step in steps:
            known = len(failures)
            try:
                step()
                verdict = "ok" if len(failures) == known else "FAILED REQUESTS"
            except Exception as problem:  # noqa: BLE001 - every kind of failure is a failed step
                verdict = f"FAILED: {type(problem).__name__}: {(str(problem).splitlines() or [''])[0][:220]}"
                failures.append(f"{name}: {verdict}")
            print(f"  {name:<46} {verdict}", flush=True)
        browser.close()


def main() -> int:
    app = create_app()
    answer = app.wsgi_app

    def listening(environ, start_response):     # what reaches the server; what the browser keeps never does
        heard.append(environ.get("PATH_INFO", ""))
        return answer(environ, start_response)

    app.wsgi_app = listening  # type: ignore[method-assign]
    server = make_server("127.0.0.1", 0, app, threaded=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        run(f"http://127.0.0.1:{server.server_port}")
    finally:
        server.shutdown()
        os.chdir(ROOT)
        shutil.rmtree(HOME, ignore_errors=True)
    if failures:
        print("\nFailed:")
        for line in failures:
            print("  ", line)
        return 1
    print(f"\nAll steps passed ({len(asked)} pictures and {len(made)} video{'' if len(made) == 1 else 's'} "
          "were asked of the stand-ins).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
