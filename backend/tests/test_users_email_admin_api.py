"""v1.39.3 (CA10) — admin-editable user email + role-clobber safety.

The /api/users endpoints gate with require_admin(request, db) INLINE (not a Depends), so these
tests mint real sessions (the require_admin path itself is the subject). Covers: PUT
/api/users/{id}/email happy path + format validation + blank-clears, the admin role-gate
(401 anon / 403 non-admin), email surfaced in GET /api/users, and the broadened role allowlist
(sales/planner assignable) so the legacy edit modal can no longer reset a Phase-1 role.
Marker users P39EU*; self-healing purge at setup + teardown.
"""
import uuid

import pytest


def _purge(db) -> None:
    from sqlalchemy import text
    db.execute(text("DELETE FROM icb_costings.user_sessions WHERE id LIKE 'p39eu-%'"))
    db.execute(text("DELETE FROM icb_costings.users WHERE username LIKE 'P39EU%'"))
    db.commit()


@pytest.fixture(scope="module")
def app_mod():
    import app.main as m
    from starlette.testclient import TestClient
    with TestClient(m.app):
        yield m


@pytest.fixture
def env(app_mod):
    """Yield (client_as, target_id). client_as(role) -> a TestClient carrying a session for a
    freshly-minted user of that role ('admin' reuses the seeded admin)."""
    from app.database import SessionLocal, User, UserSession
    from app.deps import pwd_context
    from starlette.testclient import TestClient
    made_users, made_sids = [], []
    with SessionLocal() as db:
        _purge(db)
        admin = db.query(User).filter_by(username="admin").first()
        target = User(username=f"P39EU_target_{uuid.uuid4().hex[:6]}", role="user",
                      email="old@icecoldgrp.co.za", password_hash=pwd_context.hash("x"))
        db.add(target)
        db.commit()
        target_id = target.id
        made_users.append(target_id)

        def _client_as(role):
            with SessionLocal() as d2:
                if role == "admin":
                    uid = admin.id
                else:
                    u = User(username=f"P39EU_{role}_{uuid.uuid4().hex[:6]}", role=role,
                             email="", password_hash=pwd_context.hash("x"))
                    d2.add(u)
                    d2.commit()
                    uid = u.id
                    made_users.append(uid)
                sid = f"p39eu-{uuid.uuid4().hex[:8]}"
                d2.merge(UserSession(id=sid, user_id=uid, role=role, csrf_token="t"))
                d2.commit()
                made_sids.append(sid)
            c = TestClient(app_mod.app)
            c.cookies.set("session_id", sid)
            return c

    yield _client_as, target_id

    with SessionLocal() as db:
        for sid in made_sids:
            r = db.get(UserSession, sid)
            if r:
                db.delete(r)
        for uid in made_users:
            u = db.get(User, uid)
            if u:
                db.delete(u)
        db.commit()
        _purge(db)


def test_admin_sets_valid_email_and_it_surfaces_in_list(env):
    client_as, tid = env
    admin = client_as("admin")
    r = admin.put(f"/api/users/{tid}/email", json={"email": "new@icecoldgrp.co.za"})
    assert r.status_code == 200, r.text
    assert r.json()["email"] == "new@icecoldgrp.co.za"
    listed = {u["id"]: u for u in admin.get("/api/users").json()}
    assert listed[tid]["email"] == "new@icecoldgrp.co.za"


def test_admin_blank_email_clears(env):
    client_as, tid = env
    admin = client_as("admin")
    r = admin.put(f"/api/users/{tid}/email", json={"email": "  "})
    assert r.status_code == 200, r.text
    assert r.json()["email"] == ""


def test_admin_invalid_email_rejected(env):
    client_as, tid = env
    admin = client_as("admin")
    for bad in ("not-an-email", "a@b", "a@b.", "@x.co"):
        r = admin.put(f"/api/users/{tid}/email", json={"email": bad})
        assert r.status_code == 400, f"{bad!r} should be rejected, got {r.status_code}"


def test_non_admin_forbidden_and_anon_unauthorized(env, app_mod):
    from starlette.testclient import TestClient
    client_as, tid = env
    # anonymous -> 401
    assert TestClient(app_mod.app).put(f"/api/users/{tid}/email",
                                       json={"email": "x@y.co"}).status_code == 401
    # a planner (non-admin) -> 403 (only admins edit other users' emails)
    planner = client_as("planner")
    assert planner.put(f"/api/users/{tid}/email",
                       json={"email": "x@y.co"}).status_code == 403


def test_sales_and_planner_roles_are_assignable(env):
    """Broadened allowlist (the role-clobber fix): the admin UI can now set sales/planner —
    so editing a Phase-1 signer no longer forces their role back to a legacy value."""
    client_as, tid = env
    admin = client_as("admin")
    for role in ("sales", "planner"):
        r = admin.put(f"/api/users/{tid}/role", json={"role": role})
        assert r.status_code == 200, r.text
        assert r.json()["role"] == role
