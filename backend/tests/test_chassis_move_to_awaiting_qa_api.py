"""WO v4.36a.1 §0.5 — the Awaiting-QA handoff: record_moved_to_awaiting_qa service + the
POST /api/chassis-records/{id}/move-to-awaiting-qa endpoint + the GET /api/chassis-records/awaiting-qa zone.

Unlike body_attached (a PHASE-only event that keeps status='in_assembly'), this is a workflow-phase
TRANSITION: it writes a 'moved_to_awaiting_qa' event AND promotes the chassis status to 'awaiting_qa'
atomically — which, because current_occupants() gates on status=='in_assembly', drops the chassis out of
bay occupancy everywhere (the bay derives 'empty'). These tests assert all four guards (on a bay / body
attached / not already moved / live), the atomic status flip, the bay-clearing, the permission gate, and
the zone list. Mirrors the fixture style of test_chassis_assembly_assign_api.py; runs on *_test only.
"""
import uuid
from datetime import date, datetime, timezone

import pytest
from fastapi import HTTPException


# ── fixtures (mirror test_chassis_assembly_assign_api.py) ────────────────────────
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
            rec = ChassisRecord(vin=f"TST{uuid.uuid4().hex[:12].upper()}", source="manual", status="received",
                                customer_name="Bay Test Cust")   # WO v4.36b §3.4 — Gate 1 needs a resolvable customer
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
    """The first n FREE assembly bays (event-derived occupancy) — skip if too few are free, so an
    interactive dev session parked on a low bay doesn't fail this suite (mirrors the assign suite)."""
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


@pytest.fixture
def on_bay_with_body(fresh_chassis):
    """A chassis on an assembly bay (status in_assembly) WITH a body_attached event this cycle — the full
    precondition for moving to Awaiting QA. The body_attached event is inserted directly (the move guard
    only checks _has_event, not the body↔job link machinery). Returns (record_id, bay_id)."""
    from app.database import SessionLocal
    from app.models.mes import ChassisLifecycleEvent
    from app.services import chassis as svc

    def _make():
        rid, bay = fresh_chassis(), _bay_ids(1)[0]
        with SessionLocal() as db:
            svc.assign_assembly_bay(db, rid, bay, who="admin")          # -> in_assembly + assembly_assigned
            cycle = svc._latest_cycle(db, rid)
            db.add(ChassisLifecycleEvent(chassis_record_id=rid, cycle_number=cycle,
                                         event_type="body_attached", event_date=date.today()))
            db.commit()
        return rid, bay

    return _make


# ── service unit tests — the four guards + the atomic flip ───────────────────────
def test_move_writes_event_and_promotes_status(app_mod, on_bay_with_body):
    from app.database import SessionLocal
    from app.models.mes import ChassisRecord
    from app.services import chassis as svc
    rid, _ = on_bay_with_body()
    with SessionLocal() as db:
        evt = svc.record_moved_to_awaiting_qa(db, rid, who="admin")
        assert evt.event_type == "moved_to_awaiting_qa"
        assert db.get(ChassisRecord, rid).status == "awaiting_qa"       # PHASE TRANSITION (not phase-only)


def test_move_clears_bay_occupancy(app_mod, on_bay_with_body):
    """The single status write is the bay-clearing mechanism: current_occupants() gates on in_assembly."""
    from app.database import SessionLocal
    from app.services import chassis as svc
    rid, bay = on_bay_with_body()
    with SessionLocal() as db:
        occ = svc.current_occupants(db)
        assert bay in occ and occ[bay]["chassis_id"] == rid            # on the bay before the move
    with SessionLocal() as db:
        svc.record_moved_to_awaiting_qa(db, rid, who="admin")
    with SessionLocal() as db:
        from app.models.mes import ChassisRecord
        occ = svc.current_occupants(db)
        assert bay not in occ                                          # bay derives EMPTY after the move
        # The bay clears via the STATUS transition (current_occupants gates on in_assembly). move-to-qa is
        # status-promoting, NOT event-deleting — the assembly_assigned event intentionally persists — so
        # _current_assembly_bay_id (status-BLIND by design, v4.31 §0.12) still returns the bay. Assert the
        # actual bay-clearing mechanism instead: the chassis has left in_assembly.
        assert db.get(ChassisRecord, rid).status == "awaiting_qa"


def test_move_without_body_attached_422(app_mod, fresh_chassis):
    """On a bay but no body_attached this cycle -> 422 (attach the body first)."""
    from app.database import SessionLocal
    from app.services import chassis as svc
    rid, bay = fresh_chassis(), _bay_ids(1)[0]
    with SessionLocal() as db:
        svc.assign_assembly_bay(db, rid, bay, who="admin")            # in_assembly, but NO body_attached
    with SessionLocal() as db:
        with pytest.raises(HTTPException) as ei:
            svc.record_moved_to_awaiting_qa(db, rid, who="admin")
        assert ei.value.status_code == 422


def test_move_not_on_bay_422(app_mod, fresh_chassis):
    """status != in_assembly (booked-in only) -> 422."""
    from app.database import SessionLocal
    from app.services import chassis as svc
    rid = fresh_chassis()                                             # in_workshop, never assigned
    with SessionLocal() as db:
        with pytest.raises(HTTPException) as ei:
            svc.record_moved_to_awaiting_qa(db, rid, who="admin")
        assert ei.value.status_code == 422


def test_move_idempotent_409(app_mod, on_bay_with_body):
    """A second move is a 409 (already in Awaiting QA) — and is blocked by the status guard too."""
    from app.database import SessionLocal
    from app.services import chassis as svc
    rid, _ = on_bay_with_body()
    with SessionLocal() as db:
        svc.record_moved_to_awaiting_qa(db, rid, who="admin")
    with SessionLocal() as db:
        with pytest.raises(HTTPException) as ei:
            svc.record_moved_to_awaiting_qa(db, rid, who="admin")
        assert ei.value.status_code in (409, 422)                     # already awaiting_qa (status guard fires)


def test_move_deleted_chassis_409(app_mod, on_bay_with_body):
    from app.database import SessionLocal
    from app.models.mes import ChassisRecord
    from app.services import chassis as svc
    rid, _ = on_bay_with_body()
    with SessionLocal() as db:
        db.get(ChassisRecord, rid).deleted_at = datetime.now(timezone.utc)
        db.commit()
    with SessionLocal() as db:
        with pytest.raises(HTTPException) as ei:
            svc.record_moved_to_awaiting_qa(db, rid, who="admin")
        assert ei.value.status_code == 409


def test_move_unknown_chassis_404(app_mod):
    from app.database import SessionLocal
    from app.services import chassis as svc
    with SessionLocal() as db:
        with pytest.raises(HTTPException) as ei:
            svc.record_moved_to_awaiting_qa(db, 99999999, who="admin")
        assert ei.value.status_code == 404


# ── integration + permission tests ──────────────────────────────────────────────
def test_move_endpoint_admin_201(api, on_bay_with_body):
    rid, _ = on_bay_with_body()
    r = api.post(f"/api/chassis-records/{rid}/move-to-awaiting-qa", json={"notes": "QC ready"})
    assert r.status_code == 201
    assert r.json()["event_type"] == "moved_to_awaiting_qa"


def test_awaiting_qa_zone_lists_moved_chassis(api, on_bay_with_body):
    rid, _ = on_bay_with_body()
    api.post(f"/api/chassis-records/{rid}/move-to-awaiting-qa", json={})
    rows = api.get("/api/chassis-records/awaiting-qa").json()
    assert any(row["chassis_id"] == rid for row in rows)


def test_move_permission_gate(api_as, make_user, on_bay_with_body):
    # production has chassis.assembly_assign -> allowed
    rid, _ = on_bay_with_body()
    ok = api_as(make_user("production")).post(f"/api/chassis-records/{rid}/move-to-awaiting-qa", json={})
    assert ok.status_code == 201
    # a plain user has no grant -> 403 (gate runs before the handler body)
    rid2, _ = on_bay_with_body()
    denied = api_as(make_user("user")).post(f"/api/chassis-records/{rid2}/move-to-awaiting-qa", json={})
    assert denied.status_code == 403
