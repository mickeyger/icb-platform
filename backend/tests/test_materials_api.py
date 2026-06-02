"""Tests for the Materials / Buying / Stores surface (WO v4.15).

Service unit tests call the service functions directly; integration tests inject
auth via dependency_overrides[require_user] (the host-scoped Secure cookie won't
carry through TestClient — same wrinkle as v4.14). Mutation tests create fresh
rows (po_suggestions / stock_counts) and clean them up so the suite is rerunnable
and order-independent; the seeded read-model rows (12 materials, 11 suppliers,
8 po, 10 counts, 3 discrepancies, 15 demand lines) back the GET smoke tests.
"""
import uuid
from datetime import date

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
def created(app_mod):
    """Tracks rows created by a test and removes them (+ dependent discrepancies)."""
    from app.database import SessionLocal
    from app.models.mes import Discrepancy, POSuggestion, StockCount
    counts: list[int] = []
    pos: list[int] = []
    yield {"counts": counts, "pos": pos}
    with SessionLocal() as db:
        for cid in counts:
            for d in db.query(Discrepancy).filter_by(stock_count_id=cid).all():
                db.delete(d)
            sc = db.get(StockCount, cid)
            if sc:
                db.delete(sc)
        for pid in pos:
            p = db.get(POSuggestion, pid)
            if p:
                db.delete(p)
        db.commit()


@pytest.fixture
def fresh_po(created):
    """Factory -> id of a fresh pending PO suggestion (cleaned up after the test)."""
    from app.database import SessionLocal
    from app.models.mes import POSuggestion

    def _make(status="pending"):
        with SessionLocal() as db:
            p = POSuggestion(
                sap_code=f"TST-{uuid.uuid4().hex[:8]}", qty=5, suggested_supplier="Test Supplier",
                last_price=100.0, total=500.0, urgency="advisory", status=status,
                jobs_impacted=["TST-JOB-1"],
            )
            db.add(p)
            db.commit()
            db.refresh(p)
            created["pos"].append(p.id)
            return p.id

    return _make


@pytest.fixture
def fresh_count(created):
    """Factory -> id of a fresh stock count (cleaned up after the test)."""
    from app.database import SessionLocal
    from app.models.mes import StockCount

    def _make(status="discrepancy", sap_stock=10.0, physical=5.0):
        with SessionLocal() as db:
            sc = StockCount(
                sap_code=f"TST-{uuid.uuid4().hex[:8]}", bin="T-1",
                sap_stock_at_count=sap_stock, physical_count=physical, status=status,
            )
            db.add(sc)
            db.commit()
            db.refresh(sc)
            created["counts"].append(sc.id)
            return sc.id

    return _make


# ── service unit tests ────────────────────────────────────────────────────────
def test_record_count_confirmed(created, user):
    from app.database import SessionLocal
    from app.services import stock_counts as svc
    with SessionLocal() as db:
        item = svc.record_count(db, sap_code="INS-PUR-50", bin="B-12-4", physical_count=40, user=user)
        created["counts"].append(item.id)
        assert item.status == "confirmed" and item.diff == 0


def test_record_count_discrepancy(created, user):
    from app.database import SessionLocal
    from app.services import stock_counts as svc
    with SessionLocal() as db:
        item = svc.record_count(db, sap_code="INS-PUR-50", bin="B-12-4", physical_count=37, user=user)
        created["counts"].append(item.id)
        assert item.status == "discrepancy" and item.diff == -3


def test_raise_discrepancy_requires_discrepancy_status(fresh_count, user):
    from app.database import SessionLocal
    from app.services import stock_counts as svc
    cid = fresh_count(status="confirmed", sap_stock=10, physical=10)
    with SessionLocal() as db:
        with pytest.raises(svc.InvalidStateError):
            svc.raise_discrepancy(db, stock_count_id=cid, user=user)


def test_resolve_twice_raises(fresh_count, user):
    from app.database import SessionLocal
    from app.services import discrepancies as dsvc
    from app.services import stock_counts as scsvc
    cid = fresh_count(status="discrepancy")
    with SessionLocal() as db:
        disc = scsvc.raise_discrepancy(db, stock_count_id=cid, raised_to_buyer_name="M. Nkomo", user=user)
        dsvc.resolve_discrepancy(db, discrepancy_id=disc.id, resolution_notes="ok", user=user)
        with pytest.raises(dsvc.InvalidStateError):
            dsvc.resolve_discrepancy(db, discrepancy_id=disc.id, user=user)


def test_raise_pr_once_then_422(fresh_po, user):
    from app.database import SessionLocal
    from app.services import po_suggestions as svc
    pid = fresh_po()
    with SessionLocal() as db:
        item = svc.raise_pr(db, suggestion_id=pid, user=user)
        assert item.status == "raised" and item.pr_number.startswith("PR-")
        with pytest.raises(svc.InvalidStateError):
            svc.raise_pr(db, suggestion_id=pid, user=user)


def test_defer_after_raise_422(fresh_po, user):
    from app.database import SessionLocal
    from app.services import po_suggestions as svc
    pid = fresh_po()
    with SessionLocal() as db:
        svc.raise_pr(db, suggestion_id=pid, user=user)
        with pytest.raises(svc.InvalidStateError):
            svc.defer_suggestion(db, suggestion_id=pid, deferred_until=date(2026, 6, 30), user=user)


# ── integration tests (auth injected) ──────────────────────────────────────────
def test_materials_list_seeded(api):
    r = api.get("/api/mes-materials")
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 12
    assert all("stock" in m for m in body)


def test_material_detail_and_404(api):
    d = api.get("/api/mes-materials/GRP-MPS-A-0077").json()
    assert d["sap_code"] == "GRP-MPS-A-0077"
    assert d["stock"]["sap_stock"] is not None
    assert isinstance(d["recent_counts"], list)
    assert api.get("/api/mes-materials/NOPE-404").status_code == 404


def test_materials_low_stock_filter(api):
    rows = api.get("/api/mes-materials?low_stock=true").json()
    assert len(rows) == 2  # DOR-RR-2000 + FRZ-CT-380 (free == 0)
    assert all(m["stock"]["free"] <= 0 for m in rows)


def test_materials_dept_filter(api):
    rows = api.get("/api/mes-materials?dept=vacuum").json()
    assert rows and all(m["dept"] == "vacuum" for m in rows)


def test_suppliers_seeded(api):
    assert len(api.get("/api/suppliers").json()) == 11


def test_po_suggestions_seeded_and_enriched(api):
    rows = api.get("/api/po-suggestions").json()
    assert len(rows) == 8
    assert any(p["jobs_impacted"] for p in rows)         # Q3 column populated
    assert any(p.get("supplier_contact") for p in rows)  # enriched from suppliers
    assert any(p.get("description") for p in rows)        # enriched from catalogue


def test_po_status_filter(api):
    assert len(api.get("/api/po-suggestions?status=pending").json()) == 8
    assert api.get("/api/po-suggestions?status=raised").json() == []


def test_discrepancies_resolved_filter(api):
    unresolved = api.get("/api/discrepancies?resolved=false").json()
    assert len(unresolved) >= 3
    assert all(not d["resolved"] for d in unresolved)


def test_demand_lines_and_rollups(api):
    assert len(api.get("/api/demand-lines").json()) == 15
    week = api.get("/api/demand-lines?group_by=week").json()
    assert week and all("total_qty" in r and "job_count" in r for r in week)
    sap = api.get("/api/demand-lines?group_by=sap").json()
    assert len(sap) == 12
    assert len(sap) <= 15  # rollup row count never exceeds the raw lines


def test_record_count_roundtrip(api, created):
    # POST a count with a variance -> discrepancy
    r = api.post("/api/stock-counts", json={"sap_code": "INS-PUR-50", "bin": "B-12-4", "physical_count": 37})
    assert r.status_code == 201
    sc = r.json()
    created["counts"].append(sc["id"])
    assert sc["status"] == "discrepancy" and sc["diff"] == -3
    before = len(api.get("/api/discrepancies").json())
    rd = api.post(f"/api/stock-counts/{sc['id']}/raise-discrepancy", json={"raised_to_buyer_name": "M. Nkomo"})
    assert rd.status_code == 201
    disc = rd.json()
    assert len(api.get("/api/discrepancies").json()) == before + 1
    res = api.post(f"/api/discrepancies/{disc['id']}/resolve", json={"resolution_notes": "Mis-issue corrected"})
    assert res.status_code == 200
    assert res.json()["resolved"] is True and res.json()["resolved_at"] is not None


def test_raise_discrepancy_on_confirmed_422(api, created):
    r = api.post("/api/stock-counts", json={"sap_code": "INS-PUR-50", "bin": "B-12-4", "physical_count": 40})
    sc = r.json()
    created["counts"].append(sc["id"])
    assert sc["status"] == "confirmed"
    assert api.post(f"/api/stock-counts/{sc['id']}/raise-discrepancy", json={}).status_code == 422


def test_stock_count_branch_filter(api, created):
    from app.database import Branch, SessionLocal
    with SessionLocal() as db:
        jhb = db.query(Branch).filter_by(code="JHB").first().id
    r = api.post("/api/stock-counts",
                 json={"sap_code": "INS-PUR-50", "bin": "B-1", "physical_count": 40, "branch_id": jhb})
    sc = r.json()
    created["counts"].append(sc["id"])
    assert any(x["id"] == sc["id"] for x in api.get(f"/api/stock-counts?branch_id={jhb}").json())
    assert api.get("/api/stock-counts?branch_id=999999").json() == []


def test_raise_pr_endpoint(api, fresh_po):
    pid = fresh_po()
    r = api.post(f"/api/po-suggestions/{pid}/raise")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "raised" and body["pr_number"].startswith("PR-")
    assert api.post(f"/api/po-suggestions/{pid}/raise").status_code == 422  # already raised


def test_defer_endpoint(api, fresh_po):
    pid = fresh_po()
    r = api.post(f"/api/po-suggestions/{pid}/defer", json={"deferred_until": "2026-06-30"})
    assert r.status_code == 200 and r.json()["status"] == "deferred"


def test_requires_auth(app_mod):
    from app.deps import require_user
    from starlette.testclient import TestClient
    app_mod.app.dependency_overrides.pop(require_user, None)
    with TestClient(app_mod.app) as c:
        assert c.get("/api/mes-materials").status_code == 401
        assert c.get("/api/suppliers").status_code == 401
        assert c.get("/api/po-suggestions").status_code == 401
