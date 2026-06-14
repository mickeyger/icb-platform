"""WO v4.33.1 §3.7 — admin Outstanding Pre-Job Sign-offs journey.

The new sidebar entry → the list of sent_for_check cards → a filter chip → a row deep-link into the
existing /prejob/{id}/signoff/{role} page. Admin-only surface (§0.4). J331O markers; purge at setup
AND teardown.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from playwright.sync_api import Page, expect

from _common import admin_session, shot  # noqa: E402

T = 15_000
JOURNEY = "outstanding_signoffs"


def _purge(db) -> None:
    from sqlalchemy import text
    db.execute(text("DELETE FROM icb_mes.prejob_cards WHERE body_description LIKE 'J331O%'"))
    db.execute(text("DELETE FROM icb_mes.prejob_templates WHERE name LIKE 'J331O%'"))
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
        tpl = PrejobTemplate(name="J331O TPL", body_type="chiller", product_line="standard",
                             is_active=True, sections=[{"name": "S", "items": [{"text": "x"}]}],
                             created_by="j331o")
        db.add(tpl)
        db.flush()
        card = PrejobCard(calculation_id=calc.id, template_id=tpl.id,
                          body_description="J331O — Outstanding Card", sections=tpl.sections,
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


def test_admin_outstanding_via_nav(page: Page, sent_card) -> None:
    admin_session(page)
    page.goto("/mes-app/admin/spec-options")              # land in the admin module
    nav = page.get_by_test_id("admin-nav-prejob-signoffs")
    expect(nav).to_be_visible(timeout=T)                  # the NEW sidebar entry
    with page.expect_response(lambda r: "/api/prejob-cards/outstanding" in r.url, timeout=T) as ri:
        nav.click()
    assert ri.value.status == 200, f"outstanding fetch returned {ri.value.status}"
    expect(page.get_by_test_id("outstanding-signoffs")).to_be_visible(timeout=T)
    row = page.locator(f"[data-testid=outstanding-row][data-id='{sent_card}']")
    expect(row).to_be_visible(timeout=T)
    shot(page, "01-outstanding-list", journey=JOURNEY)
    # filter: Both pending (the staged card has no sign-offs yet)
    page.get_by_test_id("outstanding-filter-both").click()
    expect(row).to_be_visible(timeout=T)
    # a row action opens the existing planner sign-off page
    page.get_by_test_id(f"outstanding-open-planner-{sent_card}").click()
    expect(page.get_by_test_id("prejob-signoff-page")).to_be_visible(timeout=T)
    shot(page, "02-row-to-signoff", journey=JOURNEY)
