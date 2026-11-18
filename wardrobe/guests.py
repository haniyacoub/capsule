"""Visitors without an account ("guests"): one example wardrobe to look through, read-only.

Most websites open without a gate. With `guests = true` in config/site.toml (the default), someone who has no account,
or is not logged in, can open Outfits and swipe through the outfits of one example wardrobe, the same for every
visitor: the example profile (its example sizes, no photo) at the middle price level, Medium, with its pieces from
Stilsmith's own product list. He sees each outfit's title, its pieces by their names and colours, drawn as the app's
own colour drawings (never a store's photo), and its AI picture where one has been drawn already: of Stilsmith's house
model, never of anyone's photo.

What a visitor does not get is left out on the server, not hidden in the browser: the stores, the stores' names for
their products, prices and totals, what a yes would add, sizes, links and the stores' photos are not in the page at
all (app.py, guest_outfits and guest_piece, which build what is shown from nothing but what may be shown). In their
place are grey bars, and one line per outfit: "Create a free account to see the stores, prices and links." Every button
that would change or save something leads to "Create your account", with one line that says why (WHY).

How the example wardrobe is held: an account that Stilsmith keeps for itself (EXAMPLE_EMAIL), made at start-up on the
public site whatever the switch says (ensure_example), so that it is there before anyone visits. It has no password,
so nobody can log in to it. A visitor's request reads it through the same functions as a customer's (db.set_user),
with the database read-only for that request (db.set_read_only: SQLite itself refuses every write). So no visitor can
change what the next one sees, and nothing a visitor does is stored: no account, no row, no cookie.

On your own machine (not settings.PRODUCTION) none of this applies: there is no login there.
"""
from __future__ import annotations

import sys

from flask import g, redirect, request, url_for
from werkzeug.wrappers import Response

from . import capsule, catalog, config, db, mock, settings, shared
from . import profile as profile_mod
from .config import ConfigError

# The example wardrobe's account. ".invalid" is a name the internet keeps for addresses that can never exist
# (RFC 2606): no mail goes there, and no one else can have it.
EXAMPLE_EMAIL = "example-wardrobe@stilsmith.invalid"
EXAMPLE_LEVEL = "medium"        # the middle of the price levels (selection.MODES): Cheapest, Cheap, Medium, …

# What a visitor may open without an account: the outfits, the pop-up for one piece, and the AI picture of one of the
# example's outfits (its own address: app.example_picture; every other picture, at /looks/, needs an account).
LOOK_AROUND = {"outfits_page", "outfits_piece", "example_picture"}

# Why "Create your account" is shown, in one line over its form: by what was tapped (?why= in its address). Only
# these words are ever shown there: the address names one of them, it never carries words of its own.
WHY = {
    "save": "Create a free account to save outfits.",
    "no": "Create a free account to hide the outfits you don't like.",
    "change": "Create a free account to swap pieces and choose products.",
    "pictures": "Create a free account for more photos and videos of the outfits.",
    "you": "Create a free account to set your sizes, budget and price level.",
    "shop": "Create a free account to see the stores, prices and links.",
}
# While there is no published product list, every customer's products are the invented demo ones ("Demo data" on the
# page): then an account shows those, so the lines say "products and prices", not stores and links (as landing.html).
WHY_DEMO = {"shop": "Create a free account to see each piece's product and price."}
# Where the videos are off ("See it move", videos.py), the line about pictures promises none.
WHY_NO_VIDEOS = "Create a free account for more photos of the outfits."

# Which line goes with which button or page: the buttons a visitor sees (Add to my wardrobe, Not for me) and the
# other things the app's pages do, should a visitor's browser ask for one (a page from before, an old tab).
BY_ENDPOINT = {
    "outfits_save": "save",
    "outfits_no": "no",
    **dict.fromkeys(("slot_pick", "slot_restore", "slot_lock", "slot_own", "slot_keep", "slot_spare", "slot_colour",
                     "slot_import", "slot_details", "slot_remove", "slots_add", "slots_save", "slots_delete",
                     "slots_repropose", "outfits_tryon"), "change"),
    **dict.fromkeys(("outfits_look", "outfits_look_state", "outfits_photos", "outfits_video", "outfits_video_make",
                     "video_file", "look_full", "profile_picture", "profile_model"), "pictures"),
    **dict.fromkeys(("settings", "profile_page", "profile_sizes_ok", "profile_style_brief", "profile_style_say",
                     "profile_photo", "profile_photo_file", "welcome"), "you"),
    **dict.fromkeys(("outfits_buy", "list_page", "list_csv", "list_markdown"), "shop"),
}


def door_open() -> bool:
    """Whether visitors without an account may look around: on the public site, while config/site.toml says
    `guests = true`. A missing or broken file reads as closed, as the site was before the switch existed."""
    if not settings.PRODUCTION:
        return False
    try:
        return config.load("site.toml").get("guests", True) is True
    except ConfigError:
        return False


def reason(why: str | None, real: bool = True) -> str:
    """The line over "Create your account" for ?why=<why>, or "" for none (or a word that is not one of WHY's).
    `real`: whether the products are real ones from a published list (else the demo's words, WHY_DEMO). The line
    about pictures says only what is switched on: none while AI pictures are off, no videos while those are."""
    if not why or why not in WHY:
        return ""
    if why == "pictures":
        from . import looks, videos         # (here: they need nothing of this module, and most pages none of them)
        try:
            if looks.service() is None:
                return ""
            return WHY[why] if videos.service() is not None else WHY_NO_VIDEOS
        except ConfigError:                 # a typo in config/looks.toml: promise nothing
            return ""
    return WHY[why] if real else WHY_DEMO.get(why, WHY[why])


def sign_up(why: str | None = None) -> str:
    """The address of "Create your account", with the line that says why (WHY), if there is one."""
    return url_for("auth.signup", why=why) if why in WHY else url_for("auth.signup")


# ── the example wardrobe ──────────────────────────────────────────────────────


# Whether this server process has the example wardrobe: set at start-up once ensure_example has gone through. Until
# then (or if it failed: app.bootstrap says why in the log) visitors are sent to log in, as before the door opened.
_ready = False


def ensure_example() -> None:
    """At start-up on the public site: make the example wardrobe, or bring it up to date. It is what a new customer
    starts with (onboarding.ensure_setup: the example profile, the plan proposed for it, its products from the
    published list, or the demo ones while there is none), at the price level Medium. Written only where something
    differs, so a restart usually writes nothing. Several server processes may start at once: each writes the same."""
    global _ready
    _ready = False
    user_id = db.internal_account(EXAMPLE_EMAIL, make=True)
    if user_id is None:     # (only if a customer got this address first: his wardrobe is never shown to visitors)
        print(f"Warning: {EXAMPLE_EMAIL} belongs to an account with a password, so it cannot be the example "
              "wardrobe. Visitors without an account are sent to log in.", file=sys.stderr, flush=True)
        return
    with db.as_user(user_id):
        answers = dict(profile_mod.EXAMPLE)
        if db.get_setting("profile") != answers:
            db.set_setting("profile", answers)
        if db.get_setting("mode") != EXAMPLE_LEVEL:
            db.set_setting("mode", EXAMPLE_LEVEL)
        replanned = not db.get_setting("slots_initialised") or not capsule.same_plan(db.list_slots(), answers)
        if replanned:
            db.replace_slots(capsule.propose(answers)[0])
            db.set_setting("slots_initialised", True)
        pool = shared.load()
        products = shared.revision(pool) if pool and pool.get("products") else "demo"
        if replanned or db.get_setting("pool") != products or catalog.stored().get("source") == "empty":
            real = shared.build_catalog(db.list_slots(), None) if products != "demo" else None
            catalog.save(real or mock.build(db.list_slots()))
            db.set_setting("pool", products)
    _ready = True


def example_id() -> int | None:
    """The example wardrobe's account, or None while there is none (or it could not be set up at start-up)."""
    return db.internal_account(EXAMPLE_EMAIL) if _ready else None


def outfit(w, o, board: dict) -> dict:
    """One outfit as a visitor sees it (outfits_guest.html), made only of what may be shown, never of a product:
    its key and the pieces it combines (sig: the plan's ids, "navy-blazer~white-tee~…"), its title (label), and for
    each piece its name ("Dark brown loafers"), its kind of garment (for the app's own drawing of it) and its colour
    as the plan has it (name and hex), with the place of its dot on the picture (spot, once there is a picture).
    `picture`: the file of its front picture where one is there and finished (outfit_picture), else "": nothing is
    drawn for a visitor.
    `w`: the example wardrobe; `o`: the outfit (outfits.Outfit); `board`: its pieces (outfits.snapshot) and pictures."""
    pieces = []
    for p in board["pieces"]:
        colour = w.get(p["slot_id"]).colour
        pieces.append({"slot_id": p["slot_id"], "name": p["shown_name"], "category": p["category"],
                       "colour": colour.label, "hex": colour.hex, "spot": p.get("spot"),
                       # the app's own drawing of this kind of garment in the plan's colour (mockimg.py)
                       "drawing": url_for("mock_image", kind=p["category"], c=colour.hex.lstrip("#"), ground=0)})
    return {"key": o.key, "sig": o.sig, "label": o.label, "pieces": pieces, "picture": outfit_picture(board)}


def outfit_picture(board: dict) -> str:
    """The file of an outfit's front picture, where one is there and finished (looks.attach gave the board its
    pictures), else "". Pictures drawn from someone's photo are never among them (looks._view)."""
    photos = board.get("photos") or []
    front = photos[0].look if photos else None
    return front.file if front is not None and front.status == "ready" and front.file else ""


# ── at the door: before every request of a visitor without an account ─────────


def at_the_door() -> Response | None:
    """A visitor without an account asks for one of the app's pages or buttons (app.py, accounts_and_csrf; not a
    public page, not Stilsmith's own files, not the owner's pages). Returns None when he may look: the outfits of the
    example wardrobe, read-only (enter). Otherwise where he goes instead:
      - a button (a form sent, or a request from a page's script): "Create your account", with the line that says
        why (BY_ENDPOINT, WHY). From a page's script (HTMX) as an instruction to open that page (HX-Redirect).
      - a page (a link, an address typed in), and the Account page's own buttons (log out, a new password, deleting
        the account: they are for someone who has an account, whose login ran out): "Log in", as before the door
        opened, and back to that page after it.
    Nothing is checked or stored for any of these, so the token of a form (CSRF) is not needed: nothing happens."""
    endpoint = request.endpoint or ""
    if request.method in ("GET", "HEAD") and endpoint in LOOK_AROUND:
        user_id = example_id()
        if user_id is not None:
            enter(user_id)
            return None
    by_script = bool(request.headers.get("HX-Request"))
    a_page = request.method in ("GET", "HEAD", "OPTIONS") and not by_script
    if a_page:
        to = url_for("auth.login", next=request.full_path.rstrip("?"))
    elif request.blueprint == "auth":
        to = url_for("auth.login")
    else:
        to = sign_up(BY_ENDPOINT.get(endpoint))
    if by_script:
        return Response(status=401, headers={"HX-Redirect": to})
    return redirect(to)


def enter(user_id: int) -> None:
    """The rest of this request reads the example wardrobe, and may write nothing (left again in leave)."""
    g.guest = True
    if "user_token" in g:                       # (auth.load_user scoped the request to nobody)
        db.reset_user(g.pop("user_token"))
    g.user_token = db.set_user(user_id)         # auth.unload_user puts this back at the end of the request
    g.read_only_token = db.set_read_only(True)


def leave(_exc=None) -> None:
    """At the end of every request: a server thread serves the next request with nothing of this one left."""
    token = g.pop("read_only_token", None)
    if token is not None:
        db.reset_read_only(token)


def is_guest() -> bool:
    """Whether this request is a visitor's, looking at the example wardrobe."""
    return bool(g.get("guest"))
