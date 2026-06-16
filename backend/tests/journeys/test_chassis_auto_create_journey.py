"""WO v4.34 §3.8 — chassis AUTO-CREATE journey (§3.2) + the §3.7 DDM dropdown / provenance pill.

Admin drives a Pre-Job submit, picking the chassis type from the DDM dropdown (no free-text); the
submit auto-creates an 'expected' chassis (§3.2) which then shows in the Chassis list under the
Expected filter with an "Auto · Pre-Job" provenance pill. Planner separately exercises +New (the
manual path → "Manual" provenance). Render + response-status style; the lifecycle depth lives in the
API suites (test_chassis_auto_create.py). J434A* markers; purge at setup AND teardown.
"""
from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect

from _common import admin_session, role_session, shot  # noqa: E402

T = 15_000
JOURNEY = "chassis_auto_create"
TPL_NAME = "J434A Journey Template"
CHASSIS_TYPE = "Isuzu FTR 850 AMT (MY22)"        # a seeded DDM entry (migration 0021)


def _purge(db) -> None:
    from sqlalchemy import text
    # Cards first (card→chassis is SET NULL, so they never block). Capture the auto-created chassis
    # ids off the J434A jobs BEFORE deleting the jobs (job→chassis is ON DELETE RESTRICT), then the
    # jobs, then those chassis + any manual J434A-VIN chassis, then the template.
    db.execute(text("DELETE FROM icb_mes.prejob_cards WHERE calculation_id IN "
                    "(SELECT calculation_record_id FROM icb_mes.production_jobs WHERE job_number LIKE 'J434A%')"))
    auto_ids = [r[0] for r in db.execute(text(
        "SELECT chassis_record_id FROM icb_mes.production_jobs "
        "WHERE job_number LIKE 'J434A%' AND chassis_record_id IS NOT NULL")).fetchall()]
    db.execute(text("DELETE FROM icb_mes.production_jobs WHERE job_number LIKE 'J434A%'"))
    if auto_ids:
        db.execute(text("DELETE FROM icb_mes.chassis_records WHERE id = ANY(:ids)"), {"ids": auto_ids})
    # The make-based fallback must NOT touch a job-linked (real) chassis — exclude any still
    # referenced by a production_job (ON DELETE RESTRICT). Our own auto-created rows were already
    # unlinked + deleted above via auto_ids.
    db.execute(text("DELETE FROM icb_mes.chassis_records WHERE (vin LIKE 'J434A%' OR "
                    "(created_via='pre_job_card' AND make=:mk AND status IN ('expected','expected_orphaned'))) "
                    "AND id NOT IN (SELECT chassis_record_id FROM icb_mes.production_jobs "
                    "WHERE chassis_record_id IS NOT NULL)"), {"mk": CHASSIS_TYPE})
    db.execute(text("DELETE FROM icb_mes.prejob_templates WHERE name LIKE 'J434A%'"))
    db.commit()


@pytest.fixture(scope="module")
def staged():
    from app.database import Branch, CalculationRecord, SessionLocal
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
        branch = db.query(Branch).order_by(Branch.id).first()
        db.add(PrejobTemplate(
            name=TPL_NAME, body_type="chiller", size_category="big", product_line="standard",
            is_active=True, created_by="j434a",
            header_format="{{external_length}}mm GRP Chiller — Chassis: {{chassis_make_model}}",
            sections=[{"name": "GRP SECTION", "items": [{"text": "Body build."}]}]))
        db.add(ProductionJob(calculation_record_id=calc.id, branch_id=branch.id, source="quote",
                             status="accepted", job_number="J434A01", job_number_source="quote_derived"))
        db.commit()
        quote = calc.quote_number
    yield {"quote": quote}
    from app.database import SessionLocal as SL
    with SL() as db:
        _purge(db)


def _open_modal(page: Page, quote: str) -> None:
    page.goto("/mes-app/costings")
    expect(page.get_by_test_id("costings-dashboard")).to_be_visible(timeout=T)
    row = page.locator("tr", has_text=quote).first
    expect(row).to_be_visible(timeout=T)
    row.get_by_role("button", name="Pre-Job Card").click()
    expect(page.get_by_test_id("prejob-card-modal")).to_be_visible(timeout=T)


def test_admin_submit_auto_creates_expected_chassis(page: Page, role_users, staged) -> None:
    # role_users seeds journey_sales / journey_planner so the signer dropdowns have ≥1 option
    # beyond the placeholder on CI's fresh DB (mirrors the create journey).
    admin_session(page)
    _open_modal(page, staged["quote"])
    page.get_by_test_id("prejob-template-select").select_option(label=TPL_NAME)
    page.get_by_test_id("prejob-create-draft").click()
    expect(page.get_by_test_id("prejob-modal-section").first).to_be_visible(timeout=T)
    # §3.7 — pick the chassis type from the DDM dropdown (was free-text). submit() saves the draft
    # first, so this persists and §3.2 reads it.
    chassis = page.get_by_test_id("prejob-chassis-make")
    expect(chassis).to_be_visible(timeout=T)
    chassis.select_option(label=CHASSIS_TYPE)
    page.get_by_test_id("prejob-sales-rep").select_option(index=1)
    page.get_by_test_id("prejob-planner").select_option(index=1)
    waive = page.get_by_test_id("prejob-waive-gap")
    if waive.count() > 0:
        waive.check()
    with page.expect_response(lambda r: "submit-for-check" in r.url, timeout=T) as ri:
        page.get_by_test_id("prejob-submit-check").click()
    assert ri.value.status == 200, f"submit failed HTTP {ri.value.status}: {ri.value.text()[:300]}"
    expect(page.get_by_test_id("prejob-status-banner")).to_be_visible(timeout=T)
    shot(page, "01-submit-auto-create", journey=JOURNEY)

    # §3.2 — the submit auto-created an 'expected' chassis carrying the DDM make. Locate its id.
    from app.database import SessionLocal
    from app.models.mes import ChassisRecord
    with SessionLocal() as db:
        ch = (db.query(ChassisRecord)
              .filter(ChassisRecord.created_via == "pre_job_card",
                      ChassisRecord.make == CHASSIS_TYPE, ChassisRecord.status == "expected")
              .order_by(ChassisRecord.id.desc()).first())
        assert ch is not None, "submit did not auto-create an 'expected' chassis"
        chassis_id = ch.id

    # §3.7 — it shows in the Chassis list under the Expected filter, with the Auto · Pre-Job pill.
    page.get_by_test_id("nav-chassis").click()
    expect(page.get_by_test_id("chassis-list")).to_be_visible(timeout=T)
    page.get_by_test_id("chassis-filter-expected").click()
    row = page.locator(f"[data-testid=chassis-row][data-id='{chassis_id}']")
    expect(row).to_be_visible(timeout=T)
    expect(row).to_contain_text("Auto")                 # the provenance pill (avoids the · glyph)
    shot(page, "02-chassis-expected", journey=JOURNEY)
    row.click()
    expect(page.get_by_test_id("chassis-detail")).to_be_visible(timeout=T)
    expect(page.get_by_test_id("chassis-detail")).to_contain_text("Auto")


def test_planner_creates_manual_chassis(page: Page, live_server: str, role_users, staged) -> None:
    """The +New manual path (planner) — make from the same DDM dropdown → 'Manual' provenance."""
    role_session(page, role_users["planner"], base=live_server)
    page.get_by_test_id("nav-chassis").click()
    expect(page.get_by_test_id("chassis-list")).to_be_visible(timeout=T)
    page.get_by_test_id("chassis-new").click()
    expect(page.get_by_test_id("chassis-create-form")).to_be_visible(timeout=T)
    page.get_by_test_id("chassis-create-vin").fill("J434AMANUAL000001")
    page.get_by_test_id("chassis-create-make").select_option(label=CHASSIS_TYPE)
    with page.expect_response(
            lambda r: r.url.endswith("/api/chassis-records") and r.request.method == "POST", timeout=T) as ri:
        page.get_by_test_id("chassis-create-save").click()
    assert ri.value.status == 201, f"create failed HTTP {ri.value.status}: {ri.value.text()[:300]}"
    page.get_by_test_id("chassis-search").fill("J434AMANUAL000001")
    page.wait_for_timeout(400)
    row = page.get_by_test_id("chassis-row").first
    expect(row).to_be_visible(timeout=T)
    expect(row).to_contain_text("Manual")
    shot(page, "03-manual-chassis", journey=JOURNEY)
