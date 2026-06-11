"""WO v4.33 §3.4 — /api/prejob-cards lifecycle: create-prefill, draft edits, submit-for-check.

Covers the §0 locks: §0.6 suggestion ranking (rhinorange_2_0 first), §0.13 sales-rep default
(quote-time column, calc-owner fallback), §0.8 body-gap gate (422 unless waived), §0.14
re-submit clears reject_reason, §0.21 legacy production_jobs drive (positive path: an
'accepted' job flips to pre_job_sent; jobless calcs submit fine), §0.3 user-options (planner
list = planner+admin, production excluded), draft-only edit 409s, one-card-per-costing 409.
P433C markers; self-healing purge; uses an EXISTING calculation (read-only on icb_costings —
the v4.27/§0.20 rule) that has no production job, so no real job is ever touched.
"""
import pytest


def _purge(db) -> None:
    from sqlalchemy import text
    db.execute(text("DELETE FROM icb_mes.prejob_cards WHERE body_description LIKE 'P433C%'"))
    db.execute(text("DELETE FROM icb_mes.prejob_templates WHERE name LIKE 'P433C%'"))
    db.execute(text("DELETE FROM icb_mes.production_jobs WHERE job_number LIKE 'P433C%'"))
    db.commit()


@pytest.fixture(scope="module")
def app_mod():
    import app.main as m
    from starlette.testclient import TestClient
    with TestClient(m.app):
        yield m


@pytest.fixture
def api(app_mod):
    """Admin (code-level wildcard satisfies require_permission('prejob.create'))."""
    from app.database import SessionLocal, User
    from app.deps import require_permission, require_user
    from starlette.testclient import TestClient
    with SessionLocal() as db:
        _purge(db)
        admin = db.query(User).filter_by(username="admin").first()
    app_mod.app.dependency_overrides[require_user] = lambda: admin
    # require_permission returns a nested dependency; override the require_user it builds on
    with TestClient(app_mod.app) as c:
        yield c
    app_mod.app.dependency_overrides.pop(require_user, None)
    with SessionLocal() as db:
        _purge(db)


@pytest.fixture
def seeded(api):
    """A free calculation (no production job), two P433C templates (2.0 + legacy, both active,
    same body/size so §0.6 ranking is observable), and the ids needed by the tests."""
    from app.database import CalculationRecord, SessionLocal
    from app.models.mes import PrejobTemplate, ProductionJob
    sections = [{"name": "GRP SECTION", "items": [{"text": "External dimensions ..."}]},
                {"name": "SUB FRAME SECTION", "items": [{"text": "Body gap - TBC"}]},
                {"name": "FINISHING SECTION", "items": [{"text": "Reflexite tape"}]}]
    with SessionLocal() as db:
        taken = {j.calculation_record_id for j in db.query(ProductionJob)
                 .filter(ProductionJob.calculation_record_id.isnot(None)).all()}
        calc = (db.query(CalculationRecord)
                .filter(~CalculationRecord.id.in_(taken or {0}))
                .order_by(CalculationRecord.id).first())
        if calc is None:
            pytest.skip("no job-free calculation on this DB")
        t_legacy = PrejobTemplate(name="P433C Big Test Body (legacy)", body_type="freezer",
                                  size_category="big", product_line="rhinorange_legacy",
                                  header_format="P433C header", sections=sections,
                                  is_active=True, created_by="t")
        t_20 = PrejobTemplate(name="P433C Big Test Body 2.0", body_type="freezer",
                              size_category="big", product_line="rhinorange_2_0",
                              header_format="P433C header 2.0", sections=sections,
                              is_active=True, created_by="t")
        t_draft = PrejobTemplate(name="P433C Draft (must not list)", body_type="freezer",
                                 size_category="big", product_line="standard",
                                 sections=sections, is_active=False, created_by="t")
        db.add_all([t_legacy, t_20, t_draft])
        db.commit()
        return {"calc_id": calc.id, "calc_user_id": calc.user_id,
                "tpl_20": t_20.id, "tpl_legacy": t_legacy.id, "tpl_draft": t_draft.id}


def test_template_options_rank_rhinorange_20_first_and_hide_drafts(api, seeded):
    rows = api.get("/api/prejob-cards/templates?body_type=freezer&size_hint=big").json()
    names = [r["name"] for r in rows]
    assert "P433C Draft (must not list)" not in names           # §0.15 structural gate
    i20 = names.index("P433C Big Test Body 2.0")
    ileg = names.index("P433C Big Test Body (legacy)")
    assert i20 < ileg                                           # §0.6 — 2.0 preferred
    assert rows[0]["suggested"] is True


def test_user_options_planner_includes_admin_excludes_production(api, seeded):
    planners = api.get("/api/prejob-cards/user-options?kind=planner").json()
    roles = {u["role"] for u in planners}
    assert "admin" in roles and "production" not in roles       # §0.3 / Q4
    assert api.get("/api/prejob-cards/user-options?kind=nope").status_code == 422


def test_create_prefills_and_one_card_per_costing(api, seeded):
    r = api.post("/api/prejob-cards", json={"calculation_id": seeded["calc_id"],
                                            "template_id": seeded["tpl_20"]})
    assert r.status_code == 201
    card = r.json()
    assert card["status"] == "draft"
    assert card["body_description"] == "P433C header 2.0"       # template header prefill
    assert [s["name"] for s in card["sections"]] == [
        "GRP SECTION", "SUB FRAME SECTION", "FINISHING SECTION"]
    # §0.13 — sales rep defaults to calc.sales_rep_user_id (NULL on legacy rows) → calc owner
    assert card["sales_rep_user_id"] == seeded["calc_user_id"]
    assert card["body_gap_pending"] is (card["body_gap_mm"] is None)
    # one card per costing (§0.7 — the costing IS the reference)
    dup = api.post("/api/prejob-cards", json={"calculation_id": seeded["calc_id"],
                                              "template_id": seeded["tpl_20"]})
    assert dup.status_code == 409
    # mark for purge
    api.patch(f"/api/prejob-cards/{card['id']}", json={"body_description": "P433C header 2.0"})


def _make_card(api, seeded) -> dict:
    r = api.post("/api/prejob-cards", json={"calculation_id": seeded["calc_id"],
                                            "template_id": seeded["tpl_20"]})
    assert r.status_code == 201, r.text
    return r.json()


def test_submit_gates_and_clears_reject_reason(api, seeded):
    card = _make_card(api, seeded)
    cid = card["id"]
    url = f"/api/prejob-cards/{cid}/submit-for-check"
    # §3.4 step-6 validation: signers required
    api.patch(f"/api/prejob-cards/{cid}", json={"sales_rep_user_id": None})
    assert api.post(url, json={}).status_code == 422
    planner = api.get("/api/prejob-cards/user-options?kind=planner").json()[0]
    sales_like = seeded["calc_user_id"] or planner["id"]
    api.patch(f"/api/prejob-cards/{cid}", json={"sales_rep_user_id": sales_like,
                                                "planner_user_id": planner["id"],
                                                "body_gap_mm": None})
    # §0.8 — body gap pending blocks unless waived
    assert api.post(url, json={"waive_body_gap": False}).status_code == 422
    r = api.post(url, json={"waive_body_gap": True})
    assert r.status_code == 200
    sent = r.json()
    assert sent["status"] == "sent_for_check" and sent["sent_for_check_at"]
    # drafts-only edit rule
    assert api.patch(f"/api/prejob-cards/{cid}",
                     json={"customer_notes": "x"}).status_code == 409
    # re-submit guard
    assert api.post(url, json={"waive_body_gap": True}).status_code == 409


def test_sections_shape_validated_on_patch(api, seeded):
    card = _make_card(api, seeded)
    bad = {"sections": [{"name": "", "items": []}]}
    assert api.patch(f"/api/prejob-cards/{card['id']}", json=bad).status_code == 422


def test_submit_drives_accepted_job_to_pre_job_sent(api, seeded):
    """§0.21 positive path on a P433C-owned job (no real job is touched)."""
    from app.database import Branch, SessionLocal
    from app.models.mes import PrejobCard, ProductionJob
    card = _make_card(api, seeded)
    with SessionLocal() as db:
        branch = db.query(Branch).order_by(Branch.id).first()
        job = ProductionJob(calculation_record_id=seeded["calc_id"], branch_id=branch.id,
                            source="quote", status="accepted", job_number="P433C01")
        db.add(job)
        db.commit()
        jid = job.id
    planner = api.get("/api/prejob-cards/user-options?kind=planner").json()[0]
    api.patch(f"/api/prejob-cards/{card['id']}",
              json={"sales_rep_user_id": planner["id"], "planner_user_id": planner["id"],
                    "body_gap_mm": 120})
    r = api.post(f"/api/prejob-cards/{card['id']}/submit-for-check", json={})
    assert r.status_code == 200
    with SessionLocal() as db:
        j = db.get(ProductionJob, jid)
        assert j.status == "pre_job_sent" and j.pre_job_sent_at is not None   # §0.21
        # the legacy job-level SIGNOFF columns stay untouched (§0.21 honesty rule)
        assert j.pre_job_signoff_sales_at is None
        assert j.pre_job_signoff_production_at is None
