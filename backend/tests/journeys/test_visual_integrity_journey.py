"""WO v4.36b §3.6 — Visual Integrity journey: the nav attention badge → Health Check dashboard →
drill-through renders against a deliberately-flagged chassis. Browser-level coverage of the §3.2 nav
badge + §3.3 dashboard surfaces (the API-level role-filter + flag lifecycle live in
test_visual_integrity_api.py). J436BVI marker; purge at setup AND teardown.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from playwright.sync_api import Page, expect

from _common import admin_session, shot  # noqa: E402

T = 15_000
JOURNEY = "visual_integrity"
_MARK = "J436BVI"
UTC = timezone.utc


def _purge(db) -> None:
    from sqlalchemy import text
    db.execute(text("DELETE FROM icb_mes.chassis_records WHERE created_source_ref LIKE 'J436BVI%'"))
    db.commit()


@pytest.fixture(scope="module")
def flagged():
    """A live, backdated (>24h) VIN-less chassis → trips chassis_no_vin (Chassis group, RED). The
    journey server reads this same DB, so the seed is visible to the running SPA."""
    from app.database import SessionLocal
    from app.models.mes import ChassisRecord
    with SessionLocal() as db:
        _purge(db)
        rec = ChassisRecord(vin=None, customer_name="J436B VI Cust", make="HINO", model="500",
                            status="received", source="manual", created_via="manual_chassis_menu",
                            created_source_ref=f"{_MARK}-{uuid.uuid4().hex[:6]}",
                            created_at=datetime.now(UTC) - timedelta(days=2),
                            created_by="t", updated_by="t")
        db.add(rec)
        db.commit()
        db.refresh(rec)
        cid = rec.id
    yield {"chassis_id": cid}
    from app.database import SessionLocal as SL
    with SL() as db:
        _purge(db)


def test_nav_badge_to_health_check_drill(page: Page, flagged) -> None:
    """The nav 'N attention items' badge is present (≥1 flag), routes to the Health Check dashboard,
    and drilling chassis_no_vin lists the affected chassis (the §3 demo narrative, end-to-end)."""
    admin_session(page)
    badge = page.get_by_test_id("nav-flag-badge")
    expect(badge).to_be_visible(timeout=T)
    badge.click()

    expect(page.get_by_test_id("health-check")).to_be_visible(timeout=T)
    expect(page.get_by_test_id("health-total")).to_contain_text("attention")
    flagbtn = page.get_by_test_id("health-flag-chassis_no_vin")
    expect(flagbtn).to_be_visible(timeout=T)
    flagbtn.click()
    expect(page.get_by_test_id("health-drill-list")).to_be_visible(timeout=T)
    shot(page, "01-health-check-drill", journey=JOURNEY)
