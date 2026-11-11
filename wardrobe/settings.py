"""How the app is running. Everything here comes from environment variables.

    CAPSULE_ENV=local        (default) your own machine: one implicit user, no login,
                             the collector (`python -m wardrobe refresh`) is available
    CAPSULE_ENV=production   customers: accounts, CSRF protection, secure cookies,
                             security headers, and no collector at all

Production also needs:
    SECRET_KEY               long random string that signs the session cookie (required)
    SITE_URL                 public address, e.g. https://capsule.example (used in emails)
and optionally:
    WARDROBE_DATA_DIR        where the database lives (default: ./data)
    SMTP_URL                 smtp://user:password@host:587 — without it, emails are only logged
    MAIL_FROM                sender address for those emails
    TRUSTED_PROXY_HOPS       how many reverse proxies sit in front (0 = none, 1 = typical)
    SESSION_DAYS             how long a login lasts (default 30)

In either mode, one of these switches on the AI pictures of outfits (looks.py):
    OPENAI_API_KEY           a key from platform.openai.com
    GEMINI_API_KEY           a key from aistudio.google.com (GOOGLE_API_KEY is read too)
Which one is used, and with which model, is set in config/looks.toml.
"""
from __future__ import annotations

import os

MODE = os.environ.get("CAPSULE_ENV", "local").strip().lower()
PRODUCTION = MODE == "production"

SITE_NAME = "Capsule"
SITE_URL = os.environ.get("SITE_URL", "http://127.0.0.1:8000").rstrip("/")
SECRET_KEY = os.environ.get("SECRET_KEY", "")
SMTP_URL = os.environ.get("SMTP_URL", "")
MAIL_FROM = os.environ.get("MAIL_FROM", "Capsule <no-reply@localhost>")
TRUSTED_PROXY_HOPS = int(os.environ.get("TRUSTED_PROXY_HOPS", "0") or 0)
SESSION_DAYS = int(os.environ.get("SESSION_DAYS", "30") or 30)

# Keys of the image services. Secrets: they come from the environment only, never from a file in the project.
UNUSABLE_KEYS: list[str] = []      # names of keys that are set but cannot be keys


def _key(*names: str) -> str:
    """The first of these environment variables that is set. A value that cannot be a key (a pasted
    placeholder such as "sk-…", a stray space or line break) counts as not set, and its name is noted."""
    for name in names:
        value = os.environ.get(name, "").strip()
        if value and value.isascii() and value.isprintable() and " " not in value:
            return value
        if value:
            UNUSABLE_KEYS.append(name)
    return ""


OPENAI_API_KEY = _key("OPENAI_API_KEY")
GEMINI_API_KEY = _key("GEMINI_API_KEY", "GOOGLE_API_KEY")

# Accounts
MIN_PASSWORD_LENGTH = 10
LOGIN_WINDOW_SECONDS = 15 * 60
LOGIN_MAX_FAILURES_PER_EMAIL = 5      # wrong passwords for one address inside the window
LOGIN_MAX_FAILURES_PER_IP = 30        # … and from one network address
SIGNUPS_PER_IP_PER_HOUR = 10
RESET_TOKEN_MINUTES = 60


def on_this_machine() -> bool:
    """True while the service's public address (SITE_URL) is this computer: a trial run, with no
    outside customers yet. Messages meant for the operator may then be shown on the pages."""
    from urllib.parse import urlsplit
    return (urlsplit(SITE_URL).hostname or "") in ("127.0.0.1", "localhost", "::1")


def check() -> None:
    """Refuse to start in production with settings that would be unsafe."""
    if PRODUCTION and len(SECRET_KEY) < 32:
        raise SystemExit(
            "CAPSULE_ENV=production needs a SECRET_KEY of at least 32 characters.\n"
            "Make one with:  python -c \"import secrets; print(secrets.token_urlsafe(48))\"")
