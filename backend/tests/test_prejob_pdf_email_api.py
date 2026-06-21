"""WO v4.33 §3.6 — PDF rendering + email content endpoints.

ONE renderer, two consumers: GET /{id}/pdf must return a real PDF of the CURRENT content;
submit-for-check must persist the records snapshot (pdf_file_id + file on disk); GET
/{id}/email must carry both click-to-signoff links + a mailto with NO recipient (users have
no email column — v4.34) and NO attachment pretence (§0.11 BA-corrected). P433P markers.
"""
import pytest


def _purge(db) -> None:
    from sqlalchemy import text
    # cards first (they reference chassis_record_id), then the linked test chassis, then templates.
    db.execute(text("DELETE FROM icb_mes.prejob_cards WHERE body_description LIKE 'P433P%'"))
    db.execute(text("DELETE FROM icb_mes.chassis_records WHERE make LIKE 'P433P%'"))
    db.execute(text("DELETE FROM icb_mes.prejob_templates WHERE name LIKE 'P433P%'"))
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
def card(api):
    client, admin = api
    from app.database import CalculationRecord, SessionLocal
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
            name="P433P TPL", body_type="explosive", product_line="standard", is_active=True,
            header_format="P433P GRP Explosive Body",
            sections=[{"name": "GRP SECTION",
                       "items": [{"text": "Solid rear", "note": "Rear will be solid panel"}]},
                      {"name": "FINISHING SECTION",
                       "items": [{"text": "Hazchem pack",
                                  "sub_items": ["Orange diamond", "Document box"]}]}],
            created_by="t")
        db.add(tpl)
        db.commit()
        calc_id, tpl_id = calc.id, tpl.id
    r = client.post("/api/prejob-cards", json={"calculation_id": calc_id, "template_id": tpl_id})
    assert r.status_code == 201, r.text
    c = r.json()
    client.patch(f"/api/prejob-cards/{c['id']}",
                 json={"body_description": "P433P GRP Explosive Body",
                       "sales_rep_user_id": admin.id, "planner_user_id": admin.id,
                       "body_gap_mm": 100})
    return c


def test_pdf_renders_current_content(api, card):
    client, _ = api
    r = client.get(f"/api/prejob-cards/{card['id']}/pdf")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/pdf"
    assert "prejob-" in r.headers["content-disposition"]
    assert r.content[:5] == b"%PDF-"
    assert len(r.content) > 1500                       # a real document, not a stub


def test_submit_persists_records_snapshot(api, card):
    client, _ = api
    from app.services.file_store import prejob_pdf_abspath
    r = client.post(f"/api/prejob-cards/{card['id']}/submit-for-check", json={})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "sent_for_check"
    assert body["pdf_file_id"], "submit must persist the records-copy PDF (§0.11)"
    path = prejob_pdf_abspath(body["pdf_file_id"])
    assert path.exists() and path.read_bytes()[:5] == b"%PDF-"


def test_email_payload_links_and_mailto(api, card):
    client, _ = api
    r = client.get(f"/api/prejob-cards/{card['id']}/email")
    assert r.status_code == 200
    e = r.json()
    assert f"/mes-app/prejob/{card['id']}/signoff/sales" in e["body"]
    assert f"/mes-app/prejob/{card['id']}/signoff/planner" in e["body"]
    assert e["mailto"].startswith("mailto:?subject=")  # blank recipient — no user emails yet
    assert "attach" not in e["mailto"].split("body=")[0]   # no attachment pretence (§0.11)
    assert "Pre-Job Card" in e["subject"]
    assert e["cc"] is None                                 # no CC set → no cc= param


def test_cc_recipients_persist_and_reach_mailto(api, card):
    """CC addition (migration 0019): stored raw on the draft; only email-shaped entries feed
    the &cc= param (the 'not-an-email' entry is filtered from the mailto, kept in storage)."""
    client, _ = api
    cid = card["id"]
    r = client.patch(f"/api/prejob-cards/{cid}",
                     json={"cc_recipients": "burt@icb.co.za, not-an-email, nadie@icb.co.za"})
    assert r.status_code == 200
    assert r.json()["cc_recipients"] == "burt@icb.co.za, not-an-email, nadie@icb.co.za"
    e = client.get(f"/api/prejob-cards/{cid}/email").json()
    assert e["cc"] == "burt@icb.co.za,nadie@icb.co.za"
    assert e["mailto"].startswith("mailto:?cc=")
    assert "burt%40icb.co.za" in e["mailto"] and "not-an-email" not in e["mailto"]


def test_summaries_carries_card_state_for_the_costings_list(api, card):
    """§0.21 — /summaries feeds the bulk supersede on the costings list surfaces (dashboard +
    Planning ack + detail panel): the card's calc id, status, and resolved signer usernames."""
    client, _ = api
    rows = client.get("/api/prejob-cards/summaries").json()
    mine = next((r for r in rows if r["id"] == card["id"]), None)
    assert mine, "summaries must include the created card"
    assert mine["calculation_id"] == card["calculation_id"]
    assert mine["status"] == "draft"
    assert mine["sales_rep_username"] == "admin" and mine["planner_username"] == "admin"
    assert mine["sales_rep_signoff_at"] is None and mine["planner_signoff_at"] is None


def test_summaries_surfaces_linked_chassis_vin_when_card_vin_is_blank(api, card):
    """WO — the Planning-ack panel back-fills + locks the VIN box from the LIVE linked
    chassis_records.vin. A VIN captured later on the Chassis page (chassis_page_manual) lands on
    chassis.vin but NOT on card.vin_number (propagation is forward-only), so /summaries must surface
    the chassis VIN DISTINCTLY from the attested vin_number — else the ack modal shows blank (the
    A32759 bug). Asserts: card.vin_number stays NULL, chassis_vin carries the linked chassis's VIN."""
    client, _ = api
    from app.database import SessionLocal
    from app.models.mes import ChassisRecord, PrejobCard
    test_vin = "P433PXX0000000001"  # 17 chars, strict-VIN charset (no I/O/Q), unique to this test
    with SessionLocal() as db:
        ch = ChassisRecord(make="P433P MAKE", model="X", vin=test_vin, status="expected",
                           source="manual", created_via="pre_job_card")
        db.add(ch)
        db.flush()
        c = db.get(PrejobCard, card["id"])
        c.chassis_record_id = ch.id      # link the chassis; leave card.vin_number NULL (the bug condition)
        db.commit()
    rows = client.get("/api/prejob-cards/summaries").json()
    mine = next((r for r in rows if r["id"] == card["id"]), None)
    assert mine, "summaries must include the created card"
    assert mine["vin_number"] is None, "card was never attested a VIN — vin_number stays NULL"
    assert mine["chassis_vin"] == test_vin, "the LIVE linked chassis VIN must surface for the ack back-fill+lock"
