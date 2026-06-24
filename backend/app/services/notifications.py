"""Outbound notifications for the Feedback Portal (WO v4.38).

Two channels behind one tiny interface:
  * send_email()    — server-side SMTP, consuming settings.SMTP_URL. (The MES had
                      NO server-side sender before v4.38 — the Pre-Job Card "email"
                      is a mailto: payload; see WO v4.38 §3.0.) No-op when SMTP_URL
                      is empty (the existing dev-mode contract).
  * send_whatsapp() — Twilio. Lazy-imported + gated on creds; logs and no-ops until
                      TWILIO_* land in the env (Week 2). Adding the creds +
                      `pip install twilio` activates it with no code change.

Both are best-effort and never raise — a delivery failure must not fail the
submission that triggered it. Each returns True only on a real send."""
from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage
from urllib.parse import urlparse

from ..config import settings

logger = logging.getLogger("icb.feedback.notify")


def send_email(subject: str, body: str, to: str | None = None) -> bool:
    """Send a plaintext email via settings.SMTP_URL. Returns False (no-op) when
    SMTP is unconfigured or no recipient is set. Never raises.

    SMTP_URL forms supported:
        smtp://[user:pass@]host[:port]        (plain; STARTTLS attempted if offered)
        smtp+ssl://[user:pass@]host[:port]    (implicit TLS, e.g. :465)
    """
    url = (settings.SMTP_URL or "").strip()
    recipient = (to or settings.FEEDBACK_NOTIFY_EMAIL or "").strip()
    if not url or not recipient:
        logger.info("send_email skipped (smtp_configured=%s, recipient_set=%s)", bool(url), bool(recipient))
        return False
    try:
        p = urlparse(url)
        use_ssl = p.scheme in ("smtp+ssl", "smtps")
        host = p.hostname or "localhost"
        port = p.port or (465 if use_ssl else 587)
        sender = (p.username and f"{p.username}@{host}") or f"feedback@{host}"
        msg = EmailMessage()
        msg["Subject"] = subject[:200]
        msg["From"] = sender
        msg["To"] = recipient
        msg.set_content(body)
        if use_ssl:
            with smtplib.SMTP_SSL(host, port, timeout=10) as s:
                if p.username:
                    s.login(p.username, p.password or "")
                s.send_message(msg)
        else:
            with smtplib.SMTP(host, port, timeout=10) as s:
                try:
                    s.starttls()
                except smtplib.SMTPException:
                    pass  # relay without STARTTLS — proceed plain (dev mailcatchers)
                if p.username:
                    s.login(p.username, p.password or "")
                s.send_message(msg)
        logger.info("feedback email sent to %s", recipient)
        return True
    except Exception as e:  # noqa: BLE001
        logger.warning("feedback email send failed: %s", str(e)[:200])
        return False


def send_whatsapp(body: str, to: str | None = None) -> bool:
    """Send a WhatsApp ping via Twilio. No-op (logs) until TWILIO_* creds are set;
    activates when they are present and the twilio SDK is installed. Never raises."""
    sid = (settings.TWILIO_ACCOUNT_SID or "").strip()
    token = (settings.TWILIO_AUTH_TOKEN or "").strip()
    from_ = (settings.TWILIO_WHATSAPP_FROM or "").strip()
    target = (to or settings.FEEDBACK_NOTIFY_WHATSAPP or "").strip()
    if not (sid and token and from_ and target):
        logger.info("send_whatsapp stubbed (creds not fully set) — would send: %s", body[:120])
        return False
    try:
        from twilio.rest import Client  # lazy: only needed when creds are present
    except ImportError:
        logger.warning("twilio SDK not installed — WhatsApp ping skipped")
        return False
    try:
        if not target.startswith("whatsapp:"):
            target = f"whatsapp:{target}"
        Client(sid, token).messages.create(body=body[:1500], from_=from_, to=target)
        logger.info("feedback WhatsApp ping sent to %s", target)
        return True
    except Exception as e:  # noqa: BLE001
        logger.warning("feedback WhatsApp send failed: %s", str(e)[:200])
        return False
