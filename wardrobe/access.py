"""Cloudflare Access in front of the site: whoever it has checked needs no password here.

A private trial sits behind Cloudflare Access (deploy/README.md): before any page, Cloudflare asks a visitor for his
email address, sends a code to it, and lets through only the addresses on the owner's list. So when a request reaches
Stilsmith, Cloudflare has already proved whose address it is, and says so in a signed token it adds to the request
(the header Cf-Access-Jwt-Assertion). With ACCESS_TEAM and ACCESS_AUD set (settings.py) Stilsmith reads that token,
and asks nobody whom Cloudflare has checked for a second proof (auth.py):

    no account yet            "Create your account" names his address over one button: no form, no password
                              (auth.checked). The account it makes has no password at all (NO_PASSWORD).
    an account made that way  he is logged in when he opens a page (auth.load_user), until he logs out here: from
                              then on "Log in" has one button for him, "Continue as …".
    an account with a         is not touched: it logs in with its password, as always. Cloudflare's check never opens
    password                  it, so nobody gets into an account that somebody else may have made in his name.

What is believed, and what is not. Only the token, and only after checking it here, each time: that the team's own key
signed it (RS256; the keys are fetched from the team's address and kept for a few hours), that it was made for this
site (aud) by this team (iss), that it has not run out (exp), and that it is an application's token that names an email
address (a service token names none). The address on its own, in a header of its own, is never read: anyone can write
a header. A token that fails, or keys that cannot be fetched, count as no token. The site then works as it does
without Cloudflare Access, with its forms and passwords: nothing here lets someone in whom a password would not.

Without the two settings (your own machine, a server with nothing in front) no token is read at all.

The checking itself is PyJWT's, with the `cryptography` package for the signature (requirements-prod.txt). It is
loaded only where the two settings are set.
"""
from __future__ import annotations

import json
import logging
import threading
import time
import urllib.request
from typing import Any

from flask import g, request

from . import settings

log = logging.getLogger("capsule.access")

HEADER = "Cf-Access-Jwt-Assertion"      # where Cloudflare puts its token, on every request it lets through
# What stands in place of a password's hash in an account made through Cloudflare's check. It is no hash (one begins
# with its method and a "$"), so no password matches it. Not empty either: that marks Stilsmith's own accounts
# (db.internal_account). (The risk check reads the name as a password written into the code: it is the opposite.)
NO_PASSWORD = "!cloudflare-access"      # nosec B105
KEYS_SECONDS = 4 * 3600         # the team's keys are fetched again after this long (Cloudflare changes them every six
                                # weeks, and honours the one before for seven days more)
KEYS_LAST = 24 * 3600           # keys that could not be fetched again for this long are no longer used
ASK_AGAIN_SECONDS = 60          # after a fetch that failed, or a token signed with a key that is not among them
TIMEOUT = 3                     # seconds for the fetch: a page waits for it
MAX_KEYS = 256 * 1024           # bytes. The answer holds two keys
LEEWAY = 60                     # seconds a clock may be off
SAY_AGAIN_SECONDS = 60          # the same kind of line in the log: once in this long

_lock = threading.Lock()
_keys: dict[str, Any] = {}              # the team's public keys, by their id (kid)
_fetched_at: float | None = None        # when they were fetched (time.monotonic)
_asked_at: float | None = None          # when they were last asked for, whether or not that worked
_said: dict[str, float] = {}            # the kinds of line written to the log, and when


def on() -> bool:
    """Whether Cloudflare's tokens are read: on the public site, with both settings."""
    return settings.PRODUCTION and bool(settings.ACCESS_TEAM and settings.ACCESS_AUD)


def issuer() -> str:
    """Who signs the tokens: the team's own address at Cloudflare."""
    return f"https://{settings.ACCESS_TEAM}.cloudflareaccess.com"


def status() -> str:
    """For the start-up lines: whether it is on, in words."""
    if not on():
        return "off (ACCESS_TEAM and ACCESS_AUD are not set): everyone logs in with a password"
    return (f"on. Whoever {settings.ACCESS_TEAM}.cloudflareaccess.com has checked creates an account with one button "
            "and needs no password")


def _clock() -> float:
    """Seconds that only ever go forward, for the ages of the keys and of the log's lines."""
    return time.monotonic()


def _say(kind: str, message: str, *args: object, once: bool = False, warning: bool = True) -> None:
    """One line in the log, but the same kind not again within a minute (`once`: never again in this process):
    a wrong setting refuses every request's token, and the log is not for counting them."""
    now = _clock()
    last = _said.get(kind)
    if last is not None and (once or now - last < SAY_AGAIN_SECONDS):
        return
    _said[kind] = now
    log.log(logging.WARNING if warning else logging.INFO, message, *args)


# ── the team's keys ───────────────────────────────────────────────────────────

class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """The keys come from the team's own address or not at all: an answer that points elsewhere is not followed."""

    def redirect_request(self, *args, **kwargs):
        return None


# Proxies are taken from the environment only, as in imagegen.py: the default would also ask macOS for its system
# proxy settings, and doing that inside a web-server worker crashes the worker on a Mac.
_opener = urllib.request.build_opener(urllib.request.ProxyHandler(urllib.request.getproxies_environment()),
                                      _NoRedirect)


def _fetch() -> dict[str, Any]:
    """The team's public keys by their id, from its own address. Raises when the address cannot be reached, or
    answers with anything else."""
    import jwt                                  # PyJWT: only a site behind Cloudflare Access loads it
    with _opener.open(issuer() + "/cdn-cgi/access/certs", timeout=TIMEOUT) as answer:
        listed = json.loads(answer.read(MAX_KEYS + 1))
    keys = {str(entry["kid"]): jwt.PyJWK.from_dict(entry, algorithm="RS256").key
            for entry in listed["keys"] if entry.get("kty") == "RSA" and entry.get("kid")}
    if not keys:
        raise ValueError("the answer holds no keys")
    return keys


def _key(kid: str) -> Any | None:
    """The team's key with this id, or None. The keys are fetched when there are none, when they are old, and when
    this one is not among them (Cloudflare has changed them) — but never twice within ASK_AGAIN_SECONDS, whatever
    arrives. While a fetch fails, the keys from before go on being used, for a day at most."""
    global _keys, _fetched_at, _asked_at
    with _lock:
        now = _clock()
        fresh = _fetched_at is not None and now - _fetched_at < KEYS_SECONDS
        asked_just_now = _asked_at is not None and now - _asked_at < ASK_AGAIN_SECONDS
        if (kid in _keys and fresh) or asked_just_now:
            return _keys.get(kid)
        _asked_at = now
        try:
            _keys, _fetched_at = _fetch(), now
        except Exception as problem:  # noqa: BLE001 - whatever went wrong: no new keys, and the site carries on
            _say("keys", "Cloudflare Access: the team's keys could not be fetched from %s (%s). Until they can, "
                         "people log in with a password.", issuer(), type(problem).__name__)
            if _fetched_at is None or now - _fetched_at > KEYS_LAST:
                _keys = {}
        return _keys.get(kid)


def forget_keys() -> None:
    """Start again with no keys and nothing said (for tests, which give each case a team of its own)."""
    global _keys, _fetched_at, _asked_at
    with _lock:
        _keys, _fetched_at, _asked_at = {}, None, None
        _said.clear()


# ── a request's token ─────────────────────────────────────────────────────────

def email_in(token: str) -> str | None:
    """The email address Cloudflare vouches for in this token, in small letters — or None: a token that is not
    believed (the module's own words say what is checked), or one that names no address (a service token)."""
    import jwt                                  # PyJWT: only a site behind Cloudflare Access loads it
    try:
        head = jwt.get_unverified_header(token)
        if head.get("alg") != "RS256":          # before any key is looked up: Cloudflare signs with RS256, always
            raise jwt.InvalidAlgorithmError("not RS256")
        key = _key(str(head.get("kid") or ""))
        if key is None:
            raise jwt.InvalidKeyError("not signed with one of the team's keys")
        claims = jwt.decode(token, key, algorithms=["RS256"], audience=settings.ACCESS_AUD, issuer=issuer(),
                            options={"require": ["exp", "iat", "iss", "aud"]}, leeway=LEEWAY)
    except jwt.PyJWTError as refusal:
        # Only the kind of refusal: never the token, and never words that might quote it.
        _say(type(refusal).__name__, "Cloudflare Access: a request's token was not believed (%s). If every one is "
             "refused, check ACCESS_TEAM and ACCESS_AUD. Such a visitor logs in with a password.",
             type(refusal).__name__)
        return None
    _say("believed", "Cloudflare Access: the first token was checked and believed.", once=True, warning=False)
    email = claims.get("email")
    if claims.get("type") != "app" or not isinstance(email, str) or not email.strip():
        return None                             # a service token, or the team's own session: nobody's address
    return email.strip().lower()


def checked_email() -> str | None:
    """The email address Cloudflare vouches for on this request (email_in), or None. Worked out once a request."""
    if not on():
        return None
    if "access_email" not in g:
        token = request.headers.get(HEADER, "")
        g.access_email = email_in(token) if token else None
    return g.access_email
