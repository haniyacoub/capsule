"""Talking to Google's video model, which makes the "See it move" clips (videos.py).

The rest of the app uses one function:

    make(service, picture, prompt)  ->  the clip: the bytes of an MP4 file

`picture` is the outfit's AI picture (the bytes of a JPEG, PNG or WebP), the
clip's first frame; `prompt` says what happens in it. Nothing else is sent.

Like the pictures (imagegen.py), it is one HTTPS request with Python's standard
library and the same Gemini key, to the same address. It is the request behind
`client.interactions.create(model=…, input=[picture, words], response_format=…)`
in Google's own package (google-genai 3.3.0, read for this, not installed):

    POST https://generativelanguage.googleapis.com/v1beta/interactions
         {"model": "gemini-omni-flash-preview",
          "input": [{"type": "image", "mime_type": "image/jpeg", "data": "…"},
                    {"type": "text", "text": "…"}],
          "response_format": {"type": "video", "duration": "8s", "aspect_ratio": "9:16", "resolution": "720p"}}
    answer   {"status": "completed",
              "steps": [{"type": "model_output",
                         "content": [{"type": "video", "mime_type": "video/mp4", "data": "…"}]}]}

The clip may come as "data" (the file itself) or as a "uri" on Google's server,
which is then fetched with the same key. Making one takes about 40 seconds to two
minutes. When Google says no, imagegen.DrawError carries what kind of problem it
is (the same kinds as for a picture) and Google's own words.
"""
from __future__ import annotations

import base64
import json
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from . import imagegen
from .imagegen import DrawError

DURATION = "8s"
ASPECT_RATIO = "9:16"                # portrait, like a phone held upright
RESOLUTION = "720p"
TIMEOUT = 300                        # seconds: a clip takes up to two minutes, and its answer is a few megabytes
GOOGLE_HOST = "generativelanguage.googleapis.com"


@dataclass(frozen=True)
class Service:
    model: str
    key: str = field(repr=False)     # never printed

    @property
    def tag(self) -> str:
        """Which model and what kind of clip: part of a video's fingerprint."""
        return f"google:{self.model}:{DURATION}:{ASPECT_RATIO}:{RESOLUTION}"


def is_clip(data: bytes) -> bool:
    """Whether these bytes are an MP4 file (its first box says "ftyp")."""
    return data[4:8] == b"ftyp"


def make(service: Service, picture: bytes, prompt: str) -> bytes:
    ext = imagegen.kind_of(picture) or "jpg"
    sent = base64.b64encode(picture).decode("ascii")
    payload = {"model": service.model,
               "input": [{"type": "image", "mime_type": imagegen.MIME[ext], "data": sent},
                         {"type": "text", "text": prompt}],
               "response_format": {"type": "video", "duration": DURATION, "aspect_ratio": ASPECT_RATIO,
                                   "resolution": RESOLUTION}}
    headers = {"x-goog-api-key": service.key, "Content-Type": "application/json",
               "Api-Revision": imagegen.GOOGLE_REVISION}
    status, body = imagegen._send(imagegen.GOOGLE_URL, headers, json.dumps(payload).encode(),
                                  timeout=TIMEOUT)
    answers = imagegen._answers(body)
    label = imagegen.Service(name="google", model=service.model, key=service.key)    # for the error's words
    error = next((answer["error"] for answer in answers if answer.get("error")), None)
    if status >= 400 or error:
        raise imagegen._google_error(status, error, label)
    made = [block for answer in answers for step in answer.get("steps") or []
            if isinstance(step, dict) and step.get("type") == "model_output"
            for block in step.get("content") or [] if isinstance(block, dict) and block.get("type") == "video"]
    if not made:
        faults = [fault for answer in answers for step in answer.get("steps") or [] if isinstance(step, dict)
                  for fault in [step.get("error")] if isinstance(fault, dict)]
        faults += [fault for answer in answers for fault in answer.get("errors") or [] if isinstance(fault, dict)]
        if faults:
            raise imagegen._google_error(status, faults[0], label)
        state = next((answer.get("status") for answer in answers if answer.get("status")), "unknown")
        raise DrawError("empty", f"Google answered without a video (status {state})")
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
    """A clip Google kept on its own server: fetched with the key, only from Google's address."""
    parts = urlsplit(uri)
    if parts.scheme != "https" or parts.hostname != GOOGLE_HOST:
        raise DrawError("empty", f"Google gave the video's address on another server ({parts.hostname})")
    status, body = imagegen._send(uri, {"x-goog-api-key": service.key}, None, timeout=TIMEOUT)
    if status != 200 or not body:
        raise DrawError("busy", f"the video could not be fetched from Google (status {status})")
    return body
