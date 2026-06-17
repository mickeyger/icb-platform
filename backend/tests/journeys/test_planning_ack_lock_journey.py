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
LOCKED_JOB = "94350"        # card attests make + VIN → both lock read-only
VINOPEN_JOB = "94351"       # card attests make, NO VIN → type locks, VIN editable (the §3.9 refine)
CHASSIS = "Hino 300 815"    # a seeded DDM entry (migration 0021)
ATTESTED_VIN = "J434DVN0000000001"   # WO v4.36a — conformant 17-char ISO-3779 (was 'J434DVIN00001')


def _purge(db) -> None:
    from sqlalchemy import text
    db.execute(text("DELETE FROM icb_mes.prejob_cards WHERE body_description LIKE 'J434D%'"))
    db.execute(text("DELETE FROM icb_mes.production_jobs WHERE job_number IN (:a, :b)"),
               {"a": LOCKED_JOB, "b": VINOPEN_JOB})
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
        full_calc, vinopen_calc = free[0], free[1]
        # FULLY-ATTESTED path — card with make AND VIN → both lock read-only at ack.
        db.add(ProductionJob(calculation_record_id=full_calc.id, branch_id=branch.id, source="quote",
                             status="pre_job_confirmed", job_number=LOCKED_JOB,
                             job_number_source="quote_derived"))
        db.add(PrejobCard(calculation_id=full_calc.id, template_id=tpl.id,
                          body_description="J434D — Attested Card", sections=tpl.sections,
                          chassis_make_model=CHASSIS, vin_number=ATTESTED_VIN, body_gap_mm=100,
                          body_gap_pending=False, created_by_user_id=admin.id,
                          sales_rep_user_id=admin.id, planner_user_id=admin.id,
                          status="pre_job_confirmed"))
        # VIN-OPEN path — card with make but NO VIN → type locks, VIN stays editable (capture at ack).
        db.add(ProductionJob(calculation_record_id=vinopen_calc.id, branch_id=branch.id, source="quote",
                             status="pre_job_confirmed", job_number=VINOPEN_JOB,
                             job_number_source="quote_derived"))
        db.add(PrejobCard(calculation_id=vinopen_calc.id, template_id=tpl.id,
                          body_description="J434D — Make-only Card", sections=tpl.sections,
                          chassis_make_model=CHASSIS, body_gap_mm=100, body_gap_pending=False,
                          created_by_user_id=admin.id, sales_rep_user_id=admin.id,
                          planner_user_id=admin.id, status="pre_job_confirmed"))
        db.commit()
    yield {"full": LOCKED_JOB, "vinopen": VINOPEN_JOB}
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


def test_attested_make_and_vin_both_lock(page: Page, staged) -> None:
    admin_session(page)
    _open_ack(page, staged["full"])
    # §3.9 — make AND VIN attested at pre-job ⇒ both read-only, editable controls gone.
    locked = page.get_by_test_id("planning-ack-chassis-locked")
    expect(locked).to_be_visible(timeout=T)
    expect(locked).to_contain_text(CHASSIS)
    vinlock = page.get_by_test_id("planning-ack-vin-locked")
    expect(vinlock).to_be_visible(timeout=T)
    expect(vinlock).to_contain_text(ATTESTED_VIN)
    expect(page.get_by_test_id("planning-ack-chassis-model")).to_have_count(0)
    expect(page.get_by_test_id("planning-ack-vin")).to_have_count(0)
    shot(page, "01-both-locked", journey=JOURNEY)


def test_blank_vin_editable_despite_type_lock(page: Page, staged) -> None:
    admin_session(page)
    _open_ack(page, staged["vinopen"])
    # §3.9 refine — make attested (type locks) but NO VIN on the card ⇒ VIN stays editable for capture.
    expect(page.get_by_test_id("planning-ack-chassis-locked")).to_be_visible(timeout=T)
    expect(page.get_by_test_id("planning-ack-vin")).to_be_visible(timeout=T)
    expect(page.get_by_test_id("planning-ack-vin-locked")).to_have_count(0)
    shot(page, "02-vin-editable", journey=JOURNEY)
