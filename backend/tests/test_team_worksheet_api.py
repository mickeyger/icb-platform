"""WO v4.32 §3.1/§3.3 — GET /api/production/team-worksheet + the §0.4 bays/assembly
utilisation extension.

Covers: the uniform 5-team contract (same shape, team-specific fields nullable), the §3.3
validation locks (team allow-list, ±7-day date clamp), per-team §0.6 defaults (slot weeks for
vacuum/press incl. the press→'panelshop' lane mapping; event-derived assembly occupancy;
parking pool + capacity chip; expected/overdue chassis ETAs; dispatch pending-collection +
collected-on-date), and the additive BayOut utilisation fields (v4.31 consumers keep
id/code/label). Expected values RE-DERIVE from the DB where counts could collide with
pre-existing dev rows. Self-cleaning fixtures (v4.27 standing rule).
"""
from datetime import datetime, timedelta, timezone

import pytest


def _now():
    return datetime.now(timezone.utc)


def _purge_markers(db):
    """Delete every T432W* marker row (FK-safe order). Runs at fixture setup AND teardown so a
    mid-test crash can never leak rows into the next run (self-healing, v4.27 standing rule)."""
    from sqlalchemy import text
    db.execute(text("DELETE FROM icb_mes.chassis_lifecycle_events WHERE chassis_record_id IN "
                    "(SELECT id FROM icb_mes.chassis_records WHERE vin LIKE 'T432W%')"))
    db.execute(text("DELETE FROM icb_mes.planning_slots WHERE bay IN ('V-77','P-77')"))
    db.execute(text("DELETE FROM icb_mes.production_jobs WHERE job_number LIKE 'T432W%'"))
    db.execute(text("DELETE FROM icb_mes.chassis_records WHERE vin LIKE 'T432W%'"))
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
def seeded(app_mod, api):
    """One row per team surface, all marker-prefixed (T432W*) + self-cleaned:
    vacuum + press slots this week; a parking-pool chassis; an assembly-bay occupant (on a
    bay that is FREE pre-test); an expected-arrival job (ETA today), an overdue-ETA job
    (yesterday); a completed job pending collection; a chassis DCL'd today."""
    from app.database import Branch, SessionLocal
    from app.models.mes import (
        ChassisLifecycleEvent, ChassisRecord, PlanningSlot, ProductionJob,
    )
    now = _now()
    today = now.date()
    monday = today - timedelta(days=today.weekday())
    created = {"jobs": [], "chassis": [], "events": [], "slots": []}

    free = [b for b in api.get("/api/chassis-records/bays/assembly").json() if not b["occupied"]]
    if not free:
        pytest.skip("no free assembly bay on this DB")
    bay = free[0]

    with SessionLocal() as db:
        _purge_markers(db)                      # self-heal any leak from a crashed prior run
        branch = db.query(Branch).order_by(Branch.id).first()
        assert branch is not None

        def job(num, **kw):
            j = ProductionJob(branch_id=branch.id, source="workbook", job_number=num,
                              accepted_at=now - timedelta(days=2), **kw)
            db.add(j)
            db.flush()
            created["jobs"].append(j.id)
            return j

        j_vac = job("T432WV1", status="planning", customer_name="WS VACUUM")
        j_prs = job("T432WP1", status="in_production", customer_name="WS PRESS")
        db.add_all([
            PlanningSlot(production_job_id=j_vac.id, week=monday, bay="V-77",
                         lane="vacuum", slot_position=77, status="scheduled"),
            PlanningSlot(production_job_id=j_prs.id, week=monday, bay="P-77",
                         lane="panelshop", slot_position=77, status="in_progress"),
        ])

        rec_yard = ChassisRecord(vin="T432WYARD", source="manual", status="in_workshop",
                                 customer_name="WS YARD")
        rec_bay = ChassisRecord(vin="T432WBAY", source="manual", status="in_assembly",
                                customer_name="WS ON-BAY")
        rec_done = ChassisRecord(vin="T432WDONE", source="manual", status="in_workshop",
                                 customer_name="WS PENDING-COLLECT")
        rec_gone = ChassisRecord(vin="T432WGONE", source="manual", status="dispatched",
                                 customer_name="WS COLLECTED")
        db.add_all([rec_yard, rec_bay, rec_done, rec_gone])
        db.flush()
        created["chassis"] = [rec_yard.id, rec_bay.id, rec_done.id, rec_gone.id]

        def ev(rec_id, etype, edate, **kw):
            e = ChassisLifecycleEvent(chassis_record_id=rec_id, cycle_number=1,
                                      event_type=etype, event_date=edate, created_by="t", **kw)
            db.add(e)
            db.flush()
            created["events"].append(e.id)

        ev(rec_yard.id, "VCL", today - timedelta(days=1))
        ev(rec_bay.id, "VCL", today - timedelta(days=2))
        ev(rec_bay.id, "assembly_assigned", today - timedelta(days=1),
           assembly_bay_id=bay["id"])
        ev(rec_done.id, "VCL", today - timedelta(days=9))
        ev(rec_gone.id, "VCL", today - timedelta(days=5))
        ev(rec_gone.id, "DCL", today)

        job("T432WETA", status="planning", customer_name="WS ARRIVING", chassis_eta=now)
        job("T432WLATE", status="planning", customer_name="WS OVERDUE",
            chassis_eta=now - timedelta(days=3))
        job("T432WCOL", status="completed", customer_name="WS COLLECT",
            completed_at=now - timedelta(days=9), chassis_record_id=rec_done.id)

        db.commit()
    try:
        yield {"bay_code": bay["code"], "bay_id": bay["id"], "monday": monday}
    finally:
        with SessionLocal() as db:
            _purge_markers(db)


def _names(items):
    return {i["job_number"] or i["chassis_vin"] for i in items}


def test_team_validation(api):
    assert api.get("/api/production/team-worksheet?team=paintshop").status_code == 422
    far = (_now() + timedelta(days=30)).date().isoformat()
    assert api.get(f"/api/production/team-worksheet?team=vacuum&date={far}").status_code == 422


def test_uniform_contract_all_five_teams(api):
    for team in ("vacuum", "press", "assembly", "parking", "dispatch"):
        body = api.get(f"/api/production/team-worksheet?team={team}").json()
        assert body["team"] == team
        assert body["date"] == _now().date().isoformat()      # defaults to today
        assert set(body["sections"]) == {"scheduled", "in_flight", "blocking"}


def test_vacuum_and_press_slot_weeks(api, seeded):
    vac = api.get("/api/production/team-worksheet?team=vacuum").json()
    assert "T432WV1" in _names(vac["sections"]["scheduled"])
    prs = api.get("/api/production/team-worksheet?team=press").json()   # lane='panelshop'
    assert "T432WP1" in _names(prs["sections"]["in_flight"])
    assert "T432WV1" not in _names(prs["sections"]["scheduled"])        # lanes don't bleed


def test_assembly_occupancy_and_utilisation_extension(api, seeded):
    ws = api.get("/api/production/team-worksheet?team=assembly").json()
    mine = [i for i in ws["sections"]["in_flight"] if i["chassis_vin"] == "T432WBAY"]
    assert mine and mine[0]["location"] == seeded["bay_code"]
    bays = api.get("/api/chassis-records/bays/assembly").json()
    target = next(b for b in bays if b["id"] == seeded["bay_id"])
    assert target["occupied"] is True and target["occupant_vin"] == "T432WBAY"
    for b in bays:                                            # v4.31 contract intact
        assert {"id", "code", "label"} <= set(b)


def test_parking_pool_capacity_and_eta_views(api, seeded):
    from app.database import SessionLocal
    from app.models.mes import ChassisRecord, ParkingBay
    body = api.get("/api/production/team-worksheet?team=parking").json()
    assert "T432WYARD" in _names(body["sections"]["in_flight"])
    assert "T432WETA" in _names(body["sections"]["scheduled"])          # ETA == today
    late = [i for i in body["sections"]["blocking"] if i["job_number"] == "T432WLATE"]
    assert late and "overdue" in (late[0]["flag"] or "")
    with SessionLocal() as db:
        exp_total = db.query(ParkingBay).filter_by(is_active=True).count()
        exp_used = db.query(ChassisRecord).filter_by(status="in_workshop").count()
    assert body["capacity"]["total"] == exp_total
    # used counts the branch-visible pool; with no other-branch jobs in fixture it equals the pool
    assert body["capacity"]["used"] <= exp_used


def test_dispatch_pending_and_collected(api, seeded):
    body = api.get("/api/production/team-worksheet?team=dispatch").json()
    pend = [i for i in body["sections"]["scheduled"] if i["job_number"] == "T432WCOL"]
    assert pend and pend[0]["status"] == "pending_collection"
    assert "awaiting collection" in (pend[0]["flag"] or "")             # 9d > 7d threshold
    assert "T432WGONE" in _names(body["sections"]["in_flight"])         # DCL'd today


def test_worksheet_requires_auth(app_mod):
    from starlette.testclient import TestClient
    with TestClient(app_mod.app) as c:
        assert c.get("/api/production/team-worksheet?team=vacuum").status_code == 401
