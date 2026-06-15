"""WO v4.34.4 §3.1 — unit tests for the shared DB-name safety guard (app/db_guard.py).

Pure-logic tests (no DB connection). On CI these run against icb_test, but the assertions only inspect
URL strings. The guard is the mechanism that makes the v4.27 rule unviolatable.
"""
import pytest

from app.db_guard import assert_test_db, is_test_db, resolve_db_name, resolve_host

DEV = "postgresql+psycopg://icb_app:icb_app_dev@localhost:5432/icb"
TEST = "postgresql+psycopg://icb_app:icb_app_dev@localhost:5432/icb_test"


def test_resolve_db_name_and_host():
    assert resolve_db_name(TEST) == "icb_test"
    assert resolve_db_name(DEV) == "icb"
    assert resolve_host(TEST) == "localhost"          # dev + test share the host — hostname can't discriminate


def test_is_test_db():
    assert is_test_db(TEST) is True
    assert is_test_db(DEV) is False
    assert is_test_db("postgresql://u@host/anything_test") is True


def test_assert_test_db_allows_test_db():
    assert assert_test_db(TEST, context="pytest") == "icb_test"


def test_assert_test_db_refuses_shared_dev_db():
    with pytest.raises(RuntimeError) as exc:
        assert_test_db(DEV, context="pytest")
    msg = str(exc.value)
    assert "REFUSED" in msg and "icb" in msg and "_test" in msg   # names the offending db + the remedy


def test_assert_test_db_refuses_non_test_names_on_any_host():
    # Same-host guard is by NAME: a prod-looking DB on localhost is still refused.
    with pytest.raises(RuntimeError):
        assert_test_db("postgresql://u@localhost/icb_prod", context="script")
