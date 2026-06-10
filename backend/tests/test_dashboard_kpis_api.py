"""WO v4.31 §3.4 — GET /api/dashboard/kpis value parity with the source tables.

The endpoint shares compute_kpis() with the legacy Jinja dashboard (parity by construction); this
suite independently RE-DERIVES every metric from the underlying tables with the same formulas —
anchored on the response's own `as_of` timestamp so the time-window boundaries are identical —
and asserts equality, including all three approval-rate buckets (§3.4 verification reminder).
Read-only: no rows created.
"""
import json
from datetime import datetime, timedelta

import pytest


@pytest.fixture(scope="module")
def app_mod():
    import app.main as m
    from starlette.testclient import TestClient
    with TestClient(m.app) as _c:
        yield m


@pytest.fixture
def admin():
    from app.database import SessionLocal, User
    with SessionLocal() as db:
        return db.query(User).filter_by(username="admin").first()


@pytest.fixture
def api(app_mod, admin):
    """The dashboard router calls get_current_user(request, db) DIRECTLY (no Depends), so
    dependency_overrides can't inject — mint a real UserSession + cookie instead (the
    test_session_returns_csrf_token pattern). GETs skip CSRF validation."""
    from app.database import SessionLocal, UserSession
    from starlette.testclient import TestClient
    sid = "test-kpis-sess-v431"
    with SessionLocal() as db:
        db.merge(UserSession(id=sid, user_id=admin.id, role=admin.role, csrf_token="tok_v431_kpis"))
        db.commit()
    with TestClient(app_mod.app) as c:
        c.cookies.set("session_id", sid)
        yield c
    with SessionLocal() as db:
        row = db.get(UserSession, sid)
        if row:
            db.delete(row)
            db.commit()


def test_kpis_match_source_tables(api):
    from app.database import CalculationRecord, Material, SessionLocal

    body = api.get("/api/dashboard/kpis").json()
    as_of = datetime.fromisoformat(body["as_of"])          # the endpoint's own window anchor

    with SessionLocal() as db:
        week_ago = as_of - timedelta(days=7)
        exp_week = (db.query(CalculationRecord)
                    .filter(CalculationRecord.created_at >= week_ago).count())

        exp_total = 0.0
        exp_approved_value = 0.0
        for rj, approved_at in db.query(CalculationRecord.result_json,
                                        CalculationRecord.approved_at).all():
            if rj:
                try:
                    d = json.loads(rj)
                    v = float(d.get("selling_price") or d.get("grand_total") or 0)
                except Exception:
                    continue
                exp_total += v
                if approved_at:
                    exp_approved_value += v

        exp_approved_count = (db.query(CalculationRecord)
                              .filter(CalculationRecord.approved_at.isnot(None)).count())
        exp_mat = db.query(Material).filter_by(is_active=True).count()

        # approval-rate buckets — same boundaries as _compute_approval_rates, anchored on as_of
        cur_month = as_of.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        prev_month = (cur_month.replace(year=cur_month.year - 1, month=12)
                      if cur_month.month == 1 else cur_month.replace(month=cur_month.month - 1))

        def bucket(start, end):
            total = (db.query(CalculationRecord)
                     .filter(CalculationRecord.created_at >= start,
                             CalculationRecord.created_at < end).count())
            approved = (db.query(CalculationRecord)
                        .filter(CalculationRecord.created_at >= start,
                                CalculationRecord.created_at < end,
                                CalculationRecord.approved_at.isnot(None)).count())
            pct = round((approved / total) * 100, 1) if total else 0.0
            return {"approved": approved, "total": total, "pct": pct}

        exp_buckets = {"week": bucket(week_ago, as_of),
                       "month": bucket(cur_month, as_of),
                       "prev": bucket(prev_month, cur_month)}

    assert body["quotes_this_week"] == exp_week
    assert body["total_value_quoted"] == pytest.approx(exp_total)
    assert body["approved_value_quoted"] == pytest.approx(exp_approved_value)
    assert body["approved_count"] == exp_approved_count
    assert body["mat_count"] == exp_mat
    for k in ("week", "month", "prev"):                    # all three periods (§3.4 reminder)
        got = body["approval_rates"][k]
        assert got["approved"] == exp_buckets[k]["approved"], k
        assert got["total"] == exp_buckets[k]["total"], k
        assert got["pct"] == pytest.approx(exp_buckets[k]["pct"]), k


def test_kpis_requires_auth(app_mod):
    from starlette.testclient import TestClient
    with TestClient(app_mod.app) as c:                     # no session cookie -> 401
        assert c.get("/api/dashboard/kpis").status_code == 401
