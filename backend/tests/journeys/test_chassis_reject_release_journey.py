"""WO v4.34 §3.8 — chassis REJECT-RELEASE journey (§3.4): admin rejects a Pre-Job card whose chassis
was auto-created → the chassis is released to 'expected_orphaned'.

Stages a sent_for_check card with an auto-created (created_via='pre_job_card') 'expected' chassis
linked ONLY to the card (no job), so the §3.4 release flips it to 'expected_orphaned' on reject. The
reject is driven through the planner sign-off page (same path as the prejob reject journey). The
release matching (created_source_ref == _source_ref) is API-tested in test_chassis_auto_create.py.
J434B* markers; purge at setup AND teardown.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from playwright.sync_api import Page, expect

from _common import admin_session, shot  # noqa: E402

T = 15_000
JOURNEY = "chassis_reject_release"
CHASSIS_TYPE = "Hino 500 1627 LWB (EJ5)"


def _purge(db) -> None:
    from sqlalchemy import text
    db.execute(text("DELETE FROM icb_mes.prejob_cards WHERE body_description LIKE 'J434B%'"))
    # Target ONLY this journey's chassis (created_by='j434b') — a make-based purge would catch real
    # pre_job_card chassis (e.g. the #32746 job's), tripping ON DELETE RESTRICT.
    db.execute(text("DELETE FROM icb_mes.chassis_records WHERE created_by='j434b'"))
    db.execute(text("DELETE FROM icb_mes.prejob_templates WHERE name LIKE 'J434B%'"))
    db.commit()


@pytest.fixture()
def staged():
    from app.database import CalculationRecord, SessionLocal, User
    from app.models.mes import ChassisRecord, PrejobCard, PrejobTemplate, ProductionJob
    with SessionLocal() as db:
        _purge(db)
        taken = {j.calculation_record_id for j in db.query(ProductionJob)
                 .filter(ProductionJob.calculation_record_id.isnot(None)).all()}
        carded = {c.calculation_id for c in db.query(PrejobCard).all()}
        calc = (db.query(CalculationRecord)
                .filter(~CalculationRecord.id.in_((taken | carded) or {0}))
                .order_by(CalculationRecord.id).first())
        if calc is None:
            pytest.skip("no free calculation on this DB")
        admin = db.query(User).filter_by(username="admin").first()
        tpl = PrejobTemplate(name="J434B TPL", body_type="chiller", product_line="standard",
                             is_active=True, sections=[{"name": "S", "items": [{"text": "Item"}]}],
                             created_by="j434b")
        db.add(tpl)
        db.flush()
        card = PrejobCard(calculation_id=calc.id, template_id=tpl.id,
                          body_description="J434B — Reject-Release Card", sections=tpl.sections,
                          body_gap_mm=100, body_gap_pending=False, created_by_user_id=admin.id,
                          sales_rep_user_id=admin.id, planner_user_id=admin.id,
                          status="sent_for_check", sent_for_check_at=datetime.now(timezone.utc))
        db.add(card)
        db.flush()
        # created_source_ref MUST equal _source_ref(calc, card) computed at reject (quote, else "card N").
        ref = calc.quote_number or f"card {card.id}"
        chassis = ChassisRecord(make=CHASSIS_TYPE, vin=None, status="expected",
                                source="pre_job_card", created_via="pre_job_card",
                                created_source_ref=ref, created_by="j434b", updated_by="j434b")
        db.add(chassis)
        db.flush()
        card.chassis_record_id = chassis.id              # linked ONLY to the card (no job)
        db.commit()
        ids = {"card_id": card.id, "chassis_id": chassis.id}
    yield ids
    from app.database import SessionLocal as SL
    with SL() as db:
        _purge(db)


def test_admin_reject_releases_chassis_to_orphaned(page: Page, staged) -> None:
    admin_session(page)
    with page.expect_response(lambda r: "/api/session" in r.url, timeout=30_000):
        page.goto(f"/mes-app/prejob/{staged['card_id']}/signoff/planner")
    page.get_by_test_id("prejob-reject-btn").click()
    reason = page.get_by_test_id("prejob-reject-reason")
    expect(reason).to_be_visible(timeout=T)
    reason.fill("Chassis spec wrong — release the placeholder.")
    with page.expect_response(lambda r: "/reject/" in r.url, timeout=T) as ri:
        page.get_by_test_id("prejob-reject-confirm").click()
    assert ri.value.status == 200, f"reject failed HTTP {ri.value.status}: {ri.value.text()[:300]}"
    expect(page.get_by_text("Back at draft", exact=False)).to_be_visible(timeout=T)

    # §3.4 — the auto-created, card-only chassis is released to 'expected_orphaned'.
    from app.database import SessionLocal
    from app.models.mes import ChassisRecord
    with SessionLocal() as db:
        ch = db.get(ChassisRecord, staged["chassis_id"])
        assert ch is not None and ch.status == "expected_orphaned", \
            f"chassis status is {ch.status if ch else 'GONE'}, expected 'expected_orphaned'"

    # §3.7 — it shows under the Expected (Orphaned) filter (red pill).
    page.get_by_test_id("nav-chassis").click()
    expect(page.get_by_test_id("chassis-list")).to_be_visible(timeout=T)
    page.get_by_test_id("chassis-filter-expected_orphaned").click()
    row = page.locator(f"[data-testid=chassis-row][data-id='{staged['chassis_id']}']")
    expect(row).to_be_visible(timeout=T)
    shot(page, "01-chassis-orphaned", journey=JOURNEY)
