"""Pytest fixtures for the ICB Platform backend.

These are smoke/integration tests that run against a real (local or CI)
PostgreSQL database which has had `alembic upgrade head` applied. The TestClient
fixture triggers the app's startup event (seed of the admin user + defaults).

WO v4.34.4 §3.1: the `pytest_sessionstart` hook below makes the v4.27 rule unviolatable — the
suite ABORTS before any test/fixture runs unless DATABASE_URL points at an isolated test DB
(db-name ending in `_test`). This stops the destructive seed-reset test from ever truncating the
shared dev DB again. See docs/testing/setup.md.
"""
import sys
from pathlib import Path

import pytest

# Make the backend package importable regardless of pytest's working directory.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from starlette.testclient import TestClient  # noqa: E402


def pytest_sessionstart(session):
    """WO v4.34.4 §0.3 — hard environment guard. Fires once, before collection; aborts the whole
    session (no test runs, no fixtures, no journey subprocess) when DATABASE_URL is not an isolated
    test DB. Keyed on db-NAME, not hostname (dev/test/CI all share localhost — §3.0)."""
    from app.config import settings
    from app.db_guard import assert_test_db, resolve_db_name, resolve_host
    url = settings.DATABASE_URL
    print(f"[db-guard] pytest DB target: host={resolve_host(url)} db={resolve_db_name(url)}")
    try:
        assert_test_db(url, context="pytest")
    except RuntimeError as exc:
        raise pytest.UsageError(str(exc))


@pytest.fixture(scope="session")
def client():
    import app.main  # imported lazily so config/.env load first

    with TestClient(app.main.app) as c:
        yield c
