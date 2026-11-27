"""Customer accounts (production mode only).

Sign-up, log-in, log-out, password reset, and the account page with the two
things data-protection law gives every customer: a copy of their data and its
deletion. Also the request-level guards: who is signed in, and the CSRF token
that every form and HTMX request must carry.

Passwords are stored only as salted scrypt hashes (werkzeug). A login cookie
holds the user id and a counter; changing the password raises the counter,
which signs the account out everywhere else.

Behind Cloudflare Access (access.py) someone whose email address Cloudflare has
already checked needs no password: one button makes his account (checked), and
from then on Cloudflare's check opens it (load_user). An account with a password
is never opened that way. The owner can also make such an account for someone
beforehand (owner.py, `account add`): he then never signs up at all, and his
first page is the welcome (_first_page).
"""
from __future__ import annotations

import hmac
import json
import re
import secrets

from flask import (Blueprint, Flask, Response, abort, flash, g, redirect, render_template, request,
                   session, url_for)
from flask.sessions import SecureCookieSessionInterface, SessionMixin
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.wrappers import Response as Answer

from . import access, db, guests, looks, mail, person, settings, shared
from .onboarding import ensure_setup

bp = Blueprint("auth", __name__)

EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")
# Checked when the address is unknown, so a wrong address takes as long as a wrong password.
_DUMMY_HASH = generate_password_hash("not a real password")


# ── who is signed in ──────────────────────────────────────────────────────────

# Stilsmith's own files: the stylesheet, scripts, fonts and icons (static/) and /favicon.ico. They are the same for
# everyone, so no account is looked up for them and they never carry the login cookie: browsers keep them (see
# static_files_kept in app.py), and so can a shared cache such as Cloudflare's, which keeps no file that sets a cookie.
FILES = {"static", "favicon"}


class LoginCookie(SecureCookieSessionInterface):
    """Flask's signed login cookie, except on Stilsmith's own files: those never set it, nor "Vary: Cookie".
    (Flask renews a lasting login cookie with every response, a stylesheet or a font included. Every page
    still renews it.)"""

    def save_session(self, app: Flask, session: SessionMixin, response: Response) -> None:
        if request.endpoint in FILES:
            return
        super().save_session(app, session, response)


# In the cookie of a browser that logged out while Cloudflare vouches for its user (access.py): his account is not
# opened again by itself. It stays so until he asks: "Continue as …" on Log in (checked).
LEFT = "left"


def load_user() -> Answer | None:
    """Runs before every request: find the signed-in user and scope the database to them. (What it returns is
    where someone goes whom Cloudflare's check has just logged in, when that is not the page he asked for:
    _first_page.)"""
    g.user = None
    if request.endpoint in FILES:       # a file, the same for everyone: no account is looked up
        return None
    user_id = session.get("uid")
    if user_id is not None:
        user = db.get_user(user_id)
        if user and user["session_epoch"] == session.get("epoch") and not _someone_else(user):
            g.user = user
        else:
            session.clear()             # deleted account, signed out everywhere, or now somebody else's browser
    let_in = False
    if g.user is None and _opens_a_page() and not session.get(LEFT):
        user = checked_account()
        if user:        # Cloudflare has checked him, and nothing but that check opens his account: he is in
            _fresh_cookie(user)
            g.user, let_in = user, True
    g.user_token = db.set_user(g.user["id"] if g.user else None)
    return _first_page() if let_in else None


# Set in an account that was made for someone: the welcome then says what he agrees to by going on (_begin).
AGREES = "agrees_at_welcome"


def _begin() -> bool:
    """Give an account that was made for someone (owner.py, `python -m wardrobe account add`) what the sign-up form
    gives a new one, the first time he is in: its set-up and the welcome. True if this was that first time. What he
    agrees to is said by the welcome's buttons then (welcome.html, AGREES): he never saw the sign-up page, where
    it is said otherwise."""
    if db.get_setting("slots_initialised"):
        return False
    ensure_setup()
    db.set_setting("welcome", "new")
    db.set_setting(AGREES, True)
    return True


def _first_page() -> Answer | None:
    """Where someone goes whom Cloudflare's check has just logged in (load_user), if not to the page he asked for.
    The first time, to the welcome (_begin), as after the sign-up form. And by the front door, to the welcome he
    left before its end: it is offered once more, as logging in with a password does."""
    if _begin() or (request.endpoint == "wardrobe" and db.get_setting("welcome") == "new"):
        return redirect(url_for("welcome"))
    return None


def _opens_a_page() -> bool:
    """Whether this request opens a page, by its address or a link: not a form being sent, not a page's own script
    (HTMX), not a picture. Only then is someone logged in by Cloudflare's check: logging in starts a new cookie,
    and with it a new token for the forms (csrf_token), which a page that is already open would not have."""
    return (request.method == "GET" and not request.headers.get("HX-Request")
            and "text/html" in request.headers.get("Accept", ""))


def _checked() -> str | None:
    """The email address Cloudflare vouches for on this request (access.py), or None: always None where Cloudflare
    Access is not set up."""
    return _email(access.checked_email())


def checked_account() -> dict | None:
    """The account that Cloudflare's check opens for whoever sent this request: the one with the address Cloudflare
    vouches for, if it was made through that check (it has no password). Never an account with a password: whoever
    chose that password may be somebody else. And never one of Stilsmith's own (db.internal_account)."""
    email = _checked()
    user = db.get_user_by_email(email) if email else None
    return user if user and user["password_hash"] == access.NO_PASSWORD else None


def _someone_else(user: dict) -> bool:
    """Whether Cloudflare now vouches for another address than this account's, in a browser that is logged in to an
    account its check opens: somebody else has sat down at it. (No token, or one that is not believed, changes
    nothing: he stays logged in, as with a password.)"""
    if user["password_hash"] != access.NO_PASSWORD:
        return False
    email = _checked()
    return email is not None and email != user["email"]


def is_owner() -> bool:
    """Whether the person asking runs Stilsmith, and so may see the owner's pages (owner.py).
    On your own machine you do: one person, no login. In production, an account marked with
    `python -m wardrobe owner add EMAIL`; nobody signed out is one."""
    if not settings.PRODUCTION:
        return True
    user = g.get("user")
    return bool(user) and db.is_owner(user["id"])


def unload_user(_exc=None) -> None:
    token = g.pop("user_token", None)
    if token is not None:
        db.reset_user(token)


def _fresh_cookie(user: dict) -> None:
    session.clear()                     # a fresh cookie: nothing carries over from before login
    session["uid"], session["epoch"] = user["id"], user["session_epoch"]
    session["csrf"] = secrets.token_urlsafe(32)
    session.permanent = True


def start_session(user: dict) -> None:
    _fresh_cookie(user)
    db.set_user(user["id"])
    g.user = user


# ── CSRF ──────────────────────────────────────────────────────────────────────

def csrf_token() -> str:
    if "csrf" not in session:
        session["csrf"] = secrets.token_urlsafe(32)
    return session["csrf"]


def check_csrf() -> None:
    """Every request that changes something must prove it came from one of our own pages."""
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return
    sent = request.headers.get("X-CSRF-Token") or request.form.get("csrf_token", "")
    if not sent or not hmac.compare_digest(sent, session.get("csrf", "")):
        abort(400, f"This page was open for too long or was not sent from {settings.SITE_NAME}. "
                   "Reload it and try again.")


# ── helpers ───────────────────────────────────────────────────────────────────

def _email(value: str | None) -> str | None:
    value = (value or "").strip().lower()
    return value if len(value) <= 254 and EMAIL.fullmatch(value) else None


def password_problem(password: str, email: str = "") -> str | None:
    if len(password) < settings.MIN_PASSWORD_LENGTH:
        return f"Use at least {settings.MIN_PASSWORD_LENGTH} characters."
    if len(password) > 200:
        return "That password is too long."
    if email and password.lower() == email.lower():
        return "The password must not be your email address."
    return None


def _next_page() -> str:
    """Where logging in leads: back to the page that was asked for, or else the outfits, Stilsmith's home."""
    target = request.values.get("next", "")
    # Only a plain path on this site. Browsers drop tabs and line breaks from an address and read "\" as
    # "/", so "/<tab>/evil.example" and "/\evil.example" would both lead to another website.
    if target.startswith("/") and not target.startswith("//") and not re.search(r"[\\\s\x00-\x1f\x7f]", target):
        return target
    return url_for("outfits_page")


def _throttled(email: str) -> bool:
    by_email, by_ip = db.failed_logins(email, request.remote_addr or "", settings.LOGIN_WINDOW_SECONDS)
    return by_email >= settings.LOGIN_MAX_FAILURES_PER_EMAIL or by_ip >= settings.LOGIN_MAX_FAILURES_PER_IP


# ── sign up, log in, log out ──────────────────────────────────────────────────

@bp.route("/signup", methods=["GET", "POST"])
def signup():
    if g.user:                                  # already has an account: his outfits
        return redirect(url_for("outfits_page"))
    invite = bool(settings.INVITE_CODE)         # by invitation: the form also asks for the code
    # HEAD (link checkers, "curl -I") is answered like GET here and below, never as a form that was sent.
    if request.method in ("GET", "HEAD"):
        # `why`: what a visitor without an account tapped, in one line over the form ("Create a free account to save
        # outfits."): only words of guests.WHY, picked by the word in the address (?why=save), never words from it.
        why = guests.reason(request.args.get("why"), real=shared.published())
        # Someone Cloudflare has checked (access.py) gets one button in place of the form (checked): his address is
        # known and proved. Not with an invitation code set, which the form asks for, and not when he asks for the
        # form himself (?password=1: another address, or a password of his own).
        email = None if invite or request.args.get("password") else _checked()
        account = db.get_user_by_email(email) if email else None
        if account and account["password_hash"] == access.NO_PASSWORD:
            return redirect(url_for("auth.login"))      # he has one, and logged out here: "Continue as …"
        if email and not account:
            return render_template("auth_signup.html", checked=email, why=why)
        return render_template("auth_signup.html", invite=invite, code=request.args.get("code", "")[:200], why=why)
    email, password = _email(request.form.get("email")), request.form.get("password", "")
    code = request.form.get("code", "").strip()[:200]
    problem = "Enter a valid email address." if not email else password_problem(password, email)
    # Every attempt from here on is counted, a wrong invitation code included: the code cannot be
    # tried at speed. (Nothing above this line looks at the code, so nothing uncounted reveals it.)
    if not problem and db.note_signup(request.remote_addr or "") > settings.SIGNUPS_PER_IP_PER_HOUR:
        problem = "Too many new accounts from this connection. Try again in an hour."
    if not problem and invite and not hmac.compare_digest(code.encode(), settings.INVITE_CODE.encode()):
        problem = f"That invitation code is not right. {settings.SITE_NAME} is open by invitation for now."
    if problem:
        flash(problem)
        return render_template("auth_signup.html", email=request.form.get("email", ""), invite=invite, code=code), 400
    assert email is not None
    user_id = db.create_user(email, generate_password_hash(password))
    if user_id is None:
        flash("There is already an account with this email address. Log in, or reset the password.")
        return render_template("auth_signup.html", email=email, invite=invite, code=code), 400
    user = db.get_user(user_id)
    assert user is not None
    start_session(user)
    ensure_setup()
    # First the welcome: three short steps (his sizes, colours and budget, what he dresses for), each of which he
    # may skip, then the outfits (app.py, welcome). Until he has been through it, logging in leads there again.
    db.set_setting("welcome", "new")
    return redirect(url_for("welcome"))


def _login_page(**shown) -> str:
    """The Log in page. For someone Cloudflare has checked, whose account that check opens and who logged out in
    this browser, it has one button over the form: "Continue as …" (checked)."""
    account = checked_account()
    return render_template("auth_login.html", checked=account["email"] if account else None, **shown)


@bp.route("/login", methods=["GET", "POST"])
def login():
    if g.user:
        return redirect(_next_page())
    if request.method in ("GET", "HEAD"):
        return _login_page(next=request.args.get("next", ""))
    email = _email(request.form.get("email")) or ""
    password = request.form.get("password", "")
    if _throttled(email):
        flash("Too many attempts. Wait fifteen minutes, or reset the password.")
        return _login_page(email=email, next=request.form.get("next", "")), 429
    user = db.get_user_by_email(email) if email else None
    # An account without a password (Stilsmith's own, or one that Cloudflare's check opens: access.py) is treated
    # as an unknown address is: the same work, the same answer.
    has_password = bool(user and user["password_hash"] and user["password_hash"] != access.NO_PASSWORD)
    stored = user["password_hash"] if user and has_password else _DUMMY_HASH
    if not check_password_hash(stored, password) or not user or not has_password:
        db.note_failed_login(email, request.remote_addr or "")
        flash("Email or password is wrong.")
        return _login_page(email=email, next=request.form.get("next", "")), 401
    db.clear_failed_logins(email)
    start_session(user)
    if not request.values.get("next") and db.get_setting("welcome") == "new":
        return redirect(url_for("welcome"))     # he left the welcome before its end: it is offered once more
    return redirect(_next_page())


@bp.post("/checked")
def checked():
    """The one button of someone Cloudflare has checked (access.py). "Create my account", the first time: his
    account has no password, and Cloudflare's check opens it from then on. And "Continue as …" on Log in, after he
    logged out in this browser. The address is the one in Cloudflare's token on this very request, never one the
    browser sends."""
    if g.user:
        return redirect(_next_page())
    email = _checked()
    if not email:
        flash("The check of your email address has run out. Reload the page and try again.")
        return redirect(url_for("auth.login"))
    user = db.get_user_by_email(email)
    if user is None and settings.INVITE_CODE:       # by invitation: the form asks for the code, this button cannot
        flash(f"{settings.SITE_NAME} is open by invitation for now. Create your account with the form and your code.")
        return redirect(url_for("auth.signup", password=1))
    new = False
    if user is None:
        user_id = db.create_user(email, access.NO_PASSWORD)
        new = user_id is not None                   # (None: the button was pressed twice at once, and the other won)
        user = db.get_user(user_id) if user_id is not None else db.get_user_by_email(email)
    if not user or user["password_hash"] != access.NO_PASSWORD:
        # An account with a password: his own from before, or one somebody else made with his address. Cloudflare's
        # check does not open it, and it is not his to take over here.
        flash("This email address already has an account with a password. Log in with that password.")
        return redirect(url_for("auth.login"))
    start_session(user)
    if new:
        db.owner_at_last(user["id"], email)     # named as an owner before he had an account (owner.py)
        ensure_setup()
        db.set_setting("welcome", "new")        # first the welcome, as after the sign-up form
        return redirect(url_for("welcome"))
    if _begin():                                # an account made for him, opened for the first time
        return redirect(url_for("welcome"))
    if not request.values.get("next") and db.get_setting("welcome") == "new":
        return redirect(url_for("welcome"))     # he left the welcome before its end: it is offered once more
    return redirect(_next_page())


@bp.post("/logout")
def logout():
    session.clear()
    if access.on():         # Cloudflare's check would open his account again at the next page: not until he asks
        session[LEFT] = True
        session.permanent = True
    flash("You are logged out.")
    return redirect(url_for("wardrobe"))


# ── forgotten password ────────────────────────────────────────────────────────

@bp.route("/forgot", methods=["GET", "POST"])
def forgot():
    if request.method in ("GET", "HEAD"):
        return render_template("auth_forgot.html")
    email = _email(request.form.get("email"))
    user = db.get_user_by_email(email) if email else None
    if user and user["password_hash"] and not _throttled(email or ""):
        token = secrets.token_urlsafe(32)
        db.add_reset_token(user["id"], token, settings.RESET_TOKEN_MINUTES)
        link = settings.SITE_URL + url_for("auth.reset", token=token)
        mail.send(user["email"], f"Reset your {settings.SITE_NAME} password",
                  f"Someone asked to reset the {settings.SITE_NAME} password for this address.\n\n"
                  f"Choose a new one here (the link works for {settings.RESET_TOKEN_MINUTES} minutes):\n{link}\n\n"
                  "If that wasn't you, ignore this message; nothing changes.")
    # The same answer whether or not the address has an account.
    flash("If there is an account for that address, a reset link is on its way.")
    return redirect(url_for("auth.login"))


@bp.route("/reset/<token>", methods=["GET", "POST"])
def reset(token: str):
    user_id = db.reset_token_user(token)
    if user_id is None:
        flash("That reset link has expired or was already used. Ask for a new one.")
        return redirect(url_for("auth.forgot"))
    if request.method in ("GET", "HEAD"):
        return render_template("auth_reset.html", token=token)
    user = db.get_user(user_id)
    password = request.form.get("password", "")
    problem = password_problem(password, user["email"] if user else "")
    if problem or not user:
        flash(problem or "That account no longer exists.")
        return render_template("auth_reset.html", token=token), 400
    db.set_password(user_id, generate_password_hash(password))
    db.clear_failed_logins(user["email"])
    session.clear()
    flash("Password changed. Log in with the new one.")
    return redirect(url_for("auth.login"))


# ── the account page ──────────────────────────────────────────────────────────

@bp.get("/account")
def account():
    # owner: the link to /stores. no_password: an account that Cloudflare's check opens (access.py) has none to
    # change, and none to ask for before it is deleted.
    return render_template("account.html", tab="account", owner=is_owner(),
                           no_password=g.user["password_hash"] == access.NO_PASSWORD)


@bp.post("/account/password")
def change_password():
    current, new = request.form.get("current", ""), request.form.get("password", "")
    if g.user["password_hash"] == access.NO_PASSWORD:
        flash("This account has no password: the check of your email address logs you in.")
    elif not check_password_hash(g.user["password_hash"], current):
        flash("The current password is wrong.")
    elif (problem := password_problem(new, g.user["email"])):
        flash(problem)
    else:
        db.set_password(g.user["id"], generate_password_hash(new))
        refreshed = db.get_user(g.user["id"])
        assert refreshed is not None
        start_session(refreshed)        # this device stays in; all others are signed out
        flash("Password changed. You've been logged out everywhere else.")
    return redirect(url_for("auth.account"))


@bp.get("/account/export")
def export_data():
    data = db.export_user()
    # Said as the Account page says it ("your photo and the pictures made from it"): the two are kept and go together.
    data["your_photo"] = ("stored, with the pictures made from it; see the photo, or delete it and them, "
                          "on the Profile page" if person.photo() else "none stored")
    body = json.dumps(data, ensure_ascii=False, indent=2)
    name = f"{settings.SITE_NAME.lower()}-my-data.json"         # stilsmith-my-data.json
    return Response(body, mimetype="application/json", headers={"Content-Disposition": f"attachment; filename={name}"})


@bp.post("/account/delete")
def delete_account():
    if g.user["password_hash"] == access.NO_PASSWORD:
        # No password to type again: in its place, Cloudflare's check of this account's address on this very request.
        if _checked() != g.user["email"]:
            flash("The check of your email address has run out, so nothing was deleted. Reload the page and try again.")
            return redirect(url_for("auth.account"))
    elif not check_password_hash(g.user["password_hash"], request.form.get("current", "")):
        flash("The password is wrong, so nothing was deleted.")
        return redirect(url_for("auth.account"))
    looks.forget_photo(g.user["id"])    # the files: their photo and the pictures drawn from it
    db.delete_user(g.user["id"])
    session.clear()
    flash("Your account and everything in it have been deleted.")
    return redirect(url_for("wardrobe"))
