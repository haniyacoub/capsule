"""The app driven through a real browser: what the unit tests cannot see.

    python tests/browser_check.py

Needs the packages in requirements.txt and, once, `python -m playwright install chromium`.

It starts the app in production mode on a spare port, with a throwaway data folder and a
stand-in for the image service (nothing is sent anywhere and nothing is billed), then does
what a new customer would: signs up and lands on the starter outfits (a banner where the budget bar would be,
the whole picture above the tab bar on three phones), changes the price level, watches an outfit's picture
arrive (said to be drawing inside its box, then labelled 'AI picture' on itself, without the
page on a phone jumping), opens a piece from its dot, swaps it, leaves a layer off, opens a piece on a phone
(named by its product, the quick changes on the first screen, the page behind it staying put, and back from
comparing all options to the same outfit), tabs up and down a pop-up that scrolls (nothing with keyboard focus
hidden under its top row), sees that with scrollbars shown the page behind the pop-up does not move sideways,
moves between outfits (by keyboard too: Next among the first Tab stops, focus going with the outfit shown, which a
screen reader hears named, Tab leading into the outfit shown and Next keeping focus at the end of the row, the heart
keeping focus, Escape hiding a dot's label),
saves and "buys" one (keeping the example sizes as his own), prints the shopping list,
logs in again and lands on the outfits, puts a model together, uploads a photo, sees Profile ask before a
budget or colours changed and not saved would be lost, saves new colours (the plan is rebuilt,
keeping the swapped piece, and the budget bar takes the banner's place), sees that a phone's first
screen shows the outfit on the model with its price and the heart (and every chip over it, whole,
by keyboard), tabs through three pages to see that nothing with keyboard focus is hidden under the
budget bar or the tab bar, locks and chooses on a piece's page by keyboard (focus stays where it was) and pastes
a link that is not a store's (answered inside that section, on a phone's screen, with JavaScript on and off),
and deletes the account.

On the way a second customer, on a small product list published for that step alone, goes from the
starter outfits to his profile with "Make them mine" and fills a piece the list has nothing for with one tap.
A third picks his colours on a phone by tapping swatches (and by keyboard), sees his first liked colour that is not a
neutral become the plan's accent, and then types colours into the two text fields with JavaScript switched off.
And with the invented sample stores' feeds imported, the customer finds no store catalogues (/stores) until he is
marked as an owner; then his Account page leads to them, on a phone and on a computer.

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
                  OPENAI_API_KEY="stand-in", SITE_URL="http://127.0.0.1")
for name in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "SMTP_URL"):
    os.environ.pop(name, None)
sys.path.insert(0, str(ROOT))

from playwright.sync_api import expect, sync_playwright  # noqa: E402
from werkzeug.serving import make_server  # noqa: E402

from wardrobe import colours, imagegen  # noqa: E402
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

failures: list[str] = []
swapped: dict[str, str] = {}    # the piece swapped inside an outfit: its slot and the product chosen
heard: list[str] = []           # every address the server was asked for, in order (see main)
PASSWORD = "only for this check 123"
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

        def in_view(selector: str, words: str) -> None:
            """A message is where the eye is after the page has jumped: on the screen, with nothing over it."""
            page.wait_for_selector(selector)
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

        def pick_colours(where_page, liked=(), avoided=()) -> None:
            """Colours chosen on Profile the way a customer does: by tapping their swatches. Whatever is chosen already
            is cleared first (a liked colour takes two taps, one to avoid a single tap), then each liked colour is
            tapped once, most important first, and each to avoid twice. The two hidden fields the taps fill in must
            then name them in that order, as typing them would."""
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
            # The text font and the serif for titles come from Capsule itself. They must really load, under the
            # site's own security policy: a font that fails is replaced by another without any error to see.
            page.goto(base + "/profile", wait_until="networkidle")
            loaded = page.evaluate("() => document.fonts.ready.then(() => [...document.fonts]"
                                   ".filter(f => f.status === 'loaded').map(f => f.family.replace(/\"/g, '')))")
            assert "Instrument Sans" in loaded and "Instrument Serif" in loaded, f"Capsule's fonts did not load: {loaded}"
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
            # The outfits on the model are the heart of Capsule: logging in, the first tab and the wordmark
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
            # A stranger gives the page a few seconds. It says what Capsule is and who it is for, in plain words,
            # with the way in on a phone's first screen and one 'Log in' there (the header's), the headline in
            # Capsule's serif, no text cut off, nothing drawn from the demo data, and a description for search
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
                assert "men's" in seen["text"].split(), f"at {width}px the page does not say who Capsule is for"
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
            # sets the one its token needs. A page that isn't there says so in Capsule's words, with the wordmark, the
            # way home and the legal links, on a phone and on a computer. Capsule's icon is there for browsers to find.
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
                assert seen["links"][:2] == [["Capsule", "/"], ["Go to the home page", "/"]], f"the way home: {seen['links']}"
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
            assert page.locator(f"{first} .collage").is_hidden(), "the product photos still show under the picture"
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

        def dot_opens_the_piece():
            spot = page.locator(f"{first} .spot").nth(0)
            spot.hover()
            assert spot.locator(".tip").is_visible(), "no label on hover"
            spot.click()
            page.wait_for_selector("dialog#piece[open]")
            assert page.locator("#piece-body h2").inner_text().strip(), "an empty pop-up"
            assert "outfits your pieces make" in page.locator("#piece-body").inner_text()

        def swap_from_the_popup():
            choose = page.locator("#piece-body .swap li:not(.out) button", has_text="Choose")
            assert choose.count() > 0, "nothing to swap for"
            wanted = page.locator("#piece-body .swap li:not(.out) b").nth(0).inner_text()
            swapped.update(choose.nth(0).evaluate("b => ({slot: b.form.getAttribute('action').split('/')[2], "
                                                  "product: b.closest('li').querySelector('b').textContent.trim()})"))
            choose.nth(0).click()
            page.wait_for_url("**/outfits?at=**")
            page.wait_for_load_state("networkidle")
            names = page.locator(f"{first} .piece-text span").all_inner_texts()
            explained = page.locator(".flash").all_inner_texts()
            assert wanted in names or explained, f"{wanted!r} is not in the outfit and nothing says why"

        def leave_a_layer_off():
            # An outfit with a coat or jacket: the wardrobe page lists them first, so their slot leads its address.
            page.goto(base + "/outfits?n=60", wait_until="networkidle")
            slide = page.locator("#reel .slide:has(.piece-row:nth-child(1))").filter(has=page.locator(".pieces li:nth-child(5)")).first
            rows = slide.locator(".piece-row")
            before = rows.count()
            rows.nth(0).evaluate("row => row.click()")
            page.wait_for_selector("dialog#piece[open]")
            off = page.locator("#piece-body a", has_text="Leave the")
            assert off.count() == 1, "a five-piece outfit whose first piece cannot be left off"
            off.click()
            page.wait_for_load_state("networkidle")
            assert page.locator(f"{first} .piece-row").count() == before - 1, "the piece is still there"

        def the_piece_pop_up_on_a_phone():
            # Tapping a dot on a phone (390 x 844): the pop-up is named by the product, says 'Quality' next to the
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
            sheet = other.locator("dialog#piece")
            expect(sheet, "the pop-up is not named by the product").to_have_accessible_name(
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

        def pop_up_never_hides_the_focus():
            # The pop-up's top row (the piece's name and Close) stays while the sheet scrolls, and what has keyboard
            # focus is never hidden under it (WCAG 2.4.11). On a small phone and a short computer screen, where the
            # coat's pop-up scrolls, Tab goes from Close to the last control, then from the sheet's end Shift+Tab
            # comes back up to Close, so that each new focus comes in from below and from above. At least one of
            # five points of each must be inside the sheet with neither the top row nor Close over it.
            hidden: list[str] = []
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
                            return {seen, name: (el.innerText || el.getAttribute('aria-label') || el.tagName).replace(/\\s+/g, ' ').trim().slice(0, 50)};
                        }""")
                        if focus is None:
                            break
                        stops += 1
                        if not focus["seen"]:
                            hidden.append(f"{width} x {height} {key}: {focus['name']}")
                    assert stops >= 4, f"at {width} x {height}, {key} met only {stops} things to focus in the pop-up"
                context.close()
            assert not hidden, "hidden under the pop-up's top row while it had keyboard focus: " + "; ".join(hidden[:6])

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
            # sliding. The outfit on screen is kept in the address without a new step in the history, so Back from
            # 'Buy this outfit' and a reload come back to it.
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
            page.goto(base + "/profile", wait_until="networkidle")
            for group, value in (("age", "30s"), ("build", "athletic"), ("hair", "brown"), ("cut", "short")):
                page.locator(f'.pick input[name="{group}"][value="{value}"]').check(force=True)
            page.click("button:has-text('Save model')")
            page.wait_for_load_state("networkidle")
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
            # Profile has three forms: About you, the model and the photo. Sending the model's or the photo's loads the
            # page again, so a budget or a colour changed in About you and not saved would be lost without a word. The
            # page asks first, and only then; told no, it stays as it is. (A page of its own, to answer the question.)
            question = "You changed your sizes, colours or budget but didn't save them. Leave those changes unsaved?"
            said: list[str] = []
            reply = {"leave them": False}
            other = page.context.new_page()
            other.on("dialog", lambda d: (said.append(d.message), d.accept() if reply["leave them"] else d.dismiss()))
            other.on("pageerror", lambda e: failures.append(f"script error: {e}"))
            try:
                other.goto(base + "/profile", wait_until="networkidle")
                other.click("button:has-text('Save model')")
                other.wait_for_load_state("networkidle")
                assert not said, f"'Save model' asked although nothing had changed: {said}"
                assert "Model saved" in other.locator("#model .flash").inner_text(), "the model was not saved"

                other.goto(base + "/profile", wait_until="networkidle")
                budget = other.input_value("#budget")
                other.fill("#budget", str(int(budget) + 111))
                other.evaluate("() => { window.stayed = true; }")
                with other.expect_event("dialog"):
                    other.click("button:has-text('Save model')")
                assert said == [question], f"with the budget changed, 'Save model' asked {said}"
                assert other.evaluate("() => window.stayed === true") and other.locator("#model .flash").count() == 0, \
                    "told no, the page was sent all the same"
                assert other.input_value("#budget") == str(int(budget) + 111), "told no, the changed budget is gone"

                # The photo's button asks the same, once a photo is chosen and the box ticked (the browser's own checks
                # come first). This time the budget is back as it was and only a colour swatch was tapped: a tap is a
                # change too.
                photo = HOME / "me-again.png"
                photo.write_bytes(picture(600, 800, (150, 130, 120)))
                other.fill("#budget", budget)
                pick_colours(other, profile_mod.EXAMPLE["liked"], ["mustard"])
                other.set_input_files("[data-photo-form] input[type=file]", str(photo))
                other.wait_for_selector("[data-photo-form] [data-photo-ready]:not(.bad) img:not([hidden])")
                other.check("[data-photo-form] input[name=agree]")
                with other.expect_event("dialog"):
                    other.click("[data-photo-form] button")
                assert said == [question, question], f"with a colour changed, 'Use this photo' asked {said[1:]}"
                assert other.evaluate("() => window.stayed === true") and other.locator(".me img").count() == 0, \
                    "told no, the photo was sent all the same"

                reply["leave them"] = True        # told yes: the model is saved, the changes above are left unsaved
                other.click("button:has-text('Save model')")
                other.wait_for_load_state("networkidle")
                assert len(said) == 3 and "Model saved" in other.locator("#model .flash").inner_text(), \
                    "told yes, the model was not saved"
                assert other.input_value("#budget") == budget and other.input_value("input[name=refused]") == "", \
                    "the changes left unsaved were saved after all"
            finally:
                other.close()

        def one_tap_colour():
            # A piece the store list has nothing for says so and offers, in one tap, a colour Capsule has. The demo
            # data has something for every piece, so a small list is published first, the way the operator does:
            # jumpers in grey and navy only. A second customer who likes black, grey and white then has a black
            # jumper with nothing to buy. Every signed-in page picks up a list as soon as it is published, so it is
            # taken away again at the end: the first customer's steps stay on the demo data, whatever their order.
            jumper = {"category": "knit", "store": "zara", "currency": "EUR", "composition_text": "100% Wolle",
                      "fit": "regular", "sizes_all": ["S", "M", "L"], "sizes_in_stock": ["S", "M", "L"],
                      "image_url": "", "source": "collected"}
            products = [{**jumper, "id": f"zara-9{n}", "name": f"Pullover aus Wolle {n}", "slug": f"pullover-{n}",
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
                assert offer.count(), "no piece with nothing to buy offers a colour Capsule has"
                card = offer.evaluate("b => b.closest('article').id")
                colour = colours.get(offer.evaluate("b => b.form.elements.colour.value"))
                name = phone.locator(f"#{card} .slot-name").inner_text()
                qty = phone.locator(f"#{card} .qty")
                pieces = int(qty.inner_text().lstrip("×")) if qty.count() else 1
                before = missing()
                assert phone.locator(f"#{card} .note").inner_text().startswith("Not in Capsule's product list in "), \
                    "the empty piece does not say what is missing"
                # The card's link is named "<piece>: see all options"; a screen reader hears its note as well.
                link = phone.locator(f"#{card} .slot-main")
                expect(link, "a screen reader is not told why the piece is empty").to_have_accessible_description(
                    re.compile(r"^Not in Capsule's product list in \w"))
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
            # Every colour Capsule knows is a swatch to tap, five to a row on a phone. Once: liked, numbered in the
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
                phone.goto(base + "/profile", wait_until="networkidle")
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
                                           for c in colours.COLOURS.values()], "a swatch is not in the colour Capsule shows for it"
                assert grid["firstRow"] == 5 and grid["smallest"] >= 44, f"on a phone the swatches are laid out as {grid}"
                assert not phone.locator("input[name=liked]").is_visible() and not phone.locator("input[name=refused]").is_visible(), \
                    "the text fields are still shown beside the swatches"

                pick_colours(phone, ("navy", "olive"), ("black",))      # navy, olive, then black twice
                for name in ("Navy: liked, first", "Olive: liked, second", "Black: avoided"):
                    expect(phone.get_by_role("button", name=name, pressed=True), f"no swatch reads {name!r}").to_have_count(1)
                numbers = [phone.locator(f".swatch[data-colour={c}] b").inner_text() for c in ("navy", "olive")]
                assert numbers == ["1", "2"], f"navy and olive are numbered {numbers}"

                # By keyboard: Tab goes through every swatch in turn, and Space changes the one with focus, which says
                # what it is now.
                phone.focus("#budget")
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
                phone.goto(base + "/profile", wait_until="networkidle")
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
                card = page.locator(f"#card-{swapped['slot']} .item").inner_text()
                assert swapped["product"] in card, f"the kept piece shows {card!r}, not {swapped['product']!r}"
            else:
                assert "Not kept: " in said, f"the swapped piece is gone and the message does not say so: {said!r}"

        def the_outfit_on_a_phones_first_screen():
            # The model view is the heart of Capsule. On a phone (390 x 844) the first screen shows the AI picture and,
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

            def tab_through(other, path: str, key: str) -> None:
                other.goto(base + path, wait_until="networkidle")
                stops = 0
                for _ in range(400):
                    other.keyboard.press(key)
                    focus = other.evaluate("""() => {
                        const el = document.activeElement;
                        if (!el || el === document.body) return null;          // out of the page, past its last stop
                        if (el.dataset.walked) return 'again';                 // all the way round
                        el.dataset.walked = '1';
                        const bars = [document.getElementById('summary'), document.querySelector('nav.tabs')].filter(Boolean);
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
            for path in ("/", "/list", "/profile"):
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
            for path in ("/", "/list", "/profile"):
                tab_through(other, path, "Shift+Tab")
            context.close()
            assert not hidden, "hidden under the bars or off the screen while it had keyboard focus: " + "; ".join(hidden[:6])

        def a_pieces_page_by_keyboard():
            # On a piece's page the buttons stay where they are and keep keyboard focus: after 'Lock this choice' it is
            # on the same button, now 'Unlock'; after 'Choose this' on the mark that replaces it, and the next Tab
            # goes on through that option, not to the footer. What pasted links came to is said inside the 'Add a
            # product by link' section the page comes back to, on the screen, with JavaScript on and off. The piece
            # used is one Capsule picks (not the one swapped earlier), and it is left that way.
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
                raise AssertionError("no piece that Capsule picks, with another option to choose")
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
            page.locator("#slot-lock").focus()                     # back to what Capsule picks
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
                    assert said == [{"words": "Not added: “https://shop.example.org/jumper” is not a COS, Weekday or Zara link.",
                                     "inside": True, "status": "status", "shown": True}], \
                        f"with JavaScript {'on' if javascript else 'off'} the rejected link is answered: {said}"
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
            # The owner's view of every store's catalogue (/stores, owner.py), with the invented sample stores'
            # feeds imported. A customer who is no owner gets the page that is not there, and no link to it. Once
            # marked as an owner, the Account page leads to it: the stores and their products, no wider than a phone
            # or a computer screen, every photo from the feed's own address and shown whole, a filter that narrows
            # the list. The samples' photo addresses (example.com, example.org) are answered here with a stand-in:
            # nothing leaves this computer.
            from wardrobe import db
            from wardrobe.feeds import FORMATS, registry
            feeds = ROOT / "tests" / "fixtures" / "feeds"
            now = db.now_iso()
            for key, values in registry.load().items():     # (production leaves the samples out of `stores sync`)
                db.save_store(key, values)
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
                        return {path: location.pathname, wide: document.documentElement.scrollWidth,
                                stores: document.querySelectorAll('.cat-stores tbody tr').length,
                                rows: document.querySelectorAll('.cat-products tbody tr').length,
                                whole: imgs.every(i => getComputedStyle(i).objectFit === 'contain'),
                                loaded: imgs.filter(i => i.complete && i.naturalWidth > 0).length,
                                outside: imgs.filter(i => i.getAttribute('src').startsWith('/')).length};
                    }""")
                    assert seen.pop("wide") <= width + 1, f"the store catalogues are wider than {width}px"
                    assert seen == {"path": "/stores", "stores": 3, "rows": 17, "whole": True, "loaded": 17, "outside": 0}, \
                        f"the store catalogues at {width}px: {seen}"
                    other.select_option("select[name=size]", "M")
                    other.click("button:has-text('Show')")
                    other.wait_for_load_state("networkidle")
                    shown = other.locator(".cat-products tbody tr").count()
                    assert shown == 5 and other.evaluate("document.documentElement.scrollWidth") <= width + 1, \
                        f"filtered to size M at {width}px: {shown} products (5 in the samples have M in stock)"
                    context.close()
            finally:
                db.remove_owner(EMAIL)

        steps = [("create an account", sign_up), ("Capsule's own typefaces load", own_typefaces),
                 ("price levels and best for budget", price_levels),
                 ("price levels fit a phone and a computer", levels_fit_every_screen),
                 ("an option not in your size fades only its photo", out_of_size_fades_only_the_photo),
                 ("the picture of an outfit arrives by itself", picture_arrives),
                 ("the starter outfits fit three phones", starter_outfits_fit_a_phone),
                 ("on a phone it arrives labelled, without a jump", a_picture_arrives_on_a_phone_without_a_jump),
                 ("a dot on the picture opens the piece", dot_opens_the_piece),
                 ("swap a piece from the pop-up", swap_from_the_popup), ("leave a layer off", leave_a_layer_off),
                 ("the piece pop-up on a phone", the_piece_pop_up_on_a_phone),
                 ("the pop-up's top row never hides what has focus", pop_up_never_hides_the_focus),
                 ("the page behind the pop-up stays put", the_page_behind_the_pop_up_stays_put),
                 ("arrows and arrow keys", arrows_move),
                 ("arrows for every mouse, your place kept on Back", arrows_for_every_mouse_and_your_place_kept),
                 ("the outfit row by keyboard and screen reader", the_outfit_row_by_keyboard),
                 ("save an outfit and buy it", save_and_buy),
                 ("the shopping list prints without photos", list_prints_without_photos),
                 ("log-in, first tab and wordmark lead to outfits", outfits_are_home),
                 ("the landing page says what Capsule is", the_landing_page),
                 ("public pages: no cookie, errors in plain words", public_pages_and_errors),
                 ("moving between tabs fetches only the page", tabs_fetch_only_the_page),
                 ("no page is wider than a phone or a computer screen", nothing_scrolls_sideways),
                 ("the owner's store catalogues, owners only", owners_store_catalogues),
                 ("put a model together", my_model), ("upload a photo, then delete it", my_photo),
                 ("Profile asks before unsaved changes are lost", unsaved_changes_are_not_lost_silently),
                 ("colours picked by tapping swatches", colours_by_tapping_swatches),
                 ("one tap fills a piece the list has nothing for", one_tap_colour),
                 ("new colours rebuild the plan, keeping the swap", new_colours_rebuild_the_plan),
                 ("the outfit on a phone's first screen", the_outfit_on_a_phones_first_screen),
                 ("the budget bar never hides what has focus", budget_bar_never_hides_the_focus),
                 ("a piece's page by keyboard, links answered there", a_pieces_page_by_keyboard),
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
    print(f"\nAll steps passed ({len(asked)} pictures were asked of the stand-in).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
