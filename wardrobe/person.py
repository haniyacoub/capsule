"""Who wears the outfits in the AI pictures.

Either a model you put together from a few lists (age, height, build, skin,
hair, beard: choices only, nothing typed), or you yourself, from a photo you
upload. Both are optional; without them the pictures show the standard model
described in config/looks.toml.

The photo is kept in <data>/people/ under your user number and is sent to the
image service every time a picture of you is drawn. Removing it also removes
the pictures made from it (the app does that; see looks.forget_photo).
"""
from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path

from . import db, imagegen, paths

MAX_PHOTO = 6 * 1024 * 1024      # bytes; the page shrinks a photo to a fraction of this before sending it


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
    body: str = ""              # just the height and build (used alongside a photo)
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


def describe(choices: dict[str, str]) -> tuple[str, str]:
    """(the whole model in words, just height and build). Both are "" when nothing was chosen.

        ({"age": "30s", "height": "tall", "build": "athletic", "hair": "brown", "cut": "short"})
        -> ("an adult man in his thirties (tall, athletic build; short brown hair)", "tall, athletic build")
    """
    said = {group: next((o.words for o in options if o.key == choices.get(group)), "")
            for group, (_, options) in GROUPS.items()}
    body = ", ".join(part for part in (said["height"], said["build"]) if part)
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
    ext = imagegen.kind_of(data)
    if ext is None:
        return "That file is not a JPEG, PNG or WebP picture."
    if len(data) > MAX_PHOTO:
        return "That picture is too large. Use one under 6 MB."
    user_id = db.uid()
    remove_photo(user_id)
    _folder().mkdir(parents=True, exist_ok=True)
    target = _folder() / f"{user_id}.{ext}"
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, target)
    db.set_setting("photo_added", db.now_iso())      # when, and that consent was given then
    return None


def remove_photo(user_id: int) -> None:
    for ext in imagegen.MIME:
        (_folder() / f"{user_id}.{ext}").unlink(missing_ok=True)


def current(allow_photo: bool = True) -> Who:
    """The signed-in user's model: their photo if they uploaded one, else their choices, else nothing."""
    words, body = describe(load())
    path = photo() if allow_photo else None
    if path is None:
        return Who(words=words, body=body)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()[:16]
    return Who(words=words, body=body, photo=path, mark=f"{db.uid()}:{digest}")
