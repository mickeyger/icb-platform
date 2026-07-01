"""v1.39.3 backport — send_email_multi (multi To + Cc) unit tests.

The Pre-Job "Submit for Check" auto-send needs one email to many recipients (Sales + Planner on
To, the card CC list on Cc). These tests exercise send_email_multi directly, monkeypatching the
transport (_deliver) so no real SMTP is touched: recipient hygiene (blank-drop, de-dupe,
Cc-that-duplicates-To dropped), the no-op contract (SMTP unset / no recipients), and the
never-raises contract (a transport failure returns False, does not propagate).
"""
from email.message import EmailMessage

import pytest

from app.services import notifications


@pytest.fixture
def capture(monkeypatch):
    """Force SMTP 'configured' and capture the EmailMessage handed to the transport."""
    sent: list[EmailMessage] = []
    monkeypatch.setattr(notifications.settings, "SMTP_URL", "smtp://user:pw@mail.test:587", raising=False)
    monkeypatch.setattr(notifications.settings, "EMAIL_FROM", "", raising=False)
    monkeypatch.setattr(notifications, "_deliver", lambda msg, url: sent.append(msg))
    return sent


def test_sends_to_and_cc(capture):
    ok = notifications.send_email_multi("Subj", "Body",
                                        to=["a@x.co", "b@x.co"], cc=["c@x.co"])
    assert ok is True
    assert len(capture) == 1
    msg = capture[0]
    assert msg["To"] == "a@x.co, b@x.co"
    assert msg["Cc"] == "c@x.co"
    assert msg["Subject"] == "Subj"
    assert msg.get_content().strip() == "Body"


def test_dedupes_and_drops_blanks(capture):
    ok = notifications.send_email_multi("S", "B",
                                        to=["a@x.co", " a@x.co ", "", None], cc=["  "])
    assert ok is True
    assert capture[0]["To"] == "a@x.co"
    assert capture[0]["Cc"] is None                     # blank CC dropped → no Cc header


def test_cc_duplicating_a_to_is_dropped(capture):
    ok = notifications.send_email_multi("S", "B", to=["a@x.co"], cc=["a@x.co", "d@x.co"])
    assert ok is True
    assert capture[0]["To"] == "a@x.co"
    assert capture[0]["Cc"] == "d@x.co"                 # a@x.co not double-delivered


def test_noop_when_smtp_unset(monkeypatch):
    calls = []
    monkeypatch.setattr(notifications.settings, "SMTP_URL", "", raising=False)
    monkeypatch.setattr(notifications, "_deliver", lambda msg, url: calls.append(msg))
    assert notifications.send_email_multi("S", "B", to=["a@x.co"]) is False
    assert calls == []                                  # transport never opened


def test_noop_when_no_recipients(capture):
    assert notifications.send_email_multi("S", "B", to=[], cc=[]) is False
    assert capture == []


def test_never_raises_on_transport_failure(monkeypatch):
    def boom(msg, url):
        raise OSError("smtp down")
    monkeypatch.setattr(notifications.settings, "SMTP_URL", "smtp://mail.test", raising=False)
    monkeypatch.setattr(notifications, "_deliver", boom)
    # Best-effort contract: swallow the error, return False (never propagate).
    assert notifications.send_email_multi("S", "B", to=["a@x.co"]) is False


def test_email_from_override_is_honoured(monkeypatch):
    sent: list[EmailMessage] = []
    monkeypatch.setattr(notifications.settings, "SMTP_URL", "smtp://login:pw@smtp.gmail.com:587", raising=False)
    monkeypatch.setattr(notifications.settings, "EMAIL_FROM", "mes@icecoldgrp.co.za", raising=False)
    monkeypatch.setattr(notifications, "_deliver", lambda msg, url: sent.append(msg))
    assert notifications.send_email_multi("S", "B", to=["a@x.co"]) is True
    assert sent[0]["From"] == "mes@icecoldgrp.co.za"    # not login@smtp.gmail.com
