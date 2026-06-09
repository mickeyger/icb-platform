"""Tests for WO v4.16 — Planning Board, active-branch session, per-role gating.

Service unit tests call services directly. Integration tests inject auth via
dependency_overrides[require_user]; the 403 matrix creates real users with MES
roles (the 0005 seed grants them perms) and asserts allow/deny. Mutations create
fresh rows (cleaned up) so the suite is rerunnable.
"""
import json
import uuid
from datetime import date, datetime, timedelta, timezone

import pytest


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
    """Factory -> a fresh User with the given role (cleaned up; cross-schema FKs SET NULL)."""
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
    """Factory -> a TestClient acting as `user` (overrides require_user)."""
    from app.deps import require_user
    from starlette.testclient import TestClient

    def _as(user):
        app_mod.app.dependency_overrides[require_user] = lambda u=user: u
        return TestClient(app_mod.app)

    yield _as
    app_mod.app.dependency_overrides.pop(require_user, None)


@pytest.fixture
def fresh_po(app_mod):
    from app.database import SessionLocal
    from app.models.mes import POSuggestion
    created = []

    def _make(supplier="Test Supplier", status="pending"):
        with SessionLocal() as db:
            p = POSuggestion(sap_code=f"TST-{uuid.uuid4().hex[:6]}", qty=2, suggested_supplier=supplier,
                             last_price=100.0, total=200.0, urgency="advisory", status=status)
            db.add(p)
            db.commit()
            db.refresh(p)
            created.append(p.id)
            return p.id

    yield _make
    with SessionLocal() as db:
        for pid in created:
            p = db.get(POSuggestion, pid)
            if p:
                db.delete(p)
        db.commit()


@pytest.fixture
def fresh_planning_job(app_mod):
    """Factory -> id of a fresh status='planning' production job (+ its calc). Cleaned up."""
    from app.database import Branch, CalculationRecord, SessionLocal
    from app.models.mes import PlanningSlot, ProductionJob
    pjs, calcs = [], []

    def _make(chassis_eta=None, chassis_received_at=None):
        with SessionLocal() as db:
            jhb = db.query(Branch).filter_by(code="JHB").first()
            c = CalculationRecord(
                quote_number=f"Q-PL{uuid.uuid4().hex[:8]}", status="accepted", branch_id=jhb.id,
                dimensions_json=json.dumps({"body_type": "Test Body"}),
                result_json=json.dumps({"selling_zar": 1000.0}))
            db.add(c)
            db.commit()
            db.refresh(c)
            calcs.append(c.id)
            pj = ProductionJob(calculation_record_id=c.id, branch_id=jhb.id, job_number=f"PL{c.id}",
                               status="planning", chassis_eta=chassis_eta,
                               chassis_received_at=chassis_received_at)
            db.add(pj)
            db.commit()
            db.refresh(pj)
            pjs.append(pj.id)
            return pj.id

    yield _make
    with SessionLocal() as db:
        for pid in pjs:
            for s in db.query(PlanningSlot).filter_by(production_job_id=pid).all():
                db.delete(s)
            pj = db.get(ProductionJob, pid)
            if pj:
                db.delete(pj)
        for cid in calcs:
            c = db.get(CalculationRecord, cid)
            if c:
                db.delete(c)
        db.commit()


# ── service unit tests ──────────────────────────────────────────────────────
def test_eta_gate_blocks_bypasses_and_passes():
    """WO v4.29 D4 (§0.4 revised, BA 7-Jun): `received` is an explicit kwarg; the gate BLOCKS when
    there is neither receipt nor ETA (the inverted-symptom fix), RETAINS the within-target-week guard,
    and bypasses entirely when received."""
    from app.services import planning as pl

    class J:
        pass
    j = J()
    j.chassis_eta = datetime(2026, 12, 1, tzinfo=timezone.utc)
    assert pl.eta_gate_reason(j, date(2026, 6, 1), received=False) is not None    # ETA after target week -> blocked
    assert pl.eta_gate_reason(j, date(2026, 12, 7), received=False) is None       # week of the ETA -> ok
    assert pl.eta_gate_reason(j, date(2026, 6, 1), received=True) is None         # received -> bypass
    j.chassis_eta = None
    assert pl.eta_gate_reason(j, date(2026, 6, 1), received=False) is not None    # no ETA + not received -> BLOCK (v4.29 fix)
    assert pl.eta_gate_reason(j, date(2026, 6, 1), received=True) is None         # no ETA but received -> ok


def test_schedule_occupied_409(fresh_planning_job, admin):
    from app.database import SessionLocal
    from app.services import planning as pl
    # WO v4.29 D4: the gate now blocks jobs with no chassis signal, so mark the chassis received —
    # this test is about cell occupancy, not the ETA gate.
    rcv = datetime(2026, 1, 1, tzinfo=timezone.utc)
    a, b = fresh_planning_job(chassis_received_at=rcv), fresh_planning_job(chassis_received_at=rcv)
    with SessionLocal() as db:
        pl.schedule(db, production_job_id=a, week=date(2026, 9, 7), bay="QA-1", user=admin)
        with pytest.raises(pl.CellOccupiedError):
            pl.schedule(db, production_job_id=b, week=date(2026, 9, 7), bay="QA-1", user=admin)


def test_schedule_eta_gate(fresh_planning_job, admin):
    from app.database import SessionLocal
    from app.services import planning as pl
    jid = fresh_planning_job(chassis_eta=datetime(2027, 1, 1, tzinfo=timezone.utc))
    with SessionLocal() as db:
        with pytest.raises(pl.ChassisEtaError):
            pl.schedule(db, production_job_id=jid, week=date(2026, 6, 1), bay="QA-2", user=admin)


def test_unschedule_frees(fresh_planning_job, admin):
    from app.database import SessionLocal
    from app.models.mes import PlanningSlot
    from app.services import planning as pl
    jid = fresh_planning_job(chassis_received_at=datetime(2026, 1, 1, tzinfo=timezone.utc))  # D4: ready to schedule
    with SessionLocal() as db:
        it = pl.schedule(db, production_job_id=jid, week=date(2026, 9, 14), bay="QA-3", user=admin)
        pl.unschedule(db, slot_id=it.id, user=admin)
        assert db.get(PlanningSlot, it.id) is None


def test_override_recompute_and_raised_422(fresh_po, admin):
    from app.database import SessionLocal
    from app.services import po_suggestions as po
    pid = fresh_po()
    with SessionLocal() as db:
        it = po.override_supplier(db, suggestion_id=pid, supplier_name="NewSup", last_price=50, user=admin)
        assert it.suggested_supplier == "NewSup" and it.total == 100  # qty 2 * 50
        po.raise_pr(db, suggestion_id=pid, user=admin)
        with pytest.raises(po.InvalidStateError):
            po.override_supplier(db, suggestion_id=pid, supplier_name="X", user=admin)


def test_bulk_raise_groups_and_skips(fresh_po, admin):
    from app.database import SessionLocal
    from app.services import po_suggestions as po
    a, b, c = fresh_po(supplier="S1"), fresh_po(supplier="S1"), fresh_po(supplier="S2")
    with SessionLocal() as db:
        res = po.bulk_raise(db, ids=[a, b, c], user=admin)
        assert len(res.pr_numbers) == 2 and len(res.raised) == 3 and len(res.skipped) == 0
        again = po.bulk_raise(db, ids=[a, b, c], user=admin)
        assert len(again.raised) == 0 and len(again.skipped) == 3


# ── integration tests ─────────────────────────────────────────────────────────
def test_session_get_defaults(api):
    s = api.get("/api/session").json()
    assert s["active_branch"]["code"] == "JHB"
    assert {b["code"] for b in s["accessible_branches"]} == {"JHB", "CPT", "CEN"}


def test_session_returns_permissions(api, api_as, make_user):
    # admin (the `api` fixture) gets all seeded permission keys (wildcard).
    admin_perms = api.get("/api/session").json()["permissions"]
    assert {"buying.bulk_raise", "planning.schedule", "stores.count"} <= set(admin_perms)
    # a buyer has raise_pr / defer_pr but not the senior-only bulk_raise / override.
    buyer_perms = api_as(make_user("buyer")).get("/api/session").json()["permissions"]
    assert "buying.raise_pr" in buyer_perms
    assert "buying.bulk_raise" not in buyer_perms and "buying.override_supplier" not in buyer_perms


def test_planning_board_seeded(api):
    bd = api.get("/api/planning-board?weeks=8").json()
    assert len(bd["slots"]) >= 1 and "unscheduled_pool" in bd and "capacity" in bd
    assert isinstance(bd["lanes"], list)


def test_schedule_move_unschedule_roundtrip(api, fresh_planning_job):
    jid = fresh_planning_job(chassis_received_at=datetime(2026, 1, 1, tzinfo=timezone.utc))  # D4: ready to schedule
    r = api.post("/api/planning-slots", json={"production_job_id": jid, "week": "2026-10-05",
                                              "bay": "QA-7", "lane": "test", "slot_position": 7})
    assert r.status_code == 201
    slot_id = r.json()["id"]
    assert r.json()["production_job"]["planned_start_date"] is not None
    mv = api.post(f"/api/planning-slots/{slot_id}/move", json={"week": "2026-10-12", "bay": "QA-8"})
    assert mv.status_code == 200 and mv.json()["bay"] == "QA-8"
    assert api.delete(f"/api/planning-slots/{slot_id}").status_code == 200


def test_schedule_eta_gate_422(api, fresh_planning_job):
    jid = fresh_planning_job(chassis_eta=datetime(2027, 6, 1, tzinfo=timezone.utc))
    r = api.post("/api/planning-slots", json={"production_job_id": jid, "week": "2026-06-01", "bay": "QA-9"})
    assert r.status_code == 422


def test_session_switch_scopes_lists(app_mod, admin):
    from app.database import Branch, SessionLocal
    from app.deps import current_session_id, require_user
    from app.models.mes import SessionBranch
    from starlette.testclient import TestClient
    app_mod.app.dependency_overrides[require_user] = lambda: admin
    app_mod.app.dependency_overrides[current_session_id] = lambda: "test-sess-X"
    try:
        with SessionLocal() as db:
            cpt = db.query(Branch).filter_by(code="CPT").first().id
        with TestClient(app_mod.app) as c:
            total = len(c.get("/api/production-jobs?limit=100").json())      # no switch -> all
            sw = c.post("/api/session/branch", json={"branch_id": cpt})
            assert sw.status_code == 200 and sw.json()["active_branch"]["code"] == "CPT"
            switched = len(c.get("/api/production-jobs?limit=100").json())    # now CPT-scoped
            explicit = len(c.get(f"/api/production-jobs?branch_id={cpt}&limit=100").json())
            assert switched == explicit and switched <= total
    finally:
        app_mod.app.dependency_overrides.pop(require_user, None)
        app_mod.app.dependency_overrides.pop(current_session_id, None)
        with SessionLocal() as db:
            sb = db.get(SessionBranch, "test-sess-X")
            if sb:
                db.delete(sb)
                db.commit()


def test_switch_unknown_branch_404(api):
    assert api.post("/api/session/branch", json={"branch_id": 999999}).status_code == 404


# ── per-role permission matrix (403) ────────────────────────────────────────
def test_buyer_can_raise_but_not_bulk(make_user, api_as, fresh_po):
    c = api_as(make_user("buyer"))
    assert c.post(f"/api/po-suggestions/{fresh_po()}/raise").status_code == 200   # has buying.raise_pr
    assert c.post("/api/po-suggestions/raise", json={"ids": [fresh_po()]}).status_code == 403  # lacks bulk


def test_buyer_senior_can_bulk(make_user, api_as, fresh_po):
    c = api_as(make_user("buyer_senior"))
    assert c.post("/api/po-suggestions/raise", json={"ids": [fresh_po()]}).status_code == 200


def test_stores_can_count_not_raise(make_user, api_as):
    c = api_as(make_user("stores"))
    rc = c.post("/api/stock-counts", json={"sap_code": "INS-PUR-50", "bin": "Z-1", "physical_count": 40})
    assert rc.status_code == 201                                                 # has stores.count
    assert c.post("/api/po-suggestions/1/raise").status_code == 403              # lacks buying.raise_pr
    # cleanup the created count
    from app.database import SessionLocal
    from app.models.mes import StockCount
    with SessionLocal() as db:
        sc = db.get(StockCount, rc.json()["id"])
        if sc:
            db.delete(sc)
            db.commit()


def test_planner_can_schedule(make_user, api_as, fresh_planning_job):
    c = api_as(make_user("planner"))
    jid = fresh_planning_job(chassis_received_at=datetime(2026, 1, 1, tzinfo=timezone.utc))  # D4: ready to schedule
    r = c.post("/api/planning-slots", json={"production_job_id": jid, "week": "2026-11-02", "bay": "QA-11"})
    assert r.status_code == 201                                                  # has planning.schedule


def test_plain_user_forbidden(make_user, api_as, fresh_po):
    c = api_as(make_user("user"))   # no MES grants
    assert c.post(f"/api/po-suggestions/{fresh_po()}/raise").status_code == 403
    assert c.post("/api/planning-slots", json={"production_job_id": 1, "week": "2026-06-01", "bay": "X-1"}).status_code == 403


def test_reads_ungated_for_any_user(make_user, api_as):
    c = api_as(make_user("user"))
    assert c.get("/api/planning-board").status_code == 200
    assert c.get("/api/po-suggestions").status_code == 200
    assert c.get("/api/session").status_code == 200


def test_session_returns_csrf_token(app_mod, admin):
    """GET /api/session exposes the session's CSRF token so the SPA can send
    X-CSRF-Token on mutations (WO v4.18 csrf_middleware enabler)."""
    from app.database import SessionLocal, UserSession
    from app.deps import current_session_id, require_user
    from starlette.testclient import TestClient
    sid = "test-csrf-sess-v418"
    app_mod.app.dependency_overrides[require_user] = lambda: admin
    app_mod.app.dependency_overrides[current_session_id] = lambda: sid
    try:
        with SessionLocal() as db:
            db.merge(UserSession(id=sid, user_id=admin.id, role=admin.role, csrf_token="tok_v418_csrf"))
            db.commit()
        with TestClient(app_mod.app) as c:
            body = c.get("/api/session").json()
            assert "csrf_token" in body
            assert body["csrf_token"] == "tok_v418_csrf"
    finally:
        app_mod.app.dependency_overrides.pop(require_user, None)
        app_mod.app.dependency_overrides.pop(current_session_id, None)
        with SessionLocal() as db:
            row = db.get(UserSession, sid)
            if row:
                db.delete(row)
                db.commit()
