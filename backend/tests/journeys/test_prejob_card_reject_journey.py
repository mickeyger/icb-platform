"""WO v4.33 §3.7 — Pre-Job Card REJECT journey: admin (reject path back to draft, §0.14).

A sent_for_check card: admin rejects from the planner page with a reason → the page banner
shows "Back at draft — [planner check — admin] <reason>" and the sign-off action disappears
(card no longer sent_for_check). J433R* markers; purge at setup AND teardown.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from playwright.sync_api import Page, expect

from _common import admin_session, shot  # noqa: E402

T = 15_000
JOURNEY = "prejob_reject"


def _purge(db) -> None:
    from sqlalchemy import text
    db.execute(text("DELETE FROM icb_mes.prejob_cards WHERE body_description LIKE 'J433R%'"))
    db.execute(text("DELETE FROM icb_mes.prejob_templates WHERE name LIKE 'J433R%'"))
    db.commit()


@pytest.fixture()
def sent_card_id():
    from app.database import CalculationRecord, SessionLocal, User
    from app.models.mes import PrejobCard, PrejobTemplate, ProductionJob
    with SessionLocal() as db:
        _purge(db)
        taken = {j.calculation_record_id for j in db.query(ProductionJob)
                 .filter(ProductionJob.calculation_record_id.isnot(None)).all()}
        carded = {c.calculation_id for c in db.query(PrejobCard).all()}
        calc = (db.query(CalculationRecord)
                .filter(~CalculationRecord.id.in_((taken | carded) or {0}))
                .order_by(CalculationRecord.id).first())
        if calc is None:
            pytest.skip("no free calculation on this DB")
        admin = db.query(User).filter_by(username="admin").first()
        tpl = PrejobTemplate(name="J433R TPL", body_type="chiller", product_line="standard",
                             is_active=True,
                             sections=[{"name": "GRP SECTION", "items": [{"text": "Item"}]}],
                             created_by="j")
        db.add(tpl)
        db.flush()
        card = PrejobCard(calculation_id=calc.id, template_id=tpl.id,
                          body_description="J433R — Reject Journey Card",
                          sections=tpl.sections, body_gap_mm=100, body_gap_pending=False,
                          created_by_user_id=admin.id, sales_rep_user_id=admin.id,
                          planner_user_id=admin.id, status="sent_for_check",
                          sent_for_check_at=datetime.now(timezone.utc))
        db.add(card)
        db.commit()
        db.refresh(card)
        cid = card.id
    yield cid
    from app.database import SessionLocal as SL
    with SL() as db:
        _purge(db)


def test_admin_rejects_back_to_draft_with_reason(page: Page, sent_card_id) -> None:
    admin_session(page)
    # Wait for the SPA session bootstrap (the X-CSRF source) before any mutation —
    # the §3.7 CSRF race (see the signoff journey's note).
    with page.expect_response(lambda r: "/api/session" in r.url, timeout=30_000):
        page.goto(f"/mes-app/prejob/{sent_card_id}/signoff/planner")
    expect(page.get_by_test_id("prejob-reject-btn")).to_be_visible(timeout=T)
    page.get_by_test_id("prejob-reject-btn").click()
    reason = page.get_by_test_id("prejob-reject-reason")
    expect(reason).to_be_visible(timeout=T)
    reason.fill("Body gap unworkable on this chassis.")
    # no mid-modal screenshot (full_page shots scroll under the fixed modal — flake class);
    # instrumented click — a failing POST prints its error detail into the CI log.
    with page.expect_response(lambda r: "/reject/" in r.url, timeout=T) as ri:
        page.get_by_test_id("prejob-reject-confirm").click()
    assert ri.value.status == 200, f"reject failed HTTP {ri.value.status}: {ri.value.text()[:300]}"
    # §0.14 — back to draft; the page banner carries the prefixed reason; actions are gone.
    banner = page.get_by_text("Back at draft", exact=False)
    expect(banner).to_be_visible(timeout=T)
    expect(page.get_by_text("planner check — admin", exact=False)).to_be_visible(timeout=T)
    expect(page.get_by_text("Body gap unworkable", exact=False)).to_be_visible(timeout=T)
    expect(page.get_by_test_id("prejob-signoff-btn")).to_have_count(0)
    shot(page, "02-rejected-draft-banner", journey=JOURNEY)
