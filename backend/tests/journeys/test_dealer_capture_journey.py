"""WO v4.34.1 §3.6 — dealer capture at Planning ack (journey).

A planner (and admin) opens an ack candidate and sees the structured dealer dropdown (replacing the
old free-text field), populated from the is_dealer customers, and picks one. Dealer→chassis
propagation itself is covered by the backend (record_planning_ack + test_production_jobs_api); this
journey proves the §3.3 UI surface is wired and selectable. J341D markers; purge at setup + teardown.
"""
from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect

from _common import admin_session, role_session, shot  # noqa: E402

T = 15_000
JOURNEY = "dealer_capture"
JOB = "94341"
DEALER_NAME = "J341D Dealer Co"


def _purge(db) -> None:
    from sqlalchemy import text
    db.execute(text("DELETE FROM icb_mes.prejob_cards WHERE body_description LIKE 'J341D%'"))
    db.execute(text("DELETE FROM icb_mes.production_jobs WHERE job_number = :j"), {"j": JOB})
    db.execute(text("DELETE FROM icb_mes.prejob_templates WHERE name LIKE 'J341D%'"))
    db.execute(text("DELETE FROM icb_costings.customers WHERE name LIKE 'J341D%'"))
    db.commit()


@pytest.fixture(scope="module")
def staged():
    from app.database import Branch, CalculationRecord, Customer, SessionLocal, User
    from app.models.mes import PrejobCard, PrejobTemplate, ProductionJob
    with SessionLocal() as db:
        _purge(db)
        dealer = Customer(name=DEALER_NAME, bp_code="J341D001", is_active=True, is_dealer=True)
        db.add(dealer)
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
        branch = db.query(Branch).order_by(Branch.id).first()
        admin = db.query(User).filter_by(username="admin").first()
        tpl = PrejobTemplate(name="J341D TPL", body_type="chiller", product_line="standard",
                             is_active=True, sections=[{"name": "S", "items": [{"text": "x"}]}],
                             created_by="j341d")
        db.add(tpl)
        db.flush()
        db.add(ProductionJob(calculation_record_id=calc.id, branch_id=branch.id, source="quote",
                             status="pre_job_confirmed", job_number=JOB, job_number_source="quote_derived"))
        db.add(PrejobCard(calculation_id=calc.id, template_id=tpl.id,
                          body_description="J341D — Dealer Card", sections=tpl.sections,
                          chassis_make_model="Hino 300 815", body_gap_mm=100, body_gap_pending=False,
                          created_by_user_id=admin.id, sales_rep_user_id=admin.id,
                          planner_user_id=admin.id, status="pre_job_confirmed"))
        db.commit()
    yield {"job": JOB, "dealer": DEALER_NAME}
    from app.database import SessionLocal as SL
    with SL() as db:
        _purge(db)


def _open_ack(page: Page, job_number: str) -> None:
    nav = page.get_by_test_id("nav-planning")
    expect(nav).to_be_visible(timeout=T)
    nav.click()
    expect(page.get_by_role("heading", name="Planning Board")).to_be_visible(timeout=T)
    card = page.locator("button", has_text=f"#{job_number}").first
    expect(card).to_be_visible(timeout=T)
    card.click()


def _assert_dealer_dropdown(page: Page, dealer_name: str) -> None:
    dd = page.get_by_test_id("planning-ack-dealer")
    expect(dd).to_be_visible(timeout=T)
    expect(dd.locator("option", has_text=dealer_name)).to_have_count(1, timeout=T)   # is_dealer customer listed
    dd.select_option(label=dealer_name)
    shot(page, "01-dealer-selected", journey=JOURNEY)


def test_planner_picks_dealer(page: Page, live_server: str, role_users, staged) -> None:
    role_session(page, role_users["planner"], base=live_server)
    _open_ack(page, staged["job"])
    _assert_dealer_dropdown(page, staged["dealer"])


def test_admin_picks_dealer(page: Page, staged) -> None:
    admin_session(page)
    _open_ack(page, staged["job"])
    _assert_dealer_dropdown(page, staged["dealer"])
