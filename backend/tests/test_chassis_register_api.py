"""Tests for the /api/chassis-register surface (WO v4.22, §3.3).

Read-only chassis lifecycle API. The fixture inserts a chassis_register row directly
(the table is ETL-loaded; the API never writes), exercises the three GET endpoints,
and cleans up.
"""
from datetime import date

import pytest


@pytest.fixture(scope="module")
def app_mod():
    import app.main as m
    from starlette.testclient import TestClient
    with TestClient(m.app) as _c:   # triggers startup seed
        yield m


@pytest.fixture
def user():
    from app.database import SessionLocal, User
    with SessionLocal() as db:
        return db.query(User).filter_by(username="admin").first()


@pytest.fixture
def api(app_mod, user):
    from app.deps import require_user
    app_mod.app.dependency_overrides[require_user] = lambda: user
    from starlette.testclient import TestClient
    with TestClient(app_mod.app) as c:
        yield c
    app_mod.app.dependency_overrides.pop(require_user, None)


@pytest.fixture
def chassis_row(app_mod):
    from app.database import SessionLocal
    from app.models.mes import ChassisRegister
    created = []

    def _make(**kw):
        with SessionLocal() as db:
            row = ChassisRegister(
                job_number=kw.get("job_number", "TST-CH-1"),
                customer_name=kw.get("customer_name", "Test Chassis Customer"),
                vehicle_id_no=kw.get("vehicle_id_no", "VINTEST123"),
                make=kw.get("make", "SCANIA"),
                date_received_1=date(2026, 2, 11),
                raw_row_json={"JOB NO": kw.get("job_number", "TST-CH-1"), "extra": "kept"},
            )
            db.add(row)
            db.commit()
            created.append(row.id)
            return row.id

    yield _make
    with SessionLocal() as db:
        for rid in created:
            r = db.get(ChassisRegister, rid)
            if r:
                db.delete(r)
        db.commit()


def test_chassis_register_list(api, chassis_row):
    rid = chassis_row(job_number="TST-CH-LIST", make="ISUZU")
    rows = api.get("/api/chassis-register?limit=1000").json()
    row = next((r for r in rows if r["id"] == rid), None)
    assert row is not None
    assert row["job_number"] == "TST-CH-LIST"
    assert row["make"] == "ISUZU"


def test_chassis_register_detail_carries_raw_json(api, chassis_row):
    rid = chassis_row()
    d = api.get(f"/api/chassis-register/{rid}").json()
    assert d["vehicle_id_no"] == "VINTEST123"
    assert d["date_received_1"] == "2026-02-11"        # Date serialised ISO
    assert d["raw_row_json"]["extra"] == "kept"        # full source row preserved


def test_chassis_register_by_job(api, chassis_row):
    chassis_row(job_number="TST-CH-BYJOB")
    rows = api.get("/api/chassis-register/by-job/TST-CH-BYJOB").json()
    assert len(rows) >= 1
    assert rows[0]["job_number"] == "TST-CH-BYJOB"


def test_chassis_register_404(api):
    assert api.get("/api/chassis-register/99999999").status_code == 404


def test_chassis_register_requires_auth(app_mod):
    from app.deps import require_user
    from starlette.testclient import TestClient
    app_mod.app.dependency_overrides.pop(require_user, None)
    with TestClient(app_mod.app) as c:
        assert c.get("/api/chassis-register").status_code == 401
