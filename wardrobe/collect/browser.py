"""One ordinary browser window, used politely.

`Session.fetch(store, url)` is the only way the collector touches a store:

  * it uses a normal, visible Chrome window with its own profile folder —
    nothing about the browser is disguised or altered;
  * it reads the store's robots.txt first and refuses addresses that file
    disallows;
  * it waits a random few seconds between two pages of the same store;
  * if the store answers "Access Denied", shows a captcha or rate-limits, it
    raises `Blocked` — the caller then stops that store. Nothing is retried.

`Session.fetch_listing(store, base, url)` reads a category page as a visitor's
browser shows it: it waits until the page has stopped loading (at most the page
timeout), scrolls a few screens where the list grows as you scroll, and keeps
the JSON the page itself fetched while it loaded (the answers to the page's own
requests, read from the browser: the collector never sends a request of its own).
"""
from __future__ import annotations

import hashlib
import html as html_lib
import json
import os
import random
import re
import time
from pathlib import Path
from typing import Any

from .. import paths
from .robots import Robots

BLOCK_STATUSES = {401, 403, 429, 503}
BLOCK_WORDS = ("access denied", "captcha", "are you a robot", "pardon our interruption",
               "unusual traffic", "request unsuccessful", "verify you are human")


class Blocked(Exception):
    """The store refused the page. The collector stops for that store."""

    def __init__(self, store: str, url: str, reason: str):
        super().__init__(f"{reason} ({url})")
        self.store, self.url, self.reason = store, url, reason


class LimitReached(Blocked):
    """The run hit its own ceiling on page loads for one store."""


class BrowserClosed(Exception):
    """The browser window was closed while the collector was using it."""


class NotAllowed(Exception):
    """robots.txt asks automated visitors not to open this address."""


class PageMissing(Exception):
    """The page no longer exists (the store probably renamed a category)."""


# What fetch_listing keeps of the JSON a page fetched: answers of at most this size each, and this much in all.
JSON_EACH = 8_000_000
JSON_ALL = 40_000_000


def block_reason(status: int | None, title: str, html: str, check_body: bool = True) -> str | None:
    """Why this response counts as the store saying no — or None if it is a normal page."""
    if status in BLOCK_STATUSES:
        return f"the store answered {status} ({title.strip() or 'no title'})"
    if status is not None and status >= 500:
        return f"the store's server reported an error ({status})"
    text = title.lower()
    if check_body and len(html) < 20_000:   # block pages are small; real pages mention captchas in scripts
        text += " " + html.lower()
    for word in BLOCK_WORDS:
        if word in text:
            return f"the store showed a “{word}” page"
    return None


class Session:
    def __init__(self, settings: dict, log=print):
        self.settings = settings
        self.log = log
        self.pause = tuple(settings.get("pause_seconds", [5, 9]))
        self.timeout_ms = int(settings.get("page_timeout_seconds", 45)) * 1000
        self.max_pages = int(settings.get("max_pages_per_store", 160))
        self.pages_loaded: dict[str, int] = {}
        self._last_load: dict[str, float] = {}
        self._robots: dict[str, Robots] = {}
        self._seen: dict[str, str] = {}             # pages already read in this run
        self._listings: dict[str, tuple[str, list, str]] = {}   # category pages read in this run (fetch_listing)
        self.fetched: list = []                     # the JSON the last category page fetched (fetch_listing)
        self.landed = ""                            # the address it ended on
        self.scroll_screens = int(settings.get("scroll_screens", 4))
        self.settle_ms = int(settings.get("settle_seconds", 15)) * 1000
        cache = os.environ.get("WARDROBE_PAGE_CACHE")   # debugging aid: reuse saved pages
        self._disk_cache = Path(cache) if cache else None
        self._playwright: Any = None
        self._context: Any = None
        self._page: Any = None

    # ── opening and closing the browser ──────────────────────────────────────
    def __enter__(self) -> "Session":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def _start(self) -> None:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            raise RuntimeError(
                "Playwright is not installed. Run:  pip install -r requirements.txt") from None
        profile = paths.DATA_DIR / "browser-profile"
        profile.mkdir(parents=True, exist_ok=True)
        self._playwright = sync_playwright().start()
        options = dict(
            headless=bool(self.settings.get("headless", False)),
            locale="de-DE",
            viewport={"width": 1280, "height": 900},
            args=["--window-size=1320,1000"],
        )
        wanted = self.settings.get("browser", "chrome")
        try:
            self._context = self._playwright.chromium.launch_persistent_context(
                str(profile), channel="chrome" if wanted == "chrome" else None, **options)
        except Exception as first:  # noqa: BLE001 — e.g. Chrome is not installed
            if wanted != "chrome":
                raise
            self.log(f"  Could not start Google Chrome ({str(first).splitlines()[0][:80]}); "
                     "using Playwright's Chromium instead.")
            self._context = self._playwright.chromium.launch_persistent_context(str(profile), **options)
        self._page = self._context.pages[0] if self._context.pages else self._context.new_page()

    def close(self) -> None:
        for closer in (getattr(self._context, "close", None), getattr(self._playwright, "stop", None)):
            if closer:
                try:
                    closer()
                except Exception:  # noqa: BLE001 — closing twice or a crashed browser is fine
                    pass
        self._playwright = self._context = self._page = None

    # ── loading pages ────────────────────────────────────────────────────────
    def _cache_file(self, url: str) -> Path | None:
        if not self._disk_cache:
            return None
        self._disk_cache.mkdir(parents=True, exist_ok=True)
        return self._disk_cache / (hashlib.sha1(url.encode(), usedforsecurity=False).hexdigest()[:20] + ".html")

    def _load(self, store: str, url: str, check_body: bool = True, listing: bool = False) -> str:
        """Open one address in the browser, after the polite pause. Returns the HTML. With `listing`, it waits for the
        page as a visitor would (fetch_listing) and keeps the JSON the page fetched (self.fetched) and the address it
        ended on (self.landed)."""
        self.fetched, self.landed = [], url
        cached = self._cache_file(url)
        if cached and cached.exists():
            extra = cached.with_suffix(".json")
            if listing and extra.exists():
                kept = json.loads(extra.read_text(encoding="utf-8"))
                self.fetched, self.landed = kept.get("fetched", []), kept.get("landed", url)
            return cached.read_text(encoding="utf-8")
        if self.pages_loaded.get(store, 0) >= self.max_pages:
            raise LimitReached(store, url, f"reached this run's limit of {self.max_pages} pages for one store")
        if self._page is None:
            self._start()
        if self._page.is_closed():
            raise BrowserClosed("The browser window was closed, so the refresh stopped.")
        wait = self._last_load.get(store, 0) + random.uniform(*self.pause) - time.time()
        if wait > 0:
            time.sleep(wait)

        answers: list = []

        def heard(request) -> None:         # the page's own requests for data, once their answer has fully arrived
            try:
                response = request.response() if request.resource_type in ("fetch", "xhr") else None
                if response is not None and "json" in (response.headers.get("content-type") or ""):
                    answers.append(response)
            except Exception:  # noqa: BLE001 — a response we cannot look at is simply not kept
                pass

        if listing:
            # "requestfinished": only answers that have arrived in full are kept, so reading one never waits for an
            # answer that is still streaming.
            self._page.on("requestfinished", heard)
        try:
            response = self._page.goto(url, wait_until="domcontentloaded", timeout=self.timeout_ms)
            status = response.status if response else None
            first = ""
            if listing:
                # The page as it is first shown, and again once it has finished loading and been scrolled: some
                # pages swap their first list for another as they finish (Foot Locker's links to its products go).
                self._page.wait_for_timeout(2000)
                try:
                    first = self._page.content()
                except Exception:  # noqa: BLE001 — still moving: the page as it ends is read below
                    first = ""
                self._settle()
            title = html = ""
            for attempt in range(4):
                self._page.wait_for_timeout(2000)   # let the page settle, as it would for a visitor
                try:
                    title, html = self._page.title(), self._page.content()
                    break
                except Exception as still_moving:  # noqa: BLE001
                    # Some pages redirect themselves once more after loading; read again
                    # when they have stopped. (This re-reads the open page; it requests nothing.)
                    if attempt == 3 or "navigat" not in str(still_moving).lower():
                        raise
            if listing:
                self.landed = self._page.url
                self.fetched = self._bodies(answers)
                if first and first != html:
                    html += "\n<!-- the page as it was first shown -->\n" + first
        except Exception as e:  # noqa: BLE001 — timeouts, closed window, no network
            self._last_load[store] = time.time()
            if self._page.is_closed():
                raise BrowserClosed("The browser window was closed, so the refresh stopped.") from None
            detail = (str(e).splitlines() or [type(e).__name__])[0][:140]
            raise Blocked(store, url, f"the page did not load: {detail}") from None
        finally:
            if listing:
                try:
                    self._page.remove_listener("requestfinished", heard)
                except Exception:  # noqa: BLE001
                    pass
        self._last_load[store] = time.time()
        self.pages_loaded[store] = self.pages_loaded.get(store, 0) + 1

        reason = block_reason(status, title, html, check_body)
        if reason:
            raise Blocked(store, url, reason)
        if status == 404:
            raise PageMissing(url)
        if cached:
            cached.write_text(html, encoding="utf-8")
            if listing:
                cached.with_suffix(".json").write_text(
                    json.dumps({"fetched": self.fetched, "landed": self.landed}, ensure_ascii=False), encoding="utf-8")
        return html

    def _settle(self) -> None:
        """Wait as a visitor's browser would: until the page has stopped loading (at most `settle_seconds`), then
        scroll down a screen at a time while the page grows, at most `scroll_screens` screens. A page that never
        stops loading (some keep a connection open) is simply read as it is then."""
        try:
            self._page.wait_for_load_state("networkidle", timeout=self.settle_ms)
        except Exception:  # noqa: BLE001 — still loading after the wait: read what is there
            pass
        try:
            height = self._page.evaluate("document.body ? document.body.scrollHeight : 0")
            for _ in range(self.scroll_screens):
                self._page.mouse.wheel(0, 900)
                self._page.wait_for_timeout(1500)
                grown = self._page.evaluate("document.body ? document.body.scrollHeight : 0")
                if grown <= height:
                    break
                height = grown
        except Exception:  # noqa: BLE001 — a page that cannot be scrolled is read as it is
            pass

    @staticmethod
    def _bodies(answers: list) -> list:
        """The JSON of the page's own requests, read from what the browser already received (nothing is asked
        again), within JSON_EACH and JSON_ALL."""
        out, total = [], 0
        for response in answers:
            body = b""
            try:
                body = response.body()
            except Exception:  # noqa: BLE001 — an answer the browser no longer holds is skipped (body stays empty)
                body = b""
            if not body or len(body) > JSON_EACH or total + len(body) > JSON_ALL:
                continue
            try:
                out.append(json.loads(body))
            except ValueError:
                continue
            total += len(body)
        return out

    def robots(self, store: str, base: str) -> Robots:
        if store not in self._robots:
            try:
                page = self._load(store, base.rstrip("/") + "/robots.txt", check_body=False)
            except PageMissing:
                page = ""                            # no robots.txt: nothing is disallowed
            text = html_lib.unescape(re.sub(r"<[^>]+>", "", page))   # Chrome wraps text files in <pre>
            self._robots[store] = Robots(text)
        return self._robots[store]

    def fetch(self, store: str, base: str, url: str) -> str:
        """The HTML of `url`, read at most once per run."""
        if url in self._seen:
            return self._seen[url]
        if not self.robots(store, base).allowed(url):
            raise NotAllowed(url)
        html = self._load(store, url)
        self._seen[url] = html
        return html

    def fetch_listing(self, store: str, base: str, url: str) -> tuple[str, list, str]:
        """A category page as a visitor's browser shows it (see the top of this file): (its HTML, the JSON the page
        fetched while it loaded, the address it ended on). Read at most once per run."""
        if url in self._listings:
            return self._listings[url]
        if not self.robots(store, base).allowed(url):
            raise NotAllowed(url)
        html = self._load(store, url, listing=True)
        self._listings[url] = (html, self.fetched, self.landed)
        return self._listings[url]
