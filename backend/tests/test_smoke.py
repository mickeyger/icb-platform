"""Phase 1 smoke tests — the unified app boots on PostgreSQL, the Jinja routes
behave, the React SPA is served at /mes-app/, auth runs through the provider,
and the multi-branch seed is present."""


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json().get("status") == "ok"


def test_login_page_renders(client):
    r = client.get("/login")
    assert r.status_code == 200
    assert "Trailer Costing System" in r.text


def test_calculator_requires_auth(client):
    r = client.get("/calculator", follow_redirects=False)
    assert r.status_code in (302, 303, 307)
    assert "/login" in r.headers.get("location", "")


def test_mes_app_served(client):
    r = client.get("/mes-app/", follow_redirects=False)
    # 200 once the frontend is built (CI builds it); 503 if dist is absent.
    assert r.status_code in (200, 503)
    if r.status_code == 200:
        assert "/mes-app/assets" in r.text


def test_login_runs_through_provider(client):
    bad = client.post("/login", data={"username": "admin", "password": "nope"},
                      follow_redirects=False)
    assert bad.status_code == 200  # re-renders the login form with an error
    ok = client.post("/login", data={"username": "admin", "password": "admin123"},
                     follow_redirects=False)
    assert ok.status_code in (302, 303, 307)


def test_branches_seeded():
    from app.database import SessionLocal, Branch
    with SessionLocal() as db:
        codes = {b.code for b in db.query(Branch).all()}
    assert {"JHB", "CPT", "CEN"}.issubset(codes)


def test_auth_provider_is_email_password():
    from app.auth import get_auth_provider
    assert get_auth_provider().name == "email_password"
