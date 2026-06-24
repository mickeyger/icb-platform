r"""WO v4.36b.2 — regression coverage for csrf_middleware's FORM-FIELD fallback (app/main.py).

Context. CA4's v4.38 §3.0 adversarial sweep reported the fallback's Content-Type literals as
escape-bugged — "application\x-www-form-urlencoded" (\x = a hex escape) and "multipart\form-data"
(\f = form-feed, 0x0C). Verified against the code BEFORE touching it: the literals on main are
correct ("application/x-www-form-urlencoded" / "multipart/form-data") and have been unchanged since
the v4.12 import (git blame -> d37716a); a repo-wide search finds the buggy literal nowhere in the
tree. (The \x variant would in fact be a hard SyntaxError, so it could never have run.) So there is
no literal to fix.

What WAS genuinely missing is coverage: every existing CSRF test drives the X-CSRF-Token HEADER path
(the SPA pattern); none exercises the classic-<form> body fallback (main.py:281-299). These tests
lock that path in — a form POST carrying the token in the BODY (urlencoded AND multipart) passes
CSRF; a wrong or absent body token is rejected 403. Had the literals ever been escape-bugged, the two
"correct token" cases below would 403 instead — so this is also the regression guard for exactly the
class CA4 flagged.

Middleware-level: csrf_middleware reads the session straight off the session_id cookie (not via deps,
main.py:250), so these use a real UserSession row + cookie on the icb_test DB. zzcsrf-* ids, cleaned
up after each test.
"""
import pytest
from starlette.testclient import TestClient


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


@pytest.fixture(autouse=True)
def _cleanup():
    yield
    from app.database import SessionLocal, UserSession
    with SessionLocal() as db:
        db.query(UserSession).filter(UserSession.id.like("zzcsrf-%")).delete(synchronize_session=False)
        db.commit()


def _seed(sid, token, admin):
    from app.database import SessionLocal, UserSession
    with SessionLocal() as db:
        db.merge(UserSession(id=sid, user_id=admin.id, role=admin.role, csrf_token=token))
        db.commit()


def _post(app_mod, sid, **kw):
    """POST to the probe with the session_id cookie set via an explicit Cookie header. csrf_middleware
    reads request.cookies.get('session_id') directly (main.py:250); a raw header is the reliable way to
    land it under the TestClient — httpx's cookie jar won't match the dot-less 'testserver' host."""
    return TestClient(app_mod.app).post(PROBE, headers={"Cookie": f"session_id={sid}"}, **kw)


def _is_csrf_block(r):
    """The two distinctive 403s the middleware — and only the middleware — emits."""
    return r.status_code == 403 and "CSRF token" in r.text


# No handler at this path ON PURPOSE: csrf_middleware runs BEFORE routing, so a CSRF-blocked request
# 403s here while a passing one falls through to a 404 — isolating the middleware from any real
# endpoint's own logic. POST is a non-safe method and the path is non-exempt, so the check runs.
PROBE = "/api/__zzcsrf_probe_v436b2__"


def test_urlencoded_body_token_passes_csrf(app_mod, admin):
    """Classic <form> POST, token in an application/x-www-form-urlencoded body, no header → passes."""
    _seed("zzcsrf-ue-ok", "tok_ue_ok", admin)
    r = _post(app_mod, "zzcsrf-ue-ok", data={"csrf_token": "tok_ue_ok"})
    assert not _is_csrf_block(r), f"urlencoded body token must pass CSRF, got {r.status_code} {r.text[:200]}"


def test_urlencoded_wrong_body_token_rejected(app_mod, admin):
    """Wrong body token (no header) → 403 invalid (constant-time compare, main.py:305)."""
    _seed("zzcsrf-ue-bad", "tok_ue_real", admin)
    r = _post(app_mod, "zzcsrf-ue-bad", data={"csrf_token": "tok_ue_WRONG"})
    assert r.status_code == 403 and r.json()["detail"] == "CSRF token invalid"


def test_form_post_without_token_rejected(app_mod, admin):
    """Form POST with no csrf_token field and no header → 403 missing (main.py:301)."""
    _seed("zzcsrf-ue-missing", "tok_ue_present", admin)
    r = _post(app_mod, "zzcsrf-ue-missing", data={"nope": "x"})
    assert r.status_code == 403 and r.json()["detail"] == "CSRF token missing"


def test_multipart_body_token_passes_csrf(app_mod, admin):
    """Token in a multipart/form-data body → passes (size-guarded form() branch, main.py:293-297)."""
    _seed("zzcsrf-mp-ok", "tok_mp_ok", admin)
    r = _post(app_mod, "zzcsrf-mp-ok",
              data={"csrf_token": "tok_mp_ok"}, files={"f": ("a.txt", b"x")})   # files= → multipart
    assert not _is_csrf_block(r), f"multipart body token must pass CSRF, got {r.status_code} {r.text[:200]}"
