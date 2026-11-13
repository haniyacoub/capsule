"""Customer accounts (production mode only).

Sign-up, log-in, log-out, password reset, and the account page with the two
things data-protection law gives every customer: a copy of their data and its
deletion. Also the request-level guards: who is signed in, and the CSRF token
that every form and HTMX request must carry.

Passwords are stored only as salted scrypt hashes (werkzeug). A login cookie
holds the user id and a counter; changing the password raises the counter,
which signs the account out everywhere else.
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

from . import db, looks, mail, person, settings
from .onboarding import ensure_setup

bp = Blueprint("auth", __name__)

EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")
# Checked when the address is unknown, so a wrong address takes as long as a wrong password.
_DUMMY_HASH = generate_password_hash("not a real password")


# ── who is signed in ──────────────────────────────────────────────────────────

# Capsule's own files: the stylesheet, scripts, fonts and icons (static/) and /favicon.ico. They are the same for
# everyone, so no account is looked up for them and they never carry the login cookie: browsers keep them (see
# static_files_kept in app.py), and so can a shared cache such as Cloudflare's, which keeps no file that sets a cookie.
FILES = {"static", "favicon"}


class LoginCookie(SecureCookieSessionInterface):
    """Flask's signed login cookie, except on Capsule's own files: those never set it, nor "Vary: Cookie".
    (Flask renews a lasting login cookie with every response, a stylesheet or a font included. Every page
    still renews it.)"""

    def save_session(self, app: Flask, session: SessionMixin, response: Response) -> None:
        if request.endpoint in FILES:
            return
        super().save_session(app, session, response)


def load_user() -> None:
    """Runs before every request: find the signed-in user and scope the database to them."""
    g.user = None
    if request.endpoint in FILES:       # a file, the same for everyone: no account is looked up
        return
    user_id = session.get("uid")
    if user_id is not None:
        user = db.get_user(user_id)
        if user and user["session_epoch"] == session.get("epoch"):
            g.user = user
        else:
            session.clear()             # deleted account, or signed out everywhere
    g.user_token = db.set_user(g.user["id"] if g.user else None)


def is_owner() -> bool:
    """Whether the person asking runs Capsule, and so may see the owner's pages (owner.py).
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


def start_session(user: dict) -> None:
    session.clear()                     # a fresh cookie: nothing carries over from before login
    session["uid"], session["epoch"] = user["id"], user["session_epoch"]
    session["csrf"] = secrets.token_urlsafe(32)
    session.permanent = True
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
        abort(400, "This page was open for too long or was not sent from Capsule. Reload it and try again.")


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
    """Where logging in leads: back to the page that was asked for, or else the outfits, Capsule's home."""
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
        return render_template("auth_signup.html", invite=invite, code=request.args.get("code", "")[:200])
    email, password = _email(request.form.get("email")), request.form.get("password", "")
    code = request.form.get("code", "").strip()[:200]
    problem = "Enter a valid email address." if not email else password_problem(password, email)
    # Every attempt from here on is counted, a wrong invitation code included: the code cannot be
    # tried at speed. (Nothing above this line looks at the code, so nothing uncounted reveals it.)
    if not problem and db.note_signup(request.remote_addr or "") > settings.SIGNUPS_PER_IP_PER_HOUR:
        problem = "Too many new accounts from this connection. Try again in an hour."
    if not problem and invite and not hmac.compare_digest(code.encode(), settings.INVITE_CODE.encode()):
        problem = "That invitation code is not right. Capsule is open by invitation for now."
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
    # Straight to the starter outfits on the model, drawn already and shared, so they show at once. The banner at
    # their top says whose they are and leads to the Profile page to make them his (outfits.html): no form first.
    return redirect(url_for("outfits_page"))


@bp.route("/login", methods=["GET", "POST"])
def login():
    if g.user:
        return redirect(_next_page())
    if request.method in ("GET", "HEAD"):
        return render_template("auth_login.html", next=request.args.get("next", ""))
    email = _email(request.form.get("email")) or ""
    password = request.form.get("password", "")
    if _throttled(email):
        flash("Too many attempts. Wait fifteen minutes, or reset the password.")
        return render_template("auth_login.html", email=email, next=request.form.get("next", "")), 429
    user = db.get_user_by_email(email) if email else None
    stored = user["password_hash"] if user and user["password_hash"] else _DUMMY_HASH
    if not check_password_hash(stored, password) or not user or not user["password_hash"]:
        db.note_failed_login(email, request.remote_addr or "")
        flash("Email or password is wrong.")
        return render_template("auth_login.html", email=email, next=request.form.get("next", "")), 401
    db.clear_failed_logins(email)
    start_session(user)
    return redirect(_next_page())


@bp.post("/logout")
def logout():
    session.clear()
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
                  f"Someone asked to reset the password for this address.\n\n"
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
    return render_template("account.html", tab="account", owner=is_owner())    # owner: the link to /stores


@bp.post("/account/password")
def change_password():
    current, new = request.form.get("current", ""), request.form.get("password", "")
    if not check_password_hash(g.user["password_hash"], current):
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
    return Response(body, mimetype="application/json",
                    headers={"Content-Disposition": "attachment; filename=capsule-my-data.json"})


@bp.post("/account/delete")
def delete_account():
    if not check_password_hash(g.user["password_hash"], request.form.get("current", "")):
        flash("The password is wrong, so nothing was deleted.")
        return redirect(url_for("auth.account"))
    looks.forget_photo(g.user["id"])    # the files: their photo and the pictures drawn from it
    db.delete_user(g.user["id"])
    session.clear()
    flash("Your account and everything in it have been deleted.")
    return redirect(url_for("wardrobe"))
