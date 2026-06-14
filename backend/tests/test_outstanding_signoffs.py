"""WO v4.33.1 §3.1 — admin Outstanding Pre-Job Sign-offs endpoint + service."""


def test_outstanding_service_matches_sent_for_check():
    from sqlalchemy import text
    from app.database import SessionLocal
    from app.services.prejob_cards import list_outstanding_signoffs
    keys = {"id", "quote_number", "customer_name", "sent_for_check_at",
            "sales_rep_username", "sales_rep_signoff_at", "planner_username", "planner_signoff_at"}
    with SessionLocal() as db:
        rows = list_outstanding_signoffs(db)
        n = db.execute(text(
            "select count(*) from icb_mes.prejob_cards where status='sent_for_check'")).scalar()
    assert len(rows) == n                                  # exactly the awaiting-sign-off cards
    for r in rows:
        assert keys.issubset(r.keys())


def test_outstanding_endpoint_admin():
    import app.main as m
    from app.database import SessionLocal, User
    from app.deps import require_admin
    from starlette.testclient import TestClient
    with SessionLocal() as db:
        admin = db.query(User).filter_by(username="admin").first()
    m.app.dependency_overrides[require_admin] = lambda: admin
    try:
        with TestClient(m.app) as c:
            r = c.get("/api/prejob-cards/outstanding")
            assert r.status_code == 200
            body = r.json()
            assert isinstance(body, list)
            for row in body:
                assert "quote_number" in row and "sales_rep_signoff_at" in row
    finally:
        m.app.dependency_overrides.pop(require_admin, None)
