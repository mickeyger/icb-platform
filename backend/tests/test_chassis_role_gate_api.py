"""WO v4.36.5 §3.5 — chassis sole-editor + audit-viewer ROLE matrix (API-level).

Auth is injected via dependency_overrides[require_user] (which propagates through require_permission —
see deps.require_perm); the 0005/0013 seed grants each MES role its perms. Fresh role users are created
per test and cleaned up; chassis + audit rows self-purge via the 'V4365ROLE' marker — no seeded row touched.

⚠ Code-grounded note baked into the matrix: 0013 grants `chassis.update` to planner AND **production**
(line 32). So production is NOT blocked by the *permission* — it is blocked from attribute edits by the §3.1
SERVICE role-gate (admin/planner only). That makes the role-gate the load-bearing control, and it makes the
audit endpoint (gated on chassis.update) viewable by production too — broader than the strict edit audience.
The "no chassis.update" deny case is therefore sales/workshop, not production.
"""
import uuid

import pytest

_MARK = "V4365ROLE"


@pytest.fixture(scope="module")
def app_mod():
    import app.main as m
    from starlette.testclient import TestClient
    with TestClient(m.app) as _c:
        yield m


@pytest.fixture
def make_user(app_mod):
    """Factory -> a fresh User with the given MES role (cleaned up; the audit FK is cross-schema SET NULL)."""
    from app.database import SessionLocal, User
    created = []

    def _make(role):
        with SessionLocal() as db:
            u = User(username=f"{_MARK}_{role}_{uuid.uuid4().hex[:6]}", password_hash="x", role=role)
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
    """Factory -> a TestClient acting as `user` (overrides require_user → propagates through require_permission)."""
    from app.deps import require_user
    from starlette.testclient import TestClient

    def _as(user):
        app_mod.app.dependency_overrides[require_user] = lambda u=user: u
        return TestClient(app_mod.app)

    yield _as
    app_mod.app.dependency_overrides.pop(require_user, None)


@pytest.fixture(autouse=True)
def _purge():
    from sqlalchemy import text
    from app.database import SessionLocal

    def go():
        with SessionLocal() as db:
            db.execute(text("DELETE FROM icb_mes.chassis_records_audit WHERE edited_by_name LIKE :m"), {"m": f"{_MARK}%"})
            db.execute(text("DELETE FROM icb_mes.chassis_records WHERE created_source_ref LIKE :m"), {"m": f"{_MARK}%"})
            db.commit()

    go()
    yield
    go()


def _expected_chassis(make="Isuzu FTR") -> int:
    from app.database import SessionLocal
    from app.models.mes import ChassisRecord
    with SessionLocal() as db:
        rec = ChassisRecord(vin=None, status="expected", source="manual",
                            created_via="manual_chassis_menu", created_source_ref=f"{_MARK} ref", make=make)
        db.add(rec)
        db.commit()
        return rec.id


def test_production_blocked_from_attribute_edit_403(make_user, api_as):
    """Q1 — production is read-only on chassis attributes. It HAS chassis.update (0013), so the permission
    layer lets it through; the §3.1 service role-gate is what refuses the edit (403). This is the test that
    proves the role-gate is load-bearing, not redundant with the permission."""
    rid = _expected_chassis()
    c = api_as(make_user("production"))
    assert c.patch(f"/api/chassis-records/{rid}", json={"notes": f"{_MARK} x"}).status_code == 403


def test_planner_can_edit_and_audit_is_visible(make_user, api_as):
    """admin/planner edit (200) and the §3.4 audit endpoint surfaces the change for that same audience."""
    rid = _expected_chassis()
    c = api_as(make_user("planner"))
    r = c.patch(f"/api/chassis-records/{rid}", json={"notes": f"{_MARK} note", "version": 0})
    assert r.status_code == 200, r.text
    rows = c.get(f"/api/chassis-records/{rid}/audit").json()
    assert any(row["field_name"] == "notes" and row["source"] == "chassis_page" for row in rows)


def test_admin_can_view_audit(make_user, api_as):
    rid = _expected_chassis()
    assert api_as(make_user("admin")).get(f"/api/chassis-records/{rid}/audit").status_code == 200


def test_production_with_chassis_update_can_view_audit(make_user, api_as):
    """Documents the breadth: production HOLDS chassis.update (0013), so it CAN read the audit (200) even
    though the role-gate blocks its edits. If the BA wants view==edit (admin/planner only), tighten the
    endpoint with the same role-gate — flagged at §3.5 close."""
    rid = _expected_chassis()
    assert api_as(make_user("production")).get(f"/api/chassis-records/{rid}/audit").status_code == 200


def test_role_without_chassis_update_blocked_from_audit_403(make_user, api_as):
    """The real deny case: sales has no chassis.update grant (0013) → 403 on the audit endpoint."""
    rid = _expected_chassis()
    assert api_as(make_user("sales")).get(f"/api/chassis-records/{rid}/audit").status_code == 403
