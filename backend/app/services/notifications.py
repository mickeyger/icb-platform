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


def _sender_from(url_parts) -> str:
    """Derive the From address from the SMTP_URL. Honours an explicit EMAIL_FROM override
    (needed for real relays like Gmail where the login user is not user@host); otherwise
    falls back to the historic user@host / feedback@host derivation."""
    override = (getattr(settings, "EMAIL_FROM", "") or "").strip()
    if override:
        return override
    host = url_parts.hostname or "localhost"
    return (url_parts.username and f"{url_parts.username}@{host}") or f"feedback@{host}"


def _deliver(msg: EmailMessage, url: str) -> None:
    """Open the SMTP_URL connection and hand the message to the server. send_message()
    derives the envelope recipients from the To/Cc headers on the message. Raises on any
    transport error (the callers wrap this best-effort)."""
    p = urlparse(url)
    use_ssl = p.scheme in ("smtp+ssl", "smtps")
    host = p.hostname or "localhost"
    port = p.port or (465 if use_ssl else 587)
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
        msg = EmailMessage()
        msg["Subject"] = subject[:200]
        msg["From"] = _sender_from(urlparse(url))
        msg["To"] = recipient
        msg.set_content(body)
        _deliver(msg, url)
        logger.info("feedback email sent to %s", recipient)
        return True
    except Exception as e:  # noqa: BLE001
        logger.warning("feedback email send failed: %s", str(e)[:200])
        return False


def send_email_multi(subject: str, body: str, to: list[str],
                     cc: list[str] | None = None) -> bool:
    """Send one plaintext email to many To + Cc recipients via settings.SMTP_URL. Used by the
    Pre-Job Card "Submit for Check" auto-send (v1.39.3): the Sales + Planner signers go on To,
    the card's CC list on Cc. Returns False (no-op) when SMTP is unconfigured or there are no
    recipients at all. De-dupes and drops blanks. Never raises — a delivery failure must not
    fail the submit that triggered it (log-and-continue, Phase-1 contract)."""
    url = (settings.SMTP_URL or "").strip()

    def _clean(addrs: list[str] | None) -> list[str]:
        seen: dict[str, None] = {}
        for a in addrs or []:
            a = (a or "").strip()
            if a and a not in seen:
                seen[a] = None
        return list(seen)

    to_list = _clean(to)
    # a Cc that duplicates a To is dropped (no double-delivery / self-Cc noise)
    cc_list = [a for a in _clean(cc) if a not in to_list]
    if not url or not (to_list or cc_list):
        logger.info("send_email_multi skipped (smtp_configured=%s, recipients=%d)",
                    bool(url), len(to_list) + len(cc_list))
        return False
    try:
        msg = EmailMessage()
        msg["Subject"] = subject[:200]
        msg["From"] = _sender_from(urlparse(url))
        if to_list:
            msg["To"] = ", ".join(to_list)
        if cc_list:
            msg["Cc"] = ", ".join(cc_list)
        msg.set_content(body)
        _deliver(msg, url)
        logger.info("prejob check email sent (to=%d, cc=%d)", len(to_list), len(cc_list))
        return True
    except Exception as e:  # noqa: BLE001
        logger.warning("prejob check email send failed: %s", str(e)[:200])
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
