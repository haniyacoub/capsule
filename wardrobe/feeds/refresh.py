"""Fetching the approved stores' feeds and importing them: `python -m wardrobe feeds`.

    python -m wardrobe feeds                              every approved store, when its feed changed
    python -m wardrobe feeds --store KEY                  one store
    python -m wardrobe feeds --force                      download even when the feed says it has not changed, and
                                                          import a file that would remove most of a store (step 3)
    python -m wardrobe feeds --store KEY --from FILE      import a file you have: nothing is downloaded
                                                          (an approved store's, or an invented sample's)

This runs from the command line (later from a timer on the server), never inside a web worker,
and only one run goes at a time: a second one stops at once and says so. For each store:

 1. Ask when its feed last changed, where the network offers a way (rules.check_url in
    config/feeds.toml), or look at the file's time for a feed on this computer.
 2. Download it only when that says it changed (or with --force). Where there is nothing to ask,
    it is downloaded, and imported unless its Last-Modified time shows it is the version already
    imported. Either way the networks' limits are kept, from one run to the next too: Awin's API
    is asked at most 5 times a minute, and Tradedoubler, which allows 3 downloads of one file
    version a day, gets at most one download every 8 hours, unless its rules.check_url says the
    feed changed after the last download.
 3. Read it with the store's importer and replace all of that store's products in one
    transaction: products missing from the new file are gone, and a failure part-way keeps the
    old ones exactly as they were. So does a download that stops short of the size its server
    announced, and a file in which no product can be read. So does a file that would remove more
    than half of a store's products, once it has 10 or more, unless --force is given: more likely
    a cut download (one whose server gave no size to check it against) or a broken export at the
    store than a store that sells half as much overnight.
 4. Record the import, or the error, on the store. One store's failure never stops the others.

The feed's date (stale or not, and later the "as of" next to prices): the network's own word
where it gives one (rules.check_url, or the download's Last-Modified), the file's own time for a
feed file on this computer, and otherwise the newest time its products carry, since a file copied
today may hold an old feed (for a file given with --from, the file's time when they carry none).
A time a product carries is never taken as later than the import: a product dated 2099 never
makes a feed look fresh.

A feed address may name secrets, such as {AWIN_API_TOKEN}: they are read from environment variables
of that name when the feed is fetched, and the filled-in address is never printed or stored.
"""
from __future__ import annotations

import contextlib
import csv
import fcntl
import http.client
import io
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib
from collections.abc import Callable, Iterator
from datetime import datetime, timedelta
from pathlib import Path

from .. import db, paths, settings
from . import FORMATS, registry, rows

TIMEOUT = 60                   # seconds without an answer before a download gives up
DEFAULT_MAX_MB = 300           # a bigger feed is refused; rules.max_mb in config/feeds.toml allows more
MOST_GONE = 0.5                # an import that would remove more than this share of a store's products ...
FEW_PRODUCTS = 10              # ... of a store with at least this many is refused, unless --force (_refuse_most_gone)
AGENT = "Capsule feed import"

# The networks' own limits.
# Awin's product API: "no more than 5 requests per minute", so one request every 12 seconds:
#     https://help.awin.com/apidocs/retail-publisher-productapidocumentation-1.md   (8 Sep 2026)
SECONDS_BETWEEN_REQUESTS = {"awin": 12.0}
# Tradedoubler's Products API: each version of a whole-feed file may be downloaded 3 times in 24 hours:
#     https://dev.tradedoubler.com/products/publisher
DOWNLOADS_PER_VERSION_PER_DAY = {"tradedoubler": 3}


class FeedError(Exception):
    """A store's feed could not be fetched or read. The message says why, never with a secret in it."""


def run(store_key: str | None = None, force: bool = False, from_file: str | None = None,
        say: Callable[[str], object] = print) -> int:
    """Refresh the chosen stores, saying how each went. Returns how many failed."""
    with _one_run_at_a_time():
        stores = chosen(store_key, from_file)
        if not stores:
            say("No approved stores. Their status is set in config/feeds.toml, then: python -m wardrobe stores sync")
        failed = 0
        for store in stores:
            try:
                said = refresh_store(store, force=force, from_file=Path(from_file) if from_file else None)
            except Exception as problem:      # one store's failure never stops the others
                failed += 1
                # Only a FeedError's own words are passed on: another error's text might quote an address with a secret.
                reason = str(problem) if isinstance(problem, FeedError) else f"an unexpected {type(problem).__name__}"
                db.note_store(store["key"], error=f"{db.now_iso()}: {reason}")
                kept = (db.get_store(store["key"]) or store)["products"]
                said = (f"failed, and its products are kept as they were: {reason}" if kept
                        else f"failed, and nothing was imported: {reason}")
            say(f"{store['key']}: {said}")
            current = db.get_store(store["key"]) or store
            if registry.stale(current):
                say(f"{store['key']}: STALE: {registry.stale_words(current)}")
        return failed


@contextlib.contextmanager
def _one_run_at_a_time() -> Iterator[None]:
    """Only one run at a time: the timer's and one started by hand would not keep to the networks'
    limits together, and would download the same feeds twice. A second run stops at once and says
    so. The lock belongs to the running process, so a run that was killed leaves none behind."""
    folder = paths.DATA_DIR / "feeds"
    folder.mkdir(parents=True, exist_ok=True)
    with (folder / "run.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise FeedError("another `python -m wardrobe feeds` is running: try again once it has finished") from None
        yield


def chosen(store_key: str | None, from_file: str | None) -> list[dict]:
    """The stores to refresh: the one asked for, or every approved one. FeedError for a refusal."""
    if from_file and not store_key:
        raise FeedError("--from needs --store: which store's file is it?")
    if not store_key:
        return [s for s in db.list_stores()
                if s["status"] == "approved" and not _left_out(s) and not s["rules"].get("links_only")]
    store = db.get_store(store_key)
    if store is None:
        raise FeedError(f"There is no store called {store_key!r}. The stores: python -m wardrobe stores")
    if _left_out(store):
        raise FeedError(f"{store_key} is an invented sample store, left out in production")
    # A programme that forbids keeping its site's data (MR PORTER's): its products are shown as live links only.
    if store["rules"].get("links_only"):
        raise FeedError(f"{store_key} is {registry.LINKS_ONLY}")
    if store["status"] == "ended":
        raise FeedError(f"{store_key} has ended: its products were deleted and stay deleted. If its programme "
                        f"takes Capsule back: python -m wardrobe stores sync --reopen {store_key}")
    # Products come only from a programme that has approved Capsule: its feed is licensed, a file
    # of it before then is not. An invented sample store's file may be tried whatever its status.
    if store["status"] != "approved" and not (from_file and store["rules"].get("sample")):
        raise FeedError(f"{store_key} is {store['status']!r}, not approved: Capsule takes a store's products "
                        "only once its programme has approved it"
                        + (", so no file of it is imported either" if from_file else ""))
    return [store]


def _left_out(store: dict) -> bool:
    return bool(store["rules"].get("sample")) and settings.PRODUCTION


def refresh_store(store: dict, force: bool = False, from_file: Path | None = None) -> str:
    """Fetch one store's feed if it changed and import it. Returns what happened, in a few words."""
    if store.get("feed_format") not in FORMATS:
        raise FeedError(f"its feed_format in config/feeds.toml is not one of {', '.join(FORMATS)}")
    if from_file is not None:
        if not from_file.is_file():
            raise FeedError(f"there is no file {from_file}")
        # A file you have may hold an old feed copied today: it is dated by its products (_feed_time).
        return _import(store, from_file, None, file_time=_file_time(from_file), force=force)
    where = store.get("feed_location")
    if not where:
        raise FeedError("it has no feed_location in config/feeds.toml")
    if not re.match(r"[a-z]+://", where, re.IGNORECASE):          # a file on this computer
        path = Path(where) if Path(where).is_absolute() else paths.ROOT / where
        if not path.is_file():
            raise FeedError(f"there is no file {where}")
        version = _file_time(path)
        if not force and _same(version, store["last_feed_update"]):
            return _unchanged(store, version)
        return _import(store, path, version, force=force)

    asked = _remote_version(store)
    if asked and not force and _same(asked, store["last_feed_update"]):
        return _unchanged(store, asked)
    wait = _too_soon(store, asked)
    if wait:
        return wait
    target = paths.DATA_DIR / "feeds" / f"{store['key']}.download"
    try:
        modified = _download(store, expand(where, store), target, float(store["rules"].get("max_mb", DEFAULT_MAX_MB)),
                             feed=True)
        if not asked and modified and not force and _same(modified, store["last_feed_update"]):
            return _unchanged(store, modified)            # nowhere to ask first: the download's own time says
        return _import(store, target, asked or modified, force=force)
    finally:
        target.unlink(missing_ok=True)       # the feed is kept as products, not as a copy of the file


def _unchanged(store: dict, version: str) -> str:
    db.note_store(store["key"], error=None)
    return f"unchanged since {version[:16].replace('T', ' ')}, not imported again"


def _import(store: dict, path: Path, version: str | None, file_time: str | None = None, force: bool = False) -> str:
    """Read the file with the store's importer and swap the store's products for what it holds.
    `version` is the feed's date where the network or the file's place gives one; `file_time` the
    time of a file given by hand (see _feed_time). force: even if it would remove most of the store."""
    try:
        result = FORMATS[store["feed_format"]](path)
    except (OSError, ValueError, EOFError, csv.Error, zlib.error) as problem:
        raise FeedError(f"the file could not be read as {store['feed_format']} ({type(problem).__name__})") from None
    if not result.rows:
        skipped = f" ({result.summary()})" if result.skipped else ""
        raise FeedError(f"no product in the file could be read{skipped}")
    imported_at = db.now_iso()
    feed_time = _feed_time(version, result.rows, file_time, imported_at)
    for row in result.rows:
        row["imported_at"] = imported_at
        row["feed_updated_at"] = _not_after(row["feed_updated_at"], imported_at) or feed_time
    check = None if force else _refuse_most_gone(store["key"], from_file=file_time is not None)
    count, gone = db.replace_products(store["key"], result.rows, check)
    db.note_store(store["key"], error=None, feed_update=feed_time, imported_at=imported_at)
    said = [f"{count} products imported"]
    if gone:
        said.append(f"{gone} from the last import {'is' if gone == 1 else 'are'} gone")
    if result.skipped:
        said.append(result.summary())
    return ", ".join(said)


def _refuse_most_gone(key: str, from_file: bool) -> Callable[[int, int], None]:
    """The check db.replace_products makes before it swaps a store's products: it refuses a file that
    would remove more than half of them (MOST_GONE), once the store has FEW_PRODUCTS or more. A cut
    download whose server gave no size, or a broken export at the store, looks just like that, and
    taking it would empty most of the store's catalogue at once. The old products stay, and the
    store's last error says why and how to go on."""
    def check(now: int, gone: int) -> None:
        if now >= FEW_PRODUCTS and gone > now * MOST_GONE:
            again = f"python -m wardrobe feeds --store {key}" + (" --from FILE" if from_file else "") + " --force"
            raise FeedError(f"the new file would remove {gone} of its {now} products, more than half. "
                            f"If the store really has that few now, import it with: {again}")
    return check


def _feed_time(version: str | None, found: list[dict], file_time: str | None, imported_at: str) -> str:
    """The feed's date, in this order:

        version    the network's own word (rules.check_url, the download's Last-Modified), or the
                   time of the feed file on this computer: taken as it is
        products   the newest time any product carries (Awin's last_updated, Tradedoubler's
                   modified): the feed is at least that new. Never newer than the import, though
                   (a product dated 2099 would keep the feed looking fresh for ever), nor, for a
                   file given by hand, than the file itself
        file_time  a file given by hand whose products carry no time (Google's format has none)
        imported_at  a download with none of these: the time it was imported
    """
    if version:
        return version
    times = [row["feed_updated_at"] for row in found if row["feed_updated_at"]]
    if times:
        newest = max(times, key=datetime.fromisoformat)
        return min(newest, file_time or imported_at, imported_at, key=datetime.fromisoformat)
    return file_time or imported_at


def _not_after(when: str | None, latest: str) -> str | None:
    """`when`, or `latest` if `when` is later: no product's time is later than its import."""
    if when and datetime.fromisoformat(when) > datetime.fromisoformat(latest):
        return latest
    return when


def _file_time(path: Path) -> str:
    return rows.parse_time(path.stat().st_mtime) or db.now_iso()


def _same(a: str | None, b: str | None) -> bool:
    return bool(a and b) and datetime.fromisoformat(a or "") == datetime.fromisoformat(b or "")


def _too_soon(store: dict, version: str | None) -> str:
    """Tradedoubler allows 3 downloads of one file version a day, and counts every download, imported
    or not. So downloads are kept a third of a day apart (8 hours), unless the feed says it changed
    after the last download (`version`, from rules.check_url): that version is new here, and may be
    fetched now. '' when nothing stands in the way."""
    per_day = DOWNLOADS_PER_VERSION_PER_DAY.get(store.get("network") or "")
    last = store.get("last_download_at")
    if not per_day or not last:
        return ""
    if version and datetime.fromisoformat(version) > datetime.fromisoformat(last):
        return ""
    now = datetime.now().astimezone()
    wait = timedelta(hours=24 / per_day) - (now - datetime.fromisoformat(last))
    if wait <= timedelta(0):
        return ""
    return (f"not downloaded: the network allows {per_day} downloads of one feed version a day, and the last "
            f"download was at {last[11:16]}. Next after {(now + wait).strftime('%H:%M')}")


# ── the address, and the download ─────────────────────────────────────────────

_NAME = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")


def expand(template: str, store: dict, quote: bool = True) -> str:
    """The address with {programme_id} and {ENVIRONMENT_VARIABLES} filled in. It may hold a secret:
    it is used for the request and nowhere else."""
    def fill(match: re.Match) -> str:
        name = match.group(1)
        value = store.get("programme_id") if name == "programme_id" else os.environ.get(name, "").strip()
        if not value:
            raise FeedError(f"{{{name}}} in its feed address has no value"
                            + ("" if name == "programme_id" else f": set the environment variable {name}"))
        return urllib.parse.quote(value, safe="") if quote else value
    return _NAME.sub(fill, template)


def _stand_in(url: str) -> bool:
    """A file, or a stand-in server on this computer: what the tests fetch instead of a network.
    Never in production: there a feed, and wherever it sends the downloader, is https only."""
    if settings.PRODUCTION:
        return False
    parts = urllib.parse.urlsplit(url)
    return parts.scheme == "file" or (parts.scheme == "http" and parts.hostname in ("127.0.0.1", "localhost", "::1"))


class _OnlyHttps(urllib.request.HTTPRedirectHandler):
    """A feed may move to another address (a download server), but only to an https one."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not (newurl.lower().startswith("https://") or _stand_in(newurl)):
            return None
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _opener() -> urllib.request.OpenerDirector:
    # Proxies come from the environment (HTTPS_PROXY) only. The default would also ask macOS for its
    # system proxy settings, which kills a process forked from a web server (see imagegen.py). This
    # runs from the command line, but it keeps to the same rule.
    return urllib.request.build_opener(urllib.request.ProxyHandler(urllib.request.getproxies_environment()),
                                       _OnlyHttps)


def _pace(network: str | None) -> None:
    """Wait as long as the network asks between two requests (Awin: 12 seconds). When each network
    was last asked is kept in a file, feeds/asked.json in the data folder, so the wait holds from
    one run to the next too (and runs never overlap: _one_run_at_a_time)."""
    gap = SECONDS_BETWEEN_REQUESTS.get(network or "")
    if not gap or not network:
        return
    kept = paths.DATA_DIR / "feeds" / "asked.json"
    try:
        asked = json.loads(kept.read_text(encoding="utf-8"))      # {"awin": seconds since 1970}
    except (OSError, ValueError):
        asked = {}
    if not isinstance(asked, dict):
        asked = {}
    last = asked.get(network)
    if isinstance(last, (int, float)):
        wait = min(last + gap - time.time(), gap)     # never longer than the gap, even if the clock was put back
        if wait > 0:
            time.sleep(wait)
    asked[network] = time.time()
    kept.parent.mkdir(parents=True, exist_ok=True)
    kept.write_text(json.dumps(asked), encoding="utf-8")


def _download(store: dict, url: str, target: Path, limit_mb: float, feed: bool = False) -> str | None:
    """Fetch one address into `target`, at most `limit_mb` megabytes. Returns the answer's Last-Modified
    time, if it gave one. Only https is fetched (and, for the tests, a file or a stand-in here).
    feed=True for the feed itself (not the question when it changed): once it begins to arrive, the
    download is recorded on the store, finished or not, as the networks count it."""
    if not (url.lower().startswith("https://") or _stand_in(url)):
        raise FeedError("only https:// feed addresses are fetched")
    _pace(store.get("network"))
    request = urllib.request.Request(url, headers={"User-Agent": AGENT})
    for name, template in (store["rules"].get("headers") or {}).items():
        # A header named in rules.headers (a token) is never passed on to another address.
        request.add_unredirected_header(str(name), expand(str(template), store, quote=False))
    target.parent.mkdir(parents=True, exist_ok=True)
    done = False
    try:
        with _opener().open(request, timeout=TIMEOUT) as answer, target.open("wb") as out:
            if feed:
                db.note_download(store["key"], db.now_iso())
            size, limit = 0, limit_mb * 1024 * 1024
            while chunk := answer.read(1024 * 1024):
                size += len(chunk)
                if size > limit:
                    raise FeedError(f"the feed is larger than {limit_mb:g} MB; rules.max_mb can allow more")
                out.write(chunk)
            # When the connection closes before the size the server announced (Content-Length), the
            # reading above just ends, with no error: a cut file would be imported as the whole feed.
            # So what arrived is counted. (A feed sent in chunks raises IncompleteRead instead, below,
            # and a cut gzipped feed fails to unpack.)
            announced = (answer.headers.get("Content-Length") or "").strip()
            if announced.isdecimal() and size < int(announced):
                raise FeedError(f"the download broke off ({size} of {announced} bytes arrived)")
            modified = answer.headers.get("Last-Modified")
        done = True
    except urllib.error.HTTPError as refusal:      # an answer, with an error status
        refusal.close()
        raise FeedError(f"its feed address answered {refusal.code}") from None
    except urllib.error.URLError as problem:       # nothing came back
        raise FeedError(f"its feed address could not be reached ({type(problem.reason).__name__})") from None
    except ValueError:                              # a header that cannot be sent: a line break in a secret
        raise FeedError("a header in its rules.headers cannot be sent") from None
    except (OSError, http.client.HTTPException) as problem:
        raise FeedError(f"the download broke off ({type(problem).__name__})") from None
    finally:
        if not done:
            target.unlink(missing_ok=True)
    return rows.parse_time(modified)


def _remote_version(store: dict) -> str | None:
    """When the feed last changed, asked before downloading it, at the address in rules.check_url
    (Tradedoubler's productsUnlimited/lastUpdated, or Awin's list of feeds). None: nowhere to ask."""
    check = store["rules"].get("check_url")
    if not check:
        return None
    target = paths.DATA_DIR / "feeds" / f"{store['key']}.check"
    try:
        _download(store, expand(str(check), store), target, 5)
        answer = target.read_text(encoding="utf-8-sig", errors="replace")
    finally:
        target.unlink(missing_ok=True)
    version = version_in(answer, store.get("programme_id"))
    if version is None:
        raise FeedError("the answer at its rules.check_url holds no time")
    return version


def version_in(answer: str, programme_id: str | None) -> str | None:
    """The time in an answer to rules.check_url:

        JSON   a time on its own, or an object holding lastUpdated (Tradedoubler), last_updated or modified
        CSV    Awin's list of feeds: the "Last Imported" column on the line whose "Advertiser ID" is the
               store's programme id. Unsure: those two column names were not in a page that was read;
               check them against the first real list, here
        text   a time on its own
    """
    try:
        data = json.loads(answer)
    except ValueError:
        data = None
    if isinstance(data, dict):
        found = next((data[name] for name in ("lastUpdated", "last_updated", "modified") if name in data), None)
        return rows.parse_time(found)
    if data is not None:
        return rows.parse_time(data)
    lines = answer.strip().splitlines()
    if len(lines) > 1 and programme_id:
        for line in csv.DictReader(io.StringIO(answer.strip())):
            if (line.get("Advertiser ID") or "").strip() == programme_id:
                return rows.parse_time(line.get("Last Imported"))
        return None
    return rows.parse_time(answer.strip())
