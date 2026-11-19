"""Talking to the image services that draw the AI pictures: OpenAI and Google.

The rest of the app uses one function:

    draw(service, prompt, photo=None, references=())  ->  (picture bytes, "jpg" | "png" | "webp")

Without `photo` the service draws whoever the prompt describes. With it (the
bytes of a JPEG, PNG or WebP of a person) it is asked to draw that person.
`references` are pictures to make the new one from: looks.py sends an outfit's
front picture, so that the same man in the same clothes can be shown walking,
turned, or somewhere else. Every picture given travels with the words in the
one request (Google takes up to 14, of which 4 of a person).

OpenAI: a request with any picture goes to its "edits" address, which takes
several. That is how its documentation reads; it has only ever been tried here
with one photo, so pictures made from a front picture are untested on OpenAI.

Both are called over plain HTTPS with Python's standard library, so nothing
extra has to be installed. Written from the companies' documentation as it
stood in November 2026:

    OpenAI   POST https://api.openai.com/v1/images/generations    JSON
             POST https://api.openai.com/v1/images/edits          a form carrying the pictures
             answer   {"data": [{"b64_json": "…"}]}
    Google   POST https://generativelanguage.googleapis.com/v1beta/interactions
             input    [{"type": "text", …}, {"type": "image", "mime_type": …, "data": base64}, …]
             "store": false
             answer   {"steps": [{"type": "model_output", "content": [{"type": "image", "data": "…"}]}]}

"store": false asks Google not to keep the request (the words, a customer's photo, the
pictures sent along) and its picture as an "interaction" to fetch again later, which it
otherwise does for 55 days. Google's own page on the Interactions API (read 19 Nov 2026,
aistudio.google.com/docs/interactions-overview) says any interaction can opt out, except
one run in the background or continued from an earlier one by its id; a picture is
neither: one request, one answer. Google's separate 55-day log for spotting misuse is
not switched off by it.

Answers are read tolerantly (one object, a list of objects, or a stream of
"data:" lines), because Google's errors already arrive as a list.

Model names change every few months; they are settings in config/looks.toml,
not code. When a service says no, DrawError carries what kind of problem it is
and the service's own words.
"""
from __future__ import annotations

import base64
import http.client
import json
import re
import secrets
import urllib.error
import urllib.request
from dataclasses import dataclass, field

OPENAI_URL = "https://api.openai.com/v1/images"
GOOGLE_URL = "https://generativelanguage.googleapis.com/v1beta/interactions"
GOOGLE_REVISION = "2026-05-20"       # the version of Google's interface whose answers are read below
AGENT = "capsule-wardrobe/1.0"
TIMEOUT = 180                        # seconds: a picture can take a minute or two
MAX_ANSWER = 40 * 1024 * 1024        # bytes: no picture or video comes anywhere near this
LABELS = {"openai": "OpenAI", "google": "Google"}
MIME = {"jpg": "image/jpeg", "png": "image/png", "webp": "image/webp"}
MAX_PICTURES = 14                    # pictures sent along with the words in one request (Google's limit)


@dataclass(frozen=True)
class Service:
    name: str                        # openai | google
    model: str
    key: str = field(repr=False)     # never printed
    quality: str = "medium"          # OpenAI: low | medium | high
    image_size: str = "1K"           # Google: 1K | 2K | 4K

    @property
    def label(self) -> str:
        return LABELS.get(self.name, self.name)

    @property
    def tag(self) -> str:
        """Which service, model and quality: part of a picture's fingerprint."""
        return f"{self.name}:{self.model}:{self.quality if self.name == 'openai' else self.image_size}"


class DrawError(Exception):
    """A picture could not be drawn. `kind` says why:

        key, account, model, request    something the operator has to fix
        refused                         the service will not draw this
        busy, empty                     worth another try

    `free` is True only when the service certainly drew nothing and so billed nothing: it could
    not be reached, or it turned the request away at the door. A request that got as far as being
    worked on may have been charged for, whatever came back.
    """

    def __init__(self, kind: str, detail: str = "", free: bool = False):
        super().__init__(f"{kind}: {detail}")
        self.kind, self.detail, self.free = kind, detail, free


def draw(service: Service, prompt: str, photo: bytes | None = None,
         references: list[bytes] | tuple[bytes, ...] = ()) -> tuple[bytes, str]:
    # Every picture that goes with the words: the person's own photo first, then the pictures to make this one from.
    pictures = ([photo] if photo is not None else []) + list(references)
    if len(pictures) > MAX_PICTURES:
        raise DrawError("request", f"{len(pictures)} pictures to send, and {MAX_PICTURES} is the most", free=True)
    if service.name == "openai":
        return _openai(service, prompt, pictures)
    if service.name == "google":
        return _google(service, prompt, pictures)
    raise DrawError("request", f"unknown image service {service.name!r}")


def kind_of(data: bytes) -> str | None:
    """The file type of a picture, read from its first bytes: jpg, png, webp, or None."""
    if data[:3] == b"\xff\xd8\xff":
        return "jpg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return None


# ── OpenAI ────────────────────────────────────────────────────────────────────

_NO_CREDIT = {"insufficient_quota", "credit_balance_exhausted", "billing_hard_limit_reached",
              "organization_spend_limit_exceeded", "project_spend_limit_exceeded",
              "organization_usage_limit_exceeded"}


def _openai(service: Service, prompt: str, pictures: list[bytes]) -> tuple[bytes, str]:
    fields = {"model": service.model, "prompt": prompt, "n": 1, "size": "1024x1536",   # portrait
              "quality": service.quality, "output_format": "jpeg", "output_compression": 90}
    auth = {"Authorization": f"Bearer {service.key}"}
    if not pictures:
        status, body = _send(f"{OPENAI_URL}/generations", {**auth, "Content-Type": "application/json"},
                             json.dumps(fields).encode())
    else:
        files = []
        for number, picture in enumerate(pictures, 1):
            ext = kind_of(picture) or "jpg"
            files.append(("image[]", f"picture-{number}.{ext}", MIME[ext], picture))
        form, content_type = _form({name: str(value) for name, value in fields.items()}, files)
        status, body = _send(f"{OPENAI_URL}/edits", {**auth, "Content-Type": content_type}, form)
    answers = _answers(body)
    answer = answers[0] if answers else {}
    if status >= 400 or answer.get("error"):
        raise _openai_error(status, answer.get("error"), service)
    made = answer.get("data")
    first = made[0] if isinstance(made, list) and made and isinstance(made[0], dict) else {}
    return _picture(first.get("b64_json"), service)


def _openai_error(status: int, error: object, service: Service) -> DrawError:
    err = error if isinstance(error, dict) else {}
    code, kind, message = str(err.get("code") or ""), str(err.get("type") or ""), str(err.get("message") or "")
    detail = _detail(service, status, code, message)
    said = message.lower()
    if code == "moderation_blocked" or kind == "image_generation_user_error" or "safety system" in said:
        return DrawError("refused", detail)
    if status == 401:
        return DrawError("key", detail, free=True)
    if status in (402, 403) or code in _NO_CREDIT or kind == "insufficient_quota":
        return DrawError("account", detail, free=True)   # no credit, a spend limit, or the account is not verified
    if status == 404 or code == "model_not_found" or ("model" in said and "not exist" in said):
        return DrawError("model", detail, free=True)
    if status == 429 or status >= 500:
        return DrawError("busy", detail, free=status == 429)
    return DrawError("request", detail, free=True)


# ── Google ────────────────────────────────────────────────────────────────────

_WILL_NOT = {"image_safety", "image_prohibited_content", "image_recitation", "safety", "prohibited_content",
             "blocklist"}


def _google(service: Service, prompt: str, pictures: list[bytes]) -> tuple[bytes, str]:
    # The words first, then each picture inside the request itself (base64), in the order given.
    content: list[dict] = [{"type": "text", "text": prompt}]
    for picture in pictures:
        ext = kind_of(picture) or "jpg"
        content.append({"type": "image", "mime_type": MIME[ext], "data": base64.b64encode(picture).decode("ascii")})
    payload = {"model": service.model, "input": content, "store": False,     # not kept by Google (see the top)
               "response_format": {"type": "image", "mime_type": "image/jpeg", "aspect_ratio": "2:3",   # portrait
                                   "image_size": service.image_size}}
    headers = {"x-goog-api-key": service.key, "Content-Type": "application/json", "Api-Revision": GOOGLE_REVISION}
    status, body = _send(GOOGLE_URL, headers, json.dumps(payload).encode())
    answers = _answers(body)
    error = next((answer["error"] for answer in answers if answer.get("error")), None)
    if status >= 400 or error:
        raise _google_error(status, error, service)
    # The documented place: what the model produced, never a picture that was sent along.
    drawn: list[object] = [
        block.get("data")
        for answer in answers for step in answer.get("steps") or []
        if isinstance(step, dict) and step.get("type") == "model_output"
        for block in step.get("content") or [] if isinstance(block, dict) and block.get("type") == "image"]
    if not drawn:       # an answer shaped differently: any picture in it that is not one we sent
        drawn = list(_pictures_in(answers, {part["data"] for part in content[1:]}))
    if not drawn:
        faults = [fault for answer in answers for fault in answer.get("errors") or [] if isinstance(fault, dict)]
        if faults:
            raise _google_error(status, faults[0], service)
        state = next((answer.get("status") for answer in answers if answer.get("status")), "unknown")
        raise DrawError("empty", f"Google answered without a picture (status {state})")
    return _picture(drawn[-1], service)              # the last one; earlier ones can be drafts


def _pictures_in(node: object, sent: set[str]) -> list[str]:
    """Every encoded picture anywhere inside an answer, except those that were sent."""
    found: list[str] = []
    if isinstance(node, dict):
        data = node.get("data")
        kind = str(node.get("mime_type") or node.get("mimeType") or "")
        if (isinstance(data, str) and len(data) > 1000 and data not in sent
                and (node.get("type") == "image" or kind.startswith("image/"))):
            found.append(data)
        for value in node.values():
            found += _pictures_in(value, sent)
    elif isinstance(node, list):
        for value in node:
            found += _pictures_in(value, sent)
    return found


def _google_error(status: int, error: object, service: Service) -> DrawError:
    err = error if isinstance(error, dict) else {}
    # Two spellings are in use: {"code": "quota_exceeded"} and {"code": 429, "status": "RESOURCE_EXHAUSTED"}.
    names = {str(err.get("code") or "").lower(), str(err.get("status") or "").lower()} - {"", str(status)}
    message = str(err.get("message") or "")
    detail = _detail(service, status, " ".join(sorted(names)), message)
    said = message.lower()
    if names & _WILL_NOT:
        return DrawError("refused", detail)
    if names & {"no_image", "image_other"}:
        return DrawError("empty", detail)
    if status == 401 or names & {"authentication", "unauthenticated"} or "api key" in said:
        return DrawError("key", detail, free=True)
    # A 429 can be "slow down" (a per-minute limit: wait a little) or "nothing left" (a daily quota,
    # no credit: the operator has to act). Google words both as "quota"; only the lasting kind counts here.
    used_up = status == 429 and any(word in said for word in ("per day", "daily", "billing", "credit", "prepay"))
    if status in (402, 403) or names & {"payment_required", "permission_denied", "quota_exceeded"} or used_up:
        return DrawError("account", detail, free=True)   # billing is off, the quota is used up, or no permission
    if status == 404 or names & {"model_not_found", "not_found"}:
        return DrawError("model", detail, free=True)
    if status == 429 or status >= 500:
        return DrawError("busy", detail, free=status == 429)
    return DrawError("request", detail, free=True)


# ── shared plumbing ───────────────────────────────────────────────────────────

class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """The key travels in a header, so a redirect to some other address is not followed."""

    def redirect_request(self, *args, **kwargs):
        return None


# Proxies are taken from the environment (HTTPS_PROXY) only. The default would also ask macOS for
# its system proxy settings, and doing that inside a web-server worker crashes the worker on a Mac.
_opener = urllib.request.build_opener(urllib.request.ProxyHandler(urllib.request.getproxies_environment()),
                                      _NoRedirect)


REDIRECTS = (301, 302, 303, 307, 308)


def _send(url: str, headers: dict[str, str], body: bytes | None, timeout: float = TIMEOUT) -> tuple[int, bytes]:
    """One HTTPS POST (a GET without a `body`: fetching a video, videogen.py). Returns the status and the bytes
    of the answer. A redirect is not followed (the key travels in a header): its answer is the address it points
    to, for the caller to judge (videogen.py follows one to Google's storage, without the key)."""
    host = url.split("/")[2]
    request = urllib.request.Request(url, data=body, headers={"User-Agent": AGENT, **headers},
                                     method="GET" if body is None else "POST")
    try:
        answer = _opener.open(request, timeout=timeout)
    except urllib.error.HTTPError as refusal:        # an answer with an error status, or a redirect
        if refusal.code in REDIRECTS:
            with refusal:                            # its own body is not wanted
                where = refusal.headers.get("Location") if refusal.headers else None
                return refusal.code, (where or "").encode("latin-1")
        return refusal.code, refusal.read(1024 * 1024)
    except urllib.error.URLError as problem:         # it could not be reached: nothing was sent, nothing drawn
        raise DrawError("busy", f"{host} could not be reached: {type(problem.reason).__name__}", free=True) from None
    except ValueError:
        # A header that cannot be sent: in practice a key with a line break or a character such as "…"
        # in it. The error's own words would quote the key, so they are not passed on.
        raise DrawError("key", "the key contains characters that no key has", free=True) from None
    except (OSError, http.client.HTTPException) as problem:    # sent, but no (whole) answer came back in time
        raise DrawError("busy", f"no answer from {host}: {type(problem).__name__}") from None
    try:
        with answer:
            return answer.status, answer.read(MAX_ANSWER)
    except (OSError, http.client.HTTPException) as problem:    # the answer broke off half-way
        raise DrawError("busy", f"the answer from {host} broke off: {type(problem).__name__}") from None


def _form(fields: dict[str, str], files: list[tuple[str, str, str, bytes]]) -> tuple[bytes, str]:
    """A multipart form: plain fields plus files as (field name, file name, type, bytes)."""
    boundary = "capsule-" + secrets.token_hex(16)
    parts = [f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode()
             for name, value in fields.items()]
    for name, filename, mime, data in files:
        head = (f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'
                f"Content-Type: {mime}\r\n\r\n")
        parts.append(head.encode() + data + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def _answers(body: bytes) -> list[dict]:
    """The JSON object(s) in an answer: one object, a list of them, or a stream of "data: {…}" lines."""
    text = body.decode("utf-8", "replace").strip()
    try:
        data = json.loads(text)
    except ValueError:
        data = []
        for line in text.splitlines():
            if line.startswith("data:"):
                try:
                    data.append(json.loads(line[5:].strip()))
                except ValueError:
                    pass
    return [item for item in (data if isinstance(data, list) else [data]) if isinstance(item, dict)]


def _picture(encoded: object, service: Service) -> tuple[bytes, str]:
    """The picture in an answer, checked to really be one."""
    if not isinstance(encoded, str) or not encoded:
        raise DrawError("empty", f"{service.label} answered without a picture")
    try:
        data = base64.b64decode(encoded)
    except ValueError:
        raise DrawError("empty", f"the picture from {service.label} could not be read") from None
    ext = kind_of(data)
    if ext is None or len(data) < 2000:
        raise DrawError("empty", f"{service.label} sent something that is not a picture")
    return data, ext


def _detail(service: Service, status: int, code: str, message: str) -> str:
    """The service's answer in one line, with anything that looks like a key removed."""
    text = f"{service.label} answered {status}" + (f" {code}" if code else "")
    text += f": {message}" if message else ""
    if service.key:
        text = text.replace(service.key, "(the key)")
    return re.sub(r"\b(?:sk-|AIza)[\w*.-]{6,}", "(a key)", text)[:400]
