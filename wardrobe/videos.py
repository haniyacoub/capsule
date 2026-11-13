"""AI videos of outfits: "See it move".

On an outfit whose AI picture is ready, "See it move" asks Google's video model
(videogen.py) for an 8-second clip that starts from that picture, whatever its
scene: the model turns slowly on the spot in one full circle, then faces the
camera and settles into a relaxed pose. The picture and one paragraph
(config/looks.toml, [videos] text) are all that is sent: no name, no email, no
sizes.

Like the pictures (looks.py), a video is made in the background (about 40 seconds
to two minutes) while the page asks every few seconds how it is going; it is kept
in <data>/videos/ and never paid for twice: a picture has one video, whoever asks.
A video of a picture drawn from someone's photo is theirs alone, like the picture:
shown only to them, and deleted with the picture, the photo and the account.

Drag to turn: where ffmpeg is installed, the turn (the clip's first seconds) is
kept a second time with every frame a keyframe, so that dragging across the
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
# for a video: in the photo's box on Profile (profile.html; app.py stores the date as photo_consent with the photo)
# or, for a photo added before those words, in the box of the video's band (_video.html; stored as video_consent,
# with the photo it is about). Give it a new date whenever those words change.
CONSENT = "2026-11-13"


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
    return videogen.Service(model=chosen["model"], key=settings.GEMINI_API_KEY)


def fingerprint(chosen: videogen.Service, text: str, picture: str) -> str:
    """The name of a video: the same model, words and picture file give the same one. A picture drawn again
    has a new file, so its video is a new one too."""
    return hashlib.sha256("\x1f".join((chosen.tag, text, picture)).encode()).hexdigest()[:24]


# ── one video: where it stands ────────────────────────────────────────────────

@dataclass
class Video:
    key: str
    status: str                  # working | ready | failed | limit | consent (the band's box not ticked)
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


def _key(chosen: videogen.Service, look: looks.Look) -> str:
    return fingerprint(chosen, (rules() or {}).get("text", ""), look.file or "")


def of(look: looks.Look | None) -> Video | None:
    """Where the video of this picture stands, or None (no video yet, or videos are off)."""
    chosen = service()
    if chosen is None or look is None or look.status != "ready" or not look.file:
        return None
    return get(_key(chosen, look))


def attach(boards: list[dict]) -> bool:
    """Give every outfit on a page whose picture is ready the state of its video (board["video"], or None).
    Returns False, changing nothing, while videos are off."""
    chosen = service()
    if chosen is None:
        return False
    ready = [board for board in boards if board.get("look") and board["look"].status == "ready" and board["look"].file]
    keys = {id(board): _key(chosen, board["look"]) for board in ready}
    rows = db.video_rows(list(keys.values()))
    for board in boards:
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


def left_words(number: int) -> str:
    """'1 video left today', '5 videos left today', or 'No videos left today: more tomorrow'."""
    if number <= 0:
        return NONE_LEFT
    return f"{number} video{'' if number == 1 else 's'} left today"


# ── a picture of the customer's photo: his agreement first ───────────────────

def consented() -> bool:
    """Whether the signed-in customer agreed that pictures drawn from his photo may go to Google for videos: when
    he added the photo (the words of CONSENT's date, or later ones), or since then, in the video's band."""
    if str(db.get_setting("photo_consent") or "") >= CONSENT:
        return True
    later = db.get_setting("video_consent")
    return (isinstance(later, dict) and str(later.get("words", "")) >= CONSENT
            and later.get("photo_added") == db.get_setting("photo_added"))    # for this photo, not an earlier one


def needs_consent(look: looks.Look) -> bool:
    """Whether making this picture's video needs the customer's agreement first (see consented)."""
    row = db.look_rows([look.key]).get(look.key) or {}
    return row.get("user_id") is not None and not consented()


# ── asking for a video ────────────────────────────────────────────────────────

def request(look: looks.Look, agreed: bool = False) -> Video | None:
    """Start making the video of this picture, or say where it stands. None while videos are off or the
    picture is not ready. `agreed`: the customer ticked the band's box (needs_consent).

    Asking twice never pays twice: a finished video is returned as it is, and one being made is left alone.
    A new one takes one of the day's videos, apart from the pictures' allowance.
    """
    chosen = service()
    if chosen is None or look.status != "ready" or not look.file:
        return None
    text = (rules() or {})["text"]
    key = fingerprint(chosen, text, look.file)
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
    if db.start_video(key, look.file, chosen.tag, owner, now - STALE_SECONDS, lost=lost):
        if lost and row and row["turn"]:
            _unlink([row["turn"]])                  # the turn of the lost clip, if it is still there
        try:
            picture = (looks.folder() / look.file).read_bytes()
        except OSError:                          # drawn again a moment ago: nothing was sent, nothing counts
            db.fail_video(key, SAY["unknown"])
            db.drop_video_request(ticket)
            return get(key)
        _spawn(lambda: _make(key, chosen, text, picture, ticket, owner is not None))
    else:
        db.drop_video_request(ticket)            # somebody asked for the same video a moment ago
    return get(key) or Video(key, "working")


def _spawn(job) -> None:
    """Run `job` in the background (the tests swap this for running it at once)."""
    threading.Thread(target=job, name="video", daemon=True).start()


def _make(key: str, chosen: videogen.Service, text: str, picture: bytes, ticket: int, personal: bool) -> None:
    """Background: have the clip made, keep it (and its turn for dragging) and record how it went. Never raises.
    `ticket` is this request's entry in the day's count, given back only when Google certainly made (and billed)
    nothing. `personal`: the picture is drawn from the customer's own photo."""
    try:
        data = videogen.make(chosen, picture, text)
        stamp = int(time.time())                 # a new name each time, so browsers don't show an old one
        name, turn_name = f"{key}-{stamp}.mp4", f"{key}-{stamp}-turn.mp4"
        folder().mkdir(parents=True, exist_ok=True)
        tmp = folder() / (name + ".tmp")
        tmp.write_bytes(data)
        os.replace(tmp, folder() / name)
        turn = turn_file(folder() / name, folder() / turn_name)
        try:
            db.finish_video(key, name, turn.name if turn else None)
        except LookupError:                      # the account was deleted meanwhile
            for path in (folder() / name, turn):
                if path:
                    path.unlink(missing_ok=True)
            return
        log.info("Made video %s with %s", key, chosen.tag)
    except imagegen.DrawError as problem:
        if personal and problem.kind in ("refused", "request"):
            problem = imagegen.DrawError("person", problem.detail, problem.free)
        said = _say(problem)
        db.fail_video(key, said)
        if problem.free:
            db.drop_video_request(ticket)
        level = logging.ERROR if problem.kind in looks.OPERATORS else logging.WARNING
        log.log(level, "Video %s was not made (%s): %s", key, problem.kind, problem.detail)
        looks._write_down(key, chosen.tag, problem.kind, problem.detail, what="video")
    except Exception as error:
        # Never the exception's own words in a log that outlives the process: they could quote the key.
        trace = traceback.format_exc()
        log.error("Video %s was not made\n%s", key, trace.replace(chosen.key, "(the key)") if chosen.key else trace)
        db.fail_video(key, SAY["unknown"])
        looks._write_down(key, chosen.tag, "unknown", type(error).__name__, what="video")


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

