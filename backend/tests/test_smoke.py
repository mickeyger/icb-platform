"""Smoke tests — the unified app boots on PostgreSQL, Jinja routes behave, the
React SPA is served at /mes-app/, auth runs through the provider, the
multi-branch seed is present, and (WO v4.13) the icb_mes schema + seed load."""


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


# ── WO v4.13: icb_mes schema + seed ──────────────────────────────────────────

def test_mes_schema_tables():
    # 12 (WO v4.13) + 3 (v4.15: mes_materials/stock_positions/suppliers) + 1 (v4.16:
    # session_branches) + 2 (v4.22: live_daily_count/chassis_register)
    # + 3 (v4.25: bom_rules/bom_rule_lookups/material_price_overrides)
    # + 1 (v4.26: bom_spec_options) + 2 (v4.27: generated_boms/bom_lines)
    # + 3 (v4.28: chassis_records/chassis_lifecycle_events/chassis_photos)
    # + 2 (v4.31: parking_bays/assembly_bays)
    # + 3 (v4.33: prejob_templates/prejob_cards/fridge_units) = 32.
    from sqlalchemy import text
    from app.database import SessionLocal
    with SessionLocal() as db:
        n = db.execute(text(
            "select count(*) from information_schema.tables "
            "where table_schema='icb_mes' and table_type='BASE TABLE'")).scalar()
        new_tables = db.execute(text(
            "select count(*) from information_schema.tables where table_schema='icb_mes' "
            "and table_name in ('mes_materials','stock_positions','suppliers','session_branches')")).scalar()
        v422_tables = db.execute(text(
            "select count(*) from information_schema.tables where table_schema='icb_mes' "
            "and table_name in ('live_daily_count','chassis_register')")).scalar()
        v425_tables = db.execute(text(
            "select count(*) from information_schema.tables where table_schema='icb_mes' "
            "and table_name in ('bom_rules','bom_rule_lookups','material_price_overrides')")).scalar()
        v426_tables = db.execute(text(
            "select count(*) from information_schema.tables where table_schema='icb_mes' "
            "and table_name = 'bom_spec_options'")).scalar()
        v427_tables = db.execute(text(
            "select count(*) from information_schema.tables where table_schema='icb_mes' "
            "and table_name in ('generated_boms','bom_lines')")).scalar()
        v428_tables = db.execute(text(
            "select count(*) from information_schema.tables where table_schema='icb_mes' "
            "and table_name in ('chassis_records','chassis_lifecycle_events','chassis_photos')")).scalar()
        v431_tables = db.execute(text(
            "select count(*) from information_schema.tables where table_schema='icb_mes' "
            "and table_name in ('parking_bays','assembly_bays')")).scalar()
        v433_tables = db.execute(text(
            "select count(*) from information_schema.tables where table_schema='icb_mes' "
            "and table_name in ('prejob_templates','prejob_cards','fridge_units')")).scalar()
        v434_tables = db.execute(text(
            "select count(*) from information_schema.tables where table_schema='icb_mes' "
            "and table_name = 'chassis_models'")).scalar()      # WO v4.34 §3.7 (migration 0021)
    assert n == 36                                              # +chassis_models (0021); +production_jobs_audit (0023); +production_job_bay_events (0024); +feedback_submissions (v4.38 0027)
    assert new_tables == 4
    assert v422_tables == 2
    assert v425_tables == 3
    assert v426_tables == 1
    assert v427_tables == 2
    assert v428_tables == 3
    assert v431_tables == 2
    assert v433_tables == 3
    assert v434_tables == 1


def test_legacy_view_exposes_old_shape():
    from sqlalchemy import text
    from app.database import SessionLocal
    with SessionLocal() as db:
        cols = db.execute(text(
            "select count(*) from information_schema.columns where "
            "table_schema='icb_costings' and table_name='v_calculation_records_legacy'")).scalar()
    assert cols == 32  # 14 staying + 18 moved columns


def test_seed_from_mockup_counts():
    # Self-contained: seed (reset) then assert the volumes match the mockup JSON.
    from scripts.seed_from_mockup import seed
    seed(reset=True)
    from app.database import SessionLocal
    from app.models.mes import (
        DemandLine, Discrepancy, POSuggestion, ProductionJob, StockCount,
    )
    with SessionLocal() as db:
        assert db.query(POSuggestion).count() == 8
        assert db.query(StockCount).count() == 10
        assert db.query(Discrepancy).count() == 3
        assert db.query(DemandLine).count() == 15
        assert db.query(ProductionJob).count() >= 1
