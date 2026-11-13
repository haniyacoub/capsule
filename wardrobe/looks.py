"""AI pictures of an outfit being worn ("looks").

For each outfit an image service (imagegen.py) gets a written description:
who the model is (person.py), every piece from the outer layer down to the
shoes, and how the picture is to be taken. It sends back one picture. Nothing
else is sent: no name, no email, no sizes. Only when someone uploaded their own
photo does that photo go along.

Pictures are kept in <data>/looks/ and reused: the same description is never
paid for twice, whoever asks. Drawing takes up to a minute, so it runs in the
background while the page asks every few seconds whether it is done.

Each outfit is drawn in a studio first. Other scenes (a street, a library…)
are drawn only when the customer taps one under the picture: a scene changes
the words about the place and the light, and so is a picture of its own, with
its own name, kept, billed and counted like any other.

All of it is off until a key is set (settings.py). The wording, the service,
the limits and where the dots sit are in config/looks.toml.
"""
from __future__ import annotations

import hashlib
import logging
import os
import re
import threading
import time
import traceback
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from . import colours, composition, config, db, imagegen, outfits, paths, person, settings
from .config import ConfigError
from .garments import GARMENTS

log = logging.getLogger("capsule.looks")

STALE_SECONDS = imagegen.TIMEOUT + 60          # a drawing still "working" after this has died
QUEUE_SECONDS = 30 * 60                        # … and one still waiting its turn after this
FORGET_FAILURE_SECONDS = 3600                  # after this, or once the app was restarted, a failure is tried afresh
STARTED = time.time()                          # when this server process started
_TURNS = threading.BoundedSemaphore(2)         # pictures being drawn at once, per server process
IN_LINE = "Waiting its turn · two pictures are drawn at a time"
STUDIO = "studio"                              # the scene drawn by itself; the others only when tapped ([scenes])

# What went wrong, in words. The lines a customer can meet say "the AI". The four operator lines (OPERATORS) name
# the image service: customers of a public service only ever see CLOSED in their place (see _say).
SAY = {
    "photo": "The AI could not use your photo. Try a different one on the Profile page.",
    "key": "The image service did not accept the key.",
    "account": "The image service account cannot draw right now: no credit, a spending limit, or it still needs verifying.",
    "model": "The image service does not know the model named in config/looks.toml.",
    "request": "The image service did not accept the request.",
    "refused": "The AI declined to draw this outfit.",
    "busy": "The AI is busy or did not answer in time. Try again in a minute.",
    "empty": "The AI answered without a picture. Try again.",
    "stalled": "That took too long and was stopped. Try again.",
    "unknown": "Something went wrong while drawing. Try again.",
}
OPERATORS = {"key", "account", "model", "request"}      # nothing a customer can do about these …
CLOSED = "Pictures are not available at the moment."    # … so this is all they are told

# When the service itself is the problem, asking again at once only repeats the failure (and every
# outfit looked at would ask). So this server process holds off for a while: five minutes after a
# problem the operator has to fix, half a minute after "busy". Restarting the app clears it.
HOLD_OFF = {"operator": 300, "busy": 30}
_held: tuple[float, str] = (0.0, "")                    # (until when, what to say meanwhile)


def held_off() -> str | None:
    """What to say instead of drawing, while the service is being left alone; None when it is not."""
    until, message = _held
    return message if time.time() < until else None


# ── settings ──────────────────────────────────────────────────────────────────

def load_rules() -> dict:
    return config.load("looks.toml", _check)


def _check(data: dict) -> None:
    service = config.table(data.get("service"), "service")
    if service.get("use") not in ("auto", "openai", "google"):
        raise ConfigError('service.use must be "auto", "openai" or "google"')
    openai = config.table(service.get("openai"), "service.openai")
    google = config.table(service.get("google"), "service.google")
    for where, value in (("service.openai.model", openai.get("model")), ("service.google.model", google.get("model"))):
        if not isinstance(value, str) or not value.strip():
            raise ConfigError(f"{where} must be the name of a model")
    if openai.get("quality") not in ("low", "medium", "high"):
        raise ConfigError('service.openai.quality must be "low", "medium" or "high"')
    if google.get("image_size") not in ("1K", "2K", "4K"):
        raise ConfigError('service.google.image_size must be "1K", "2K" or "4K"')

    pictures = config.table(data.get("pictures"), "pictures")
    for name in ("auto", "photos"):
        if not isinstance(pictures.get(name), bool):
            raise ConfigError(f"pictures.{name} must be true or false")
    for name in ("per_day", "per_customer_per_day"):
        value = pictures.get(name)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ConfigError(f"pictures.{name} must be a whole number, 0 or more")

    text = config.table(data.get("text"), "text")
    for name in ("model", "scene", "scene_with_photo", "avoid"):
        if not isinstance(text.get(name), str) or not text[name].strip():
            raise ConfigError(f"text.{name} must be a sentence")
    for name in ("scene", "scene_with_photo"):        # without these every scene would be the same picture
        if "{photograph}" not in text[name] or "{setting}" not in text[name]:
            raise ConfigError(f"text.{name} must say where the scene's words go: {{photograph}} and {{setting}}")

    scenes = config.table(data.get("scenes"), "scenes")
    if STUDIO not in scenes:
        raise ConfigError(f"[scenes.{STUDIO}] is missing: it is the picture drawn by itself")
    if len(scenes) > 6:
        raise ConfigError("[scenes] has room for six scenes at most")
    for name, scene in scenes.items():
        if not re.fullmatch(r"[a-z]{1,20}", name):
            raise ConfigError(f"[scenes.{name}]: a scene's name is a word in small letters, like [scenes.street]")
        scene = config.table(scene, f"scenes.{name}")
        for part in ("label", "photograph", "setting"):
            if not isinstance(scene.get(part), str) or not scene[part].strip():
                raise ConfigError(f"scenes.{name}.{part} must be words")
        if len(scene["label"]) > 12:
            raise ConfigError(f"scenes.{name}.label must be one short word: it goes on a button under the picture")

    spots = config.table(data.get("hotspots"), "hotspots")
    for name in ("outer", "mid", "top", "collar", "bottom", "shoes"):
        pair = spots.get(name)
        if not (isinstance(pair, list) and len(pair) == 2
                and all(isinstance(v, (int, float)) and not isinstance(v, bool) and 0 <= v <= 100 for v in pair)):
            raise ConfigError(f"hotspots.{name} must be two percentages, like [50, 30]")


def service() -> imagegen.Service | None:
    """The image service to use, or None while no key for it is set."""
    rules = load_rules()["service"]
    keys = {"openai": settings.OPENAI_API_KEY, "google": settings.GEMINI_API_KEY}
    for name in (("openai", "google") if rules["use"] == "auto" else (rules["use"],)):
        if keys[name]:
            return imagegen.Service(name=name, model=rules[name]["model"], key=keys[name],
                                    quality=rules["openai"]["quality"], image_size=rules["google"]["image_size"])
    return None


def status() -> tuple[bool, str]:
    """(on?, one line saying which service draws, or what is missing)."""
    chosen = service()
    if chosen:
        return True, f"on — drawn by {chosen.label}, model {chosen.model}"
    if settings.UNUSABLE_KEYS:
        return False, (f"off — {' and '.join(settings.UNUSABLE_KEYS)} is set, but what is in it cannot be a key "
                       "(it has spaces, line breaks or characters such as “…”). Paste the key itself.")
    wanted = load_rules()["service"]["use"]
    need = {"openai": "OPENAI_API_KEY", "google": "GEMINI_API_KEY"}.get(wanted, "OPENAI_API_KEY or GEMINI_API_KEY")
    return False, f"off — set {need} and start the app again"


# ── the description sent to the image service ─────────────────────────────────

FITS = {"slim": "slim fit", "regular": "regular fit", "relaxed": "relaxed fit", "oversized": "oversized fit"}
_MODEL_NOTE = re.compile(r"^\s*(?:Größe des Models|Model height)\s*:?\s*\d+\s*cm\.?\s*", re.IGNORECASE)


def _clean(text: object, limit: int) -> str:
    """A store's text, safe to pass on: letters, digits and plain punctuation, cut to a sensible length."""
    out = re.sub(r"[^\w\s.,;:%/&+()'’-]", " ", str(text or "")).replace("_", " ")
    out = " ".join(out.split())
    return out if len(out) <= limit else out[:limit].rsplit(" ", 1)[0]


def _plain(text: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9äöüß]+", " ", text.lower()).split())


def _colour(piece: dict, trusted: bool) -> str:
    """'navy', or 'charcoal (the store calls it Dunkelgrau meliert)'. The store's name wins over its swatch."""
    named = colours.find(piece.get("colour"))
    key = named or colours.nearest(piece.get("hex"))[0]
    word = colours.get(key).label.lower() if key else ""
    theirs = _clean(piece.get("colour"), 40) if trusted else ""
    # Their name is passed on when it says more than ours: several words ("grey melange"), or one we don't know.
    if theirs and theirs.lower() != word and (named is None or " " in theirs):
        return f"{word} (the store calls it {theirs})" if word else theirs
    return word


def _fabric(piece: dict) -> str:
    """'wool', or 'wool and polyester blend': the one or two main fibres."""
    fibres = composition.parse(piece.get("composition")) or composition.guess(piece.get("name"))[0]
    main = [(fibre, share) for fibre, share in fibres if fibre != "other"][:2]
    if not main:
        return ""
    if len(main) == 1 or main[0][1] >= 80:
        return composition.label(main[0][0])
    return f"{composition.label(main[0][0])} and {composition.label(main[1][0])} blend"


def _garment(piece: dict) -> str:
    garment = GARMENTS.get(piece.get("category", ""))
    return garment.label if garment else "Garment"


def _worn(piece: dict, pieces: list[dict]) -> str:
    """How a layer sits over the others, so that everything in the outfit can be seen."""
    if piece.get("role") == "outer":
        return "worn open as the outer layer, so that what is underneath stays visible"
    if piece.get("role") == "mid":
        base = next((_garment(p).lower() for p in pieces if p.get("role") == "top"), "top")
        if piece.get("category") == "knit":
            return f"worn over the {base}, with the collar of the {base} showing at the neck"
        return f"worn open over the {base}"
    return ""


def _describe(piece: dict, pieces: list[dict]) -> str:
    # A public service passes on a store's words, never a customer's: what they
    # typed (slot names, links, items added by hand) stays out of the description.
    trusted = not settings.PRODUCTION or piece.get("source") == "collected"
    facts = [fact for fact in (_colour(piece, trusted), _fabric(piece), FITS.get(piece.get("fit") or "", "")) if fact]
    worn = _worn(piece, pieces)
    line = _garment(piece) + (f", {worn}" if worn else "") + (": " + ", ".join(facts) if facts else "") + "."
    if not trusted:
        return line
    if piece.get("owned"):
        named = _clean(piece.get("slot_name"), 60)
        return line + (f" Described as: {named}." if named else "")
    # The store's own name for the product. (`name` may be the slot's name, which a customer typed,
    # standing in for a product that has none: outfits saved before `store_name` existed only have that.)
    theirs = piece["store_name"] if "store_name" in piece else ("" if settings.PRODUCTION else piece.get("name"))
    name = _clean(theirs, 90)
    english = ""
    if piece.get("store") in ("cos", "weekday"):         # their web addresses carry the name in English
        english = _clean(re.sub(r"-\d{6,}$", "", piece.get("slug") or "").replace("-", " "), 90)
    about = _clean(_MODEL_NOTE.sub("", piece.get("description") or ""), 320).rstrip(".")
    if name:
        line += f" Sold as: {name}" + (f" ({english})" if english and _plain(english) != _plain(name) else "") + "."
    return line + (f" {about}." if about else "")


def scenes() -> list[tuple[str, str]]:
    """The scenes a picture can be drawn in, as (name, label), in the order of config/looks.toml."""
    return [(name, scene["label"]) for name, scene in load_rules()["scenes"].items()]


def scene_named(name: str | None) -> str:
    """`name` if it is a scene in config/looks.toml, else the studio: what a page asks for is checked here."""
    return name if name and name in load_rules()["scenes"] else STUDIO


def prompt(pieces: list[dict], rules: dict, who: person.Who, scene: str = STUDIO) -> str:
    """Everything the image service is told about one outfit, in one scene. A scene changes only the words
    about the photograph and the setting: the person, the pose, the pieces and what to avoid stay as they are."""
    pieces = outfits.with_roles(pieces)
    text = rules["text"]
    where = rules["scenes"].get(scene) or rules["scenes"][STUDIO]
    # The scene's words go in first, the person's after, so nothing in the person's words is ever read as a place.
    opening = text["scene_with_photo" if who.photo else "scene"]
    opening = opening.replace("{photograph}", where["photograph"]).replace("{setting}", where["setting"])
    if who.photo:
        opening = opening.replace("{body}", f"Their build: {who.body}. " if who.body else "")
    else:
        opening = opening.replace("{model}", who.words or text["model"])
    lines = [f"{number}. {_describe(piece, pieces)}" for number, piece in enumerate(pieces, 1)]
    if not any(piece.get("role") == "shoes" for piece in pieces):
        lines.append("Shoes are not part of this outfit: show plain, neutral ones.")
    return "\n".join([opening, "",
                      "The model wears exactly these pieces, listed from the outermost layer down to the shoes:",
                      *lines, "", text["avoid"]])


def fingerprint(chosen: imagegen.Service, text: str, mark: str = "") -> str:
    """The name of a picture: the same service, model, quality, person and description give the same one."""
    return hashlib.sha256("\x1f".join((chosen.tag, mark, text)).encode()).hexdigest()[:24]


def place_spots(pieces: list[dict], rules: dict) -> None:
    """Give each piece the place of its dot on the picture: piece["spot"] = [left %, top %]."""
    spots = rules["hotspots"]
    under_jumper = any(p.get("role") == "mid" and p.get("category") == "knit" for p in pieces)
    for piece in pieces:
        role = piece.get("role", "top")
        if under_jumper and role == "top":
            role = "collar"                     # only the shirt's collar shows
        elif under_jumper and role == "mid":
            role = "top"                        # the jumper covers the chest
        piece["spot"] = spots.get(role, spots["top"])


# ── one picture: where it stands ──────────────────────────────────────────────

@dataclass
class Look:
    key: str
    status: str                  # working | ready | failed | limit
    file: str | None = None      # the picture's name under /looks/ (kept while a new version is drawn)
    message: str = ""            # why it failed or is refused; when ready, why a new version was not drawn


def folder() -> Path:
    return paths.DATA_DIR / "looks"


def _view(row: dict | None) -> Look | None:
    """A database row as the page should see it. None: there is no picture and none is being drawn."""
    if row is None:
        return None
    if row["user_id"] is not None and row["user_id"] != db.uid():
        return None                              # drawn from somebody else's photo
    file = row["file"] if row["file"] and (folder() / row["file"]).is_file() else None
    state, message, now = row["status"], row["error"] or "", time.time()
    if state == "waiting" and row["started_at"] >= now - QUEUE_SECONDS:
        return Look(row["key"], "working", file, IN_LINE)
    if state == "working" and row["started_at"] >= now - STALE_SECONDS:
        return Look(row["key"], "working", file)
    if state in ("waiting", "working"):          # the server stopped while it waited or drew
        state, message = "failed", SAY["stalled"]
    # What went wrong is worth showing for a while. After an hour, or once the app was restarted,
    # it may have been put right: the message goes, and a picture that failed is tried afresh.
    if row["started_at"] < max(STARTED, now - FORGET_FAILURE_SECONDS):
        message = ""
    if file:                                     # there is a picture, whatever happened to the last attempt
        return Look(row["key"], "ready", file, message)
    if state == "failed" and message:
        return Look(row["key"], "failed", None, message)
    return None                                  # nothing to show: as if it had never been asked for


def get(key: str) -> Look | None:
    return _view(db.look_rows([key]).get(key))


_NAME = re.compile(r"([0-9a-f]{24})-\d{1,12}\.(?:jpg|png|webp)")


def image(name: str) -> Path | None:
    """The file of a picture, if there is one by that name and the signed-in user may see it."""
    match = _NAME.fullmatch(name)
    look = get(match.group(1)) if match else None
    return folder() / name if look and look.file == name else None


def attach(boards: list[dict]) -> bool:
    """Give every outfit on a page the state of its picture (board["look"], or None) and the
    places of its dots. Returns False, changing nothing, while AI pictures are off."""
    chosen = service()
    if chosen is None:
        return False
    rules = load_rules()
    who = person.current(rules["pictures"]["photos"])
    for board in boards:      # "look_pieces": what to describe, where that is not exactly what the board shows
        described = board.get("look_pieces") or board["pieces"]
        board["look_key"] = fingerprint(chosen, prompt(described, rules, who), who.mark)
    rows = db.look_rows([board["look_key"] for board in boards])
    for board in boards:
        board["look"] = _view(rows.get(board["look_key"]))
        place_spots(board["pieces"], rules)
    return True


# ── asking for a picture ──────────────────────────────────────────────────────

USED_UP = {
    "mine": "That's your {pictures} for today. More tomorrow.",     # "10 pictures": per_customer_per_day in config/looks.toml
    "all": "Today's pictures are used up.",
}


def request(pieces: list[dict], again: bool = False, scene: str = STUDIO) -> Look | None:
    """Start drawing one outfit in one scene, or say where that picture stands. None while AI pictures are off.

    Asking twice never pays twice: a finished picture is returned as it is
    (unless `again` asks for a new version), and one being drawn is left alone.
    Each scene is a picture of its own, so a new scene takes a turn of the day's allowance like any picture.
    """
    chosen = service()
    if chosen is None:
        return None
    rules = load_rules()
    who = person.current(rules["pictures"]["photos"])
    text = prompt(pieces, rules, who, scene_named(scene))
    key = fingerprint(chosen, text, who.mark)
    row = db.look_rows([key]).get(key)
    look = _view(row)
    if look and (look.status == "working" or (look.status == "ready" and not again)):
        return look
    def refused(why: str, status: str) -> Look:
        if look and look.status == "ready":      # the picture that is there stays; only the new version is refused
            look.message = why
            return look
        return Look(key, status, message=why)

    waiting = held_off()
    if waiting:
        return refused(waiting, "failed")
    now, limits = time.time(), rules["pictures"]
    ticket, used_up = db.take_look_ticket(now - 24 * 3600, limits["per_day"],
                                          limits["per_customer_per_day"] if settings.PRODUCTION else None)
    if not ticket:
        hint = "" if settings.PRODUCTION or used_up == "mine" else " The limit is per_day in config/looks.toml."
        allowance = limits["per_customer_per_day"]
        said = USED_UP[used_up].format(pictures="picture" if allowance == 1 else f"{allowance} pictures")
        return refused(said + hint, "limit")
    lost = row is not None and row["status"] == "ready" and look is None    # its file was deleted by hand
    owner = db.uid() if who.photo else None
    if db.start_look(key, chosen.tag, now - STALE_SECONDS, now - QUEUE_SECONDS, again=again or lost, owner=owner):
        photo = who.photo.read_bytes() if who.photo else None
        # A drawing turn that is free now is taken here, and the picture marked as being drawn, before the page is
        # answered: so the page says "Drawing this outfit", not "Waiting its turn", when nothing else is drawn.
        # Only when both turns are taken does the picture wait in line (in _draw), and the page says that.
        turn = _TURNS.acquire(blocking=False)
        handed_over = False
        try:
            if turn and not db.touch_look(key):  # gone already: its account was deleted a moment ago
                db.drop_look_request(ticket)
            else:
                _spawn(lambda: _draw(key, chosen, text, photo, ticket, turn))
                handed_over = True               # from here the drawing gives the turn back when it is done
        finally:
            # A turn taken here and not handed to a drawing (gone already, or an error before the drawing started)
            # is given back at once: otherwise it would stay taken until the server restarts.
            if turn and not handed_over:
                _TURNS.release()
    else:
        db.drop_look_request(ticket)             # somebody else asked for the same picture a moment ago
    return get(key) or Look(key, "working")


def _spawn(job) -> None:
    """Run `job` in the background (the tests swap this for running it at once)."""
    threading.Thread(target=job, name="look", daemon=True).start()


@contextmanager
def _a_turn(taken: bool):
    """One of the two drawing turns, held while a picture is drawn. `taken`: request() took it already;
    otherwise this waits in line until one is free."""
    if not taken:
        _TURNS.acquire()
    try:
        yield
    finally:
        _TURNS.release()


def _draw(key: str, chosen: imagegen.Service, text: str, photo: bytes | None, ticket: int, turn: bool = False) -> None:
    """Background: have the picture drawn and record how it went. Never raises.
    `ticket` is this request's entry in the day's count. It is given back only when the service
    certainly drew (and billed) nothing; anything else counts, which is what bounds "Try again".
    `turn`: request() found a drawing turn free, took it and marked the picture as being drawn.
    Without it, the picture waits in line here, and is checked again once its turn comes."""
    global _held
    with _a_turn(turn):
        try:
            waiting = None if turn else held_off()
            if waiting:                                  # the service failed for another picture meanwhile
                db.fail_look(key, waiting)
                db.drop_look_request(ticket)
                return
            if not turn and not db.touch_look(key):      # no longer wanted: its account went, or it was started afresh
                db.drop_look_request(ticket)
                return
            data, ext = imagegen.draw(chosen, text, photo)
            name = f"{key}-{int(time.time())}.{ext}"     # a new name each time, so browsers don't show the old one
            folder().mkdir(parents=True, exist_ok=True)
            tmp = folder() / (name + ".tmp")
            tmp.write_bytes(data)
            os.replace(tmp, folder() / name)
            try:
                before = db.finish_look(key, name)
            except LookupError:                          # the account was deleted meanwhile
                (folder() / name).unlink(missing_ok=True)
                return
            if before and before != name:
                (folder() / before).unlink(missing_ok=True)
            log.info("Drew look %s with %s", key, chosen.tag)
        except imagegen.DrawError as problem:
            if photo is not None and problem.kind == "request":
                # The request the service would not take carried this person's photo. That is their
                # problem to solve, not a reason to stop drawing for everybody, and it counts as theirs.
                problem = imagegen.DrawError("photo", problem.detail)
            said = _say(problem)
            db.fail_look(key, said)
            if problem.free:
                db.drop_look_request(ticket)
            wait = HOLD_OFF.get("operator" if problem.kind in OPERATORS else problem.kind)
            if wait:
                _held = (time.time() + wait, said)
            level = logging.ERROR if problem.kind in OPERATORS else logging.WARNING
            log.log(level, "Look %s was not drawn (%s): %s", key, problem.kind, problem.detail)
            _write_down(key, chosen, problem.kind, problem.detail)
        except Exception as error:
            # Never the exception's own words in a log that outlives the process: they could quote the key.
            trace = traceback.format_exc()
            log.error("Look %s was not drawn\n%s", key, trace.replace(chosen.key, "(the key)") if chosen.key else trace)
            db.fail_look(key, SAY["unknown"])
            _write_down(key, chosen, "unknown", type(error).__name__)


def _say(problem: imagegen.DrawError) -> str:
    """What the page shows. On your own machine, and on a service whose address is still this
    machine (a trial, no outside customers), the service's own words; to customers, nothing internal."""
    text = SAY.get(problem.kind, SAY["unknown"])
    if settings.PRODUCTION and not settings.on_this_machine():
        return CLOSED if problem.kind in OPERATORS else text
    return f"{text} {problem.detail.rstrip('.')}." if problem.detail else text


def _write_down(key: str, chosen: imagegen.Service, kind: str, detail: str) -> None:
    """Keep the reason a picture failed in <data>/looks/problems.log, where the operator can find it later."""
    try:
        folder().mkdir(parents=True, exist_ok=True)
        book_path = folder() / "problems.log"
        if book_path.exists() and book_path.stat().st_size > 512 * 1024:     # keep it readable: one older file, no more
            os.replace(book_path, folder() / "problems.old.log")
        with book_path.open("a", encoding="utf-8") as book:
            book.write(f"{db.now_iso()}  {kind:<8} {chosen.tag}  look {key}  {' '.join(detail.split())[:500]}\n")
    except OSError:
        pass                                             # the server log has it too


def forget_pictures_of(user_id: int) -> None:
    """Delete every picture drawn from a user's photo."""
    for name in db.drop_personal_looks(user_id):
        (folder() / name).unlink(missing_ok=True)


def forget_photo(user_id: int) -> None:
    """Delete a user's photo and every picture drawn from it. The photo goes first, so that no
    new picture of them can be started while the old ones are being removed."""
    person.remove_photo(user_id)
    forget_pictures_of(user_id)


# ── checking the key from the command line ────────────────────────────────────

def _sample_piece(role: str, category: str, colour: str, fabric: str, fit: str = "regular") -> dict:
    return {"role": role, "layer": role, "category": category, "owned": False, "hex": colours.get(colour).hex,
            "colour": colours.get(colour).label, "composition": fabric, "fit": fit, "name": "", "slug": "",
            "description": "", "source": "collected", "slot_name": ""}


SAMPLE = [
    _sample_piece("outer", "coat", "charcoal", "80% Wolle, 20% Polyamid", "relaxed"),
    _sample_piece("mid", "knit", "navy", "100% Merinowolle"),
    _sample_piece("top", "shirt", "white", "100% Baumwolle"),
    _sample_piece("bottom", "trousers", "grey", "70% Wolle, 30% Polyester"),
    _sample_piece("shoes", "sneakers", "white", "100% Leder"),
]


def sample() -> tuple[Path, float]:
    """Draw one made-up outfit on the standard model. Returns the file and how many seconds it took.
    Raises imagegen.DrawError with the service's own words if it does not work."""
    chosen = service()
    if chosen is None:
        raise imagegen.DrawError("key", "no key is set")
    started = time.time()
    data, ext = imagegen.draw(chosen, prompt([dict(piece) for piece in SAMPLE], load_rules(), person.Who()))
    folder().mkdir(parents=True, exist_ok=True)
    path = folder() / f"sample.{ext}"
    path.write_bytes(data)
    return path, time.time() - started
