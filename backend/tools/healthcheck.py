"""External healthcheck — pings prod /health and emails on failure.

Designed to be run from cron on a different machine (laptop, another VPS,
shared host with cron) so it survives the prod box being completely down.
Uses stdlib only — no external deps.

Cron example (every 5 min):
  */5 * * * * /usr/bin/python3 /path/to/healthcheck.py >> ~/healthcheck.log 2>&1

Env vars:
  HEALTH_URL    — URL to probe (default https://faje.co.za/health)
  ALERT_FROM    — sender email (default no-reply@faje.co.za)
  ALERT_TO      — comma-separated recipient list (REQUIRED for email)
  ALERT_SMTP    — SMTP host (default smtp.faje.co.za)
  ALERT_PORT    — SMTP port (default 587)
  ALERT_USER    — SMTP username (optional)
  ALERT_PASS    — SMTP password (optional)
  STATE_FILE    — path to flap-suppression state file (default ~/.icecold-health)

Behaviour:
  - Sends one email when state transitions from OK → DOWN
  - Sends one "recovered" email when DOWN → OK
  - Does NOT spam every 5 minutes while down
"""
import os
import smtplib
import socket
import sys
from email.mime.text import MIMEText
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

URL        = os.environ.get("HEALTH_URL", "https://faje.co.za/health")
SMTP_HOST  = os.environ.get("ALERT_SMTP", "smtp.faje.co.za")
SMTP_PORT  = int(os.environ.get("ALERT_PORT", "587"))
ALERT_FROM = os.environ.get("ALERT_FROM", "no-reply@faje.co.za")
ALERT_TO   = os.environ.get("ALERT_TO",   "")
ALERT_USER = os.environ.get("ALERT_USER", "")
ALERT_PASS = os.environ.get("ALERT_PASS", "")
STATE_FILE = os.environ.get("STATE_FILE", os.path.expanduser("~/.icecold-health"))

TIMEOUT = 10  # seconds


def probe() -> tuple[bool, str]:
    try:
        req = Request(URL, headers={"User-Agent": "icecold-healthcheck/1.0"})
        with urlopen(req, timeout=TIMEOUT) as resp:
            code = resp.status
            if code == 200:
                return True, "200 OK"
            return False, f"HTTP {code}"
    except HTTPError as e:
        return False, f"HTTP {e.code}"
    except (URLError, socket.timeout, OSError) as e:
        return False, f"{type(e).__name__}: {e}"


def read_state() -> str:
    try:
        with open(STATE_FILE) as f:
            return f.read().strip() or "ok"
    except FileNotFoundError:
        return "ok"


def write_state(state: str):
    try:
        with open(STATE_FILE, "w") as f:
            f.write(state)
    except OSError as e:
        print(f"WARN: could not write state file {STATE_FILE}: {e}", file=sys.stderr)


def send_email(subject: str, body: str):
    if not ALERT_TO:
        print("ALERT_TO not set — skipping email")
        return
    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"]    = ALERT_FROM
    msg["To"]      = ALERT_TO
    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=15) as s:
            s.ehlo()
            try:
                s.starttls()
                s.ehlo()
            except smtplib.SMTPException:
                pass  # plain SMTP fallback
            if ALERT_USER:
                s.login(ALERT_USER, ALERT_PASS)
            s.sendmail(ALERT_FROM, [a.strip() for a in ALERT_TO.split(",") if a.strip()], msg.as_string())
        print(f"Sent: {subject}")
    except Exception as e:
        print(f"ERR: email send failed: {e}", file=sys.stderr)


def main():
    ok, detail = probe()
    prev = read_state()
    new = "ok" if ok else "down"
    if new == prev:
        print(f"[{URL}] {new} — {detail} (no change)")
        return 0 if ok else 1
    write_state(new)
    if not ok:
        send_email(
            f"[ALERT] IceCold {URL} is DOWN",
            f"Healthcheck failed for {URL}\n\nDetail: {detail}\n\nNo further alerts until recovered.",
        )
        print(f"[{URL}] DOWN — {detail} (alert sent)")
        return 1
    send_email(
        f"[OK] IceCold {URL} recovered",
        f"Healthcheck for {URL} returned 200 OK after a previous failure.",
    )
    print(f"[{URL}] RECOVERED — {detail} (alert sent)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
