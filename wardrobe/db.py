"""Accounts and everyone's decisions, in SQLite (data/wardrobe.db).

Every row of a customer's data carries their `user_id`, and every function
below that touches such rows reads the id from one place: `uid()`, the user of
the current request. There is no way to ask for another user's rows.

    local mode        one implicit user (id 1); no login
    production mode   uid() raises unless a logged-in user was set for the request

Look around with `sqlite3 data/wardrobe.db`:

    SELECT id, email, created_at FROM users;
    SELECT name, category, colour, qty, owned, locked, pick FROM slots WHERE user_id = 1 ORDER BY position;
    SELECT key, value FROM settings WHERE user_id = 1;
    SELECT key, status, last_import_at FROM stores;          -- the store feeds (feeds/)
    SELECT store, name, price, colour, sizes_in_stock FROM products LIMIT 20;
    SELECT u.email, o.added_at FROM owners o JOIN users u ON u.id = o.user_id;   -- who runs Stilsmith (owner.py)
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from collections.abc import Callable
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime

from . import paths, settings

SCHEMA_VERSION = 6
LOCAL_USER_ID = 1

SCHEMA = """
CREATE TABLE users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    email         TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash TEXT NOT NULL,
    created_at    TEXT NOT NULL,
    session_epoch INTEGER NOT NULL DEFAULT 0     -- raised to sign out every device
);
CREATE TABLE settings (
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    key     TEXT NOT NULL,
    value   TEXT NOT NULL,              -- JSON: profile, mode, threshold, …
    PRIMARY KEY (user_id, key)
);
CREATE TABLE slots (
    user_id   INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    id        TEXT NOT NULL,            -- stable slug, e.g. 'white-tee'
    position  INTEGER NOT NULL,
    name      TEXT NOT NULL,
    category  TEXT NOT NULL,            -- a key from garments.py
    colour    TEXT NOT NULL,            -- a key from colours.py
    keywords  TEXT NOT NULL DEFAULT '',
    qty       INTEGER NOT NULL DEFAULT 1,
    owned     INTEGER NOT NULL DEFAULT 0,   -- 1 = already own, costs nothing
    locked    INTEGER NOT NULL DEFAULT 0,   -- 1 = the price level must not change it
    pick      TEXT,                     -- candidate id, set while locked
    PRIMARY KEY (user_id, id)
);
CREATE TABLE saved_outfits (
    user_id   INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    key       TEXT NOT NULL,            -- fingerprint of the pieces
    saved_at  TEXT NOT NULL,
    label     TEXT NOT NULL,
    pieces    TEXT NOT NULL,            -- JSON snapshot, so a favourite survives a refresh
    PRIMARY KEY (user_id, key)
);
CREATE TABLE catalogs (                 -- production: each customer's candidates (JSON)
    user_id    INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    updated_at TEXT NOT NULL,
    data       TEXT NOT NULL
);
CREATE TABLE login_attempts (           -- failed logins, to slow down guessing
    email TEXT NOT NULL,
    ip    TEXT NOT NULL,
    at    REAL NOT NULL
);
CREATE INDEX login_attempts_at ON login_attempts (at);
CREATE TABLE signups (ip TEXT NOT NULL, at REAL NOT NULL);
CREATE TABLE reset_tokens (             -- only a hash of each emailed token is kept
    token_hash TEXT PRIMARY KEY,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    expires_at REAL NOT NULL
);
"""

# Added in version 3: the AI pictures of outfits (looks.py). Version 4 changed look_requests:
# an entry now outlives its account (with no name on it), so that deleting an account and
# signing up again cannot be used to get round the day's total.
# (No semicolons inside the comments: the statements are split on them.)
SCHEMA_PICTURES = """
CREATE TABLE IF NOT EXISTS looks (      -- one row per picture, the files are in <data>/looks/
    key        TEXT PRIMARY KEY,        -- fingerprint of what was sent to the image service
    user_id    INTEGER REFERENCES users(id) ON DELETE CASCADE,   -- only for a picture of someone's own photo
    status     TEXT NOT NULL,           -- waiting (its turn) | working | ready | failed
    started_at REAL NOT NULL,
    file       TEXT,                    -- the picture, once there is one
    error      TEXT,                    -- why the last attempt failed
    service    TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS look_requests (   -- when a picture was asked for: the daily limits
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    at      REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS look_requests_at ON look_requests (at);
"""

# Added in version 5: the store feeds (feeds/). These tables are shared, not per customer: the
# stores whose affiliate programmes may license Stilsmith a product feed, and the products from
# those feeds. A database from version 4 gains them and nothing else changes.
# (No semicolons inside the comments: the statements are split on them.)
SCHEMA_FEEDS = """
CREATE TABLE IF NOT EXISTS stores (     -- copied from config/feeds.toml by `python -m wardrobe stores sync`
    key              TEXT PRIMARY KEY,  -- short name for the command line, e.g. 'musterhaus'
    label            TEXT NOT NULL,     -- the store's name as people read it
    network          TEXT,              -- awin | rakuten | tradedoubler | partnerize | daisycon | webgains | impact
    programme_id     TEXT,              -- the store's id in its network, e.g. an Awin advertiser id
    status           TEXT NOT NULL DEFAULT 'none',   -- none | applied | approved | refused | ended
    feed_format      TEXT,              -- google | awin_csv | tradedoubler_json
    feed_location    TEXT,              -- address or file, {NAMES} in it are read from environment variables
    delivery_note    TEXT,              -- shown next to prices later, e.g. 'Versand 4,95 EUR'
    disclaimer       TEXT,              -- text the programme requires next to its name
    rules            TEXT NOT NULL DEFAULT '{}',     -- JSON: refresh hours, delete on exit, images, answers,
                                        -- links only, and for the owner its programme page and notes
    last_feed_update TEXT,              -- when the feed itself last changed
    last_import_at   TEXT,              -- when its products were last imported here
    last_download_at TEXT,              -- when its feed last began to download (Tradedoubler counts downloads)
    last_error       TEXT               -- why the last refresh failed, NULL after one that worked
);
CREATE TABLE IF NOT EXISTS products (   -- one row per product per store, replaced at each import of its feed
    store           TEXT NOT NULL REFERENCES stores(key),
    product_id      TEXT NOT NULL,      -- the feed's id for it (one size or colour of a garment)
    group_id        TEXT,               -- the same garment in other sizes or colours shares this
    name            TEXT NOT NULL,
    brand           TEXT,
    category        TEXT,               -- the feed's own words
    gender          TEXT,               -- the feed's own words
    colour          TEXT,               -- the feed's own words
    colour_key      TEXT,               -- Stilsmith's colour (colours.py), NULL when not recognised
    material        TEXT,               -- the feed's own words
    composition     TEXT NOT NULL DEFAULT '[]',      -- JSON [[fibre, percent], ...] from composition.py
    price           REAL NOT NULL,      -- Google format: the regular price. Awin CSV: search_price, the price now
    sale_price      REAL,               -- a reduced price below `price`, when the feed gives one. The price
                                        -- to show is COALESCE(sale_price, price), and no "was" price
                                        -- until a lawyer has said how one must be shown
    currency        TEXT NOT NULL,
    sizes           TEXT NOT NULL DEFAULT '[]',      -- JSON, every size the feed names (empty: it does not say)
    sizes_in_stock  TEXT NOT NULL DEFAULT '[]',      -- JSON, the sizes it says are in stock (empty: it does not say)
    available       INTEGER,            -- 1 can be bought now, 0 cannot, NULL the feed does not say
    image_url       TEXT,               -- the feed's photo address, exactly as given
    buy_link        TEXT NOT NULL,      -- the tracked link, exactly as given
    feed_updated_at TEXT,               -- the feed's time for this product (or for the whole feed)
    imported_at     TEXT NOT NULL,
    PRIMARY KEY (store, product_id)
);
CREATE INDEX IF NOT EXISTS products_by_group ON products (store, group_id);
"""

# Added in version 6: who runs Stilsmith (owner.py). An owner's account sees the owner's pages, such as
# every store's catalogue at /stores. Marked with `python -m wardrobe owner add EMAIL`, straight in
# the database: no setting and no restart. Deleting the account deletes the mark with it.
# (No semicolons inside the comments: the statements are split on them.)
SCHEMA_OWNERS = """
CREATE TABLE IF NOT EXISTS owners (     -- `python -m wardrobe owner add | remove | list`
    user_id  INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    added_at TEXT NOT NULL
);
"""


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


@contextmanager
def connect():
    paths.DATA_DIR.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(paths.DB_PATH, timeout=10)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    try:
        yield con
        con.commit()
    finally:
        con.close()


@contextmanager
def exclusive():
    """Like connect(), but holding the write lock from the start: what is read inside cannot
    have changed by the time it is written. Other writers wait their turn (up to ten seconds)."""
    paths.DATA_DIR.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(paths.DB_PATH, timeout=10, isolation_level=None)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    try:
        con.execute("BEGIN IMMEDIATE")
        yield con
        con.execute("COMMIT")
    except BaseException:
        if con.in_transaction:
            con.execute("ROLLBACK")
        raise
    finally:
        con.close()


def init() -> None:
    """Create the tables, or bring an older database up to date. Safe to call often."""
    with connect() as con:
        version = con.execute("PRAGMA user_version").fetchone()[0]
    if version < SCHEMA_VERSION:
        _migrate()
    if not settings.PRODUCTION:
        ensure_local_user()


def _migrate() -> None:
    """Bring the database up to date. Several server processes may start at the same moment:
    whichever gets the write lock first does the work, and the others then find it done."""
    for attempt in range(100):                         # switching to WAL needs the file to itself for a moment
        try:
            with connect() as con:
                con.execute("PRAGMA journal_mode = WAL")   # readers don't block the writer
                _copy_before_accounts(con)
            break
        except sqlite3.OperationalError:
            if attempt == 99:
                raise
            time.sleep(0.05)
    with exclusive() as con:
        version = con.execute("PRAGMA user_version").fetchone()[0]    # read again, now that nobody else can write
        if version >= SCHEMA_VERSION:
            return
        if version < 2:                                # a new database, or the single-user layout of version 1
            _add_accounts(con)
        if version == 3:                               # look_requests in its first shape: set it aside
            con.execute("ALTER TABLE look_requests RENAME TO look_requests_v3")
            con.execute("DROP INDEX IF EXISTS look_requests_at")
        for statement in SCHEMA_PICTURES.split(";"):   # safe to repeat
            if statement.strip():
                con.execute(statement)
        if version == 3:
            con.execute("INSERT INTO look_requests (user_id, at) SELECT user_id, at FROM look_requests_v3")
            con.execute("DROP TABLE look_requests_v3")
        for statement in SCHEMA_FEEDS.split(";"):      # new in version 5, safe to repeat
            if statement.strip():
                con.execute(statement)
        for statement in SCHEMA_OWNERS.split(";"):     # new in version 6, safe to repeat
            if statement.strip():
                con.execute(statement)
        con.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")


def _copy_before_accounts(con: sqlite3.Connection) -> None:
    """Keep an untouched copy of a database from before accounts existed (the single-user layout)."""
    tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    if "users" not in tables and any(t in tables for t in ("settings", "slots", "saved_outfits")):
        backup = paths.DB_PATH.with_name(paths.DB_PATH.name + ".before-accounts")
        if not backup.exists():
            con.execute("VACUUM INTO ?", (str(backup),))


def _add_accounts(con: sqlite3.Connection) -> None:
    tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    old = [t for t in ("settings", "slots", "saved_outfits") if t in tables]   # the single-user layout
    for table in old:
        con.execute(f"ALTER TABLE {table} RENAME TO {table}_v1")
    for statement in SCHEMA.split(";"):
        if statement.strip():
            con.execute(statement)
    if old:   # everything that existed belonged to the one local user
        con.execute("INSERT INTO users (id, email, password_hash, created_at) VALUES (?, ?, '', ?)",
                    (LOCAL_USER_ID, "local@localhost", now_iso()))
        if "settings" in old:
            con.execute("INSERT INTO settings SELECT ?, key, value FROM settings_v1", (LOCAL_USER_ID,))
        if "slots" in old:
            con.execute("INSERT INTO slots SELECT ?, id, position, name, category, colour, keywords, "
                        "qty, owned, locked, pick FROM slots_v1", (LOCAL_USER_ID,))
        if "saved_outfits" in old:
            con.execute("INSERT INTO saved_outfits SELECT ?, key, saved_at, label, pieces "
                        "FROM saved_outfits_v1", (LOCAL_USER_ID,))
        for table in old:
            con.execute(f"DROP TABLE {table}_v1")


# ── whose data: the user of the current request ───────────────────────────────

_current: ContextVar[int | None] = ContextVar("capsule_user", default=None)


def uid() -> int:
    user_id = _current.get()
    if user_id is not None:
        return user_id
    if settings.PRODUCTION:
        raise RuntimeError("No user is signed in for this request.")   # fail closed
    return LOCAL_USER_ID


def set_user(user_id: int | None):
    return _current.set(user_id)


def reset_user(token) -> None:
    _current.reset(token)


@contextmanager
def as_user(user_id: int):
    """Run a block as one user (used by tests and command-line tools)."""
    token = _current.set(user_id)
    try:
        yield
    finally:
        _current.reset(token)


def ensure_local_user() -> None:
    with connect() as con:
        con.execute("INSERT OR IGNORE INTO users (id, email, password_hash, created_at) VALUES (?, ?, '', ?)",
                    (LOCAL_USER_ID, "local@localhost", now_iso()))


# ── accounts ──────────────────────────────────────────────────────────────────

def create_user(email: str, password_hash: str) -> int | None:
    """The new user's id, or None if the address is already registered."""
    try:
        with connect() as con:
            cur = con.execute("INSERT INTO users (email, password_hash, created_at) VALUES (?, ?, ?)",
                              (email, password_hash, now_iso()))
            return cur.lastrowid
    except sqlite3.IntegrityError:
        return None


def get_user(user_id: int) -> dict | None:
    with connect() as con:
        row = con.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return dict(row) if row else None


def get_user_by_email(email: str) -> dict | None:
    with connect() as con:
        row = con.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    return dict(row) if row else None


def set_password(user_id: int, password_hash: str) -> None:
    """Change the password and sign the account out everywhere."""
    with connect() as con:
        con.execute("UPDATE users SET password_hash = ?, session_epoch = session_epoch + 1 WHERE id = ?",
                    (password_hash, user_id))
        con.execute("DELETE FROM reset_tokens WHERE user_id = ?", (user_id,))


def delete_user(user_id: int) -> None:
    """Remove the account and, through the foreign keys, every row that belongs to it."""
    with connect() as con:
        email = con.execute("SELECT email FROM users WHERE id = ?", (user_id,)).fetchone()
        con.execute("DELETE FROM users WHERE id = ?", (user_id,))
        if email:
            con.execute("DELETE FROM login_attempts WHERE email = ?", (email["email"],))


# ── owners: the accounts that run Stilsmith (owner.py) ────────────────────────

def add_owner(email: str) -> str:
    """Mark the account with this address as an owner. Returns 'added', 'already' or 'no account'."""
    with connect() as con:
        user = con.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
        if user is None:
            return "no account"
        cur = con.execute("INSERT OR IGNORE INTO owners (user_id, added_at) VALUES (?, ?)", (user["id"], now_iso()))
    return "added" if cur.rowcount == 1 else "already"


def remove_owner(email: str) -> bool:
    """The account with this address is no longer an owner. False if it was not one."""
    with connect() as con:
        cur = con.execute("DELETE FROM owners WHERE user_id = (SELECT id FROM users WHERE email = ?)", (email,))
    return cur.rowcount == 1


def list_owners() -> list[dict]:
    with connect() as con:
        rows = con.execute("SELECT u.email, o.added_at FROM owners o JOIN users u ON u.id = o.user_id "
                           "ORDER BY u.email").fetchall()
    return [dict(r) for r in rows]


def is_owner(user_id: int) -> bool:
    with connect() as con:
        return con.execute("SELECT 1 FROM owners WHERE user_id = ?", (user_id,)).fetchone() is not None


def export_user() -> dict:
    """Everything stored about the current user, as plain data (their GDPR copy)."""
    user_id = uid()
    with connect() as con:
        user = con.execute("SELECT email, created_at FROM users WHERE id = ?", (user_id,)).fetchone()
        prefs = con.execute("SELECT key, value FROM settings WHERE user_id = ?", (user_id,)).fetchall()
        catalogue = con.execute("SELECT data FROM catalogs WHERE user_id = ?", (user_id,)).fetchone()
        asked = con.execute("SELECT at FROM look_requests WHERE user_id = ? ORDER BY at", (user_id,)).fetchall()
        owner = con.execute("SELECT added_at FROM owners WHERE user_id = ?", (user_id,)).fetchone()
    account = dict(user) if user else {}
    if owner:       # only on the copy of someone who runs Stilsmith (owner.py)
        account["owner_since"] = owner["added_at"]
    return {
        "account": account,
        "settings": {r["key"]: json.loads(r["value"]) for r in prefs},
        "slots": list_slots(),
        "saved_outfits": list_saved(),
        "items_you_added": [c for c in json.loads(catalogue["data"]).get("candidates", [])
                            if c.get("source") == "manual" or c.get("manual")] if catalogue else [],
        "ai_pictures_asked_for_at": [datetime.fromtimestamp(r["at"]).astimezone().isoformat(timespec="seconds")
                                     for r in asked],
    }


# ── slowing down password guessing ────────────────────────────────────────────

def note_failed_login(email: str, ip: str) -> None:
    with connect() as con:
        con.execute("INSERT INTO login_attempts (email, ip, at) VALUES (?, ?, ?)", (email, ip, time.time()))
        con.execute("DELETE FROM login_attempts WHERE at < ?", (time.time() - 24 * 3600,))


def failed_logins(email: str, ip: str, window: float) -> tuple[int, int]:
    """(failures for this address, failures from this network address) inside the window."""
    since = time.time() - window
    with connect() as con:
        by_email = con.execute("SELECT COUNT(*) FROM login_attempts WHERE email = ? AND at > ?",
                               (email, since)).fetchone()[0]
        by_ip = con.execute("SELECT COUNT(*) FROM login_attempts WHERE ip = ? AND at > ?",
                            (ip, since)).fetchone()[0]
    return by_email, by_ip


def clear_failed_logins(email: str) -> None:
    with connect() as con:
        con.execute("DELETE FROM login_attempts WHERE email = ?", (email,))


def note_signup(ip: str) -> int:
    """Record a sign-up from this address; returns how many it made in the last hour."""
    now = time.time()
    with connect() as con:
        con.execute("DELETE FROM signups WHERE at < ?", (now - 3600,))
        con.execute("INSERT INTO signups (ip, at) VALUES (?, ?)", (ip, now))
        return con.execute("SELECT COUNT(*) FROM signups WHERE ip = ?", (ip,)).fetchone()[0]


# ── password reset tokens ─────────────────────────────────────────────────────

def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def add_reset_token(user_id: int, token: str, minutes: int) -> None:
    with connect() as con:
        con.execute("DELETE FROM reset_tokens WHERE user_id = ? OR expires_at < ?", (user_id, time.time()))
        con.execute("INSERT INTO reset_tokens (token_hash, user_id, expires_at) VALUES (?, ?, ?)",
                    (_hash_token(token), user_id, time.time() + minutes * 60))


def reset_token_user(token: str) -> int | None:
    """The user a still-valid reset token belongs to."""
    with connect() as con:
        row = con.execute("SELECT user_id FROM reset_tokens WHERE token_hash = ? AND expires_at > ?",
                          (_hash_token(token), time.time())).fetchone()
    return row["user_id"] if row else None


# ── settings ──────────────────────────────────────────────────────────────────

def get_setting(key: str, default=None):
    with connect() as con:
        row = con.execute("SELECT value FROM settings WHERE user_id = ? AND key = ?", (uid(), key)).fetchone()
    return json.loads(row["value"]) if row else default


def set_setting(key: str, value) -> None:
    with connect() as con:
        con.execute(
            "INSERT INTO settings (user_id, key, value) VALUES (?, ?, ?) "
            "ON CONFLICT(user_id, key) DO UPDATE SET value = excluded.value",
            (uid(), key, json.dumps(value)),
        )


# ── slots ─────────────────────────────────────────────────────────────────────

def _slot(row: sqlite3.Row) -> dict:
    d = dict(row)
    d.pop("user_id", None)
    d["owned"] = bool(d["owned"])
    d["locked"] = bool(d["locked"])
    return d


def list_slots() -> list[dict]:
    with connect() as con:
        rows = con.execute("SELECT * FROM slots WHERE user_id = ? ORDER BY position, name", (uid(),)).fetchall()
    return [_slot(r) for r in rows]


def get_slot(slot_id: str) -> dict | None:
    with connect() as con:
        row = con.execute("SELECT * FROM slots WHERE user_id = ? AND id = ?", (uid(), slot_id)).fetchone()
    return _slot(row) if row else None


def replace_slots(slots: list[dict]) -> None:
    """Swap in a whole new slot list: a fresh proposal, or one rebuilt from the profile that keeps
    the products picked by hand (their pick and lock are written too)."""
    user_id = uid()
    with connect() as con:
        con.execute("DELETE FROM slots WHERE user_id = ?", (user_id,))
        for i, s in enumerate(slots):
            locked = bool(s.get("locked") and s.get("pick"))
            con.execute(
                "INSERT INTO slots (user_id, id, position, name, category, colour, keywords, qty, owned, locked, pick) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (user_id, s["id"], i, s["name"], s["category"], s["colour"], s.get("keywords", ""),
                 int(s.get("qty", 1)), int(bool(s.get("owned"))), int(locked), s["pick"] if locked else None),
            )


def add_slot(slot: dict) -> None:
    user_id = uid()
    with connect() as con:
        pos = con.execute("SELECT COALESCE(MAX(position), -1) + 1 FROM slots WHERE user_id = ?",
                          (user_id,)).fetchone()[0]
        con.execute(
            "INSERT INTO slots (user_id, id, position, name, category, colour, keywords, qty) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (user_id, slot["id"], pos, slot["name"], slot["category"], slot["colour"],
             slot.get("keywords", ""), int(slot.get("qty", 1))),
        )


def update_slot(slot_id: str, **fields) -> None:
    allowed = {"name", "category", "colour", "keywords", "qty", "owned", "locked", "pick", "position"}
    cols = [k for k in fields if k in allowed]
    if not cols:
        return
    values = [int(fields[k]) if isinstance(fields[k], bool) else fields[k] for k in cols]
    # The column names in the statement come from the fixed list above, never from the request.
    statement = f"UPDATE slots SET {', '.join(c + ' = ?' for c in cols)} WHERE user_id = ? AND id = ?"  # nosec
    with connect() as con:
        con.execute(statement, (*values, uid(), slot_id))


def delete_slot(slot_id: str) -> None:
    with connect() as con:
        con.execute("DELETE FROM slots WHERE user_id = ? AND id = ?", (uid(), slot_id))


# ── saved outfits ─────────────────────────────────────────────────────────────

def list_saved() -> list[dict]:
    with connect() as con:
        rows = con.execute("SELECT key, saved_at, label, pieces FROM saved_outfits WHERE user_id = ? "
                           "ORDER BY saved_at DESC", (uid(),)).fetchall()
    return [{**dict(r), "pieces": json.loads(r["pieces"])} for r in rows]


def saved_keys() -> set[str]:
    with connect() as con:
        return {r["key"] for r in con.execute("SELECT key FROM saved_outfits WHERE user_id = ?", (uid(),))}


def save_outfit(key: str, saved_at: str, label: str, pieces: list[dict]) -> None:
    with connect() as con:
        con.execute(
            "INSERT INTO saved_outfits (user_id, key, saved_at, label, pieces) VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(user_id, key) DO UPDATE SET saved_at = excluded.saved_at, label = excluded.label, "
            "pieces = excluded.pieces",
            (uid(), key, saved_at, label, json.dumps(pieces, ensure_ascii=False)),
        )


def unsave_outfit(key: str) -> None:
    with connect() as con:
        con.execute("DELETE FROM saved_outfits WHERE user_id = ? AND key = ?", (uid(), key))


# ── each customer's catalogue (production) ────────────────────────────────────

def get_catalog() -> dict | None:
    with connect() as con:
        row = con.execute("SELECT data FROM catalogs WHERE user_id = ?", (uid(),)).fetchone()
    return json.loads(row["data"]) if row else None


def put_catalog(data: dict) -> None:
    with connect() as con:
        con.execute(
            "INSERT INTO catalogs (user_id, updated_at, data) VALUES (?, ?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET updated_at = excluded.updated_at, data = excluded.data",
            (uid(), now_iso(), json.dumps(data, ensure_ascii=False)),
        )


# ── AI pictures of outfits (looks.py) ─────────────────────────────────────────
# The pictures are not scoped by uid(): one drawn from product descriptions alone
# is the same for everybody, so everybody shares it. One drawn from a person's own
# photo carries that person's user_id; looks.py shows it to nobody else.

def look_rows(keys: list[str]) -> dict[str, dict]:
    if not keys:
        return {}
    marks = ", ".join("?" * len(keys))        # only question marks go into the statement
    statement = f"SELECT * FROM looks WHERE key IN ({marks})"  # nosec
    with connect() as con:
        rows = con.execute(statement, keys).fetchall()
    return {r["key"]: dict(r) for r in rows}


def start_look(key: str, service: str, stale_before: float, waiting_before: float,
               again: bool = False, owner: int | None = None) -> bool:
    """Claim the drawing of one picture. True for exactly one caller: a new picture, another try
    after a failure or after an attempt that died (drawing since before `stale_before`, or waiting
    its turn since before `waiting_before`), or with `again` a fresh version of a finished one."""
    now = time.time()
    with connect() as con:
        cur = con.execute("INSERT OR IGNORE INTO looks (key, user_id, status, started_at, service) "
                          "VALUES (?, ?, 'waiting', ?, ?)", (key, owner, now, service))
        if cur.rowcount == 1:
            return True
        cur = con.execute(
            "UPDATE looks SET status = 'waiting', started_at = ?, error = NULL, service = ? WHERE key = ? AND "
            "(status = 'failed' OR (status = 'working' AND started_at < ?) "
            " OR (status = 'waiting' AND started_at < ?) OR (status = 'ready' AND ?))",
            (now, service, key, stale_before, waiting_before, int(again)))
        return cur.rowcount == 1


def touch_look(key: str) -> bool:
    """Its turn has come: the drawing starts now. False if it is no longer wanted (the row is
    gone with its account, or somebody started it afresh in the meantime)."""
    with connect() as con:
        cur = con.execute("UPDATE looks SET status = 'working', started_at = ? WHERE key = ? AND status = 'waiting'",
                          (time.time(), key))
        return cur.rowcount == 1


def finish_look(key: str, file: str) -> str | None:
    """Record the finished picture. Returns the file it replaces, if any; LookupError if the row is gone."""
    with exclusive() as con:
        row = con.execute("SELECT file FROM looks WHERE key = ?", (key,)).fetchone()
        if row is None:
            raise LookupError(key)
        con.execute("UPDATE looks SET status = 'ready', file = ?, error = NULL WHERE key = ?", (file, key))
    return row["file"]


def fail_look(key: str, error: str) -> None:
    """The attempt failed. A picture that existed before the attempt stays."""
    with connect() as con:
        con.execute("UPDATE looks SET status = CASE WHEN file IS NULL THEN 'failed' ELSE 'ready' END, error = ? "
                    "WHERE key = ?", (error, key))


def drop_personal_looks(user_id: int) -> list[str]:
    """Forget the pictures drawn from this user's photo. Returns their files, for deleting."""
    with exclusive() as con:
        files = [r["file"] for r in con.execute("SELECT file FROM looks WHERE user_id = ? AND file IS NOT NULL",
                                                (user_id,))]
        con.execute("DELETE FROM looks WHERE user_id = ?", (user_id,))
    return files


def take_look_ticket(since: float, per_day: int, per_user: int | None) -> tuple[int, str]:
    """Count one picture for the current user, if the limits leave room for it.

    Returns (ticket, "") when it was counted, or (0, "mine") / (0, "all") naming the limit that
    is used up: `per_user` for this user (None: no such limit), `per_day` for everyone together.
    Looking and counting happen in one step, so requests arriving together cannot all slip under.
    """
    user_id, now = uid(), time.time()
    with exclusive() as con:
        con.execute("DELETE FROM look_requests WHERE at < ?", (now - 48 * 3600,))
        if per_user is not None:
            mine = con.execute("SELECT COUNT(*) FROM look_requests WHERE user_id = ? AND at > ?",
                               (user_id, since)).fetchone()[0]
            if mine >= per_user:
                return 0, "mine"
        if con.execute("SELECT COUNT(*) FROM look_requests WHERE at > ?", (since,)).fetchone()[0] >= per_day:
            return 0, "all"
        cur = con.execute("INSERT INTO look_requests (user_id, at) VALUES (?, ?)", (user_id, now))
        return int(cur.lastrowid or 0), ""


def drop_look_request(ticket: int) -> None:
    """Give a ticket back: a request that certainly cost nothing does not count towards the day's limits."""
    with connect() as con:
        con.execute("DELETE FROM look_requests WHERE id = ?", (ticket,))


def look_requests(since: float, mine: bool = False) -> int:
    """How many pictures were counted since then: for the current user, or for everyone."""
    with connect() as con:
        if mine:
            return con.execute("SELECT COUNT(*) FROM look_requests WHERE user_id = ? AND at > ?",
                               (uid(), since)).fetchone()[0]
        return con.execute("SELECT COUNT(*) FROM look_requests WHERE at > ?", (since,)).fetchone()[0]


# ── store feeds (feeds/) ──────────────────────────────────────────────────────
# Shared by everybody, not scoped by uid(): which stores Stilsmith may take products
# from, and the products their feeds carry.

STORE_SETTINGS = ("label", "network", "programme_id", "status", "feed_format", "feed_location",
                  "delivery_note", "disclaimer", "rules")
PRODUCT_COLUMNS = ("store", "product_id", "group_id", "name", "brand", "category", "gender", "colour",
                   "colour_key", "material", "composition", "price", "sale_price", "currency", "sizes",
                   "sizes_in_stock", "available", "image_url", "buy_link", "feed_updated_at", "imported_at")


def _store(row: sqlite3.Row) -> dict:
    d = dict(row)
    d["rules"] = json.loads(d.get("rules") or "{}")
    return d


def list_stores() -> list[dict]:
    """Every store in the registry, with how many products it has now."""
    with connect() as con:
        rows = con.execute("SELECT s.*, (SELECT COUNT(*) FROM products p WHERE p.store = s.key) AS products "
                           "FROM stores s ORDER BY s.key").fetchall()
    return [_store(r) for r in rows]


def get_store(key: str) -> dict | None:
    with connect() as con:
        row = con.execute("SELECT s.*, (SELECT COUNT(*) FROM products p WHERE p.store = s.key) AS products "
                          "FROM stores s WHERE s.key = ?", (key,)).fetchone()
    return _store(row) if row else None


def save_store(key: str, values: dict) -> str:
    """Add a store or update its settings. Returns 'added', 'updated' or 'unchanged'.
    Its products and its import history are left as they are."""
    values = {**values, "rules": json.dumps(values.get("rules") or {}, ensure_ascii=False, sort_keys=True)}
    row = [values.get(name) for name in STORE_SETTINGS]
    with exclusive() as con:
        old = con.execute("SELECT * FROM stores WHERE key = ?", (key,)).fetchone()
        if old is None:
            con.execute("INSERT INTO stores (key, label, network, programme_id, status, feed_format, feed_location, "
                        "delivery_note, disclaimer, rules) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (key, *row))
            return "added"
        if [old[name] for name in STORE_SETTINGS] == row:
            return "unchanged"
        con.execute("UPDATE stores SET label = ?, network = ?, programme_id = ?, status = ?, feed_format = ?, "
                    "feed_location = ?, delivery_note = ?, disclaimer = ?, rules = ? WHERE key = ?", (*row, key))
        return "updated"


def note_store(key: str, *, error: str | None, feed_update: str | None = None, imported_at: str | None = None) -> None:
    """Record how a refresh went: the error (None: it worked), and the feed's time and the import's when known."""
    with connect() as con:
        con.execute("UPDATE stores SET last_error = ?, last_feed_update = COALESCE(?, last_feed_update), "
                    "last_import_at = COALESCE(?, last_import_at) WHERE key = ?",
                    (error, feed_update, imported_at, key))


def note_download(key: str, when: str) -> None:
    """Record that a store's feed began to download at `when`, whether or not it is then imported:
    a network that limits downloads (Tradedoubler) counts every one."""
    with connect() as con:
        con.execute("UPDATE stores SET last_download_at = ? WHERE key = ?", (when, key))


def replace_products(store: str, rows: list[dict],
                     check: Callable[[int, int], None] | None = None) -> tuple[int, int]:
    """Swap one store's products for these, in one transaction: if anything fails part-way, the old
    rows stay exactly as they were. Products missing from `rows` are gone afterwards.
    `check`, if given, is told how many products the store has and how many of them the swap would
    remove, inside the same transaction and before anything changes; it raises to stop the swap.
    Returns (products now, products that were there before and are gone)."""
    marks = ", ".join("?" * len(PRODUCT_COLUMNS))      # only the fixed column names go into the statement
    statement = f"INSERT INTO products ({', '.join(PRODUCT_COLUMNS)}) VALUES ({marks})"  # nosec
    with exclusive() as con:
        before = {r[0] for r in con.execute("SELECT product_id FROM products WHERE store = ?", (store,))}
        gone = len(before - {row["product_id"] for row in rows})
        if check is not None:
            check(len(before), gone)
        con.execute("DELETE FROM products WHERE store = ?", (store,))
        for row in rows:
            con.execute(statement, _product_values(store, row))
    return len(rows), gone


def _product_values(store: str, row: dict) -> list:
    """A product row in the order of PRODUCT_COLUMNS, its lists written as JSON."""
    values = []
    for name in PRODUCT_COLUMNS:
        value = store if name == "store" else row.get(name)
        if name in ("composition", "sizes", "sizes_in_stock"):
            value = json.dumps(value or [], ensure_ascii=False)
        elif name == "available" and value is not None:
            value = int(bool(value))
        values.append(value)
    return values


def end_store(key: str) -> int:
    """A programme ended, or the store asked: all of its products go at once and it is marked ended.
    Returns how many products were deleted."""
    with exclusive() as con:
        gone = con.execute("DELETE FROM products WHERE store = ?", (key,)).rowcount
        con.execute("UPDATE stores SET status = 'ended' WHERE key = ?", (key,))
    return gone


def store_products(store: str) -> list[dict]:
    """One store's products, with the JSON columns read back into lists."""
    with connect() as con:
        rows = con.execute("SELECT * FROM products WHERE store = ? ORDER BY product_id", (store,)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        for name in ("composition", "sizes", "sizes_in_stock"):
            d[name] = json.loads(d[name])
        if d["available"] is not None:
            d["available"] = bool(d["available"])
        out.append(d)
    return out


# ── the owner's view of every store's catalogue (owner.py) ────────────────────

def _has_words(text: str | None, words: str) -> bool:
    """Whether every word of a search is in the text, whatever their case: 'WEISS merino' finds
    'Weiß ... Merinowolle' ('ß' folds to 'ss'). `words` comes folded already."""
    folded = (text or "").casefold()
    return all(word in folded for word in words.split())


# Which products a search finds. Every filter is given, as NULL when it is not used, so the statement is
# fixed text: nothing from the request is ever written into it. Colour 'unknown' finds the products whose
# colour Stilsmith did not recognise. A size is one the feed says is in stock. The words are looked for in the
# name, brand, category, colour (the feed's and Stilsmith's: 'navy' finds 'Marineblau'), fabric, id and store.
_FOUND = """
    FROM products p JOIN stores s ON s.key = p.store
    WHERE (:store IS NULL OR p.store = :store)
      AND (:category IS NULL OR p.category = :category)
      AND (:colour IS NULL OR p.colour_key = :colour OR (:colour = 'unknown' AND p.colour_key IS NULL))
      AND (:size IS NULL OR EXISTS (SELECT 1 FROM json_each(p.sizes_in_stock) j WHERE j.value = :size))
      AND (:words IS NULL OR has_words(p.name || ' ' || COALESCE(p.brand, '') || ' ' || COALESCE(p.category, '')
                                       || ' ' || COALESCE(p.colour, '') || ' ' || replace(COALESCE(p.colour_key, ''), '-', ' ')
                                       || ' ' || COALESCE(p.material, '') || ' ' || p.product_id || ' ' || s.label, :words))
"""
# Fixed text only (see _FOUND): nothing from a request is written into these two statements. Bandit's
# check for SQL built from strings (B608) does not flag them, so they carry no nosec.
_COUNT_FOUND = "SELECT COUNT(*)" + _FOUND
_LIST_FOUND = ("SELECT p.*, s.label AS store_label" + _FOUND
               + " ORDER BY s.label, p.name, p.group_id, p.product_id LIMIT :limit OFFSET :offset")


def find_products(store: str | None = None, category: str | None = None, colour: str | None = None,
                  size: str | None = None, words: str | None = None, limit: int = 100,
                  offset: int = 0) -> tuple[int, list[dict]]:
    """Every store's products that match, a page at a time: (how many match in all, this page's rows),
    with the JSON columns read back into lists and the store's label as store_label."""
    asked = {"store": store, "category": category, "colour": colour, "size": size,
             "words": " ".join(words.casefold().split()) or None if words else None,
             "limit": limit, "offset": offset}
    with connect() as con:
        con.create_function("has_words", 2, _has_words, deterministic=True)
        total = con.execute(_COUNT_FOUND, asked).fetchone()[0]
        rows = con.execute(_LIST_FOUND, asked).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        for name in ("composition", "sizes", "sizes_in_stock"):
            d[name] = json.loads(d[name])
        out.append(d)
    return total, out


def product_choices() -> dict[str, list[tuple[str | None, int]]]:
    """What the filters on the owner's catalogue offer, each with how many products have it: the feeds'
    own categories, Stilsmith's colours (None: not recognised) and the sizes the feeds say are in stock."""
    with connect() as con:
        return {
            "categories": [tuple(r) for r in con.execute(
                "SELECT category, COUNT(*) FROM products WHERE category IS NOT NULL GROUP BY category ORDER BY category")],
            "colours": [tuple(r) for r in con.execute("SELECT colour_key, COUNT(*) FROM products GROUP BY colour_key")],
            "sizes": [tuple(r) for r in con.execute(
                "SELECT j.value, COUNT(*) FROM products p, json_each(p.sizes_in_stock) j GROUP BY j.value")],
        }
