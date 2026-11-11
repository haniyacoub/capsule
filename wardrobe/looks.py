"""AI pictures of an outfit being worn ("looks").

For each outfit an image service (imagegen.py) gets a written description:
who the model is (person.py), every piece from the outer layer down to the
shoes, and how the picture is to be taken. It sends back one picture. Nothing
else is sent: no name, no email, no sizes. Only when someone uploaded their own
photo does that photo go along.

Pictures are kept in <data>/looks/ and reused: the same description is never
paid for twice, whoever asks. Drawing takes up to a minute, so it runs in the
background while the page asks every few seconds whether it is done.

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
from dataclasses import dataclass
from pathlib import Path

from . import colours, composition, config, db, imagegen, outfits, paths, person, settings
from .config import ConfigError
from .garments import GARMENTS

log = logging.getLogger("capsule.looks")

STALE_SECONDS = imagegen.TIMEOUT + 60          # a drawing still "working" after this has died
FORGET_FAILURE_SECONDS = 3600                  # after this, or once the app was restarted, a failure is tried afresh
STARTED = time.time()                          # when this server process started
_TURNS = threading.BoundedSemaphore(2)         # pictures being drawn at once, per server process

SAY = {
    "key": "The image service did not accept the key.",
    "account": "The image service account cannot draw right now: no credit, a spending limit, or it still needs verifying.",
    "model": "The image service does not know the model named in config/looks.toml.",
    "request": "The image service did not accept the request.",
    "refused": "The image service declined to draw this outfit.",
    "busy": "The image service is busy or did not answer in time. Try again in a minute.",
    "empty": "The image service answered without a picture. Try again.",
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
    name = _clean(piece.get("name"), 90)
    english = ""
    if piece.get("store") in ("cos", "weekday"):         # their web addresses carry the name in English
        english = _clean(re.sub(r"-\d{6,}$", "", piece.get("slug") or "").replace("-", " "), 90)
    about = _clean(_MODEL_NOTE.sub("", piece.get("description") or ""), 320).rstrip(".")
    if name:
        line += f" Sold as: {name}" + (f" ({english})" if english and _plain(english) != _plain(name) else "") + "."
    return line + (f" {about}." if about else "")


def prompt(pieces: list[dict], rules: dict, who: person.Who) -> str:
    """Everything the image service is told about one outfit."""
    pieces = outfits.with_roles(pieces)
    text = rules["text"]
    if who.photo:
        opening = text["scene_with_photo"].replace("{body}", f"Their build: {who.body}. " if who.body else "")
    else:
        opening = text["scene"].replace("{model}", who.words or text["model"])
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
    state, message = row["status"], row["error"] or ""
    if state == "working" and row["started_at"] < time.time() - STALE_SECONDS:
        state, message = ("ready" if file else "failed"), SAY["stalled"]    # the server stopped mid-drawing
    elif state == "failed" and row["started_at"] < max(STARTED, time.time() - FORGET_FAILURE_SECONDS):
        return None                              # an old failure: whatever was wrong may have been fixed since
    if state == "ready" and file is None:
        return None                              # the file was deleted by hand: as if never drawn
    return Look(row["key"], state, file, message)


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
    for board in boards:
        board["look_key"] = fingerprint(chosen, prompt(board["pieces"], rules, who), who.mark)
    rows = db.look_rows([board["look_key"] for board in boards])
    for board in boards:
        board["look"] = _view(rows.get(board["look_key"]))
        place_spots(board["pieces"], rules)
    return True


# ── asking for a picture ──────────────────────────────────────────────────────

def _over_the_limit(rules: dict) -> str | None:
    since = time.time() - 24 * 3600
    limits = rules["pictures"]
    if settings.PRODUCTION and db.look_requests(since, mine=True) >= limits["per_customer_per_day"]:
        return "You have had today's pictures. There are more tomorrow."
    if db.look_requests(since) >= limits["per_day"]:
        return "Today's pictures are used up." + ("" if settings.PRODUCTION
                                                  else " The limit is per_day in config/looks.toml.")
    return None


def request(pieces: list[dict], again: bool = False) -> Look | None:
    """Start drawing one outfit, or say where its picture stands. None while AI pictures are off.

    Asking twice never pays twice: a finished picture is returned as it is
    (unless `again` asks for a new version), and one being drawn is left alone.
    """
    chosen = service()
    if chosen is None:
        return None
    rules = load_rules()
    who = person.current(rules["pictures"]["photos"])
    text = prompt(pieces, rules, who)
    key = fingerprint(chosen, text, who.mark)
    row = db.look_rows([key]).get(key)
    look = _view(row)
    if look and (look.status == "working" or (look.status == "ready" and not again)):
        return look
    waiting = held_off()
    refusal = waiting or _over_the_limit(rules)
    if refusal:
        if look and look.status == "ready":
            look.message = refusal
            return look
        return Look(key, "failed" if waiting else "limit", message=refusal)
    lost = row is not None and row["status"] == "ready" and look is None    # its file was deleted by hand
    owner = db.uid() if who.photo else None
    if db.start_look(key, chosen.tag, time.time() - STALE_SECONDS, again=again or lost, owner=owner):
        ticket = db.note_look_request()
        photo = who.photo.read_bytes() if who.photo else None
        _spawn(lambda: _draw(key, chosen, text, photo, ticket))
    return get(key) or Look(key, "working")


def _spawn(job) -> None:
    """Run `job` in the background (the tests swap this for running it at once)."""
    threading.Thread(target=job, name="look", daemon=True).start()


def _draw(key: str, chosen: imagegen.Service, text: str, photo: bytes | None, ticket: int) -> None:
    """Background: have the picture drawn and record how it went. Never raises.
    `ticket` is this request's entry in the day's count; a request that fails gives it back."""
    global _held
    with _TURNS:
        try:
            db.touch_look(key)
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
            said = _say(problem)
            db.fail_look(key, said)
            db.drop_look_request(ticket)
            wait = HOLD_OFF.get("operator" if problem.kind in OPERATORS else problem.kind)
            if wait:
                _held = (time.time() + wait, said)
            level = logging.ERROR if problem.kind in OPERATORS else logging.WARNING
            log.log(level, "Look %s was not drawn (%s): %s", key, problem.kind, problem.detail)
            _write_down(key, chosen, problem.kind, problem.detail)
        except Exception as error:
            log.exception("Look %s was not drawn", key)
            db.fail_look(key, SAY["unknown"])
            db.drop_look_request(ticket)
            _write_down(key, chosen, "unknown", f"{type(error).__name__}: {error}")


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
        with (folder() / "problems.log").open("a", encoding="utf-8") as book:
            book.write(f"{db.now_iso()}  {kind:<8} {chosen.tag}  look {key}  {' '.join(detail.split())[:500]}\n")
    except OSError:
        pass                                             # the server log has it too


def forget_pictures_of(user_id: int) -> None:
    """Delete every picture drawn from a user's photo."""
    for name in db.drop_personal_looks(user_id):
        (folder() / name).unlink(missing_ok=True)


def forget_photo(user_id: int) -> None:
    """Delete a user's photo and every picture drawn from it."""
    forget_pictures_of(user_id)
    person.remove_photo(user_id)


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
