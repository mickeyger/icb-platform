"""WO v4.33 §3.7 — Pre-Job Card SIGN-OFF journey: admin + sales rep + planner.

A sent_for_check card (API-staged): the planner signs via the §3.5 page (attestation modal),
the sales rep's page shows "awaiting the other check" cross-state, the second sign-off flips
the green CONFIRMED banner. Role-gating render check: the planner-role user on the SALES page
gets the role-gated empty state (prejob.signoff_sales not granted to planner — §0.3
separation). J433S* markers; purge at setup AND teardown.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from playwright.sync_api import Page, expect

from _common import admin_session, role_session, shot  # noqa: E402

T = 15_000
JOURNEY = "prejob_signoff"


def _goto_with_session(page: Page, path: str) -> None:
    """Direct-load a page AND wait for the SPA's /api/session bootstrap — apiPost takes its
    X-CSRF token from that response, so clicking before it lands 403s ("CSRF token missing").
    THE root cause of the §3.7 ubuntu flake family (exposed by response instrumentation)."""
    with page.expect_response(lambda r: "/api/session" in r.url, timeout=30_000):
        page.goto(path)


def _purge(db) -> None:
    from sqlalchemy import text
    db.execute(text("DELETE FROM icb_mes.prejob_cards WHERE body_description LIKE 'J433S%'"))
    db.execute(text("DELETE FROM icb_mes.prejob_templates WHERE name LIKE 'J433S%'"))
    db.commit()


@pytest.fixture()
def sent_card_id():
    """A fresh sent_for_check card per test (sign-offs mutate state)."""
    from app.database import CalculationRecord, SessionLocal, User
    from app.models.mes import PrejobCard, PrejobTemplate, ProductionJob
    with SessionLocal() as db:
        _purge(db)
        taken = {j.calculation_record_id for j in db.query(ProductionJob)
                 .filter(ProductionJob.calculation_record_id.isnot(None)).all()}
        from app.models.mes import PrejobCard as PC
        carded = {c.calculation_id for c in db.query(PC).all()}
        calc = (db.query(CalculationRecord)
                .filter(~CalculationRecord.id.in_((taken | carded) or {0}))
                .order_by(CalculationRecord.id).first())
        if calc is None:
            pytest.skip("no free calculation on this DB")
        admin = db.query(User).filter_by(username="admin").first()
        tpl = PrejobTemplate(name="J433S TPL", body_type="chiller", product_line="standard",
                             is_active=True, header_format="J433S header",
                             sections=[{"name": "GRP SECTION", "items": [{"text": "Item"}]}],
                             created_by="j")
        db.add(tpl)
        db.flush()
        card = PrejobCard(calculation_id=calc.id, template_id=tpl.id,
                          body_description="J433S — Journey Card",
                          sections=tpl.sections, body_gap_mm=120, body_gap_pending=False,
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


def test_planner_signs_then_admin_completes(page: Page, live_server: str, role_users,
                                            sent_card_id) -> None:
    # Planner signs via the §3.5 page.
    role_session(page, role_users["planner"], base=live_server)
    _goto_with_session(page, f"/mes-app/prejob/{sent_card_id}/signoff/planner")
    expect(page.get_by_test_id("prejob-signoff-page")).to_be_visible(timeout=T)
    page.get_by_test_id("prejob-signoff-btn").click()
    attest = page.get_by_test_id("prejob-attestation")
    expect(attest).to_be_visible(timeout=T)
    attest.fill("I, Planner, confirm feasibility — chassis fits, gap workable.")
    # NO screenshot between fill and click: a full_page shot scrolls the page under the
    # fixed-position modal and destabilises the button (the §3.7 flake class). Instrumented —
    # a failing POST prints its error detail into the CI log.
    with page.expect_response(lambda r: "/signoff/" in r.url and r.request.method == "POST",
                              timeout=T) as ri:
        page.get_by_test_id("prejob-attestation-confirm").click()
    assert ri.value.status == 200, f"signoff failed HTTP {ri.value.status}: {ri.value.text()[:300]}"
    expect(page.get_by_text("Your Planner sign-off is in", exact=False)).to_be_visible(timeout=T)
    shot(page, "02-planner-signed", journey=JOURNEY)

    # Admin completes the sales check → CONFIRMED. Two session subtleties (both bit):
    # admin_session() would KEEP the planner session (the SPA autologin reuses an existing
    # valid session — the v4.29 note), and role_session's autologin POST 403s through the
    # CSRF middleware when the context already carries a session cookie. Clear cookies, THEN
    # re-mint as admin.
    page.context.clear_cookies()
    role_session(page, "admin", base=live_server)
    _goto_with_session(page, f"/mes-app/prejob/{sent_card_id}/signoff/sales")
    expect(page.get_by_test_id("prejob-signoff-btn")).to_be_visible(timeout=T)
    page.get_by_test_id("prejob-signoff-btn").click()
    attest = page.get_by_test_id("prejob-attestation")
    expect(attest).to_be_visible(timeout=T)
    attest.fill("Commercial spec matches the sale.")
    page.get_by_test_id("prejob-attestation-confirm").click()
    expect(page.get_by_text("Pre-Job CONFIRMED", exact=False).first).to_be_visible(timeout=T)
    shot(page, "03-confirmed", journey=JOURNEY)


def test_planner_role_gated_off_sales_page(page: Page, live_server: str, role_users,
                                           sent_card_id) -> None:
    """§0.3 separation: planner lacks prejob.signoff_sales → the SALES page renders the
    role-gated empty state (and the backend would 403 regardless)."""
    role_session(page, role_users["planner"], base=live_server)
    page.goto(f"/mes-app/prejob/{sent_card_id}/signoff/sales")
    expect(page.get_by_text("Sales Rep sign-off is role-gated", exact=False)).to_be_visible(timeout=T)
    shot(page, "04-planner-gated-off-sales", journey=JOURNEY)
