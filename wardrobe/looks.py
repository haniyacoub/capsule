"""AI pictures of an outfit being worn ("looks").

For each outfit an image service (imagegen.py) gets a written description:
who the model is (person.py), every piece from the outer layer down to the
shoes, and how the picture is to be taken. It sends back one picture. The
model's words include the customer's body once he has entered it on Profile:
his height and build in a few words, and his chest against his waist, never
the numbers. Nothing else is sent: no name, no email, no clothing sizes. Only
when someone uploaded their own photo does that photo go along.

Pictures are kept in <data>/looks/ and reused: the same description is never
paid for twice, whoever asks. Drawing takes up to a minute, so it runs in the
background while the page asks every few seconds whether it is done.

Each outfit has up to six pictures. The first is the front picture: the man
standing, facing the camera, on a white studio background, drawn from the
words. It is the one drawn by itself and the one the dots sit on. The other
five (two more poses in the studio, three surroundings: [poses] and [scenes]
in config/looks.toml) are drawn only when the customer taps "More photos", and
they are made FROM the front picture: that picture is sent to the image service
with a short instruction ("the same man in the same outfit, now walking"), so
the man and the clothes are copied instead of being described, and drawn,
anew. Each is a picture of its own: kept, billed and counted like any other.
A picture made from a front picture belongs with it: when the front picture is
drawn again, the pictures made from the old one are deleted.

All of it is off until a key is set (settings.py). The wording, the service,
the limits and where the dots sit are in config/looks.toml. A finished picture
can also be made into a short video ("See it move"): videos.py.
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
FRONT = "front"                                # the picture drawn by itself; the others are made from it ([poses], [scenes])
FRONT_LABEL = "Front"

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
    for name in ("model", "scene", "scene_with_photo", "from_anchor", "avoid", "avoid_scene"):
        if not isinstance(text.get(name), str) or not text[name].strip():
            raise ConfigError(f"text.{name} must be a sentence")
    if "{model}" not in text["scene"]:
        raise ConfigError("text.scene must say where the model's description goes: {model}")
    if "{change}" not in text["from_anchor"]:      # without it every further picture would be the same one
        raise ConfigError("text.from_anchor must say where the pose's or the scene's words go: {change}")

    seen: set[str] = set()
    for group in ("poses", "scenes"):              # the pictures made from the front picture
        table = config.table(data.get(group) or {}, group)
        if len(table) > 6:
            raise ConfigError(f"[{group}] has room for six at most")
        for name, shot in table.items():
            if not re.fullmatch(r"[a-z]{1,20}", name):
                raise ConfigError(f"[{group}.{name}]: its name is a word in small letters, like [{group}.{'street' if group == 'scenes' else 'walking'}]")
            if name in (FRONT, "other") or name in seen:      # "other" names a movement ([videos.motion])
                raise ConfigError(f"[{group}.{name}]: that name is taken (the front picture, or another pose or scene)")
            seen.add(name)
            shot = config.table(shot, f"{group}.{name}")
            for part in ("label", "change"):
                if not isinstance(shot.get(part), str) or not shot[part].strip():
                    raise ConfigError(f"{group}.{name}.{part} must be words")
            if len(shot["label"]) > 12:
                raise ConfigError(f"{group}.{name}.label must be one short word: it names a small picture under the outfit")

    if data.get("videos") is not None:                 # "See it move" (videos.py); without [videos] it is off
        _check_videos(config.table(data["videos"], "videos"))

    spots = config.table(data.get("hotspots"), "hotspots")
    for name in ("outer", "mid", "top", "collar", "bottom", "shoes"):
        pair = spots.get(name)
        if not (isinstance(pair, list) and len(pair) == 2
                and all(isinstance(v, (int, float)) and not isinstance(v, bool) and 0 <= v <= 100 for v in pair)):
            raise ConfigError(f"hotspots.{name} must be two percentages, like [50, 30]")


def _check_videos(videos: dict) -> None:
    if not isinstance(videos.get("on"), bool):
        raise ConfigError("videos.on must be true or false")
    for name in ("model", "start", "keep"):
        if not isinstance(videos.get(name), str) or not videos[name].strip():
            raise ConfigError(f"videos.{name} must be " + ("the name of a model" if name == "model" else "words"))
    if not isinstance(videos.get("task", ""), str):
        raise ConfigError('videos.task must be "image_to_video", or "" to leave it out of the request')
    seconds = videos.get("turn_seconds")
    if isinstance(seconds, bool) or not isinstance(seconds, (int, float)) or not 1 <= seconds <= 8:
        raise ConfigError("videos.turn_seconds must be a number of seconds from 1 to 8 (the turn is 8 seconds long)")
    length = videos.get("seconds")
    if isinstance(length, bool) or not isinstance(length, int) or not 3 <= length <= 15:
        raise ConfigError("videos.seconds must be a whole number of seconds from 3 to 15 (what Google makes)")
    for name in ("per_day", "per_customer_per_day", "pro_per_customer_per_day"):
        value = videos.get(name)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ConfigError(f"videos.{name} must be a whole number, 0 or more")
    motion = config.table(videos.get("motion"), "videos.motion")
    for name in (FRONT, "other"):
        if name not in motion:
            raise ConfigError(f"videos.motion.{name} must be words: " + (
                "the movement of the front picture" if name == FRONT else "the movement of a picture that has no line of its own"))
    for name, words in motion.items():
        if not isinstance(words, str) or not words.strip():     # (a line for a pose that is gone is left alone)
            raise ConfigError(f"videos.motion.{name} must be words")


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


def _more(rules: dict) -> dict[str, tuple[str, str, bool]]:
    """The pictures made from the front picture, in the order of config/looks.toml, the poses before the scenes:
    name -> (its label, what the image service is told to change, whether it is a scene)."""
    return {name: (shot["label"], shot["change"], group == "scenes")
            for group in ("poses", "scenes") for name, shot in (rules.get(group) or {}).items()}


def shots() -> list[tuple[str, str]]:
    """An outfit's pictures as (name, label), in the order they are shown: the front picture, the poses, the scenes."""
    return [(FRONT, FRONT_LABEL)] + [(name, label) for name, (label, _, _) in _more(load_rules()).items()]


def shot_named(name: str | None) -> str:
    """`name` if it is one of an outfit's pictures, else the front picture: what a page asks for is checked here."""
    return name if name and name in _more(load_rules()) else FRONT


def _listed(pieces: list[dict]) -> list[str]:
    """The pieces as numbered lines, from the outermost layer down to the shoes."""
    lines = [f"{number}. {_describe(piece, pieces)}" for number, piece in enumerate(pieces, 1)]
    if not any(piece.get("role") == "shoes" for piece in pieces):
        lines.append("Shoes are not part of this outfit: show plain, neutral ones.")
    return lines


def prompt(pieces: list[dict], rules: dict, who: person.Who) -> str:
    """Everything the image service is told about one outfit for its front picture: who the model is, how the
    picture is taken, every piece, and what to avoid."""
    pieces = outfits.with_roles(pieces)
    text = rules["text"]
    if who.photo:
        opening = text["scene_with_photo"].replace("{body}", f"Their build: {who.body}. " if who.body else "")
    else:
        opening = text["scene"].replace("{model}", who.words or text["model"])
    return "\n".join([opening, "",
                      "The model wears exactly these pieces, listed from the outermost layer down to the shoes:",
                      *_listed(pieces), "", text["avoid"]])


def prompt_from(pieces: list[dict], rules: dict, shot: str) -> str:
    """What the image service is told, with the front picture, to make one of the further pictures from it: keep
    the man and the clothes, change only the pose or the place (`shot`: a name under [poses] or [scenes]). The
    pieces are listed again, as Google advises for keeping details. Nothing about the person is said in words: he
    is in the picture."""
    pieces = outfits.with_roles(pieces)
    text = rules["text"]
    _, change, in_a_scene = _more(rules)[shot]
    return "\n".join([text["from_anchor"].replace("{change}", change), *_listed(pieces), "",
                      text["avoid_scene" if in_a_scene else "avoid"]])


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


@dataclass
class Photo:
    """One of an outfit's pictures, as the row of small pictures under the outfit shows it."""
    name: str                    # front | a name under [poses] or [scenes]
    label: str                   # "Front", "Walking", "Café"
    look: Look | None = None     # where it stands; None: not asked for (or nothing to show)


def _made_from(chosen: imagegen.Service, rules: dict, pieces: list[dict], front: Look | None) -> dict[str, str]:
    """The names of the pictures made from this front picture: shot -> key. Empty until the front picture is there.
    The front picture's own file is part of each name: a front picture drawn again starts a new set."""
    if front is None or front.status != "ready" or not front.file:
        return {}
    return {name: fingerprint(chosen, prompt_from(pieces, rules, name), front.file) for name in _more(rules)}


def _photos(rules: dict, front: Look | None, keys: dict[str, str], rows: dict[str, dict]) -> list[Photo]:
    return [Photo(FRONT, FRONT_LABEL, front)] + [
        Photo(name, label, _view(rows.get(keys[name])) if name in keys else None)
        for name, (label, _, _) in _more(rules).items()]


def gallery(pieces: list[dict]) -> list[Photo] | None:
    """An outfit's pictures and where each stands, the front picture first. None while AI pictures are off."""
    chosen = service()
    if chosen is None:
        return None
    rules = load_rules()
    who = person.current(rules["pictures"]["photos"])
    front = get(fingerprint(chosen, prompt(pieces, rules, who), who.mark))
    keys = _made_from(chosen, rules, pieces, front)
    return _photos(rules, front, keys, db.look_rows(list(keys.values())))


def shown(photos: list[Photo], shot: str | None) -> Photo:
    """The picture to show large: the one asked for if there is anything of it to show (it is there, being drawn,
    or failed with a reason), else the front picture."""
    return next((photo for photo in photos if photo.name == shot and photo.look), photos[0])


def to_draw(photos: list[Photo]) -> int:
    """How many pictures "More photos" would start: those after the front one that are neither there nor being
    drawn. 0 until the front picture is there."""
    front = photos[0].look
    if front is None or front.status != "ready":
        return 0
    return sum(1 for photo in photos[1:] if not photo.look or photo.look.status not in ("ready", "working"))


def made_from_front(pieces: list[dict]) -> int:
    """How many of an outfit's other photos are there or being drawn: they are made from the front picture, and are
    removed when it is drawn again (forget_made_from). 0 while the front picture itself is not there."""
    photos = gallery(pieces) or []
    if not photos or not photos[0].look or photos[0].look.status != "ready":
        return 0
    return sum(1 for photo in photos[1:] if photo.look and photo.look.status in ("ready", "working"))


def videos_from_front(photos: list[Photo] | None) -> int:
    """How many videos go when an outfit's front picture is drawn again: its own and those of the photos made from
    it, made or being made (forget_made_from removes them with it). 0 while the front picture is not there."""
    from . import videos
    if not photos or not photos[0].look or photos[0].look.status != "ready":
        return 0
    found = (videos.of(photo.look, photo.name) for photo in photos if photo.look and photo.look.status == "ready")
    return sum(1 for video in found if video is not None and video.status in ("ready", "working"))


def redraw_words(photos: list[Photo] | None) -> tuple[str, int]:
    """What "Draw again" on a front picture asks first, and how many things it would remove: the other photos made
    from it, and the videos of it and of them. ("", 0) when it would remove nothing: then it is not asked."""
    photos = photos or []
    others = sum(1 for photo in photos[1:] if photo.look and photo.look.status in ("ready", "working"))
    if not photos or not photos[0].look or photos[0].look.status != "ready":
        others = 0
    n_videos = videos_from_front(photos)
    if not others and not n_videos:
        return "", 0
    said = "Draw the front picture again? "
    if others:
        said += ("The other photo of this outfit is made from it, so it" if others == 1 else
                 f"The other {others} photos of this outfit are made from it, so they") + " will be removed"
        if n_videos:
            said += (", and with them the video" if n_videos == 1 else f", and with them the {n_videos} videos") + \
                " made from these pictures"
        said += f". “More photos” draws {'it' if others == 1 else 'them'} again."
    else:
        said += ("Its video" if n_videos == 1 else f"Its {n_videos} videos") + " will be removed."
    if n_videos:
        said += f" “See it move” makes a new {'one' if n_videos == 1 else 'video'}, as one of your videos for the day."
    return said, others + n_videos


# ── a picture of the customer's own photo: his yes before it goes out again ──

# From this date on, the words a customer agrees to when he adds his photo (the box on Profile: their date is
# app.PHOTO_CONSENT, stored with the photo as photo_consent) say that an outfit's further photos are made from the
# AI picture of him, which goes to the image service again. Whoever added his photo under earlier words is asked
# once, before the first such photo is made (app.outfits_look, _look_ask.html). His yes is stored as
# more_photos_consent, with the photo it is about.
# (On the live site those words were shown from 16 Nov, some days before this date was stored with them. A photo
# added in those days carries the older date although its owner read the words: he is asked once all the same,
# which costs him one tap, and the question does not claim that he was never told.)
SENT_AGAIN_SAID = "2026-11-15"


def agreed_to_sending_again() -> bool:
    """Whether the signed-in customer agreed that the AI picture of him may go to the image service again, for an
    outfit's further photos: when he added his photo (the words of SENT_AGAIN_SAID or later ones), or since then,
    asked under an outfit's picture."""
    if str(db.get_setting("photo_consent") or "") >= SENT_AGAIN_SAID:
        return True
    later = db.get_setting("more_photos_consent")
    return isinstance(later, dict) and later.get("photo_added") == db.get_setting("photo_added")   # for this photo


def agree_to_sending_again() -> None:
    """He said yes under an outfit's picture: kept, for the photo he has now, so he is not asked again."""
    db.set_setting("more_photos_consent", {"words": SENT_AGAIN_SAID, "photo_added": db.get_setting("photo_added"),
                                           "at": db.now_iso()})


def needs_ok(pieces: list[dict]) -> bool:
    """Whether making another photo from this outfit's front picture needs the customer's yes first: the front
    picture is drawn from his own photo, and he has not agreed to its going to the image service again."""
    photos = gallery(pieces) or []
    front = photos[0].look if photos else None
    if front is None or front.status != "ready":
        return False                    # nothing is made from a front picture that is not there
    row = db.look_rows([front.key]).get(front.key) or {}
    return row.get("user_id") is not None and not agreed_to_sending_again()


def allowance_words() -> str:
    """The day's limit, as said beside "More photos" before it is tapped: "of your 30 a day"."""
    limits = load_rules()["pictures"]
    if settings.PRODUCTION:
        return f"of your {limits['per_customer_per_day']} a day"
    return f"of the day's {limits['per_day']}"


def left() -> int:
    """How many pictures the signed-in customer can still have drawn today: of his own allowance, and of the site's."""
    limits, since = load_rules()["pictures"], time.time() - 24 * 3600
    room = limits["per_day"] - db.look_requests(since)
    if settings.PRODUCTION:
        room = min(room, limits["per_customer_per_day"] - db.look_requests(since, mine=True))
    return max(0, room)


def more_words(wanted: int) -> str:
    """What "More photos" will cost, said beside it before it is tapped: "5 pictures of your 30 a day". With fewer
    left today than it would draw, how many it really draws: "Only 3 of the 5: 3 pictures left today";
    with none, "No pictures left today: more tomorrow" (and no button: app.css, _shots.html)."""
    can = left()
    if can >= wanted:
        return f"{wanted} {'picture' if wanted == 1 else 'pictures'} {allowance_words()}"
    if can == 0:
        return NONE_LEFT
    return f"Only {can} of the {wanted}: {can} {'picture' if can == 1 else 'pictures'} left today"


_NAME = re.compile(r"([0-9a-f]{24})-\d{1,12}\.(?:jpg|png|webp)")


def image(name: str) -> Path | None:
    """The file of a picture, if there is one by that name and the signed-in user may see it."""
    match = _NAME.fullmatch(name)
    look = get(match.group(1)) if match else None
    return folder() / name if look and look.file == name else None


def attach(boards: list[dict]) -> bool:
    """Give every outfit on a page its pictures and the places of its dots. Returns False, changing nothing, while
    AI pictures are off.

    board["photos"]: its pictures (Photo), the front one first. board["shot"] and board["look"]: the one shown large
    and its state (or None): the front picture, unless the page asked for another (board["shot"], a small picture
    tapped without JavaScript: app.outfits_look) and there is something of it to show."""
    chosen = service()
    if chosen is None:
        return False
    rules = load_rules()
    who = person.current(rules["pictures"]["photos"])
    for board in boards:      # "look_pieces": what to describe, where that is not exactly what the board shows
        board["look_key"] = fingerprint(chosen, prompt(board.get("look_pieces") or board["pieces"], rules, who), who.mark)
    rows = db.look_rows([board["look_key"] for board in boards])
    made = {}                 # for each outfit whose front picture is there: the names of the pictures made from it
    for board in boards:
        front = _view(rows.get(board["look_key"]))
        made[id(board)] = (front, _made_from(chosen, rules, board.get("look_pieces") or board["pieces"], front))
    rows = db.look_rows([key for _, keys in made.values() for key in keys.values()])
    for board in boards:
        front, keys = made[id(board)]
        board["photos"] = _photos(rules, front, keys, rows)
        large = shown(board["photos"], board.get("shot"))
        board["shot"], board["look"] = large.name, large.look
        place_spots(board["pieces"], rules)
    return True


# ── asking for a picture ──────────────────────────────────────────────────────

NONE_LEFT = "No pictures left today: more tomorrow"
USED_UP = {
    "mine": "That's your {pictures} for today. More tomorrow.",     # "30 pictures": per_customer_per_day in config/looks.toml
    "all": "Today's pictures are used up.",
}


def request(pieces: list[dict], again: bool = False, shot: str = FRONT) -> Look | None:
    """Start drawing one picture of an outfit, or say where that picture stands. None while AI pictures are off.

    `shot`: the front picture, or the name of one made from it ([poses], [scenes]). One of those needs the front
    picture to be there: until it is, asking for one asks for the front picture.

    Asking twice never pays twice: a finished picture is returned as it is
    (unless `again` asks for a new version), and one being drawn is left alone.
    Each of an outfit's pictures is one picture of the day's allowance.
    """
    chosen = service()
    if chosen is None:
        return None
    rules = load_rules()
    who = person.current(rules["pictures"]["photos"])
    text = prompt(pieces, rules, who)
    key = fingerprint(chosen, text, who.mark)
    row = db.look_rows([key]).get(key)
    # A picture made from the front picture: that picture goes to the image service with the words, and the new
    # one is named after both. It belongs to whoever the front picture belongs to (someone's own photo: only them).
    anchor: str | None = None            # the front picture's file
    reference: bytes | None = None       # … and what is in it
    owner = db.uid() if who.photo else None
    front = _view(row) if shot_named(shot) != FRONT else None
    if front and row and front.status == "ready" and front.file:
        try:
            reference = (folder() / front.file).read_bytes()
        except OSError:                  # deleted a moment ago (drawn again): the front picture is asked for instead
            reference = None
        if reference is not None:
            anchor, owner = front.file, row["user_id"]
            text = prompt_from(pieces, rules, shot)
            key = fingerprint(chosen, text, anchor)
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
    if db.start_look(key, chosen.tag, now - STALE_SECONDS, now - QUEUE_SECONDS, again=again or lost, owner=owner,
                     made_from=anchor):
        # The person's own photo goes with the front picture only: the others get the front picture, and he is in it.
        photo = who.photo.read_bytes() if who.photo and reference is None else None
        # A drawing turn that is free now is taken here, and the picture marked as being drawn, before the page is
        # answered: so the page says "Drawing this outfit", not "Waiting its turn", when nothing else is drawn.
        # Only when both turns are taken does the picture wait in line (in _draw), and the page says that.
        turn = _TURNS.acquire(blocking=False)
        handed_over = False
        try:
            if turn and not db.touch_look(key):  # gone already: its account was deleted a moment ago
                db.drop_look_request(ticket)
            else:
                try:
                    _spawn(lambda: _draw(key, chosen, text, photo, ticket, turn, reference))
                except Exception:
                    # The drawing could not start (no thread to run it): nothing was sent, so nothing counts, and
                    # the box says so with "Try again" rather than "Drawing" for minutes about nothing.
                    log.exception("Look %s could not be started", key)
                    db.fail_look(key, SAY["unknown"])
                    db.drop_look_request(ticket)
                    return get(key) or Look(key, "failed", message=SAY["unknown"])
                handed_over = True               # from here the drawing gives the turn back when it is done
        finally:
            # A turn taken here and not handed to a drawing (gone already, or an error before the drawing started)
            # is given back at once: otherwise it would stay taken until the server restarts.
            if turn and not handed_over:
                _TURNS.release()
    else:
        db.drop_look_request(ticket)             # somebody else asked for the same picture a moment ago
    return get(key) or Look(key, "working")


def request_more(pieces: list[dict]) -> str:
    """"More photos": start every picture after the front one that is neither there nor being drawn. Each is one
    picture of the day's allowance. Returns "" when all of them were started, else why the rest were not (the day's
    pictures are used up, the service is being left alone for a while): those are simply not started."""
    photos = gallery(pieces) or []
    if not photos or to_draw(photos) == 0:
        return ""
    for photo in photos[1:]:
        if photo.look and photo.look.status in ("ready", "working"):
            continue
        look = request(pieces, shot=photo.name)
        if look is not None and look.status in ("limit", "failed"):
            return look.message          # refused, or it failed at once: the next would go the same way
    return ""


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


def _draw(key: str, chosen: imagegen.Service, text: str, photo: bytes | None, ticket: int, turn: bool = False,
          reference: bytes | None = None) -> None:
    """Background: have the picture drawn and record how it went. Never raises.
    `reference`: the front picture this one is to be made from (one of an outfit's further pictures).
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
            if reference is None:
                data, ext = imagegen.draw(chosen, text, photo)
            else:
                data, ext = imagegen.draw(chosen, text, references=[reference])
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
                from . import videos                     # its videos showed the picture that is gone
                videos.forget_made_from(before)
                forget_made_from(before)                 # … and so did the pictures made from it
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
            _write_down(key, chosen.tag, problem.kind, problem.detail)
        except Exception as error:
            # Never the exception's own words in a log that outlives the process: they could quote the key.
            trace = traceback.format_exc()
            log.error("Look %s was not drawn\n%s", key, trace.replace(chosen.key, "(the key)") if chosen.key else trace)
            db.fail_look(key, SAY["unknown"])
            _write_down(key, chosen.tag, "unknown", type(error).__name__)


def _say(problem: imagegen.DrawError) -> str:
    """What the page shows. On your own machine, and on a service whose address is still this
    machine (a trial, no outside customers), the service's own words; to customers, nothing internal."""
    text = SAY.get(problem.kind, SAY["unknown"])
    if settings.PRODUCTION and not settings.on_this_machine():
        return CLOSED if problem.kind in OPERATORS else text
    return f"{text} {problem.detail.rstrip('.')}." if problem.detail else text


def _write_down(key: str, tag: str, kind: str, detail: str, what: str = "look") -> None:
    """Keep the reason a picture (or a video, videos.py) failed in <data>/looks/problems.log, where the operator
    can find it later. `tag`: which service and model."""
    try:
        folder().mkdir(parents=True, exist_ok=True)
        book_path = folder() / "problems.log"
        if book_path.exists() and book_path.stat().st_size > 512 * 1024:     # keep it readable: one older file, no more
            os.replace(book_path, folder() / "problems.old.log")
        with book_path.open("a", encoding="utf-8") as book:
            book.write(f"{db.now_iso()}  {kind:<8} {tag}  {what} {key}  {' '.join(detail.split())[:500]}\n")
    except OSError:
        pass                                             # the server log has it too


def forget_made_from(front: str) -> None:
    """Delete the pictures made from a front picture that was drawn again, and their videos: they show a man and
    clothes that the outfit's front picture no longer shows."""
    from . import videos
    for name in db.drop_looks_made_from(front):
        videos.forget_made_from(name)
        (folder() / name).unlink(missing_ok=True)


def forget_pictures_of(user_id: int) -> None:
    """Delete every picture drawn from a user's photo, and the videos made from those pictures (videos.py)."""
    from . import videos
    videos.forget_of(user_id)
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


def sample_set(report=lambda line: None) -> list[Path]:
    """Draw the made-up outfit's whole set: the front picture, then each further picture made from it (one picture
    billed for each: six with the settings as shipped). `report` is told each file as it is written. Returns the
    files, the front picture first. Raises imagegen.DrawError with the service's own words if one does not work."""
    front, seconds = sample()
    report(f"{front}  (front, {seconds:.0f} seconds)")
    chosen, rules, pieces = service(), load_rules(), [dict(piece) for piece in SAMPLE]
    if chosen is None:
        raise imagegen.DrawError("key", "no key is set")
    files = [front]
    for name in _more(rules):
        started = time.time()
        data, ext = imagegen.draw(chosen, prompt_from(pieces, rules, name), references=[front.read_bytes()])
        path = folder() / f"sample-{name}.{ext}"
        path.write_bytes(data)
        report(f"{path}  ({name}, made from the front picture, {time.time() - started:.0f} seconds)")
        files.append(path)
    return files
