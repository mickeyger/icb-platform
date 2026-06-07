"""Tests for WO v4.29 — upstream stabilisation defect fixes (D1–D6).

Service unit tests call services directly; integration tests inject auth via
dependency_overrides[require_user]=admin (admin is the code-level permission
wildcard). Every factory cleans up its rows so the suite is rerunnable against
the shared local/CI Postgres.
"""
import json
import uuid
from datetime import date, datetime, timezone

import pytest


# ── fixtures ──────────────────────────────────────────────────────────────────
@pytest.fixture(scope="module")
def app_mod():
    import app.main as m
    from starlette.testclient import TestClient
    with TestClient(m.app) as _c:        # triggers startup -> seeds admin user
        yield m


@pytest.fixture
def user():
    from app.database import SessionLocal, User
    with SessionLocal() as db:
        return db.query(User).filter_by(username="admin").first()


@pytest.fixture
def api(app_mod, user):
    from app.deps import require_user
    from starlette.testclient import TestClient
    app_mod.app.dependency_overrides[require_user] = lambda: user
    with TestClient(app_mod.app) as c:
        yield c
    app_mod.app.dependency_overrides.pop(require_user, None)


@pytest.fixture
def jhb_id():
    from app.database import SessionLocal, Branch
    with SessionLocal() as db:
        return db.query(Branch).filter_by(code="JHB").first().id


@pytest.fixture
def fresh_calc(app_mod):
    """Factory -> calculation_id. `branch='none'` makes a NULL-branch calc (the D1 repro)."""
    from app.database import SessionLocal, CalculationRecord, Branch
    from app.models.mes import ProductionJob
    created = []

    def _make(branch="JHB", status="accepted"):
        with SessionLocal() as db:
            bid = None
            if branch != "none":
                bid = db.query(Branch).filter_by(code=branch).first().id
            c = CalculationRecord(
                quote_number=f"A-T{uuid.uuid4().hex[:8]}", status=status, branch_id=bid,
                dimensions_json=json.dumps({"body_type": "Test Body"}),
                result_json=json.dumps({"selling_zar": 1000.0}))
            db.add(c)
            db.commit()
            db.refresh(c)
            created.append(c.id)
            return c.id

    yield _make
    with SessionLocal() as db:
        for cid in created:
            for pj in db.query(ProductionJob).filter_by(calculation_record_id=cid).all():
                db.delete(pj)
            c = db.get(CalculationRecord, cid)
            if c:
                db.delete(c)
        db.commit()


@pytest.fixture
def fresh_job(app_mod, jhb_id):
    """Factory -> production_job id at a chosen status, optionally linked to a chassis_record with a
    VCL/DCL event (for the D3 read-bridge). Cleans up slots, events, chassis, job, calc."""
    from app.database import SessionLocal, CalculationRecord
    from app.models.mes import (ChassisLifecycleEvent, ChassisRecord, PlanningSlot, ProductionJob)
    pjs, calcs, chassis = [], [], []

    def _make(status="planning", chassis_eta=None, chassis_received_at=None, vcl_date=None,
              dcl_only=False):
        with SessionLocal() as db:
            jn = f"V{uuid.uuid4().hex[:8]}"
            c = CalculationRecord(quote_number=f"A-{jn}", status="accepted", branch_id=jhb_id,
                                  dimensions_json=json.dumps({"body_type": "Test"}),
                                  result_json=json.dumps({"selling_zar": 1000.0}))
            db.add(c); db.commit(); db.refresh(c); calcs.append(c.id)
            cr_id = None
            if vcl_date is not None or dcl_only:
                cr = ChassisRecord(vin=f"TVIN{uuid.uuid4().hex[:13].upper()}", job_number=jn,
                                   status="in_workshop", source="test")
                db.add(cr); db.commit(); db.refresh(cr); chassis.append(cr.id); cr_id = cr.id
                ev_type = "DCL" if dcl_only else "VCL"
                db.add(ChassisLifecycleEvent(chassis_record_id=cr.id, cycle_number=1,
                                             event_type=ev_type, event_date=(vcl_date or date(2026, 5, 1))))
                db.commit()
            pj = ProductionJob(calculation_record_id=c.id, branch_id=jhb_id, job_number=jn,
                               status=status, chassis_eta=chassis_eta,
                               chassis_received_at=chassis_received_at, chassis_record_id=cr_id)
            db.add(pj); db.commit(); db.refresh(pj); pjs.append(pj.id)
            return pj.id

    yield _make
    with SessionLocal() as db:
        for pid in pjs:
            for s in db.query(PlanningSlot).filter_by(production_job_id=pid).all():
                db.delete(s)
            pj = db.get(ProductionJob, pid)
            if pj:
                db.delete(pj)
        db.commit()                    # drop jobs (FK -> chassis is ON DELETE RESTRICT) first
        for crid in chassis:
            for e in db.query(ChassisLifecycleEvent).filter_by(chassis_record_id=crid).all():
                db.delete(e)
            cr = db.get(ChassisRecord, crid)
            if cr:
                db.delete(cr)
        for cid in calcs:
            c = db.get(CalculationRecord, cid)
            if c:
                db.delete(c)
        db.commit()


# ── D1: accept with a NULL-branch calc no longer 500s ──────────────────────────
def test_d1_accept_null_branch_defaults_to_jhb(fresh_calc, user, jhb_id):
    from app.database import SessionLocal
    from app.services import production_jobs as svc
    cid = fresh_calc(branch="none")                       # the A-series null-branch repro
    with SessionLocal() as db:
        (job, *_), created = svc.accept_calculation(db, cid, user)
        assert created is True
        assert job.branch_id == jhb_id                    # defaulted, not NULL (was IntegrityError)


def test_d1_fallback_branch_preferred_over_default(fresh_calc, user):
    from app.database import SessionLocal, Branch
    from app.services import production_jobs as svc
    with SessionLocal() as db:
        cpt = db.query(Branch).filter_by(code="CPT").first().id
    cid = fresh_calc(branch="none")
    with SessionLocal() as db:
        (job, *_), _ = svc.accept_calculation(db, cid, user, fallback_branch_id=cpt)
        assert job.branch_id == cpt                        # active branch wins over the JHB default


def test_d1_retry_from_calculation_201(api, fresh_calc):
    cid = fresh_calc(branch="none")
    r = api.post(f"/api/production-jobs/from-calculation/{cid}")
    assert r.status_code == 201                            # was 500 (NotNullViolation on branch_id)
    assert r.json()["branch_code"] == "JHB"


# ── D2: planning-ack captures ETA + rich chassis data (no legacy deadlock) ─────
def test_d2_planning_ack_captures_eta_and_rich_data(fresh_job, user):
    from app.database import SessionLocal
    from app.services import production_jobs as svc
    jid = fresh_job(status="pre_job_confirmed")
    with SessionLocal() as db:
        (job, *_) = svc.record_planning_ack(
            db, jid, date(2026, 6, 26), "ack note", user,
            chassis_data={"chassis_model": "HINO-500", "customer_dealer": "Verify Dealer",
                          "chassis_vin": None})
        assert job.status == "planning"
        assert job.chassis_eta is not None
        data = json.loads(job.chassis_data_json)
        assert data["chassis_model"] == "HINO-500" and data["customer_dealer"] == "Verify Dealer"
        assert "chassis_vin" not in data                   # None values are not persisted


def test_d2_planning_ack_via_api(api, fresh_job):
    jid = fresh_job(status="pre_job_confirmed")
    r = api.post(f"/api/production-jobs/{jid}/planning-ack",
                 json={"chassis_eta": "2026-06-26", "chassis_model": "ISUZU-FTR"})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "planning"
    assert body["chassis_data"]["chassis_model"] == "ISUZU-FTR"


# ── D3: read-bridge surfaces the latest VCL event as the chassis-received signal ─
def test_d3_signal_prefers_vcl_then_legacy(fresh_job):
    from app.database import SessionLocal
    from app.services import planning as pl
    vcl_job = fresh_job(status="planning", vcl_date=date(2026, 6, 7))
    legacy_job = fresh_job(status="planning",
                           chassis_received_at=datetime(2026, 5, 14, tzinfo=timezone.utc))
    none_job = fresh_job(status="planning")
    with SessionLocal() as db:
        pool = {j.id: j for j in pl._unscheduled_pool(db)}
        assert pool[vcl_job].chassis_received_source == "vcl"
        assert pool[vcl_job].chassis_received_signal.date() == date(2026, 6, 7)
        assert pool[legacy_job].chassis_received_source == "legacy"
        assert pool[none_job].chassis_received_source is None


def test_d3_dcl_only_is_not_received(fresh_job):
    """A DCL (dispatch) event is not a chassis-received signal — only VCL (book-in) is."""
    from app.database import SessionLocal
    from app.services import planning as pl
    dcl_job = fresh_job(status="planning", dcl_only=True)
    with SessionLocal() as db:
        pool = {j.id: j for j in pl._unscheduled_pool(db)}
        assert pool[dcl_job].chassis_received_source is None


# ── D4: revised chassis-ETA gate (block-no-info + retained within-week guard) ───
@pytest.mark.parametrize("received,eta,target,blocked", [
    (False, None,                                  date(2026, 6, 1),  True),   # no info -> BLOCK (fix)
    (True,  None,                                  date(2026, 6, 1),  False),  # received -> allow
    (False, datetime(2026, 6, 3, tzinfo=timezone.utc),  date(2026, 6, 1),  False),  # ETA within week
    (False, datetime(2026, 12, 1, tzinfo=timezone.utc), date(2026, 6, 1),  True),   # ETA after week (kept)
    (True,  datetime(2026, 12, 1, tzinfo=timezone.utc), date(2026, 6, 1),  False),  # received bypasses
])
def test_d4_gate_quadrant_matrix(received, eta, target, blocked):
    from app.services import planning as pl
    from types import SimpleNamespace
    reason = pl.eta_gate_reason(SimpleNamespace(chassis_eta=eta), target, received=received)
    assert (reason is not None) == blocked


def test_d4_schedule_blocks_no_info_allows_received(api, fresh_job):
    tag = uuid.uuid4().hex[:6]                                               # unique bays -> rerun-safe
    no_info = fresh_job(status="planning")                                   # no ETA, not received
    r1 = api.post("/api/planning-slots",
                  json={"production_job_id": no_info, "week": "2026-09-07", "bay": f"QA-{tag}a"})
    assert r1.status_code == 422                                             # blocked (v4.29 fix)
    received = fresh_job(status="planning", vcl_date=date(2026, 6, 1))       # VCL -> received
    r2 = api.post("/api/planning-slots",
                  json={"production_job_id": received, "week": "2026-09-07", "bay": f"QA-{tag}b"})
    assert r2.status_code == 201                                             # allowed via D3 signal


# ── D5: natural-numeric bay sort ───────────────────────────────────────────────
def test_d5_bay_natural_sort_key():
    from app.services import planning as pl
    assert sorted(["Bay-10", "Bay-2", "Bay-1", "V-5", "V-12", "P-3"], key=pl._bay_sort_key) == \
        ["Bay-1", "Bay-2", "Bay-10", "P-3", "V-5", "V-12"]


def test_d5_board_lanes_numeric_order(api):
    lanes = api.get("/api/planning-board").json()["lanes"]
    nums = [int(b.split("-")[1]) for b in lanes if b.startswith("Bay-")]
    assert nums == sorted(nums)                                              # ascending numeric, not "Bay-10" < "Bay-2"


# ── D6: contiguous week header (no dropped empty weeks) ────────────────────────
def test_d6_weeks_contiguous(api):
    weeks = [date.fromisoformat(w["start"]) for w in api.get("/api/planning-board?weeks=8").json()["weeks"]]
    assert len(weeks) == 8
    assert all((weeks[i + 1] - weeks[i]).days == 7 for i in range(len(weeks) - 1))   # no gaps (W17/W18 fix)
