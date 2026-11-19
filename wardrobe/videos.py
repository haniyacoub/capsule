"""AI videos of outfits: "See it move".

An outfit has up to six AI pictures (looks.py): the front one, two more poses
and three surroundings. Under whichever of them is showing, "See it move" asks
Google's video model (videogen.py) for a clip that starts from exactly that
stored picture, with a movement that fits it: the front picture turns slowly on
the spot in one full circle and then poses (8 seconds), each other picture moves
naturally for a few seconds (walks on, lifts the cup, turns a page: 5 seconds).
The picture and one paragraph (config/looks.toml, [videos] start, the picture's
line under [videos.motion], keep) are all that is sent: no name, no email, no
sizes. Every clip is played muted.

Like the pictures (looks.py), a video is made in the background (about 40 seconds
to two minutes) while the page asks every few seconds how it is going; it is kept
in <data>/videos/ and never paid for twice: a picture has one video, whoever asks,
and it is shown again whenever that picture is showing.
A video of a picture drawn from someone's photo is theirs alone, like the picture:
shown only to them, and deleted with the picture, the photo and the account.

The example wardrobe's clips (example, make_example_now): the owner's command
(python -m wardrobe example-pictures --clips K) makes a 5-second clip of the front
picture of each of the first outfits that visitors without an account see, with a
movement of its own ([videos.motion] example), outside the day's limits. A visitor's
page plays it in place of the picture, muted and looping (example_clips). Nothing is
ever made for a visitor.

Drag to turn (the front picture's video only): where ffmpeg is installed, the
turn (the clip's first seconds) is kept a second time with every frame a keyframe, so that dragging across the
picture shows any moment of the turn at once. Without ffmpeg the clip itself is
dragged through, a little less smoothly.

Limits ([videos] in config/looks.toml), apart from the pictures': a video costs
about as much as twenty pictures, so each customer may ask for one a day, a Pro
account (and an owner) for five, and the whole site for ten. On your own machine
only the site's limit applies, as for pictures. Pro is a mark on an account:

    python -m wardrobe pro add EMAIL          the account must exist: sign up on the site first
    python -m wardrobe pro remove EMAIL
    python -m wardrobe pro list

There is nothing to buy: for now, Pro only means more videos a day.
"""
from __future__ import annotations

import argparse
import hashlib
import logging
import os
import re
import shutil
# subprocess runs ffmpeg only, with a fixed list of arguments and the app's own file names (turn_file).
import subprocess  # nosec B404
import sys
import threading
import time
import traceback
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from . import db, imagegen, looks, paths, settings, videogen

log = logging.getLogger("capsule.videos")

FFMPEG_SECONDS = 120                                   # making the turn file takes a second or two; never this long
STALE_SECONDS = videogen.TIMEOUT + FFMPEG_SECONDS + 60  # a video still "being made" after this has died
FORGET_FAILURE_SECONDS = 3600                          # after this, or once the app was restarted, a failure is forgotten
STARTED = time.time()                                  # when this server process started

# What went wrong, in words. The lines a customer can meet say "the AI"; the four operator lines (looks.OPERATORS)
# name Google, and customers of a public service only ever see CLOSED in their place (see _say).
SAY = {
    "refused": "The AI would not make a video of this picture.",
    "person": ("The AI would not make a video of this picture. It turns down some pictures of real, recognisable "
               "people, and this one is drawn from your photo."),
    "busy": "The AI is busy or did not answer in time. Try again in a minute.",
    "empty": "The AI answered without a video. Try again.",
    "stalled": "That took too long and was stopped. Try again.",
    "unknown": "Something went wrong while making the video. Try again.",
    "key": "Google did not accept the key (GEMINI_API_KEY).",
    "account": "Google's account cannot make videos right now: no credit, a spending limit, or no access to the model.",
    "model": "Google does not know the video model named in config/looks.toml, [videos] model.",
    "request": "Google did not accept the request for a video.",
}
CLOSED = "Videos are not available at the moment."
NONE_LEFT = "No videos left today: more tomorrow"
TICK_FIRST = "Not made. This picture is drawn from your photo: tick the box to agree to it going to Google first."

# The date of the words about videos that a customer agrees to before a picture drawn from his photo goes to Google
# for a video: in the photo's box on Profile (profile.html) or, for a photo added before those words or while videos
# were off, in the box of the video's offer (_video.html). Either way it is stored as video_consent, with the photo
# it is about (agreed_with_the_photo, request). Give it a new date whenever those words change.
# The photo box's other words have their own date (app.PHOTO_CONSENT, stored as photo_consent): the two are never
# compared. Until 15 Nov 2026 one setting held both: a photo added with the videos' words has photo_consent
# "2026-11-13" (WITH_THE_PHOTO_THEN) and no video_consent, and still counts as agreed.
CONSENT = "2026-11-13"
WITH_THE_PHOTO_THEN = "2026-11-13"


# ── settings ──────────────────────────────────────────────────────────────────

def rules() -> dict | None:
    """[videos] in config/looks.toml (checked by looks._check), or None where the file has none."""
    return looks.load_rules().get("videos")


def service() -> videogen.Service | None:
    """Google's video model, or None while videos are off: [videos] on = false, or no Gemini key is set.
    The video needs Google's key even where OpenAI draws the pictures."""
    chosen = rules()
    if not chosen or not chosen["on"] or not settings.GEMINI_API_KEY:
        return None
    return videogen.Service(model=chosen["model"], key=settings.GEMINI_API_KEY, task=chosen.get("task", ""))


def fingerprint(chosen: videogen.Service, text: str, picture: str, seconds: int = videogen.SECONDS) -> str:
    """The name of a video: the same model, words, length and picture file give the same one. A picture drawn
    again has a new file, so its video is a new one too."""
    return hashlib.sha256("\x1f".join((_tag(chosen, seconds), text, picture)).encode()).hexdigest()[:24]


def _tag(chosen: videogen.Service, seconds: int) -> str:
    """Which model made a clip and what kind it is, as kept with it: "google:<model>:9:16:720p:image_to_video:5s"."""
    return f"{chosen.tag}:{seconds}s"


# ── which picture, which movement ─────────────────────────────────────────────

@dataclass(frozen=True)
class Clip:
    """What "See it move" makes of one of an outfit's pictures."""
    shot: str                    # front | a name under [poses] or [scenes]
    label: str                   # "Front", "Walking", "Café": the picture's name on the page
    seconds: int                 # 8 for the turn, else [videos] seconds
    turns: bool                  # the front picture's turn: it can be dragged round
    text: str                    # what the video model is told, with the picture

    @property
    def says(self) -> str:
        """The offer's first sentence: which picture it animates, for how long, and what happens. Short: with
        "1 video left today." after it, it has two lines on a 320px phone and no more (_video.html)."""
        does = "he turns round once" if self.turns else "he moves naturally"
        return f"AI video of the {self.label} picture, {self.seconds} seconds: {does}."


def clip_of(shot: str | None) -> Clip:
    """The clip of the picture called `shot` (the front picture for a name that is not one): its length and the
    words that go to Google with the picture. A pose or a scene without a movement of its own gets "other"."""
    chosen = rules() or {}
    shot = looks.shot_named(shot)
    motion = chosen.get("motion") or {}
    words = motion.get(shot) or motion.get("other", "")
    text = " ".join(part.strip() for part in (chosen.get("start", ""), words, chosen.get("keep", "")) if part.strip())
    turns = shot == looks.FRONT
    return Clip(shot, dict(looks.shots()).get(shot, looks.FRONT_LABEL),
                videogen.SECONDS if turns else chosen.get("seconds", 5), turns, text)


def shot_of(look: looks.Look, photos: list[looks.Photo] | None) -> str | None:
    """Which of an outfit's pictures `look` is, found among the outfit's own (`photos`, looks.gallery): never
    taken from what a page sends, so a picture has one movement and one clip. Without the outfit, a picture that
    was not made from another is a front picture; anything else is not known (None)."""
    for photo in photos or []:
        if photo.look is not None and photo.look.key == look.key:
            return photo.name
    return None if db.look_made_from(look.key) else looks.FRONT


# ── one video: where it stands ────────────────────────────────────────────────

@dataclass
class Video:
    key: str
    status: str                  # working | ready | failed | limit | consent (the offer's box not ticked)
    file: str | None = None      # the clip's name under /videos/
    turn: str | None = None      # the turn with every frame a keyframe, for dragging (None: drag the clip itself)
    message: str = ""            # why it failed or cannot be made


def folder() -> Path:
    return paths.DATA_DIR / "videos"


def _view(row: dict | None) -> Video | None:
    """A database row as the page should see it. None: there is no video and none is being made."""
    if row is None:
        return None
    if row["user_id"] is not None and row["user_id"] != db.uid():
        return None                              # made from a picture of somebody else's photo
    file = row["file"] if row["file"] and (folder() / row["file"]).is_file() else None
    if file:
        turn = row["turn"] if row["turn"] and (folder() / row["turn"]).is_file() else None
        return Video(row["key"], "ready", file, turn)
    now = time.time()
    if row["status"] == "working" and row["started_at"] >= now - STALE_SECONDS:
        return Video(row["key"], "working")
    message = SAY["stalled"] if row["status"] == "working" else row["error"] or ""
    if row["started_at"] < max(STARTED, now - FORGET_FAILURE_SECONDS):
        message = ""                             # it may have been put right meanwhile: as if never asked for
    return Video(row["key"], "failed", message=message) if message else None


def get(key: str) -> Video | None:
    return _view(db.video_rows([key]).get(key))


def _key(chosen: videogen.Service, look: looks.Look, shot: str | None = None) -> str:
    clip = clip_of(shot)
    return fingerprint(chosen, clip.text, look.file or "", clip.seconds)


def of(look: looks.Look | None, shot: str | None = None) -> Video | None:
    """Where the video of this picture stands, or None (no video yet, or videos are off). `shot`: which of the
    outfit's pictures it is (the front one, unless said)."""
    chosen = service()
    if chosen is None or look is None or look.status != "ready" or not look.file:
        return None
    return get(_key(chosen, look, shot))


def attach(boards: list[dict]) -> bool:
    """Give every outfit on a page whose picture is ready the state of that picture's video (board["video"], or
    None), and what "See it move" would make of the picture showing (board["clip"]: board["shot"] says which of
    the outfit's pictures that is). Returns False, changing nothing, while videos are off."""
    chosen = service()
    if chosen is None:
        return False
    ready = [board for board in boards if board.get("look") and board["look"].status == "ready" and board["look"].file]
    keys = {id(board): _key(chosen, board["look"], board.get("shot")) for board in ready}
    rows = db.video_rows(list(keys.values()))
    for board in boards:
        board["clip"] = clip_of(board.get("shot"))
        board["video"] = _view(rows.get(keys[id(board)])) if id(board) in keys else None
    return True


def file_of(name: str) -> Path | None:
    """The file of a video (the clip or its turn), if there is one by that name and the signed-in user may see it."""
    match = _NAME.fullmatch(name)
    video = get(match.group(1)) if match else None
    return folder() / name if video and name in (video.file, video.turn) else None


_NAME = re.compile(r"([0-9a-f]{24})-\d{1,12}(?:-turn)?\.mp4")


# ── how many are left today ───────────────────────────────────────────────────

def is_pro(user_id: int) -> bool:
    """Pro, for the number of videos a day: an account marked with `python -m wardrobe pro add`, or an owner."""
    return db.is_pro(user_id) or db.is_owner(user_id)


def allowance() -> int | None:
    """How many videos the signed-in customer may ask for in a day. None on your own machine: no such limit."""
    chosen = rules() or {}
    if not settings.PRODUCTION:
        return None
    return chosen["pro_per_customer_per_day"] if is_pro(db.uid()) else chosen["per_customer_per_day"]


def left() -> int:
    """How many videos the signed-in customer can still ask for today: his own allowance, and the site's."""
    chosen, since = rules() or {}, time.time() - 24 * 3600
    room = chosen.get("per_day", 0) - db.video_requests(since)
    mine = allowance()
    if mine is not None:
        room = min(room, mine - db.video_requests(since, mine=True))
    return max(0, room)


NEARLY = 1      # videos left today at or under which the day's allowance is said (review N14): the last one


def left_words(number: int) -> str:
    """'1 video left today' for the last, or 'No videos left today: more tomorrow'; nothing ("") while more are
    left, so the offer does not read as rationed before it is used (review N14)."""
    if number <= 0:
        return NONE_LEFT
    if number > NEARLY:
        return ""
    return f"{number} video{'' if number == 1 else 's'} left today"


_TRY_AGAIN = re.compile(r" ?Try again(?: in a minute)?\.")


def told(message: str, left: int | None) -> str:
    """What the offer says about the last try (`message`), next to how many videos are `left` today. With none left,
    it ends "No videos left today: more tomorrow" and has no button to try with: so a failure's "Try again" is left
    out ("The AI is busy or did not answer in time. No videos left today: more tomorrow."), and a box to tick that
    is not there is not asked for (TICK_FIRST: the offer says what a video is instead)."""
    if left != 0:
        return message
    return "" if message == TICK_FIRST else _TRY_AGAIN.sub("", message)


# ── a picture of the customer's photo: his agreement first ───────────────────

def consented() -> bool:
    """Whether the signed-in customer agreed that pictures drawn from his photo may go to Google for videos: when
    he added the photo (the words of CONSENT's date, or later ones), or since then, in the video's offer."""
    if db.get_setting("photo_consent") == WITH_THE_PHOTO_THEN and CONSENT == WITH_THE_PHOTO_THEN:
        return True                     # a photo added before 15 Nov 2026, with the videos' words as they still are
    later = db.get_setting("video_consent")
    return (isinstance(later, dict) and str(later.get("words", "")) >= CONSENT
            and later.get("photo_added") == db.get_setting("photo_added"))    # for this photo, not an earlier one


def agreed_with_the_photo(videos_said: bool) -> None:
    """A photo was just added on Profile (app.profile_photo). `videos_said`: the box he ticked also said that
    pictures of him go to Google for videos: kept as video_consent, for this photo. Otherwise an earlier agreement
    is dropped: it was for the photo before this one."""
    if videos_said:
        db.set_setting("video_consent", {"words": CONSENT, "photo_added": db.get_setting("photo_added"),
                                         "at": db.now_iso()})
    elif db.get_setting("video_consent") is not None:
        db.set_setting("video_consent", None)


def needs_consent(look: looks.Look) -> bool:
    """Whether making this picture's video needs the customer's agreement first (see consented)."""
    row = db.look_rows([look.key]).get(look.key) or {}
    return row.get("user_id") is not None and not consented()


# ── asking for a video ────────────────────────────────────────────────────────

def request(look: looks.Look, agreed: bool = False, shot: str | None = None) -> Video | None:
    """Start making the video of this picture, or say where it stands. None while videos are off or the
    picture is not ready. `agreed`: the customer ticked the offer's box (needs_consent). `shot`: which of the
    outfit's pictures it is (shot_of; the front one unless said): its movement and its length follow from that.

    Asking twice never pays twice: a finished video is returned as it is, and one being made is left alone.
    A new one takes one of the day's videos, apart from the pictures' allowance.
    """
    chosen = service()
    if chosen is None or look.status != "ready" or not look.file:
        return None
    clip = clip_of(shot)
    text = clip.text
    key = fingerprint(chosen, text, look.file, clip.seconds)
    row = db.video_rows([key]).get(key)
    video = _view(row)
    if video and video.status in ("working", "ready"):
        return video
    # A video whose file has gone (its folder was emptied, say) is made again, like one never made.
    lost = row["file"] if row and row["file"] and row["user_id"] in (None, db.uid()) else None
    if needs_consent(look):
        if not agreed:
            return Video(key, "consent", message=TICK_FIRST)
        db.set_setting("video_consent", {"words": CONSENT, "photo_added": db.get_setting("photo_added"),
                                         "at": db.now_iso()})
    limits, now = rules() or {}, time.time()
    ticket, used_up = db.take_video_ticket(now - 24 * 3600, limits["per_day"], allowance())
    if not ticket:
        hint = "" if settings.PRODUCTION or used_up == "mine" else " The limit is per_day under [videos] in config/looks.toml."
        return Video(key, "limit", message=NONE_LEFT + "." + hint)
    picture_row = db.look_rows([look.key]).get(look.key) or {}
    owner = picture_row.get("user_id")             # a picture of someone's own photo: the video is theirs too
    if db.start_video(key, look.file, _tag(chosen, clip.seconds), owner, now - STALE_SECONDS, lost=lost):
        if lost and row and row["turn"]:
            _unlink([row["turn"]])                  # the turn of the lost clip, if it is still there
        try:
            picture = (looks.folder() / look.file).read_bytes()
        except OSError:                          # drawn again a moment ago: nothing was sent, nothing counts
            db.fail_video(key, SAY["unknown"])
            db.drop_video_request(ticket)
            return get(key)
        try:
            _spawn(lambda: _make(key, chosen, clip, picture, ticket, owner is not None))
        except Exception:
            # The making could not start (no thread to run it): nothing was sent, so the day's video is given back,
            # and the offer under the picture says so with "Try again", not "Making the video" for minutes about nothing.
            log.exception("Video %s could not be started", key)
            db.fail_video(key, SAY["unknown"])
            db.drop_video_request(ticket)
            return get(key) or Video(key, "failed", message=SAY["unknown"])
    else:
        db.drop_video_request(ticket)            # somebody asked for the same video a moment ago
    return get(key) or Video(key, "working")


def _spawn(job) -> None:
    """Run `job` in the background (the tests swap this for running it at once)."""
    threading.Thread(target=job, name="video", daemon=True).start()


def _make(key: str, chosen: videogen.Service, clip: Clip, picture: bytes, ticket: int,
          personal: bool) -> imagegen.DrawError | None:
    """Background: have the clip made, keep it (and, for the front picture's, its turn for dragging) and record how
    it went. Never raises. `ticket` is this request's entry in the day's count, given back only when Google certainly made (and billed)
    nothing (0: nothing was counted, the owner's command, make_example_now). `personal`: the picture is drawn from the
    customer's own photo.
    Returns what went wrong when making it failed: Google's own words, or the kind of error. None when it was made (or
    its account was deleted meanwhile). The owner's command prints it (make_example_now); a page shows the row's words
    instead (_say)."""
    try:
        data = videogen.make(chosen, picture, clip.text, seconds=clip.seconds)
        stamp = int(time.time())                 # a new name each time, so browsers don't show an old one
        name, turn_name = f"{key}-{stamp}.mp4", f"{key}-{stamp}-turn.mp4"
        folder().mkdir(parents=True, exist_ok=True)
        tmp = folder() / (name + ".tmp")
        tmp.write_bytes(data)
        os.replace(tmp, folder() / name)
        turn = turn_file(folder() / name, folder() / turn_name) if clip.turns else None
        try:
            db.finish_video(key, name, turn.name if turn else None)
        except LookupError:                      # the account was deleted meanwhile
            for path in (folder() / name, turn):
                if path:
                    path.unlink(missing_ok=True)
            return None
        log.info("Made video %s (%s) with %s", key, clip.shot, _tag(chosen, clip.seconds))
        return None
    except imagegen.DrawError as problem:
        if personal and problem.kind in ("refused", "request"):
            problem = imagegen.DrawError("person", problem.detail, problem.free)
        said = _say(problem)
        db.fail_video(key, said)
        if problem.free:
            db.drop_video_request(ticket)
        level = logging.ERROR if problem.kind in looks.OPERATORS else logging.WARNING
        log.log(level, "Video %s was not made (%s): %s", key, problem.kind, problem.detail)
        looks._write_down(key, _tag(chosen, clip.seconds), problem.kind, problem.detail, what="video")
        return problem
    except Exception as error:
        # Never the exception's own words in a log that outlives the process: they could quote the key.
        trace = traceback.format_exc()
        log.error("Video %s was not made\n%s", key, trace.replace(chosen.key, "(the key)") if chosen.key else trace)
        db.fail_video(key, SAY["unknown"])
        looks._write_down(key, _tag(chosen, clip.seconds), "unknown", type(error).__name__, what="video")
        return imagegen.DrawError("unknown", type(error).__name__)


def _say(problem: imagegen.DrawError) -> str:
    """What the page shows: as looks._say, for a video."""
    text = SAY.get(problem.kind, SAY["unknown"])
    if settings.PRODUCTION and not settings.on_this_machine():
        return CLOSED if problem.kind in looks.OPERATORS else text
    return f"{text} {problem.detail.rstrip('.')}." if problem.detail else text


def _ffmpeg() -> str | None:
    """Where ffmpeg is installed, or None (the Dockerfile installs it; on a Mac, Homebrew's)."""
    return shutil.which("ffmpeg")


def turn_file(clip: Path, target: Path) -> Path | None:
    """The turn for dragging: the clip's first seconds ([videos] turn_seconds), without sound, 540 pixels wide,
    with every frame a keyframe, so that any moment of the turn shows at once while dragging. Made with ffmpeg;
    None where ffmpeg is not installed or fails (then the clip itself is dragged through)."""
    ffmpeg = _ffmpeg()
    if not ffmpeg:
        return None
    seconds = (rules() or {}).get("turn_seconds", 6)
    tmp = target.with_name(target.name + ".tmp")
    command = [ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error", "-y", "-i", str(clip),
               "-t", f"{seconds:g}", "-an", "-vf", "scale=540:-2", "-c:v", "libx264", "-preset", "veryfast",
               "-crf", "25", "-g", "1", "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-f", "mp4", str(tmp)]
    try:
        subprocess.run(command, check=True, capture_output=True, timeout=FFMPEG_SECONDS)  # nosec B603
        os.replace(tmp, target)
        return target
    except (OSError, subprocess.SubprocessError) as problem:
        tmp.unlink(missing_ok=True)
        log.warning("The turn of %s was not made, so the clip itself is dragged: %s", clip.name, type(problem).__name__)
        return None


# ── the example wardrobe's clips: made by the owner, by hand ─────────────────
# python -m wardrobe example-pictures --clips K (__main__.py) makes a short clip of the front picture of each of the
# first K outfits that visitors without an account see (guests.py), once the owner has seen what they would cost. A
# visitor's Outfits page shows it in place of the picture, muted and looping (outfits_guest.html, app.js 15a), at its
# own address (app.example_clip). Never at start-up, never for a visitor, and never of a picture of someone's photo.

EXAMPLE_SECONDS = 5     # each example clip's length: long enough for its movement, short enough to loop in place


def example() -> Clip | None:
    """What the owner's command makes of an example outfit's front picture: a clip of EXAMPLE_SECONDS with the
    movement under [videos.motion] `example` in config/looks.toml, between `start` and `keep`, as every clip. Played
    in a loop in place of the picture. None while that line is not there: then no example clip is made or shown."""
    chosen = rules() or {}
    words = (chosen.get("motion") or {}).get("example", "")
    if not words.strip():
        return None
    text = " ".join(part.strip() for part in (chosen.get("start", ""), words, chosen.get("keep", "")) if part.strip())
    return Clip(looks.FRONT, looks.FRONT_LABEL, EXAMPLE_SECONDS, False, text)


def status() -> tuple[bool, str]:
    """(on?, one line saying which model makes the videos, or why they are off): for the owner's command."""
    chosen = rules()
    if not chosen:
        return False, "off — config/looks.toml has no [videos]"
    if not chosen["on"]:
        return False, "off — [videos] on = false in config/looks.toml"
    if not settings.GEMINI_API_KEY:
        if "GEMINI_API_KEY" in settings.UNUSABLE_KEYS or "GOOGLE_API_KEY" in settings.UNUSABLE_KEYS:
            return False, "off — GEMINI_API_KEY is set, but what is in it cannot be a key. Paste the key itself."
        return False, "off — set GEMINI_API_KEY"
    return True, f"on — made by Google, model {chosen['model']}"


def price_per_second() -> Decimal | None:
    """What one second of video costs, in US dollars: price_per_second_usd under [videos] in config/looks.toml, an
    estimate. None while it is not set. (A Decimal, as looks.price_each: 3 clips of 5 seconds at 0.10 are 1.50.)"""
    price = (rules() or {}).get("price_per_second_usd")
    return None if price is None else Decimal(str(price))


def _front(board: dict) -> looks.Look | None:
    """An outfit's front picture where it is there and finished (looks.attach gave the board its pictures)."""
    photos = board.get("photos") or []
    front = photos[0].look if photos else None
    return front if front is not None and front.status == "ready" and front.file else None


def example_clips(boards: list[dict]) -> None:
    """Give each of the example's outfits on a visitor's page the file of its clip, board["clip"]: the clip the owner's
    command made of its front picture, where it is finished and its file is there, else "". Only a clip of a picture
    that belongs to no account (Stilsmith's house model), never one of a picture of someone's photo. Nothing is made
    here. All "" while videos are off, or while there is no example movement (example)."""
    for board in boards:
        board["clip"] = ""
    chosen, clip = service(), example()
    if chosen is None or clip is None:
        return
    keys = {id(board): fingerprint(chosen, clip.text, front.file or "", clip.seconds)
            for board in boards if (front := _front(board)) is not None}
    rows = db.video_rows(list(keys.values()))
    for board in boards:
        row = rows.get(keys.get(id(board), ""))
        video = _view(row) if row is not None and row["user_id"] is None else None
        if video is not None and video.status == "ready" and video.file:
            board["clip"] = video.file


def example_state(board: dict) -> str:
    """Where the example clip of an outfit stands, for the owner's command: there | working (being made already) |
    missing (also while its front picture is not there yet: its clip is made from it)."""
    chosen, clip, front = service(), example(), _front(board)
    if chosen is None or clip is None or front is None:
        return "missing"
    video = get(fingerprint(chosen, clip.text, front.file or "", clip.seconds))
    return video.status if video is not None and video.status in ("ready", "working") else "missing"


def make_example_now(look: looks.Look) -> tuple[str, imagegen.DrawError | None]:
    """Make the example clip (example) of one front picture here and now, and wait for it: for the owner's command,
    which runs it as the example wardrobe (guests.py), one outfit after another.
    The picture must be of Stilsmith's house model: a picture drawn from someone's photo is refused (ValueError), so
    no clip of a person is ever made this way, and the clip belongs to no account. It is written as every clip is
    (_make): its row in the database and its file in <data>/videos/, so a running site shows it from its next page
    load. It is not counted in the day's limits ([videos] in config/looks.toml): the command is run by hand and has its
    own ceiling (--max-cost).
    Returns (what happened, what went wrong):
        ("there", None)      it is there already: nothing was sent
        ("working", None)    it is being made already (by another run of the command): left alone
        ("ready", None)      made now
        ("failed", problem)  not made, with Google's own words (None: it could not even be asked)
    """
    chosen, clip = service(), example()
    if chosen is None or clip is None:
        raise imagegen.DrawError("key", "videos are off, or [videos.motion] has no example", free=True)
    if look.status != "ready" or not look.file:
        return "failed", None
    if (db.look_rows([look.key]).get(look.key) or {}).get("user_id") is not None:
        raise ValueError("This picture is drawn from someone's photo: clips of a person are never made from the "
                         "command line. Nothing more was made.")
    key = fingerprint(chosen, clip.text, look.file, clip.seconds)
    row = db.video_rows([key]).get(key)
    video = _view(row)
    if video is not None and video.status in ("ready", "working"):
        return ("there" if video.status == "ready" else "working"), None
    lost = row["file"] if row and row["file"] and row["user_id"] is None else None   # its file was deleted by hand
    if not db.start_video(key, look.file, _tag(chosen, clip.seconds), None, time.time() - STALE_SECONDS, lost=lost):
        return "working", None                  # another run asked for it a moment ago
    try:
        picture = (looks.folder() / look.file).read_bytes()
    except OSError:                             # drawn again a moment ago: nothing was sent
        db.fail_video(key, SAY["unknown"])
        return "failed", None
    problem = _make(key, chosen, clip, picture, 0, False)      # waits for the clip
    video = get(key)
    if problem is None and video is not None and video.status == "ready":
        return "ready", None
    return "failed", problem


# ── forgetting ────────────────────────────────────────────────────────────────

def _unlink(names: list[str]) -> None:
    for name in names:
        (folder() / name).unlink(missing_ok=True)


def forget_of(user_id: int) -> None:
    """Delete every video made from a picture of a user's photo (with the photo, the pictures and the account)."""
    _unlink(db.drop_personal_videos(user_id))


def forget_made_from(picture: str) -> None:
    """Delete the videos of a picture that was drawn again: they show a picture that is gone."""
    _unlink(db.drop_videos_of(picture))


# ── trying the video model from the command line ─────────────────────────────

def sample(shot: str | None = None, model: str | None = None) -> tuple[Path, float, Clip]:
    """Make one clip from a sample picture (`python -m wardrobe looks --test-video`): the picture `shot` of the
    made-up outfit that `looks --test-set` drew (the front one unless said), as "See it move" would. `model`:
    another model name to try, instead of [videos] model. One clip is billed. Returns the file, how many seconds
    it took and what was asked for. Raises imagegen.DrawError with Google's own words if it does not work, or
    with kind "picture" where the sample picture has not been drawn yet."""
    chosen = service()
    if chosen is None:
        raise imagegen.DrawError("key", "videos are off: GEMINI_API_KEY is not set, or [videos] on = false")
    if model:
        chosen = videogen.Service(model=model, key=chosen.key, task=chosen.task)
    clip = clip_of(shot)
    stem = "sample" if clip.turns else f"sample-{clip.shot}"
    picture = next((path for ext in ("jpg", "png", "webp") for path in [looks.folder() / f"{stem}.{ext}"]
                    if path.is_file()), None)
    if picture is None:
        raise imagegen.DrawError("picture", f"there is no sample picture {looks.folder() / stem}.jpg yet")
    started = time.time()
    data = videogen.make(chosen, picture.read_bytes(), clip.text, seconds=clip.seconds)
    folder().mkdir(parents=True, exist_ok=True)
    path = folder() / f"{stem}.mp4"
    path.write_bytes(data)
    return path, time.time() - started, clip


# ── the command line: python -m wardrobe pro ... (added in __main__.py) ──────

def add_commands(sub) -> None:
    p_pro = sub.add_parser("pro", help="Pro accounts, which may ask for more AI videos a day (nothing to buy yet)")
    p_pro.set_defaults(func=list_pro)
    what = p_pro.add_subparsers(title="what to do (without one: list them)")
    p_add = what.add_parser("add", help="mark an account as Pro (sign up on the site first)")
    p_add.add_argument("email")
    p_add.set_defaults(func=add_pro)
    p_remove = what.add_parser("remove", help="the account is no longer Pro")
    p_remove.add_argument("email")
    p_remove.set_defaults(func=remove_pro)
    what.add_parser("list", help="the Pro accounts").set_defaults(func=list_pro)


def _per_day() -> str:
    chosen = rules() or {}
    return (f"{chosen.get('pro_per_customer_per_day', '?')} videos a day instead of "
            f"{chosen.get('per_customer_per_day', '?')}")


LOCAL_NOTE = ("On your own machine (CAPSULE_ENV=local) there is no limit per person anyway. "
              "Marks made here count where this database runs in production.")


def add_pro(args: argparse.Namespace) -> None:
    db.init()
    email = args.email.strip().lower()
    result = db.add_pro(email)
    if result == "no account":
        sys.exit(f"There is no account with the address {email}. Sign up on the site with it first, then run this again.")
    print(f"{email} is Pro already." if result == "already" else f"{email} is now Pro: {_per_day()}, from its next page.")
    if not settings.PRODUCTION:
        print(LOCAL_NOTE)


def remove_pro(args: argparse.Namespace) -> None:
    db.init()
    email = args.email.strip().lower()
    if not db.remove_pro(email):
        sys.exit(f"{email} is not Pro. The Pro accounts: python -m wardrobe pro list")
    print(f"{email} is no longer Pro, from its next page.")


def list_pro(args: argparse.Namespace) -> None:
    db.init()
    marked = db.list_pro()
    if not marked:
        print("No Pro accounts yet. Mark one (sign up on the site first): python -m wardrobe pro add EMAIL")
    for row in marked:
        print(f"{row['email']:<40} Pro since {row['added_at'][:10]}")
    print(f"Pro means {_per_day()}. Owners (python -m wardrobe owner list) count as Pro.")
    if not settings.PRODUCTION:
        print(LOCAL_NOTE)

