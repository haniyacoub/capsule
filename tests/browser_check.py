"""The app driven through a real browser: what the unit tests cannot see.

    python tests/browser_check.py

Needs the packages in requirements.txt and, once, `python -m playwright install chromium`.

It starts the app in production mode on a spare port, with a throwaway data folder and
stand-ins for the image service and Google's video model (nothing is sent anywhere and nothing is billed), then does
what a new customer would: signs up and lands on the starter outfits (a banner where the budget bar would be,
the whole picture above the tab bar on three phones), changes the price level, watches an outfit's picture
arrive (said to be drawing inside its box, then labelled 'AI picture' on itself, without the
page on a phone jumping), taps Street while a picture is asked for or drawn (no late answer of the studio's undoes the
tap, and none is asked for while the street is) and
taps a scene with JavaScript off (the page comes back showing it), makes the outfit's AI video with "See it move" (told
first, under the picture and on five phones, that it is his one video today), watches it play under the caption 'Look
and fit will differ', drags it round and turns it with the arrow keys, then finds the day's video used up on
the next outfit, opens a piece from its dot, swaps it (said over the outfit, with Undo, which puts back the
product and its lock state), leaves a layer off (said, with 'Put it back'), opens a piece on a phone
(named by its product, the quick changes on the first screen, the page behind it staying put, and back from
comparing all options to the same outfit), opens a piece with JavaScript off (its page, and back to the same outfit)
and with Space, tabs up and down a pop-up that scrolls (nothing with keyboard focus
hidden under its top row, no focus ring cut off at its bottom), sees that with scrollbars shown the page behind
the pop-up does not move sideways,
sees the label 'AI picture' clear of every dot on a picture as narrow as 124px,
moves between outfits (by keyboard too: Next among the first Tab stops, focus going with the outfit shown, which a
screen reader hears named, Tab leading into the outfit shown and Next keeping focus at the end of the row, the heart
keeping focus, Escape hiding a dot's label),
saves and "buys" one (keeping the example sizes as his own), saves an outfit with the heart and takes it back with the
next tap (phone, computer and without JavaScript; under Saved it leaves the page, with Undo; the step's own customer
is deleted when it ends), prints the shopping list,
logs in again and lands on the outfits, puts a model together on Profile's character screen (its tabs, the figure
in the middle that follows every height, build, skin and hair choice at once, by mouse, keyboard and links, on a phone,
a computer and without JavaScript, and "Your model" drawn by AI there), uploads a photo, sees Profile ask before
changes not saved would be lost, unticks a store on Profile's Stores tab (its pieces picked again, said in one line;
the last store with products stays ticked, and the six with none yet are listed apart) and ticks it again, saves new colours (the plan is rebuilt,
keeping the swapped piece, and the budget bar takes the banner's place), sees that a phone's first
screen shows the outfit on the model with its price and the heart (and every chip over it, whole,
by keyboard), tabs through three pages to see that nothing with keyboard focus is hidden under the
budget bar or the tab bar, locks and chooses on a piece's page by keyboard (focus stays where it was) and pastes
a link that is not a store's (answered inside that section, on a phone's screen, with JavaScript on and off), then a
link from Hirmer, a store with no products yet, with its page as he saved it (name and price filled in, no photo, no
store asked for anything) and a women's link (refused: menswear only),
sees an option's "Choose this" and "Open at COS" side by side wherever they fit, on three phones, adds and saves a
piece of the plan (answered inside that piece, on a phone's screen), and deletes the account. On the way it watches
everything that moves (app.css "Motion"): a tab slides the page forward or back and a tap while it slides is not lost,
the pop-up slides up and lets a tap through as it closes, the heart grows in, the AI picture comes up whole over the
pieces' photos (never blank, never half-loaded, on a slow connection too), all within 300 ms and without a layout
shift; and with less motion asked for, the same taps move nothing.

On the way a second customer, on a small product list published for that step alone, goes from the
starter outfits to his profile with "Make them mine" and fills a piece the list has nothing for with one tap.
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

from wardrobe import colours, imagegen, looks, person, videogen, videos  # noqa: E402
from wardrobe import profile as profile_mod  # noqa: E402
from wardrobe.app import create_app  # noqa: E402


def picture(width: int = 240, height: int = 360, tint: tuple[int, int, int] = (120, 124, 130)) -> bytes:
    """A small valid PNG: a grey card standing in for a drawn outfit."""
    row = b"\x00" + bytes(tint) * width
    raw = row * height

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))


asked: list[dict] = []      # what the "image service" was asked to draw


def stand_in(service, prompt, photo=None):
    asked.append({"prompt": prompt, "photo": photo})
    time.sleep(1.5)         # long enough for the page to show that it is waiting
    return picture(tint=(90, 120, 170) if photo else (120, 124, 130)), "png"


imagegen.draw = stand_in

made: list[str] = []        # what the "video model" was asked to make
refuse: list[imagegen.DrawError] = []   # a problem the "video model" is to have instead, next time (nothing made)
CLIP = (ROOT / "tests" / "fixtures" / "test-pattern.mp4").read_bytes()     # 8 s of ffmpeg's test pattern, no person


def video_stand_in(service, picture, prompt):
    if refuse:
        time.sleep(0.5)
        raise refuse.pop(0)
    made.append(prompt)
    time.sleep(1.5)         # long enough for the page to show that it is being made
    return CLIP


def never(*args, **kwargs):
    raise AssertionError("the walk-through never calls Google")


videogen.make = video_stand_in
imagegen._send = never

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
        page.on("dialog", lambda d: d.accept())
        # (The demo catalogue has one picture that is missing on purpose, to show the fallback.)
        page.on("response", lambda r: failures.append(f"{r.status} {r.request.method} {r.url.replace(base, '')[:100]}")
                if r.status >= 400 and r.url.startswith(base) and "does-not-exist" not in r.url else None)
        page.on("pageerror", lambda e: failures.append(f"script error: {e}"))

        def total() -> str:
            return page.locator("#summary .num b").nth(0).inner_text()

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

        def starter(where_page) -> dict:
            """The starter banner over a new customer's outfits, and the budget bar it stands in for."""
            return where_page.evaluate("""() => {
                const banner = document.querySelector('.starter'), link = banner && banner.querySelector('a');
                return {words: banner ? banner.querySelector('p').textContent.replace(/\\s+/g, ' ').trim() : null,
                        link: link ? [link.textContent.trim(), link.getAttribute('href')] : null,
                        height: banner ? banner.getBoundingClientRect().height : null,
                        bar: !!document.getElementById('summary'),
                        flashes: [...document.querySelectorAll('main > .flash')].map(f => f.textContent.trim())};
            }""")

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

        # Said from the example values every account starts with (wardrobe/profile.py), never typed.
        liked = [colours.get(key).label.lower() for key in profile_mod.EXAMPLE["liked"]]
        starter_words = (f"Starter outfits for a man of {profile_mod.EXAMPLE['height_cm']} cm, size "
                         f"{profile_mod.EXAMPLE['top_size']}, who likes {', '.join(liked[:-1])} and {liked[-1]}.")

        def sign_up():
            # A new customer sees the starter outfits on the model first, not a form of someone else's values: no
            # message to read, and in the budget bar's place a banner that says whose outfits these are, with one way
            # to make them his.
            page.goto(base + "/signup", wait_until="networkidle")
            page.fill("input[name=email]", EMAIL)
            page.fill("input[name=password]", PASSWORD)
            page.click("button:has-text('Create account')")
            page.wait_for_url(base + "/outfits")
            page.wait_for_load_state("networkidle")
            seen = starter(page)
            assert seen["words"] == starter_words, f"the starter banner reads {seen['words']!r}"
            assert seen["link"] == ["Make them mine", "/profile"], f"the banner's way to the profile: {seen['link']}"
            assert not seen["bar"], "the budget bar is over a new customer's outfits, for a budget he never set"
            assert not seen["flashes"], f"a message to read before the outfits: {seen['flashes']}"
            assert page.locator(f"{first} .collage .tile").count() >= 2, "no outfit under the banner"

        def starter_outfits_fit_a_phone():
            # On three phones, the starter banner is at most 96px tall, and the picture is sized from its real height:
            # the whole picture, its lowest dot included, still ends above the tab bar.
            for width, height in ((390, 844), (375, 667), (360, 740)):
                context = browser.new_context(viewport={"width": width, "height": height}, is_mobile=True, has_touch=True)
                other = context.new_page()
                other.goto(base + "/login", wait_until="networkidle")
                other.fill("input[name=email]", EMAIL)
                other.fill("input[name=password]", PASSWORD)
                other.click("button:has-text('Log in')")
                other.wait_for_url(base + "/outfits")
                other.wait_for_selector(f"{first} .look-pic img")
                # Invented products here, so the page opens with the "Demo data" notice that customers never see.
                other.evaluate("() => document.querySelectorAll('main > .demo').forEach(notice => notice.remove())")
                seen = {**starter(other), **other.evaluate("""s => {
                    const slide = document.querySelector(s), box = el => el.getBoundingClientRect();
                    return {bottom: Math.max(box(slide.querySelector('.look-pic')).bottom,
                                             ...[...slide.querySelectorAll('.spot')].map(d => box(d).bottom)),
                            tabs: box(document.querySelector('nav.tabs')).top};
                }""", first)}
                context.close()
                assert seen["words"] and not seen["bar"], f"at {width} x {height} no starter banner in the bar's place: {seen}"
                assert seen["height"] <= 96, f"at {width} x {height} the starter banner is {seen['height']:.0f}px tall"
                assert seen["bottom"] <= seen["tabs"], \
                    f"at {width} x {height} the picture ends at {seen['bottom']:.0f}px, under the tab bar at {seen['tabs']:.0f}px"

        def own_typefaces():
            # The text font and the serif for titles come from Stilsmith itself. They must really load, under the
            # site's own security policy: a font that fails is replaced by another without any error to see.
            page.goto(base + "/profile", wait_until="networkidle")
            loaded = page.evaluate("() => document.fonts.ready.then(() => [...document.fonts]"
                                   ".filter(f => f.status === 'loaded').map(f => f.family.replace(/\"/g, '')))")
            assert "Instrument Sans" in loaded and "Instrument Serif" in loaded, f"Stilsmith's fonts did not load: {loaded}"
            assert page.evaluate("() => getComputedStyle(document.body).fontFamily").startswith('"Instrument Sans"'), \
                "the text is not set in Instrument Sans"
            assert page.evaluate("() => getComputedStyle(document.querySelector('.brand')).fontFamily").startswith(
                '"Instrument Serif"'), "the wordmark is not set in Instrument Serif"

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
            # Stilsmith's serif, no text cut off, nothing drawn from the demo data, and a description for search
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
                            serif: getComputedStyle(document.querySelector('main h1')).fontFamily,
                            loaded: [...document.fonts].filter(f => f.status === 'loaded').map(f => f.family.replace(/"/g, '')),
                            description: (document.querySelector('meta[name=description]') || {}).content || '',
                            cut: [...document.querySelectorAll('main h1, main h2, main p, main .btn')]
                                 .filter(el => el.scrollWidth > el.clientWidth + 1).map(el => el.textContent.trim().slice(0, 30))};
                })""")
                context.close()
                assert "men's" in seen["text"].split(), f"at {width}px the page does not say who Stilsmith is for"
                planner = [word for word in ("slot", "candidate", "score") if word in seen["text"]]
                assert not planner, f"the planner's words on the landing page: {planner}"
                assert seen["log_in"] == 1, f"'Log in' is on the first screen {seen['log_in']} times at {width}px"
                assert seen["join"], f"'Create a free account' is not on the first screen at {width}px"
                assert seen["serif"].startswith('"Instrument Serif"') and "Instrument Serif" in seen["loaded"], \
                    f"the headline is not set in Instrument Serif at {width}px"
                assert not seen["cut"], f"text cut off at {width}px: {seen['cut']}"
                assert seen["description"], "no description for search results and shared links"
                assert not [url for url in fetched if "/mock/img/" in url], "the landing page still loads the demo drawings"
                assert not [url for url in fetched if "htmx" in url], f"the landing page loads htmx at {width}px"
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
                        chip_on: chip.left >= pic.left && chip.bottom <= pic.bottom + .5 && chip.width > 0,
                        pill: pill && {words: pill.textContent.trim(), width: box(pill).width}};
            }""", first)

        def the_label_never_meets_a_dot(where_page, where: str) -> None:
            # The label 'AI picture' and the dots never meet: on the picture as this screen has it, and on pictures 124
            # to 240px wide (the narrowest a phone shows, under a message). Under 200px "See it move" is its play sign
            # alone, so that its words do not cover the head; they are still read out.
            seen = label_and_dots(where_page)
            assert seen["dots"] and not seen["met"] and seen["chip_on"], f"{where}: the label 'AI picture' meets a dot: {seen}"
            for width in (124, 140, 150, 160, 170, 180, 190, 200, 220, 240):
                where_page.evaluate("w => document.querySelector('.looks').style.setProperty('--stage-w', w + 'px')", width)
                seen = label_and_dots(where_page)
                assert not seen["met"] and seen["chip_on"], f"{where}, a picture {width}px wide: the label meets a dot: {seen}"
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
            other.evaluate("() => document.querySelectorAll('main > .demo').forEach(notice => notice.remove())")
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

        def scenes_for_the_picture():
            # Under each outfit's picture, the scenes: Studio, Street, Library, Café. The studio is the picture drawn by
            # itself; another scene is drawn only when it is tapped: one more picture, asked for in that scene's words
            # with the person and the pieces word for word as in the studio, shown in the same box (the drawing said
            # inside it), with that scene pressed and keyboard focus kept on it. Back to the studio, its picture is
            # there at once and nothing is drawn again. On a phone and a computer, light and dark, the row lies under
            # the line under the picture, whole on the screen, four cells 40px tall with their words whole and readable
            # (4.5:1) whether pressed or not, with the corners of a segmented control's cells (--r-ui) in a track with its
            # own (--r-track); on a phone the outfit's title, price and heart still end above the tab bar.
            row = f"{first} .scenes"
            page.goto(base + "/outfits", wait_until="networkidle")
            page.wait_for_selector(f"{first} .look-pic img")
            studio = page.get_attribute(f"{first} .look-pic img", "src")
            labels = page.locator(f"{row} button").all_inner_texts()
            assert labels == ["Studio", "Street", "Library", "Café"], f"the scenes under the picture are {labels}"
            assert page.locator(f"{row} [aria-pressed=true]").all_inner_texts() == ["Studio"], "the studio is not the scene shown"
            assert page.get_attribute(row, "role") == "group" and page.get_attribute(row, "aria-label") == "Scene", \
                "the scenes are not one group named 'Scene' for screen readers"
            elsewhere = [scene["setting"] for name, scene in looks.load_rules()["scenes"].items() if name != looks.STUDIO]
            assert not any(words in sent["prompt"] for sent in asked for words in elsewhere), "a scene was drawn without being tapped"
            before = len(asked)
            page.focus(f"{row} button:has-text('Street')")              # by keyboard
            page.keyboard.press("Enter")
            page.wait_for_selector(f"{first} .look-bar.wait")
            status = drawing_status(page)
            assert status["inside"] and status["words"].startswith("Drawing this outfit"), \
                f"while the Street picture is drawn, the picture's box does not say so: {status}"
            page.wait_for_function("([s, old]) => { const i = document.querySelector(s + ' .look-pic img');"
                                   " return i && i.getAttribute('src') !== old && i.complete; }", arg=[first, studio])
            shows(f"{first} .look-pic img", "the Street picture")
            labelled(page, "1280 x 860, Street")
            assert page.locator(f"{row} [aria-pressed=true]").all_inner_texts() == ["Street"], "Street is not shown as pressed"
            focused = page.evaluate("() => document.activeElement.id")
            assert focused.startswith("scene-") and focused.endswith("-street"), f"keyboard focus left Street for {focused!r}"
            assert page.locator(f"{first} .spot").count() == page.locator(f"{first} .piece-row").count(), "a dot per piece"
            assert len(asked) == before + 1, f"tapping Street asked for {len(asked) - before} pictures"
            street = asked[-1]["prompt"]
            assert looks.load_rules()["scenes"]["street"]["setting"] in street and "studio" not in street.lower(), \
                "the Street picture was not asked for in the street"
            assert any(sent["prompt"].split("\n", 1)[1] == street.split("\n", 1)[1] for sent in asked[:before]), \
                "the Street picture's pieces and what to avoid are not word for word the studio picture's"
            page.click(f"{row} button:has-text('Studio')")
            page.wait_for_function("([s, src]) => { const i = document.querySelector(s + ' .look-pic img');"
                                   " return i && i.getAttribute('src') === src; }", arg=[first, studio])
            assert len(asked) == before + 1 and not page.locator(f"{first} .look-bar.wait").count(), \
                "going back to the studio drew its picture again"

            for width, height, touch in ((390, 844, True), (1280, 860, False)):
                for scheme in ("light", "dark"):
                    context, other = logged_in_on(browser, viewport={"width": width, "height": height}, is_mobile=touch,
                                                  has_touch=touch, color_scheme=scheme)
                    other.goto(base + "/outfits", wait_until="networkidle")
                    other.wait_for_selector(f"{first} .look-pic img")
                    other.evaluate("() => document.querySelectorAll('main > .demo').forEach(notice => notice.remove())")
                    seen = other.evaluate("""s => {
                        const slide = document.querySelector(s), box = el => el.getBoundingClientRect();
                        const row = slide.querySelector('.scenes'), r = box(row), line = box(slide.querySelector('.look-line'));
                        const rgb = c => c.match(/[\\d.]+/g).slice(0, 4).map(Number);
                        const lum = c => { const [r, g, b] = rgb(c).slice(0, 3).map(v => { v /= 255;
                            return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; }); return 0.2126 * r + 0.7152 * g + 0.0722 * b; };
                        const ratio = (a, b) => { const [x, y] = [lum(a), lum(b)].sort((m, n) => n - m); return (x + 0.05) / (y + 0.05); };
                        const ground = getComputedStyle(row).backgroundColor;
                        const cells = [...row.querySelectorAll('button')].map(b => {
                            const style = getComputedStyle(b), own = style.backgroundColor;
                            const bg = rgb(own)[3] === 0 ? ground : own;
                            return {words: b.textContent.trim(), height: box(b).height, whole: b.scrollWidth <= b.clientWidth,
                                    contrast: Math.round(ratio(style.color, bg) * 100) / 100, corner: style.borderTopLeftRadius};
                        });
                        const token = name => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
                        const meta = [...slide.querySelectorAll('.about-head h2, .count, .board-cost, .heart')].map(el => box(el).bottom);
                        return {cells, cell_corner: token('--r-ui'), track_corner: [getComputedStyle(row).borderTopLeftRadius, token('--r-track')],
                                left: r.left, right: r.right, top: r.top, under: Math.abs(r.top - line.bottom) < 1,
                                same_width: Math.abs(r.width - line.width) < 1, screen: innerWidth,
                                line_end: Math.max(...meta), tabs: box(document.querySelector('nav.tabs')).top,
                                page: document.documentElement.scrollWidth};
                    }""", first)
                    where = f"{width} x {height}, {scheme}"
                    assert seen["under"] and seen["same_width"] and 0 <= seen["left"] and seen["right"] <= seen["screen"], \
                        f"{where}: the scenes are not right under the line under the picture, whole on the screen: {seen}"
                    assert seen["page"] <= width, f"{where}: the page is {seen['page']}px wide"
                    for cell in seen["cells"]:
                        assert cell["height"] >= 40 and cell["whole"] and cell["contrast"] >= 4.5, \
                            f"{where}: the scene {cell['words']!r} is under 40px tall, cut off or hard to read: {cell}"
                        assert cell["corner"] == seen["cell_corner"], \
                            f"{where}: the scene {cell['words']!r} has {cell['corner']} corners, not a cell's {seen['cell_corner']}"
                    assert seen["track_corner"][0] == seen["track_corner"][1], f"{where}: the scenes' track corners: {seen}"
                    if touch:
                        assert seen["line_end"] <= seen["tabs"], \
                            f"{where}: with the scenes, the outfit's title, price and heart end under the tab bar: {seen}"
                    context.close()

        def a_scene_tap_is_kept():
            # A scene tapped while the studio picture is drawn is never undone by the drawing's own question (asked
            # every 3 s) coming back late: here that question is held until Street has been tapped and shown, then let
            # go. The box stays on Street, and the street picture arrives in it. The same for the studio's own request
            # for its picture ("See it worn", sent by itself or tapped), sent before the tap or while the street is
            # asked for (then it is not sent at all), and for "Draw again". Without JavaScript a tap on a scene
            # comes back to the outfits with that outfit showing that scene, and its picture once it is drawn. A
            # customer of his own, so that these pictures leave the first customer's ten a day as they were.
            who = "scenes-" + EMAIL
            pressed = "s => { const b = document.querySelector(s + ' .scenes [aria-pressed=true]'); return b && b.textContent.trim(); }"
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
                tapper.wait_for_url(base + "/outfits")
                for seed in range(141, 200):            # a shuffle whose first outfit has no picture yet
                    tapper.goto(base + f"/outfits?seed={seed}", wait_until="domcontentloaded")
                    if not tapper.locator(f"{first} .look-pic").count():
                        break
                else:
                    raise AssertionError("the first outfit of every shuffle tried already has its picture")
                held: list = []
                tapper.route("**/outfits/look/*", lambda route: route.continue_() if "scene=" in route.request.url
                             else held.append(route))   # the studio's question waits; the street's goes through
                tapper.wait_for_selector(f"{first} .look-bar.wait")                  # drawn by itself …
                for _ in range(100):                                                  # … and its question asked
                    if held:
                        break
                    tapper.wait_for_timeout(100)
                assert held, "the studio picture's box never asked how the drawing is going"
                before = len(asked)
                tapper.click(f"{first} .scenes button:has-text('Street')")
                tapper.wait_for_function(f"s => ({pressed})(s) === 'Street'", arg=first)
                for route in held:                                                    # the studio's answer, late
                    try:
                        route.continue_()
                    except Exception:  # noqa: BLE001 - the browser gave up on it already: that is the point
                        pass
                tapper.wait_for_timeout(1500)
                late = tapper.evaluate(pressed, first)
                assert late == "Street", f"the studio's late answer put {late!r} back over the Street tapped"
                tapper.wait_for_function("s => { const i = document.querySelector(s + ' .look-pic img');"
                                         " return i && i.alt.includes('Street scene') && i.complete; }", arg=first)
                assert tapper.evaluate(pressed, first) == "Street", "the street picture arrived under another scene"
                assert any(looks.load_rules()["scenes"]["street"]["setting"] in sent["prompt"] for sent in asked[before:]), \
                    "the Street picture was not asked for"
                tapper.unroute("**/outfits/look/*")

                # The same for the studio's own request for its picture ("See it worn", sent by itself 1.2 s after an
                # outfit without one comes into view, or tapped): whether it was sent before the tap or is sent while
                # the street is being asked for, its answer never puts the studio back. Each order on an outfit of its
                # own; the box's requests for it are held here and let go in the order the test says.
                def until(sent: list, what: str) -> None:
                    for _ in range(60):
                        if sent:
                            return
                        tapper.wait_for_timeout(100)
                    raise AssertionError(what)

                done: set = set()
                for order in ("studio asked, then Street tapped", "Street tapped, then the studio asked"):
                    for seed in range(201, 300):
                        tapper.goto(base + f"/outfits?seed={seed}", wait_until="domcontentloaded")
                        key = tapper.get_attribute(first, "id").removeprefix("outfit-")
                        if key not in done and not tapper.locator(f"{first} .look-pic").count() \
                                and tapper.locator(f"{first} [data-auto-look]").count():
                            break
                    else:
                        raise AssertionError("the first outfit of every shuffle tried already has its picture")
                    done.add(key)
                    studio_asked: list = []
                    street_asked: list = []

                    def holding(key: str, studio_asked: list, street_asked: list):
                        def hold(route):                            # this outfit's requests wait; others go through
                            sent = route.request.post_data or ""
                            if f"key={key}" not in sent:
                                route.continue_()
                            else:
                                (street_asked if "scene=street" in sent else studio_asked).append(route)
                        return hold
                    tapper.route("**/outfits/look", holding(key, studio_asked, street_asked))
                    if order.startswith("studio"):
                        until(studio_asked, "the studio picture was never asked for by itself")   # once in view
                        tapper.click(f"{first} .scenes button:has-text('Street')")
                        until(street_asked, "tapping Street asked for nothing")
                    else:
                        tapper.click(f"{first} .scenes button:has-text('Street')")
                        until(street_asked, "tapping Street asked for nothing")
                        sent_before = len(studio_asked)
                        # Meanwhile the studio is asked for: by the outfit itself (the event its timer sends) and by a
                        # tap on "See it worn". Neither is sent: nothing is drawn that would only be thrown away.
                        tapper.evaluate("s => htmx.trigger(document.querySelector(s + ' form.look-bar.ask'), 'draw')", first)
                        tapper.click(f"{first} form.look-bar.ask button:has-text('See it worn')")
                        tapper.wait_for_timeout(1500)               # longer than the outfit's own 1.2 s
                        assert len(studio_asked) == sent_before, \
                            f"{order}: the studio picture was asked for while the street's was under way"
                    for route in street_asked:                      # the street's answer first …
                        route.continue_()
                    tapper.wait_for_function(f"s => ({pressed})(s) === 'Street'", arg=first)
                    for route in studio_asked:                      # … then the studio's, late
                        try:
                            route.continue_()
                        except Exception:  # noqa: BLE001 - the browser gave up on it already: that is the point
                            pass
                    tapper.wait_for_timeout(1500)
                    late = tapper.evaluate(pressed, first)
                    assert late == "Street", f"{order}: the studio's late answer put {late!r} back over the Street tapped"
                    tapper.unroute("**/outfits/look")
                    tapper.wait_for_function("s => { const i = document.querySelector(s + ' .look-pic img');"
                                             " return i && i.alt.includes('Street scene') && i.complete; }", arg=first)
                    assert tapper.evaluate(pressed, first) == "Street", f"{order}: the street picture arrived under another scene"

                # And "Draw again" under the street picture, answered after Studio was tapped: Studio stays.
                again_asked: list = []
                tapper.route("**/outfits/look", lambda route: again_asked.append(route)
                             if "again=1" in (route.request.post_data or "") else route.continue_())
                tapper.click(f"{first} .look-line button:has-text('Draw again')")
                until(again_asked, "Draw again asked for nothing")
                tapper.click(f"{first} .scenes button:has-text('Studio')")
                tapper.wait_for_function(f"s => ({pressed})(s) === 'Studio'", arg=first)
                for route in again_asked:
                    try:
                        route.continue_()
                    except Exception:  # noqa: BLE001 - the browser gave up on it already: that is the point
                        pass
                tapper.wait_for_timeout(1500)
                late = tapper.evaluate(pressed, first)
                assert late == "Studio", f"the late answer to Draw again in the street put {late!r} back over the Studio tapped"
                tapper.unroute("**/outfits/look")
                tapper.wait_for_function("s => { const i = document.querySelector(s + ' .look-pic img');"
                                         " return i && !i.alt.includes(' scene') && i.complete; }", arg=first)
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
                other.goto(base + "/outfits", wait_until="networkidle")
                key = other.get_attribute(first, "id").removeprefix("outfit-")
                other.click(f"#look-{key} .scenes button:has-text('Library')")
                other.wait_for_load_state("networkidle")
                address = other.url.replace(base, "")
                assert "scene=library" in address and f"scene_of={key}" in address and address.endswith(f"#outfit-{key}"), \
                    f"without JavaScript, Library leads back to {address}"
                shown = other.evaluate(pressed, f"#look-{key}")
                assert shown == "Library", f"without JavaScript, the page came back showing {shown!r}, not Library"
                for _ in range(20):                     # drawn meanwhile: the same address shows it
                    other.wait_for_timeout(500)
                    other.reload(wait_until="networkidle")
                    if other.locator(f"#look-{key} .look-pic img").count():
                        break
                alt = other.get_attribute(f"#look-{key} .look-pic img", "alt")
                assert "Library scene" in alt and other.evaluate(pressed, f"#look-{key}") == "Library", \
                    f"without JavaScript, the library picture is not the one shown: {alt!r}"
            finally:
                context.close()

        def see_it_move():
            # Under a finished picture, "See it move": a button on the picture, at its top right, clear of every dot.
            # Tapped, it says under the picture what a video is and how many are left today ("1 video left today"), with
            # the button that makes one beside "Not now", in place of the picture's line and the scenes: the picture
            # stays whole. The button has keyboard focus; nothing is made until it is pressed. While the video is made the
            # picture's box says so (and "Making the video" is said once); then the video lies over the picture,
            # labelled 'AI video', plays once and rests on its last frame, with keyboard focus on it and "Video ready"
            # said once, and the picture's caption 'Look and fit will differ' still under it, above "Drag to turn",
            # "Play again" and "Show picture". Dragging across it, or the arrow keys, turn the model (a slider, its
            # value in degrees) without moving on to another outfit; "Play again" plays it from the start; "Show
            # picture" brings back the picture and its dots. Reloaded, playing it again is free. The customer's one
            # video a day is then used: another outfit says "No videos left today: more tomorrow", which a screen reader
            # hears with its only button, Close. Nothing below the picture's line and scenes moves at any point. On a
            # short phone, where the line and the scenes are below the tab bar, the page goes up as the offer opens,
            # so that the whole offer and the button with keyboard focus show above the tab bar: for a first offer, for
            # "No videos left today", and for a video that could not be made (said when the customer is still looking
            # at its picture; the page stays where it is when he has read on past it). Places are measured on the
            # page, not on the screen, so that a page that went up is not taken for one whose parts moved.
            page.goto(base + "/outfits", wait_until="networkidle")
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
                        scenes: box(slide.querySelector('.scenes')).top, scenes_end: box(slide.querySelector('.scenes')).bottom,
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
                        under: Math.abs(o.top - p.bottom) < 1, height: o.height, end: o.bottom, page: document.documentElement.scrollWidth,
                        side_by_side: buttons.length === 2 && Math.abs(buttons[0].top - buttons[1].top) < 1,
                        whole: words.scrollWidth <= words.clientWidth + 1 && o.left >= 0 && o.right <= innerWidth,
                        instead: [...slide.querySelectorAll('.look > .look-line, .look > .scenes')].every(el => !el.getClientRects().length),
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
            # most, whole, and its two buttons side by side, in the room of the picture's line and the scenes. All of it
            # shows above the tab bar once the page has come to rest (where less motion is asked for too: 375 x 667), the
            # button with keyboard focus too.
            for width, height, scheme in ((320, 568, "light"), (360, 740, "light"), (375, 667, "dark"), (390, 664, "light"),
                                          (390, 844, "dark")):
                context, other = logged_in_on(browser, viewport={"width": width, "height": height}, is_mobile=True,
                                              has_touch=True, color_scheme=scheme,
                                              reduced_motion="reduce" if height == 667 else "no-preference")
                other.goto(base + "/outfits", wait_until="networkidle")
                other.wait_for_selector(f"{first} .look-pic img")
                other.evaluate("() => document.querySelectorAll('main > .demo').forEach(notice => notice.remove())")
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
                    f"{where}: the offer took more room than the line and the scenes: {placed}, {shut}"
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
                other.goto(base + "/outfits", wait_until="networkidle")
                other.wait_for_selector(f"{first} .look-pic img")
                other.evaluate("() => document.querySelectorAll('main > .demo').forEach(notice => notice.remove())")
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
                f"the offer is not under the picture, its two buttons side by side, in place of the line and the scenes: {placed}"
            assert placed["end"] <= before["scenes_end"] + 0.5 and placed["title"] == before["title"], \
                f"the offer took more room than the line and the scenes, and what is under them moved: {placed}, {before}"
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
                        line_under: Math.abs(line.top - p.bottom) < 1, line: slide.querySelector('.vid-line').innerText.replace(/\\s+/g, ' ').trim(),
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
            assert len(made) == 1 and made[0] == looks.load_rules()["videos"]["text"], "the video was not asked for once, in the set words"
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
            page.locator(".reel-nav.next").click()
            second = "#reel .slide:nth-child(2)"
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
                f"'No videos left today' is not said under the picture, in place of the line and the scenes: {placed}"
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
            other.goto(base + "/outfits", wait_until="networkidle")
            other.evaluate("() => { document.querySelectorAll('main > .demo').forEach(notice => notice.remove());"
                           " const r = document.getElementById('reel'); r.style.scrollBehavior = 'auto';"
                           " r.scrollLeft = r.clientWidth; r.style.scrollBehavior = ''; }")
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
            page.goto(base + "/outfits", wait_until="networkidle")     # the next steps start from the first outfit
            page.wait_for_selector(f"{first} .look-pic img")

            for width, height, touch in ((390, 844, True), (1280, 860, False)):
                for scheme in ("light", "dark"):
                    context, other = logged_in_on(browser, viewport={"width": width, "height": height}, is_mobile=touch,
                                                  has_touch=touch, color_scheme=scheme, reduced_motion="reduce")
                    other.goto(base + "/outfits", wait_until="networkidle")
                    other.wait_for_selector(f"{first} .look-pic img")
                    other.evaluate("() => document.querySelectorAll('main > .demo').forEach(notice => notice.remove())")
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
                        box = el => el.getBoundingClientRect(), meta = [...slide.querySelectorAll('.about-head h2, .board-cost, .heart')];
                        return {paused: v.paused, rest: v.duration - v.currentTime, page: document.documentElement.scrollWidth,
                                line_end: Math.max(...meta.map(el => box(el).bottom)), tabs: box(document.querySelector('nav.tabs')).top}; }""", first)
                    assert still["paused"] and still["rest"] < 0.2, f"{where}: with less motion asked for, the video played by itself: {still}"
                    assert still["page"] <= width, f"{where}: the page is {still['page']}px wide"
                    if touch:
                        assert still["line_end"] <= still["tabs"], f"{where}: the outfit's line ends under the tab bar: {still}"
                    context.close()

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

            page.goto(base + "/outfits", wait_until="networkidle")
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
                other.goto(base + "/outfits", wait_until="networkidle")
                other.wait_for_selector(f"{first} .look-pic img")
                motion_ended(other)
                found = small_with_room_to_tap(other, "on a phone")
                assert all(d["seen"] == 1 for d in found), f"on a phone, where nothing can be pointed at, the dots do not show: {found}"
            finally:
                context.close()

        def dot_opens_the_piece():
            spot = page.locator(f"{first} .spot").nth(0)
            spot.hover()
            assert spot.locator(".tip").is_visible(), "no label on hover"
            spot.click()
            page.wait_for_selector("dialog#piece[open]")
            assert page.locator("#piece-body h2").inner_text().strip(), "an empty pop-up"
            assert "outfits your pieces make" in page.locator("#piece-body").inner_text()

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
            # steps after this one. On a short phone the line is whole on the first screen, with the outfit's picture
            # box still above the tab bar, under the starter banner too.
            choose = page.locator("#piece-body .swap li:not(.out) button", has_text="Choose")
            assert choose.count() > 0, "nothing to swap for"
            # The store's own name for the option (lang=de: under its English name where there is one), which is
            # what the outfit's list of pieces shows.
            wanted = page.locator("#piece-body .swap li:not(.out)").nth(0).locator("[lang=de]").first.inner_text()
            swapped.update(choose.nth(0).evaluate("b => ({slot: b.form.getAttribute('action').split('/')[2], "
                                                  "product: b.closest('li').querySelector('[lang=de]').textContent.trim()})"))
            was = page.evaluate("""() => { const body = document.querySelector('#piece-body'), text = el => el.textContent.trim();
                const option = body.querySelector('.swap li:not(.out) form').closest('li');
                return {piece: text(body.querySelector('#piece-title')), name: text(body.querySelector('.piece-facts [lang=de]')),
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
                other.evaluate("() => document.querySelectorAll('main > .demo').forEach(notice => notice.remove())")
                other.wait_for_selector(f"{first} .look-pic img", timeout=20000)
                the_label_never_meets_a_dot(other, f"{width} x {height} after Choose")
                context.close()
            context, other = logged_in_on(browser, viewport={"width": 390, "height": 664}, is_mobile=True, has_touch=True)
            other.goto(changed_at, wait_until="networkidle")
            other.evaluate("() => document.querySelectorAll('main > .demo').forEach(notice => notice.remove())")  # (invented products)
            seen = other.evaluate("""() => { const box = el => el.getBoundingClientRect();
                const line = box(document.querySelector('main > .said')), undo = document.querySelector('main > .said button');
                return {top: line.top, bottom: line.bottom, starter: !!document.querySelector('.starter'),
                        stage: box(document.querySelector('#reel .slide:first-child .stage')).bottom,
                        tabs: box(document.querySelector('nav.tabs')).top,
                        target: parseFloat(getComputedStyle(undo, '::after').height)}; }""")
            context.close()
            assert 0 <= seen["top"] and seen["bottom"] <= seen["tabs"] and seen["stage"] <= seen["tabs"] + 0.5, \
                f"at 390 x 664 the line after Choose is not whole on the first screen, or the picture runs under the tab bar: {seen}"
            assert seen["target"] >= 44, f"Undo is a {seen['target']}px tall target"

            with page.expect_navigation(url="**/outfits?at=**"):     # (the address it leaves matches that too)
                page.locator("main > .said button", has_text="Undo").click()
            page.wait_for_load_state("networkidle")
            names = page.locator(f"{first} .piece-text span").all_inner_texts()
            assert was["name"] in names, f"after Undo the outfit shows {names}, not {was['name']!r}"
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
            # A piece's card says the same lines in the same order in the pop-up, on its Wardrobe card, on its own page
            # and on Buy: the store and 'Quality 73/100', the store's name for the product in English (lang=en) with its
            # own words under it (lang=de, smaller, or on a card where the English is already 13px, greyer), 'Fabric: …'
            # and 'Fit: …'. Every line inside its card, on a phone (light) and a computer (dark). The piece: the first
            # of the first outfit whose name the word list knows and whose cut is said.
            LINES = """root => {
                const box = root.getBoundingClientRect(), lines = {};
                const found = {by: root.querySelector('.by'), en: root.querySelector('[lang=en]'),
                               orig: root.querySelector('[lang=de]:not(.colour-name)'),
                               fabric: root.querySelector('.fabric'), fit: root.querySelector('.fit')};
                for (const [kind, el] of Object.entries(found)) {
                    if (!el) { lines[kind] = null; continue; }
                    const r = el.getBoundingClientRect(), cs = getComputedStyle(el);
                    lines[kind] = {text: el.textContent.replace(/\\s+/g, ' ').trim(), top: Math.round(r.top),
                                   size: parseFloat(cs.fontSize), colour: cs.color, shown: r.width > 0 && r.height > 0,
                                   inside: r.left >= box.left - 1 && r.right <= box.right + 1};
                }
                return {lines, wide: document.documentElement.scrollWidth};
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
                said = {}
                for where, seen in place.items():
                    assert seen["wide"] <= width + 1, f"at {width}px the {where} is wider than the screen"
                    lines = seen["lines"]
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
                    assert len(set(said[k].values())) == 1, f"at {width}px the four places say the {k} line differently: {said[k]}"

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
                assert seen["hidden"] and seen["seen"] + seen["hidden"] == other.locator("#wardrobe-body .by").count(), \
                    f"at 320px no card puts its quality on a line of its own: {seen}"
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
                other.wait_for_url(base + "/outfits")
                other.goto(base + "/", wait_until="networkidle")
                estimated = other.locator("#wardrobe-body .est")
                assert estimated.count(), "the jeans with no fabric on their label are not 'estimated'"
                tidy(other.locator("#wardrobe-body").evaluate(DOTS), "Wardrobe with the published jeans")
                other.goto(base + "/list", wait_until="networkidle")
                tidy(other.locator("main").evaluate(DOTS), "shopping list")
                caution = other.locator(".buy-main .fabric.caution")
                assert caution.count() == 1 and caution.inner_text().strip() == "Fabric not stated: check the product page", \
                    f"the jumper with no fabric says {[t.strip() for t in caution.all_inner_texts()]}"
                amber = other.evaluate("() => getComputedStyle(document.querySelector('.buy-main .fabric.caution')).color")
                ok = other.evaluate("() => { const e = document.createElement('i'); e.style.color = 'var(--ok)'; document.body.append(e);"
                                    " const c = getComputedStyle(e).color; e.remove(); return c; }")
                assert amber == ok, f"'Fabric not stated' is {amber}, not the amber of a caution ({ok})"
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
            # from the page's live region. The heart pressed with Enter keeps focus, and is called "Save outfit"
            # whether saved or not (pressed says which). Escape hides a dot's label, until a dot is pointed at again.
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
                page.locator(f"{first} .heart").focus()
                for pressed in ("true", "false"):           # saved, then not: the walk-through saves it later
                    page.keyboard.press("Enter")
                    # htmx takes over the new heart once it has settled (htmx-added gone, 20 ms): a key pressed
                    # before that would send the form without it, as a page of its own.
                    page.wait_for_selector(f"{first} form.save:not(.htmx-added) .heart[aria-pressed={pressed}]")
                    heart = page.evaluate("""() => ({on: document.activeElement.matches('#reel .slide:first-child .heart'),
                        name: document.activeElement.textContent.trim()})""")
                    assert heart["on"], f"after pressing the heart with Enter (aria-pressed {pressed}), focus left it"
                    assert heart["name"] == "Save outfit", f"the heart is called {heart['name']!r} (aria-pressed {pressed})"

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
            page.goto(base + "/outfits", wait_until="networkidle")
            page.locator(f"{first} .heart").click()
            page.wait_for_selector(f"{first} .heart[aria-pressed=true]")
            page.locator(f"{first} .about-actions a").click()
            page.wait_for_load_state("networkidle")
            assert page.locator(".buy").count() >= 2, "the buy page lists nothing"
            words = page.locator("main").inner_text()
            assert "checkout" in words, "it does not say how buying works"
            assert "VAT" in words and "delivery" in words, "it does not say what the prices include and leave out"
            assert page.locator("#summary").count() == 0, "the wardrobe's budget bar is on the outfit's Buy page"
            assert page.locator(".buy").count() == page.locator(".buy .pic").count(), "a line has no photo or swatch"
            # A new customer's sizes are the example's: the page says so before he orders in them, and he can keep them.
            sizes = page.locator(".your-sizes")
            assert "Your sizes: Tops M" in sizes.inner_text() and "example sizes" in sizes.inner_text(), \
                "the example sizes are not called example sizes"
            change = sizes.locator("a[href$='#sizes']").bounding_box()
            assert change["height"] >= 24, f"'Change' (your sizes) is {change['height']:.1f}px tall: under 24px to tap"
            buy_page = page.url
            sizes.locator("button:has-text('These are my sizes')").click()
            page.wait_for_load_state("networkidle")
            assert page.url == buy_page, "keeping the sizes leaves the Buy page"
            assert "Your sizes: Tops M" in page.locator(".your-sizes").inner_text(), "the sizes are no longer said"
            assert "example sizes" not in page.locator("main").inner_text(), "the example warning stays after 'These are my sizes'"
            page.goto(base + "/outfits?occasion=saved", wait_until="networkidle")
            assert page.locator("#reel .slide").count() == 1, "the saved outfit is not under Saved"
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
                store = other.locator(".store-list").filter(has=other.locator("[data-open-next]")).first
                button = store.locator("[data-open-next]")
                name = button.get_attribute("data-store")
                pages = store.locator("a.buy-product").evaluate_all("links => links.map(a => a.href)")
                total = len(pages)
                assert total >= 2, "the example list has no store with two products"
                assert "Open all" not in other.locator("main").inner_text(), "the page still promises to open all at once"
                assert button.inner_text().strip().startswith(f"Open the first of {total} at {name}"), \
                    f"the button says '{button.inner_text().strip()}'"
                assert store.locator(".buy-opened:visible").count() == 0, "a line is ticked before anything was opened"
                size = button.bounding_box()
                assert size["height"] >= 24, f"the button is {size['height']:.0f}px tall: under 24px to tap"
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
                    said = store.locator("[data-open-status]").inner_text()
                    if number < total:
                        assert f"{number} of {total} opened" in said, f"after tap {number} it says '{said}'"
                        assert button.inner_text().strip().startswith(f"Open the next at {name}"), "the button does not offer the next"
                    else:
                        assert f"All {total} opened" in said, f"after the last tap it says '{said}'"
                # A product's own link ticks its line too, and the ticks are still there after a look at another page.
                lone = other.locator(".store-list").filter(has_not=other.locator("[data-open-next]")).locator("a.buy-product").first
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
                assert page.locator(".buy-product").first.is_visible(), "the product names are not printed"
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
                phone.wait_for_url(base + "/outfits")
                phone.goto(base + "/profile", wait_until="networkidle")

                # The tabs: a tablist, the first open, the others' controls hidden.
                tabs = phone.get_by_role("tab")
                assert tabs.all_inner_texts() == ["You", "Body", "Sizes", "Colours", "Budget", "Stores"], \
                    f"the tabs: {tabs.all_inner_texts()}"
                expect(phone.get_by_role("tab", name="You")).to_have_attribute("aria-selected", "true")
                assert phone.locator(".cc-panel:visible").evaluate_all("ps => ps.map(p => p.dataset.tab)") == ["you", "you"], \
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
                            ("tab-you", "panel-you photo-panel"), ("tab-stores", "panel-stores"),
                            ("tab-you", "panel-you photo-panel"), ("tab-stores", "panel-stores")]
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
                                                           "panel-budget", "panel-stores", "photo-panel")], \
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
                phone.wait_for_url(base + "/outfits")
                phone.goto(base + "/list", wait_until="networkidle")
                assert "Weekday" in phone.locator("main").inner_text(), "the starter shopping list has nothing from Weekday"
                phone.goto(base + "/profile#stores", wait_until="networkidle")
                expect(phone.locator("#tab-stores")).to_have_attribute("aria-selected", "true")
                assert phone.evaluate(stores_of) == [["cos", True, "COS · Rakuten partner"],
                                                     ["weekday", True, "Weekday · Rakuten partner"]], phone.evaluate(stores_of)
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
                phone.get_by_role("checkbox", name="Weekday · Rakuten partner").tap()
                expect(phone.locator("[data-store-said]")).to_be_hidden()
                # The last store with products cannot be unticked, however many of the six are ticked.
                phone.get_by_role("checkbox", name="COS · Rakuten partner").tap()
                expect(phone.get_by_role("checkbox", name="COS · Rakuten partner")).to_be_checked()
                said = "At least one store with products must stay ticked: your pieces need a store to come from."
                expect(phone.locator("[data-store-said]")).to_have_text(said)
                expect(phone.locator("[data-store-said]")).to_be_in_viewport()
                assert phone.locator("#announce").text_content() == said, "a screen reader is not told"
                phone.focus("input[name=stores][value=cos]")
                phone.keyboard.press("Space")
                expect(phone.get_by_role("checkbox", name="COS · Rakuten partner"), "by keyboard too").to_be_checked()
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
                phone.get_by_role("checkbox", name="Weekday · Rakuten partner").tap()
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
                phone.wait_for_url(base + "/outfits")
                assert starter(phone)["words"] == starter_words, "the second customer's outfits have no starter banner"
                phone.locator(".starter a", has_text="Make them mine").click()
                phone.wait_for_url(base + "/profile")
                notes = example_notes(phone)
                assert notes == ["These are example values. Change them to yours and save: your plan is rebuilt around them, "
                                 "then you see the outfits."], f"a new account's Profile says of its example values: {notes}"
                pick_colours(phone, ("black", "grey", "white"))
                phone.click("button:has-text('Save profile')")
                phone.wait_for_url(base + "/outfits")
                phone.wait_for_load_state("networkidle")
                seen = starter(phone)
                assert seen["words"] is None and seen["bar"], f"after the first save the banner stays or the bar is not back: {seen}"
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
                # The card's link is named "<piece>: see all options"; a screen reader hears its note as well.
                link = phone.locator(f"#{card} .slot-main")
                expect(link, "a screen reader is not told why the piece is empty").to_have_accessible_description(
                    re.compile(r"^Not in Stilsmith's product list in \w"))
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
                expect(link, "the piece's link does not say what it leads to").to_have_accessible_name(
                    re.compile(r"^" + re.escape(colour.label) + r" .*: see all options$"))
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
                phone.wait_for_url(base + "/outfits")
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
            # He kept the example sizes as his on the Buy page: the one note about example values no longer calls them so.
            notes = example_notes(page)
            assert len(notes) == 1 and notes[0].startswith("You said these sizes are yours; the rest are example values."), \
                f"after 'These are my sizes' the Profile says of its example values: {notes}"
            pick_colours(page, ("black", "grey", "white"))
            open_tab(page, "you")
            page.locator("input[name=use][value=office]").check(force=True)
            page.click("button:has-text('Save profile')")
            page.wait_for_url(base + "/outfits")
            in_view("main > .flash", "Your plan now has")
            seen = starter(page)
            assert seen["words"] is None and seen["bar"], f"after the first save the banner stays or the bar is not back: {seen}"
            said = page.locator("main > .flash").first.inner_text()
            page.goto(base + "/slots", wait_until="networkidle")
            names = [name.strip() for name in page.locator(".slot-list .nm").all_inner_texts()]
            for colour in ("Black", "Grey", "White"):
                assert any(name.startswith(colour + " ") for name in names), f"no {colour.lower()} piece in the plan: {names}"
            assert not any(name.startswith(("Navy ", "Olive ")) for name in names), f"the old colours are still planned: {names}"
            page.goto(base + "/", wait_until="networkidle")
            lock = page.locator(f"#lock-{swapped['slot']}")
            if lock.count():            # the new plan has the swapped piece: its product and lock stay
                assert "Kept your 1 hand-picked piece" in said, f"the message does not count the kept piece: {said!r}"
                assert lock.get_attribute("aria-pressed") == "true", "the kept piece is no longer locked"
                card = page.locator(f"#card-{swapped['slot']} .item[lang=de]").inner_text()   # the store's own words
                assert swapped["product"] in card, f"the kept piece shows {card!r}, not {swapped['product']!r}"
            else:
                assert "Not kept: " in said, f"the swapped piece is gone and the message does not say so: {said!r}"

        def the_heart_saves_and_takes_back():
            # The heart under an outfit saves it; a tap on the filled heart takes it out of the saved ones again: on a
            # phone by touch, on a computer by mouse, and with JavaScript off. The second tap works the moment the
            # heart has filled, and the Saved chip's number is right at once ("Saved 1", then "Saved"). A heart always
            # does what it showed: filled on a page that has gone out of date (the outfit removed meanwhile under
            # Saved), a tap leaves it removed rather than saving it again. Under Saved, a tap on the heart takes the
            # outfit off the page at once, the page says which one in a line the screen shows, and its Undo puts it
            # back. A customer of his own, so that what he saves is not in the other steps' way; his account is deleted
            # when the step ends, passed or failed (delete_the_hearts_customer), so that the step leaves nothing
            # behind on whatever server it is run against: a night preview once kept fifteen "heart-" accounts.
            hearter = "heart-" + EMAIL
            context = browser.new_context()
            signing = context.new_page()
            signing.goto(base + "/signup", wait_until="networkidle")
            signing.fill("input[name=email]", hearter)
            signing.fill("input[name=password]", PASSWORD)
            signing.click("button:has-text('Create account')")
            signing.wait_for_url(base + "/outfits")
            context.close()
            second = "#reel .slide:nth-child(2)"
            for where, phone, script in (("phone", True, True), ("computer", False, True), ("phone, no JavaScript", True, False)):
                screen = {"width": 390, "height": 844} if phone else {"width": 1280, "height": 860}
                context = browser.new_context(viewport=screen, is_mobile=phone, has_touch=phone, java_script_enabled=script)
                try:
                    other = context.new_page()
                    other.on("response", lambda r: failures.append(f"{r.status} {r.request.method} {r.url.replace(base, '')[:100]}")
                             if r.status >= 400 and r.url.startswith(base) and "does-not-exist" not in r.url else None)
                    other.goto(base + "/login", wait_until="networkidle")
                    other.fill("input[name=email]", hearter)
                    other.fill("input[name=password]", PASSWORD)
                    other.click("button:has-text('Log in')")
                    other.wait_for_url(base + "/outfits")
                    other.wait_for_load_state("networkidle")

                    def tap(view, selector: str) -> None:
                        (view.locator(selector).first.tap() if phone else view.locator(selector).first.click())

                    def heart(view, slide: str, pressed: str) -> None:
                        try:
                            view.wait_for_selector(f"{slide} .heart[aria-pressed={pressed}]", timeout=5000)
                        except Exception:  # noqa: BLE001 - it never came: said in the customer's terms
                            raise AssertionError(f"{where}: after a tap the heart is not {'filled' if pressed == 'true' else 'empty'}") from None

                    def chip(view, words: str, when: str) -> None:
                        if not script:
                            view.wait_for_load_state("networkidle")
                        try:            # (with JavaScript the chip is swapped in a moment after the tap)
                            view.wait_for_function("words => document.querySelector('.chips a[href$=occasion\\\\=saved]').textContent.trim() === words",
                                                   arg=words, timeout=3000) if script else None
                        except Exception:  # noqa: BLE001 - it never said so: reported just below, in words
                            pass
                        seen = view.locator(".chips a[href$='occasion=saved']").inner_text().strip()
                        assert seen == words, f"{where}: {when}, the chip says {seen!r}, not {words!r}"

                    def truly(pressed: str, when: str) -> None:      # what a fresh page says of the first outfit
                        other.goto(base + "/outfits", wait_until="networkidle")
                        seen = other.get_attribute(f"{first} .heart", "aria-pressed")
                        assert seen == pressed, f"{where}: {when}, a reload shows the heart {'filled' if seen == 'true' else 'empty'}"

                    # Saved, and taken back with the very next tap.
                    chip(other, "Saved", "before anything is saved")
                    tap(other, f"{first} .heart")
                    heart(other, first, "true")
                    tap(other, f"{first} .heart")           # at once: the moment the heart has filled
                    heart(other, first, "false")
                    chip(other, "Saved", "saved and taken back")
                    truly("false", "saved and taken back")
                    tap(other, f"{first} .heart")
                    heart(other, first, "true")
                    chip(other, "Saved 1", "with one outfit saved")
                    truly("true", "saved")

                    # A heart that shows filled takes the outfit out, also when it was removed meanwhile elsewhere.
                    elsewhere = context.new_page()
                    elsewhere.goto(base + "/outfits?occasion=saved", wait_until="networkidle")
                    tap(elsewhere, f"{first} .heart")
                    elsewhere.wait_for_url("**removed=*")
                    elsewhere.close()
                    assert other.get_attribute(f"{first} .heart", "aria-pressed") == "true"     # this page still shows it filled
                    tap(other, f"{first} .heart")
                    heart(other, first, "false")
                    truly("false", "a filled heart tapped on a page gone out of date")

                    # Under Saved: the outfit leaves the page, the page says so where the screen shows it, and Undo.
                    tap(other, f"{first} .heart")
                    heart(other, first, "true")
                    if phone and script:
                        other.evaluate("document.getElementById('reel').scrollTo({left: innerWidth, behavior: 'instant'})")
                        other.wait_for_timeout(400)         # the row has come to rest on the second outfit
                    tap(other, f"{second} .heart")
                    heart(other, second, "true")
                    chip(other, "Saved 2", "with two outfits saved")
                    other.goto(base + "/outfits?occasion=saved", wait_until="networkidle")
                    keys = [slide.get_attribute("id") for slide in other.locator("#reel .slide").all()]
                    assert len(keys) == 2, f"{where}: two outfits saved, {len(keys)} under Saved"
                    tap(other, f"{first} .heart")
                    other.wait_for_url("**removed=*")
                    other.wait_for_load_state("networkidle")
                    left = [slide.get_attribute("id") for slide in other.locator("#reel .slide").all()]
                    assert left == keys[1:], f"{where}: the outfit removed under Saved is still on the page ({len(left)} shown)"
                    chip(other, "Saved 1", "one of two removed under Saved")
                    said = other.locator("main > .said")
                    assert said.count() == 1 and "Removed" in said.inner_text() and "from your saved outfits" in said.inner_text(), \
                        f"{where}: the page does not say an outfit was removed"
                    box = said.bounding_box()
                    assert box["y"] >= 0 and box["y"] + box["height"] <= screen["height"], \
                        f"{where}: the line that says an outfit was removed, with Undo, is off the screen ({box})"
                    tap(other, "main > .said button:has-text('Undo')")
                    other.wait_for_url("**occasion=saved#outfit-*")
                    other.wait_for_load_state("networkidle")
                    back = [slide.get_attribute("id") for slide in other.locator("#reel .slide").all()]
                    assert back == keys, f"{where}: Undo did not put the removed outfit back where it was"
                    chip(other, "Saved 2", "after Undo")
                    assert other.locator("main > .said").count() == 0, f"{where}: after Undo the page still says 'Removed'"
                    for n in (1, 0):                         # both removed: nothing left for the next screen
                        other.goto(base + "/outfits?occasion=saved", wait_until="networkidle")
                        tap(other, f"{first} .heart")
                        other.wait_for_url("**removed=*")
                        other.wait_for_load_state("networkidle")
                        assert other.locator("#reel .slide").count() == n, f"{where}: {n} saved outfits left, but not {n} shown"
                    chip(other, "Saved", "everything removed")
                    assert "Nothing saved yet" in other.locator("main").inner_text(), f"{where}: no word that nothing is saved"
                except BaseException:
                    context.close()
                    delete_the_hearts_customer(hearter)     # a failed step leaves no account behind either
                    raise
                else:
                    context.close()
            delete_the_hearts_customer(hearter)
            # Gone: his address and password no longer log anyone in.
            context = browser.new_context()
            try:
                gone = context.new_page()
                gone.goto(base + "/login", wait_until="networkidle")
                gone.fill("input[name=email]", hearter)
                gone.fill("input[name=password]", PASSWORD)
                gone.click("button:has-text('Log in')")
                gone.wait_for_load_state("networkidle")
                assert "/login" in gone.url, f"the heart step's customer still has an account (now at {gone.url})"
            finally:
                context.close()

        def delete_the_hearts_customer(email: str) -> None:
            """Delete the account the heart step made, the way a customer does: Account, "Delete my account"."""
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

        def motion_quick_and_still():
            # Stilsmith moves to answer the customer (app.css "Motion"), on a phone (390 x 844, by touch) and a computer:
            # a tab changes the page with a slide, forward along the tabs and back again, and a tap made while it slides
            # is not lost; the pop-up slides up and, closing, lets a tap through to the page at once; the heart grows in
            # as the outfit is saved; the AI picture, when it arrives, comes up whole over the pieces' photos (never a
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
            signing.wait_for_url(base + "/outfits")
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
            # Closing, it lets a tap through to the page at once.
            tap(other, True, "dialog#piece .sheet-close")
            through = other.evaluate("""s => { const heart = document.querySelector(s + ' .heart'), box = heart.getBoundingClientRect();
                const under = document.elementFromPoint(box.left + box.width / 2, box.top + box.height / 2);
                return {open: document.querySelector('dialog#piece').open, heart: !!under && heart.contains(under)}; }""", first)
            assert not through["open"] and through["heart"], f"while the pop-up closes a tap does not reach the page: {through}"
            motion_ended(other)
            quick(other, "the pop-up closing")
            # The heart grows in as the outfit is saved.
            flipped = "([s, was]) => document.querySelector(s + ' .heart').getAttribute('aria-pressed') !== was"
            was = other.get_attribute(f"{first} .heart", "aria-pressed")
            for _ in range(2):                           # (an outfit saved already is first unsaved)
                now = other.get_attribute(f"{first} .heart", "aria-pressed")
                tap(other, True, f"{first} .heart")
                other.wait_for_function(flipped, arg=[first, now])
                if now == "false":
                    break
            try:        # (HTMX hands the new heart over a moment after it has swapped it in: it grows from then)
                other.wait_for_function("() => window.moved.some(m => m.what === 'heart-pop')", timeout=1000)
            except Exception:  # noqa: BLE001 - the assertion below says what went wrong
                pass
            motion_ended(other)
            assert any(m["what"] in ("heart-pop", "heart-ring") for m in moved(other)), "the heart did not grow in as the outfit was saved"
            quick(other, "the heart")
            if was == "false":
                tap(other, True, f"{first} .heart")
                other.wait_for_selector(f"{first} .heart[aria-pressed=false]")
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
            was = other.get_attribute(f"{first} .heart", "aria-pressed")
            tap(other, True, f"{first} .heart")
            other.wait_for_function("([s, was]) => document.querySelector(s + ' .heart').getAttribute('aria-pressed') !== was", arg=[first, was])
            nothing_moved("the heart")
            tap(other, True, f"{first} .heart")
            other.wait_for_function("([s, was]) => document.querySelector(s + ' .heart').getAttribute('aria-pressed') === was", arg=[first, was])
            arrives_whole(other, "390 x 844, less motion", range(241, 281))
            nothing_moved("the picture arriving")
            context.close()
            assert not stirred, "with less motion asked for, these moved: " + "; ".join(stirred)

        def the_outfit_on_a_phones_first_screen():
            # The model view is the heart of Stilsmith. On a phone (390 x 844) the first screen shows the AI picture and,
            # under it, the outfit's title, its price and the heart, above the tab bar; on a shorter one (Safari's
            # 390 x 664) at least the whole picture with its lowest dot, also under a message at the top of the page.
            # The chips and Shuffle are one row (on a narrow phone the chips scroll sideways inside it, and a chip reached
            # by keyboard comes whole into it, ring and all), the chip that is on is marked, the line over the outfits
            # says how to see the next one (swipe on a touch screen, the arrows with a mouse), each outfit's title is a
            # heading that agrees with the chip, 'Buy this outfit' is the main button, and the outfit row does not cut
            # off the focus ring of the heart or of 'Buy this outfit'.
            def opened(width: int, height: int, touch: bool, path: str = "/outfits"):
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
                # of the real catalogue never see: it is taken away to measure the page as they get it.
                other.evaluate("() => document.querySelectorAll('main > .demo').forEach(notice => notice.remove())")
                return context, other

            def screen(other) -> dict:
                return other.evaluate("""() => {
                    const slide = document.querySelector('#reel .slide:first-child'), box = el => el.getBoundingClientRect();
                    const picture = box(slide.querySelector('.look-pic'));
                    return {top: picture.top, bottom: Math.max(picture.bottom, ...[...slide.querySelectorAll('.spot')].map(d => box(d).bottom)),
                            line: Math.max(...[...slide.querySelectorAll('.about-head h2, .count, .board-cost, .heart')].map(el => box(el).bottom)),
                            tabs: box(document.querySelector('nav.tabs')).top};
                }""")

            def rings_whole(other, where: str) -> None:
                for what in (".heart", ".about-actions a"):
                    other.keyboard.press("Tab")             # a key was pressed: focus from here on shows its ring
                    ring = other.evaluate("""s => {
                        const el = document.querySelector(s);
                        el.focus();
                        el.scrollIntoView({block: 'center'});
                        const style = getComputedStyle(el), r = el.getBoundingClientRect(), row = document.getElementById('reel').getBoundingClientRect();
                        const reach = parseFloat(style.outlineWidth) + parseFloat(style.outlineOffset);
                        return {shown: el.matches(':focus-visible') && style.outlineStyle !== 'none',
                                cut: [['left', r.left - reach < row.left], ['top', r.top - reach < row.top],
                                      ['right', r.right + reach > row.right], ['bottom', r.bottom + reach > row.bottom]]
                                     .filter(side => side[1]).map(side => side[0])};
                    }""", f"{first} {what}")
                    assert ring["shown"] and not ring["cut"], f"{where}: the focus ring of {what} is cut off at {ring['cut']}"

            context, other = opened(390, 844, True)
            seen = screen(other)
            extra = other.locator("#summary").bounding_box()["height"] - 48     # the bar's second line, if pieces have nothing to buy
            assert seen["top"] <= 210 + max(0, extra), f"at 390 x 844 the picture starts {seen['top']:.0f}px down"
            assert seen["line"] <= seen["tabs"], \
                f"at 390 x 844 the outfit's title, price and heart end at {seen['line']:.0f}px, under the tab bar at {seen['tabs']:.0f}px"
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

            for path, where in (("/outfits", "390 x 664"), ("/outfits?at=no~such~outfit", "390 x 664 under a message")):
                context, other = opened(390, 664, True, path)
                seen = screen(other)
                assert seen["bottom"] <= seen["tabs"], f"at {where} the picture ends at {seen['bottom']:.0f}px, under the tab bar at {seen['tabs']:.0f}px"
                if "at=" in path:
                    message = other.locator("main > .flash").first.bounding_box()
                    assert message and 0 <= message["y"] and message["y"] + message["height"] <= seen["tabs"], \
                        f"the message at the top of the outfits is not whole on the first screen: {message}"
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
                return other.evaluate("() => document.getElementById('summary').getBoundingClientRect().top") == 0

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
                assert said == ["Added “Oxford-Hemd Regular Fit”: its name, price, colour and fabric were read from the page "
                                "you saved — add the sizes under “Add details”."], f"a Hirmer link with its saved page: {said}"
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
                assert said == [f"Not added: “{women}” is a women's product, and Stilsmith is for menswear only."], said
                expect(phone.locator("#add .flash")).to_be_in_viewport()
                phone.locator("#cand-hirmer-9000001 button", has_text="Remove").click()     # as it was, for the next steps
                phone.wait_for_load_state("networkidle")
                assert not phone.locator("#cand-hirmer-9000001").count(), "the option added by its link was not removed"
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

        steps = [("create an account", sign_up), ("Stilsmith's own typefaces load", own_typefaces),
                 ("price levels and best for budget", price_levels),
                 ("price levels fit a phone and a computer", levels_fit_every_screen),
                 ("an option not in your size fades only its photo", out_of_size_fades_only_the_photo),
                 ("the picture of an outfit arrives by itself", picture_arrives),
                 ("the starter outfits fit three phones", starter_outfits_fit_a_phone),
                 ("on a phone it arrives labelled, without a jump", a_picture_arrives_on_a_phone_without_a_jump),
                 ("scenes: another drawn on a tap, the studio kept", scenes_for_the_picture),
                 ("a scene tap: never undone, and without JavaScript", a_scene_tap_is_kept),
                 ("see it move: a video, played, dragged, limited", see_it_move),
                 ("the dots: small, there when pointed at", the_dots_small_and_there_when_pointed_at),
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
                 ("the heart saves and takes back, Saved with Undo", the_heart_saves_and_takes_back),
                 ("a store's pages open one by one, each ticked", a_stores_pages_open_one_by_one),
                 ("the shopping list prints without photos", list_prints_without_photos),
                 ("log-in, first tab and wordmark lead to outfits", outfits_are_home),
                 ("the landing page says what Stilsmith is", the_landing_page),
                 ("public pages: no cookie, errors in plain words", public_pages_and_errors),
                 ("the wordmark Stilsmith fits at 320, 390 and 1280", the_wordmark_fits),
                 ("moving between tabs fetches only the page", tabs_fetch_only_the_page),
                 ("no page is wider than a phone or a computer screen", nothing_scrolls_sideways),
                 ("the owner's store catalogues, owners only", owners_store_catalogues),
                 ("put a model together", my_model), ("upload a photo, then delete it", my_photo),
                 ("Profile asks before unsaved changes are lost", unsaved_changes_are_not_lost_silently),
                 ("Profile is a character screen", profile_is_a_character_screen),
                 ("the store picker: only the stores ticked", the_store_picker),
                 ("colours picked by tapping swatches", colours_by_tapping_swatches),
                 ("one tap fills a piece the list has nothing for", one_tap_colour),
                 ("new colours rebuild the plan, keeping the swap", new_colours_rebuild_the_plan),
                 ("the outfit on a phone's first screen", the_outfit_on_a_phones_first_screen),
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
                verdict = f"FAILED: {type(problem).__name__}: {str(problem).splitlines()[0][:220]}"
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
