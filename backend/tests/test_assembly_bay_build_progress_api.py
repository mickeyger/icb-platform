"""WO v1.39.2 — Pre-Assembly build-progress (advance-stage) service + API tests.

The build model: a body builds inside an assembly bay while the bay holds a job's loose panels
(state 'pre_assembly'). It starts at ENTRY/0 on arrival and is walked forward-only through
ENTRY→PRE_ASSEMBLY→STAGE_2→STAGE_3→MERGE, progress derived from the stage (0/33/62/85/100).
Clearing the panels (move-back) resets the build to NULL/0.

Service unit tests call services.chassis directly; integration tests inject auth via
dependency_overrides[require_user] and assert the chassis.assembly_assign gate (granted to
production/planner in migration 0016). Fresh jobs use the 'PABP' job_number prefix so the suite is
rerunnable (purged either side). Mirrors the fixture style of test_chassis_assembly_assign_api.py.
"""
import uuid

import pytest
from fastapi import HTTPException

STAGE_PROGRESSION = [("pre_assembly", 33), ("stage_2", 62), ("stage_3", 85), ("merge", 100)]


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


def _purge(db):
    from sqlalchemy import text
    db.execute(text("DELETE FROM icb_mes.production_job_bay_events e USING icb_mes.production_jobs j "
                    "WHERE e.production_job_id = j.id AND j.job_number LIKE 'PABP%'"))
    db.execute(text("DELETE FROM icb_mes.production_jobs WHERE job_number LIKE 'PABP%'"))
    db.commit()


@pytest.fixture
def bay_with_body():
    """A free assembly bay holding a fresh job's panels → state pre_assembly, build_stage=entry, pct=0.
    Yields (bay_id, job_id). Function-scoped; PABP jobs purged + the bay build reset on teardown."""
    from app.database import Branch, CalculationRecord, SessionLocal
    from app.models.mes import AssemblyBay, ProductionJob, ProductionJobBayEvent
    from app.services import chassis as svc
    from app.services.chassis import current_occupants
    with SessionLocal() as db:
        _purge(db)
        taken = {j.calculation_record_id for j in db.query(ProductionJob)
                 .filter(ProductionJob.calculation_record_id.isnot(None)).all()}
        calc = (db.query(CalculationRecord).filter(~CalculationRecord.id.in_(taken or {0}))
                .order_by(CalculationRecord.id.desc()).first())
        if calc is None:
            pytest.skip("no job-free calculation on this DB")
        branch = db.query(Branch).order_by(Branch.id).first()
        occupied = set(current_occupants(db))
        busy_panels = {e.bay_id for e in db.query(ProductionJobBayEvent)
                       .filter_by(event_type="panels_arrived_in_bay").all()}
        bay = next((b for b in db.query(AssemblyBay).filter_by(is_active=True)
                    .order_by(AssemblyBay.sort_order).all()
                    if b.id not in occupied and b.id not in busy_panels), None)
        if bay is None:
            pytest.skip("no free assembly bay on this DB")
        job = ProductionJob(calculation_record_id=calc.id, branch_id=branch.id, source="quote",
                            status="planning", job_number="PABP01")
        db.add(job)
        db.commit()
        jid, bid = job.id, bay.id
    with SessionLocal() as db:
        svc.record_panels_arrived_in_bay(db, jid, bid)   # → pre_assembly, entry/0
    yield bid, jid
    with SessionLocal() as db:
        _purge(db)
        b = db.get(AssemblyBay, bid)
        if b is not None:
            b.build_stage = None
            b.build_progress_pct = 0
        db.commit()


# ── service unit tests ──────────────────────────────────────────────────────
def test_panels_arrival_starts_at_entry(app_mod, bay_with_body):
    from app.database import SessionLocal
    from app.models.mes import AssemblyBay
    bid, _ = bay_with_body
    with SessionLocal() as db:
        bay = db.get(AssemblyBay, bid)
        assert bay.build_stage == "entry" and bay.build_progress_pct == 0


def test_advance_forward_progression_progress_derived(app_mod, bay_with_body):
    """R6/R7 — forward advance walks the stages; progress is a pure function of the stage."""
    from app.database import SessionLocal
    from app.services import chassis as svc
    bid, _ = bay_with_body
    for stage, pct in STAGE_PROGRESSION:
        with SessionLocal() as db:
            bay = svc.advance_build_stage(db, bid, stage)
            assert bay.build_stage == stage and bay.build_progress_pct == pct


def test_advance_reject_backward_409(app_mod, bay_with_body):
    """R6 — a build is forward-only: a lower stage is refused (409) and leaves the stage unchanged."""
    from app.database import SessionLocal
    from app.models.mes import AssemblyBay
    from app.services import chassis as svc
    bid, _ = bay_with_body
    with SessionLocal() as db:
        svc.advance_build_stage(db, bid, "stage_2")
    with SessionLocal() as db:
        with pytest.raises(HTTPException) as ei:
            svc.advance_build_stage(db, bid, "entry")
        assert ei.value.status_code == 409
        assert db.get(AssemblyBay, bid).build_stage == "stage_2"   # untouched


def test_advance_same_stage_idempotent(app_mod, bay_with_body):
    """Re-advancing to the CURRENT stage is allowed (>=), a no-op — the drag can land on itself."""
    from app.database import SessionLocal
    from app.services import chassis as svc
    bid, _ = bay_with_body
    with SessionLocal() as db:
        svc.advance_build_stage(db, bid, "stage_2")
    with SessionLocal() as db:
        bay = svc.advance_build_stage(db, bid, "stage_2")
        assert bay.build_stage == "stage_2" and bay.build_progress_pct == 62


def test_advance_unknown_stage_422(app_mod, bay_with_body):
    from app.database import SessionLocal
    from app.services import chassis as svc
    bid, _ = bay_with_body
    with SessionLocal() as db:
        with pytest.raises(HTTPException) as ei:
            svc.advance_build_stage(db, bid, "bogus")
        assert ei.value.status_code == 422


def test_clear_resets_build_then_advance_409(app_mod, bay_with_body):
    """Move-panels-back resets the build to NULL/0; with no body left, advancing is 409 (no body)."""
    from app.database import SessionLocal
    from app.models.mes import AssemblyBay
    from app.services import chassis as svc
    bid, jid = bay_with_body
    with SessionLocal() as db:
        svc.advance_build_stage(db, bid, "stage_2")     # move it off entry first
    with SessionLocal() as db:
        svc.clear_panels_arrived(db, jid)               # panels gone → bay empty
    with SessionLocal() as db:
        bay = db.get(AssemblyBay, bid)
        assert bay.build_stage is None and bay.build_progress_pct == 0   # reset-on-clear
        with pytest.raises(HTTPException) as ei:
            svc.advance_build_stage(db, bid, "pre_assembly")
        assert ei.value.status_code == 409              # no body building


def test_advance_unknown_bay_404(app_mod):
    from app.database import SessionLocal
    from app.services import chassis as svc
    with SessionLocal() as db:
        with pytest.raises(HTTPException) as ei:
            svc.advance_build_stage(db, 99999999, "pre_assembly")
        assert ei.value.status_code == 404


# ── integration + permission tests ──────────────────────────────────────────
def test_bayout_surfaces_build_fields_and_endpoint_advances(api, bay_with_body):
    bid, _ = bay_with_body
    rows = api.get("/api/chassis-records/bays/assembly").json()
    row = next(r for r in rows if r["id"] == bid)
    assert row["build_stage"] == "entry" and row["build_progress_pct"] == 0
    r = api.post(f"/api/chassis-records/bays/{bid}/advance-stage", json={"stage": "stage_2"})
    assert r.status_code == 200
    assert r.json()["build_stage"] == "stage_2" and r.json()["build_progress_pct"] == 62


def test_advance_permission_gate(api_as, make_user, bay_with_body):
    bid, _ = bay_with_body
    # production holds chassis.assembly_assign (granted 0016) -> allowed
    ok = api_as(make_user("production")).post(
        f"/api/chassis-records/bays/{bid}/advance-stage", json={"stage": "pre_assembly"})
    assert ok.status_code == 200
    # a plain user has no grant -> 403 (gate runs before the handler body)
    denied = api_as(make_user("user")).post(
        f"/api/chassis-records/bays/{bid}/advance-stage", json={"stage": "stage_2"})
    assert denied.status_code == 403
