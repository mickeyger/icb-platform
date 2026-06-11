"""WO v4.33 §3.5 — sign-off + reject endpoints: the Stage B/C/D transitions.

Covers: both-signoffs auto-confirm (+ §0.21 job drive to pre_job_confirmed via STATUS columns
only — the legacy signoff columns stay NULL, the honesty assertion again), actual-signer
capture (§0.12 — the signer's id replaces the assigned one), double-sign 409, wrong-status
409s, §0.14 reject → draft + prefixed reason + sign-off reset, empty attestation/reason 422s.
P433S markers; self-healing purge; job-free + P433S-owned-job paths only.
"""
import pytest


def _purge(db) -> None:
    from sqlalchemy import text
    db.execute(text("DELETE FROM icb_mes.prejob_cards WHERE body_description LIKE 'P433S%'"))
    db.execute(text("DELETE FROM icb_mes.prejob_templates WHERE name LIKE 'P433S%'"))
    db.execute(text("DELETE FROM icb_mes.production_jobs WHERE job_number LIKE 'P433S%'"))
    db.commit()


@pytest.fixture(scope="module")
def app_mod():
    import app.main as m
    from starlette.testclient import TestClient
    with TestClient(m.app):
        yield m


@pytest.fixture
def api(app_mod):
    from app.database import SessionLocal, User
    from app.deps import require_user
    from starlette.testclient import TestClient
    with SessionLocal() as db:
        _purge(db)
        admin = db.query(User).filter_by(username="admin").first()
    app_mod.app.dependency_overrides[require_user] = lambda: admin
    with TestClient(app_mod.app) as c:
        yield c, admin
    app_mod.app.dependency_overrides.pop(require_user, None)
    with SessionLocal() as db:
        _purge(db)


@pytest.fixture
def sent_card(api):
    """A P433S card in sent_for_check, with a P433S 'accepted' job behind it (§0.21 path)."""
    client, admin = api
    from app.database import Branch, CalculationRecord, SessionLocal
    from app.models.mes import PrejobTemplate, ProductionJob
    with SessionLocal() as db:
        taken = {j.calculation_record_id for j in db.query(ProductionJob)
                 .filter(ProductionJob.calculation_record_id.isnot(None)).all()}
        calc = (db.query(CalculationRecord)
                .filter(~CalculationRecord.id.in_(taken or {0}))
                .order_by(CalculationRecord.id).first())
        if calc is None:
            pytest.skip("no job-free calculation on this DB")
        tpl = PrejobTemplate(
            name="P433S TPL", body_type="chiller", product_line="standard", is_active=True,
            header_format="P433S header",
            sections=[{"name": "GRP SECTION", "items": [{"text": "x"}]}], created_by="t")
        branch = db.query(Branch).order_by(Branch.id).first()
        job = ProductionJob(calculation_record_id=calc.id, branch_id=branch.id, source="quote",
                            status="accepted", job_number="P433S01")
        db.add_all([tpl, job])
        db.commit()
        calc_id, tpl_id, job_id = calc.id, tpl.id, job.id

    r = client.post("/api/prejob-cards", json={"calculation_id": calc_id, "template_id": tpl_id})
    assert r.status_code == 201, r.text
    card = r.json()
    client.patch(f"/api/prejob-cards/{card['id']}",
                 json={"body_description": "P433S header", "sales_rep_user_id": admin.id,
                       "planner_user_id": admin.id, "body_gap_mm": 150})
    r = client.post(f"/api/prejob-cards/{card['id']}/submit-for-check", json={})
    assert r.status_code == 200, r.text
    return {"card_id": card["id"], "job_id": job_id}


def test_both_signoffs_confirm_and_drive_job_status_only(api, sent_card):
    client, admin = api
    from app.database import SessionLocal
    from app.models.mes import ProductionJob
    cid = sent_card["card_id"]
    # empty attestation 422
    assert client.post(f"/api/prejob-cards/{cid}/signoff/sales",
                       json={"attestation": "  "}).status_code == 422
    r = client.post(f"/api/prejob-cards/{cid}/signoff/sales",
                    json={"attestation": "Commercial spec matches the sale."})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "sent_for_check"            # one of two
    assert body["sales_rep_username"] == "admin"         # §0.12 — ACTUAL signer captured
    # double-sign 409
    assert client.post(f"/api/prejob-cards/{cid}/signoff/sales",
                       json={"attestation": "again"}).status_code == 409
    r = client.post(f"/api/prejob-cards/{cid}/signoff/planner",
                    json={"attestation": "Feasible — gap workable, slot bookable."})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "pre_job_confirmed"         # Stage D auto-flip
    with SessionLocal() as db:
        j = db.get(ProductionJob, sent_card["job_id"])
        assert j.status == "pre_job_confirmed" and j.pre_job_confirmed_at is not None  # §0.21
        assert j.pre_job_signoff_sales_at is None        # honesty: signoff columns untouched
        assert j.pre_job_signoff_production_at is None
    # signing a confirmed card 409s
    assert client.post(f"/api/prejob-cards/{cid}/signoff/planner",
                       json={"attestation": "late"}).status_code == 409


def test_reject_returns_to_draft_with_reason_and_resets(api, sent_card):
    client, admin = api
    cid = sent_card["card_id"]
    client.post(f"/api/prejob-cards/{cid}/signoff/sales", json={"attestation": "ok"})
    # empty reason 422
    assert client.post(f"/api/prejob-cards/{cid}/reject/planner",
                       json={"reason": ""}).status_code == 422
    r = client.post(f"/api/prejob-cards/{cid}/reject/planner",
                    json={"reason": "Body gap unworkable on this chassis"})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "draft"                     # §0.14
    assert "planner check — admin" in body["reject_reason"]
    assert "Body gap unworkable" in body["reject_reason"]
    assert body["sales_rep_signoff_at"] is None          # earlier sign-off reset — both re-check
    assert body["sent_for_check_at"] is None
    # reject on a draft 409s
    assert client.post(f"/api/prejob-cards/{cid}/reject/planner",
                       json={"reason": "x"}).status_code == 409
    # re-submit clears the reason (§0.14 round-trip)
    r = client.post(f"/api/prejob-cards/{cid}/submit-for-check", json={})
    assert r.status_code == 200 and r.json()["reject_reason"] is None
