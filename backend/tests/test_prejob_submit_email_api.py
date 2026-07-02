"""v1.39.3 backport — Submit-for-Check server-side email auto-send.

On submit-for-check the service resolves the Sales Rep + Planner user emails (To) and the card's
cc_recipients (Cc) and hands them to notifications.send_email_multi — AFTER the commit, best-effort
so a mail failure never fails the submit. These tests monkeypatch send_email_multi to capture the
call (no real SMTP), asserting: resolved To recipients, cleaned CC, the log-and-continue contract
(a raising sender still yields 200 + sent_for_check), and the no-recipient no-op. P393E markers.
"""
import pytest


def _purge(db) -> None:
    from sqlalchemy import text
    db.execute(text("DELETE FROM icb_mes.prejob_cards WHERE body_description LIKE 'P393E%'"))
    db.execute(text("DELETE FROM icb_mes.chassis_records WHERE make LIKE 'P393E%'"))
    db.execute(text("DELETE FROM icb_mes.prejob_templates WHERE name LIKE 'P393E%'"))
    db.execute(text("DELETE FROM icb_costings.users WHERE username LIKE 'P393E%'"))
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
def signers():
    """Two real signer users with addresses (sales + planner)."""
    from app.database import SessionLocal, User
    from app.deps import pwd_context
    with SessionLocal() as db:
        s = User(username="P393E_sales", role="sales", email="sales@icecoldgrp.co.za",
                 password_hash=pwd_context.hash("x"))
        p = User(username="P393E_planner", role="planner", email="deon@icecoldgrp.co.za",
                 password_hash=pwd_context.hash("x"))
        db.add_all([s, p])
        db.commit()
        return {"sales_id": s.id, "planner_id": p.id,
                "sales_email": s.email, "planner_email": p.email}


@pytest.fixture
def draft(api, signers):
    """A submittable draft: template + calc, both signers assigned, body gap set, CC populated."""
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
        tpl = PrejobTemplate(name="P393E TPL", body_type="explosive", product_line="standard",
                             is_active=True, header_format="P393E Body",
                             sections=[{"name": "S", "items": [{"text": "row"}]}], created_by="t")
        db.add(tpl)
        db.commit()
        calc_id, tpl_id = calc.id, tpl.id
    r = client.post("/api/prejob-cards", json={"calculation_id": calc_id, "template_id": tpl_id})
    assert r.status_code == 201, r.text
    card = r.json()
    client.patch(f"/api/prejob-cards/{card['id']}",
                 json={"body_description": "P393E Body",
                       "sales_rep_user_id": signers["sales_id"],
                       "planner_user_id": signers["planner_id"],
                       "body_gap_mm": 120,
                       "cc_recipients": "planner@icecoldgrp.co.za, not-an-email, extra@icecoldgrp.co.za"})
    return card, signers


def _capture_send(app_mod, monkeypatch):
    calls = []
    from app.services import notifications
    monkeypatch.setattr(notifications, "send_email_multi",
                        lambda subject, body, to, cc=None: calls.append(
                            {"subject": subject, "body": body, "to": to, "cc": cc}) or True)
    return calls


def test_submit_sends_to_signers_and_cc(api, draft, monkeypatch, app_mod):
    client, _ = api
    card, s = draft
    calls = _capture_send(app_mod, monkeypatch)
    r = client.post(f"/api/prejob-cards/{card['id']}/submit-for-check", json={})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "sent_for_check"
    assert len(calls) == 1, "submit must trigger exactly one auto-send"
    sent = calls[0]
    assert sent["to"] == [s["sales_email"], s["planner_email"]]
    # CC: only email-shaped entries survive build_email's cleaner ('not-an-email' dropped)
    assert "planner@icecoldgrp.co.za" in sent["cc"]
    assert "extra@icecoldgrp.co.za" in sent["cc"]
    assert "not-an-email" not in sent["cc"]
    # Body reuses the mailto builder — the sign-off deep links are present
    assert f"/mes-app/prejob/{card['id']}/signoff/sales" in sent["body"]
    assert f"/mes-app/prejob/{card['id']}/signoff/planner" in sent["body"]


def test_submit_succeeds_when_send_raises(api, draft, monkeypatch, app_mod):
    """Log-and-continue (Phase-1): a mail failure must not fail the (committed) submit."""
    client, _ = api
    card, _s = draft
    from app.services import notifications

    def boom(*a, **k):
        raise RuntimeError("smtp exploded")
    monkeypatch.setattr(notifications, "send_email_multi", boom)
    r = client.post(f"/api/prejob-cards/{card['id']}/submit-for-check", json={})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "sent_for_check"


def test_submit_noop_when_no_addresses(api, signers, monkeypatch, app_mod):
    """Signers with no email + no CC → no send attempted (no crash)."""
    client, admin = api
    # a draft whose signers have blank emails and no CC
    from app.database import CalculationRecord, SessionLocal, User
    from app.models.mes import PrejobTemplate, ProductionJob
    with SessionLocal() as db:
        for uid in (signers["sales_id"], signers["planner_id"]):
            db.get(User, uid).email = ""
        db.commit()
        taken = {j.calculation_record_id for j in db.query(ProductionJob)
                 .filter(ProductionJob.calculation_record_id.isnot(None)).all()}
        calc = (db.query(CalculationRecord)
                .filter(~CalculationRecord.id.in_(taken or {0}))
                .order_by(CalculationRecord.id).first())
        if calc is None:
            pytest.skip("no job-free calculation on this DB")
        tpl = PrejobTemplate(name="P393E TPL2", body_type="explosive", product_line="standard",
                             is_active=True, header_format="P393E Body",
                             sections=[{"name": "S", "items": [{"text": "row"}]}], created_by="t")
        db.add(tpl)
        db.commit()
        calc_id, tpl_id = calc.id, tpl.id
    r = client.post("/api/prejob-cards", json={"calculation_id": calc_id, "template_id": tpl_id})
    card = r.json()
    client.patch(f"/api/prejob-cards/{card['id']}",
                 json={"body_description": "P393E Body", "sales_rep_user_id": signers["sales_id"],
                       "planner_user_id": signers["planner_id"], "body_gap_mm": 120})
    calls = _capture_send(app_mod, monkeypatch)
    r = client.post(f"/api/prejob-cards/{card['id']}/submit-for-check", json={})
    assert r.status_code == 200, r.text
    assert calls == [], "no resolvable addresses → send_email_multi must not be called"
