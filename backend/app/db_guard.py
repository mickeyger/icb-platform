"""WO v4.34.4 §0.3 — the shared database-safety guard.

The ONE place that decides "is this DATABASE_URL safe for a destructive operation?" Used by both the
pytest session-start hook (§3.1, tests) and `scripts/_environment_guard.py` (§3.2, every DB-mutating
script). It makes the v4.27 standing rule — *never run a destructive op against the shared dev DB* —
unviolatable in code rather than aspirational.

WHY db-NAME, not hostname: the shared dev DB, every developer's test DB, and CI all live on the SAME
host (`localhost`). Hostname cannot distinguish them (confirmed §3.0). The discriminator is the
database NAME: the shared dev DB is `icb`; isolated test DBs end in `_test` (e.g. `icb_test`). CI is
pointed at `icb_test` too (BA decision), so a single rule covers local dev + CI with no bypass path.
"""
from __future__ import annotations

from urllib.parse import urlparse

TEST_DB_SUFFIX = "_test"


def resolve_db_name(database_url: str) -> str:
    """The database name from a SQLAlchemy/psycopg URL (handles the `+psycopg` dialect suffix)."""
    return (urlparse(database_url).path or "").lstrip("/")


def resolve_host(database_url: str) -> str:
    return urlparse(database_url).hostname or ""


def is_test_db(database_url: str) -> bool:
    """True only for an isolated test database (name ends in `_test`)."""
    return resolve_db_name(database_url).endswith(TEST_DB_SUFFIX)


def assert_test_db(database_url: str, *, context: str) -> str:
    """Raise RuntimeError unless `database_url` points at an isolated test DB. Returns the db name.

    `context` names the caller (e.g. "pytest", "seed_from_mockup --reset") for the error message.
    """
    name = resolve_db_name(database_url)
    host = resolve_host(database_url)
    if not name.endswith(TEST_DB_SUFFIX):
        raise RuntimeError(
            f"[db-guard] REFUSED: {context} must run against an isolated test database "
            f"(DATABASE_URL db-name ending in '{TEST_DB_SUFFIX}'), but it resolves to "
            f"'{name}' on host '{host}'.\n"
            f"  -> Set DATABASE_URL to your test database (e.g. .../{name or 'icb'}{TEST_DB_SUFFIX}) "
            f"before running. See docs/testing/setup.md.\n"
            f"  This guard makes the v4.27 rule (never run destructive ops on the shared dev DB) "
            f"unviolatable; there is no override flag by design."
        )
    return name
