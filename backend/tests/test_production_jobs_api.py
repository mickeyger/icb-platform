"""Tests for the /api/production-jobs surface (WO v4.14).

Service unit tests call the service functions directly. Integration tests inject
auth via dependency_overrides[require_user] (avoids the host-scoped Secure-cookie
issue with TestClient). A `fresh_calc` factory creates accepted calculations with
no production_job (the seeded accepted calcs are all already linked).
"""
import json
import uuid

import pytest


# ── fixtures ──────────────────────────────────────────────────────────────────
@pytest.fixture(scope="module")
def app_mod():
    import app.main as m
    from starlette.testclient import TestClient
    with TestClient(m.app) as _c:   # triggers startup -> seeds admin user
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
def fresh_calc(app_mod):
    """Factory -> calculation_id for a fresh accepted calc with no production_job."""
    from app.database import SessionLocal, CalculationRecord, Branch
    from app.models.mes import ProductionJob
    created = []

    def _make(is_repair=False, status="accepted"):
        with SessionLocal() as db:
            jhb = db.query(Branch).filter_by(code="JHB").first()
            c = CalculationRecord(
                quote_number=f"Q-T{uuid.uuid4().hex[:8]}",
                status=status, is_repair=is_repair,
                branch_id=(jhb.id if jhb else None),
                dimensions_json=json.dumps({"body_type": "Test Body", "body_category": "DF"}),
                result_json=json.dumps({"cost_zar": 1000.0, "selling_zar": 1650.0,
                                        "gross_profit_zar": 650.0, "markup_pct": 65}),
            )
            db.add(c)
            db.commit()
            created.append(c.id)
            return c.id

    yield _make

    with SessionLocal() as db:
        for cid in created:
            for pj in db.query(ProductionJob).filter_by(calculation_record_id=cid).all():
                db.delete(pj)          # CASCADE clears planning_acks etc.
            c = db.get(CalculationRecord, cid)
            if c:
                db.delete(c)
        db.commit()


# ── service unit tests ──────────────────────────────────────────────────────
def test_accept_is_idempotent(fresh_calc, user):
    from app.database import SessionLocal
    from app.services import production_jobs as svc
    cid = fresh_calc()
    with SessionLocal() as db:
        (job1, *_), created1 = svc.accept_calculation(db, cid, user)
        (job2, *_), created2 = svc.accept_calculation(db, cid, user)
    assert created1 is True and created2 is False
    assert job1.id == job2.id
    assert job1.status == "accepted"


def test_accept_rejects_non_accepted_calc(fresh_calc, user):
    from app.database import SessionLocal
    from app.services import production_jobs as svc
    cid = fresh_calc(status="pending")
    with SessionLocal() as db:
        with pytest.raises(svc.CalculationNotAcceptedError):
            svc.accept_calculation(db, cid, user)


def test_repair_quote_blocks_pre_job_card(fresh_calc, user):
    from app.database import SessionLocal
    from app.services import production_jobs as svc
    cid = fresh_calc(is_repair=True)
    with SessionLocal() as db:
        (job, *_), _ = svc.accept_calculation(db, cid, user)
        with pytest.raises(svc.RepairQuoteCannotSendPreJobError):
            svc.send_pre_job_card(db, job.id, user)


def test_signoff_auto_progresses_to_confirmed(fresh_calc, user):
    from app.database import SessionLocal
    from app.services import production_jobs as svc
    cid = fresh_calc()
    with SessionLocal() as db:
        (job, *_), _ = svc.accept_calculation(db, cid, user)
        svc.send_pre_job_card(db, job.id, user)
        (j1, *_) = svc.record_signoff(db, job.id, "sales", "ok-sales", user)
        assert j1.status == "pre_job_sent"        # only one signoff so far
        (j2, *_) = svc.record_signoff(db, job.id, "production", "ok-prod", user)
        assert j2.status == "pre_job_confirmed"   # both -> confirmed


def test_planning_ack_requires_confirmed(fresh_calc, user):
    from app.database import SessionLocal
    from app.services import production_jobs as svc
    cid = fresh_calc()
    with SessionLocal() as db:
        (job, *_), _ = svc.accept_calculation(db, cid, user)  # status 'accepted'
        with pytest.raises(svc.WrongStatusForTransitionError):
            svc.record_planning_ack(db, job.id, None, None, user)


# ── integration tests (auth injected) ────────────────────────────────────────
def test_list_returns_seeded_jobs(api):
    r = api.get("/api/production-jobs?limit=100")
    assert r.status_code == 200
    assert len(r.json()) >= 10  # 15 seeded


def test_detail_has_joined_costing(api):
    jid = api.get("/api/production-jobs?limit=1").json()[0]["id"]
    d = api.get(f"/api/production-jobs/{jid}").json()
    assert {"customer", "body_type", "selling_zar", "mes_status", "status", "is_repair"} <= set(d)
    assert d["grand_total"] == d["selling_zar"]


def test_round_trip(api, fresh_calc):
    cid = fresh_calc()
    acc = api.post(f"/api/production-jobs/from-calculation/{cid}")
    assert acc.status_code == 201
    jid = acc.json()["id"]
    assert api.post(f"/api/production-jobs/{jid}/pre-job-card").json()["status"] == "pre_job_sent"
    api.post(f"/api/production-jobs/{jid}/pre-job-signoff", json={"role": "sales", "attestation": "s"})
    conf = api.post(f"/api/production-jobs/{jid}/pre-job-signoff", json={"role": "production", "attestation": "p"})
    assert conf.json()["status"] == "pre_job_confirmed"
    ack = api.post(f"/api/production-jobs/{jid}/planning-ack", json={"notes": "ok"})
    assert ack.status_code == 200 and ack.json()["status"] == "planning"
    tl = api.get(f"/api/production-jobs/{jid}/timeline").json()
    assert len(tl) == 5  # accepted, pre_job_sent, signoff_sales, signoff_production, planning_ack
    rec = api.post(f"/api/production-jobs/{jid}/chassis-received")
    assert rec.status_code == 200 and rec.json()["chassis_received_at"] is not None


def test_from_calculation_idempotent_returns_200(api, fresh_calc):
    cid = fresh_calc()
    assert api.post(f"/api/production-jobs/from-calculation/{cid}").status_code == 201
    again = api.post(f"/api/production-jobs/from-calculation/{cid}")
    assert again.status_code == 200


def test_repair_pre_job_card_422(api, fresh_calc):
    cid = fresh_calc(is_repair=True)
    jid = api.post(f"/api/production-jobs/from-calculation/{cid}").json()["id"]
    assert api.post(f"/api/production-jobs/{jid}/pre-job-card").status_code == 422


def test_branch_filter(api):
    from app.database import SessionLocal, Branch
    with SessionLocal() as db:
        jhb = db.query(Branch).filter_by(code="JHB").first().id
    assert len(api.get(f"/api/production-jobs?branch_id={jhb}").json()) >= 1
    assert api.get("/api/production-jobs?branch_id=999999").json() == []


def test_requires_auth(app_mod):
    from app.deps import require_user
    from starlette.testclient import TestClient
    app_mod.app.dependency_overrides.pop(require_user, None)
    with TestClient(app_mod.app) as c:
        assert c.get("/api/production-jobs").status_code == 401


# ── WO v4.19 (Phase 2C-3) additions ───────────────────────────────────────────
def test_list_item_has_calculation_record_id(api, fresh_calc):
    """The list item exposes calculation_record_id so the Costings dashboard can
    join /api/calculations (spine) with /api/production-jobs (WO v4.19 §0.1)."""
    cid = fresh_calc()
    jid = api.post(f"/api/production-jobs/from-calculation/{cid}").json()["id"]
    row = next(r for r in api.get("/api/production-jobs?limit=200").json() if r["id"] == jid)
    assert row["calculation_record_id"] == cid


def test_accepted_mes_status_label_is_neutral(api, fresh_calc):
    """Flag B: the 'accepted' status keeps the neutral 'Accepted' label — the
    dispatch event is 'Pre-Job Sent', so the orderbook clarification is a frontend
    tooltip, NOT a relabel. Guards against a dispatch-implying label creeping in."""
    cid = fresh_calc()
    jid = api.post(f"/api/production-jobs/from-calculation/{cid}").json()["id"]
    assert api.get(f"/api/production-jobs/{jid}").json()["mes_status"] == "Accepted"
    row = next(r for r in api.get("/api/production-jobs?limit=200").json() if r["id"] == jid)
    assert row["mes_status"] == "Accepted"


# ── WO v4.21 (Phase 2D-2) — workbook-imported jobs (NULL calc, carrier columns) ─
@pytest.fixture
def workbook_job(app_mod):
    """Factory -> production_job id for a workbook-imported job: NULL
    calculation_record_id, source='workbook', customer/body/selling on the carriers."""
    from app.database import SessionLocal, Branch
    from app.models.mes import ProductionJob
    created = []

    def _make(**kw):
        with SessionLocal() as db:
            jhb = db.query(Branch).filter_by(code="JHB").first()
            j = ProductionJob(
                calculation_record_id=None, source="workbook",
                branch_id=(jhb.id if jhb else None),
                job_number=kw.get("job_number", f"WB{uuid.uuid4().hex[:6]}"),
                status=kw.get("status", "planning"),
                customer_name=kw.get("customer_name", "Workbook Customer Ltd"),
                description=kw.get("description", "11.9m Dryfreight"),
                selling_zar=kw.get("selling_zar", 250000.0),
            )
            db.add(j)
            db.commit()
            created.append(j.id)
            return j.id

    yield _make
    with SessionLocal() as db:
        for jid in created:
            j = db.get(ProductionJob, jid)
            if j:
                db.delete(j)
        db.commit()


def test_workbook_job_lists_without_calc(api, workbook_job):
    """A production_job with NULL calculation_record_id (workbook import) must appear
    in the list via the LEFT join, with customer/body/selling from the carrier columns
    and source='workbook'. Guards the inner-join regression that would silently drop it."""
    jid = workbook_job(customer_name="Malu Pork", description="6.7m Carcass", selling_zar=312000.0)
    rows = api.get("/api/production-jobs?limit=300").json()
    row = next((r for r in rows if r["id"] == jid), None)
    assert row is not None, "workbook job dropped from list (inner-join regression)"
    assert row["calculation_record_id"] is None
    assert row["source"] == "workbook"
    assert row["customer"] == "Malu Pork"
    assert row["body_type"] == "6.7m Carcass"
    assert row["selling_zar"] == 312000.0


def test_workbook_job_detail_no_calc(api, workbook_job):
    """The detail endpoint must not error on a null-calc job; calc-derived fields are
    None and the workbook carriers come through."""
    jid = workbook_job()
    d = api.get(f"/api/production-jobs/{jid}").json()
    assert d["source"] == "workbook"
    assert d["calculation_record_id"] is None
    assert d["quote_number"] is None
    assert d["is_repair"] is False
    assert d["customer"] == "Workbook Customer Ltd"
