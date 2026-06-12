"""WO v4.33 §3.7 — Pre-Job Card CREATE journey: admin + sales (Internal Sales lens).

Costings row → "Pre-Job Card" button → the §3.4 preview modal: template suggested, draft
created with the CORE TOKENS BAKED (External-dimensions line carries real mm — no {{tokens}}
left in the dims text), fridge dropdown live-substitutes the GRP provision line, signers
selected, Submit for Check (with the §0.8 waiver when Body Gap is pending) → toast + status.
Render-assertion style; the lifecycle depth lives in the API suites. J433C* markers, purge at
setup AND teardown. NOTE: submit auto-opens a mailto: draft — headless chromium drops the
unhandled protocol and stays on-page (asserted via the surviving toast/banner).
"""
from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect

from _common import admin_session, role_session, shot  # noqa: E402

T = 15_000
JOURNEY = "prejob_create"


def _purge(db) -> None:
    from sqlalchemy import text
    db.execute(text("DELETE FROM icb_mes.prejob_cards WHERE calculation_id IN "
                    "(SELECT calculation_record_id FROM icb_mes.production_jobs "
                    " WHERE job_number LIKE 'J433C%')"))
    db.execute(text("DELETE FROM icb_mes.production_jobs WHERE job_number LIKE 'J433C%'"))
    db.commit()


@pytest.fixture(scope="module")
def staged():
    """A job-free, card-free calculation given a J433C 'accepted' job — the live Costings row
    then shows the Pre-Job Card button (the v4.19 partial-state rule). Yields the quote."""
    from app.database import Branch, CalculationRecord, SessionLocal
    from app.models.mes import PrejobCard, ProductionJob
    with SessionLocal() as db:
        _purge(db)
        taken = {j.calculation_record_id for j in db.query(ProductionJob)
                 .filter(ProductionJob.calculation_record_id.isnot(None)).all()}
        carded = {c.calculation_id for c in db.query(PrejobCard).all()}
        calc = (db.query(CalculationRecord)
                .filter(~CalculationRecord.id.in_((taken | carded) or {0}),
                        CalculationRecord.quote_number.isnot(None),
                        CalculationRecord.is_repair.is_(False))   # repairs skip pre-job (§0)
                .order_by(CalculationRecord.id.desc()).first())
        if calc is None:
            pytest.skip("no job-free, card-free calculation on this DB")
        branch = db.query(Branch).order_by(Branch.id).first()
        job = ProductionJob(calculation_record_id=calc.id, branch_id=branch.id,
                            source="quote", status="accepted", job_number="J433C01")
        db.add(job)
        db.commit()
        quote = calc.quote_number
    yield quote
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


def test_sales_creates_draft(page: Page, live_server: str, role_users, staged) -> None:
    """Stage A through the TRUE §0.3 lens: Internal Sales (sales role, prejob.create from
    0017) picks the suggested template, creates the draft, sees the CORE TOKENS BAKED, and
    saves. Runs FIRST — the admin test then completes the same card."""
    role_session(page, role_users["sales"], base=live_server)
    _open_modal(page, staged)
    sel = page.get_by_test_id("prejob-template-select")
    expect(sel).to_be_visible(timeout=T)
    assert sel.input_value() != "", "suggested template should be pre-selected (§0.6)"
    page.get_by_test_id("prejob-create-draft").click()
    expect(page.get_by_test_id("prejob-modal-section").first).to_be_visible(timeout=T)
    dims = page.get_by_test_id("prejob-modal-section").first.locator("input").first
    assert "{{" not in (dims.input_value() or ""), "core tokens must bake at creation"
    page.get_by_test_id("prejob-save-draft").click()
    expect(page.get_by_text("Draft saved", exact=False)).to_be_visible(timeout=T)
    shot(page, "01-sales-draft", journey=JOURNEY)


def test_admin_completes_and_submits(page: Page, role_users, staged) -> None:
    """Admin re-opens the sales-created draft, drives fridge live-substitution + signers,
    submits (with the §0.8 waiver when the gap is pending) → status banner."""
    admin_session(page)
    _open_modal(page, staged)
    expect(page.get_by_test_id("prejob-modal-section").first).to_be_visible(timeout=T)
    # Step 4 — fridge dropdown live-substitutes the provision line.
    page.get_by_text("ICB orders", exact=False).click()
    fridge = page.get_by_test_id("prejob-fridge-select")
    expect(fridge).to_be_visible(timeout=T)
    fridge.select_option(label="Transfrig KV 760i · cutout 1250×325")
    assert fridge.input_value() == "Transfrig KV 760i"
    # Section items render as <input value=…> — get_by_text can't see input VALUES, so
    # assert on them directly: the fridge token is consumed wherever the template had one.
    values = page.locator("[data-testid=prejob-modal-section] input").evaluate_all(
        "els => els.map(e => e.value)")
    assert not any("{{fridge_make}}" in v for v in values), \
        "fridge token must be live-substituted on selection"
    # Step 6 — signers (journey_sales exists via role_users; planner list includes admin).
    page.get_by_test_id("prejob-sales-rep").select_option(index=1)
    page.get_by_test_id("prejob-planner").select_option(index=1)
    # Step 7 — submit (waive the gap when pending).
    waive = page.get_by_test_id("prejob-waive-gap")
    if waive.count() > 0:
        waive.check()
    page.get_by_test_id("prejob-submit-check").click()
    expect(page.get_by_test_id("prejob-status-banner")).to_be_visible(timeout=T)
    shot(page, "02-admin-submitted", journey=JOURNEY)
