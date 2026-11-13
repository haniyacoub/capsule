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
from datetime import timedelta
from urllib.parse import urlsplit

from flask import Flask, Response, abort, flash, g, redirect, render_template, request, send_file, url_for
from markupsafe import Markup
from werkzeug.exceptions import HTTPException, NotFound

from . import (auth, capsule, catalog, colours, composition, db, export, imagegen, looks, mock, mockimg, outfits,
               owner, person, programmes, selection, shared, tryon)
from . import profile as profile_mod
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
PHOTO_CONSENT = "2026-11-12"


def bootstrap() -> None:
    """Start-up: create or update the database; on your own machine, set up the one local user."""
    db.init()
    if not conf.PRODUCTION:
        ensure_setup()


def sync_catalog(changed_slot: str | None = None) -> bool:
    """Keep the catalogue in step with the slot list after an edit.

    On demo data the invented candidates are rebuilt. On real data, candidates
    of deleted slots are dropped, and so are those collected for a slot whose
    garment or colour just changed (they no longer fit it). Items you added by
    hand always stay. Returns True if real data now needs a refresh: only on your
    own machine, where you can run one (REFRESH_HINT). A customer can't, so a
    customer is never told to.
    """
    current = catalog.load()
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
    plan = capsule.rebuild(profile, db.list_slots(), before.get("owned", ""))
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
    """'Your plan now has 17 pieces in your colours. Kept your 2 hand-picked pieces.', and what was not kept."""
    def pieces(n: int) -> str:
        return "piece" if n == 1 else "pieces"

    total, picked, owned = sum(int(s.get("qty") or 1) for s in plan.slots), len(plan.picked), len(plan.owned)
    words = [f"Your plan now has {total} {pieces(total)} in your colours."]
    if picked and owned:
        words.append(f"Kept your {picked} hand-picked {pieces(picked)} and the {owned} you own.")
    elif picked:
        words.append(f"Kept your {picked} hand-picked {pieces(picked)}.")
    elif owned:
        words.append(f"Kept the {owned} {pieces(owned)} you own.")
    if plan.lost:
        words.append("Not kept: " + ", ".join(f"{name} ({why})" for name, why in plan.lost) + ".")
    return " ".join(words)


def recoloured_name(name: str, old: str, new: str) -> str:
    """A piece's name once it takes a new colour: 'Black wool blazer' in navy is 'Navy wool blazer'.
    Only a name that starts with the old colour's name changes; any other ('My lucky blazer') stays."""
    before, after = colours.get(old).label, colours.get(new).label
    rest = name[len(before):]
    if not name.lower().startswith(before.lower()) or rest[:1].isalpha():   # 'Blackwatch shirt' is no black shirt
        return name
    return ((after if name[:1].isupper() else after.lower()) + rest)[:60]


def starter_line() -> str:
    """Whose the starter outfits are, at the top of Outfits until the customer saves his profile: 'Starter outfits for
    a man of 180 cm, size M, who likes navy, grey, white and olive.' Said from the example values every account
    starts with (profile.EXAMPLE), so it changes with them."""
    example = profile_mod.EXAMPLE
    keys = example["liked"]
    liked = [colours.get(key).label.lower() for key in keys] if isinstance(keys, list) else []
    likes = ", ".join(liked[:-1]) + " and " + liked[-1] if len(liked) > 1 else "".join(liked)
    nbsp = "\u00a0"         # "180 cm" and "size M" are never split over two lines
    return (f"Starter outfits for a man of {example['height_cm']}{nbsp}cm, size{nbsp}{example['top_size']}"
            + (f", who likes {likes}." if likes else "."))


def eur(value) -> str:
    value = float(value or 0)
    text = f"{value:,.0f}" if abs(value - round(value)) < 0.005 else f"{value:,.2f}"
    return f"{text} €"


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
    app.jinja_env.globals.update(
        nav=NAV, GARMENTS=GARMENTS, COLOURS=colours.COLOURS, ALPHA=ALPHA,
        USES=profile_mod.USES, MODES=selection.MODES, OCCASIONS=outfits.OCCASIONS,
        ink_on=colours.ink_on, level_hints=selection.HINTS,
        # The stores customers are offered, {key: name}, and their names in a sentence (programmes.py).
        STORES=programmes.OFFERED, store_names=programmes.names,
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
        if request.endpoint == "profile_photo":     # the one form that carries a file
            request.max_content_length = person.MAX_PHOTO + 64 * 1024

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
            extra += "".join(render_template("_level_total.html", w=w, key=key, oob=True) for key in selection.MODES)
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
        lit. These are those address arguments, checked (an occasion that is not one is left out), or {} for a
        page that is part of the Wardrobe. The page's buttons and links carry them, and so does every answer that
        sends the browser back to the page: any button pressed without JavaScript, and adding, completing or
        removing a product by hand (those forms always post plainly)."""
        at = request.args.get("at", "")[:400] if request.args.get("from") == "outfit" else ""
        if not at:
            return {}
        occasion = request.args.get("occasion", "")
        return {"from": "outfit", "at": at, **({"occasion": occasion} if occasion in outfits.OCCASIONS else {})}

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

    def change_said(w: selection.Wardrobe, shown: outfits.Outfit | None) -> dict | None:
        """What a change just made from an outfit did, for the line over the outfits (outfits.html), read from the
        address it led to. Each value is checked against this customer's own wardrobe, and one that does not match is
        left out: such an address can come from anywhere (an old tab, a link). `shown` is the outfit at the address.

        Choose in the pop-up (slot_pick): ?changed=<piece>&was=<product before, or empty>&was_locked=<0|1>: the piece
        now locked to another product than `was`. Said with Undo where `was` and was_locked describe a state it can
        go back to (see slot_restore).
        'Leave the coat off' and 'Wear the … instead' (_piece.html): ?left=<piece>&back=<outfit> or
        ?instead=<piece>&back=<outfit>: the outfit shown is the one at `back` without that piece, or with another in
        its place. Said with the link back to it."""
        args = request.args
        if args.get("changed"):
            view = w.get(args["changed"])
            was, was_locked = args.get("was", ""), args.get("was_locked")
            if view is None or view.state != "locked" or view.chosen is None or view.chosen.id == was:
                return None             # (after Undo and then Back, say: what the address says changed is undone)
            said = {"kind": "changed", "view": view, "was": was, "was_locked": was_locked, "at": args.get("at", "")[:400]}
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
            cands = sorted(view.cands, key=lambda c: (not c.available, -c.score.total, c.price))
        else:
            sort, cands = "price", view.cands   # already: in stock first, then by price
        return {"s": view, "cands": cands, "sort": sort, "way": way_back()}

    # ── Wardrobe ──────────────────────────────────────────────────────────────

    @app.get("/")
    def wardrobe():
        if conf.PRODUCTION and g.user is None:
            return render_template("landing.html", looks_on=_pictures_on(),      # the public website
                                   photos=_photos_on(), invite=bool(conf.INVITE_CODE))
        # Once, after a store stopped being offered: which, and how many pieces were picked again (shared.py).
        gone = shared.gone_message(keep=request.method != "GET") if conf.PRODUCTION else ""
        return page("wardrobe.html", tab="wardrobe", gone=gone)

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
        return page("slot.html", w=w, tab="outfits" if back else "wardrobe", back=back, **slot_context(w, slot_id))

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
        if request.form.get("outfit"):      # swapped from inside an outfit: back to it, now with the new piece
            # with what was there before, so that the page says what changed and can undo it (change_said). The
            # pop-up's form says what it showed; a form without it (an older pop-up) gets the piece as it was here.
            was, was_locked = request.form.get("was"), request.form.get("was_locked")
            if was is None or was_locked not in ("0", "1"):
                was = view.chosen.id if view.chosen and view.state != "owned" else ""
                was_locked = "1" if view.state == "locked" else "0"
            return redirect(url_for("outfits_page", at=request.form["outfit"][:400],
                                    occasion=request.form.get("occasion") or None,
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
        back = url_for("outfits_page", at=outfit or None, occasion=occasion if occasion in outfits.OCCASIONS else None)
        earlier = earlier_option(view, was) if locked == "1" else None
        if locked == "1" and earlier is None:
            flash(f"The product your {view.slot['name'].lower()} had before is no longer in {conf.SITE_NAME}'s product "
                  "list, so it can't be put back.")
            return redirect(back)
        if earlier is not None and earlier["price"] <= 0:     # as Choose refuses it (slot_pick)
            abort(409, "That item has no price yet. Add its price on the piece's page first.")
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
        db.update_slot(slot_id, owned=not slot["owned"])
        return after_slot_change(slot_id)

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
        page, far above it: those messages have their own kind, "import" (_slot_body.html, base.html)."""
        from .collect import manual

        slot = db.get_slot(slot_id)
        if slot is None:
            abort(404)
        links = [u for u in re.split(r"\s+", request.form.get("urls", "")) if u][:8]
        if not links:
            flash("Paste at least one product link.", "import")
            return redirect(url_for("slot_page", slot_id=slot_id, **way_back()) + "#add")
        # No browser is ever opened: only what the link itself says is taken.
        results = manual.from_urls(links, slot)

        def add(cat: dict) -> None:
            for _, cand, _ in results:
                if cand:
                    cat["candidates"] = [c for c in cat["candidates"]
                                         if not (c.get("slot_id") == slot_id and c.get("id") == cand["id"])]
                    cat["candidates"].append(cand)
        catalog.update(add)
        for link, cand, note in results:
            shown = link if len(link) <= 80 else link[:79] + "…"
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
        """Remove a candidate you added by hand."""
        cand_id = request.form.get("candidate", "")
        cand = catalog.find(catalog.load(), slot_id, cand_id)
        if cand is None or cand.get("source") != "manual":
            abort(404)
        slot = db.get_slot(slot_id)
        if slot and slot["pick"] == cand_id:
            db.update_slot(slot_id, locked=False, pick=None)
        catalog.update(lambda cat: cat.__setitem__("candidates", [
            c for c in cat["candidates"] if not (c.get("slot_id") == slot_id and c.get("id") == cand_id)]))
        flash(f"Removed “{cand['name']}” from this piece's options.")
        return redirect(url_for("slot_page", slot_id=slot_id, **way_back()))

    # ── Outfits ───────────────────────────────────────────────────────────────

    @app.get("/outfits")
    def outfits_page():
        w = selection.build()
        prof = profile_mod.load()
        occasion = request.args.get("occasion") or ("all" if prof["use"] == "both" else prof["use"])
        if occasion not in outfits.OCCASIONS and occasion != "saved":
            occasion = "all"
        try:
            n = max(4, min(60, int(request.args.get("n", 12))))
            seed = int(request.args.get("seed", 0))
        except ValueError:
            n, seed = 12, 0
        saved = db.saved_keys()
        said = None             # what a change just made from an outfit did (change_said)

        if occasion == "saved":
            now_picked = {s.slot["id"]: (s.chosen.id if s.chosen and s.state != "owned" else None) for s in w.slots}
            boards = []
            for fav in db.list_saved():
                as_saved = [dict(piece) for piece in outfits.with_roles(fav["pieces"])]
                for piece in fav["pieces"]:   # has the wardrobe moved on since this was saved?
                    piece["changed"] = (not piece["owned"]
                                        and now_picked.get(piece["slot_id"]) != piece["cand_id"])
                    if not piece["owned"] and piece.get("store") and not programmes.is_offered(piece["store"]):
                        outfits.no_longer_offered(piece)
                same_today = outfits.find(w, fav["key"])       # still one of today's outfits, product for product
                boards.append({"key": fav["key"], "sig": "", "label": fav["label"],
                               "pieces": outfits.with_roles(fav["pieces"]),
                               # Its picture is the one "See it worn" would draw: of today's pieces if it still exists,
                               # else of the pieces as they were saved (also where a store has gone since).
                               "look_pieces": outfits.snapshot(same_today) if same_today else as_saved,
                               "cost": round(sum(p["price"] for p in fav["pieces"]), 2),
                               "saved": True, "saved_at": catalog.collected_label({"collected_at": fav["saved_at"]})})
            total = len(boards)
        else:
            chosen, total = outfits.generate(w, occasion=occasion, limit=n, seed=seed)
            at = request.args.get("at", "")
            first = None
            if at:      # one particular combination, shown first: after a swap, or "wear something else here"
                first = outfits.find_by_sig(w, at)
                if first:
                    if not first.suits(occasion):
                        total += 1              # shown although it is not of this occasion: count it
                    chosen = [first] + [o for o in chosen if o.key != first.key]
                else:
                    flash("With that change the combination no longer passes the outfit rules, "
                          "so it is not shown. These do.")
            said = change_said(w, first)
            boards = [{"key": o.key, "sig": o.sig, "label": o.label, "pieces": outfits.snapshot(o), "cost": o.cost,
                       "saved": o.key in saved} for o in chosen]
        looks_on = looks.attach(boards)     # the AI picture of each outfit, if that is switched on
        return page("outfits.html", w=w, tab="outfits", boards=boards, total=total, n_saved=len(saved),
                    occasion=occasion, n=n, seed=seed, next_seed=random.randrange(1, 1_000_000),
                    looks_on=looks_on, said=said,
                    # Until the profile is saved, the starter banner stands where the budget bar would: a budget
                    # the customer never set says nothing yet. Saving the profile brings the bar back.
                    starter=starter_line() if prof["example"] else "",
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
                    **your_sizes())

    # ── AI pictures of outfits (looks.py) ─────────────────────────────────────

    def look_fragment(outfit_key: str, look: looks.Look | None) -> str:
        return render_template("_look.html", key=outfit_key, look=look,
                               auto=looks.load_rules()["pictures"]["auto"] and not looks.held_off())

    @app.post("/outfits/look")
    def outfits_look():
        """Ask for the picture of an outfit, or for a new version of it."""
        key = request.form.get("key", "")
        outfit = outfits.find(selection.build(), key)
        pieces = outfits.snapshot(outfit) if outfit else next(
            (fav["pieces"] for fav in db.list_saved() if fav["key"] == key), None)
        if pieces is None:
            abort(409, "That outfit no longer exists — reload the page.")
        look = looks.request(pieces, again=request.form.get("again") == "1")
        if look is None:
            abort(404)                      # AI pictures are switched off
        if not request.headers.get("HX-Request"):
            return redirect(request.referrer or url_for("outfits_page"))
        return look_fragment(key, look)

    @app.get("/outfits/look/<look_key>")
    def outfits_look_state(look_key: str):
        """Asked every few seconds while a picture is being drawn."""
        look = looks.get(look_key) if re.fullmatch(r"[0-9a-f]{24}", look_key) else None
        if look is None:
            abort(404)
        outfit_key = request.args.get("outfit", "")
        return look_fragment(outfit_key if re.fullmatch(r"[0-9a-f]{12}", outfit_key) else "", look)

    @app.get("/looks/<name>")
    def look_image(name: str):
        path = looks.image(name)
        if path is None:
            abort(404)
        response = send_file(path, mimetype=imagegen.MIME[path.suffix.lstrip(".")])
        response.headers["Cache-Control"] = "private, max-age=31536000, immutable"   # a new version gets a new name
        return response

    @app.post("/outfits/save")
    def outfits_save():
        """Heart button: save an outfit as a favourite, or forget it again."""
        key = request.form.get("key", "")
        if key in db.saved_keys():
            db.unsave_outfit(key)
            is_saved = False
        else:
            outfit = outfits.find(selection.build(), key)
            if outfit is None:   # the wardrobe changed under the page
                abort(409, "That outfit no longer exists — reload the page.")
            db.save_outfit(key, catalog.now_iso(), outfit.label, outfits.snapshot(outfit))
            is_saved = True
        if not request.headers.get("HX-Request"):
            return redirect(request.referrer or url_for("outfits_page"))
        return render_template("_save_button.html", key=key, saved=is_saved)

    # ── Shopping list ─────────────────────────────────────────────────────────

    def your_sizes() -> dict:
        """For the 'Your sizes' line at the top of the shopping list and of Buy this outfit (_your_sizes.html):
        the sizes every line there is ordered in, and whether they are still the example's."""
        you = profile_mod.load()
        return {"you": you, "example_sizes": profile_mod.sizes_unconfirmed(you)}

    @app.get("/list")
    def list_page():
        w = selection.build()
        return page("list.html", w=w, tab="list", sl=export.build(w), **your_sizes())

    @app.get("/list.md")
    def list_markdown():
        text = export.to_markdown(export.build(selection.build()))
        return Response(text, mimetype="text/markdown; charset=utf-8",
                        headers={"Content-Disposition": "attachment; filename=shopping-list.md"})

    @app.get("/list.csv")
    def list_csv():
        text = export.to_csv(export.build(selection.build()))
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
        flash(f"Added “{slot['name']}” to your plan." + (f" {REFRESH_HINT}" if needs_refresh else ""))
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
        flash(f"Saved “{fields['name']}”." + (f" {REFRESH_HINT}" if changed and needs_refresh else ""))
        return redirect(url_for("slots_page") + f"#slot-{slot_id}")

    @app.post("/slots/<slot_id>/delete")
    def slots_delete(slot_id: str):
        slot = db.get_slot(slot_id)
        if slot is None:
            abort(404)
        db.delete_slot(slot_id)
        db.set_setting("plan_edited", True)
        sync_catalog()
        flash(f"Removed “{slot['name']}” from your plan.")
        return redirect(url_for("slots_page"))

    @app.post("/slots/repropose")
    def slots_repropose():
        slots, unmatched = capsule.propose(profile_mod.load())
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
            return page("profile.html", tab="profile", profile=current, groups=person.GROUPS, model=model,
                        model_words=person.describe(model)[0] or rules["text"]["model"],
                        looks_on=chosen is not None, drawn_by=chosen.label if chosen else "the AI service",
                        photos=rules["pictures"]["photos"], has_photo=person.photo() is not None,
                        photo_added=catalog.collected_label({"collected_at": db.get_setting("photo_added")}),
                        # The one note while the answers are still the example's: the sizes may already be his
                        # ("These are my sizes"), and a plan edited on the plan page is not rebuilt by a save.
                        sizes_kept=current["example"] and not profile_mod.sizes_unconfirmed(current),
                        plan_kept=current["example"] and plan_edited(current))

        new, notes = profile_mod.from_form(request.form, current)
        profile_mod.save(new)
        for note in notes:
            flash(note)

        shapes_capsule = ("liked", "refused", "use", "shoes", "outerwear", "owned")
        # The plan has no tab of its own, so a message that sends you to it carries the link.
        # (Markup: the link is shown as a link; what the customer typed is still escaped.)
        same_plan = all(current[f] == new[f] for f in shapes_capsule)
        if same_plan and not current["example"]:        # sizes or budget: the plan stays as it is
            flash(Markup('Profile saved. <a href="%s">See your outfits</a>') % url_for("outfits_page"))
            return redirect(url_for("profile_page"))
        if plan_edited(current):        # a plan changed on the plan page is never rebuilt without asking
            if current["refused"] != new["refused"]:
                sync_catalog()          # its pieces stay, but no longer with products in a colour now refused
            flash(Markup("Profile saved. Your plan stays as you edited it. To rebuild it from these answers, use "
                         "“Start over from my profile” on <a href=\"%s\">the plan page</a>.") % url_for("slots_page"))
            return redirect(url_for("profile_page"))
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

    @app.post("/profile/sizes-ok")
    def profile_sizes_ok():
        """'These are my sizes', under the example sizes on the shopping list and on Buy this outfit: they are
        the customer's own, so the warning goes. Back to the page the button is on."""
        profile_mod.confirm_sizes()
        flash("Sizes saved.")
        at = request.form.get("at", "")[:400]       # pressed on one outfit's Buy page
        return redirect(url_for("outfits_buy", at=at) if at else url_for("list_page"))

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
                db.set_setting("photo_consent", PHOTO_CONSENT)      # beside photo_added: which words he agreed to
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
