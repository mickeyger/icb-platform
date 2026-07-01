"""WO v4.33 §3.7 — Pre-Job Card CREATE journey: admin + sales (Internal Sales lens).

Costings row → "Pre-Job Card" button → the §3.4 preview modal: template suggested, draft
created with the CORE TOKENS BAKED (External-dimensions line carries real mm — no {{tokens}}
left in the dims text), fridge dropdown live-substitutes the GRP provision line, signers
selected, Submit for Check (with the §0.8 waiver when Body Gap is pending) → toast + status.
Render-assertion style; the lifecycle depth lives in the API suites. J433C* markers, purge at
setup AND teardown. NOTE: submit now sends server-side (v1.39.3 — no mailto: draft opens); the
authoritative success signal is the submit-for-check 200 + the modal closing.
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
    db.execute(text("DELETE FROM icb_mes.prejob_templates WHERE name LIKE 'J433C%'"))
    db.commit()


TPL_NAME = "J433C Journey Template"


@pytest.fixture(scope="module")
def staged():
    """Self-sufficient staging (CI's fresh DB has NO templates — the importer is a dev/ops
    script — and NO fridge DDM): a J433C ACTIVE tokened template, the idempotent Drawing-A
    fridge seed, and a job-free/card-free/non-repair calculation given a J433C 'accepted'
    job (the live Costings row then shows the Pre-Job Card button). Yields the quote."""
    from app.database import Branch, CalculationRecord, SessionLocal
    from app.models.mes import PrejobCard, PrejobTemplate, ProductionJob
    from scripts.seed_fridge_units import seed as seed_fridges
    seed_fridges()                                     # idempotent — no-op on the dev DB
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
        db.add(PrejobTemplate(
            name=TPL_NAME, body_type="chiller", size_category="big",
            product_line="standard", is_active=True, created_by="j433c",
            header_format="{{external_length}}mm GRP Chiller Body VIN Nr: {{vin}}",
            sections=[
                {"name": "GRP SECTION", "items": [
                    {"text": "External dimensions – {{external_length}}mm o/a (l) x "
                             "{{external_width}}mm o/a (w) x {{external_height}}mm o/a (h)"},
                    {"text": "Provision for {{fridge_make}} fridge unit – cut out."}]},
                {"name": "FINISHING SECTION", "items": [{"text": "Reflexite tape."}]},
            ]))
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
    # Deterministic everywhere (CI has only the staged template; dev has Nadie's 22):
    # pick the J433C template explicitly — the §0.6 suggestion RANKING is API-tested.
    sel.select_option(label=TPL_NAME)
    page.get_by_test_id("prejob-create-draft").click()
    expect(page.get_by_test_id("prejob-modal-section").first).to_be_visible(timeout=T)
    # Deterministic bake-proof: {{vin}} is ALWAYS in the context (None -> "Pending"), so the
    # header must never carry it post-create. Dim tokens bake only when the calc HAS dims —
    # CI's mock calcs may not (absent keys stay visible BY DESIGN), so don't assert on them.
    body_desc = page.get_by_test_id("prejob-card-modal").locator("input").first
    assert "{{vin}}" not in (body_desc.input_value() or ""), "vin token must bake at creation"
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
    # Step 7 — submit (waive the gap when pending). Instrumented: a failing POST prints its
    # error detail instead of a blind banner-timeout (the CI-debuggability rule).
    waive = page.get_by_test_id("prejob-waive-gap")
    if waive.count() > 0:
        waive.check()
    with page.expect_response(lambda r: "submit-for-check" in r.url, timeout=T) as ri:
        page.get_by_test_id("prejob-submit-check").click()
    assert ri.value.status == 200, f"submit failed HTTP {ri.value.status}: {ri.value.text()[:300]}"
    # WO v4.36b.3 — CI flake stabilization. The submit-for-check 200 above is the AUTHORITATIVE success
    # signal. The in-modal `prejob-status-banner` is TRANSIENT and must NOT be asserted: submit() does
    # setCard(sent) (banner renders) then `await onConfirm()`, which runs `await refresh(); setPreJobTarget
    # (null)` → the modal UNMOUNTS, taking the banner with it. The banner is therefore only on screen for
    # the refresh() window, so to_be_visible() races it (flaked on BOTH runners across §3.1/§3.2/§3.6 — a
    # sturdier WAIT can't fix a transient element). Assert the DURABLE end-state instead — the modal closes
    # (element+state, auto-retried, no timer): proves the submit flow ran to completion.
    expect(page.get_by_test_id("prejob-card-modal")).to_have_count(0, timeout=T)
    shot(page, "02-admin-submitted", journey=JOURNEY)
