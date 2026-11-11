"""Talking to the image services that draw the AI pictures: OpenAI and Google.

The rest of the app uses one function:

    draw(service, prompt, photo=None)  ->  (picture bytes, "jpg" | "png" | "webp")

Without `photo` the service draws whoever the prompt describes. With it (the
bytes of a JPEG, PNG or WebP of a person) it is asked to draw that person.

Both are called over plain HTTPS with Python's standard library, so nothing
extra has to be installed. Written from the companies' documentation as it
stood in November 2026:

    OpenAI   POST https://api.openai.com/v1/images/generations    JSON
             POST https://api.openai.com/v1/images/edits          a form carrying the photo
             answer   {"data": [{"b64_json": "…"}]}
    Google   POST https://generativelanguage.googleapis.com/v1beta/interactions
             answer   {"steps": [{"type": "model_output", "content": [{"type": "image", "data": "…"}]}]}

Answers are read tolerantly (one object, a list of objects, or a stream of
"data:" lines), because Google's errors already arrive as a list.

Model names change every few months; they are settings in config/looks.toml,
not code. When a service says no, DrawError carries what kind of problem it is
and the service's own words.
"""
from __future__ import annotations

import base64
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
MAX_ANSWER = 40 * 1024 * 1024        # bytes: no picture comes anywhere near this
LABELS = {"openai": "OpenAI", "google": "Google"}
MIME = {"jpg": "image/jpeg", "png": "image/png", "webp": "image/webp"}


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
    """

    def __init__(self, kind: str, detail: str = ""):
        super().__init__(f"{kind}: {detail}")
        self.kind, self.detail = kind, detail


def draw(service: Service, prompt: str, photo: bytes | None = None) -> tuple[bytes, str]:
    if service.name == "openai":
        return _openai(service, prompt, photo)
    if service.name == "google":
        return _google(service, prompt, photo)
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


def _openai(service: Service, prompt: str, photo: bytes | None) -> tuple[bytes, str]:
    fields = {"model": service.model, "prompt": prompt, "n": 1, "size": "1024x1536",   # portrait
              "quality": service.quality, "output_format": "jpeg", "output_compression": 90}
    auth = {"Authorization": f"Bearer {service.key}"}
    if photo is None:
        status, body = _send(f"{OPENAI_URL}/generations", {**auth, "Content-Type": "application/json"},
                             json.dumps(fields).encode())
    else:
        ext = kind_of(photo) or "jpg"
        form, content_type = _form({name: str(value) for name, value in fields.items()},
                                   [("image[]", f"person.{ext}", MIME[ext], photo)])
        status, body = _send(f"{OPENAI_URL}/edits", {**auth, "Content-Type": content_type}, form)
    answers = _answers(body)
    answer = answers[0] if answers else {}
    if status >= 400 or answer.get("error"):
        raise _openai_error(status, answer.get("error"), service)
    pictures = answer.get("data")
    first = pictures[0] if isinstance(pictures, list) and pictures and isinstance(pictures[0], dict) else {}
    return _picture(first.get("b64_json"), service)


def _openai_error(status: int, error: object, service: Service) -> DrawError:
    err = error if isinstance(error, dict) else {}
    code, kind, message = str(err.get("code") or ""), str(err.get("type") or ""), str(err.get("message") or "")
    detail = _detail(service, status, code, message)
    said = message.lower()
    if code == "moderation_blocked" or kind == "image_generation_user_error" or "safety system" in said:
        return DrawError("refused", detail)
    if status == 401:
        return DrawError("key", detail)
    if status in (402, 403) or code in _NO_CREDIT or kind == "insufficient_quota":
        return DrawError("account", detail)          # no credit, a spend limit, or the account is not verified
    if status == 404 or code == "model_not_found" or ("model" in said and "not exist" in said):
        return DrawError("model", detail)
    if status == 429 or status >= 500:
        return DrawError("busy", detail)
    return DrawError("request", detail)


# ── Google ────────────────────────────────────────────────────────────────────

_WILL_NOT = {"image_safety", "image_prohibited_content", "image_recitation", "safety", "prohibited_content",
             "blocklist"}


def _google(service: Service, prompt: str, photo: bytes | None) -> tuple[bytes, str]:
    content: list[dict] = [{"type": "text", "text": prompt}]
    if photo is not None:
        ext = kind_of(photo) or "jpg"
        content.append({"type": "image", "mime_type": MIME[ext], "data": base64.b64encode(photo).decode("ascii")})
    payload = {"model": service.model, "input": content,
               "response_format": {"type": "image", "mime_type": "image/jpeg", "aspect_ratio": "2:3",   # portrait
                                   "image_size": service.image_size}}
    headers = {"x-goog-api-key": service.key, "Content-Type": "application/json", "Api-Revision": GOOGLE_REVISION}
    status, body = _send(GOOGLE_URL, headers, json.dumps(payload).encode())
    answers = _answers(body)
    error = next((answer["error"] for answer in answers if answer.get("error")), None)
    if status >= 400 or error:
        raise _google_error(status, error, service)
    # The documented place: what the model produced, never the photo that was sent along.
    drawn: list[object] = [
        block.get("data")
        for answer in answers for step in answer.get("steps") or []
        if isinstance(step, dict) and step.get("type") == "model_output"
        for block in step.get("content") or [] if isinstance(block, dict) and block.get("type") == "image"]
    if not drawn:       # an answer shaped differently: any picture in it that is not the one we sent
        sent = content[1]["data"] if photo is not None else None
        drawn = list(_pictures_in(answers, sent))
    if not drawn:
        faults = [fault for answer in answers for fault in answer.get("errors") or [] if isinstance(fault, dict)]
        if faults:
            raise _google_error(status, faults[0], service)
        state = next((answer.get("status") for answer in answers if answer.get("status")), "unknown")
        raise DrawError("empty", f"Google answered without a picture (status {state})")
    return _picture(drawn[-1], service)              # the last one; earlier ones can be drafts


def _pictures_in(node: object, sent: str | None) -> list[str]:
    """Every encoded picture anywhere inside an answer, except the one that was sent."""
    found: list[str] = []
    if isinstance(node, dict):
        data = node.get("data")
        kind = str(node.get("mime_type") or node.get("mimeType") or "")
        if (isinstance(data, str) and len(data) > 1000 and data != sent
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
        return DrawError("key", detail)
    if (status in (402, 403) or names & {"payment_required", "permission_denied", "quota_exceeded"}
            or (status == 429 and "quota" in said)):
        return DrawError("account", detail)          # billing is off, the quota is used up, or no permission
    if status == 404 or names & {"model_not_found", "not_found"}:
        return DrawError("model", detail)
    if status == 429 or status >= 500:
        return DrawError("busy", detail)
    return DrawError("request", detail)


# ── shared plumbing ───────────────────────────────────────────────────────────

class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """The key travels in a header, so a redirect to some other address is not followed."""

    def redirect_request(self, *args, **kwargs):
        return None


# Proxies are taken from the environment (HTTPS_PROXY) only. The default would also ask macOS for
# its system proxy settings, and doing that inside a web-server worker crashes the worker on a Mac.
_opener = urllib.request.build_opener(urllib.request.ProxyHandler(urllib.request.getproxies_environment()),
                                      _NoRedirect)


def _send(url: str, headers: dict[str, str], body: bytes) -> tuple[int, bytes]:
    """One HTTPS POST. Returns the status and the bytes of the answer."""
    request = urllib.request.Request(url, data=body, headers={"User-Agent": AGENT, **headers}, method="POST")
    try:
        with _opener.open(request, timeout=TIMEOUT) as answer:
            return answer.status, answer.read(MAX_ANSWER)
    except urllib.error.HTTPError as refusal:        # an answer with an error status
        return refusal.code, refusal.read(1024 * 1024)
    except OSError as problem:                       # no connection, or no answer in time
        raise DrawError("busy", f"no answer from {url.split('/')[2]}: {type(problem).__name__}: {problem}") from None


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
