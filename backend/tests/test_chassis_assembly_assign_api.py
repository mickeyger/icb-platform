"""WO v4.31 §3.1 — chassis assembly attribution (assign-to-bay) service + API tests.

Service unit tests call services.chassis directly; integration tests inject auth via
dependency_overrides[require_user] and assert the chassis.assembly_assign permission gate (granted to
production/planner in migration 0016). Mutations create fresh chassis (cleaned up; lifecycle events
cascade on delete) so the suite is rerunnable. Mirrors the fixture style of
test_planning_session_roles_api.py.
"""
import uuid
from datetime import date

import pytest
from fastapi import HTTPException


# ── fixtures ──────────────────────────────────────────────────────────────────
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
    from app.deps import require_user
    from starlette.testclient import TestClient
    app_mod.app.dependency_overrides[require_user] = lambda: admin
    with TestClient(app_mod.app) as c:
        yield c
    app_mod.app.dependency_overrides.pop(require_user, None)


@pytest.fixture
def make_user(app_mod):
    from app.database import SessionLocal, User
    created = []

    def _make(role):
        with SessionLocal() as db:
            u = User(username=f"t_{role}_{uuid.uuid4().hex[:6]}", password_hash="x", role=role)
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
def api_as(app_mod):
    from app.deps import require_user
    from starlette.testclient import TestClient

    def _as(user):
        app_mod.app.dependency_overrides[require_user] = lambda u=user: u
        return TestClient(app_mod.app)

    yield _as
    app_mod.app.dependency_overrides.pop(require_user, None)


@pytest.fixture
def fresh_chassis(app_mod):
    """Factory -> id of a fresh ChassisRecord. booked_in=True adds a cycle-1 VCL (status in_workshop)."""
    from app.database import SessionLocal
    from app.models.mes import ChassisLifecycleEvent, ChassisRecord
    ids = []

    def _make(booked_in=True):
        with SessionLocal() as db:
            rec = ChassisRecord(vin=f"TST{uuid.uuid4().hex[:12].upper()}", source="manual", status="received")
            db.add(rec)
            db.commit()
            db.refresh(rec)
            if booked_in:
                db.add(ChassisLifecycleEvent(chassis_record_id=rec.id, cycle_number=1,
                                             event_type="VCL", event_date=date.today()))
                rec.status = "in_workshop"
                db.commit()
            ids.append(rec.id)
            return rec.id

    yield _make
    with SessionLocal() as db:
        for rid in ids:
            for e in db.query(ChassisLifecycleEvent).filter_by(chassis_record_id=rid).all():
                db.delete(e)
            r = db.get(ChassisRecord, rid)
            if r:
                db.delete(r)
        db.commit()


def _bay_ids(n=2):
    """The first n FREE assembly bays (WO v4.33 hardening): positional bays 1..n broke whenever
    an interactive dev session left a chassis on a low bay — occupancy 409s aren't this suite's
    subject, so select unoccupied bays (event-derived, §0.12) and skip if too few are free."""
    from app.database import SessionLocal
    from app.models.mes import AssemblyBay
    from app.services.chassis import current_occupants
    with SessionLocal() as db:
        occupied = set(current_occupants(db))
        free = [b.id for b in db.query(AssemblyBay).filter_by(is_active=True)
                .order_by(AssemblyBay.sort_order).all() if b.id not in occupied]
    if len(free) < n:
        pytest.skip(f"only {len(free)} free assembly bays on this DB (need {n})")
    return free[:n]


# ── service unit tests ──────────────────────────────────────────────────────
def test_assign_refuses_chassis_without_vin(app_mod):   # WO v4.36b §3.4 NEW Gate 1 (VIN dimension)
    """A booked-in chassis with no VIN can't be assigned to a bay — 409 (the incomplete-chassis gate).
    Customer is set so ONLY the VIN dimension trips (the customer dimension is held pending re-ratification)."""
    from datetime import date as _date
    from app.database import SessionLocal
    from app.models.mes import ChassisLifecycleEvent, ChassisRecord
    from app.services import chassis as svc
    with SessionLocal() as db:
        rec = ChassisRecord(vin=None, source="manual", status="in_workshop", make="HINO",
                            customer_name="Gate1 VIN Test", created_by="t", updated_by="t")
        db.add(rec); db.flush()
        db.add(ChassisLifecycleEvent(chassis_record_id=rec.id, cycle_number=1,
                                     event_type="VCL", event_date=_date.today()))
        db.commit()
        rid = rec.id
    try:
        bay = _bay_ids(1)[0]
        with SessionLocal() as db:
            try:
                svc.assign_assembly_bay(db, rid, bay, who="admin")
                raise AssertionError("expected 409 — a VIN-less chassis can't be assigned to a bay")
            except HTTPException as e:
                assert e.status_code == 409
    finally:
        with SessionLocal() as db:
            for e in db.query(ChassisLifecycleEvent).filter_by(chassis_record_id=rid).all():
                db.delete(e)
            r = db.get(ChassisRecord, rid)
            if r:
                db.delete(r)
            db.commit()


def test_assign_sets_current_bay_and_event(app_mod, fresh_chassis):
    from app.database import SessionLocal
    from app.models.mes import ChassisRecord
    from app.services import chassis as svc
    rid, bay = fresh_chassis(), _bay_ids(1)[0]
    with SessionLocal() as db:
        evt = svc.assign_assembly_bay(db, rid, bay, who="admin")
        assert evt.event_type == "assembly_assigned" and evt.assembly_bay_id == bay
        rec = db.get(ChassisRecord, rid)
        assert rec.status == "in_assembly"          # §0.12: state denormalised onto status, not a column
        assert svc._current_assembly_bay_id(db, rid) == bay   # "which bay" derived from the latest event


def test_assign_reassign_moves_bay_no_duplicate(app_mod, fresh_chassis):
    from app.database import SessionLocal
    from app.models.mes import ChassisLifecycleEvent, ChassisRecord
    from app.services import chassis as svc
    rid = fresh_chassis()
    a, b = _bay_ids(2)
    with SessionLocal() as db:
        svc.assign_assembly_bay(db, rid, a, who="admin")
        svc.assign_assembly_bay(db, rid, b, who="admin")        # move A -> B
        events = db.query(ChassisLifecycleEvent).filter_by(
            chassis_record_id=rid, event_type="assembly_assigned").all()
        assert len(events) == 1 and events[0].assembly_bay_id == b   # UPSERT, not a second row
        assert db.get(ChassisRecord, rid).status == "in_assembly"
        assert svc._current_assembly_bay_id(db, rid) == b


def test_assign_occupied_409(app_mod, fresh_chassis):
    from app.database import SessionLocal
    from app.services import chassis as svc
    r1, r2, bay = fresh_chassis(), fresh_chassis(), _bay_ids(1)[0]
    with SessionLocal() as db:
        svc.assign_assembly_bay(db, r1, bay, who="admin")
    with SessionLocal() as db:
        with pytest.raises(HTTPException) as ei:
            svc.assign_assembly_bay(db, r2, bay, who="admin")
        assert ei.value.status_code == 409


def test_assign_no_open_cycle_422(app_mod, fresh_chassis):
    from app.database import SessionLocal
    from app.services import chassis as svc
    rid, bay = fresh_chassis(booked_in=False), _bay_ids(1)[0]      # no VCL -> not in the yard
    with SessionLocal() as db:
        with pytest.raises(HTTPException) as ei:
            svc.assign_assembly_bay(db, rid, bay, who="admin")
        assert ei.value.status_code == 422


def test_assign_unknown_bay_404(app_mod, fresh_chassis):
    from app.database import SessionLocal
    from app.services import chassis as svc
    rid = fresh_chassis()
    with SessionLocal() as db:
        with pytest.raises(HTTPException) as ei:
            svc.assign_assembly_bay(db, rid, 99999999, who="admin")
        assert ei.value.status_code == 404


# ── integration + permission tests ──────────────────────────────────────────
def test_bays_endpoints_seeded(api):
    assert len(api.get("/api/chassis-records/bays/assembly").json()) == 5
    assert len(api.get("/api/chassis-records/bays/parking").json()) == 24


def test_assign_endpoint_admin_201(api, fresh_chassis):
    rid, bay = fresh_chassis(), _bay_ids(1)[0]
    r = api.post(f"/api/chassis-records/{rid}/assembly", json={"assembly_bay_id": bay})
    assert r.status_code == 201
    assert r.json()["assembly_bay_id"] == bay and r.json()["event_type"] == "assembly_assigned"


def test_assign_permission_gate(api_as, make_user, fresh_chassis):
    a, b = _bay_ids(2)
    # production has chassis.assembly_assign (granted in 0016) -> allowed
    rid = fresh_chassis()
    ok = api_as(make_user("production")).post(f"/api/chassis-records/{rid}/assembly",
                                              json={"assembly_bay_id": a})
    assert ok.status_code == 201
    # a plain user has no grant -> 403 (gate runs before the handler body)
    rid2 = fresh_chassis()
    denied = api_as(make_user("user")).post(f"/api/chassis-records/{rid2}/assembly",
                                            json={"assembly_bay_id": b})
    assert denied.status_code == 403
