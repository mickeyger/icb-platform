"""WO v4.32 §3.1/§3.4 — GET /api/production-jobs/kpis + /in-progress.

Style mirrors test_dashboard_kpis_api (v4.31): the suite RE-DERIVES every metric from the
underlying tables with the same §0.6 formulas and asserts equality against the endpoint —
deterministic fixture rows guarantee each §0.6 branch (start-slipped / chassis-slipped /
bottleneck / completed-today) is non-empty, and the re-derivation absorbs whatever else the
dev DB holds. Also pins the ROUTE-ORDER regression: /kpis and /in-progress are literal paths
declared before the /{job_id} int catch-all (a regression turns them into 422s).
Self-cleaning fixtures (v4.27 standing rule).
"""
from datetime import datetime, timedelta, timezone

import pytest


def _now():
    return datetime.now(timezone.utc)


def _purge_markers(db):
    """Delete every T432* marker row (FK-safe order). Runs at fixture setup AND teardown so a
    mid-test crash can never leak rows into the next run (self-healing, v4.27 standing rule)."""
    from sqlalchemy import text
    db.execute(text("DELETE FROM icb_mes.chassis_lifecycle_events WHERE chassis_record_id IN "
                    "(SELECT id FROM icb_mes.chassis_records WHERE vin LIKE 'T432%')"))
    db.execute(text("DELETE FROM icb_mes.planning_slots WHERE bay IN ('V-77','P-77')"))
    db.execute(text("DELETE FROM icb_mes.production_jobs WHERE job_number LIKE 'T432%'"))
    db.execute(text("DELETE FROM icb_mes.chassis_records WHERE vin LIKE 'T432%'"))
    db.commit()


@pytest.fixture(scope="module")
def app_mod():
    import app.main as m
    from starlette.testclient import TestClient
    with TestClient(m.app):
        yield m


@pytest.fixture
def api(app_mod):
    from app.database import SessionLocal, User
    from app.deps import require_user
    from starlette.testclient import TestClient
    with SessionLocal() as db:
        admin = db.query(User).filter_by(username="admin").first()
    app_mod.app.dependency_overrides[require_user] = lambda: admin
    with TestClient(app_mod.app) as c:
        yield c
    app_mod.app.dependency_overrides.pop(require_user, None)


@pytest.fixture
def seeded(app_mod):
    """Deterministic §0.6 fixture rows: one start-slipped 'planning' job (3 days into its
    stage → a bottleneck candidate), one chassis-slipped job (ETA yesterday, no chassis),
    one job completed today, and one in_production job whose chassis sits on an assembly bay
    (for /in-progress chassis/bay context). All branch = first seeded branch; all cleaned up."""
    from app.database import Branch, SessionLocal
    from app.models.mes import (
        AssemblyBay, ChassisLifecycleEvent, ChassisRecord, ProductionJob,
    )
    now = _now()
    created = {"jobs": [], "chassis": [], "events": []}
    with SessionLocal() as db:
        _purge_markers(db)                      # self-heal any leak from a crashed prior run
        branch = db.query(Branch).order_by(Branch.id).first()
        assert branch is not None, "icb_costings.branches must be seeded"
        branch_id = branch.id                   # primitive — branch detaches when the session closes
        bay = (db.query(AssemblyBay).filter_by(is_active=True)
               .order_by(AssemblyBay.sort_order).first())
        if bay is None:
            pytest.skip("assembly_bays not seeded (migration 0016) on this DB")

        j_start = ProductionJob(branch_id=branch.id, source="workbook", status="planning",
                                job_number="T432K1", customer_name="KPI START-SLIP",
                                accepted_at=now - timedelta(days=10),
                                planned_start_date=now - timedelta(days=3))
        j_eta = ProductionJob(branch_id=branch.id, source="workbook", status="planning",
                              job_number="T432K2", customer_name="KPI CHASSIS-SLIP",
                              accepted_at=now - timedelta(days=1),
                              chassis_eta=now - timedelta(days=1))
        j_done = ProductionJob(branch_id=branch.id, source="workbook", status="completed",
                               job_number="T432K3", customer_name="KPI DONE-TODAY",
                               accepted_at=now - timedelta(days=5), completed_at=now)
        rec = ChassisRecord(vin="T432KPIVIN", source="manual", status="in_assembly",
                            customer_name="KPI BAY OCCUPANT")
        db.add_all([j_start, j_eta, j_done, rec])
        db.flush()
        j_bay = ProductionJob(branch_id=branch.id, source="workbook", status="in_production",
                              job_number="T432K4", customer_name="KPI ON-BAY",
                              accepted_at=now - timedelta(days=1),
                              chassis_record_id=rec.id)
        ev_vcl = ChassisLifecycleEvent(chassis_record_id=rec.id, cycle_number=1,
                                       event_type="VCL", event_date=now.date(), created_by="t")
        ev_aa = ChassisLifecycleEvent(chassis_record_id=rec.id, cycle_number=1,
                                      event_type="assembly_assigned", assembly_bay_id=bay.id,
                                      event_date=now.date(), created_by="t")
        db.add_all([j_bay, ev_vcl, ev_aa])
        db.commit()
        created["jobs"] = [j_start.id, j_eta.id, j_done.id, j_bay.id]
        created["chassis"] = [rec.id]
        created["events"] = [ev_vcl.id, ev_aa.id]
        bay_code = bay.code                     # primitive — bay detaches when the session closes
    try:
        yield {"branch_id": branch_id, "bay_code": bay_code, **created}
    finally:
        with SessionLocal() as db:
            _purge_markers(db)


def test_route_order_kpis_and_in_progress_are_not_job_ids(api):
    """Literal paths must be matched BEFORE /{job_id} — a 422 here means route order broke."""
    assert api.get("/api/production-jobs/kpis").status_code == 200
    assert api.get("/api/production-jobs/in-progress").status_code == 200


def test_kpis_match_manual_rederivation(api, seeded):
    from app.database import SessionLocal
    from app.models.mes import ChassisRecord, ProductionJob, ReworkTicket
    from app.services.production_jobs import IN_FLIGHT_STATUSES

    body = api.get("/api/production-jobs/kpis").json()
    as_of = datetime.fromisoformat(body["as_of"])
    today = as_of.date()

    def aware(dt):
        return dt if (dt is None or dt.tzinfo) else dt.replace(tzinfo=timezone.utc)

    with SessionLocal() as db:
        jobs = (db.query(ProductionJob)
                .filter(ProductionJob.status.in_(IN_FLIGHT_STATUSES)).all())
        ch_status = {c.id: c.status for c in db.query(ChassisRecord).filter(
            ChassisRecord.id.in_([j.chassis_record_id for j in jobs if j.chassis_record_id] or [0])
        ).all()}

        start_slipped, chassis_slipped, stage_days = set(), set(), {}
        for j in jobs:
            psd = aware(j.planned_start_date)
            if j.status == "planning" and psd is not None and psd.date() < today:
                start_slipped.add(j.id)
            eta = aware(j.chassis_eta)
            received = (j.chassis_received_at is not None
                        or ch_status.get(j.chassis_record_id) in
                        ("in_workshop", "in_assembly", "dispatched"))
            if eta is not None and eta.date() < today and not received:
                chassis_slipped.add(j.id)
            cands = [aware(t) for t in (j.accepted_at, j.pre_job_sent_at, j.pre_job_confirmed_at,
                                        j.planning_acknowledged_at, j.chassis_received_at,
                                        j.planned_start_date) if t is not None]
            entered = max(cands) if cands else aware(j.created_at)
            if entered is not None:
                stage_days[j.id] = (as_of - entered).days

        day_start = datetime(today.year, today.month, today.day, tzinfo=timezone.utc)
        exp_completed = (db.query(ProductionJob)
                         .filter(ProductionJob.completed_at >= day_start).count())
        exp_rework = db.query(ReworkTicket).filter_by(status="open").count()

    assert body["units_in_production"] == len(jobs)
    assert body["delayed"]["start_slipped"] == len(start_slipped)
    assert body["delayed"]["chassis_slipped"] == len(chassis_slipped)
    assert body["delayed"]["total"] == len(start_slipped | chassis_slipped)
    assert body["critical_chassis"] == len(chassis_slipped)
    assert body["completed_today"] == exp_completed
    assert body["open_rework"] == exp_rework
    assert body["target_today"] is None                      # §0.6 no-target-line branch
    # fixture guarantees the >2d branch is non-empty; argmax must match the re-derivation
    stuck = {jid: d for jid, d in stage_days.items() if d > 2}
    assert stuck, "fixture should force a bottleneck candidate"
    assert body["bottleneck"] is not None
    max_days = max(stuck.values())
    assert body["bottleneck"]["days_in_stage"] == max_days
    assert body["bottleneck"]["job_id"] in {j for j, d in stuck.items() if d == max_days}
    # the deterministic fixture rows registered in the right §0.6 buckets
    assert seeded["jobs"][0] in start_slipped
    assert seeded["jobs"][1] in chassis_slipped


def test_in_progress_carries_chassis_and_bay_context(api, seeded):
    rows = api.get("/api/production-jobs/in-progress").json()
    by_num = {r["job_number"]: r for r in rows}
    on_bay = by_num.get("T432K4")
    assert on_bay is not None
    assert on_bay["chassis_vin"] == "T432KPIVIN"
    assert on_bay["chassis_status"] == "in_assembly"
    assert on_bay["current_assembly_bay_code"] == seeded["bay_code"]
    assert on_bay["days_in_stage"] is not None
    # a chassis-less in-flight job carries None context (modal-grade missing-data handling)
    no_ch = by_num.get("T432K1")
    assert no_ch is not None
    assert no_ch["chassis_vin"] is None and no_ch["current_assembly_bay_code"] is None
    # completed jobs are NOT in-flight (§0.6)
    assert "T432K3" not in by_num


def test_kpis_branch_filter(api, seeded):
    """branch_id filters the branch-attributable metrics (§0.7)."""
    all_kpis = api.get("/api/production-jobs/kpis").json()
    mine = api.get(f"/api/production-jobs/kpis?branch_id={seeded['branch_id']}").json()
    other = api.get("/api/production-jobs/kpis?branch_id=999999").json()
    assert mine["units_in_production"] <= all_kpis["units_in_production"]
    assert other["units_in_production"] == 0
    assert other["completed_today"] == 0
    # open_rework has no branch column — global under any filter ("where attributable", §0.7)
    assert other["open_rework"] == all_kpis["open_rework"]


def test_kpis_requires_auth(app_mod):
    from starlette.testclient import TestClient
    with TestClient(app_mod.app) as c:
        assert c.get("/api/production-jobs/kpis").status_code == 401
        assert c.get("/api/production-jobs/in-progress").status_code == 401
