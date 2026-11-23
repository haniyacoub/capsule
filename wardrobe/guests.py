"""Visitors without an account ("guests"): one example wardrobe to look through, read-only.

Most websites open without a gate, and many shops on their goods rather than on a page about themselves. With
`guests = true` in config/site.toml (the default), someone who has no account, or is not logged in, opens the home
page, "/", on the outfits of one example wardrobe (or Outfits, the same), the same for every visitor, to swipe through
(the website's own words are at /about): the example profile (its example sizes, no photo) with a budget of its own (config/site.toml,
`example_budget`: 600 €), planned for everyday and the office and fitted to that budget ("Best for budget"), with its
pieces from Stilsmith's own product list. He sees each outfit's title, its pieces by their names and colours, drawn as the app's
own colour drawings (never a store's photo), and its AI picture where one has been drawn already: of Stilsmith's house
model, never of anyone's photo. The outfits that have one come first (row). A visitor never causes a drawing: the owner
draws them by hand, after seeing what they would cost (python -m wardrobe example-pictures, __main__.py). With --clips
the owner also makes a short clip of the first outfits' pictures, which a visitor sees play in place of the picture
(videos.example_clips, at its own address: app.example_clip). On the row he first opens, his first three outfits carry
a hint each: what the example is in its own numbers (wardrobe_line: no price, no budget, no store's name), that a piece
can be tapped, and what the picture is (outfits_guest.html). He can put each away; nothing of that is kept.

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
from collections.abc import Callable

from flask import g, redirect, request, url_for
from werkzeug.wrappers import Response

from . import capsule, catalog, config, db, looks, mock, outfits, settings, shared, videos, yes
from . import profile as profile_mod
from .config import ConfigError

# The example wardrobe's account. ".invalid" is a name the internet keeps for addresses that can never exist
# (RFC 2606): no mail goes there, and no one else can have it.
EXAMPLE_EMAIL = "example-wardrobe@stilsmith.invalid"
EXAMPLE_LEVEL = "budget"        # "Best for budget" (selection.MODES): the whole plan fitted to the example's budget
EXAMPLE_BUDGET = 600            # € when config/site.toml names none (`example_budget`)

# What a visitor may open without an account: the outfits, the pop-up for one piece, and the AI picture and the clip of
# one of the example's outfits (their own addresses: app.example_picture and app.example_clip; every other picture, at
# /looks/, and every other video, at /videos/, needs an account). The home page, "/", is his outfits too (app.wardrobe).
LOOK_AROUND = {"outfits_page", "outfits_piece", "example_picture", "example_clip"}

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


def example_budget() -> int:
    """The budget the visitors' example wardrobe is planned and fitted for, in whole euros: config/site.toml's
    `example_budget` (EXAMPLE_BUDGET when it names none). Not the budget a new account starts with (profile.EXAMPLE):
    the example shows what Stilsmith plans for a fuller wardrobe. A value that is not an amount is a ConfigError,
    which app.bootstrap says in the log; visitors are then sent to log in until it is put right."""
    value = config.load("site.toml").get("example_budget", EXAMPLE_BUDGET)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not 1 <= value <= 100000:
        raise ConfigError(f"config/site.toml: example_budget must be an amount in euros from 1 to 100000, like 600, "
                          f"not {value!r}")
    return int(value)


def reason(why: str | None, real: bool = True) -> str:
    """The line over "Create your account" for ?why=<why>, or "" for none (or a word that is not one of WHY's).
    `real`: whether the products are real ones from a published list (else the demo's words, WHY_DEMO). The line
    about pictures says only what is switched on: none while AI pictures are off, no videos while those are."""
    if not why or why not in WHY:
        return ""
    if why == "pictures":
        from . import videos                # (here: it needs nothing of this module, and most pages none of it)
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
    published list, or the demo ones while there is none), but for its budget, its own (example_budget), which it
    has given: its colours, budget and what it dresses for are its answers ("answered"), so "Best for budget" fits
    the plan to that budget. Written only where something differs, so a restart usually writes nothing. A new
    budget is a new plan, made at the next start (its outfits' pictures must then be drawn again). Several server
    processes may start at once: each writes the same."""
    global _ready
    _ready = False
    user_id = db.internal_account(EXAMPLE_EMAIL, make=True)
    if user_id is None:     # (only if a customer got this address first: his wardrobe is never shown to visitors)
        print(f"Warning: {EXAMPLE_EMAIL} belongs to an account with a password, so it cannot be the example "
              "wardrobe. Visitors without an account are sent to log in.", file=sys.stderr, flush=True)
        return
    with db.as_user(user_id):
        answers = {**profile_mod.EXAMPLE, "budget": example_budget()}
        # What it dresses for, stored in one word before kinds were ticked ("both"), is the same answer as the kinds
        # everyday and the office: compared by what it means, so that no deploy rewrites it.
        stored = db.get_setting("profile")
        if stored is None or {**stored, "use": list(capsule.kinds_of(stored.get("use")))} != answers:
            db.set_setting("profile", answers)
        given = sorted(profile_mod.QUESTIONS)       # its budget, colours and what it dresses for (profile.answered)
        if db.get_setting("answered") != given:
            db.set_setting("answered", given)
        if db.get_setting("mode") != EXAMPLE_LEVEL:
            db.set_setting("mode", EXAMPLE_LEVEL)
        replanned = not db.get_setting("slots_initialised") or not capsule.same_plan(db.list_slots(), answers)
        if replanned:
            db.replace_slots(capsule.propose(answers)[0])
            db.set_setting("slots_initialised", True)
        elif example_locked():
            lock_pieces()       # to what it shows now, before a newer list (more stores) is brought in below
        pool = shared.load()
        products = shared.revision(pool) if pool and pool.get("products") else "demo"
        if replanned or db.get_setting("pool") != products or catalog.stored().get("source") == "empty":
            real = shared.build_catalog(db.list_slots(), None) if products != "demo" else None
            catalog.save(real or mock.build(db.list_slots()))
            db.set_setting("pool", products)
        if example_locked():
            lock_pieces()       # a new plan, or its first real products: locked from now on
    _ready = True


def example_locked() -> bool:
    """config/site.toml's `example_locked` (true when it says nothing): each piece of the example wardrobe is locked to
    the product it shows, once it has real products, so that a bigger product list (more stores) changes none of
    its products, outfits, pictures or clips (lock_pieces)."""
    try:
        return config.load("site.toml").get("example_locked", True) is not False
    except ConfigError:
        return True


def lock_pieces() -> int:
    """Lock each piece of the example wardrobe (the account of this request: ensure_example) to the product it shows
    now, as a customer's "Lock this choice" does, once its products are real ones (from a published list, not the
    demo's). A piece locked already keeps its lock; an owned one is left as it is. Returns how many were locked now.

    A lock holds while its product is among the piece's options, which are at most 6 a store (shared.candidates_for):
    publishing COS's and Weekday's products as they are keeps them there. A piece that shows no product cannot be
    held empty: should one get its first product from a bigger list, its outfits change, and the log says so."""
    from . import selection        # (here: selection builds on much of what this module needs)

    if catalog.stored().get("source") != "collected":
        return 0
    locked = 0
    for view in selection.build().slots:
        slot = view.slot
        if slot["owned"] or slot["locked"]:
            continue
        if view.chosen is None:
            print(f"Note: the example wardrobe's {slot['name'].lower()} shows no product, so it cannot be locked: "
                  "a bigger product list may give it one, and change its outfits.", file=sys.stderr, flush=True)
            continue
        db.update_slot(slot["id"], locked=True, pick=view.chosen.id)
        locked += 1
    return locked


def example_id() -> int | None:
    """The example wardrobe's account, or None while there is none (or it could not be set up at start-up)."""
    return db.internal_account(EXAMPLE_EMAIL) if _ready else None


def outfit(w, o, board: dict) -> dict:
    """One outfit as a visitor sees it (outfits_guest.html), made only of what may be shown, never of a product:
    its key and the pieces it combines (sig: the plan's ids, "navy-blazer~white-tee~…"), its title (label), and for
    each piece its name ("Dark brown loafers"), its kind of garment (for the app's own drawing of it) and its colour
    as the plan has it (name and hex), with the place of its dot on the picture (spot, once there is a picture).
    `picture`: the file of its front picture where one is there and finished (outfit_picture), else "": nothing is
    drawn for a visitor. `clip`: the file of the clip the owner's command made of that picture, where it is finished
    (videos.example_clips, which row gives each board), else "": nothing is made for a visitor either.
    `w`: the example wardrobe; `o`: the outfit (outfits.Outfit); `board`: its pieces (outfits.snapshot) and pictures."""
    pieces = []
    for p in board["pieces"]:
        colour = w.get(p["slot_id"]).colour
        pieces.append({"slot_id": p["slot_id"], "name": p["shown_name"], "category": p["category"],
                       "colour": colour.label, "hex": colour.hex, "spot": p.get("spot"),
                       # the app's own drawing of this kind of garment in the plan's colour (mockimg.py)
                       "drawing": url_for("mock_image", kind=p["category"], c=colour.hex.lstrip("#"), ground=0)})
    picture = outfit_picture(board)
    return {"key": o.key, "sig": o.sig, "label": o.label, "pieces": pieces, "picture": picture,
            "clip": board.get("clip", "") if picture else ""}


def outfit_picture(board: dict) -> str:
    """The file of an outfit's front picture, where one is there and finished (looks.attach gave the board its
    pictures), else "". Pictures drawn from someone's photo are never among them (looks._view)."""
    photos = board.get("photos") or []
    front = photos[0].look if photos else None
    return front.file if front is not None and front.status == "ready" and front.file else ""


# ── the row of outfits a visitor swipes through ───────────────────────────────

PAGE = 12       # the outfits on a visitor's first page, and how many more "Show more outfits" adds (as app.place)
MOST = 60       # the most outfits one page holds (as app.place)


def row(w, occasion: str, n: int = PAGE, seed: int = 0, front: list[str] | tuple[str, ...] = (),
        pictured: Callable[[dict], bool] | None = None) -> tuple[list[tuple[outfits.Outfit, dict]], int, bool]:
    """The outfits a visitor's Outfits page shows, in its order, each with its board: its pieces (outfits.snapshot),
    its pictures where they are there (looks.attach, which draws nothing) and the file of its clip where the owner's
    command made one (board["clip"], videos.example_clips). Returns (those outfits with their boards, how many outfits
    there are to see in all, whether AI pictures are on).
    The order is a customer's (yes.offer: varied; Shuffle is another `seed`), with one change: the outfits whose
    front picture is there (outfit_picture) come first, then the others, each group in that order.
    `front`: the outfits that were on the page before "Show more outfits" (their keys, in the order they were
    shown). They keep their places at the head of the row, so the visitor goes on from where he was; only the
    outfits behind them, the ones just added, are put in this order.
    `pictured`: which outfits count as having their picture, in place of the pictures there now: for the owner's
    command, which works out the order a visitor will see once the pictures it is about to draw are there.
    `w`: the example wardrobe (selection.build, as the example's account)."""
    chosen, total, _ = yes.offer(w, occasion, n, seed, front)
    boards = [{"key": o.key, "pieces": outfits.snapshot(o)} for o in chosen]
    looks_on = looks.attach(boards)
    if looks_on:
        videos.example_clips(boards)
    pairs = list(zip(chosen, boards))
    held = next((i for i, o in enumerate(chosen) if o.key not in front), len(chosen)) if front else 0
    has = pictured or (lambda board: bool(outfit_picture(board)))
    # A stable sort, so each group keeps the row's order: those with a picture (False) before those without.
    pairs[held:] = sorted(pairs[held:], key=lambda pair: not has(pair[1]))
    return pairs, total, looks_on


def first_outfits(w, n: int = PAGE,
                  pictured: Callable[[dict], bool] | None = None) -> list[tuple[outfits.Outfit, dict]]:
    """The first `n` outfits a visitor sees, in his order, with their boards (row): his first page, then each
    "Show more outfits" as he would press it, until there are `n` (at most MOST, as many as one page can hold).
    For the owner's command, python -m wardrobe example-pictures. `w`: the example wardrobe. `pictured`: as in row."""
    occasion = outfits.opens_on(profile_mod.load()["use"])     # the outfits his page opens on (as app.usual_occasion)
    pairs, total, _ = row(w, occasion, pictured=pictured)
    while len(pairs) < min(n, total, MOST):
        more, total, _ = row(w, occasion, min(len(pairs) + PAGE, MOST), 0, [o.key for o, _ in pairs], pictured)
        if len(more) <= len(pairs):                  # (nothing more to see)
            break
        pairs = more
    return pairs[:n]


# ── what the example is, in numbers, and the three hints on a visitor's first outfits ──────────

def numbers(w) -> dict:
    """The example wardrobe in its own real numbers: how many pieces its outfits are made of, from how many stores, and
    how many outfits they make ({"pieces": 12, "stores": 2, "outfits": 84}). The outfits are all it has (every
    occasion: a visitor's page names how many its own row shows); the pieces are the ones they wear, and the stores
    those pieces' products come from (a store is counted, never named). No price, no budget. `w`: the example."""
    every = outfits.all_outfits(w)
    worn = {slot_id for o in every for slot_id in o.slots}
    stores = {view.chosen.data.get("store") for view in w.slots
              if view.slot["id"] in worn and view.chosen is not None and view.state != "owned"}
    return {"pieces": len(worn), "stores": len(stores - {None, ""}), "outfits": len(every)}


def plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def wardrobe_line(count: dict, real: bool = True) -> str:
    """The first hint, on a visitor's first outfit: "12 pieces from 2 stores, combined into 84 outfits." From the
    example's real numbers (`count`, numbers), with no price or budget figure and no store's name. `real`: whether the
    products are real ones from a published list; the demo's invented products come from no store, so then no stores
    are counted ("12 pieces, combined into 84 outfits.")."""
    stores = f" from {plural(count['stores'], 'store')}" if real and count["stores"] else ""
    return f"{plural(count['pieces'], 'piece')}{stores}, combined into {plural(count['outfits'], 'outfit')}."


def description(count: dict) -> str:
    """What search results and shared links say of the home page a visitor opens (app.wardrobe): the example's
    outfits, in its real numbers (numbers), with no price, budget or store. "" while it has no outfits."""
    if not count["outfits"]:
        return ""
    return (f"Look through {plural(count['outfits'], 'menswear outfit')} made from {plural(count['pieces'], 'piece')} "
            "of one example wardrobe. Create a free account to plan your own, sized to your budget.")


# The second and third hints (outfits_guest.html says each where it belongs; the piece's in the words of a touch screen
# and of a mouse). The photo's sentence only while customers may upload a photo, and the picture's hint only on an
# outfit that shows its AI picture.
PIECE_HINT = ("Tap a piece to see what it is.", "Click a piece to see what it is.", "With an account you can swap it.")
PICTURE_HINT = "Drawn by AI on a model."
PHOTO_HINT = "Add your photo and it's you."


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
