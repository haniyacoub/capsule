"""Who wears the outfits in the AI pictures.

Either a model you put together from a few lists (age, height, build, skin,
hair, beard: choices only, nothing typed), or you yourself, from a photo you
upload. Both are optional; without them the pictures show the standard model
described in config/looks.toml.

The model's body follows your own: the height, weight, chest and waist on the
Profile page are turned into a few words ("a little shorter than average, lean
build"), never passed on as numbers; see "the body from Profile" below. Until
you enter your own, they are the example's and nothing is said about the body.

The photo is kept in <data>/people/ under your user number and is sent to the
image service every time a picture of you is drawn. Removing it also removes
the pictures made from it (the app does that; see looks.forget_photo).

What is kept is the picture and nothing else: the notes a camera or phone
writes into a photo file (where and when it was taken, on what device, a small
preview of the original) are cut out before it is stored, see tidy().
"""
from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path

from . import db, imagegen, paths
from . import profile as profile_mod

MAX_PHOTO = 2 * 1024 * 1024      # bytes; the page shrinks a photo to a fraction of this before sending it
MIN_SIDE, MAX_SIDE = 128, 8000   # pixels: smaller is no use to the image service, larger is not a photo

TOO_LARGE = "That photo is too large and could not be made smaller in this browser. Choose one under 2 MB."
NOT_A_PHOTO = ("That file is not a photo this can use. Choose a JPEG or PNG picture, at least 128 pixels a side. "
               "(Photos from an iPhone are often HEIC: save a copy as JPEG first.)")


@dataclass(frozen=True)
class Choice:
    key: str
    label: str        # on the page
    words: str        # in the description sent to the image service
    swatch: str = ""  # a colour to show beside it


# The menu. To add a choice, add a row; the words are what the image service reads.
GROUPS: dict[str, tuple[str, list[Choice]]] = {
    "age": ("Age", [
        Choice("20s", "20s", "in his twenties"), Choice("30s", "30s", "in his thirties"),
        Choice("40s", "40s", "in his forties"), Choice("50s", "50s", "in his fifties"),
        Choice("60s", "60+", "in his sixties")]),
    "height": ("Height", [
        Choice("short", "Short", "shorter than average"), Choice("medium", "Average", "of average height"),
        Choice("tall", "Tall", "tall")]),
    "build": ("Build", [
        Choice("slim", "Slim", "slim build"), Choice("athletic", "Athletic", "athletic build"),
        Choice("average", "Average", "average build"), Choice("broad", "Broad", "broad, sturdy build"),
        Choice("heavy", "Heavy", "heavy build")]),
    "skin": ("Skin", [
        Choice("fair", "Fair", "fair skin", "#f6e0cf"), Choice("light", "Light", "light skin", "#eac9a8"),
        Choice("medium", "Medium", "medium-toned skin", "#d2a37c"), Choice("tan", "Tan", "tan skin", "#b07d55"),
        Choice("brown", "Brown", "brown skin", "#7f5236"), Choice("dark", "Dark", "dark skin", "#4a2f22")]),
    "hair": ("Hair colour", [
        Choice("black", "Black", "black", "#1c1a19"), Choice("dark-brown", "Dark brown", "dark brown", "#3b2a20"),
        Choice("brown", "Brown", "brown", "#6b4a32"), Choice("blond", "Blond", "blond", "#d8b26a"),
        Choice("red", "Red", "red", "#a2502a"), Choice("grey", "Grey", "grey", "#a7a6a2")]),
    "cut": ("Hair", [
        Choice("shaved", "Shaved", "a shaved head"), Choice("short", "Short", "short"),
        Choice("medium", "Medium", "medium-length"), Choice("long", "Long", "long"),
        Choice("curly", "Curly", "short curly")]),
    "beard": ("Beard", [
        Choice("none", "None", "clean-shaven"), Choice("stubble", "Stubble", "light stubble"),
        Choice("short", "Short", "a short beard"), Choice("full", "Full", "a full beard")]),
}


@dataclass(frozen=True)
class Who:
    words: str = ""             # the model in words, if one was put together
    body: str = ""              # just the body: height, build, chest against waist (used alongside a photo)
    photo: Path | None = None   # the person's own photo, if they uploaded one
    mark: str = ""              # ties a picture of a real person to that person and that photo


# ── the model in words ────────────────────────────────────────────────────────

def load() -> dict[str, str]:
    """The choices made on the Profile page: {"build": "athletic", …}. Unset groups are absent."""
    return clean(db.get_setting("model") or {})


def save(choices: dict[str, str]) -> None:
    db.set_setting("model", clean(choices))


def clean(choices) -> dict[str, str]:
    """Only values that are on the menu survive; anything else is dropped."""
    return {group: str(choices[group]) for group, (_, options) in GROUPS.items()
            if choices.get(group) in {o.key for o in options}}


# ── the body from Profile, in words ───────────────────────────────────────────
#
# The image service is told about the body in words, never in numbers: a picture model asked for "172 cm, 95 kg"
# is as likely to print the numbers on the picture as to draw them, and words are what it draws from. They are the
# same few words for everyone in the same range, so they do not single anyone out.

# Height in cm, up to (not including) the first number: what the image service reads. Men in Germany are about
# 180 cm tall on average.
HEIGHTS: list[tuple[float, str]] = [
    (166, "clearly shorter than average"),
    (174, "a little shorter than average"),
    (187, "of average height"),
    (194, "tall"),
    (float("inf"), "very tall, with long legs"),
]


@dataclass(frozen=True)
class Build:
    below: float      # weight in kg divided by (height in metres, squared): this build up to here
    label: str        # on the page, under the drawn figure
    words: str        # in the description sent to the image service
    figure: str       # the build the drawn figure on Profile takes (figure.BUILDS)


# The build worked out from height and weight, where none is chosen in the menu. 78 kg at 180 cm gives 24: average.
BUILDS: list[Build] = [
    Build(20, "slim", "slim, narrow build", "slim"),
    Build(23, "lean", "lean build", "slim"),
    Build(26, "average", "average build", "average"),
    Build(29, "stocky", "solid, stocky build, a little soft round the middle", "broad"),
    Build(34, "heavy", "heavy build with a full stomach", "heavy"),
    Build(float("inf"), "very heavy", "very heavy build with a large, round stomach", "heavy"),
]

# Chest and waist are compared, not quoted: a chest this many cm larger than the waist is a marked V shape, and
# one less than this many cm larger is a straight middle.
CHEST_WELL_OVER_WAIST, CHEST_NEAR_WAIST = 16, 6

BODY = ("height_cm", "weight_kg", "chest_cm", "waist_cm")     # the body on the Profile page


def own_body(profile: dict | None) -> bool:
    """Whether the body on Profile is the customer's own: any of height, weight, chest or waist differs from the
    example's (180 cm, 78 kg, no chest, no waist). Until then nothing about it is said to the image service, so
    a customer who changed nothing is asked for in the same words as before and keeps the pictures he has."""
    if not profile:
        return False
    return any(profile.get(key) != profile_mod.EXAMPLE[key] for key in BODY)


def build_of(profile: dict) -> Build | None:
    """The build that height and weight give, or None where one of them is missing or makes no sense."""
    try:
        metres, kg = float(profile.get("height_cm") or 0) / 100, float(profile.get("weight_kg") or 0)
    except (TypeError, ValueError):
        return None
    if metres <= 0 or kg <= 0:
        return None
    ratio = kg / (metres * metres)
    return next(build for build in BUILDS if ratio < build.below)


def body_words(profile: dict | None) -> tuple[str, str, str]:
    """The body on Profile as the image service is told it: (height, build, chest against waist). Each is ""
    where there is nothing to say; all three are "" while the body is still the example's (own_body).

        ({"height_cm": 172, "weight_kg": 95, "chest_cm": 104, "waist_cm": 102})
        -> ("a little shorter than average", "heavy build with a full stomach", "waist about as wide as the chest")
    """
    if not profile or not own_body(profile):
        return "", "", ""
    try:
        cm = float(profile.get("height_cm") or 0)
    except (TypeError, ValueError):
        cm = 0
    height = next(words for below, words in HEIGHTS if cm < below) if cm > 0 else ""
    build = build_of(profile)
    shape = ""
    chest, waist = profile.get("chest_cm"), profile.get("waist_cm")
    if isinstance(chest, (int, float)) and isinstance(waist, (int, float)) and chest > 0 and waist > 0:
        if chest - waist >= CHEST_WELL_OVER_WAIST:
            shape = "broad chest and shoulders, narrow waist"
        elif chest < waist:
            shape = "waist wider than the chest"
        elif chest - waist < CHEST_NEAR_WAIST:
            shape = "waist about as wide as the chest"
    return height, build.words if build else "", shape


def describe(choices: dict[str, str], profile: dict | None = None) -> tuple[str, str]:
    """(the whole model in words, just the body). Both are "" when nothing was chosen and the body on Profile
    (`profile`) is still the example's.

    The body is the height, the build, and the chest against the waist. A height or build chosen in the menu is
    used as chosen; one left on "Any" comes from the customer's own body, once he has entered it.

        ({"age": "30s", "height": "tall", "build": "athletic", "hair": "brown", "cut": "short"})
        -> ("an adult man in his thirties (tall, athletic build; short brown hair)", "tall, athletic build")
        ({"hair": "brown", "cut": "short"}, {"height_cm": 172, "weight_kg": 60, …})
        -> ("an adult man (a little shorter than average, lean build; short brown hair)",
            "a little shorter than average, lean build")
    """
    said = {group: next((o.words for o in options if o.key == choices.get(group)), "")
            for group, (_, options) in GROUPS.items()}
    own_height, own_build, shape = body_words(profile)
    body = ", ".join(part for part in (said["height"] or own_height, said["build"] or own_build, shape) if part)
    if choices.get("cut") == "shaved":
        hair = said["cut"]
    else:
        hair = " ".join(part for part in (said["cut"], said["hair"]) if part)
        hair += " hair" if hair else ""
    features = [part for part in (body, said["skin"], hair, said["beard"]) if part]
    if not features and not said["age"]:
        return "", ""
    words = "an adult man" + (f" {said['age']}" if said["age"] else "")
    return words + (f" ({'; '.join(features)})" if features else ""), body


# ── the photo ─────────────────────────────────────────────────────────────────

def _folder() -> Path:
    return paths.DATA_DIR / "people"


def photo_of(user_id: int) -> Path | None:
    for ext in imagegen.MIME:
        path = _folder() / f"{user_id}.{ext}"
        if path.is_file():
            return path
    return None


def photo() -> Path | None:
    """The signed-in user's photo."""
    return photo_of(db.uid())


def save_photo(data: bytes) -> str | None:
    """Keep this picture as the user's photo. Returns what is wrong with it, or None when saved."""
    if len(data) > MAX_PHOTO:
        return TOO_LARGE
    tidied = tidy(data)
    if tidied is None:
        return NOT_A_PHOTO
    picture, ext = tidied
    user_id = db.uid()
    remove_photo(user_id)
    _folder().mkdir(parents=True, exist_ok=True)
    target = _folder() / f"{user_id}.{ext}"
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_bytes(picture)
    os.replace(tmp, target)
    db.set_setting("photo_added", db.now_iso())      # when, and that consent was given then
    return None


# ── only the picture: reading a photo file's structure ────────────────────────

def tidy(data: bytes) -> tuple[bytes, str] | None:
    """The picture in a JPEG or PNG file, without anything else the file carries, and its type.

    None if the file is not a well-formed JPEG or PNG of a sensible size. This walks the file's
    structure; it does not decode the picture, so a file can pass and still be rejected by the
    image service (looks.py then tells the person their photo could not be used).
    """
    kind = imagegen.kind_of(data)
    found = _jpeg(data) if kind == "jpg" else _png(data) if kind == "png" else None
    if found is None:
        return None
    picture, width, height = found
    if not (MIN_SIDE <= width <= MAX_SIDE and MIN_SIDE <= height <= MAX_SIDE):
        return None
    return picture, str(kind)


_JPEG_SIZE = {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}   # "start of frame"


def _jpeg(data: bytes) -> tuple[bytes, int, int] | None:
    """A JPEG is a row of segments, each starting 0xFF + a marker. Kept: everything the picture
    needs. Dropped: comments and the "application" segments, where Exif (place, time, device, a
    preview) and editing history live; the colour profile and Adobe's colour note stay. Whatever
    follows the end marker (phones append clips and second pictures there) is left out."""
    if data[:2] != b"\xff\xd8":
        return None
    out = bytearray(b"\xff\xd8")
    width = height = 0
    at, size = 2, len(data)
    while at + 2 <= size:
        if data[at] != 0xFF:
            return None
        marker = data[at + 1]
        if marker == 0xFF:                       # padding between segments
            at += 1
            continue
        if marker == 0xD9:                       # the end of the picture
            out += b"\xff\xd9"
            return (bytes(out), width, height) if width and height else None
        if at + 4 > size:
            return None
        length = int.from_bytes(data[at + 2:at + 4], "big")
        end = at + 2 + length
        if length < 2 or end > size:
            return None
        segment = data[at:end]
        if marker in _JPEG_SIZE and length >= 7:
            height, width = int.from_bytes(segment[5:7], "big"), int.from_bytes(segment[7:9], "big")
        colour_note = (marker == 0xE2 and segment[4:15] == b"ICC_PROFILE") or (marker == 0xEE and segment[4:9] == b"Adobe")
        if not (marker == 0xFE or (0xE1 <= marker <= 0xEF and not colour_note)):
            out += segment
        at = end
        if marker == 0xDA:                       # "start of scan": the picture data runs to the next real marker
            stop = _next_marker(data, at)
            if stop < 0:
                return None
            out += data[at:stop]
            at = stop
    return None


def _next_marker(data: bytes, at: int) -> int:
    """Where picture data ends: the next 0xFF that is not a stuffed 0xFF00 or a restart marker."""
    while True:
        at = data.find(b"\xff", at)
        if at < 0 or at + 1 >= len(data):
            return -1
        following = data[at + 1]
        if following == 0x00 or 0xD0 <= following <= 0xD7:
            at += 2
        elif following == 0xFF:
            at += 1
        else:
            return at


_PNG_PICTURE = {b"IHDR", b"PLTE", b"IDAT", b"IEND", b"tRNS", b"gAMA", b"cHRM", b"sRGB", b"iCCP", b"sBIT", b"pHYs"}


def _png(data: bytes) -> tuple[bytes, int, int] | None:
    """A PNG is a row of chunks: length, four-letter type, content, checksum. Kept: the ones the
    picture needs. Dropped: text, time, Exif, and anything unknown."""
    out = bytearray(data[:8])
    width = height = 0
    at = 8
    while at + 12 <= len(data):
        length, kind = int.from_bytes(data[at:at + 4], "big"), data[at + 4:at + 8]
        end = at + 12 + length
        if end > len(data) or (at == 8) != (kind == b"IHDR"):      # the header comes first, and only first
            return None
        if kind == b"IHDR":
            if length != 13:
                return None
            width, height = int.from_bytes(data[at + 8:at + 12], "big"), int.from_bytes(data[at + 12:at + 16], "big")
        if kind in _PNG_PICTURE:
            out += data[at:end]
        at = end
        if kind == b"IEND":
            return (bytes(out), width, height) if width and height else None
    return None


def remove_photo(user_id: int) -> None:
    for ext in imagegen.MIME:
        (_folder() / f"{user_id}.{ext}").unlink(missing_ok=True)


def current(allow_photo: bool = True) -> Who:
    """The signed-in user's model: their photo if they uploaded one, else their choices and their body from
    Profile, else nothing."""
    words, body = describe(load(), profile_mod.load())
    path = photo() if allow_photo else None
    if path is None:
        return Who(words=words, body=body)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()[:16]
    return Who(words=words, body=body, photo=path, mark=f"{db.uid()}:{digest}")
