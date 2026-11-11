"""One ordinary browser window, used politely.

`Session.fetch(store, url)` is the only way the collector touches a store:

  * it uses a normal, visible Chrome window with its own profile folder —
    nothing about the browser is disguised or altered;
  * it reads the store's robots.txt first and refuses addresses that file
    disallows;
  * it waits a random few seconds between two pages of the same store;
  * if the store answers "Access Denied", shows a captcha or rate-limits, it
    raises `Blocked` — the caller then stops that store. Nothing is retried.
"""
from __future__ import annotations

import hashlib
import html as html_lib
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

    def _load(self, store: str, url: str, check_body: bool = True) -> str:
        """Open one address in the browser, after the polite pause. Returns the HTML."""
        cached = self._cache_file(url)
        if cached and cached.exists():
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

        try:
            response = self._page.goto(url, wait_until="domcontentloaded", timeout=self.timeout_ms)
            status = response.status if response else None
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
        except Exception as e:  # noqa: BLE001 — timeouts, closed window, no network
            self._last_load[store] = time.time()
            if self._page.is_closed():
                raise BrowserClosed("The browser window was closed, so the refresh stopped.") from None
            detail = (str(e).splitlines() or [type(e).__name__])[0][:140]
            raise Blocked(store, url, f"the page did not load: {detail}") from None
        self._last_load[store] = time.time()
        self.pages_loaded[store] = self.pages_loaded.get(store, 0) + 1

        reason = block_reason(status, title, html, check_body)
        if reason:
            raise Blocked(store, url, reason)
        if status == 404:
            raise PageMissing(url)
        if cached:
            cached.write_text(html, encoding="utf-8")
        return html

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
