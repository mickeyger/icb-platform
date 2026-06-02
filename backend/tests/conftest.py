"""Pytest fixtures for the ICB Platform backend.

These are smoke/integration tests that run against a real (local or CI)
PostgreSQL database which has had `alembic upgrade head` applied. The TestClient
fixture triggers the app's startup event (seed of the admin user + defaults).
"""
import sys
from pathlib import Path

import pytest

# Make the backend package importable regardless of pytest's working directory.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from starlette.testclient import TestClient  # noqa: E402


@pytest.fixture(scope="session")
def client():
    import app.main  # imported lazily so config/.env load first

    with TestClient(app.main.app) as c:
        yield c
