"""How the app is running. Everything here comes from environment variables.

    CAPSULE_ENV=local        (default) your own machine: one implicit user, no login,
                             the collector (`python -m wardrobe refresh`) is available
    CAPSULE_ENV=production   customers: accounts, CSRF protection, secure cookies,
                             security headers, and no collector at all

Production also needs:
    SECRET_KEY               long random string that signs the session cookie (required)
    SITE_URL                 public address, e.g. https://stilsmith.example (used in emails)
and optionally:
    WARDROBE_DATA_DIR        where the database lives (default: ./data)
    SMTP_URL                 smtp://user:password@host:587 — without it, emails are only logged
    MAIL_FROM                sender address for those emails
    TRUSTED_PROXY_HOPS       how many reverse proxies sit in front (0 = none, 1 = typical)
    SESSION_DAYS             how long a login lasts (default 30)
    INVITE_CODE              if set, only people who know it can create an account ("by invitation").
                             At least 8 characters. Give it out as  <SITE_URL>/signup?code=<the code>

In either mode, one of these switches on the AI pictures of outfits (looks.py):
    OPENAI_API_KEY           a key from platform.openai.com
    GEMINI_API_KEY           a key from aistudio.google.com (GOOGLE_API_KEY is read too)
Which one is used, and with which model, is set in config/looks.toml.
"""
from __future__ import annotations

import os

MODE = os.environ.get("CAPSULE_ENV", "local").strip().lower()
PRODUCTION = MODE == "production"

# The product's name, in one place: every page's title, the wordmark, the emails, error pages, the site password's
# sign-in box and the command line's messages take it from here. The web manifest (static/app.webmanifest) is a
# plain file: a test checks that it says the same. Names inside the code, such as the package `wardrobe` and
# CAPSULE_ENV, keep the product's old name on purpose (README.md).
SITE_NAME = "Stilsmith"
SITE_URL = os.environ.get("SITE_URL", "http://127.0.0.1:8000").rstrip("/")
SECRET_KEY = os.environ.get("SECRET_KEY", "")
SMTP_URL = os.environ.get("SMTP_URL", "")
MAIL_FROM = os.environ.get("MAIL_FROM", f"{SITE_NAME} <no-reply@localhost>")
TRUSTED_PROXY_HOPS = int(os.environ.get("TRUSTED_PROXY_HOPS", "0") or 0)
SESSION_DAYS = int(os.environ.get("SESSION_DAYS", "30") or 30)
INVITE_CODE = os.environ.get("INVITE_CODE", "").strip()      # empty: anybody may create an account
MIN_INVITE_CODE_LENGTH = 8
# A private trial on the internet: when set, every page (the landing page too) first asks for this password, so
# nothing is public. Empty: the site is open as usual.
SITE_PASSWORD = os.environ.get("SITE_PASSWORD", "").strip()
MIN_SITE_PASSWORD_LENGTH = 12

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


PLACEHOLDER = "replace-me"      # how the values in deploy/app.env.example begin: known to everyone


def check() -> None:
    """Refuse to start in production with settings that would be unsafe."""
    if not PRODUCTION:
        return
    if len(SECRET_KEY) < 32 or SECRET_KEY.startswith(PLACEHOLDER):
        raise SystemExit(
            "CAPSULE_ENV=production needs a SECRET_KEY of its own, at least 32 characters"
            + (": this one is still the example's placeholder.\n" if SECRET_KEY.startswith(PLACEHOLDER) else ".\n")
            + "Make one with:  python -c \"import secrets; print(secrets.token_urlsafe(48))\"")
    if INVITE_CODE and (len(INVITE_CODE) < MIN_INVITE_CODE_LENGTH or INVITE_CODE.startswith(PLACEHOLDER)):
        raise SystemExit(
            "INVITE_CODE would keep nobody out: "
            + ("it is still the example's placeholder" if INVITE_CODE.startswith(PLACEHOLDER)
               else f"use at least {MIN_INVITE_CODE_LENGTH} characters") + ".\n"
            "Make one with:  python -c \"import secrets; print(secrets.token_urlsafe(9))\"\n"
            "(or leave INVITE_CODE out to let anybody create an account)")
    if SITE_PASSWORD and (len(SITE_PASSWORD) < MIN_SITE_PASSWORD_LENGTH or SITE_PASSWORD.startswith(PLACEHOLDER)):
        raise SystemExit(
            "SITE_PASSWORD would keep nobody out: "
            + ("it is still the example's placeholder" if SITE_PASSWORD.startswith(PLACEHOLDER)
               else f"use at least {MIN_SITE_PASSWORD_LENGTH} characters") + ".\n"
            "Make one with:  python -c \"import secrets; print(secrets.token_urlsafe(12))\"\n"
            "(or leave SITE_PASSWORD out to open the site)")
