"""WO v4.34.1 §3.6 — Gap A: late VIN capture on the Chassis page (journey).

An Expected chassis arrives with no VIN. A planner (and admin) opens it, captures the VIN via the
pencil, and sees it stick with a provenance pill — after which the Capture-VIN affordance is gone
(the backend NULL→value write-once guard, §3.4b). J341V markers; purge at setup AND teardown.
"""
from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect

from _common import admin_session, role_session, shot  # noqa: E402

T = 15_000
JOURNEY = "vin_late_entry"


def _purge(db) -> None:
    from sqlalchemy import text
    db.execute(text("DELETE FROM icb_mes.chassis_records "
                    "WHERE created_source_ref LIKE 'J341V%' OR vin LIKE 'J341V%'"))
    db.commit()


@pytest.fixture()
def expected_chassis():
    """A fresh Expected chassis (vin=NULL) — the Gap A precondition. Function-scoped so each test
    (planner, admin) gets its own NULL-VIN row to capture."""
    from app.database import SessionLocal
    from app.models.mes import ChassisRecord
    with SessionLocal() as db:
        _purge(db)
        rec = ChassisRecord(vin=None, status="expected", source="manual",
                            created_via="manual_chassis_menu", created_source_ref="J341V ref",
                            make="Isuzu FTR 850", customer_name="J341V Test Customer")
        db.add(rec)
        db.commit()
        rec_id = rec.id
    yield rec_id
    from app.database import SessionLocal as SL
    with SL() as db:
        _purge(db)


def _goto_detail(page: Page, rec_id: int) -> None:
    with page.expect_response(lambda r: f"/api/chassis-records/{rec_id}" in r.url, timeout=30_000):
        page.goto(f"/mes-app/chassis/{rec_id}")
    expect(page.get_by_test_id("chassis-detail")).to_be_visible(timeout=T)


def _capture_vin(page: Page, rec_id: int, vin: str) -> None:
    btn = page.get_by_test_id("chassis-capture-vin")
    expect(btn).to_be_visible(timeout=T)                  # vin IS NULL ⇒ affordance present
    btn.click()
    expect(page.get_by_test_id("chassis-capture-vin-form")).to_be_visible(timeout=T)
    page.get_by_test_id("chassis-capture-vin-input").fill(vin)
    with page.expect_response(lambda r: r.url.endswith(f"/chassis-records/{rec_id}/vin")
                              and r.request.method == "POST", timeout=T) as ri:
        page.get_by_test_id("chassis-capture-vin-save").click()
    assert ri.value.status == 200, f"vin capture returned {ri.value.status}"


def test_planner_captures_vin(page: Page, live_server: str, role_users, expected_chassis) -> None:
    role_session(page, role_users["planner"], base=live_server)
    _goto_detail(page, expected_chassis)
    shot(page, "01-no-vin", journey=JOURNEY)
    _capture_vin(page, expected_chassis, "J341VVIN0001")
    # VIN now shows with a provenance pill; the capture affordance is gone (write-once).
    pill = page.get_by_test_id("chassis-vin-source")
    expect(pill).to_be_visible(timeout=T)
    expect(pill).to_contain_text("manually captured")
    expect(page.get_by_test_id("chassis-capture-vin")).to_have_count(0)
    shot(page, "02-vin-captured", journey=JOURNEY)


def test_admin_captures_vin(page: Page, expected_chassis) -> None:
    admin_session(page)
    _goto_detail(page, expected_chassis)
    _capture_vin(page, expected_chassis, "J341VVIN0002")
    expect(page.get_by_test_id("chassis-vin-source")).to_contain_text("manually captured", timeout=T)
    expect(page.get_by_test_id("chassis-capture-vin")).to_have_count(0)
