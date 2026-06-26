"""WO v4.37 §3.1 — Cost Calculator backend hardening.

Covers the four ratified §3.1 changes:
  • D-3 — branch scoping / IDOR close on calculation-by-id (soft, ADR 0010).
  • D-4 — optimistic-lock etag token exposed on GET (full overwrite-412 round-trip
          needs the heavy /api/approve payload → lands in §3.6 journey coverage).
  • D-5 — BOM-PUT user-mode allowlist now includes unit_price_override.
  (Silent-deferral rollback on assign_quote_number failure also needs the full
   /api/approve payload → §3.6 journey coverage.)

Pure-function tests prove the security/concurrency PREDICATES directly (no DB).
Integration tests prove WIRING via a real session cookie — the calculator/trailer
endpoints authenticate through get_current_user(request, db) (cookie), NOT an
overridable Depends, so we seed a UserSession + cookie rather than override.
Per ADR 0011 these execute on CI/icb_test (the local guard aborts off a *_test DB).
"""
import json
import uuid
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException

from app.deps import can_access_calc, assert_calc_access, scoped_branch_id
from app.routers.calculator import _record_etag


# ── stubs for the pure-function tests ─────────────────────────────────────────
class _U:
    def __init__(self, role):
        self.role = role


class _B:
    def __init__(self, id):
        self.id = id


class _R:
    def __init__(self, result_json=None, dimensions_json=None, status=None):
        self.result_json = result_json
        self.dimensions_json = dimensions_json
        self.status = status


# ── D-3 predicate (pure) ──────────────────────────────────────────────────────
def test_can_access_calc_admin_bypasses_branch():
    assert can_access_calc(_U("admin"), rec_branch_id=99, scope_branch_id=1) is True


def test_can_access_calc_no_active_branch_sees_all():
    assert can_access_calc(_U("user"), rec_branch_id=99, scope_branch_id=None) is True


def test_can_access_calc_null_record_is_shared():
    # WO v4.29 D1 — an unbranched (legacy) calc is shared, visible even when scoped.
    assert can_access_calc(_U("user"), rec_branch_id=None, scope_branch_id=1) is True


def test_can_access_calc_blocks_cross_branch():
    assert can_access_calc(_U("user"), rec_branch_id=2, scope_branch_id=1) is False


def test_can_access_calc_allows_matching_branch():
    assert can_access_calc(_U("user"), rec_branch_id=1, scope_branch_id=1) is True


def test_scoped_branch_id_none_when_unswitched():
    assert scoped_branch_id(None) is None


def test_scoped_branch_id_returns_branch_id():
    assert scoped_branch_id(_B(7)) == 7


def test_assert_calc_access_raises_404_cross_branch():
    with pytest.raises(HTTPException) as ei:
        assert_calc_access(2, _U("user"), _B(1))
    assert ei.value.status_code == 404


def test_assert_calc_access_passes_same_branch():
    assert_calc_access(1, _U("user"), _B(1))  # no raise


def test_assert_calc_access_admin_passes_cross_branch():
    assert_calc_access(2, _U("admin"), _B(1))  # admin bypass, no raise


def test_assert_calc_access_passes_when_no_branch_switched():
    assert_calc_access(2, _U("user"), None)  # scope None → ADR 0010 soft model, no raise


# ── D-4 etag (pure) ───────────────────────────────────────────────────────────
def test_record_etag_is_deterministic():
    a = _record_etag(_R('{"x":1}', '{"l":2}', "pending"))
    b = _record_etag(_R('{"x":1}', '{"l":2}', "pending"))
    assert a == b and len(a) == 16


def test_record_etag_changes_with_content():
    base = _record_etag(_R('{"x":1}', "{}", "pending"))
    assert _record_etag(_R('{"x":2}', "{}", "pending")) != base   # result changed
    assert _record_etag(_R('{"x":1}', "{}", "accepted")) != base  # status changed


def test_record_etag_tolerates_none_fields():
    e = _record_etag(_R(None, None, None))
    assert isinstance(e, str) and len(e) == 16


# ── integration fixtures ──────────────────────────────────────────────────────
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
def make_user():
    from app.database import SessionLocal, User
    created = []

    def _make(role="user"):
        with SessionLocal() as db:
            u = User(username=f"v437_{role}_{uuid.uuid4().hex[:6]}", password_hash="x", role=role)
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
def session_client(app_mod):
    """Factory → a TestClient authenticated as `user` via a REAL session cookie,
    optionally switched to `branch_id` (SessionBranch row)."""
    from app.database import SessionLocal, UserSession
    from app.models.mes import SessionBranch
    from starlette.testclient import TestClient
    sids = []

    def _mk(user, branch_id=None):
        sid = f"v437-{uuid.uuid4().hex[:10]}"
        with SessionLocal() as db:
            db.merge(UserSession(id=sid, user_id=user.id, role=user.role))
            if branch_id is not None:
                db.merge(SessionBranch(session_id=sid, branch_id=branch_id,
                                       updated_at=datetime.now(timezone.utc)))
            db.commit()
        c = TestClient(app_mod.app)
        c.cookies.set("session_id", sid)
        sids.append(sid)
        return c

    yield _mk
    from app.database import SessionLocal as SL
    from app.models.mes import SessionBranch as SB
    with SL() as db:
        for sid in sids:
            sb = db.get(SB, sid)
            if sb:
                db.delete(sb)
            us = db.get(UserSession, sid)
            if us:
                db.delete(us)
        db.commit()


@pytest.fixture
def calc_in_branch():
    """Factory → id of a fresh pending CalculationRecord in `branch_id` (or NULL)."""
    from app.database import SessionLocal, CalculationRecord
    ids = []

    def _mk(branch_id=None, status="pending"):
        with SessionLocal() as db:
            c = CalculationRecord(branch_id=branch_id, status=status,
                                  dimensions_json=json.dumps({"length": 6}),
                                  result_json=json.dumps({"version": 1, "grand_total": 100}))
            db.add(c)
            db.commit()
            db.refresh(c)
            ids.append(c.id)
            return c.id

    yield _mk
    with SessionLocal() as db:
        for cid in ids:
            c = db.get(CalculationRecord, cid)
            if c:
                db.delete(c)
        db.commit()


@pytest.fixture
def existing_bom():
    """An existing BillOfMaterial id; restores its unit_price_override on teardown."""
    from app.database import SessionLocal, BillOfMaterial
    saved = {}

    def _get():
        with SessionLocal() as db:
            row = db.query(BillOfMaterial).first()
            if row is None:
                return None
            saved[row.id] = row.unit_price_override
            return row.id

    yield _get
    with SessionLocal() as db:
        for bid, orig in saved.items():
            row = db.get(BillOfMaterial, bid)
            if row is not None:
                row.unit_price_override = orig
        db.commit()


def _branch_id(code):
    from app.database import SessionLocal, Branch
    with SessionLocal() as db:
        b = db.query(Branch).filter_by(code=code).first()
        return b.id if b else None


# ── D-3 integration (IDOR close) ──────────────────────────────────────────────
def test_d3_get_blocks_cross_branch_for_switched_user(make_user, session_client, calc_in_branch):
    jhb, cpt = _branch_id("JHB"), _branch_id("CPT")
    if jhb is None or cpt is None:
        pytest.skip("JHB/CPT branches not seeded")
    rec_jhb = calc_in_branch(branch_id=jhb)
    rec_cpt = calc_in_branch(branch_id=cpt)
    rec_null = calc_in_branch(branch_id=None)
    c = session_client(make_user("user"), branch_id=jhb)
    assert c.get(f"/api/calculations/{rec_jhb}").status_code == 200    # own branch
    assert c.get(f"/api/calculations/{rec_cpt}").status_code == 404    # cross-branch IDOR closed
    assert c.get(f"/api/calculations/{rec_null}").status_code == 200   # NULL = shared (v4.29 D1)
    # D-4 — the GET exposes the optimistic-lock token the React editor sends back.
    assert "etag" in c.get(f"/api/calculations/{rec_jhb}").json()


def test_d3_admin_bypasses_branch_scope(admin, session_client, calc_in_branch):
    jhb, cpt = _branch_id("JHB"), _branch_id("CPT")
    if jhb is None or cpt is None:
        pytest.skip("JHB/CPT branches not seeded")
    rec_cpt = calc_in_branch(branch_id=cpt)
    c = session_client(admin, branch_id=jhb)   # admin switched to JHB
    assert c.get(f"/api/calculations/{rec_cpt}").status_code == 200   # admin sees every branch


def test_d3_unswitched_user_sees_all_soft_model(make_user, session_client, calc_in_branch):
    cpt = _branch_id("CPT")
    if cpt is None:
        pytest.skip("CPT branch not seeded")
    rec_cpt = calc_in_branch(branch_id=cpt)
    c = session_client(make_user("user"))   # no branch switch → ADR 0010 soft model
    assert c.get(f"/api/calculations/{rec_cpt}").status_code == 200


# ── D-5 integration (BOM-PUT allowlist) ───────────────────────────────────────
def test_d5_non_admin_can_set_unit_price_override(make_user, session_client, existing_bom):
    bid = existing_bom()
    if bid is None:
        pytest.skip("no BillOfMaterial seeded")
    c = session_client(make_user("user"))
    # WO v4.37 D-5 — unit_price_override is now user-writable (was admin-only → 403).
    assert c.put(f"/api/bom/{bid}", json={"unit_price_override": 123.45}).status_code == 200


def test_d5_non_admin_still_blocked_from_structural_fields(make_user, session_client, existing_bom):
    bid = existing_bom()
    if bid is None:
        pytest.skip("no BillOfMaterial seeded")
    c = session_client(make_user("user"))
    # A structural field (formula_expression) breaks the strict-subset gate → require_admin → 403.
    assert c.put(f"/api/bom/{bid}", json={"formula_expression": "2"}).status_code == 403


# ── §3.2 addendum — edit-reopen optimistic lock (D-4 etag) ─────────────────────
def test_d4_overwrite_412_on_stale_etag(make_user, session_client):
    """WO v4.37 §3.2 addendum — reopening a costing to edit and overwriting it is
    refused 412 when it changed since the editor loaded it (mock concurrent edit),
    and accepted once the editor re-loads the fresh etag."""
    import json
    from app.database import SessionLocal, CalculationRecord, TrailerType
    with SessionLocal() as db:
        tt = db.query(TrailerType).first()
        if tt is None:
            pytest.skip("no trailer type seeded")
        ttid = tt.id
        rec = CalculationRecord(trailer_type_id=ttid, status="pending",
                                dimensions_json=json.dumps({}),
                                result_json=json.dumps({"version": 1, "grand_total": 100}))
        db.add(rec)
        db.commit()
        db.refresh(rec)
        rid = rec.id
    try:
        c = session_client(make_user("user"))
        loaded = c.get(f"/api/calculations/{rid}")
        assert loaded.status_code == 200
        stale_etag = loaded.json().get("etag")
        assert stale_etag
        # Concurrent edit by someone else → the record's etag moves.
        with SessionLocal() as db:
            r = db.get(CalculationRecord, rid)
            r.result_json = json.dumps({"version": 1, "grand_total": 999})
            db.commit()
        body = {"trailer_type_id": ttid, "dimensions": {}, "version_action": "overwrite",
                "edit_record_id": rid, "base_etag": stale_etag}
        assert c.post("/api/approve", json=body).status_code == 412     # stale → refused
        fresh_etag = c.get(f"/api/calculations/{rid}").json().get("etag")
        body["base_etag"] = fresh_etag
        assert c.post("/api/approve", json=body).status_code == 200     # re-loaded → accepted
    finally:
        with SessionLocal() as db:
            r = db.get(CalculationRecord, rid)
            if r:
                db.delete(r)
                db.commit()
