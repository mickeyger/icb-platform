"""WO v4.36c §3.1 — Kenny QC + Dispatch API tests.

DB-backed (real chassis_records / qc_* tables + the 0028 permission grants) → these EXECUTE on
CI/icb_test (the hard db-guard refuses local non-_test DBs, ADR 0011). Auth is injected via
dependency_overrides[require_user] (v4.36b §3.5 pattern); the require_permission gate then evaluates
user_can() against the REAL 0028-seeded grants, so the role tests exercise the actual permission chain.

Covers: the full inspect->signoff->dispatch flow, role-gating (403), server-side completeness, sign-off
immutability, double-signoff idempotency, the FAIL re-inspection loop (cycle increments + failed_count),
the admin defect-categories CRUD (soft-deactivate), and a 200ms perf smoke on the inbox. zzqc-* / a
ZZQC VIN marker for cleanup.
"""
import time

import pytest
from starlette.testclient import TestClient

_VIN = "ZZQCVIN0000000001"        # distinctive marker for the test chassis
_QC_USER = "zzqc_inspector"


@pytest.fixture(scope="module")
def app_mod():
    import app.main as m
    with TestClient(m.app) as _c:
        yield m


@pytest.fixture
def admin():
    from app.database import SessionLocal, User
    with SessionLocal() as db:
        return db.query(User).filter_by(username="admin").first()


@pytest.fixture
def inspector():
    """A real qc_inspector user (role grants qc.inspect+qc.signoff via 0028) — must exist in the DB so
    qc_inspections.inspector_user_id (cross-schema FK) is valid."""
    from app.database import SessionLocal, User
    with SessionLocal() as db:
        u = db.query(User).filter_by(username=_QC_USER).first()
        if u is None:
            u = User(username=_QC_USER, role="qc_inspector", password_hash="x")
            db.add(u)
            db.commit()
            db.refresh(u)
        return u


@pytest.fixture
def chassis():
    """A fresh chassis parked in awaiting_qa (the only QC precondition the service checks)."""
    from app.database import SessionLocal
    from app.models.mes import ChassisRecord
    with SessionLocal() as db:
        rec = ChassisRecord(vin=_VIN, make="QC Test", model="Inbox", customer_name="ZZ QC Cust",
                            status="awaiting_qa", created_via="planning_job_create")
        db.add(rec)
        db.commit()
        cid = rec.id
    yield cid


@pytest.fixture(autouse=True)
def _cleanup():
    yield
    from sqlalchemy import select
    from app.database import SessionLocal, User
    from app.models.mes import ChassisRecord, QcInspection, QcSignoff, DefectCategory
    with SessionLocal() as db:
        ids = [r[0] for r in db.execute(
            select(ChassisRecord.id).where(ChassisRecord.vin == _VIN)).all()]
        for cid in ids:
            db.query(QcInspection).filter(QcInspection.chassis_record_id == cid).delete(synchronize_session=False)
            db.query(QcSignoff).filter(QcSignoff.chassis_record_id == cid).delete(synchronize_session=False)
        db.query(ChassisRecord).filter(ChassisRecord.vin == _VIN).delete(synchronize_session=False)
        db.query(DefectCategory).filter(DefectCategory.name.like("ZZQC %")).delete(synchronize_session=False)
        db.query(User).filter(User.username == _QC_USER).delete(synchronize_session=False)
        db.commit()


def _client(app_mod, user):
    # require_permission gates resolve via Depends(require_user); require_admin calls require_user
    # DIRECTLY (not Depends), so it needs its own override. Override both so the helper covers QC
    # (permission) AND admin (require_admin) endpoints.
    from app.deps import require_user, require_admin
    app_mod.app.dependency_overrides[require_user] = lambda: user
    app_mod.app.dependency_overrides[require_admin] = lambda: user
    c = TestClient(app_mod.app)
    return c


def _drop_override(app_mod):
    from app.deps import require_user, require_admin
    app_mod.app.dependency_overrides.pop(require_user, None)
    app_mod.app.dependency_overrides.pop(require_admin, None)


# ── flow ─────────────────────────────────────────────────────────────────────

def test_awaiting_inbox_lists_chassis(app_mod, inspector, chassis):
    try:
        r = _client(app_mod, inspector).get("/api/qc/awaiting")
        assert r.status_code == 200
        row = next((x for x in r.json() if x["chassis_id"] == chassis), None)
        assert row is not None and row["vin"] == _VIN and row["failed_count"] == 0
    finally:
        _drop_override(app_mod)


def test_inspection_returns_five_default_categories(app_mod, inspector, chassis):
    try:
        r = _client(app_mod, inspector).get(f"/api/qc/inspection/{chassis}")
        assert r.status_code == 200
        body = r.json()
        assert body["cycle_number"] == 1 and body["status"] == "awaiting_qa"
        assert len(body["categories"]) == 5 and all(c["verdict"] is None for c in body["categories"])
    finally:
        _drop_override(app_mod)


def test_record_all_pass_then_signoff_dispatches(app_mod, inspector, chassis):
    try:
        c = _client(app_mod, inspector)
        cats = c.get(f"/api/qc/inspection/{chassis}").json()["categories"]
        for cat in cats:
            rr = c.post(f"/api/qc/inspection/{chassis}/category/{cat['category_id']}",
                        json={"verdict": "pass", "notes": None})
            assert rr.status_code == 200
        s = c.post(f"/api/qc/signoff/{chassis}", json={"notes": "all good"})
        assert s.status_code == 200
        assert s.json()["overall_verdict"] == "pass" and s.json()["new_status"] == "dispatched"
        assert s.json()["pdf_available"] is True
        # it leaves the inbox and enters the dispatch zone
        assert all(x["chassis_id"] != chassis for x in c.get("/api/qc/awaiting").json())
        assert any(x["chassis_id"] == chassis for x in c.get("/api/qc/dispatched").json())
    finally:
        _drop_override(app_mod)


def test_signoff_incomplete_is_422(app_mod, inspector, chassis):
    try:
        c = _client(app_mod, inspector)
        cats = c.get(f"/api/qc/inspection/{chassis}").json()["categories"]
        c.post(f"/api/qc/inspection/{chassis}/category/{cats[0]['category_id']}", json={"verdict": "pass"})
        s = c.post(f"/api/qc/signoff/{chassis}", json={})
        assert s.status_code == 422 and "missing" in s.json()["detail"].lower()
    finally:
        _drop_override(app_mod)


def test_fail_keeps_awaiting_and_increments_cycle(app_mod, inspector, chassis):
    try:
        c = _client(app_mod, inspector)
        cats = c.get(f"/api/qc/inspection/{chassis}").json()["categories"]
        for i, cat in enumerate(cats):
            c.post(f"/api/qc/inspection/{chassis}/category/{cat['category_id']}",
                   json={"verdict": "fail" if i == 0 else "pass"})
        s = c.post(f"/api/qc/signoff/{chassis}", json={})
        assert s.json()["overall_verdict"] == "fail" and s.json()["new_status"] == "awaiting_qa"
        # re-inspection opens the next cycle, and the inbox shows the prior fail
        again = c.get(f"/api/qc/inspection/{chassis}").json()
        assert again["cycle_number"] == 2 and all(cat["verdict"] is None for cat in again["categories"])
        row = next(x for x in c.get("/api/qc/awaiting").json() if x["chassis_id"] == chassis)
        assert row["failed_count"] == 1
    finally:
        _drop_override(app_mod)


def test_record_after_signoff_is_409(app_mod, inspector, chassis):
    try:
        c = _client(app_mod, inspector)
        cats = c.get(f"/api/qc/inspection/{chassis}").json()["categories"]
        for cat in cats:
            c.post(f"/api/qc/inspection/{chassis}/category/{cat['category_id']}", json={"verdict": "pass"})
        c.post(f"/api/qc/signoff/{chassis}", json={})
        # chassis is now 'dispatched' → not awaiting_qa → recording 422 (and a second signoff 422/409)
        rr = c.post(f"/api/qc/inspection/{chassis}/category/{cats[0]['category_id']}", json={"verdict": "fail"})
        assert rr.status_code in (409, 422)
    finally:
        _drop_override(app_mod)


def test_double_signoff_blocked(app_mod, inspector, chassis):
    try:
        c = _client(app_mod, inspector)
        cats = c.get(f"/api/qc/inspection/{chassis}").json()["categories"]
        for cat in cats:
            c.post(f"/api/qc/inspection/{chassis}/category/{cat['category_id']}", json={"verdict": "pass"})
        assert c.post(f"/api/qc/signoff/{chassis}", json={}).status_code == 200
        # second signoff: chassis is 'dispatched' now → 422 (not awaiting_qa)
        assert c.post(f"/api/qc/signoff/{chassis}", json={}).status_code in (409, 422)
    finally:
        _drop_override(app_mod)


# ── role gate ────────────────────────────────────────────────────────────────

def test_non_inspector_role_forbidden(app_mod, chassis):
    from app.database import User
    sales = User(id=999999, username="zzqc_sales", role="sales")  # no qc.* grant
    try:
        r = _client(app_mod, sales).get("/api/qc/awaiting")
        assert r.status_code == 403
    finally:
        _drop_override(app_mod)


# ── admin defect-categories CRUD ───────────────────────────────────────────────

def test_defect_categories_admin_crud(app_mod, admin):
    try:
        c = _client(app_mod, admin)
        assert len(c.get("/api/admin/defect-categories").json()) >= 5      # the 5 seeded defaults
        created = c.post("/api/admin/defect-categories", json={"name": "ZZQC Extra", "sort_order": 60})
        assert created.status_code == 201
        cid = created.json()["id"]
        assert c.patch(f"/api/admin/defect-categories/{cid}", json={"name": "ZZQC Extra2"}).status_code == 200
        assert c.delete(f"/api/admin/defect-categories/{cid}").status_code == 204   # soft-deactivate
        after = next(x for x in c.get("/api/admin/defect-categories").json() if x["id"] == cid)
        assert after["is_active"] is False                                  # row survives, deactivated
    finally:
        _drop_override(app_mod)


def test_defect_categories_admin_only(app_mod):
    # No override → require_admin -> require_user finds no test session → the gate denies (401/403).
    # Proves defect-categories CRUD is admin-gated (not open). zzqc cleanup leaves no override behind.
    r = TestClient(app_mod.app).get("/api/admin/defect-categories")
    assert r.status_code in (401, 403)


# ── customer collection PDF (§3.4) ────────────────────────────────────────────

def test_collection_note_pdf_after_pass(app_mod, inspector, chassis):
    try:
        c = _client(app_mod, inspector)
        for cat in c.get(f"/api/qc/inspection/{chassis}").json()["categories"]:
            c.post(f"/api/qc/inspection/{chassis}/category/{cat['category_id']}", json={"verdict": "pass"})
        c.post(f"/api/qc/signoff/{chassis}", json={})
        r = c.get(f"/api/qc/collection-note/{chassis}")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("application/pdf")
        assert r.content[:5] == b"%PDF-"            # reportlab really rendered a PDF
    finally:
        _drop_override(app_mod)


def test_collection_note_409_before_pass(app_mod, inspector, chassis):
    try:
        r = _client(app_mod, inspector).get(f"/api/qc/collection-note/{chassis}")  # fresh, no signoff
        assert r.status_code == 409
    finally:
        _drop_override(app_mod)


# ── perf smoke (§0.9 / §1.20) ─────────────────────────────────────────────────

def test_awaiting_inbox_under_200ms_p95(app_mod, inspector, chassis):
    try:
        c = _client(app_mod, inspector)
        c.get("/api/qc/awaiting")                       # warm
        times = []
        for _ in range(20):
            t = time.perf_counter()
            assert c.get("/api/qc/awaiting").status_code == 200
            times.append((time.perf_counter() - t) * 1000)
        times.sort()
        p95 = times[int(len(times) * 0.95) - 1]
        assert p95 <= 200, f"/api/qc/awaiting p95={p95:.1f}ms exceeds 200ms"
    finally:
        _drop_override(app_mod)
