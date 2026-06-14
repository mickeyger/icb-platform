"""WO v4.33.1 §3.7 — attestation modal enhancement journey.

The §3.2 sign-off modal: interpolated boilerplate (name + role + quote), a REQUIRED checkbox that
gates the Sign off button, and an optional notes box. Confirms the gating + that the persisted
attestation is the boilerplate WITH the notes appended (audit trail). J331A markers.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from playwright.sync_api import Page, expect

from _common import admin_session, shot  # noqa: E402

T = 15_000
JOURNEY = "attestation_modal"


def _purge(db) -> None:
    from sqlalchemy import text
    db.execute(text("DELETE FROM icb_mes.prejob_cards WHERE body_description LIKE 'J331A%'"))
    db.execute(text("DELETE FROM icb_mes.prejob_templates WHERE name LIKE 'J331A%'"))
    db.commit()


@pytest.fixture()
def sent_card():
    from app.database import CalculationRecord, SessionLocal, User
    from app.models.mes import PrejobCard, PrejobTemplate, ProductionJob
    with SessionLocal() as db:
        _purge(db)
        taken = {j.calculation_record_id for j in db.query(ProductionJob)
                 .filter(ProductionJob.calculation_record_id.isnot(None)).all()}
        carded = {c.calculation_id for c in db.query(PrejobCard).all()}
        calc = (db.query(CalculationRecord)
                .filter(~CalculationRecord.id.in_((taken | carded) or {0}),
                        CalculationRecord.quote_number.isnot(None))
                .order_by(CalculationRecord.id.desc()).first())
        if calc is None:
            pytest.skip("no free calculation on this DB")
        admin = db.query(User).filter_by(username="admin").first()
        tpl = PrejobTemplate(name="J331A TPL", body_type="chiller", product_line="standard",
                             is_active=True, sections=[{"name": "S", "items": [{"text": "x"}]}],
                             created_by="j331a")
        db.add(tpl)
        db.flush()
        card = PrejobCard(calculation_id=calc.id, template_id=tpl.id,
                          body_description="J331A — Attestation Card", sections=tpl.sections,
                          body_gap_mm=100, body_gap_pending=False, created_by_user_id=admin.id,
                          sales_rep_user_id=admin.id, planner_user_id=admin.id,
                          status="sent_for_check", sent_for_check_at=datetime.now(timezone.utc))
        db.add(card)
        db.commit()
        db.refresh(card)
        cid = card.id
    yield cid
    from app.database import SessionLocal as SL
    with SL() as db:
        _purge(db)


def test_checkbox_gates_signoff_and_attestation_persists(page: Page, sent_card) -> None:
    admin_session(page)
    with page.expect_response(lambda r: "/api/session" in r.url, timeout=30_000):
        page.goto(f"/mes-app/prejob/{sent_card}/signoff/planner")
    expect(page.get_by_test_id("prejob-signoff-page")).to_be_visible(timeout=T)
    page.get_by_test_id("prejob-signoff-btn").click()

    # §3.2 — interpolated boilerplate (role label present), and the Sign off button is gated.
    boiler = page.get_by_test_id("prejob-attestation-boilerplate")
    expect(boiler).to_be_visible(timeout=T)
    expect(boiler).to_contain_text("Planner")             # role interpolated
    expect(boiler).to_contain_text("verify the specifications")
    confirm = page.get_by_test_id("prejob-attestation-confirm")
    expect(confirm).to_be_disabled()                      # disabled until the checkbox is ticked
    page.get_by_test_id("prejob-attestation-checkbox").check()
    expect(confirm).to_be_enabled()
    page.get_by_test_id("prejob-attestation").fill("Feasibility confirmed — chassis fits.")
    shot(page, "01-attestation-modal", journey=JOURNEY)
    with page.expect_response(lambda r: "/signoff/" in r.url and r.request.method == "POST",
                              timeout=T) as ri:
        confirm.click()
    assert ri.value.status == 200, f"signoff failed HTTP {ri.value.status}: {ri.value.text()[:300]}"
    expect(page.get_by_text("Your Planner sign-off is in", exact=False)).to_be_visible(timeout=T)

    # The persisted attestation is the boilerplate WITH the notes appended.
    from app.database import SessionLocal
    from app.models.mes import PrejobCard
    with SessionLocal() as db:
        att = db.get(PrejobCard, sent_card).planner_attestation or ""
    assert "verify the specifications are true and correct" in att   # boilerplate stored
    assert "Feasibility confirmed — chassis fits." in att            # notes appended
