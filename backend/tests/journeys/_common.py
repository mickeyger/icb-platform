"""WO v4.26.1 — shared substrate for the MES end-to-end *journey* tests.

These tests drive a REAL browser (Playwright / Chromium) against a REAL uvicorn
server that serves the built React SPA (`frontend/dist`) backed by the seeded
`icb_mes` database. They are deliberately kept OUT of the default ``pytest`` run
(see ``.github/workflows/ci.yml`` -> ``pytest --ignore=tests/journeys``) because
they need a browser binary plus a booted HTTP server; CI runs them in a dedicated
"Journey tests" step on both Linux and Windows.

Design notes
------------
* **Server** — a session-scoped fixture (:func:`live_server`) boots
  ``uvicorn app.main:app`` on 127.0.0.1:8000 as a subprocess with
  ``MES_DEMO_AUTOLOGIN_USER=admin`` so the SPA can mint an admin session without
  a password (see ``app/routers/pre_job_card.py`` autologin). Set the ``MES_BASE``
  env var to point at an already-running server and the boot is skipped — handy
  for local debugging against ``start`` + ``npm run dev`` proxies.
* **Browser** — raw ``playwright.sync_api`` (NOT the pytest-playwright plugin, to
  keep the dependency surface minimal): one Chromium per session, a fresh
  context + page per test for isolation.
* **Autologin gotcha** (learned the hard way in v4.26): you MUST load ``/mes-app/``
  FIRST so the React app autologins before deep-linking any sub-route, otherwise
  the auth guard bounces you to the Jinja ``/login`` page. :func:`admin_session`
  encapsulates that ordering — always start a journey through it.

Selector policy (WO v4.26.1 §5): journey tests select on ``data-testid`` only —
never CSS class names (which are styling, not contract).
"""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

import pytest
from playwright.sync_api import Browser, BrowserContext, Page, sync_playwright

# ── Repo layout ──────────────────────────────────────────────────────────────
# This file lives at backend/tests/journeys/_common.py
_BACKEND_DIR = Path(__file__).resolve().parents[2]
_REPO_ROOT = _BACKEND_DIR.parent
_DIST_DIR = _REPO_ROOT / "frontend" / "dist"
SCREENSHOT_ROOT = _REPO_ROOT / "docs" / "screenshots" / "journeys"

# ── Server boot config ───────────────────────────────────────────────────────
_HOST = "127.0.0.1"
_PORT = 8000
_DEFAULT_BASE = f"http://{_HOST}:{_PORT}"
_HEALTH_TIMEOUT_S = 90.0

# Headed mode for local debugging: MES_JOURNEY_HEADED=1
_HEADLESS = os.environ.get("MES_JOURNEY_HEADED", "").strip().lower() not in ("1", "true", "yes")


# ── Low-level helpers ────────────────────────────────────────────────────────
def _port_in_use(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex((host, port)) == 0


def _wait_for_health(base: str, proc: "subprocess.Popen | None" = None,
                     log_path: "Path | None" = None, timeout: float = _HEALTH_TIMEOUT_S) -> None:
    """Poll ``<base>/health`` until it returns 200, or fail with the server log."""
    url = f"{base.rstrip('/')}/health"
    deadline = time.monotonic() + timeout
    last_err: object = None
    while time.monotonic() < deadline:
        if proc is not None and proc.poll() is not None:
            raise RuntimeError(
                f"uvicorn exited early (code {proc.returncode}).\n{_tail(log_path)}"
            )
        try:
            with urlopen(url, timeout=2) as resp:
                if resp.status == 200:
                    return
        except (URLError, OSError) as exc:  # connection refused while booting
            last_err = exc
        time.sleep(0.4)
    raise RuntimeError(
        f"Server health check failed at {url} after {timeout:.0f}s "
        f"(last error: {last_err}).\n{_tail(log_path)}"
    )


def _tail(log_path: "Path | None", n: int = 40) -> str:
    if not log_path or not log_path.exists():
        return "(no server log captured)"
    try:
        lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return "(server log unreadable)"
    return "----- server log (tail) -----\n" + "\n".join(lines[-n:])


# ── Session-scoped fixtures ──────────────────────────────────────────────────
@pytest.fixture(scope="session")
def live_server():
    """Yield a base URL for a running MES server.

    If ``MES_BASE`` is set, assume an external server is already up and just
    return it. Otherwise boot ``uvicorn app.main:app`` on 127.0.0.1:8000 as a
    subprocess (autologin user = admin) and tear it down at session end.
    """
    external = os.environ.get("MES_BASE")
    if external:
        base = external.rstrip("/")
        _wait_for_health(base)
        yield base
        return

    if not _DIST_DIR.exists():
        pytest.fail(
            f"Frontend build not found at {_DIST_DIR}.\n"
            "Run `npm run build` in frontend/ before the journey tests "
            "(CI does this in the 'Build frontend' step)."
        )
    if _port_in_use(_HOST, _PORT):
        pytest.fail(
            f"Port {_PORT} is already in use. Stop that process, or set MES_BASE "
            "to point the journey tests at the running server instead."
        )

    env = {**os.environ, "MES_DEMO_AUTOLOGIN_USER": "admin"}
    log_handle = tempfile.NamedTemporaryFile(
        prefix="mes-journey-uvicorn-", suffix=".log", delete=False
    )
    log_path = Path(log_handle.name)
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--host", _HOST, "--port", str(_PORT)],
        cwd=str(_BACKEND_DIR),
        env=env,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
    )
    try:
        _wait_for_health(_DEFAULT_BASE, proc=proc, log_path=log_path)
        yield _DEFAULT_BASE
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=10)
        log_handle.close()
        try:
            log_path.unlink()
        except OSError:
            pass


@pytest.fixture(scope="session")
def playwright_instance():
    with sync_playwright() as pw:
        yield pw


@pytest.fixture(scope="session")
def browser(playwright_instance) -> "Browser":  # type: ignore[valid-type]
    browser = playwright_instance.chromium.launch(headless=_HEADLESS)
    yield browser
    browser.close()


# ── Per-test fixtures ────────────────────────────────────────────────────────
@pytest.fixture()
def browser_context(browser: "Browser", live_server: str) -> "BrowserContext":  # type: ignore[valid-type]
    context = browser.new_context(base_url=live_server, viewport={"width": 1440, "height": 900})
    yield context
    context.close()


@pytest.fixture()
def page(browser_context: "BrowserContext") -> "Page":  # type: ignore[valid-type]
    page = browser_context.new_page()
    page.set_default_timeout(15_000)
    yield page


# ── Journey helpers ──────────────────────────────────────────────────────────
def wait_for_dashboard(page: "Page") -> None:
    """Block until the authenticated React shell has rendered.

    ``data-testid="top-nav"`` only mounts inside :class:`Layout`, which the auth
    guard refuses to render until a session exists — so its presence proves the
    autologin round-trip completed.
    """
    page.wait_for_selector("[data-testid='top-nav']", timeout=30_000)


def admin_session(page: "Page") -> "Page":
    """Load the SPA so it autologins as admin, then return the page on the shell.

    Always call this before deep-linking any ``/mes-app`` sub-route: an
    unauthenticated deep-link races the auth guard and may bounce to the Jinja
    ``/login`` page (the v4.26 lesson).
    """
    page.goto("/mes-app/")
    wait_for_dashboard(page)
    return page


def shot(page: "Page", name: str, journey: str = "admin") -> Path:
    """Save a full-page screenshot under docs/screenshots/journeys/<journey>/."""
    out_dir = SCREENSHOT_ROOT / journey
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{name}.png"
    page.screenshot(path=str(path), full_page=True)
    return path
