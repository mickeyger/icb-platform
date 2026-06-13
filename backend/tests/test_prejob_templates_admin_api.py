"""WO v4.33 §3.3 — /api/admin/prejob-templates CRUD + approve/deactivate + gating.

Gate tests mint real sessions (no overrides — the require_admin path itself is the subject);
CRUD tests override require_admin with the admin user. Marker rows P433T*; self-healing purge
at setup AND teardown. Nadie's imported drafts are never touched — every mutation targets a
test-created template.
"""
import pytest


def _purge(db) -> None:
    from sqlalchemy import text
    db.execute(text("DELETE FROM icb_mes.prejob_templates WHERE name LIKE 'P433T%'"))
    db.commit()


@pytest.fixture(scope="module")
def app_mod():
    import app.main as m
    from starlette.testclient import TestClient
    with TestClient(m.app):
        yield m


@pytest.fixture
def admin_api(app_mod):
    from app.database import SessionLocal, User
    from app.deps import require_admin
    from starlette.testclient import TestClient
    with SessionLocal() as db:
        _purge(db)
        admin = db.query(User).filter_by(username="admin").first()
    app_mod.app.dependency_overrides[require_admin] = lambda: admin
    with TestClient(app_mod.app) as c:
        yield c
    app_mod.app.dependency_overrides.pop(require_admin, None)
    with SessionLocal() as db:
        _purge(db)


@pytest.fixture
def tpl_id(admin_api):
    """A P433T draft created via the API (so the round-trip is end-to-end... via direct ORM —
    there is deliberately no admin CREATE endpoint in §3.3: templates enter via the importer)."""
    from app.database import SessionLocal
    from app.models.mes import PrejobTemplate
    with SessionLocal() as db:
        t = PrejobTemplate(
            name="P433T EDIT TARGET", body_type="chiller", size_category="big",
            product_line="standard", header_format="0 000mm GRP Chiller Body",
            sections=[{"name": "GRP SECTION",
                       "items": [{"text": "External dimensions ..."}]}],
            created_by="test")
        db.add(t)
        db.commit()
        db.refresh(t)
        return t.id


def test_gate_unauthenticated_401_and_non_admin_403(app_mod):
    from app.database import SessionLocal, User, UserSession
    from starlette.testclient import TestClient
    with TestClient(app_mod.app) as anon:
        assert anon.get("/api/admin/prejob-templates").status_code == 401
    sid = "p433t-sales-sess"
    with SessionLocal() as db:
        sales = db.query(User).filter_by(role="sales").first()
        if sales is None:
            pytest.skip("no sales-role user on this DB")
        db.merge(UserSession(id=sid, user_id=sales.id, role=sales.role, csrf_token="t"))
        db.commit()
    try:
        with TestClient(app_mod.app) as c:
            c.cookies.set("session_id", sid)
            assert c.get("/api/admin/prejob-templates").status_code == 403
    finally:
        with SessionLocal() as db:
            row = db.get(UserSession, sid)
            if row:
                db.delete(row)
                db.commit()


def test_list_derives_summary_fields(admin_api, tpl_id):
    rows = admin_api.get("/api/admin/prejob-templates").json()
    assert len(rows) >= 1
    mine = next(r for r in rows if r["id"] == tpl_id)
    assert mine["section_names"] == ["GRP SECTION"] and mine["item_count"] == 1
    # the §3.2 import landed Nadie's library as drafts — visible here for review
    drafts = [r for r in rows if not r["is_active"]]
    assert len(drafts) >= 1


def test_patch_sections_validates_shape_and_bumps_version(admin_api, tpl_id):
    bad = {"sections": [{"name": "GRP SECTION", "items": [{"text": ""}]}]}
    assert admin_api.patch(f"/api/admin/prejob-templates/{tpl_id}", json=bad).status_code == 422

    good = {"sections": [
        {"name": "GRP SECTION", "items": [
            {"text": "Floor 93mm ...", "note": "check density",
             "sub_items": ["x1", "x2"], "sap_item_code": None}]},
        {"name": "FINISHING SECTION", "items": [{"text": "Reflexite tape"}]},
    ]}
    r = admin_api.patch(f"/api/admin/prejob-templates/{tpl_id}", json=good)
    assert r.status_code == 200
    body = r.json()
    assert body["version"] == 2                          # sections change bumps version
    assert body["sections"][0]["items"][0]["sub_items"] == ["x1", "x2"]
    assert body["section_names"] == ["GRP SECTION", "FINISHING SECTION"]


def test_approve_deactivate_and_delete_rules(admin_api, tpl_id):
    base = f"/api/admin/prejob-templates/{tpl_id}"
    r = admin_api.post(f"{base}/approve")
    assert r.status_code == 200 and r.json()["is_active"] is True
    assert admin_api.delete(base).status_code == 409     # active — refuse delete
    r = admin_api.post(f"{base}/deactivate")
    assert r.status_code == 200 and r.json()["is_active"] is False
    assert admin_api.delete(base).status_code == 204     # draft — gone
    assert admin_api.get(base).status_code == 404


def test_approve_refuses_empty_sections(admin_api):
    from app.database import SessionLocal
    from app.models.mes import PrejobTemplate
    with SessionLocal() as db:
        t = PrejobTemplate(name="P433T EMPTY", body_type="chiller",
                           product_line="standard", sections=[], created_by="test")
        db.add(t)
        db.commit()
        db.refresh(t)
        tid = t.id
    assert admin_api.post(f"/api/admin/prejob-templates/{tid}/approve").status_code == 422
