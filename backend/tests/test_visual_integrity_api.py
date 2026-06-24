"""WO v4.36b §3.6 — visual-integrity API integration tests.

End-to-end role-based filtering (role -> session -> endpoint -> filter): turns the §3.5 "thin
pass-through" claim into a test-asserted fact via dependency_overrides[require_user] role injection
(the BA's §3.5 fold-in). Plus the flag triggered -> resolved lifecycle through the real endpoints.
Execution on CI/icb_test per ADR 0011; self-cleaning (ZZVIAPI marker).
"""
import uuid
from datetime import datetime, timedelta, timezone

import pytest

_MARK = "ZZVIAPI"
UTC = timezone.utc
_ALL_GROUPS = {"Chassis", "Jobs", "Bays", "Sign-offs", "Stale Reviews"}


@pytest.fixture(scope="module")
def app_mod():
    import app.main as m
    from starlette.testclient import TestClient
    with TestClient(m.app) as _c:
        yield m


@pytest.fixture
def make_user(app_mod):
    """Create a throwaway User with the given role; deleted on teardown."""
    from app.database import SessionLocal, User
    created = []

    def _make(role):
        with SessionLocal() as db:
            u = User(username=f"vi_{role}_{uuid.uuid4().hex[:6]}", password_hash="x", role=role)
            db.add(u)
            db.commit()
            db.refresh(u)
            created.append(u.id)
            return u
    yield _make
    with SessionLocal() as db:
        for uid in created:
            u = db.get(User, uid)
            if u:
                db.delete(u)
        db.commit()


@pytest.fixture
def client_as(app_mod):
    """A TestClient whose require_user resolves to the given user (its role drives §3.5 filtering)."""
    from app.deps import require_user
    from starlette.testclient import TestClient

    def _as(user):
        app_mod.app.dependency_overrides[require_user] = lambda u=user: u
        return TestClient(app_mod.app)
    yield _as
    app_mod.app.dependency_overrides.pop(require_user, None)


@pytest.fixture
def flagged_chassis():
    """A live, backdated (>24h) VIN-less chassis → trips `chassis_no_vin` (Chassis group). Customer set
    so ONLY that flag trips. The endpoint computes age vs real now, so created_at is backdated."""
    from app.database import SessionLocal
    from app.models.mes import ChassisRecord

    def _purge(db):
        db.query(ChassisRecord).filter(
            ChassisRecord.created_source_ref.like(f"{_MARK}%")).delete(synchronize_session=False)
        db.commit()
    with SessionLocal() as db:
        _purge(db)
        rec = ChassisRecord(vin=None, customer_name="VI API Cust", make="HINO", status="received",
                            source="manual", created_via="manual_chassis_menu",
                            created_source_ref=f"{_MARK}-{uuid.uuid4().hex[:6]}",
                            created_at=datetime.now(UTC) - timedelta(days=2),
                            created_by="t", updated_by="t")
        db.add(rec)
        db.commit()
        db.refresh(rec)
        cid = rec.id
    yield cid
    with SessionLocal() as db:
        _purge(db)


def _summary(client):
    r = client.get("/api/visual-integrity/flags/summary")
    assert r.status_code == 200, r.text
    return r.json()


def test_summary_role_filter(make_user, client_as, flagged_chassis):
    """Role → session → endpoint → filter, asserted end-to-end. admin sees all groups + the seeded
    chassis_no_vin; workshop sees only Jobs+Bays (no Chassis group, no chassis_no_vin); sales sees
    Chassis+Sign-offs+Stale-Reviews (the chassis flag) but no Jobs/Bays group."""
    admin = _summary(client_as(make_user("admin")))
    workshop = _summary(client_as(make_user("workshop")))
    sales = _summary(client_as(make_user("sales")))

    assert set(admin["by_group"]) == _ALL_GROUPS
    assert admin["by_flag"].get("chassis_no_vin", 0) >= 1

    assert set(workshop["by_group"]) == {"Jobs", "Bays"}
    assert "chassis_no_vin" not in workshop["by_flag"]            # Chassis group hidden from workshop

    assert set(sales["by_group"]) == {"Chassis", "Sign-offs", "Stale Reviews"}
    assert sales["by_flag"].get("chassis_no_vin", 0) >= 1         # Chassis group visible to sales


def test_flag_triggered_then_resolved(make_user, client_as, flagged_chassis):
    """The seeded VIN-less chassis appears in the chassis drill-through under chassis_no_vin; once a VIN
    is captured the flag clears and it drops out."""
    admin = client_as(make_user("admin"))
    listed = admin.get("/api/visual-integrity/flags/chassis?flag=chassis_no_vin")
    assert listed.status_code == 200, listed.text
    assert any(r["chassis_id"] == flagged_chassis for r in listed.json())   # triggered

    from app.database import SessionLocal
    from app.models.mes import ChassisRecord
    with SessionLocal() as db:                                    # resolve — capture a VIN
        db.get(ChassisRecord, flagged_chassis).vin = "1HGCM82633A099999"
        db.commit()

    again = admin.get("/api/visual-integrity/flags/chassis?flag=chassis_no_vin")
    assert not any(r["chassis_id"] == flagged_chassis for r in again.json())   # resolved
