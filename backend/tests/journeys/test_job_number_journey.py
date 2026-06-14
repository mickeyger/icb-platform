"""WO v4.34 §3.8 — job-number assignment journey (§3.5): the Planning Board shows the quote-derived
NUMERIC job number, and the Planning-ack override field is gated by role.

A staged pre_job_confirmed job (numeric job_number) appears as an 'Awaiting Planning ack' card on
the board, shown as "#<digits>" (proves the §3.5 numeric — no letter prefix / /MM/YYYY). admin +
planner (planning.acknowledge) open the ack panel and see the job-number override field pre-filled
with the numeric; sales (no permission) reaches the same card but the override field is gated off.
The extraction + override logic is unit-tested in test_job_number_strategy.py. Distinct numeric
marker; purge at setup AND teardown.
"""
from __future__ import annotations

import re

import pytest
from playwright.sync_api import Page, expect

from _common import admin_session, role_session, shot  # noqa: E402

T = 15_000
JOURNEY = "job_number"
JOB_NUMBER = "94343"        # distinctive numeric — proves §3.5 (no letter prefix, no /MM/YYYY)


def _purge(db) -> None:
    from sqlalchemy import text
    db.execute(text("DELETE FROM icb_mes.production_jobs WHERE job_number = :n"), {"n": JOB_NUMBER})
    db.commit()


@pytest.fixture(scope="module")
def staged():
    from app.database import Branch, CalculationRecord, SessionLocal
    from app.models.mes import PrejobCard, ProductionJob
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
        branch = db.query(Branch).order_by(Branch.id).first()
        db.add(ProductionJob(calculation_record_id=calc.id, branch_id=branch.id, source="quote",
                             status="pre_job_confirmed", job_number=JOB_NUMBER,
                             job_number_source="quote_derived"))
        db.commit()
    yield {"job_number": JOB_NUMBER}
    from app.database import SessionLocal as SL
    with SL() as db:
        _purge(db)


def _open_board(page: Page) -> None:
    nav = page.get_by_test_id("nav-planning")
    expect(nav).to_be_visible(timeout=T)
    nav.click()
    expect(page.get_by_role("heading", name="Planning Board")).to_be_visible(timeout=T)


def _ack_card(page: Page, job_number: str):
    # the awaiting-ack card shows "#<job_number>" (job_number_assigned = pj.job_number = numeric §3.5)
    card = page.locator("button", has_text=f"#{job_number}").first
    expect(card).to_be_visible(timeout=T)
    return card


def test_admin_sees_numeric_and_override(page: Page, staged) -> None:
    admin_session(page)
    _open_board(page)
    _ack_card(page, staged["job_number"]).click()         # numeric on the card proves §3.5 display
    field = page.get_by_test_id("planning-ack-job-number")
    expect(field).to_be_visible(timeout=T)
    assert re.fullmatch(r"\d+", field.input_value() or ""), \
        "the override field should pre-fill with the numeric job number"
    shot(page, "01-admin-override", journey=JOURNEY)


@pytest.mark.parametrize("role", ["planner", "sales"])
def test_per_role_override_gating(page: Page, live_server: str, role_users, staged, role: str) -> None:
    role_session(page, role_users[role], base=live_server)
    _open_board(page)
    _ack_card(page, staged["job_number"]).click()
    field = page.get_by_test_id("planning-ack-job-number")
    if role == "planner":
        expect(field).to_be_visible(timeout=T)            # planner CAN ack → override shown
    else:
        expect(field).to_have_count(0)                    # sales lacks planning.acknowledge → hidden
    shot(page, f"02-{role}-board", journey=JOURNEY)
