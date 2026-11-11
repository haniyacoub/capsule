"""Outgoing email (password resets).

With SMTP_URL set (smtp://user:password@host:587, or smtps:// for port 465)
messages are sent. Without it they are kept in OUTBOX and, on your own machine
only, written to the log so you can copy the link.
"""
from __future__ import annotations

import logging
import smtplib
import ssl
from email.message import EmailMessage
from urllib.parse import unquote, urlsplit

from . import settings

OUTBOX: list[dict] = []          # the most recent messages (for local use and tests)
log = logging.getLogger("capsule.mail")


def send(to: str, subject: str, body: str) -> None:
    OUTBOX.append({"to": to, "subject": subject, "body": body})
    del OUTBOX[:-20]
    if not settings.SMTP_URL:
        if settings.PRODUCTION:   # never write a reset link into a production log
            log.error("Email to %s was not sent: SMTP_URL is not configured.", to)
        else:
            log.warning("Email to %s (not sent, no SMTP_URL) — %s\n%s", to, subject, body)
        return
    url = urlsplit(settings.SMTP_URL)
    message = EmailMessage()
    message["From"], message["To"], message["Subject"] = settings.MAIL_FROM, to, subject
    message.set_content(body)
    context = ssl.create_default_context()
    if url.scheme == "smtps":
        server: smtplib.SMTP = smtplib.SMTP_SSL(url.hostname or "", url.port or 465, timeout=15, context=context)
    else:
        server = smtplib.SMTP(url.hostname or "", url.port or 587, timeout=15)
    with server:
        if url.scheme != "smtps":
            server.starttls(context=context)
        if url.username:
            server.login(unquote(url.username), unquote(url.password or ""))
        server.send_message(message)
