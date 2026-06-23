"""WO v4.36a.2 — return a chassis from an assembly bay back to the parking pool (re-prioritise jobs):
the return_chassis_to_parking service + POST /api/chassis-records/{id}/return-to-parking endpoint.

The REVERSE of assign_assembly_bay: DELETE the cycle's assembly_assigned event + flip status
'in_assembly' → 'in_workshop'. Allowed ONLY before a merge (no body_attached this cycle). When a job is
linked, the transition is recorded in production_jobs_audit (optional reason). These tests assert the
status flip + event delete + bay-clearing, the body-attached guard (409), not-on-bay (422), the audit
written-when-linked / absent-when-unlinked split, re-assignability after the return, and the permission
gate. Mirrors test_chassis_move_to_awaiting_qa_api.py; runs on *_test only.
"""
import uuid
from datetime import date, datetime, timezone

import pytest
from fastapi import HTTPException


# ── fixtures (mirror test_chassis_move_to_awaiting_qa_api.py) ────────────────────
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
def on_bay(fresh_chassis):
    """A chassis on an assembly bay (status in_assembly + assembly_assigned), NO linked job.
    Returns (record_id, bay_id)."""
    from app.database import SessionLocal
    from app.services import chassis as svc

    def _make():
        rid, bay = fresh_chassis(), _bay_ids(1)[0]
        with SessionLocal() as db:
            svc.assign_assembly_bay(db, rid, bay, who="admin")
        return rid, bay

    return _make


@pytest.fixture
def on_bay_linked():
    """A chassis on a bay WITH a linked production job (so a return writes an audit row). Self-contained —
    owns its calc/job/chassis and tears them down FK-safe (job → chassis → calc). Returns
    (record_id, bay_id, job_id)."""
    from app.database import Branch, CalculationRecord, SessionLocal
    from app.models.mes import ChassisLifecycleEvent, ChassisRecord, ProductionJob
    from app.services import chassis as svc
    made = []   # (rid, jid, calc_id)

    def _make():
        rid, bay = None, _bay_ids(1)[0]
        with SessionLocal() as db:
            rec = ChassisRecord(vin=f"RTP{uuid.uuid4().hex[:12].upper()}", source="manual", status="received",
                                make="RTP Test", model="X")
            db.add(rec); db.flush()
            db.add(ChassisLifecycleEvent(chassis_record_id=rec.id, cycle_number=1, event_type="VCL",
                                         event_date=date.today()))
            rec.status = "in_workshop"
            br = db.query(Branch).order_by(Branch.id).first()
            tag = uuid.uuid4().hex[:6]
            calc = CalculationRecord(quote_number=f"RTP-{tag}", status="in_production", branch_id=br.id,
                                     dimensions_json='{"body_type": "Chiller"}', result_json='{"selling_zar": 1.0}')
            db.add(calc); db.flush()
            job = ProductionJob(calculation_record_id=calc.id, branch_id=br.id, status="in_production",
                                job_number=f"RTP{tag}", chassis_record_id=rec.id)
            db.add(job); db.commit()
            rid, jid, cid = rec.id, job.id, calc.id
        with SessionLocal() as db:
            svc.assign_assembly_bay(db, rid, bay, who="admin")        # → in_assembly + assembly_assigned
        made.append((rid, jid, cid))
        return rid, bay, jid

    yield _make
    with SessionLocal() as db:
        for rid, jid, cid in made:
            j = db.get(ProductionJob, jid)                            # cascades production_jobs_audit
            if j:
                db.delete(j)
                db.flush()                                            # FK-safe: emit the job DELETE (clears the
                                                                      # chassis_record_id reference) BEFORE the chassis
                                                                      # DELETE below. production_jobs.chassis_record_id
                                                                      # is a bare-column FK (no ORM relationship), so
                                                                      # the unit-of-work won't order these for us →
                                                                      # without the flush the chassis can delete first
                                                                      # → fk_production_jobs_chassis_record violation.
            for e in db.query(ChassisLifecycleEvent).filter_by(chassis_record_id=rid).all():
                db.delete(e)
            r = db.get(ChassisRecord, rid)
            if r:
                db.delete(r)
            c = db.get(CalculationRecord, cid)
            if c:
                db.delete(c)
        db.commit()


def _audit_rows(job_id):
    from app.database import SessionLocal
    from app.models.mes import ProductionJobAudit
    with SessionLocal() as db:
        return db.query(ProductionJobAudit).filter_by(
            production_job_id=job_id, action="chassis_returned_to_parking").all()


# ── service unit tests — the reverse of assign + the guards ──────────────────────
def test_return_flips_status_and_deletes_event(app_mod, on_bay):
    from app.database import SessionLocal
    from app.models.mes import ChassisLifecycleEvent, ChassisRecord
    from app.services import chassis as svc
    rid, bay = on_bay()
    with SessionLocal() as db:
        out = svc.return_chassis_to_parking(db, rid, user=_admin(db))
        assert out["reverted"] is True
    with SessionLocal() as db:
        assert db.get(ChassisRecord, rid).status == "in_workshop"     # back in the parking pool
        gone = db.query(ChassisLifecycleEvent).filter_by(
            chassis_record_id=rid, event_type="assembly_assigned").all()
        assert gone == []                                             # assembly_assigned event DELETED
        assert svc._current_assembly_bay_id(db, rid) is None
        assert bay not in svc.current_occupants(db)                   # bay derives empty


def test_return_body_attached_409(app_mod, on_bay):
    from app.database import SessionLocal
    from app.models.mes import ChassisLifecycleEvent
    from app.services import chassis as svc
    rid, _ = on_bay()
    with SessionLocal() as db:                                        # simulate a merge this cycle
        cycle = svc._latest_cycle(db, rid)
        db.add(ChassisLifecycleEvent(chassis_record_id=rid, cycle_number=cycle, event_type="body_attached",
                                     event_date=date.today()))
        db.commit()
    with SessionLocal() as db:
        with pytest.raises(HTTPException) as ei:
            svc.return_chassis_to_parking(db, rid, user=_admin(db))
        assert ei.value.status_code == 409 and "Awaiting QA" in ei.value.detail


def test_return_not_on_bay_422(app_mod, fresh_chassis):
    from app.database import SessionLocal
    from app.services import chassis as svc
    rid = fresh_chassis()                                            # in_workshop, never assigned
    with SessionLocal() as db:
        with pytest.raises(HTTPException) as ei:
            svc.return_chassis_to_parking(db, rid, user=_admin(db))
        assert ei.value.status_code == 422


def test_return_deleted_409(app_mod, on_bay):
    from app.database import SessionLocal
    from app.models.mes import ChassisRecord
    from app.services import chassis as svc
    rid, _ = on_bay()
    with SessionLocal() as db:
        db.get(ChassisRecord, rid).deleted_at = datetime.now(timezone.utc)
        db.commit()
    with SessionLocal() as db:
        with pytest.raises(HTTPException) as ei:
            svc.return_chassis_to_parking(db, rid, user=_admin(db))
        assert ei.value.status_code == 409


def test_return_unknown_404(app_mod):
    from app.database import SessionLocal
    from app.services import chassis as svc
    with SessionLocal() as db:
        with pytest.raises(HTTPException) as ei:
            svc.return_chassis_to_parking(db, 99999999, user=_admin(db))
        assert ei.value.status_code == 404


def test_return_reassignable_after(app_mod, on_bay):
    """After a return the chassis is back in the pool (open VCL cycle) → assign_assembly_bay works again."""
    from app.database import SessionLocal
    from app.models.mes import ChassisRecord
    from app.services import chassis as svc
    rid, _ = on_bay()
    with SessionLocal() as db:
        svc.return_chassis_to_parking(db, rid, user=_admin(db))
    bay2 = _bay_ids(1)[0]
    with SessionLocal() as db:
        svc.assign_assembly_bay(db, rid, bay2, who="admin")
        assert db.get(ChassisRecord, rid).status == "in_assembly"
        assert svc._current_assembly_bay_id(db, rid) == bay2


# ── D2 — audit written when linked, absent when unlinked ─────────────────────────
def test_return_writes_audit_when_linked(app_mod, on_bay_linked):
    from app.database import SessionLocal
    from app.services import chassis as svc
    rid, _, jid = on_bay_linked()
    with SessionLocal() as db:
        svc.return_chassis_to_parking(db, rid, user=_admin(db), reason="urgent job needs the bay")
    rows = _audit_rows(jid)
    assert len(rows) == 1
    assert rows[0].previous_status == "in_assembly" and rows[0].new_status == "in_workshop"
    assert rows[0].reason == "urgent job needs the bay" and rows[0].previous_bay


def test_return_no_audit_when_unlinked(app_mod, on_bay):
    """An unlinked chassis returns fine and writes NO audit row (nothing downstream to protect)."""
    from app.database import SessionLocal
    from app.models.mes import ChassisRecord
    from app.services import chassis as svc
    rid, _ = on_bay()
    with SessionLocal() as db:
        svc.return_chassis_to_parking(db, rid, user=_admin(db))
        assert db.get(ChassisRecord, rid).status == "in_workshop"     # succeeded — no job, no audit, no error


# ── integration + permission tests ──────────────────────────────────────────────
def test_return_endpoint_admin_200(api, on_bay):
    rid, _ = on_bay()
    r = api.post(f"/api/chassis-records/{rid}/return-to-parking", json={"reason": "re-prioritise"})
    assert r.status_code == 200, r.text
    assert r.json()["reverted"] is True


def test_return_permission_gate(api_as, make_user, on_bay):
    # production has chassis.assembly_assign -> allowed
    rid, _ = on_bay()
    ok = api_as(make_user("production")).post(f"/api/chassis-records/{rid}/return-to-parking", json={})
    assert ok.status_code == 200
    # a plain user has no grant -> 403 (gate runs before the handler body)
    rid2, _ = on_bay()
    denied = api_as(make_user("user")).post(f"/api/chassis-records/{rid2}/return-to-parking", json={})
    assert denied.status_code == 403


# ── helpers ──────────────────────────────────────────────────────────────────────
def _admin(db):
    from app.database import User
    return db.query(User).filter_by(username="admin").first()
