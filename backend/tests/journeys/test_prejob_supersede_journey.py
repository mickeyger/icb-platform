"""WO v4.33 §0.21 — Costings detail page: a live Pre-Job Card SUPERSEDES the legacy job-level
sign-off widget. Regression guard for the pre-merge catch (two sign-off UIs for one card: the
new /signoff flow + the legacy production_jobs widget that the new flow never writes, so its
checkboxes could never tick).

ONE free calculation, toggled — proves BOTH directions on the same record:
  1. a `pre_job_sent` job with NO card → the LEGACY widget renders (backwards-compat: rows
     in-flight at the v4.33 cutover complete on the old path);
  2. add a sent_for_check prejob_cards row → reload → the NEW status panel renders and the
     legacy widget is GONE (the supersede).
J433D markers; purge at setup AND teardown.
"""
from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import quote as urlquote

import pytest
from playwright.sync_api import Page, expect

from _common import admin_session, shot  # noqa: E402

T = 15_000
JOURNEY = "prejob_supersede"


def _purge(db) -> None:
    from sqlalchemy import text
    db.execute(text("DELETE FROM icb_mes.prejob_cards WHERE body_description LIKE 'J433D%'"))
    db.execute(text("DELETE FROM icb_mes.prejob_templates WHERE name LIKE 'J433D%'"))
    db.execute(text("DELETE FROM icb_mes.production_jobs WHERE job_number LIKE 'J433D%'"))
    db.commit()


@pytest.fixture()
def staged():
    """A free calc given a `pre_job_sent` job (→ costing status 'Pre-Job Sent', the condition
    under which the legacy widget rendered) and a parked J433D template for the mid-test card."""
    from app.database import Branch, CalculationRecord, SessionLocal, User
    from app.models.mes import PrejobCard, PrejobTemplate, ProductionJob
    with SessionLocal() as db:
        _purge(db)
        taken = {j.calculation_record_id for j in db.query(ProductionJob)
                 .filter(ProductionJob.calculation_record_id.isnot(None)).all()}
        carded = {c.calculation_id for c in db.query(PrejobCard).all()}
        calc = (db.query(CalculationRecord)
                .filter(~CalculationRecord.id.in_((taken | carded) or {0}),
                        CalculationRecord.quote_number.isnot(None),
                        CalculationRecord.is_repair.is_(False))
                .order_by(CalculationRecord.id.desc()).first())
        if calc is None:
            pytest.skip("no job-free, card-free calculation on this DB")
        admin = db.query(User).filter_by(username="admin").first()
        branch = db.query(Branch).order_by(Branch.id).first()
        tpl = PrejobTemplate(name="J433D TPL", body_type="chiller", product_line="standard",
                             is_active=True,
                             sections=[{"name": "GRP SECTION", "items": [{"text": "Item"}]}],
                             created_by="j")
        db.add(tpl)
        db.add(ProductionJob(calculation_record_id=calc.id, branch_id=branch.id,
                             source="quote", status="pre_job_sent", job_number="J433D01",
                             pre_job_sent_at=datetime.now(timezone.utc)))
        db.commit()
        ctx = {"quote": calc.quote_number, "calc_id": calc.id,
               "tpl_id": tpl.id, "admin_id": admin.id}
    yield ctx
    from app.database import SessionLocal as SL
    with SL() as db:
        _purge(db)


def _add_card(ctx) -> None:
    from app.database import SessionLocal
    from app.models.mes import PrejobCard
    with SessionLocal() as db:
        db.add(PrejobCard(calculation_id=ctx["calc_id"], template_id=ctx["tpl_id"],
                          body_description="J433D — Supersede Journey Card",
                          sections=[{"name": "GRP SECTION", "items": [{"text": "Item"}]}],
                          body_gap_mm=100, body_gap_pending=False,
                          created_by_user_id=ctx["admin_id"], sales_rep_user_id=ctx["admin_id"],
                          planner_user_id=ctx["admin_id"], status="sent_for_check",
                          sent_for_check_at=datetime.now(timezone.utc)))
        db.commit()


def _open_detail(page: Page, quote: str) -> None:
    page.goto("/mes-app/costings")
    expect(page.get_by_test_id("costings-dashboard")).to_be_visible(timeout=T)
    page.goto(f"/mes-app/costings/{urlquote(quote, safe='')}")


def test_card_supersedes_legacy_signoff_widget(page: Page, staged) -> None:
    admin_session(page)

    # 1) No card yet → the legacy widget renders (backwards-compat), no new panel.
    _open_detail(page, staged["quote"])
    expect(page.get_by_test_id("prejob-legacy-signoff")).to_be_visible(timeout=T)
    expect(page.get_by_test_id("prejob-status-panel")).to_have_count(0)
    shot(page, "01-legacy-widget-no-card", journey=JOURNEY)

    # 2) Add a Pre-Job Card → reload → the new panel supersedes; the legacy widget is GONE.
    _add_card(staged)
    _open_detail(page, staged["quote"])
    expect(page.get_by_test_id("prejob-status-panel")).to_be_visible(timeout=T)
    expect(page.get_by_test_id("prejob-legacy-signoff")).to_have_count(0)
    expect(page.get_by_text("Sent for check", exact=False)).to_be_visible(timeout=T)
    expect(page.get_by_test_id("prejob-panel-view")).to_be_visible(timeout=T)
    shot(page, "02-card-supersedes-legacy", journey=JOURNEY)
