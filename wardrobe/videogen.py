"""Talking to Google's video model, which makes the "See it move" clips (videos.py).

The rest of the app uses one function:

    make(service, picture, prompt, seconds=8)  ->  the clip: the bytes of an MP4 file

`picture` is one of an outfit's AI pictures (the bytes of a JPEG, PNG or WebP),
the clip's first frame; `prompt` says what happens in it; `seconds` is how long
the clip is (Google makes 3 to 15). Nothing else is sent.

Like the pictures (imagegen.py), it is one HTTPS request with Python's standard
library and the same Gemini key, to the same address. It is the request behind
`client.interactions.create(model=…, input=[picture, words], response_format=…)`
in Google's own package (google-genai 3.3.0, read for this, not installed):

    POST https://generativelanguage.googleapis.com/v1beta/interactions
         {"model": "gemini-omni-flash-preview",
          "input": [{"type": "image", "mime_type": "image/jpeg", "data": "…"},
                    {"type": "text", "text": "…"}],
          "response_format": {"type": "video", "duration": "8s", "aspect_ratio": "9:16", "resolution": "720p"},
          "generation_config": {"video_config": {"task": "image_to_video"}}}

The last line tells Google that the picture is the clip's first frame, not just
something to look at (its documentation of 15 Nov 2026; [videos] task in
config/looks.toml, and left out of the request where that setting is empty).
It has not been tried against the paid service yet.
    answer   {"status": "completed",
              "steps": [{"type": "model_output",
                         "content": [{"type": "video", "mime_type": "video/mp4", "data": "…"}]}]}

The clip may come as "data" (the file itself) or as a "uri" on Google's server,
which is then fetched with the same key; where that address hands the file over
from Google's storage (a redirect), the storage's address is followed once,
without the key. Making one takes about 40 seconds to two minutes. When Google
says no, imagegen.DrawError carries what kind of problem it is (the same kinds as
for a picture) and Google's own words.

An answer that is not finished yet is followed up the way Google's package does it
(_interactions_continuation.py and interactions.get in google-genai):

    "status": "in_progress" or "queued", with an "id"
        Google is still making it: asked again every few seconds,
        GET https://generativelanguage.googleapis.com/v1beta/interactions/<id>
    "status": "requires_continuation", with a "continuation_token"
        Google stopped part-way: asked to go on, with the token and the id it came
        with ("previous_interaction_id") and without the picture (Google kept it);
        what each part made is put together. A token handed back unchanged would
        go round for ever: then it stops. Each time it goes on, Google reads what
        it has so far again, and that is billed (Google's package says so): so it
        goes on at most GO_ON_AT_MOST times for one video, then stops and says so.

All of it within TIMEOUT from the first request. Once Google has taken the request,
nothing that goes wrong later is "free" (videos.py counts it): it may have been
billed.

Unlike a picture (imagegen.py), the request does not say "store": false, so Google
keeps it, with the picture it was made from, as an "interaction" for 55 days. Google's
page on its video model (aistudio.google.com/docs/omni, read 19 Nov 2026) allows
"store": false for a request answered in one go, but both ways of following up an
unfinished answer above need Google to have kept it: asking again by its id, and going
on with "previous_interaction_id" (Google's Interactions API page says "store": false
rules that out). Whether Google ever answers a video unfinished can only be seen with a
real, billed request; until then, keeping the request is what makes the clip arrive.
Another way: delete it once the clip has arrived (DELETE …/interactions/<id>).
"""
from __future__ import annotations

import base64
import json
import re
import time
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlsplit

from . import imagegen
from .imagegen import DrawError

SECONDS = 8                          # the turn; other clips say their own length (3 to 15)
ASPECT_RATIO = "9:16"                # portrait, like a phone held upright
RESOLUTION = "720p"
TIMEOUT = 300                        # seconds: a clip takes up to two minutes, and its answer is a few megabytes
GOOGLE_HOST = "generativelanguage.googleapis.com"
STORAGE = (".googleapis.com", ".googleusercontent.com")   # where Google hands over a file it kept (a redirect)
STILL_MAKING = ("in_progress", "queued")   # asked again by the interaction's id
GO_ON = "requires_continuation"            # asked to go on, with its continuation_token
GO_ON_AT_MOST = 3                          # times one video is asked to go on: each time is billed again
ASK_AGAIN_SECONDS = 5                      # between two questions while Google is still making it
_ID = re.compile(r"[\w.:-]{1,200}")        # what an interaction's id may look like, to go into its address


@dataclass(frozen=True)
class Service:
    model: str
    key: str = field(repr=False)     # never printed
    task: str = ""                   # "image_to_video": the picture is the first frame ("" leaves it out)

    @property
    def tag(self) -> str:
        """Which model and what kind of clip: part of a video's fingerprint (its length is another part)."""
        return f"google:{self.model}:{ASPECT_RATIO}:{RESOLUTION}" + (f":{self.task}" if self.task else "")


def is_clip(data: bytes) -> bool:
    """Whether these bytes are an MP4 file (its first box says "ftyp")."""
    return data[4:8] == b"ftyp"


_wait = time.sleep                  # (the tests wait no time)
_clock = time.monotonic


def make(service: Service, picture: bytes, prompt: str, seconds: int = SECONDS) -> bytes:
    ext = imagegen.kind_of(picture) or "jpg"
    sent = base64.b64encode(picture).decode("ascii")
    payload = {"model": service.model,
               "input": [{"type": "image", "mime_type": imagegen.MIME[ext], "data": sent},
                         {"type": "text", "text": prompt}],
               "response_format": {"type": "video", "duration": f"{seconds}s", "aspect_ratio": ASPECT_RATIO,
                                   "resolution": RESOLUTION}}
    if service.task:                 # the picture is the clip's first frame
        payload["generation_config"] = {"video_config": {"task": service.task}}
    headers = {"x-goog-api-key": service.key, "Content-Type": "application/json",
               "Api-Revision": imagegen.GOOGLE_REVISION}
    label = imagegen.Service(name="google", model=service.model, key=service.key)    # for the error's words
    deadline = _clock() + TIMEOUT
    status, body = imagegen._send(imagegen.GOOGLE_URL, headers, json.dumps(payload).encode(),
                                  timeout=TIMEOUT)
    answers = _read(status, body, label)
    parts = [answers]                # what each part made (one, unless Google stopped part-way and went on)
    sent_token, followed = "", False
    try:
        while True:
            state, ident, token = (_last(answers, name) for name in ("status", "id", "continuation_token"))
            if state in STILL_MAKING and _ID.fullmatch(ident):
                followed = True
                _wait(min(ASK_AGAIN_SECONDS, _left(deadline)))
                status, body = imagegen._send(f"{imagegen.GOOGLE_URL}/{ident}",
                                              {"x-goog-api-key": service.key, "Api-Revision": imagegen.GOOGLE_REVISION},
                                              None, timeout=_left(deadline))
                answers = parts[-1] = _read(status, body, label)     # the same part, further on
            elif state == GO_ON and token and token != sent_token:
                followed = True
                if len(parts) > GO_ON_AT_MOST:                       # each time costs more: enough for one video
                    raise DrawError("busy", f"Google had still not finished the video after going on "
                                            f"{GO_ON_AT_MOST} times")
                going_on = {**payload, "continuation_token": token}
                if _ID.fullmatch(ident):                             # Google kept the picture and the words
                    del going_on["input"]
                    going_on["previous_interaction_id"] = ident
                status, body = imagegen._send(imagegen.GOOGLE_URL, headers, json.dumps(going_on).encode(),
                                              timeout=_left(deadline))
                answers = _read(status, body, label)
                parts.append(answers)
                sent_token = token
            else:
                break
        return _clip(service, status, [answer for part in parts for answer in part], label)
    except DrawError as problem:
        # Google took the request (its first answer was read): whatever went wrong afterwards may have been billed,
        # so none of it is "free". That includes fetching a clip Google made and kept on its server: not reaching it
        # is the same "could not be reached" as for the first request, but the clip was made by then. An address
        # Google no longer knows, asked again, is the interaction's, not the model's.
        kind = "busy" if followed and problem.kind == "model" else problem.kind
        raise DrawError(kind, problem.detail) from None


def _read(status: int, body: bytes, label: imagegen.Service) -> list[dict]:
    """The JSON object(s) of one answer, or the DrawError it says."""
    answers = imagegen._answers(body)
    error = next((answer["error"] for answer in answers if answer.get("error")), None)
    if status >= 400 or error:
        raise imagegen._google_error(status, error, label)
    return answers


def _last(answers: list[dict], name: str) -> str:
    """One field of an answer ("status", "id", "continuation_token"), from its last object that has it, or ""."""
    found = [answer[name] for answer in answers if isinstance(answer.get(name), str) and answer[name]]
    return found[-1] if found else ""


def _left(deadline: float) -> float:
    """Seconds left to make the clip in, or DrawError once there are none (Google may still be making it)."""
    left = deadline - _clock()
    if left <= 0:
        raise DrawError("busy", f"Google was still making the video after {TIMEOUT} seconds")
    return left


def _clip(service: Service, status: int, answers: list[dict], label: imagegen.Service) -> bytes:
    """The clip in Google's finished answer(s): the bytes of an MP4 file."""
    made = [block for answer in answers for step in answer.get("steps") or []
            if isinstance(step, dict) and step.get("type") == "model_output"
            for block in step.get("content") or [] if isinstance(block, dict) and block.get("type") == "video"]
    if not made:
        faults = [fault for answer in answers for step in answer.get("steps") or [] if isinstance(step, dict)
                  for fault in [step.get("error")] if isinstance(fault, dict)]
        faults += [fault for answer in answers for fault in answer.get("errors") or [] if isinstance(fault, dict)]
        if faults:
            raise imagegen._google_error(status, faults[0], label)
        raise DrawError("empty", f"Google answered without a video (status {_last(answers, 'status') or 'unknown'})")
    clip = made[-1]                                  # the last one; earlier ones can be drafts
    if clip.get("data"):
        try:
            data = base64.b64decode(clip["data"])
        except ValueError:
            raise DrawError("empty", "the video from Google could not be read") from None
    elif clip.get("uri"):
        data = _fetch(service, str(clip["uri"]))
    else:
        raise DrawError("empty", "Google answered without a video")
    if not is_clip(data):
        raise DrawError("empty", "Google sent something that is not a video")
    return data


def _fetch(service: Service, uri: str) -> bytes:
    """A clip Google kept on its own server: fetched with the key, only from Google's address. If that address
    hands it over from Google's storage (a redirect, as Google's own examples expect: curl -L), the storage's
    address is followed once, over HTTPS and without the key. The clip is paid for by then, so this matters."""
    parts = urlsplit(uri)
    if parts.scheme != "https" or parts.hostname != GOOGLE_HOST:
        raise DrawError("empty", f"Google gave the video's address on another server ({parts.hostname})")
    status, body = imagegen._send(uri, {"x-goog-api-key": service.key}, None, timeout=TIMEOUT)
    if status in imagegen.REDIRECTS:
        location = body.decode("latin-1").strip()
        there = urlsplit(urljoin(uri, location))
        host = there.hostname or ""
        if not location or there.scheme != "https" or not (host == GOOGLE_HOST or host.endswith(STORAGE)):
            raise DrawError("busy", f"the video's address led to another server ({host or 'none'})")
        status, body = imagegen._send(there.geturl(), {}, None, timeout=TIMEOUT)
    if status != 200 or not body:
        raise DrawError("busy", f"the video could not be fetched from Google (status {status})")
    return body
