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

import random
import re
import secrets
from datetime import timedelta
from urllib.parse import urlsplit

from flask import Flask, Response, abort, flash, g, redirect, render_template, request, send_file, url_for
from markupsafe import Markup
from werkzeug.exceptions import HTTPException

from . import (auth, capsule, catalog, colours, composition, db, export, imagegen, looks, mock, mockimg, outfits,
               person, scoring, selection, shared, tryon)
from . import profile as profile_mod
from . import settings as conf
from .onboarding import ensure_setup
from .config import ConfigError
from .garments import GARMENTS
from .paths import ROOT
from .sizes import ALPHA

NAV = [
    ("wardrobe", "Wardrobe", "wardrobe"),
    ("outfits", "Outfits", "outfits_page"),
    ("list", "List", "list_page"),
    ("slots", "Slots", "slots_page"),
    ("profile", "Profile", "profile_page"),
]


# Pages anyone may open without an account (production mode).
PUBLIC = {"static", "wardrobe", "legal_page", "healthz", "robots_txt", "mock_image",
          "auth.signup", "auth.login", "auth.forgot", "auth.reset"}
LEGAL_PAGES = {"impressum": "Impressum", "privacy": "Privacy policy", "terms": "Terms of use"}


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
    hand always stay. Returns True if real data now needs a refresh.
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
    return any(s["id"] not in filled and not s["owned"] for s in slots)


REFRESH_HINT = "Slots without candidates fill up at the next “python -m wardrobe refresh”."


def eur(value) -> str:
    value = float(value or 0)
    text = f"{value:,.0f}" if abs(value - round(value)) < 0.005 else f"{value:,.2f}"
    return f"{text} €"


def weblink(url) -> str:
    """Only ordinary web addresses become links; anything else in the data is ignored."""
    url = str(url or "").strip()
    return url if url.startswith(("https://", "http://")) else "#"


def _asset_version() -> int:
    static = ROOT / "wardrobe" / "static"
    return max((int(p.stat().st_mtime) for p in static.glob("*.*")), default=0)


def _pictures_on() -> bool:
    """Whether AI pictures are switched on. A typo in config/looks.toml must not take the public pages down."""
    try:
        return looks.service() is not None
    except ConfigError:
        return False


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
        app.register_blueprint(auth.bp)
    else:
        app.secret_key = secrets.token_hex(16)   # only signs the one-off "saved" messages
    app.jinja_env.trim_blocks = True
    app.jinja_env.lstrip_blocks = True
    app.jinja_env.filters["eur"] = eur
    app.jinja_env.filters["weblink"] = weblink
    app.jinja_env.globals.update(
        nav=NAV, GARMENTS=GARMENTS, COLOURS=colours.COLOURS, ALPHA=ALPHA,
        USES=profile_mod.USES, MODES=selection.MODES, OCCASIONS=outfits.OCCASIONS,
        STORES=scoring.STORE_LABELS, ink_on=colours.ink_on, level_hints=selection.HINTS,
    )
    bootstrap()

    def csrf_field() -> Markup:
        """The hidden input every form carries in production (nothing on your own machine)."""
        if not conf.PRODUCTION:
            return Markup("")
        return Markup('<input type="hidden" name="csrf_token" value="%s">') % auth.csrf_token()

    @app.context_processor
    def per_request_values():
        return {"asset_v": _asset_version(), "tryon_available": tryon.available(),
                "production": conf.PRODUCTION, "user": g.get("user"), "csrf_field": csrf_field,
                "csrf_token": auth.csrf_token if conf.PRODUCTION else (lambda: ""),
                "legal_pages": LEGAL_PAGES, "site_name": conf.SITE_NAME}

    @app.before_request
    def same_origin_only():
        # A page on some other website must not be able to press buttons here.
        origin = request.headers.get("Origin")
        if request.method == "POST" and origin and urlsplit(origin).netloc != request.host:
            abort(403)
        if request.endpoint == "profile_photo":     # the one form that carries a file
            request.max_content_length = person.MAX_PHOTO + 64 * 1024

    if conf.PRODUCTION:
        app.before_request(auth.load_user)
        app.teardown_request(auth.unload_user)

        @app.before_request
        def accounts_and_csrf():
            auth.check_csrf()
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

    @app.errorhandler(ConfigError)
    def config_error(err: ConfigError):
        return render_template("error.html", title="A config file needs fixing", message=str(err)), 500

    @app.errorhandler(HTTPException)
    def http_error(err: HTTPException):
        if request.headers.get("HX-Request") or err.code in (301, 302, 303, 307, 308):
            return err
        titles = {400: "That didn't go through", 403: "Not allowed", 404: "Page not found",
                  409: "That changed in the meantime", 413: "Too much data", 429: "Too many attempts",
                  501: "Not available yet"}
        return render_template("error.html", title=titles.get(err.code or 500, "Something went wrong"),
                               message=err.description or "", plain=True), err.code or 500

    @app.errorhandler(Exception)
    def unexpected_error(err: Exception):
        app.logger.exception("Unhandled error on %s %s", request.method, request.path)
        return render_template("error.html", title="Something went wrong",
                               message="The error was logged. Try again in a moment.", plain=True), 500

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
        """Re-render whichever view the button was pressed in."""
        db.set_setting("slots_customised", True)
        w = selection.build()
        if not request.headers.get("HX-Request"):   # plain form post (no JavaScript)
            return redirect(url_for("slot_page", slot_id=slot_id) if request.args.get("view") == "slot"
                            else url_for("wardrobe"))
        if request.args.get("view") == "slot":
            return fragment("_slot_body.html", w, **slot_context(w, slot_id))
        return fragment("_wardrobe_body.html", w)

    def slot_context(w: selection.Wardrobe, slot_id: str) -> dict:
        view = w.get(slot_id)
        if view is None:
            abort(404)
        sort = request.args.get("sort", "price")
        if sort == "score":
            cands = sorted(view.cands, key=lambda c: (not c.available, -c.score.total, c.price))
        else:
            sort, cands = "price", view.cands   # already: in stock first, then by price
        return {"s": view, "cands": cands, "sort": sort}

    # ── Wardrobe ──────────────────────────────────────────────────────────────

    @app.get("/")
    def wardrobe():
        if conf.PRODUCTION and g.user is None:
            return render_template("landing.html", looks_on=_pictures_on())      # the public website
        return page("wardrobe.html", tab="wardrobe")

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
        return page("slot.html", w=w, tab="wardrobe", **slot_context(w, slot_id))

    @app.post("/slot/<slot_id>/pick")
    def slot_pick(slot_id: str):
        view = selection.build().get(slot_id)
        cand_id = request.form.get("candidate", "")
        if view is None or not any(c.id == cand_id for c in view.cands):
            abort(404)
        # Choosing by hand locks the choice, so the price level can't undo it.
        db.update_slot(slot_id, pick=cand_id, locked=True, owned=False)
        if request.form.get("outfit"):      # swapped from inside an outfit: back to it, now with the new piece
            db.set_setting("slots_customised", True)
            return redirect(url_for("outfits_page", at=request.form["outfit"][:400],
                                    occasion=request.form.get("occasion") or None))
        return after_slot_change(slot_id)

    @app.post("/slot/<slot_id>/lock")
    def slot_lock(slot_id: str):
        view = selection.build().get(slot_id)
        if view is None:
            abort(404)
        if view.slot["locked"]:
            db.update_slot(slot_id, locked=False, pick=None)       # back to automatic
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

    # ── Adding and completing candidates by hand ──────────────────────────────

    @app.post("/slot/<slot_id>/import")
    def slot_import(slot_id: str):
        """Manual import: pasted product links become candidates (see collect/manual.py)."""
        from .collect import manual

        slot = db.get_slot(slot_id)
        if slot is None:
            abort(404)
        links = [u for u in re.split(r"\s+", request.form.get("urls", "")) if u][:8]
        if not links:
            flash("Paste at least one product link.")
            return redirect(url_for("slot_page", slot_id=slot_id) + "#add")
        # On a server no browser is ever opened: only what the link itself says is taken.
        results = manual.from_urls(links, slot, allow_fetch=not conf.PRODUCTION)

        def add(cat: dict) -> None:
            for _, cand, _ in results:
                if cand:
                    cat["candidates"] = [c for c in cat["candidates"]
                                         if not (c.get("slot_id") == slot_id and c.get("id") == cand["id"])]
                    cat["candidates"].append(cand)
        catalog.update(add)
        for link, cand, note in results:
            flash(f"{cand['name'] if cand else link}: {note}.")
        return redirect(url_for("slot_page", slot_id=slot_id) + "#add")

    @app.post("/slot/<slot_id>/details")
    def slot_details(slot_id: str):
        """Fill in what a store page didn't give: fabric, sizes in stock, price."""
        form = request.form
        cand_id = form.get("candidate", "")
        if catalog.find(catalog.load(), slot_id, cand_id) is None:
            abort(404)
        typed: dict = {}
        fabric = " ".join(form.get("composition", "").split())
        if fabric:
            if composition.parse(fabric):
                typed["composition_text"] = fabric
            else:
                flash(f"Couldn't read a composition from “{fabric}” — write it like “80% Wolle, 20% Polyamid”.")
        sizes_given = [s for s in re.split(r"[,;\s]+", form.get("sizes", "").strip()) if s]
        price_text = form.get("price", "").replace("€", "").replace(",", ".").strip()
        try:
            price = float(price_text) if price_text else None
        except ValueError:
            price = None
            flash(f"“{form.get('price')}” isn't a price.")

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
        flash("Details cleared." if form.get("clear") == "1" else "Details saved.")
        return redirect(url_for("slot_page", slot_id=slot_id, sort=request.args.get("sort", "price")))

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
        flash(f"Removed “{cand['name']}”.")
        return redirect(url_for("slot_page", slot_id=slot_id))

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

        if occasion == "saved":
            now_picked = {s.slot["id"]: (s.chosen.id if s.chosen and s.state != "owned" else None) for s in w.slots}
            boards = []
            for fav in db.list_saved():
                for piece in fav["pieces"]:   # has the wardrobe moved on since this was saved?
                    piece["changed"] = (not piece["owned"]
                                        and now_picked.get(piece["slot_id"]) != piece["cand_id"])
                boards.append({"key": fav["key"], "sig": "", "label": fav["label"],
                               "pieces": outfits.with_roles(fav["pieces"]),
                               "cost": round(sum(p["price"] for p in fav["pieces"]), 2),
                               "saved": True, "saved_at": catalog.collected_label({"collected_at": fav["saved_at"]})})
            total = len(boards)
        else:
            chosen, total = outfits.generate(w, occasion=occasion, limit=n, seed=seed)
            at = request.args.get("at", "")
            if at:      # one particular combination, shown first: after a swap, or "wear something else here"
                first = outfits.find_by_sig(w, at)
                if first:
                    chosen = [first] + [o for o in chosen if o.key != first.key]
                else:
                    flash("With that change the combination no longer passes the outfit rules, "
                          "so it is not shown. These do.")
            boards = [{"key": o.key, "sig": o.sig, "label": o.label, "pieces": outfits.snapshot(o), "cost": o.cost,
                       "saved": o.key in saved} for o in chosen]
        looks_on = looks.attach(boards)     # the AI picture of each outfit, if that is switched on
        return page("outfits.html", w=w, tab="outfits", boards=boards, total=total, n_saved=len(saved),
                    occasion=occasion, n=n, seed=seed, next_seed=random.randrange(1, 1_000_000),
                    looks_on=looks_on,
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
                               occasion=occasion if occasion in outfits.OCCASIONS else "")

    @app.get("/outfits/buy")
    def outfits_buy():
        """Everything in one outfit as a list to buy from, store by store."""
        w = selection.build()
        outfit = outfits.find_by_sig(w, request.args.get("at", ""))
        if outfit is None:
            abort(404)
        return page("buy.html", w=w, tab="outfits", outfit=outfit, sl=export.build(w, only=outfit.slots))

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

    @app.get("/list")
    def list_page():
        w = selection.build()
        return page("list.html", w=w, tab="list", sl=export.build(w))

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
            abort(501, "Virtual try-on is not built yet — see wardrobe/tryon.py.")
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
        prof = profile_mod.load()
        return page("slots.html", tab="slots", palette=capsule.palette_summary(prof), profile=prof)

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
        db.set_setting("slots_customised", True)
        needs_refresh = sync_catalog()
        flash(f"Added “{slot['name']}”." + (f" {REFRESH_HINT}" if needs_refresh else ""))
        return redirect(url_for("slots_page") + f"#slot-{slot['id']}")

    @app.post("/slots/<slot_id>/save")
    def slots_save(slot_id: str):
        slot, fields = db.get_slot(slot_id), slot_fields()
        if slot is None:
            abort(404)
        if fields is None:
            abort(400)
        changed = (fields["category"], fields["colour"]) != (slot["category"], slot["colour"])
        if changed:
            fields.update(locked=False, pick=None)   # different garment or colour: old pick no longer applies
        db.update_slot(slot_id, **fields)
        db.set_setting("slots_customised", True)
        needs_refresh = sync_catalog(changed_slot=slot_id if changed else None)
        flash(f"Saved “{fields['name']}”." + (f" {REFRESH_HINT}" if changed and needs_refresh else ""))
        return redirect(url_for("slots_page") + f"#slot-{slot_id}")

    @app.post("/slots/<slot_id>/delete")
    def slots_delete(slot_id: str):
        slot = db.get_slot(slot_id)
        if slot is None:
            abort(404)
        db.delete_slot(slot_id)
        db.set_setting("slots_customised", True)
        sync_catalog()
        flash(f"Removed “{slot['name']}”.")
        return redirect(url_for("slots_page"))

    @app.post("/slots/repropose")
    def slots_repropose():
        slots, unmatched = capsule.propose(profile_mod.load())
        db.replace_slots(slots)
        db.set_setting("slots_customised", False)
        needs_refresh = sync_catalog()
        flash(f"Capsule re-proposed from your profile: {len(slots)} slots." + (f" {REFRESH_HINT}" if needs_refresh else ""))
        for line in unmatched:
            flash(f"Couldn't tell what kind of garment “{line}” is — add it as a slot by hand.")
        return redirect(url_for("slots_page"))

    # ── Profile ───────────────────────────────────────────────────────────────

    @app.route("/profile", methods=["GET", "POST"])
    def profile_page():
        current = profile_mod.load()
        if request.method == "GET":
            rules = looks.load_rules()
            chosen = looks.service()
            model = person.load()
            return page("profile.html", tab="profile", profile=current, groups=person.GROUPS, model=model,
                        model_words=person.describe(model)[0] or rules["text"]["model"],
                        looks_on=chosen is not None, drawn_by=chosen.label if chosen else "the image service",
                        photos=rules["pictures"]["photos"], has_photo=person.photo() is not None,
                        photo_added=catalog.collected_label({"collected_at": db.get_setting("photo_added")}))

        new, notes = profile_mod.from_form(request.form, current)
        profile_mod.save(new)
        for note in notes:
            flash(note)

        shapes_capsule = ("liked", "refused", "use", "shoes", "outerwear", "owned")
        if all(current[f] == new[f] for f in shapes_capsule):
            flash("Profile saved.")
        elif db.get_setting("slots_customised", False):
            flash("Profile saved. Your slot list was left as it is, because you have already "
                  "edited, locked or marked things — “Re-propose from profile” on the Slots "
                  "page rebuilds it from scratch.")
        else:
            slots, unmatched = capsule.propose(new)
            db.replace_slots(slots)
            needs_refresh = sync_catalog()
            flash(f"Profile saved and the capsule re-proposed from it: {len(slots)} slots. "
                  "Review them under Slots." + (f" {REFRESH_HINT}" if needs_refresh else ""))
            for line in unmatched:
                flash(f"Couldn't tell what kind of garment “{line}” is — add it as a slot by hand.")
        return redirect(url_for("profile_page"))

    # ── The model in the AI pictures: a description, or your own photo (person.py) ──

    @app.post("/profile/model")
    def profile_model():
        person.save({group: request.form.get(group, "") for group in person.GROUPS})
        flash("Model saved. Pictures drawn from now on show it; open Outfits to see.")
        return redirect(url_for("profile_page") + "#model")

    @app.post("/profile/photo")
    def profile_photo():
        if not looks.load_rules()["pictures"]["photos"]:
            abort(404)
        if request.form.get("remove") == "1":
            looks.forget_photo(db.uid())
            flash("Your photo and the pictures made from it are deleted.")
            return redirect(url_for("profile_page") + "#model")
        upload = request.files.get("photo")
        data = upload.read(person.MAX_PHOTO + 1) if upload else b""
        if not data:
            flash("Choose a photo first.")
        elif request.form.get("agree") != "on":
            flash("Tick the box to confirm that it is a photo of you and may be sent to the image service.")
        else:
            problem = person.save_photo(data)
            if problem is None:
                looks.forget_pictures_of(db.uid())      # those showed the previous photo
            flash(problem or "Photo saved. Pictures drawn from now on show you; open Outfits to see.")
        return redirect(url_for("profile_page") + "#model")

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
