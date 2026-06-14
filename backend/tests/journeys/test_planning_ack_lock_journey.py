"""WO v4.34 §3.9 — Planning-ack chassis LOCK-DOWN journey (sign-off integrity).

When the linked Pre-Job Card is CONFIRMED with a chassis supplied, the Planning-ack chassis_type +
VIN lock read-only — the attested spec is the source of truth, so a planner can't silently rewrite
what Sales + Production already signed off (ADR 0020 footnote 9, applied to a new surface). With no
such card the fields stay editable. Two staged ack candidates cover both paths. J434D* markers;
purge at setup AND teardown.
"""
from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect

from _common import admin_session, shot  # noqa: E402

T = 15_000
JOURNEY = "prejob_ack_lock"
LOCKED_JOB = "94350"
OPEN_JOB = "94351"
CHASSIS = "Hino 300 815"        # a seeded DDM entry (migration 0021)


def _purge(db) -> None:
    from sqlalchemy import text
    db.execute(text("DELETE FROM icb_mes.prejob_cards WHERE body_description LIKE 'J434D%'"))
    db.execute(text("DELETE FROM icb_mes.production_jobs WHERE job_number IN (:a, :b)"),
               {"a": LOCKED_JOB, "b": OPEN_JOB})
    db.execute(text("DELETE FROM icb_mes.prejob_templates WHERE name LIKE 'J434D%'"))
    db.commit()


@pytest.fixture(scope="module")
def staged():
    from app.database import Branch, CalculationRecord, SessionLocal, User
    from app.models.mes import PrejobCard, PrejobTemplate, ProductionJob
    with SessionLocal() as db:
        _purge(db)
        taken = {j.calculation_record_id for j in db.query(ProductionJob)
                 .filter(ProductionJob.calculation_record_id.isnot(None)).all()}
        carded = {c.calculation_id for c in db.query(PrejobCard).all()}
        free = (db.query(CalculationRecord)
                .filter(~CalculationRecord.id.in_((taken | carded) or {0}),
                        CalculationRecord.quote_number.isnot(None),
                        CalculationRecord.is_repair.is_(False))   # repairs route differently on the board
                .order_by(CalculationRecord.id.desc()).limit(2).all())
        if len(free) < 2:
            pytest.skip("need two job-free, card-free calculations on this DB")
        branch = db.query(Branch).order_by(Branch.id).first()
        admin = db.query(User).filter_by(username="admin").first()
        tpl = PrejobTemplate(name="J434D TPL", body_type="chiller", product_line="standard",
                             is_active=True, sections=[{"name": "S", "items": [{"text": "x"}]}],
                             created_by="j434d")
        db.add(tpl)
        db.flush()
        locked_calc, open_calc = free[0], free[1]
        # LOCKED path — a pre_job_confirmed job + a CONFIRMED card carrying the attested chassis.
        db.add(ProductionJob(calculation_record_id=locked_calc.id, branch_id=branch.id, source="quote",
                             status="pre_job_confirmed", job_number=LOCKED_JOB,
                             job_number_source="quote_derived"))
        db.add(PrejobCard(calculation_id=locked_calc.id, template_id=tpl.id,
                          body_description="J434D — Locked Card", sections=tpl.sections,
                          chassis_make_model=CHASSIS, body_gap_mm=100, body_gap_pending=False,
                          created_by_user_id=admin.id, sales_rep_user_id=admin.id,
                          planner_user_id=admin.id, status="pre_job_confirmed"))
        # OPEN path — a pre_job_confirmed job, NO card → chassis fields stay editable.
        db.add(ProductionJob(calculation_record_id=open_calc.id, branch_id=branch.id, source="quote",
                             status="pre_job_confirmed", job_number=OPEN_JOB,
                             job_number_source="quote_derived"))
        db.commit()
    yield {"locked": LOCKED_JOB, "open": OPEN_JOB}
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


def test_confirmed_chassis_locks_type_and_vin(page: Page, staged) -> None:
    admin_session(page)
    _open_ack(page, staged["locked"])
    # §3.9 — attested chassis ⇒ read-only display, the editable control is gone.
    locked = page.get_by_test_id("planning-ack-chassis-locked")
    expect(locked).to_be_visible(timeout=T)
    expect(locked).to_contain_text(CHASSIS)
    expect(page.get_by_test_id("planning-ack-vin-locked")).to_be_visible(timeout=T)
    expect(page.get_by_test_id("planning-ack-chassis-model")).to_have_count(0)
    shot(page, "01-locked", journey=JOURNEY)


def test_no_card_keeps_chassis_editable(page: Page, staged) -> None:
    admin_session(page)
    _open_ack(page, staged["open"])
    # no confirmed card ⇒ the editable DDM control + VIN input remain.
    expect(page.get_by_test_id("planning-ack-chassis-model")).to_be_visible(timeout=T)
    expect(page.get_by_test_id("planning-ack-chassis-locked")).to_have_count(0)
    shot(page, "02-editable", journey=JOURNEY)
