"""The web pages.

Each route loads the current state, changes one thing if asked, and renders
HTML. The thinking happens in the other modules; nothing clever lives here.

Buttons on the pages use HTMX: they POST to a route below and swap the
returned HTML fragment into the page, plus the summary bar ("out of band").

In production mode (see settings.py) the same pages sit behind customer
accounts: auth.py decides who is signed in, and db.py only ever returns that
customer's rows.
"""
from __future__ import annotations

import hashlib
import hmac
import ipaddress
import math
import random
import re
import secrets
import sys
from datetime import timedelta
from urllib.parse import parse_qsl, urlencode, urlsplit

from flask import (Flask, Response, abort, flash, g, get_flashed_messages, redirect, render_template, request,
                   send_file, session, url_for)
from markupsafe import Markup
from werkzeug.exceptions import HTTPException, NotFound

from . import (auth, capsule, catalog, colours, composition, db, export, imagegen, looks, mock, mockimg, outfits,
               owner, person, programmes, selection, shared, style, stylechat, tryon, yes)
from . import figure
from . import videos
from . import profile as profile_mod
from . import english
from . import settings as conf
from .onboarding import ensure_setup
from .config import ConfigError
from .garments import GARMENTS
from .paths import ROOT
from .sizes import ALPHA

# The tabs, in order. The outfits on the AI model are the heart of Stilsmith, so they come first.
# The plan editor (/slots) has no tab: "Edit the plan" on the Wardrobe page leads to it.
NAV = [
    ("outfits", "Outfits", "outfits_page"),
    ("wardrobe", "Wardrobe", "wardrobe"),
    ("list", "Shopping", "list_page"),
    ("profile", "Profile", "profile_page"),
]


# Pages anyone may open without an account (production mode).
PUBLIC = {"static", "wardrobe", "legal_page", "healthz", "robots_txt", "mock_image",
          "auth.signup", "auth.login", "auth.forgot", "auth.reset",
          "favicon"}
LEGAL_PAGES = {"impressum": "Impressum", "privacy": "Privacy policy", "terms": "Terms of use"}
# The date of the words a customer agrees to when he uploads his photo (the box on Profile, profile.html). It is
# stored with the photo, so it is known which words he agreed to. Give it a new date whenever those words change.
# 2026-11-15: the words say that an outfit's further photos ("More photos") are made from the AI picture of him,
# which goes to the image service again. (2026-11-12: his photo goes to the service for each picture of him.)
# While videos are on, the box's words also say that pictures of him go to Google for videos: those words have
# their own date, videos.CONSENT, which is stored beside this one (videos.agreed_with_the_photo).
PHOTO_CONSENT = "2026-11-15"


def bootstrap() -> None:
    """Start-up: create or update the database; on your own machine, set up the one local user."""
    problem = db.sqlite_problem()
    if problem:     # said in the start-up lines (the server's log in production), before the first page can freeze
        print(f"Warning: {problem}", file=sys.stderr, flush=True)
    db.init()
    if not conf.PRODUCTION:
        ensure_setup()


def sync_catalog(changed_slot: str | None = None) -> bool:
    """Keep the catalogue in step with the slot list after an edit.

    On demo data the invented candidates are rebuilt. On real data, candidates
    of deleted slots are dropped, and so are those collected for a slot whose
    garment or colour just changed (they no longer fit it). Items you added by
    hand always stay, also from a store that is no longer offered (set aside, see
    catalog.set_aside). Returns True if real data now needs a refresh: only on your
    own machine, where you can run one (REFRESH_HINT). A customer can't, so a
    customer is never told to.
    """
    current = catalog.stored()      # all of it: what you added from a store that is no longer offered stays
    slots = db.list_slots()
    if conf.PRODUCTION:                 # customers get their candidates from the shared store catalogue
        real = shared.build_catalog(slots, current)
        if real:
            catalog.save(real)
            return False
    if current.get("source") == "mock":
        fresh = mock.build(slots)
        fresh["candidates"] += [c for c in current.get("candidates", []) if c.get("source") == "manual"]
        catalog.save(fresh)
        return False
    if current.get("source") != "collected":
        return False

    def tidy(cat: dict) -> None:
        catalog.prune(cat, {s["id"] for s in slots})
        if changed_slot:
            cat["candidates"] = [c for c in cat["candidates"]
                                 if c.get("slot_id") != changed_slot or c.get("source") == "manual"]
    catalog.update(tidy)
    filled = set(catalog.by_slot(catalog.load()))
    return not conf.PRODUCTION and any(s["id"] not in filled and not s["owned"] for s in slots)


REFRESH_HINT = "Pieces with nothing to buy fill up at the next “python -m wardrobe refresh”."


def plan_edited(before: dict) -> bool:
    """Whether the plan itself was changed on the plan page: a piece added, renamed, recoloured or
    removed. Choosing a product, locking it or marking a piece as owned doesn't count: a rebuild
    from the profile keeps those (capsule.rebuild). `before` is the profile the plan was built from.
    """
    edited = db.get_setting("plan_edited")
    if edited is None:
        # Older accounts have one setting, "slots_customised", for every change made by hand. It counts
        # as an edit only if the plan is not what the profile (or the example values every account
        # starts with) proposes; a choice, a lock or an owned mark alone doesn't.
        edited = bool(db.get_setting("slots_customised")) and not any(
            capsule.same_plan(db.list_slots(), answers) for answers in (before, profile_mod.EXAMPLE))
        db.set_setting("plan_edited", edited)
    return bool(edited)


def rebuild_plan(profile: dict, before: dict) -> tuple[capsule.Rebuilt, bool]:
    """Rebuild the plan from the profile, keeping what was picked or marked as owned by hand, and
    bring the catalogue in step. Also returns whether real data now needs a refresh."""
    old = db.list_slots()
    plan = capsule.rebuild(profile, old, before.get("owned", ""))
    fresh = len(plan.slots)
    plan.slots = with_his_pieces(plan.slots, old, before)
    plan.stayed = plan.slots[fresh:]
    stayed = {slot["name"] for slot in plan.stayed}
    plan.lost = [(name, why) for name, why in plan.lost if name not in stayed]      # (it was kept after all)
    db.replace_slots(plan.slots)
    needs_refresh = sync_catalog()
    # A kept piece has the same id, garment and colour, so its product is on offer again. Checked all
    # the same: the message must not say it was kept if it is not shown.
    offered = catalog.by_slot(catalog.load())
    for slot in list(plan.picked):
        if slot["pick"] not in {c.get("id") for c in offered.get(slot["id"], [])}:
            db.update_slot(slot["id"], locked=False, pick=None)
            plan.picked.remove(slot)
            plan.lost.append((slot["name"], f"no longer in {conf.SITE_NAME}'s product list"))
    return plan, needs_refresh


def rebuilt_message(plan: capsule.Rebuilt) -> str:
    """'Your plan now has 17 pieces in your colours. Kept your 2 hand-picked pieces.', and what was not kept.
    With pieces of his wardrobe that the new plan has no place for: 'Your plan now has 16 pieces in your colours.
    The 3 pieces of your wardrobe that the new plan has no place for were kept as they were: 19 pieces in all.'"""
    def pieces(n: int) -> str:
        return "piece" if n == 1 else "pieces"

    def count(slots: list[dict]) -> int:       # as every page counts: a white tee ×2 is two pieces
        return sum(int(s.get("qty") or 1) for s in slots)

    # The pieces of his wardrobe that the new plan has no place for stay (rebuild_plan), in the colours they had:
    # they are not among the pieces "in your colours", and are counted once, in their own sentence.
    total, stayed, picked, owned = count(plan.slots), count(plan.stayed), len(plan.picked), len(plan.owned)
    words = [f"Your plan now has {total - stayed} {pieces(total - stayed)} in your colours."]
    if picked and owned:
        words.append(f"Kept your {picked} hand-picked {pieces(picked)} and the {owned} you own.")
    elif picked:
        words.append(f"Kept your {picked} hand-picked {pieces(picked)}.")
    elif owned:
        words.append(f"Kept the {owned} {pieces(owned)} you own.")
    if stayed:
        words.append(f"The {stayed} {pieces(stayed)} of your wardrobe that the new plan has no place for "
                     f"{'was kept as it was' if stayed == 1 else 'were kept as they were'}: {total} {pieces(total)} "
                     "in all.")
    if plan.lost:
        words.append("Not kept: " + ", ".join(f"{name} ({why})" for name, why in plan.lost) + ".")
    return " ".join(words)


def with_his_pieces(new: list[dict], old: list[dict], profile: dict | None = None) -> list[dict]:
    """A plan made afresh (`new`), with the pieces of the plan before it (`old`) that are in his wardrobe and that
    the new plan has no place for. A piece an outfit he said yes to wears, or one he kept, stays in the plan as it
    is, whatever new answers propose: his outfits go on being made of it, and nothing leaves his wardrobe that he
    did not take out himself. (What he owns follows its own rules: capsule.rebuild.) `profile`: the answers the
    plan before was built from."""
    mine = {view.slot["id"] for view in selection.build(profile=profile).slots if view.outfits_in or view.kept}
    here = {slot["id"] for slot in new}
    return new + [slot for slot in old if slot["id"] in mine and slot["id"] not in here]


def recoloured_name(name: str, old: str, new: str) -> str:
    """A piece's name once it takes a new colour: 'Black wool blazer' in navy is 'Navy wool blazer'.
    Only a name that starts with the old colour's name changes; any other ('My lucky blazer') stays."""
    before, after = colours.get(old).label, colours.get(new).label
    rest = name[len(before):]
    if not name.lower().startswith(before.lower()) or rest[:1].isalpha():   # 'Blackwatch shirt' is no black shirt
        return name
    return ((after if name[:1].isupper() else after.lower()) + rest)[:60]


def eur(value) -> str:
    value = float(value or 0)
    text = f"{value:,.0f}" if abs(value - round(value)) < 0.005 else f"{value:,.2f}"
    return f"{text} €"


def brief_changed(before: tuple[dict, float], after: tuple[dict, float], what: str) -> Markup | str:
    """What a change of the style brief did to his picks, in one sentence, or "" when every piece kept its product.
    `before` and `after`: each piece's product, how many of it count, and whether the piece is in his wardrobe
    ({piece: (product, how many, in his wardrobe)}), and his wardrobe's total, the one the bar at the top shows, from
    before and after the change (picks_of in create_app). `what` did it: "Your brief", "Removing it", "Your styles".

    His wardrobe is the pieces of the outfits he said yes to (yes.py), and only those count in his total. So the
    sentence says of how many pieces the product changed, and what that did to his total only where a piece of his
    is among them:

        every changed piece is his      "Your brief changed 2 pieces: +4 €."   (or "… Your total is the same.")
        some of them are his            "Your brief changed 5 pieces, 2 of them in your wardrobe: +4 €."
        none is his (a new customer)    "Your brief changed 5 of the pieces your outfits are made from. Your
                                         wardrobe is as it was."
    """
    (was, total_was), (now, total_now) = before, after
    changed = [(qty, mine) for slot_id, (product, qty, mine) in now.items()
               if was.get(slot_id, (None, 0, False))[0] != product]
    n, his = sum(qty for qty, _ in changed), sum(qty for qty, mine in changed if mine)
    if not n:
        return ""
    if not his:
        return Markup("%s changed %s of the pieces your outfits are made from. Your wardrobe is as it was.") % (what, n)
    pieces = f"{n} {'piece' if n == 1 else 'pieces'}" + (f", {his} of them in your wardrobe" if his < n else "")
    cents = round(total_now * 100) - round(total_was * 100)
    if not cents:
        return Markup("%s changed %s. Your total is the same.") % (what, pieces)
    amount = eur(abs(cents) / 100)
    # "+4 €" to the eye, "4 € more" to a screen reader, as beside the options of a piece (_piece.html).
    return Markup('%s changed %s: <span aria-hidden="true">%s%s</span><span class="sr">%s %s</span>.') % (
        what, pieces, "+" if cents > 0 else "−", amount, amount, "more" if cents > 0 else "less")


def weblink(url) -> str:
    """Only ordinary web addresses become links; anything else in the data is ignored."""
    url = str(url or "").strip()
    return url if url.startswith(("https://", "http://")) else "#"


def _asset_version() -> str:
    """The ?v= at the end of the addresses of the stylesheet and the scripts (base.html, error.html).

    Browsers keep those files for a year without asking again (static_files_kept, in create_app), so the
    address must change whenever one of them does. It is made from the name, size and time of change of
    every file under static/, htmx in static/vendor/ included: an edit, a new file or an older copy put
    back all change it. Looking at every file takes about half a millisecond, so in production it is done
    once per start (asset_version, in create_app), not for every page.
    """
    static = ROOT / "wardrobe" / "static"
    files = sorted((str(p.relative_to(static)), p.stat().st_size, p.stat().st_mtime_ns)
                   for p in static.rglob("*") if p.is_file())
    return hashlib.sha256(repr(files).encode()).hexdigest()[:12]


def _this_computer(host: str) -> bool:
    """Whether the address a browser asked for names this machine directly: localhost, a numeric
    address, or a name on the home network (something.local).

    Without a login, the app on your own machine trusts whoever can reach it. A web page elsewhere
    can make a browser talk to it by pointing a domain name of its own at 127.0.0.1; such a request
    arrives under that domain name, and is refused here.
    """
    name = (urlsplit("//" + host).hostname or "").lower()
    if name == "localhost" or name.endswith(".local"):
        return True
    try:
        ipaddress.ip_address(name)
        return True
    except ValueError:
        return False


def _pictures_on() -> bool:
    """Whether AI pictures are switched on. A typo in config/looks.toml must not take the public pages down."""
    try:
        return looks.service() is not None
    except ConfigError:
        return False


def _photos_on() -> bool:
    """Whether customers may upload a photo to be the model themselves: pictures on, and photos allowed."""
    try:
        return looks.service() is not None and looks.load_rules()["pictures"]["photos"]
    except ConfigError:
        return False


def site_password_given() -> Response | None:
    """With SITE_PASSWORD set, every page, file and form first needs that password (the browser's own sign-in box,
    any user name). Only /healthz answers without it, for the container's health check. Nothing of the app, not
    even the landing page, is shown to anyone without it."""
    if request.endpoint == "healthz":
        return None
    given = request.authorization
    password = (given.password or "") if given is not None and given.type == "basic" else ""
    if hmac.compare_digest(password.encode(), conf.SITE_PASSWORD.encode()):
        return None
    return Response(f"{conf.SITE_NAME} is private for now.\n", status=401, headers={
        "WWW-Authenticate": f'Basic realm="{conf.SITE_NAME} (private)", charset="UTF-8"',
        "Content-Type": "text/plain; charset=utf-8", "Cache-Control": "no-store"})


# A product's page as a customer saved it from his browser, sent with its link (slot_import; collect/generic.py).
SAVED_PAGE = 3 * 1024 * 1024
PAGE_TOO_LARGE = "Not added: the saved page is larger than 3 MB. Paste the link alone and type in the price."


def create_app() -> Flask:
    conf.check()
    app = Flask(__name__)
    app.config["TEMPLATES_AUTO_RELOAD"] = True   # template edits show on reload, like config edits
    app.config["MAX_CONTENT_LENGTH"] = 512 * 1024     # nothing a form sends is larger than this
    if conf.PRODUCTION:
        app.secret_key = conf.SECRET_KEY
        app.config.update(
            SESSION_COOKIE_SECURE=conf.SITE_URL.startswith("https://"),
            SESSION_COOKIE_HTTPONLY=True,
            SESSION_COOKIE_SAMESITE="Lax",
            PERMANENT_SESSION_LIFETIME=timedelta(days=conf.SESSION_DAYS),
        )
        if conf.TRUSTED_PROXY_HOPS:     # behind a reverse proxy: trust its view of address and https
            from werkzeug.middleware.proxy_fix import ProxyFix
            hops = conf.TRUSTED_PROXY_HOPS
            app.wsgi_app = ProxyFix(app.wsgi_app, x_for=hops, x_proto=hops, x_host=hops)  # type: ignore[method-assign]
        app.session_interface = auth.LoginCookie()      # the login cookie, never on Stilsmith's own files
        app.register_blueprint(auth.bp)
    else:
        app.secret_key = secrets.token_hex(16)   # only signs the one-off "saved" messages
    app.register_blueprint(owner.bp)            # the owner's pages, such as /stores: owners only (owner.py)
    app.jinja_env.trim_blocks = True
    app.jinja_env.lstrip_blocks = True
    app.jinja_env.filters["eur"] = eur
    app.jinja_env.filters["weblink"] = weblink
    app.jinja_env.filters["as_picked"] = english.as_picked     # 'Dark brown derby shoes' filled by a loafer -> 'Dark brown loafers'
    app.jinja_env.globals["outfit_title"] = yes.title     # "Office, smart casual", over an outfit
    app.jinja_env.filters["outfit_name"] = yes.name       # an outfit's pieces -> 'outfit with the navy blazer and grey trousers'
    app.jinja_env.filters["english"] = english.name      # a store's German product name in English, or None
    app.jinja_env.globals.update(
        nav=NAV, GARMENTS=GARMENTS, COLOURS=colours.COLOURS, ALPHA=ALPHA,
        USES=profile_mod.USES, MODES=selection.MODES, OCCASIONS=outfits.OCCASIONS,
        ink_on=colours.ink_on, level_hints=selection.HINTS,
        # The stores customers are offered, {key: name}, and their names in a sentence (programmes.py).
        STORES=programmes.OFFERED, store_names=programmes.names, stocked_stores=shared.stocked,
        # The stores the signed-in customer ticked on Profile's Stores tab, [key], which his pieces come from.
        my_stores=profile_mod.stores,
        # What a customer added to a piece from a store that is no longer offered, listed on its page (_set_aside.html).
        set_aside_for=catalog.set_aside,
        # Beside "More photos": what it costs, or how many pictures are really left today (_shots.html).
        more_words=looks.more_words,
    )
    bootstrap()

    # In production the files under static/ don't change while Stilsmith runs (an update restarts it, see
    # PRODUCTION.md), so their version is worked out once, here. On your own machine it is worked out for every
    # page, so an edit to the stylesheet shows at the next reload.
    version_at_start = _asset_version() if conf.PRODUCTION else None

    def asset_version() -> str:
        return version_at_start or _asset_version()

    def csrf_field() -> Markup:
        """The hidden input every form carries in production (nothing on your own machine)."""
        if not conf.PRODUCTION:
            return Markup("")
        return Markup('<input type="hidden" name="csrf_token" value="%s">') % auth.csrf_token()

    @app.context_processor
    def per_request_values():
        return {"asset_v": asset_version(), "tryon_available": tryon.available(),
                "production": conf.PRODUCTION, "user": g.get("user"), "csrf_field": csrf_field,
                "csrf_token": auth.csrf_token if conf.PRODUCTION else (lambda: ""),
                "legal_pages": LEGAL_PAGES, "site_name": conf.SITE_NAME}

    if conf.SITE_PASSWORD:  # before anything else: a private trial asks every visitor for the site's password
        app.before_request(site_password_given)
    if conf.PRODUCTION:     # first: a page that refuses a request still knows who asked (its way home, error.html)
        app.before_request(auth.load_user)
        app.teardown_request(auth.unload_user)

    @app.before_request
    def same_origin_only():
        # A page on some other website must not be able to press buttons here.
        origin = request.headers.get("Origin")
        if request.method == "POST" and origin and urlsplit(origin).netloc != request.host:
            abort(403)
        if not conf.PRODUCTION and not _this_computer(request.host):
            abort(403)
        if request.endpoint == "profile_photo":     # the two forms that carry a file: a photo,
            request.max_content_length = person.MAX_PHOTO + 64 * 1024
        elif request.endpoint == "slot_import":     # and a product's page as the customer saved it
            request.max_content_length = SAVED_PAGE + 64 * 1024

    if conf.PRODUCTION:
        @app.before_request
        def accounts_and_csrf():
            if request.endpoint in auth.FILES:      # a stylesheet, script, font or icon: no account, no form
                return None
            auth.check_csrf()
            # The owner's pages (owner.py): to anyone else, exactly what an address that does not exist gets.
            if request.blueprint == owner.bp.name and not auth.is_owner():
                abort(404)
            if g.user is None:
                if request.endpoint in PUBLIC or request.endpoint is None:
                    return None
                if request.headers.get("HX-Request"):       # a button on a page whose login ran out
                    return Response(status=401, headers={"HX-Redirect": url_for("auth.login")})
                return redirect(url_for("auth.login", next=request.full_path.rstrip("?")))
            if not db.get_setting("slots_initialised"):
                ensure_setup()
            shared.refresh_customer()   # a newer store catalogue was published: pick it up
            return None

    @app.after_request
    def response_headers(resp: Response) -> Response:
        if resp.mimetype == "text/html":
            resp.headers["Cache-Control"] = "no-store"
        if conf.PRODUCTION:
            resp.headers.setdefault("Content-Security-Policy", (
                "default-src 'self'; img-src 'self' data: https:; style-src 'self' 'unsafe-inline'; "
                "script-src 'self'; connect-src 'self'; base-uri 'self'; form-action 'self'; "
                "frame-ancestors 'none'; object-src 'none'"))
            resp.headers.setdefault("X-Content-Type-Options", "nosniff")
            resp.headers.setdefault("X-Frame-Options", "DENY")
            resp.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
            resp.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
            if request.is_secure:
                resp.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        return resp

    @app.after_request
    def static_files_kept(resp: Response) -> Response:
        """How long browsers keep Stilsmith's own files (static/), so that moving between pages fetches only the page.

        For a year, without asking again: the stylesheet and the scripts at their current ?v= (the address changes
        with every update of the files, see _asset_version), and the fonts (a changed font gets a new file name, see
        app.css).
        For a day: the manifest and the icons, whose addresses phones and browsers remember (like /favicon.ico).
        Never without asking (Flask's "no-cache"): a ?v= that is no longer the current one, from a page made before
        an update, so that an address is never kept with a file it did not name.
        """
        if request.endpoint != "static" or resp.status_code not in (200, 304):
            return resp
        version, name = request.args.get("v"), (request.view_args or {}).get("filename", "")
        if version == asset_version() or (version is None and name.startswith("fonts/")):
            resp.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        elif version is None:
            resp.headers["Cache-Control"] = "public, max-age=86400"
        return resp

    # Each error page in Stilsmith's own words: a title and one line (error.html adds the way home). Werkzeug's
    # own sentences ("The requested URL was not found on the server…") are written for developers and never
    # shown; a message Stilsmith itself gives to abort() takes the place of the line.
    error_words = {
        400: ("That didn't go through", "Reload the page and try again."),
        403: ("That didn't go through", "Reload the page and try again."),
        404: ("We can't find that page", "The link may be old, or the page may have moved."),
        405: ("We can't find that page", "The link may be old, or the page may have moved."),
        409: ("That changed in the meantime", "Reload the page and try again."),
        413: ("Too much data", "Go back and try again with less."),
        429: ("Too many attempts", "Wait a few minutes and try again."),
        500: ("Something went wrong on our side", "It's not you. Try again in a minute."),
        501: ("Not available yet", f"This part of {conf.SITE_NAME} isn't built yet."),
    }

    def error_page(code: int, own: str | None = None):
        title, line = error_words.get(code) or error_words[400 if code < 500 else 500]
        return render_template("error.html", title=title, message=own or line, plain=True), code

    @app.errorhandler(ConfigError)
    def config_error(err: ConfigError):
        """A config file with a typo. On your own machine the page names the file and the line to fix. In production
        visitors and customers see Stilsmith's own 500 page: the file, its line and the TOML text are for the operator,
        and are in the log."""
        if conf.PRODUCTION:
            app.logger.error("A config file needs fixing (%s %s): %s", request.method, request.path, err)
            return error_page(500)
        return render_template("error.html", title="A config file needs fixing", message=str(err)), 500

    @app.errorhandler(HTTPException)
    def http_error(err: HTTPException):
        if err.code == 405 and owner.hidden_here():    # an owner's page, asked with another method: as if not there
            err = NotFound()
        if request.headers.get("HX-Request") or err.code in (301, 302, 303, 307, 308):
            return err
        if err.code == 413 and request.endpoint == "profile_photo":     # back to the form, not to a dead end
            flash(f"Not saved. {person.TOO_LARGE}", "photo")
            return redirect(url_for("profile_page") + "#photo")
        if err.code == 413 and request.endpoint == "slot_import":
            flash(PAGE_TOO_LARGE, "import")
            return redirect(url_for("slot_page", slot_id=(request.view_args or {}).get("slot_id", "")) + "#add")
        # abort(409, "That outfit changed…") stores its words on the error itself; Werkzeug's sentence for
        # each kind of error lives on the class.
        return error_page(err.code or 500, vars(err).get("description"))

    @app.errorhandler(Exception)
    def unexpected_error(err: Exception):
        app.logger.exception("Unhandled error on %s %s", request.method, request.path)
        return error_page(500)

    @app.get("/healthz")
    def healthz():
        """For the hosting platform: is the app up and can it reach its database?"""
        with db.connect() as con:
            con.execute("SELECT 1").fetchone()
        return {"status": "ok"}

    @app.get("/robots.txt")
    def robots_txt():
        body = "User-agent: *\nDisallow: /slot/\nDisallow: /account\nAllow: /\n"
        return Response(body, mimetype="text/plain")

    @app.get("/favicon.ico")
    def favicon():
        """Browsers and search engines ask for this address by themselves. A 48 px icon, made once from
        static/icon.svg. Its address never changes, so it is kept for a day, not for a year."""
        return send_file(ROOT / "wardrobe" / "static" / "favicon.ico", mimetype="image/x-icon", max_age=86400)

    @app.get("/legal/<name>")
    def legal_page(name: str):
        if name not in LEGAL_PAGES:
            abort(404)
        return render_template("legal.html", name=name, title=LEGAL_PAGES[name])

    def page(template: str, **ctx) -> str:
        ctx.setdefault("w", selection.build())
        return render_template(template, **ctx)

    def fragment(template: str, w: selection.Wardrobe, **ctx) -> str:
        """An HTML fragment for HTMX, plus the refreshed summary bar."""
        extra = render_template("_summary.html", w=w, oob=True)
        if template == "_wardrobe_body.html":   # that page also shows what each price level would cost
            w = w.mine                          # … for his wardrobe, which is what it lists
            extra += "".join(render_template("_level_total.html", w=w, key=key, oob=True) for key in selection.MODES)
            extra += render_template("_level_hint.html", w=w, oob=True)    # the chosen level in words
            ctx.setdefault("example_sizes", profile_mod.sizes_unconfirmed(profile_mod.load()))   # its cards' notes
        return render_template(template, w=w, **ctx) + extra

    def after_slot_change(slot_id: str):
        """Re-render whichever view the button was pressed in. (A choice, a lock or an owned mark
        doesn't stop the profile from rebuilding the plan: the rebuild keeps them.)"""
        w = selection.build()
        if not request.headers.get("HX-Request"):   # plain form post (no JavaScript)
            return redirect(url_for("slot_page", slot_id=slot_id, **way_back()) if request.args.get("view") == "slot"
                            else url_for("wardrobe"))
        if request.args.get("view") == "slot":
            return fragment("_slot_body.html", w, **slot_context(w, slot_id))
        return fragment("_wardrobe_body.html", w)

    def way_back() -> dict:
        """A piece's page opened from an outfit's pop-up ("Compare all 3 options") has ?from=outfit&at=<the
        outfit>&occasion=<its filter> in its address: its way back leads to that outfit, and the Outfits tab stays
        lit. These are those address arguments, checked (an occasion that is not one is left out; "saved", the
        Saved outfits, is kept, as the Outfits page takes it), or {} for a page that is part of the Wardrobe. The
        page's buttons and links carry them, and so does every answer that sends the browser back to the page: any
        button pressed without JavaScript, and adding, completing or removing a product by hand (those forms always
        post plainly)."""
        at = request.args.get("at", "")[:400] if request.args.get("from") == "outfit" else ""
        if not at:
            return {}
        occasion = request.args.get("occasion", "")
        known = occasion in outfits.OCCASIONS or occasion == "saved"
        return {"from": "outfit", "at": at, **({"occasion": occasion} if known else {})}

    def back_to(where: str | None, outfit: str, occasion: str | None, **said) -> str:
        """The page a change to a piece was made from, to go back to it: the outfit it was made in (the pop-up, or
        the outfit's own list of pieces), the Saved outfits, the Wardrobe, the Shopping list, Buy this outfit, or
        the piece's own page ("slot").
        Those are the places that offer a swap for a product sold out in his size (_sold_out.html); the form says
        which in `back`. `said`: what the change did, for the line there with Undo (change_said). Buy this outfit
        needs its outfit to exist still; if the change broke it, the outfits page says so instead."""
        outfit = outfit[:400]
        if where == "slot" and request.view_args and request.view_args.get("slot_id"):
            # The piece's own page (the change was posted to /slot/<id>/...), with its way back to an outfit kept.
            keep: dict = {**({"sort": "score"} if request.args.get("sort") == "score" else {}), **way_back(), **said}
            return url_for("slot_page", slot_id=request.view_args["slot_id"], **keep)
        if where == "wardrobe":
            return url_for("wardrobe", **said)
        if where == "list":
            return url_for("list_page", **said)
        if where == "saved":
            return url_for("outfits_page", occasion="saved", **said)
        if where == "buy" and outfit and outfits.find_by_sig(selection.build(), outfit) is not None:
            return url_for("outfits_buy", at=outfit, **said)
        return url_for("outfits_page", at=outfit or None,
                       occasion=occasion if occasion in outfits.OCCASIONS else None, **said)

    def earlier_option(view: selection.SlotView, cand_id: str) -> dict | None:
        """A product this piece had before a change, by its id: its name and price, if it is one of the piece's
        options now or (in production) a product a lock to it brings back among them (shared.brought_back_by_a_lock:
        Choose lets one go that only its lock kept, see slot_pick). None for any other id."""
        here = next((c for c in view.cands if c.id == cand_id), None)
        if here is not None:
            return {"name": here.data.get("name", ""), "price": here.price}
        product = shared.brought_back_by_a_lock(view.slot, cand_id) if conf.PRODUCTION and cand_id else None
        if product is None:
            return None
        return {"name": product.get("name", ""), "price": selection.usable_price(product.get("price"))}

    def change_said(w: selection.Wardrobe, shown: outfits.Outfit | None, where: str = "") -> dict | None:
        """What a change just made from an outfit did, for the line over the outfits (outfits.html), read from the
        address it led to. Each value is checked against this customer's own wardrobe, and one that does not match is
        left out: such an address can come from anywhere (an old tab, a link). `shown` is the outfit at the address.

        Choose in the pop-up (slot_pick): ?changed=<piece>&was=<product before, or empty>&was_locked=<0|1>: the piece
        now locked to another product than `was`. Said with Undo where `was` and was_locked describe a state it can
        go back to (see slot_restore). The swap offered for a product sold out in his size is the same change, made
        from the Wardrobe, the Shopping list, Buy this outfit and the Saved outfits too: those pages read the same
        address and say the same line (`where`: which of them, so that Undo comes back to it; see back_to).
        'Leave the coat off' and 'Wear the … instead' (_piece.html): ?left=<piece>&back=<outfit> or
        ?instead=<piece>&back=<outfit>: the outfit shown is the one at `back` without that piece, or with another in
        its place. Said with the link back to it."""
        args = request.args
        if args.get("changed"):
            view = w.get(args["changed"])
            was, was_locked = args.get("was", ""), args.get("was_locked")
            if view is None or view.state != "locked" or view.chosen is None or view.chosen.id == was:
                return None             # (after Undo and then Back, say: what the address says changed is undone)
            said = {"kind": "changed", "view": view, "was": was, "was_locked": was_locked, "at": args.get("at", "")[:400],
                    "back": where}
            earlier = earlier_option(view, was) if was else None
            if (was_locked == "1" and earlier) or (was_locked == "0" and (earlier or not was)):
                said["undo"], said["was_price"] = True, earlier["price"] if earlier else None
            return said
        back_sig = args.get("back", "")[:400]
        before = outfits.find_by_sig(w, back_sig) if back_sig else None
        if shown is None or before is None:
            return None
        here, there = shown.slots, before.slots
        left, instead = args.get("left", ""), args.get("instead", "")
        if left and left in there and here == tuple(s for s in there if s != left):
            return {"kind": "left", "piece": w.get(left), "back": back_sig}
        if instead and instead in there and len(here) == len(there):
            i = there.index(instead)
            if here[i] != instead and here[:i] + here[i + 1:] == there[:i] + there[i + 1:]:
                return {"kind": "instead", "piece": w.get(instead), "new": w.get(here[i]), "back": back_sig}
        return None

    def slot_context(w: selection.Wardrobe, slot_id: str) -> dict:
        view = w.get(slot_id)
        if view is None:
            abort(404)
        sort = request.args.get("sort", "price")
        if sort == "score":
            cands = sorted(view.cands, key=lambda c: (c.size.rank, -c.score.total, c.price))
        else:
            sort, cands = "price", view.cands   # already: in your size first (sizes.SizeStatus.rank), then by price
        # `example_sizes`: while the sizes are still the example's, the pick line says "in the example size".
        return {"s": view, "cands": cands, "sort": sort, "way": way_back(),
                "example_sizes": profile_mod.sizes_unconfirmed(profile_mod.load())}

    # ── Wardrobe ──────────────────────────────────────────────────────────────

    def wardrobe_news(w: selection.Wardrobe) -> dict | None:
        """Said once to someone who was a customer before the wardrobe became the outfits he said yes to (db.py,
        version 9), the first time he opens Outfits or Wardrobe: what his wardrobe starts with, counted from what
        it holds now, and that the rest of his plan was not deleted (_news.html). None for everyone else."""
        if not db.get_setting("wardrobe_news"):
            return None
        if request.method == "GET":
            db.set_setting("wardrobe_news", None)
        mine = w.mine
        return {"outfits": w.n_outfits, "kept": sum(1 for view in mine.slots if view.kept and view.state != "owned"),
                "owned": mine.n_owned, "pieces": sum(view.qty for view in mine.slots),
                "rest": sum(view.planned for view in w.slots if not view.mine)}

    def piece_taken_out(w: selection.Wardrobe) -> selection.SlotView | None:
        """After "Take out" on a piece he kept (slot_keep): that piece, for the line with Undo on the Wardrobe
        page. None if the address names a piece that is in his wardrobe (again), or none of his."""
        view = w.get(request.args.get("took", ""))
        return view if view is not None and not view.mine else None

    def spare_said(w: selection.Wardrobe) -> dict | None:
        """After "Add a spare" or "Take the spare out" on a piece's card (slot_spare): the piece, which of the two
        was done and what the spare costs, for the line with Undo on the Wardrobe page. None unless the address
        names a piece of his wardrobe that is as it says (a reload after Undo says nothing)."""
        view, did = w.get(request.args.get("spare", "")), request.args.get("did", "")
        if view is None or not view.mine or view.n_spare < 1 or did not in ("in", "out") or view.spare != (did == "in"):
            return None
        cost = view.chosen.price * view.n_spare if view.chosen and not view.sold_out else 0
        return {"view": view, "did": did, "n": view.n_spare, "cost": cost}

    @app.get("/")
    def wardrobe():
        if conf.PRODUCTION and g.user is None:
            # `real`: a published product list is there (shared.published); without one every customer gets the
            # invented demo products, and the page says so instead of promising real ones from named stores.
            return render_template("landing.html", looks_on=_pictures_on(),      # the public website
                                   photos=_photos_on(), invite=bool(conf.INVITE_CODE), real=shared.published())
        # Once, after a store stopped being offered: which, and how many pieces were picked again (shared.py).
        gone = shared.gone_message(keep=request.method != "GET") if conf.PRODUCTION else ""
        w = selection.build()
        # The page shows his wardrobe (w.mine): the pieces of the outfits he said yes to, what he owns, what he kept.
        return page("wardrobe.html", w=w.mine, tab="wardrobe", gone=gone, said=change_said(w, None, "wardrobe"),
                    n_plan=sum(view.planned for view in w.slots), news=wardrobe_news(w), taken=piece_taken_out(w),
                    spared=spare_said(w),
                    example_sizes=profile_mod.sizes_unconfirmed(profile_mod.load()))   # "in the example size"

    @app.post("/settings")
    def settings():
        mode = request.form.get("mode")
        if mode == "good":              # the old name for "cheapest, with a minimum quality"
            mode = "cheapest"
        if mode in selection.MODES:
            db.set_setting("mode", mode)
        db.set_setting("levels", True)  # this choice was made on the price levels (see selection._controls)
        try:
            threshold = int(float(request.form.get("threshold", "")))
            db.set_setting("threshold", max(0, min(100, threshold)))
        except ValueError:
            pass
        w = selection.build()
        if not request.headers.get("HX-Request"):
            return redirect(url_for("wardrobe"))
        return fragment("_wardrobe_body.html", w)

    # ── One slot: candidates, swap, lock, own ─────────────────────────────────

    @app.get("/slot/<slot_id>")
    def slot_page(slot_id: str):
        w = selection.build()
        # Opened from an outfit's pop-up: its way back leads to that outfit (see way_back). Otherwise it is part of
        # the Wardrobe.
        way = way_back()
        back = url_for("outfits_page", at=way["at"], occasion=way.get("occasion")) if way else ""
        # After the swap for a product sold out in his size, made here: what changed, with Undo (change_said).
        return page("slot.html", w=w, tab="outfits" if back else "wardrobe", back=back,
                    said=change_said(w, None, "slot") if request.args.get("changed") == slot_id else None,
                    **slot_context(w, slot_id))

    @app.post("/slot/<slot_id>/pick")
    def slot_pick(slot_id: str):
        view = selection.build().get(slot_id)
        cand_id = request.form.get("candidate", "")
        wanted = next((c for c in view.cands if c.id == cand_id), None) if view else None
        if view is None or wanted is None:
            abort(404)
        if wanted.price <= 0:           # an item without a price would silently make the wardrobe cheaper
            abort(409, "That item has no price yet. Add its price on the piece's page first.")
        before = next((c for c in view.cands if c.id == view.slot["pick"]), None) if view.slot["locked"] else None
        # Choosing by hand locks the choice, so the price level can't undo it.
        db.update_slot(slot_id, pick=cand_id, locked=True, owned=False)
        if conf.PRODUCTION and before and before.id != cand_id and shared.kept_for_its_lock(view.slot, before.data):
            sync_catalog()      # the product it was locked to, in a colour he refused since, was kept only for that
        where = request.form.get("back")
        if request.form.get("outfit") or where in ("wardrobe", "list", "saved", "slot"):
            # Swapped from inside an outfit: back to it, now with the new piece. Or the swap for a product sold out
            # in his size, from the page that offered it (back_to). Either way the address carries
            # what was there before, so that the page says what changed and can undo it (change_said). The
            # pop-up's form says what it showed; a form without it (an older pop-up) gets the piece as it was here.
            was, was_locked = request.form.get("was"), request.form.get("was_locked")
            if was is None or was_locked not in ("0", "1"):
                was = view.chosen.id if view.chosen and view.state != "owned" else ""
                was_locked = "1" if view.state == "locked" else "0"
            return redirect(back_to(where, request.form.get("outfit", ""), request.form.get("occasion"),
                                    changed=slot_id, was=was[:200], was_locked=was_locked))
        return after_slot_change(slot_id)

    @app.post("/slot/<slot_id>/restore")
    def slot_restore(slot_id: str):
        """'Undo' on the line that says what Choose changed (outfits.html): the piece's earlier product and lock state
        again, or automatic again when it was not locked. Back to the same outfit, with a line saying so. A product
        that was kept among the piece's options only for its lock went when another was chosen (slot_pick): the
        lock put back brings it back. One that is no longer in the product list at all cannot be put back: said."""
        view = selection.build().get(slot_id)
        was, locked = request.form.get("was", ""), request.form.get("was_locked")
        if view is None or locked not in ("0", "1"):
            abort(404)
        outfit = request.form.get("outfit", "")[:400]
        occasion = request.form.get("occasion", "")
        where = request.form.get("back")
        back = back_to(where, outfit, occasion)
        earlier = earlier_option(view, was) if locked == "1" else None
        if locked == "1" and earlier is None:
            flash(f"The product your {view.slot['name'].lower()} had before is no longer in {conf.SITE_NAME}'s product "
                  "list, so it can't be put back.")
            return redirect(back)
        if earlier is not None and earlier["price"] <= 0:     # as Choose refuses it (slot_pick), said on the outfit
            said = Markup("The product your %s had before has no price now, so it can't be put back.") % (
                view.slot["name"].lower())
            if any(c.id == was for c in view.cands):       # its price can be added on the piece's page, where it is
                way: dict = {"from": "outfit", "at": outfit, **({"occasion": occasion} if occasion in outfits.OCCASIONS
                                                                 else {})} if outfit else {}     # (as way_back reads it)
                said += Markup(' <a href="%s">Add its price</a>') % url_for(
                    "slot_page", slot_id=slot_id, _anchor=f"cand-{was}", **way)
            flash(said, "said")
            return redirect(back)
        if locked == "1":
            db.update_slot(slot_id, pick=was, locked=True)
        else:
            db.update_slot(slot_id, pick=None, locked=False)        # automatic again
        # The options again as they should be: with the product put back if a lock alone keeps it, and without one
        # that only the lock just undone kept (as Choose and Unlock do).
        brought_back = locked == "1" and all(c.id != was for c in view.cands)
        letting_go = [c.data for c in view.cands if not (locked == "1" and c.id == was)]
        if conf.PRODUCTION and (brought_back or shared.kept_for_its_lock(view.slot, *letting_go)):
            sync_catalog()
        now = selection.build().get(slot_id)
        if where == "buy":      # worked out before the change: is that outfit still one, with the product put back?
            back = back_to(where, outfit, occasion)
        if now is not None and now.chosen is not None:     # "Indigo jeans: back to …" (the look: app.css .said)
            flash(Markup('%s: back to <span lang="de">%s</span>, %s, in all your outfits.%s') % (
                view.slot["name"], now.chosen.data.get("name", ""), eur(now.chosen.price),
                "" if locked == "1" else " The price level picks this piece again."), "said")
        return redirect(back)

    @app.post("/slot/<slot_id>/lock")
    def slot_lock(slot_id: str):
        view = selection.build().get(slot_id)
        if view is None:
            abort(404)
        if view.slot["locked"]:
            db.update_slot(slot_id, locked=False, pick=None)       # back to automatic
            # Any option kept only for a lock, in a colour he refused since, goes with it: the product it is locked
            # to, or one it was locked to before he chose another (as choosing did before it rebuilt, see slot_pick).
            if conf.PRODUCTION and shared.kept_for_its_lock(view.slot, *(c.data for c in view.cands)):
                sync_catalog()
        elif view.chosen is not None:
            db.update_slot(slot_id, locked=True, pick=view.chosen.id)  # freeze what's showing
        return after_slot_change(slot_id)

    @app.post("/slot/<slot_id>/own")
    def slot_own(slot_id: str):
        slot = db.get_slot(slot_id)
        if slot is None:
            abort(404)
        # Taken back, "Owned" returns the piece to where it was. A piece that was not in his wardrobe when he said he
        # owns it (yes.owned_from_outside) leaves it again. One that was (an outfit of his wears it, he kept it, or
        # it is from before this was remembered) stays, now to buy, so it does not vanish from the page under his
        # finger; "Take out" on its card removes it.
        if slot["owned"]:
            view = selection.build().get(slot_id)
            if yes.owned_from_outside(slot_id):
                yes.remember_outside(slot_id, False)
            elif view is not None and not view.outfits_in:
                yes.keep(slot_id, True)
        else:
            view = selection.build().get(slot_id)
            yes.remember_outside(slot_id, view is not None and not view.mine)
        db.update_slot(slot_id, owned=not slot["owned"])
        return after_slot_change(slot_id)

    @app.post("/slot/<slot_id>/keep")
    def slot_keep(slot_id: str):
        """'Take out' on the Wardrobe card of a piece that is in his wardrobe on its own account (he chose it by
        hand before the wardrobe was the outfits he said yes to) and in no outfit of his: it leaves the wardrobe,
        and stays a piece outfits are made from, with the product he chose. The page says so, with Undo (want=in)."""
        view = selection.build().get(slot_id)
        if view is None:
            abort(404)
        if request.form.get("want") == "in":
            yes.keep(slot_id, True)
            if request.form.get("spare") == "1" and view.n_spare:    # it had its spare with it: that comes back too
                yes.spare(slot_id, True)
            return redirect(url_for("wardrobe") + f"#card-{slot_id}")
        if view.outfits_in or view.state == "owned":
            abort(409, "That piece is in one of your outfits, or you own it, so it stays in your wardrobe.")
        yes.keep(slot_id, False)
        yes.spare(slot_id, False)       # a spare is in his wardrobe only beside the piece itself
        return redirect(url_for("wardrobe", took=slot_id, with_spare="1" if view.qty > 1 else None))

    @app.post("/slot/<slot_id>/spare")
    def slot_spare(slot_id: str):
        """'Add a spare' on the Wardrobe card of a piece the plan has more than one of (two white tees). An outfit
        wears one, and a yes adds that one; this adds the other to his wardrobe, his total and his shopping list,
        counted and said as a spare. 'Take the spare out' (want=out) takes it out again. The page says what was
        done and what it costs, with Undo."""
        view = selection.build().get(slot_id)
        if view is None:
            abort(404)
        if request.form.get("want") == "out":
            yes.spare(slot_id, False)
            return redirect(url_for("wardrobe", spare=slot_id, did="out"))
        if not view.mine or view.n_spare < 1:
            abort(409, "That piece has no spare to add: it is not in your wardrobe, you own it, or your plan has "
                       "only one of it.")
        yes.spare(slot_id, True)
        return redirect(url_for("wardrobe", spare=slot_id, did="in"))

    @app.post("/slot/<slot_id>/colour")
    def slot_colour(slot_id: str):
        """'Use navy' on a piece the product list has nothing for: the piece takes one of the colours
        offered with it (selection._offer), its name follows, and its products are matched again. Like
        Choose or Lock it is a choice made on the Wardrobe, not an edit of the plan: a later profile
        change still rebuilds the plan (see plan_edited)."""
        view = selection.build().get(slot_id)
        if view is None:
            abort(404)
        colour = request.form.get("colour", "")
        if colour not in {c.key for c in view.offers}:     # never a refused colour, nor one that fills nothing
            abort(409, "That colour is not offered for this piece any more. Reload the page.")
        name = recoloured_name(view.slot["name"], view.slot["colour"], colour)
        # An account from before plan_edited has its answer worked out by comparing the plan with the profile's
        # own: worked out now, while they still match, as this piece's new colour would make them differ.
        plan_edited(profile_mod.load())
        db.update_slot(slot_id, colour=colour, name=name, locked=False, pick=None)
        sync_catalog(changed_slot=slot_id)
        w = selection.build()
        on_its_page = request.args.get("view") == "slot"
        if not request.headers.get("HX-Request"):          # plain form post (no JavaScript)
            return redirect(url_for("slot_page", slot_id=slot_id, **way_back()) if on_its_page
                            else url_for("wardrobe") + f"#card-{slot_id}")
        # The button that was pressed is gone from the new view, so keyboard focus moves to the piece itself.
        if on_its_page:     # that page is named after the piece: HTMX takes the <title> into the tab
            title = Markup("<title>%s · %s</title>") % (name, conf.SITE_NAME)
            return str(title) + fragment("_slot_body.html", w, focus=slot_id, **slot_context(w, slot_id))
        return fragment("_wardrobe_body.html", w, focus=slot_id)

    # ── Adding and completing candidates by hand ──────────────────────────────

    @app.post("/slot/<slot_id>/import")
    def slot_import(slot_id: str):
        """Manual import: pasted product links become candidates (see collect/manual.py). What each link came to
        is said inside the "Add a product by link" section the page comes back to (#add), not at the top of the
        page, far above it: those messages have their own kind, "import" (slot.html, base.html).
        A link whose name holds a word such as "kids" or "damen" is not added yet: the page asks "Add it anyway?"
        with a button that sends that link again with anyway=1 (_slot_body.html)."""
        from .collect import manual

        slot = db.get_slot(slot_id)
        if slot is None:
            abort(404)
        links = [u for u in re.split(r"\s+", request.form.get("urls", "")) if u][:8]
        if not links:
            flash("Paste at least one product link.", "import")
            return redirect(url_for("slot_page", slot_id=slot_id, **way_back()) + "#add")
        # No browser is ever opened: only what the link itself says is taken, and, with one link, what the product's
        # page says as the customer saved it from his own browser and sent along (read as text, never shown).
        upload = request.files.get("page")
        raw = upload.read(SAVED_PAGE + 1) if upload else b""
        if len(raw) > SAVED_PAGE:
            flash(PAGE_TOO_LARGE, "import")
            return redirect(url_for("slot_page", slot_id=slot_id, **way_back()) + "#add")
        results = manual.from_urls(links, slot, raw.decode("utf-8", errors="replace") if raw else None,
                                   anyway=request.form.get("anyway") == "1")
        # "Add it anyway" on one of several links asked about: the others come along, to be asked again.
        still = [u for u in request.form.getlist("still") if u and u not in links][:8]
        if still:
            results += manual.from_urls(still, slot, None)

        def add(cat: dict) -> None:
            for _, cand, _ in results:
                if cand:
                    cat["candidates"] = [c for c in cat["candidates"]
                                         if not (c.get("slot_id") == slot_id and c.get("id") == cand["id"])]
                    cat["candidates"].append(cand)
        catalog.update(add)
        for link, cand, note in results:
            shown = link if len(link) <= 80 else link[:79] + "…"
            if isinstance(note, manual.Question):
                # Not added yet: asked. The message carries the whole link too, for the form of its button
                # (Flask keeps a message of any plain kind, not only words).
                flash({"asks": f"“{shown}” {note}", "link": link}, "import")    # type: ignore[arg-type]
                continue
            flash(f"Added “{cand['name']}”: {note}." if cand else f"Not added: “{shown}” {note}.", "import")
        return redirect(url_for("slot_page", slot_id=slot_id, **way_back()) + "#add")

    @app.post("/slot/<slot_id>/details")
    def slot_details(slot_id: str):
        """Fill in what a store page didn't give: fabric, sizes in stock, price."""
        form = request.form
        cand_id = form.get("candidate", "")
        if catalog.find(catalog.load(), slot_id, cand_id) is None:
            abort(404)
        typed: dict = {}
        problems = 0
        fabric = " ".join(form.get("composition", "").split())
        if fabric:
            if composition.parse(fabric):
                typed["composition_text"] = fabric
            else:
                problems += 1
                flash(f"Couldn't read the fabric “{fabric[:60]}”: write it as the label does, like “80% Wolle, "
                      f"20% Polyamid”.")
        sizes_given = [s for s in re.split(r"[,;\s]+", form.get("sizes", "").strip()) if s]
        price_text = form.get("price", "").replace("€", "").replace(",", ".").strip()
        try:
            price = round(float(price_text), 2) if price_text else None
            if price is not None and not (math.isfinite(price) and 0 < price <= 100_000):
                raise ValueError
        except (ValueError, OverflowError):
            price = None
            problems += 1
            flash(f"“{form.get('price', '')[:20]}” isn't a price.")

        def change(cat: dict) -> None:
            cand = catalog.find(cat, slot_id, cand_id)
            if cand is None:
                return
            if sizes_given:
                typed["sizes_in_stock"] = sizes_given
                if not cand.get("sizes_all"):      # the store gave no size list: yours is the list
                    typed["sizes_all"] = sizes_given
            if price is not None and price > 0:
                typed["price"] = price
            if typed:
                cand["manual"] = {**(cand.get("manual") or {}), **typed}
            if form.get("clear") == "1":
                cand.pop("manual", None)
        catalog.update(change)
        # Said only of what was saved: after "“cheap” isn't a price." a bare "Details saved." would be untrue.
        saved = [word for key, word in (("composition_text", "fabric"), ("sizes_in_stock", "sizes"), ("price", "price"))
                 if key in typed]
        if form.get("clear") == "1":
            flash("Details cleared.")
        elif saved and not problems:
            flash("Details saved.")
        elif saved:                                         # "Saved the sizes." / "Saved the fabric and sizes."
            flash("Saved the " + (", ".join(saved[:-1]) + " and " if len(saved) > 1 else "") + saved[-1] + ".")
        elif not problems:
            flash("Nothing to save yet: type the fabric, the sizes in stock or the price.")
        return redirect(url_for("slot_page", slot_id=slot_id, sort=request.args.get("sort", "price"), **way_back()))

    @app.post("/slot/<slot_id>/remove")
    def slot_remove(slot_id: str):
        """Remove a candidate you added by hand: one of the piece's options, or one set aside because its store is no
        longer offered (catalog.set_aside, listed on the piece's page)."""
        cand_id = request.form.get("candidate", "")
        cand = catalog.find(catalog.stored(), slot_id, cand_id)
        if cand is None or cand.get("source") != "manual":
            abort(404)
        slot = db.get_slot(slot_id)
        if slot and slot["pick"] == cand_id:
            db.update_slot(slot_id, locked=False, pick=None)
        catalog.update(lambda cat: cat.__setitem__("candidates", [
            c for c in cat["candidates"] if not (c.get("slot_id") == slot_id and c.get("id") == cand_id)]))
        # One set aside was never among the piece's options: "Removed “Basic T-Shirt”."
        where = " from this piece's options" if programmes.is_offered(cand.get("store")) else ""
        flash(f"Removed “{cand['name']}”{where}.")
        return redirect(url_for("slot_page", slot_id=slot_id, **way_back()))

    # ── Outfits ───────────────────────────────────────────────────────────────

    def usual_occasion() -> str:
        """The outfits the page opens on when its address names no occasion: what he dresses for (Profile)."""
        use = profile_mod.load()["use"]
        return "all" if use == "both" else use

    def place(source) -> tuple[int, int]:
        """Which row of outfits: how many it holds and which shuffle it is. Read from the page's address, or from a
        form under an outfit, which carries both so that an answer comes back to the row it was given in."""
        try:
            return max(4, min(60, int(source.get("n", 12)))), int(source.get("seed", 0))
        except ValueError:
            return 12, 0

    def front_of(source) -> list[str]:
        """The outfits that keep their places at the head of the row: the ones that stood in front of an outfit he
        said yes to (their keys, joined by dots under "front" in the page's address and in the forms under an
        outfit; outfits.generate). None for a row he has not said yes in."""
        return [key for key in str(source.get("front", "")).split(".") if re.fullmatch(r"[0-9a-f]{12}", key)][:60]

    def shown_number(source) -> int:
        """The number the page showed over the outfit answered ("3 / 13"), which both answers' forms carry
        (outfits.html, shown_at): the message after the answer names the outfit by it (yes.answered). 0 for a form
        without it."""
        value = str(source.get("shown", ""))
        return int(value) if re.fullmatch(r"[1-9][0-9]{0,2}", value) else 0

    def same_row(source, front: list[str] | None = None) -> dict:
        """`place` and `front_of` as address arguments, to go back to that row (none for the row every visit starts
        with). `front`: the outfits that now stay in front, when that has just changed (a yes)."""
        n, seed = place(source)
        front = front_of(source) if front is None else front
        return {"n": n if n != 12 else None, "seed": seed or None, "front": ".".join(front) or None}

    def offered_row(w: selection.Wardrobe, occasion: str, source,
                    front: list[str]) -> tuple[list[outfits.Outfit], int, int, int, outfits.Outfit | None]:
        """The outfits on offer, as the page shows them: (those outfits in order, how many there are in all, how many
        he said no to, how many stand in front, kept there after a yes (`front`), and the one asked for by its address).
        The outfit asked for ("at", after a swap or "wear something else here") is shown right behind those kept in
        front, and counted where it is not among those on offer. A page that shows one says so in the forms under its
        outfits (outfits.html, row_fields), and the answers given there (outfits_save, outfits_no) work the row out
        here as the page did: the outfits that stood in front of the one answered, that one among them, stay in front
        after it, and the outfit that follows takes its number, as everywhere."""
        n, seed = place(source)
        chosen, total, n_declined = yes.offer(w, occasion, n, seed, front)
        held = next((i for i, o in enumerate(chosen) if o.key not in front), len(chosen)) if front else 0
        at = str(source.get("at", ""))[:400]
        first = outfits.find_by_sig(w, at) if at else None
        if first is not None:
            if not first.suits(occasion) or first.sig in db.yes_sigs() or first.sig in db.declined_sigs():
                total += 1              # shown although it is not among those on offer: count it
            if first.key not in {o.key for o in chosen[:held]}:     # (first of those behind the ones in front)
                chosen = chosen[:held] + [first] + [o for o in chosen[held:] if o.key != first.key]
        return chosen, total, n_declined, held, first

    @app.get("/outfits")
    def outfits_page():
        w = selection.build()
        occasion = request.args.get("occasion") or usual_occasion()
        if occasion not in outfits.OCCASIONS and occasion != "saved":
            occasion = "all"
        n, seed = place(request.args)
        front, held = front_of(request.args), 0
        rows = db.list_saved()      # the outfits he said yes to
        saved = {fav["key"] for fav in rows}
        yes_sigs = {fav["sig"] for fav in rows if fav["sig"]}
        said = None             # what a change just made from an outfit did (change_said)
        n_declined = 0
        first = None            # the outfit asked for by the address, shown out of the row's order (offered_row)

        # The outfit just taken out of the wardrobe (outfits_save): said with Undo, and which pieces went with it.
        removed = None
        kept = db.get_setting("removed_outfit")
        if kept and kept["key"] == request.args.get("removed") and kept["key"] not in saved:
            removed = kept
        # The answer just given to an outfit, said with Undo: a yes (?added=<its key>) or a no (?declined=<its sig>).
        answer = None
        last = db.get_setting("last_answer") or {}
        if last.get("kind") == "yes" and last.get("key") == request.args.get("added") and last["key"] in saved:
            answer = last
        elif last.get("kind") == "no" and last.get("sig") == request.args.get("declined") \
                and last["sig"] in db.declined_sigs():
            answer = last
        if occasion == "saved":
            now_picked = {s.slot["id"]: (s.chosen.id if s.chosen and s.state != "owned" else None) for s in w.slots}
            boards = []
            for fav in rows:
                as_saved = [dict(piece) for piece in outfits.with_roles(fav["pieces"])]
                for piece in fav["pieces"]:   # has the wardrobe moved on since this was saved?
                    # A piece he has since removed from his plan (the plan page) is in no total and on no list:
                    # the outfit says so by name, and why it can no longer be bought as one.
                    piece["unplanned"] = piece["slot_id"] not in now_picked
                    piece["changed"] = (not piece["owned"] and not piece["unplanned"]
                                        and now_picked.get(piece["slot_id"]) != piece["cand_id"])
                    if not piece["owned"] and piece.get("store") and not programmes.is_offered(piece["store"]):
                        outfits.no_longer_offered(piece)
                same_today = outfits.find(w, fav["key"])       # still one of today's outfits, product for product
                # The same pieces as today's products make them: where "Buy this outfit" and "See it today" lead.
                live = outfits.find_by_sig(w, fav["sig"]) if fav["sig"] else None
                boards.append({"key": fav["key"], "sig": "", "label": fav["label"],
                               "pieces": outfits.with_roles(fav["pieces"]),
                               # Its picture is the one "See it worn" would draw: of today's pieces if it still exists,
                               # else of the pieces as they were saved (also where a store has gone since).
                               "look_pieces": outfits.snapshot(same_today) if same_today else as_saved,
                               "cost": round(sum(p["price"] for p in fav["pieces"]), 2),
                               "yes_sig": fav["sig"], "live": live.sig if live else "",
                               "unplanned": [p["slot_name"] for p in fav["pieces"] if p["unplanned"]],
                               "saved": True, "saved_at": catalog.collected_label({"collected_at": fav["saved_at"]})})
            total = len(boards)
            said = change_said(w, None, "saved")       # the swap for a sold-out product, made under Saved
        else:
            # The outfits he has not answered yet; those that wear pieces he already has come first (yes.offer).
            # After a yes, the outfits that stood in front of that one are still in front (front_of): `held` of them.
            # One particular combination asked for by the address ("at": after a swap, or "wear something else
            # here") is shown first of those behind them (offered_row).
            chosen, total, n_declined, held, first = offered_row(w, occasion, request.args, front)
            if request.args.get("at") and first is None:
                flash("With that change the combination no longer passes the outfit rules, "
                      "so it is not shown. These do.")
            said = change_said(w, first)
            boards = [{"key": o.key, "sig": o.sig, "label": o.label, "pieces": outfits.snapshot(o), "cost": o.cost,
                       "saved": o.sig in yes_sigs, "yes_sig": o.sig, "adds": yes.adds(w, o, yes_sigs)}
                      for o in chosen]
            if w.brief:         # with a style brief, an outfit that fits it says why in one line (style.why)
                for board, outfit in zip(boards, chosen):
                    board["why"] = style.why(board["pieces"], outfit.level, w.brief)
        # A small picture tapped without JavaScript (outfits_look): that outfit shows that picture large.
        for board in boards:
            if board["key"] == request.args.get("shot_of"):
                board["shot"] = looks.shot_named(request.args.get("shot"))
            # Asked for without JavaScript where a question comes first ("Draw again" on a front picture with
            # other photos; a photo made from the picture of him, see looks.needs_ok): that outfit asks it.
            board["ask"] = request.args.get("ask", "")[:40] if board["key"] == request.args.get("ask_of") else ""
        looks_on = looks.attach(boards)     # the AI picture of each outfit, if that is switched on
        if not looks.more_for_anyone():     # "More photos" and "See it move": on the outfits he said yes to
            g.more_offered = {board["key"]: bool(board["saved"]) for board in boards}
        for board in boards:
            # The question about the picture of him is only asked of a customer it is true for: not again once he
            # has said yes (the page reloaded, the address opened again).
            if board["ask"].startswith(("more", "send")) and not (
                    looks_on and looks.needs_ok(board.get("look_pieces") or board["pieces"])):
                board["ask"] = ""
        videos_on = looks_on and videos.attach(boards)      # … and its video, "See it move" (videos.py)
        return page("outfits.html", w=w, tab="outfits", boards=boards, total=total, n_saved=len(saved), removed=removed,
                    answer=answer, n_declined=n_declined, news=wardrobe_news(w),
                    reusing=bool(yes_sigs) and any(b.get("adds") and b["adds"].have and not b["adds"].in_wardrobe
                                                   for b in boards[held:]) and len(boards) - held > 1,
                    occasion=occasion, n=n, seed=seed, next_seed=random.randrange(1, 1_000_000),
                    shown_first=first.sig if first else "",     # said in every form under an outfit (row_fields)
                    front=front, held=held,     # the outfits kept in front after a yes, and how many of them show
                    # Pieces whose chosen product is sold out in his size: said under the piece, with the swap.
                    sold={s.slot["id"]: s for s in w.slots if s.sold_out},
                    looks_on=looks_on, videos_on=videos_on, turn_seconds=(videos.rules() or {}).get("turn_seconds", 6),
                    said=said,      # what a change just made from an outfit did, over the outfits (change_said)
                    auto=looks_on and looks.load_rules()["pictures"]["auto"] and not looks.held_off())

    @app.get("/outfits/piece")
    def outfits_piece():
        """The pop-up for one piece of an outfit: what it is, and what could take its place."""
        w = selection.build()
        outfit = outfits.find_by_sig(w, request.args.get("at", ""))
        slot_id = request.args.get("slot", "")
        view = w.get(slot_id)
        if outfit is None or view is None or slot_id not in outfit.slots:
            abort(409, "That outfit changed in the meantime — reload the page.")
        swaps, without = outfits.alternatives(w, outfit, slot_id)
        every = outfits.all_outfits(w)
        worn = sum(1 for o in every if slot_id in o.slots)
        others = [] if view.state == "owned" else [c for c in view.cands
                                                   if not (view.chosen and c.id == view.chosen.id)]
        occasion = request.args.get("occasion", "")
        return render_template("_piece.html", w=w, s=view, sig=outfit.sig, others=others[:6], n_others=len(others),
                               swaps=swaps, without=without, worn=worn, n_outfits=len(every),
                               occasion=occasion if occasion in outfits.OCCASIONS else "",
                               example_sizes=profile_mod.sizes_unconfirmed(profile_mod.load()))

    @app.get("/outfits/buy")
    def outfits_buy():
        """Everything in one outfit as a list to buy from, store by store."""
        w = selection.build()
        outfit = outfits.find_by_sig(w, request.args.get("at", ""))
        if outfit is None:
            abort(404)
        return page("buy.html", w=w, tab="outfits", outfit=outfit, sl=export.build(w, only=outfit.slots),
                    adds=yes.adds(w, outfit),       # whether it is in his wardrobe yet, and what it would add
                    said=change_said(w, outfit, "buy"), **your_sizes())

    # ── AI pictures of outfits (looks.py) ─────────────────────────────────────

    def shot_shown(outfit_key: str, shot: str, ask: str = "") -> str:
        """Where a picture asked for without JavaScript leads: back to the outfits page it was asked from (its
        occasion, its outfits), with that outfit in view (#outfit-<key>) showing the picture that was asked for
        (shot=, shot_of=; nothing for the front picture). So a tap on Street shows the street, not the front again.
        `ask`: what the page asks under that outfit's picture before anything is drawn (ask=, ask_of=; the
        questions are in _look_ask.html)."""
        back = urlsplit(request.referrer or "")
        same = back.path == url_for("outfits_page") and back.netloc in ("", request.host)
        args = {name: value for name, value in parse_qsl(back.query)
                if same and name not in ("shot", "shot_of", "ask", "ask_of")}
        if shot != looks.FRONT:
            args.update(shot=shot, shot_of=outfit_key)
        if ask:
            args.update(ask=ask, ask_of=outfit_key)
        return url_for("outfits_page") + (f"?{urlencode(args)}" if args else "") + f"#outfit-{outfit_key}"

    def more_offered(outfit_key: str) -> bool:
        """Whether "More photos" and "See it move" are offered on this outfit (config/looks.toml, more_only_on_yes):
        on an outfit he said yes to (in his wardrobe, under My outfits: by its key, or today's outfit with the same
        pieces, as the outfits page marks it), and on every outfit for whoever looks.more_for_anyone lets (the
        switch off, your own machine, owners and Pro accounts). The routes that start them ask this too, so a page
        from before is refused, not just hidden. Worked out once per outfit per request (g.more_offered)."""
        known = g.setdefault("more_offered", {})
        if outfit_key not in known:
            if looks.more_for_anyone():
                known[outfit_key] = True
            elif not outfit_key:
                known[outfit_key] = False
            elif outfit_key in db.saved_keys():
                known[outfit_key] = True
            else:
                outfit = outfits.find(selection.build(), outfit_key)
                known[outfit_key] = bool(outfit and outfit.sig in set(db.yes_sigs()))
        return known[outfit_key]

    app.jinja_env.globals["more_offered"] = more_offered
    app.jinja_env.globals.update(NOT_YET_SHORT=looks.NOT_YET_SHORT, NOT_YET_NO_VIDEO=looks.NOT_YET_NO_VIDEO,
                                 videos_shown=lambda: videos.service() is not None)

    def pieces_of(outfit_key: str) -> list[dict] | None:
        """The pieces of one of today's outfits or of a saved one, as its pictures describe them; None if it is gone."""
        outfit = outfits.find(selection.build(), outfit_key)
        if outfit:
            return outfits.snapshot(outfit)
        return next((fav["pieces"] for fav in db.list_saved() if fav["key"] == outfit_key), None)

    def look_fragment(outfit_key: str, photos: list[looks.Photo], shot: str, said: str = "") -> str:
        """The picture box of one outfit: the picture `shot` large (the front one if there is nothing of it to
        show), and the row of the outfit's small pictures under it. `said`: a refusal said under that row, once."""
        large = looks.shown(photos, shot)
        return render_template("_look.html", key=outfit_key, look=large.look, shot=large.name, photos=photos,
                               shots_said=said,
                               auto=looks.load_rules()["pictures"]["auto"] and not looks.held_off(),
                               videos_on=videos.service() is not None, video=videos.of(large.look, large.name),
                               clip=videos.clip_of(large.name),
                               turn_seconds=(videos.rules() or {}).get("turn_seconds", 6))

    def photos_said(outfit_key: str, said: str | None = None) -> str:
        """Why "More photos" did not draw every picture of an outfit (the day's pictures ran out part-way, the
        service is being left alone): kept with the customer's session, so that the row of small pictures goes on
        saying it, through its own questions "are they done?" and a reload, until he taps OK (or taps "More photos"
        again and all are drawn). `said`: the reason to keep now; "" forgets it. Returns what is kept."""
        kept = dict(session.get("photos_said") or {})
        if said is not None:
            kept.pop(outfit_key, None)
            if said:
                kept = {**dict(list(kept.items())[-4:]), outfit_key: said[:300]}      # a handful at most
            session["photos_said"] = kept
        return kept.get(outfit_key, "")

    app.jinja_env.globals["photos_said"] = photos_said
    app.jinja_env.globals["redraw_words"] = looks.redraw_words

    def picture_service() -> str:
        """The image service, as a sentence names it to the customer: "Google" (as `drawn_by` on Profile)."""
        chosen = looks.service()
        return chosen.label if chosen else "the AI service"

    app.jinja_env.globals["picture_service"] = picture_service

    def shots_fragment(outfit_key: str, photos: list[looks.Photo], shot: str, said: str = "") -> str:
        """Only the row of small pictures (it is swapped on its own while pictures arrive, so the large picture
        stays as it is). `said`: why "More photos" did not start all of them."""
        large = looks.shown(photos, shot)
        return render_template("_shots.html", key=outfit_key, look=large.look, shot=large.name, photos=photos,
                               said=said)

    @app.post("/outfits/look")
    def outfits_look():
        """Ask for a picture of an outfit: its front picture, one of the others (shot=, a small picture tapped),
        all of the others ("More photos", more=1), or a new version of one (again=1). Two things are asked about
        first, under the picture (ask_first): drawing a front picture again that other photos were made from, and
        making a photo from the AI picture of a customer who has not yet agreed to that (looks.needs_ok)."""
        key = request.form.get("key", "")
        pieces = pieces_of(key)
        if pieces is None:
            abort(409, "That outfit no longer exists — reload the page.")
        by_htmx = bool(request.headers.get("HX-Request"))
        # A question's own place under the picture (_look.html): only that is answered, so the picture stays put.
        question_only = {"HX-Retarget": f"#ask-at-{key}", "HX-Reswap": "innerHTML"}

        def ask_first(what: str, staying: str):
            """Nothing is drawn yet: the page asks first, under the outfit's picture (_look_ask.html), and the
            answer yes sends the same request again with it (sure=1, agree=1). Asked here, at the tap, so it is
            right however the page came to be as it is (photos that arrived a moment ago, without a reload), and
            without JavaScript too: then the outfits page comes back with the question (shot_shown).
            `what`: "again", "more" or "send:<picture>"; `staying`: the picture shown large meanwhile."""
            if not by_htmx:
                return redirect(shot_shown(key, staying, ask=what))
            return render_template("_look_ask.html", key=key, ask=what, shot=staying,
                                   photos=looks.gallery(pieces) or []), 200, question_only

        if request.form.get("keep") == "1":
            # "Keep them" or "Not now" under a question: the question goes, nothing else changes.
            if not by_htmx:
                return redirect(shot_shown(key, looks.shot_named(request.form.get("shown"))))
            return "", 200, question_only
        agreed = request.form.get("agree") == "1"       # "Yes" under the question about the picture of him
        if request.form.get("more") == "1":
            # "More photos": the pictures after the front one are started, each one picture of the day's allowance.
            # The picture shown large stays; only the row of small pictures is answered.
            if looks.service() is None:
                abort(404)
            staying = looks.shot_named(request.form.get("shown"))
            if not more_offered(key):
                # Not on an outfit he has not said yes to (a page from before, or a request made by hand): nothing
                # is drawn and no picture of the day is taken. Why is said under the row, this once (not kept with
                # photos_said: after a yes it would no longer be true).
                if not by_htmx:
                    flash(looks.NOT_YET)
                    return redirect(shot_shown(key, staying))
                return shots_fragment(key, looks.gallery(pieces) or [], staying, looks.NOT_YET)
            if looks.needs_ok(pieces):
                # They are made from the AI picture of him, which goes to the image service again. He added his
                # photo before its words said so: he is asked once, and his yes is kept.
                if not agreed:
                    return ask_first("more", staying)
                looks.agree_to_sending_again()
            said = photos_said(key, looks.request_more(pieces))     # kept, and said under the row until he taps OK
            if not by_htmx:
                return redirect(shot_shown(key, staying))
            row = shots_fragment(key, looks.gallery(pieces) or [], staying, said)
            if agreed:                  # sent from the question, which goes now that it is answered
                row += str(Markup('<div class="look-ask-at" id="ask-at-%s" hx-swap-oob="true"></div>') % key)
            return row
        if request.form.get("read") == "1":
            # "OK" beside why "More photos" did not draw every picture: the reason is read, and goes.
            photos_said(key, "")
            staying = looks.shot_named(request.form.get("shown"))
            if not by_htmx:
                return redirect(shot_shown(key, staying))
            return shots_fragment(key, looks.gallery(pieces) or [], staying)
        shot = looks.shot_named(request.form.get("shot"))      # a small picture tapped; else the front picture
        photos = looks.gallery(pieces) or [looks.Photo(looks.FRONT, looks.FRONT_LABEL)]
        front = photos[0].look
        if not (front and front.status == "ready"):
            shot = looks.FRONT              # nothing can be made from a front picture that is not there: it is asked for
        again = request.form.get("again") == "1"
        if again and shot == looks.FRONT and request.form.get("sure") != "1" and looks.redraw_words(photos)[0] \
                and looks.left() > 0:
            # "Draw again" on a front picture that other photos or videos were made from: they will be removed with
            # it, so the page says that and asks first; "Draw again" under the question sends sure=1. Not asked when
            # no picture is left today: then nothing is drawn and nothing removed, and the page says why.
            return ask_first("again", looks.FRONT)
        there = next((photo.look for photo in photos if photo.name == shot), None)
        if shot != looks.FRONT and (again or not (there and there.status in ("ready", "working"))) \
                and not more_offered(key):
            # A pose or a surrounding to be drawn (or drawn again) on an outfit he has not said yes to: refused like
            # "More photos" above, before anything is asked or spent; the front picture stays large. A photo of it
            # that is there already is still shown when tapped (this is not reached for it).
            if not by_htmx:
                flash(looks.NOT_YET)
                return redirect(shot_shown(key, looks.FRONT))
            return look_fragment(key, photos, looks.FRONT, said=looks.NOT_YET)
        if shot != looks.FRONT and (again or not (there and there.status in ("ready", "working"))) \
                and looks.needs_ok(pieces):
            # One of the other pictures is to be drawn now (a cell not drawn yet, or "Draw again" on it): from the
            # AI picture of him, like "More photos". The same question first, once.
            if not agreed:
                return ask_first(f"send:{shot}", shot if again else looks.FRONT)
            looks.agree_to_sending_again()
        look = looks.request(pieces, again=again, shot=shot)
        if look is None:
            abort(404)                      # AI pictures are switched off
        photos = looks.gallery(pieces) or []
        if shot != looks.FRONT and look.status in ("limit", "failed"):
            # One of the small pictures, tapped where it was not drawn, cannot be drawn now (the day's pictures are
            # used up, the service is being left alone): the front picture stays large, and the reason is said once,
            # under the row, until he taps OK. Not over the picture, which would hide it behind the pieces' photos.
            photos_said(key, look.message)
            shot, look = looks.FRONT, photos[0].look if photos else look
        for photo in photos:                # what was just answered, with its reason if it was refused
            if photo.name == shot:
                photo.look = look
        if not request.headers.get("HX-Request"):
            return redirect(shot_shown(key, shot))
        return look_fragment(key, photos, shot)

    @app.get("/outfits/look/<look_key>")
    def outfits_look_state(look_key: str):
        """Asked every few seconds while the picture shown large is being drawn."""
        look = looks.get(look_key) if re.fullmatch(r"[0-9a-f]{24}", look_key) else None
        if look is None:
            abort(404)
        # The band on the page says what it shows now ("drawing", or "line" while it waits its turn). While that
        # is still so there is nothing new to show: no content, and the page leaves the box as it is (no blink).
        if look.status == "working" and request.args.get("showing") == ("line" if look.message else "drawing"):
            return "", 204
        outfit_key = request.args.get("outfit", "")
        outfit_key = outfit_key if re.fullmatch(r"[0-9a-f]{12}", outfit_key) else ""
        pieces = pieces_of(outfit_key) if outfit_key else None
        shot = looks.shot_named(request.args.get("shot"))
        photos = (looks.gallery(pieces) if pieces else None) or [looks.Photo(looks.FRONT, looks.FRONT_LABEL, look)]
        return look_fragment(outfit_key, photos, shot if len(photos) > 1 else looks.FRONT)

    @app.get("/outfits/photos")
    def outfits_photos():
        """Asked every few seconds while some of an outfit's small pictures are being drawn: the row of them."""
        outfit_key = request.args.get("outfit", "")
        pieces = pieces_of(outfit_key) if re.fullmatch(r"[0-9a-f]{12}", outfit_key) else None
        photos = looks.gallery(pieces) if pieces else None
        if not photos:
            abort(404)
        return shots_fragment(outfit_key, photos, looks.shot_named(request.args.get("shot")))

    # ── AI videos of outfits: "See it move" (videos.py) ──────────────────────
    # The part of a picture box about its video is swapped on its own (_video.html), so the picture is not sent
    # again and does not fade in again. It is named by the picture (`look`, its key) and the outfit (`outfit`).

    def video_look() -> tuple[looks.Look, str, str]:
        """The finished picture a video request is about, the outfit's key, and which of the outfit's pictures it is
        (front, a pose, a surrounding: its movement follows from that); 404 if there is none to see. Which picture
        it is is looked up among the outfit's own pictures, never taken from the page."""
        look_key = request.values.get("look", "")
        outfit_key = request.values.get("outfit", "")
        look = looks.get(look_key) if re.fullmatch(r"[0-9a-f]{24}", look_key) else None
        if look is None or look.status != "ready" or videos.service() is None:
            abort(404)
        outfit_key = outfit_key if re.fullmatch(r"[0-9a-f]{12}", outfit_key) else ""
        pieces = pieces_of(outfit_key) if outfit_key else None
        shot = videos.shot_of(look, looks.gallery(pieces) if pieces else None)
        if shot is None:
            abort(404)
        return look, outfit_key, shot

    def video_may_start(outfit_key: str, look: looks.Look) -> bool:
        """Whether a new video of this picture may be made for this outfit: "See it move" is offered on it
        (more_offered), and, for anyone held to that, the picture is one of that outfit's own (not another outfit's
        picture sent with the key of one in his wardrobe)."""
        if looks.more_for_anyone():
            return True
        if not more_offered(outfit_key):
            return False
        pieces = pieces_of(outfit_key)
        return any(photo.look is not None and photo.look.key == look.key
                   for photo in (looks.gallery(pieces) if pieces else None) or [])

    def video_refused() -> videos.Video:
        """What "See it move" says on an outfit he has not said yes to: nothing is made, no video of the day taken."""
        return videos.Video("", "limit", message=looks.NOT_YET)

    def video_fragment(outfit_key: str, look: looks.Look, shot: str, video: videos.Video | None,
                       asking: bool = False, play: bool = False) -> str:
        offer = asking or (video is not None and video.status in ("failed", "limit", "consent"))
        refused = video is not None and video.message == looks.NOT_YET       # no button to make one: only Close
        return render_template("_video.html", key=outfit_key, look=look, video=video, asking=asking, play=play,
                               clip=videos.clip_of(shot),
                               left=(0 if refused else videos.left()) if offer else None, left_words=videos.left_words, told=videos.told,
                               needs_ok=offer and videos.needs_consent(look),
                               turn_seconds=(videos.rules() or {}).get("turn_seconds", 6))

    @app.get("/outfits/video")
    def outfits_video():
        """'See it move' opened (ask=1: what a video is and how many are left today), closed again, and asked
        every few seconds while the video is being made (wait=1: once it is ready, it plays)."""
        look, outfit_key, shot = video_look()
        video = videos.of(look, shot)
        ready = video is not None and video.status == "ready"
        if not (video and video.status in ("ready", "working")) and not video_may_start(outfit_key, look):
            # On an outfit he has not said yes to, only a video made already is shown: no offer (why, and Close),
            # and no "Try again" under one that once failed.
            if request.args.get("ask") == "1":
                return video_fragment(outfit_key, look, shot, video_refused())
            video = None
        return video_fragment(outfit_key, look, shot, video, asking=request.args.get("ask") == "1" and not video,
                              play=ready and (request.args.get("wait") == "1" or request.args.get("ask") == "1"))

    @app.post("/outfits/video")
    def outfits_video_make():
        """Make the video of one of an outfit's pictures, the one showing (or say why not)."""
        look, outfit_key, shot = video_look()
        there = videos.of(look, shot)
        if not (there and there.status in ("ready", "working")) and not video_may_start(outfit_key, look):
            # On an outfit he has not said yes to: refused before anything is sent or counted (a video that is there
            # already is still shown, below, as it always was).
            if not request.headers.get("HX-Request"):
                flash(looks.NOT_YET)
                return redirect(request.referrer or url_for("outfits_page"))
            return video_fragment(outfit_key, look, shot, video_refused())
        video = videos.request(look, agreed=request.form.get("agree") == "on", shot=shot)    # the band's box, where it has one
        if not request.headers.get("HX-Request"):
            return redirect(request.referrer or url_for("outfits_page"))
        return video_fragment(outfit_key, look, shot, video, play=video is not None and video.status == "ready")

    @app.get("/videos/<name>")
    def video_file(name: str):
        path = videos.file_of(name)
        if path is None:
            abort(404)
        # Sent in parts when the browser asks for a range of it (Range: bytes=…), which phones do to play a video.
        response = send_file(path, mimetype="video/mp4", conditional=True)
        response.headers["Cache-Control"] = "private, max-age=31536000, immutable"   # a new video gets a new name
        return response

    @app.get("/looks/<name>")
    def look_image(name: str):
        path = looks.image(name)
        if path is None:
            abort(404)
        response = send_file(path, mimetype=imagegen.MIME[path.suffix.lstrip(".")])
        response.headers["Cache-Control"] = "private, max-age=31536000, immutable"   # a new version gets a new name
        return response

    @app.get("/looks/<name>/full")
    def look_full(name: str):
        """'Full size' under an outfit's AI picture: the picture larger, on a small page of Stilsmith's own with its
        "AI picture" label and the way back, never the bare file, which would show a realistic picture (perhaps made
        from his photo) with no label (review N13; EU AI Act, Article 50). Who may see the page is exactly who may
        see the file itself (looks.image, the same check): a picture made from a customer's photo only by him; one
        of the house model (made from no photo) by any signed-in customer with its address, as the file always
        could be (looks._view). `outfit`: the outfit it is of, for the way back; the way back is to the Outfits page
        he came from, where there is one, else to that outfit on Outfits."""
        if looks.image(name) is None:
            abort(404)
        key = request.args.get("outfit", "")
        key = key if re.fullmatch(r"[0-9a-f]{12}", key) else ""
        back = url_for("outfits_page", _anchor=f"outfit-{key}" if key else None)
        came = urlsplit(request.referrer or "")
        if came.netloc == request.host and came.path.startswith("/outfits") and not came.path.startswith("/outfits/"):
            back = came.path + (f"?{came.query}" if came.query else "") + (f"#outfit-{key}" if key else "")
        return page("look_full.html", tab="outfits", name=name, back=back)

    @app.post("/outfits/save")
    def outfits_save():
        """'Add to my wardrobe' under an outfit (a yes), and 'Take out' again. The heart that saved an outfit was the
        same thing, and this is still its address.

        The button says which of the two it asks for ("want": save or remove), so a tap always does what the button
        said, also on a page that has gone out of date: asked twice, the same thing is simply true twice. A form
        without it (an older page) switches the outfit over.

        A yes stores the outfit as it is now and which pieces it combines (db.save_outfit); from then on its pieces
        are in his wardrobe (selection.SlotView.mine). Taking it out removes from the wardrobe only the pieces no
        other outfit of his wears: the page it leads back to names them, and its Undo ("want": restore) puts back
        exactly what was removed. The last outfit taken out is kept for that (the setting "removed_outfit").

        Where it leads back to: the outfits he said yes to (the form says on=saved), Buy this outfit (on=buy), or
        the outfits on offer. There he goes on from where he was: the outfits that stood in front of the one he
        said yes to keep their places (same_row, "front"), the others follow, those that reuse most of what he now
        has first, and the page comes back on the first of those: the address ends "#outfit-<its key>", which moves
        the row there with or without JavaScript.
        """
        key = request.form.get("key", "")
        sig = request.form.get("sig", "")[:400]
        want = request.form.get("want", "")
        where = request.form.get("on", "")
        occasion = request.form.get("occasion", "")
        occasion = occasion if occasion in outfits.OCCASIONS else None
        earlier = db.list_saved()
        # The outfit by its key, or (its product changed since he said yes) by the pieces it combines.
        rows = [fav for fav in earlier if fav["key"] == key] or [fav for fav in earlier if sig and fav["sig"] == sig]
        if want not in ("save", "remove", "restore"):
            want = "remove" if rows else "save"
        w = selection.build()
        stays = front_of(request.form)      # the outfits that keep their places at the head of the row
        if want == "remove":
            last = db.get_setting("last_answer") or {}
            if where not in ("saved", "buy") and last.get("kind") == "yes" and last.get("key") == key \
                    and key in (last.get("row") or []):
                # Undo of the yes just given: the row as it stood before it, every outfit in its place (the outfits
                # behind it are not sorted again by what he has now).
                stays = list(last["row"])
            if rows:
                key, sig = rows[0]["key"], rows[0]["sig"]
                # (Saved twice before version 9, with different products: the same pieces are still his through
                # the other one, so nothing goes with this one.)
                twice = any(fav["sig"] == sig and fav not in rows for fav in earlier)
                left = yes.leaving(w, sig) if sig and not twice else []
                # A spare is in his wardrobe only beside the piece itself: it goes with it (the message says "with
                # its spare"), and Undo brings it back.
                spares = [view.slot["id"] for view in left if view.qty > 1]
                db.set_setting("removed_outfit", {**rows[0], "more": rows[1:], "left": yes.names(left),
                                                  "n_left": len(left), "spares": spares})
                for fav in rows:
                    db.unsave_outfit(fav["key"])
                for slot_id in spares:
                    yes.spare(slot_id, False)
        elif not rows:
            removed = db.get_setting("removed_outfit")
            if want == "restore" and removed and removed["key"] == key:
                for fav in [removed] + list(removed.get("more") or []):
                    db.save_outfit(fav["key"], fav["saved_at"], fav["label"], fav["pieces"], fav.get("sig"))
                for slot_id in removed.get("spares") or []:
                    yes.spare(slot_id, True)
                sig = removed.get("sig") or ""
                db.set_setting("removed_outfit", None)
            else:
                outfit = outfits.find(w, key)
                if outfit is None:   # the wardrobe changed under the page
                    abort(409, "That outfit no longer exists — reload the page.")
                added = yes.adds(w, outfit)
                sig = outfit.sig
                row_now: list[str] = []
                if where not in ("saved", "buy"):       # in the row as the page showed it: what stood in front stays there
                    row_now = [o.key for o in offered_row(w, occasion or usual_occasion(), request.form, stays)[0]]
                    if key in row_now:
                        stays = row_now[:row_now.index(key)]
                for view in added.new:          # a yes adds one of each piece: never a spare left from earlier
                    if view.spare:
                        yes.spare(view.slot["id"], False)
                pieces = outfits.snapshot(outfit)
                db.save_outfit(key, catalog.now_iso(), outfit.label, pieces, sig)
                db.undecline_outfit(sig)        # (a yes to something he had said no to: the yes counts)
                # (`row`: the row as it stood before the yes, so that its Undo puts back every outfit where it was.)
                said_before = db.get_setting("last_answer")     # the message before: called the same? (yes.answered)
                # (`all_yours`: the yes added nothing and saved it to My outfits; `all_owned`: he owns every piece.)
                db.set_setting("last_answer", {"kind": "yes", "key": key, "sig": sig, "label": outfit.label,
                                               "name": yes.name(pieces), "words": added.words, "row": row_now,
                                               "all_yours": added.all_yours, "all_owned": added.all_owned,
                                               **yes.answered(outfit.label, occasion or usual_occasion(), pieces,
                                                              row_now, key, said_before, shown_number(request.form))})
        if request.headers.get("HX-Request"):
            # A page from before the button was a plain form: its new state and the chip with its new number.
            return render_template("_save_button.html", key=key, saved=want != "remove", yes_sig=sig,
                                   chip=len(db.saved_keys()))
        if where == "saved":
            if want == "remove":        # the page from its top, where it says what was taken out, with Undo
                return redirect(url_for("outfits_page", occasion="saved", removed=key))
            return redirect(url_for("outfits_page", occasion="saved", _anchor=f"outfit-{key}"))     # shown again
        if where == "buy" and sig and outfits.find_by_sig(selection.build(), sig) is not None:
            return redirect(url_for("outfits_buy", at=sig))
        row = same_row(request.form, stays)
        if want == "save":              # the next outfit in line: behind the ones he passed, it reuses most of his pieces
            after = yes.offer(selection.build(), occasion or usual_occasion(), *place(request.form), stays)[0]
            following = next((o for o in after if o.key not in stays), after[-1] if after else None)
            return redirect(url_for("outfits_page", occasion=occasion, added=key, **row,
                                    _anchor=f"outfit-{following.key}" if following and stays else None))
        # That outfit again, on offer as before, in the place where he answered it.
        back = outfits.find_by_sig(selection.build(), sig) if sig and stays else None
        return redirect(url_for("outfits_page", occasion=occasion, at=sig or None,
                                removed=key if want == "remove" else None, **row,
                                _anchor=f"outfit-{back.key}" if back else None))

    @app.post("/outfits/no")
    def outfits_no():
        """'Not for me' under an outfit: that combination of pieces is not offered again (db.decline_outfit). The
        page it leads back to says so, with Undo (want=undo), which shows the outfit again. "Offer them again" at the
        foot of Outfits (want=all) brings back every outfit he said no to.

        He goes on from where he was. A no takes that one outfit out of the row and leaves the others in their
        places (outfits.generate), and the page comes back on the outfit that followed it: the form names it
        ("next", its key), and the address ends "#outfit-<that key>", which moves the row there with or without
        JavaScript. After a no to the last outfit of the row the form says where it stood instead ("i"), and the
        page comes back on what stands there now. Undo puts the outfit back in its place and shows it."""
        sig = request.form.get("sig", "")[:400]
        want = request.form.get("want", "")
        occasion = request.form.get("occasion", "")
        occasion = occasion if occasion in outfits.OCCASIONS else None
        row = same_row(request.form)
        if want == "all":
            n = db.undecline_outfit()
            if n:
                flash(f"The {n} {'outfit' if n == 1 else 'outfits'} you said no to {'is' if n == 1 else 'are'} "
                      "offered again.")
            return redirect(url_for("outfits_page", occasion=occasion, **row))
        if want == "undo":
            db.undecline_outfit(sig)
            last = db.get_setting("last_answer") or {}
            if last.get("kind") == "no" and last.get("sig") == sig and last.get("row"):
                row = same_row(request.form, list(last["row"]))     # the row as it was before the no
            shown = yes.offer(selection.build(), occasion or usual_occasion(), *place(request.form), front_of(row))[0]
            back = next((o for o in shown if o.sig == sig), None)
            if back is not None:        # in its old place in the row, and on screen
                return redirect(url_for("outfits_page", occasion=occasion, **row, _anchor=f"outfit-{back.key}"))
            return redirect(url_for("outfits_page", occasion=occasion, at=sig or None, **row))
        outfit = outfits.find_by_sig(selection.build(), sig)
        if outfit is None:
            abort(409, "That outfit no longer exists — reload the page.")
        if sig in db.yes_sigs():
            abort(409, "That outfit is in your wardrobe. Take it out first.")
        # The row as it stands now. After the no every other outfit of it stays in front, in its place, and one more
        # joins at the end: he goes on from where he was, and none he passed moves (a row sorted by what he has
        # would put the newcomer among them). Its Undo puts back the row as it was.
        row_was = [o.key for o in offered_row(selection.build(), occasion or usual_occasion(), request.form,
                                              front_of(request.form))[0]]
        row = same_row(request.form, [k for k in row_was if k != outfit.key])
        db.decline_outfit(sig)
        pieces = outfits.snapshot(outfit)
        db.set_setting("last_answer", {"kind": "no", "sig": sig, "label": outfit.label,
                                       "name": yes.name(pieces), "row": row_was,
                                       **yes.answered(outfit.label, occasion or usual_occasion(), pieces, row_was,
                                                      outfit.key, db.get_setting("last_answer"), shown_number(request.form))})
        following = request.form.get("next", "")
        if not re.fullmatch(r"[0-9a-f]{12}", following):
            # It was the last of the row: whatever stands in its place now, or the one before it.
            shown = yes.offer(selection.build(), occasion or usual_occasion(), *place(request.form),
                              front_of(row))[0]
            try:
                i = max(0, min(len(shown) - 1, int(request.form.get("i", 0))))
            except ValueError:
                i = 0
            following = shown[i].key if shown else ""
        return redirect(url_for("outfits_page", occasion=occasion, declined=sig, **row,
                                _anchor=f"outfit-{following}" if following else None))

    # ── Shopping list ─────────────────────────────────────────────────────────

    def your_sizes() -> dict:
        """For the 'Your sizes' line at the top of the shopping list and of Buy this outfit (_your_sizes.html):
        the sizes every line there is ordered in, and whether they are still the example's."""
        you = profile_mod.load()
        return {"you": you, "example_sizes": profile_mod.sizes_unconfirmed(you)}

    @app.get("/list")
    def list_page():
        w = selection.build()
        # The list is of his wardrobe (w.mine): the pieces of the outfits he said yes to.
        return page("list.html", w=w, tab="list", sl=export.build(w.mine), said=change_said(w, None, "list"),
                    **your_sizes())

    @app.get("/list.md")
    def list_markdown():
        # "Download as plain text" (list.html): a .txt file, which every phone and computer opens (review N16).
        text = export.to_markdown(export.build(selection.build().mine))
        return Response(text, mimetype="text/plain; charset=utf-8",
                        headers={"Content-Disposition": "attachment; filename=shopping-list.txt"})

    @app.get("/list.csv")
    def list_csv():
        text = export.to_csv(export.build(selection.build().mine))
        return Response("\ufeff" + text, mimetype="text/csv; charset=utf-8",   # BOM: Excel reads the € sign
                        headers={"Content-Disposition": "attachment; filename=shopping-list.csv"})

    @app.post("/outfits/tryon")
    def outfits_tryon():
        """Hook for the future virtual try-on — see tryon.py. Not built."""
        if not tryon.available():
            abort(501, "Trying outfits on yourself isn't built yet.")
        w = selection.build()
        outfit = outfits.find(w, request.form.get("key", ""))
        if outfit is None:
            abort(409, "That outfit no longer exists — reload the page.")
        garments = [{"layer": p["layer"], "category": p["category"], "name": p["name"],
                     "colour_hex": p["hex"], "image_url": p["image_url"], "url": p["url"]}
                    for p in outfits.snapshot(outfit)]
        image = tryon.PROVIDER.render(tryon.PERSON_PHOTO, garments)  # type: ignore[union-attr]
        return Response(image.read_bytes(), mimetype="image/jpeg")

    # ── Slots: review and edit the capsule ────────────────────────────────────

    @app.get("/slots")
    def slots_page():
        prof = profile_mod.load()     # the plan is part of the Wardrobe, so its tab stays lit
        return page("slots.html", tab="wardrobe", palette=capsule.palette_summary(prof), profile=prof)

    def slot_fields() -> dict | None:
        form = request.form
        category, colour = form.get("category", ""), form.get("colour", "")
        if category not in GARMENTS or colour not in colours.COLOURS:
            return None
        try:
            qty = max(1, min(9, int(form.get("qty", 1))))
        except ValueError:
            qty = 1
        name = " ".join(form.get("name", "").split())[:60]
        if not name:
            name = f"{colours.get(colour).label} {GARMENTS[category].label.lower()}"
        return {"name": name, "category": category, "colour": colour, "qty": qty,
                "keywords": " ".join(form.get("keywords", "").split())[:80]}

    @app.post("/slots/add")
    def slots_add():
        fields = slot_fields()
        if fields is None:
            abort(400)
        taken = {s["id"] for s in db.list_slots()}
        slot = capsule.new_slot(fields["category"], fields["colour"], fields["name"],
                                fields["keywords"], fields["qty"], taken)
        db.add_slot(slot)
        db.set_setting("plan_edited", True)     # a profile change no longer rebuilds the plan by itself
        needs_refresh = sync_catalog()
        # Said inside the new piece, where the page lands, not at the page's top (slots.html, base.html).
        flash(f"Added “{slot['name']}” to your plan." + (f" {REFRESH_HINT}" if needs_refresh else ""),
              "plan:" + slot["id"])
        return redirect(url_for("slots_page") + f"#slot-{slot['id']}")

    @app.post("/slots/<slot_id>/save")
    def slots_save(slot_id: str):
        slot, fields = db.get_slot(slot_id), slot_fields()
        if slot is None:
            abort(404)
        if fields is None:
            abort(400)
        changed = (fields["category"], fields["colour"]) != (slot["category"], slot["colour"])
        if any(fields[k] != slot[k] for k in fields):
            db.set_setting("plan_edited", True)     # (pressing Save without changing anything is no edit)
        if changed:
            fields.update(locked=False, pick=None)   # different garment or colour: old pick no longer applies
        db.update_slot(slot_id, **fields)
        needs_refresh = sync_catalog(changed_slot=slot_id if changed else None)
        flash(f"Saved “{fields['name']}”." + (f" {REFRESH_HINT}" if changed and needs_refresh else ""),
              "plan:" + slot_id)      # said inside the piece, as "Added" above
        return redirect(url_for("slots_page") + f"#slot-{slot_id}")

    @app.post("/slots/<slot_id>/delete")
    def slots_delete(slot_id: str):
        """Remove a piece from the plan. A piece that is in his wardrobe leaves it with that, and his total and his
        shopping list: the button asks first (slots.html) and the message says so. An outfit of his that wore it
        stays under My outfits as he added it, where it says that the piece is gone (outfits.html)."""
        slot = db.get_slot(slot_id)
        if slot is None:
            abort(404)
        view = selection.build().get(slot_id)
        mine, worn = bool(view and view.mine), view.outfits_in if view else 0
        owned = bool(view and view.state == "owned")        # what he owns is in no total and on no list to buy
        db.delete_slot(slot_id)
        if slot_id in (db.get_setting("kept_pieces") or []):
            yes.keep(slot_id, False)            # (a piece that is gone is no longer one he kept)
        if slot_id in (db.get_setting("spares") or []):
            yes.spare(slot_id, False)           # (… nor one with a spare)
        if yes.owned_from_outside(slot_id):
            yes.remember_outside(slot_id, False)
        db.set_setting("plan_edited", True)
        sync_catalog()
        said = f"Removed “{slot['name']}” from your plan."
        if mine:
            said = (f"Removed “{slot['name']}” from your plan, and with that from your wardrobe"
                    + ("." if owned else ", your total and your shopping list."))
        if worn:
            said += (f" It was in {worn} of your outfits: {'it stays' if worn == 1 else 'they stay'} under My "
                     f"outfits as you added {'it' if worn == 1 else 'them'}, but can no longer be bought as "
                     f"{'an outfit' if worn == 1 else 'outfits'}.")
        flash(said)
        return redirect(url_for("slots_page"))

    @app.post("/slots/repropose")
    def slots_repropose():
        slots, unmatched = capsule.propose(profile_mod.load())
        slots = with_his_pieces(slots, db.list_slots())     # … but for the pieces of the outfits he said yes to
        db.replace_slots(slots)
        db.set_setting("plan_edited", False)    # from scratch: profile changes rebuild it again
        needs_refresh = sync_catalog()
        pieces = sum(int(s.get("qty") or 1) for s in slots)       # a white tee ×2 is two pieces, as on the page
        flash(f"Started over from your profile: your plan has {pieces} {'piece' if pieces == 1 else 'pieces'}."
              + (f" {REFRESH_HINT}" if needs_refresh else ""))
        for line in unmatched:
            flash(f"Couldn't tell what kind of garment “{line}” is: add it to your plan by hand.")
        return redirect(url_for("slots_page"))

    # ── Profile ───────────────────────────────────────────────────────────────

    @app.route("/profile", methods=["GET", "POST"])
    def profile_page():
        current = profile_mod.load()
        # HEAD (link checkers, "curl -I") is answered like GET: never as a sent form, which would save an empty one.
        if request.method in ("GET", "HEAD"):
            rules = looks.load_rules()
            chosen = looks.service()
            model = person.load()
            w = selection.build()
            return page("profile.html", tab="profile", profile=current, groups=person.GROUPS, model=model, w=w,
                        # The drawn figure in the middle (figure.py), and what app.js needs to redraw it.
                        fig=figure.drawing(model, current["height_cm"], current), figure_data=figure.data(),
                        tabs=profile_mod.TABS, picture=model_picture(w) if chosen else None,
                        model_words=person.describe(model, current)[0] or rules["text"]["model"],
                        own_body=person.own_body(current),
                        looks_on=chosen is not None, drawn_by=chosen.label if chosen else "the AI service",
                        videos_on=chosen is not None and videos.service() is not None,
                        photos=rules["pictures"]["photos"], has_photo=person.photo() is not None,
                        store_rows=store_rows(current),
                        # A message that was not sent without JavaScript: its words came along (profile_style_say).
                        **style_context(kept=next(iter(get_flashed_messages(category_filter=["style-kept"])), "")),
                        photo_added=catalog.collected_label({"collected_at": db.get_setting("photo_added")}),
                        # What he has not answered yet is said where it is asked, in a plain line: his sizes,
                        # his colours (the plan starts with Stilsmith's), his budget (its field stays empty).
                        sizes_given=not profile_mod.sizes_unconfirmed(current),
                        answered=profile_mod.answered(current))

        new, notes = profile_mod.from_form(request.form, current)
        answer = save_answers(current, new, notes)
        # The styles ticked under "What do you dress for?" are the style brief's styles (style.py). `styles_shown`
        # tells a form that has them from one that does not. They change which products and outfits come first,
        # never the plan itself. They are saved last, after everything else this save changes (the budget, the
        # sizes, a plan built anew), so that what the styles did to his picks can be told apart from the rest and
        # said: "Your styles changed 1 piece: +70 €."
        if "styles_shown" in request.form and style.styles_differ(request.form.getlist("styles")):
            before = picks_of(selection.build())
            style.set_styles(request.form.getlist("styles"))
            changed = brief_changed(before, picks_of(selection.build()), "Your styles")
            if changed:
                flash(changed)
        return answer

    def save_answers(current: dict, new: dict, notes: list[str]):
        """Profile's form, sent: everything in it but the styles is saved, and the page to go to next is given
        back (profile_page saves the styles after it)."""
        # The model's choices (the Body tab) are sent with the same form, where the menu is shown. A save that changed
        # only them saves only them, as the model's own button did (person.py): the profile stays as it was, also
        # while it holds the example's values, and the message is said beside the model.
        model = person.load()
        chosen_model = person.clean(request.form) if any(group in request.form for group in person.GROUPS) else model
        if chosen_model != model:
            person.save(chosen_model)
            if not notes and profile_mod.same_answers(new, current):
                flash("Model saved. Pictures drawn from now on show it.", "model")   # profile.html adds "See your outfits"
                return redirect(url_for("profile_page") + "#model")
            flash("Model saved. Pictures drawn from now on show it.")
        elif looks.service() is not None and person.describe(model, new)[1] != person.describe(model, current)[1]:
            # New measurements that change the body in words (person.body_words): the pictures are asked for anew.
            flash("Your model now follows your new measurements. Pictures drawn from now on show it.")
        # Stores unticked on the Stores tab: their pieces are picked again, his own choices among them (shared.py).
        stores_line = shared.stores_unticked(current, new)
        # The whole form was in front of him: its colours and what he dresses for are his answers now. The budget
        # only if he typed one, or had given one before (its field is empty until then).
        typed_budget = profile_mod.given_budget(request.form.get("budget")) is not None
        profile_mod.answer("colours", "use", *(["budget"] if typed_budget else []))
        # A budget he had, its field emptied: he has no budget now. The bar shows his total, with nothing left or
        # over, as before he gave one ("Best for budget" says it needs one).
        cleared = ("budget" in request.form and not request.form["budget"].strip()
                   and profile_mod.budget_known(current))
        if cleared:
            profile_mod.unanswer("budget")
        profile_mod.save(new)
        if cleared:
            flash("Budget cleared. The bar at the top now shows what your wardrobe costs, without a budget.")
        for note in notes:
            flash(note)
        if stores_line:
            flash(stores_line)

        shapes_capsule = ("liked", "refused", "use", "shoes", "outerwear", "owned")
        # The plan has no tab of its own, so a message that sends you to it carries the link.
        # (Markup: the link is shown as a link; what the customer typed is still escaped.)
        same_plan = all(current[f] == new[f] for f in shapes_capsule)
        if same_plan and not current["example"]:        # sizes or budget: the plan stays as it is
            flash(Markup('Profile saved. <a href="%s">See your outfits</a>') % url_for("outfits_page"))
            return back_to_tab()
        if plan_edited(current):        # a plan changed on the plan page is never rebuilt without asking
            if current["refused"] != new["refused"]:
                sync_catalog()          # its pieces stay, but no longer with products in a colour now refused
            flash(Markup("Profile saved. Your plan stays as you edited it. To rebuild it from these answers, use "
                         "“Start over from my profile” on <a href=\"%s\">the plan page</a>.") % url_for("slots_page"))
            return back_to_tab()
        if same_plan:
            # The first save, with the example's colours and use kept: the plan is built from them already. As the
            # note on Profile says, the outfits follow, now under the budget bar instead of the starter banner.
            flash("Profile saved.")
            return redirect(url_for("outfits_page"))

        plan, needs_refresh = rebuild_plan(new, current)
        flash(rebuilt_message(plan) + (f" {REFRESH_HINT}" if needs_refresh else ""))
        edit_the_plan = Markup('<a href="%s">Edit the plan</a>') % url_for("slots_page")
        for line in plan.unmatched:
            flash(Markup("Couldn't tell what kind of garment “%s” is: add it to your plan by hand. %s")
                  % (line, edit_the_plan))
        return redirect(url_for("outfits_page"))       # the new plan, where it shows best: on the model

    def store_rows(profile: dict) -> list[dict]:
        """The Stores tab: every store customers are offered (programmes.offered), with the network that runs its
        partner programme ("Rakuten") and whether he ticked it (profile.stores). `accepted`: the store's programme
        has accepted Stilsmith ("approved" in the owner's registry, the stores table); only then is the store called
        a partner on the page."""
        mine = profile_mod.stores(profile)
        stocked = shared.stocked()
        approved = {store["key"] for store in db.list_stores() if store["status"] == "approved"}
        rows = [{"key": key, "label": label, "on": key in mine, "empty": key not in stocked, "accepted": key in approved,
                 "network": owner.NETWORKS.get(programmes.network(key), programmes.network(key).title())}
                for key, label in programmes.offered().items()]
        # The stores with products first; those with none yet are shown apart, under their own line (profile.html).
        return [row for row in rows if not row["empty"]] + [row for row in rows if row["empty"]]

    def style_context(said: str = "", kept: str = "") -> dict:
        """What Profile's style part shows (_style_chat.html): the styles to tick, the brief in use, and, where the
        chat is offered, the conversation and the brief it suggested. `said`: what just went wrong, if anything,
        and `kept`: the message that was not sent then, put back in the field so that he need not type it again."""
        chat = stylechat.state()
        brief = style.stored()
        shown = chat["draft"] or (brief if style.active(brief) else None)      # the brief the editor shows
        mine = profile_mod.stores()
        stocked = shared.stocked()
        most = int(style.load_rules()["chat"]["max_message_chars"])
        return {"STYLES": style.styles(), "FORMALITIES": style.formalities(), "PRICE_FEELINGS": style.prices(),
                "STYLE_FITS": style.FITS, "brief": brief, "brief_in_use": style.active(brief),
                "brief_words": style.in_words(brief), "chat_on": stylechat.available(), "chat": chat,
                "brief_shown": shown, "chat_said": said, "chat_kept": kept[:most],
                "chat_allowance": stylechat.allowance(), "chat_max": most,
                # The stores that suit the brief shown, ranked by the style table (config/stores.toml), among the
                # stores he ticked: a name, and whether Stilsmith has products from it yet.
                "brief_stores": [{"label": programmes.label(key), "empty": key not in stocked}
                                 for key in (style.stores_that_suit(shown, mine) if shown else [])]}

    def picks_of(w: selection.Wardrobe) -> tuple[dict[str, tuple[str | None, int, bool]], float]:
        """Each piece's product as it is picked now (how many of it count, and whether the piece is in his
        wardrobe), and his wardrobe's total, the one the bar at the top shows: taken before and after a change of
        the style brief, to say what the change did (brief_changed). The pieces are all the plan's, since outfits
        are made from all of them; the total is that of the pieces of the outfits he said yes to (w.mine)."""
        return ({view.slot["id"]: (view.chosen.id if view.chosen else None, view.qty, view.mine) for view in w.slots},
                w.mine.total)

    def still_against(w: selection.Wardrobe) -> Markup | str:
        """The pieces whose product the brief in use speaks against (a colour he avoids, something he does not
        want: style.against), in one sentence, or "". Such a product stays where nothing else good enough was
        found for the piece, or where he chose it himself; saying so keeps "no leather" from reading as if the
        leather shoes were gone."""
        names = [(view.slot["name"], view.qty) for view in w.slots
                 if view.state != "owned" and view.chosen is not None
                 and (style.against(view.chosen.data, view.slot["category"], w.brief)
                      or style.name_against(view.slot["name"], w.brief))]   # "White leather sneakers", by name
        if not names:
            return ""
        n = sum(qty for _, qty in names)
        shown = ", ".join(name for name, _ in names[:3])
        more = f" and {len(names) - 3} more" if len(names) > 3 else ""
        return Markup("%s still %s against it: %s%s.") % (f"{n} {'piece' if n == 1 else 'pieces'}",
                                                         "goes" if n == 1 else "go", shown, more)

    @app.post("/profile/style/say")
    def profile_style_say():
        """One message to the style chat. Its answer and the brief it suggests are shown; nothing is in use yet."""
        message = request.form.get("message", "")
        said = stylechat.say(message)
        if request.headers.get("HX-Request"):
            return render_template("_style_chat.html", **style_context(said, message if said else ""))
        if said:
            # Without JavaScript the page is loaded again: what went wrong is said beside the chat, where the page
            # comes back to, and his words are put back in the field there as well (_style_chat.html).
            flash(said, "style-bad")
            if message.strip():
                flash(message[:int(style.load_rules()["chat"]["max_message_chars"])], "style-kept")
        return redirect(url_for("profile_page") + "#style")

    @app.post("/profile/style/brief")
    def profile_style_brief():
        """The brief's own buttons: "Use this brief" (as he corrected it), "Remove brief", "Start again". What each
        did is said beside the brief, where the page comes back to, with what it did to his picks and total."""
        do = request.form.get("do")
        see_outfits = Markup('<a href="%s">See your outfits</a>') % url_for("outfits_page")
        if do == "use":
            brief = style.from_form(request.form)
            before = picks_of(selection.build())
            style.save(brief)                   # one that says nothing is none: style.save removes it
            stylechat.confirmed()
            now = selection.build()
            if style.active(brief):
                changed = brief_changed(before, picks_of(now), "Your brief")
                against = still_against(now)
                flash(Markup("Style brief saved. %s %s%s") % (changed or "It changed none of your pieces.",
                                                              against + " " if against else "", see_outfits), "style")
            else:
                changed = brief_changed(before, picks_of(now), "Removing the one you had")
                flash(Markup("The brief was empty, so none is in use. %s %s")
                      % (changed or "Your picks are as they are without one.", see_outfits), "style")
        elif do == "remove":
            before = picks_of(selection.build())
            talked = bool(stylechat.state()["turns"])       # the conversation goes with it: said
            style.remove()
            stylechat.forget()
            changed = brief_changed(before, picks_of(selection.build()), "Removing it")
            flash(Markup("Style brief removed%s. %s %s") % (", and the conversation with it" if talked else "",
                                                           changed or "That changed none of your pieces.", see_outfits),
                  "style")
        elif do == "forget":
            stylechat.forget()
            flash("The conversation is deleted." + (" Your style brief stays in use." if style.current() else ""),
                  "style")
        return redirect(url_for("profile_page") + "#style")

    def partner_stores() -> list[str] | None:
        """The names of the real stores whose partner programme has accepted Stilsmith ("approved" in the owner's
        registry). From the day there is one, the Stores tab calls that store a partner, and the page's foot, the
        shopping list and Buy this outfit say that its links may earn a commission (German law wants such links marked
        as advertising) instead of "Not affiliated with any retailer". [] while there are none; None if the registry
        cannot be read (an error page): then the foot says nothing either way."""
        try:
            # (An invented sample store, for trying the importers, is no partner: it does not count.)
            return [store.get("label") or store["key"] for store in db.list_stores()
                    if store["status"] == "approved" and not (store.get("rules") or {}).get("sample")]
        except Exception:
            return None

    def no_partners() -> bool:
        """True while no real store's partner programme has accepted Stilsmith (partner_stores)."""
        return partner_stores() == []

    app.jinja_env.globals.update(no_partners=no_partners, partner_stores=partner_stores)

    def back_to_tab():
        """Back to Profile, on the tab the form was sent from (app.js writes it in the form; without it, the first)."""
        tab = request.form.get("tab", "")
        return redirect(url_for("profile_page") + (f"#{tab}" if tab in profile_mod.TABS else ""))

    def first_outfit(w: selection.Wardrobe) -> list[dict] | None:
        """The pieces of the first outfit Outfits shows (for what the customer dresses for, unshuffled)."""
        use = profile_mod.load()["use"]
        chosen, _ = outfits.generate(w, occasion="all" if use == "both" else use, limit=1)
        return outfits.snapshot(chosen[0]) if chosen else None

    def model_picture(w: selection.Wardrobe) -> dict:
        """'Your model' on Profile: the AI picture of the saved model in the first outfit, which is the picture Outfits
        shows first (the same picture, never drawn twice), or where it stands. `look` is None while there is none."""
        pieces = first_outfit(w)
        if pieces is None:
            return {"look": None, "outfit": False}
        board = {"pieces": pieces}
        looks.attach([board])
        return {"look": board.get("look"), "outfit": True}

    @app.route("/profile/picture", methods=["GET", "POST"])
    def profile_picture():
        """'Draw my model' (POST), and where its picture stands, asked every few seconds while it is drawn (GET).
        The picture is asked for like any outfit's (looks.request), with the same daily limits."""
        if looks.service() is None:
            abort(404)                      # AI pictures are switched off
        w = selection.build()
        if request.method == "POST":
            pieces = first_outfit(w)
            if pieces is None:
                abort(409, "There is no outfit to draw yet — reload the page.")
            look = looks.request(pieces, again=request.form.get("again") == "1")
            if not request.headers.get("HX-Request"):
                return redirect(url_for("profile_page") + "#figure")
            return render_template("_model_picture.html", picture={"look": look, "outfit": True})
        return render_template("_model_picture.html", picture=model_picture(w))

    @app.post("/profile/sizes-ok")
    def profile_sizes_ok():
        """'These are my sizes', under the example sizes on the shopping list and on Buy this outfit: they are
        the customer's own, so the warning goes. Back to the page the button is on."""
        profile_mod.confirm_sizes()
        flash("Sizes saved.")
        at = request.form.get("at", "")[:400]       # pressed on one outfit's Buy page
        return redirect(url_for("outfits_buy", at=at) if at else url_for("list_page"))

    # ── The welcome: three short steps for a new customer, each of which he may skip ─────────────

    WELCOME = {1: "Your sizes", 2: "Colours and budget", 3: "What you dress for"}

    def as_sent(profile: dict) -> dict:
        """A saved profile as the Profile form would send it, so that one step's answers can be read with the same
        care as that form's (profile.from_form), everything else staying as it is."""
        def names(keys) -> str:
            return ", ".join(colours.get(key).label.lower() for key in keys or [])
        sent = {key: str(profile[key]) for key in ("top_size", "waist", "length", "shoe", "height_cm", "weight_kg",
                                                   "budget", "use", "owned")}
        sent.update(chest_cm=str(profile.get("chest_cm") or ""), waist_cm=str(profile.get("waist_cm") or ""),
                    liked=names(profile.get("liked")), refused=names(profile.get("refused")))
        for box in ("shoes", "outerwear"):
            if profile.get(box):
                sent[box] = "on"
        return sent

    @app.route("/welcome", defaults={"step": 1}, methods=["GET", "POST"])
    @app.route("/welcome/<int:step>", methods=["GET", "POST"])
    def welcome(step: int):
        """Sizes; colours and budget; what he dresses for. Each step saves what he answered to his profile, as the
        Profile page would, and leaves the rest unanswered; "Skip" answers nothing. Then the outfits, or, from the
        last step where the style chat is on, the chat on Profile ("Or describe your style in your own words"). No
        total and no budget bar here: he has not chosen anything yet."""
        if step not in WELCOME:
            abort(404)
        current = profile_mod.load()

        def onwards():
            if step < len(WELCOME):
                return redirect(url_for("welcome", step=step + 1))
            db.set_setting("welcome", "done")
            # "Or describe your style in your own words", under the last step where the style chat is on: the
            # welcome ends as it does with "Show me outfits" (what he ticked is saved, logging in no longer leads
            # here), and he is on Profile, at the chat.
            if request.form.get("then") == "style" and stylechat.available():
                return redirect(url_for("profile_page") + "#style")
            return redirect(url_for("outfits_page"))

        if request.method in ("GET", "HEAD"):
            return render_template("welcome.html", step=step, steps=WELCOME, profile=current, plain=True,
                                   sizes_given=not profile_mod.sizes_unconfirmed(current),
                                   answered=profile_mod.answered(current), given=None,
                                   chat_on=stylechat.available())
        form = request.form
        if form.get("skip") == "1":
            return onwards()
        profile_mod.answer()        # from here on what he answered is noted one by one (profile.answered)
        sent = as_sent(current)
        questions: list[str] = []
        given: dict[str, str] = {}
        if step == 1:
            given = {key: form.get(key, "").strip() for key in profile_mod.SIZES}
            if any(given.values()) and not all(given.values()):
                flash("Give all four sizes, or skip this step.")
                return render_template("welcome.html", step=step, steps=WELCOME, profile=current, plain=True,
                                       sizes_given=False, answered=profile_mod.answered(current), given=given), 400
            if not any(given.values()):
                return onwards()
            sent.update(given)
        elif step == 2:
            liked = [key for key in form.getlist("liked") if key in colours.COLOURS]
            if liked:
                sent["liked"] = ", ".join(colours.get(key).label.lower() for key in liked)
                sent["refused"] = ", ".join(colours.get(key).label.lower() for key in current.get("refused") or []
                                            if key not in liked)
                questions.append("colours")
            if profile_mod.given_budget(form.get("budget")) is not None:
                sent["budget"] = form["budget"]
                questions.append("budget")
            elif form.get("budget", "").strip():        # "0", or not a number: no budget was given
                flash(profile_mod.NOT_A_BUDGET)
        else:
            if form.get("use") in profile_mod.USES:
                sent["use"] = form["use"]
                questions.append("use")
        new, notes = profile_mod.from_form(sent, current)
        for note in notes:
            flash(note)
        if step == 1:
            if profile_mod.same_sizes(new, {**current, **given}):
                profile_mod.confirm_sizes()     # he typed them, also where they are the sizes pages start with
            else:
                flash("One of those sizes is not one we know, so your sizes were not saved. You can give them "
                      "on the Profile page.")
                new = current
        profile_mod.answer(*questions)
        if not profile_mod.same_answers(new, current):
            profile_mod.save(new)
            shapes_plan = ("liked", "refused", "use")
            if any(current[key] != new[key] for key in shapes_plan) and not plan_edited(current):
                rebuild_plan(new, current)
        return onwards()

    # ── The model in the AI pictures: a description, or your own photo (person.py) ──

    @app.post("/profile/model")
    def profile_model():
        person.save({group: request.form.get(group, "") for group in person.GROUPS})
        # Said where the page lands (the "model" and "photo" kinds are shown inside that section,
        # not at the top of the page, which is off the screen by then).
        flash("Model saved. Pictures drawn from now on show it.", "model")    # profile.html adds "See your outfits"
        return redirect(url_for("profile_page") + "#model")

    @app.post("/profile/photo")
    def profile_photo():
        back = redirect(url_for("profile_page") + "#photo")
        if request.form.get("remove") == "1":       # always possible, also once uploads were switched off
            looks.forget_photo(db.uid())
            flash("Your photo and the pictures made from it are deleted.", "photo")
            return back
        if not looks.load_rules()["pictures"]["photos"]:
            abort(404)
        upload = request.files.get("photo")
        data = upload.read(person.MAX_PHOTO + 1) if upload else b""
        if not data:
            flash("No photo arrived. Choose a photo first.", "photo")
        elif request.form.get("agree") != "on":
            chosen = looks.service()
            flash(f"Not saved. Tick the box to confirm that this is you, that you're 18 or over and that the photo "
                  f"may be sent to {chosen.label if chosen else 'the AI service'}.", "photo")   # as the box says
        else:
            problem = person.save_photo(data)
            if problem is None:
                # Beside photo_added: which words he agreed to, and whether the videos' words were among them.
                videos_shown = looks.service() is not None and videos.service() is not None    # as profile_page
                db.set_setting("photo_consent", PHOTO_CONSENT)
                videos.agreed_with_the_photo(videos_shown)
                looks.forget_pictures_of(db.uid())      # those showed the previous photo
            flash(f"Not saved. {problem}" if problem
                  else "Photo saved. Pictures drawn from now on show you.", "photo")
        return back

    @app.get("/profile/photo")
    def profile_photo_file():
        path = person.photo()
        if path is None:
            abort(404)
        response = send_file(path, mimetype=imagegen.MIME[path.suffix.lstrip(".")])
        response.headers["Cache-Control"] = "no-store"
        return response

    # ── Demo pictures ─────────────────────────────────────────────────────────

    @app.get("/mock/img/<kind>.svg")
    def mock_image(kind: str):
        try:
            body = mockimg.svg(kind, request.args.get("c"))
        except KeyError:
            abort(404)
        return Response(body, mimetype="image/svg+xml",
                        headers={"Cache-Control": "public, max-age=86400"})

    return app
