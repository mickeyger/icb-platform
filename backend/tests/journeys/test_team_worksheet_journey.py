"""WO v4.32 §3.6 — Team worksheet per-role journey: admin + production + workshop.

Per Testing Strategy v1.1 (§0.8). Covers the §0.9 list: per-team data load through the
uniform §0.4 contract, the ±7-day date selector, the parking capacity chip + blocking flags,
dispatch pending-collection, and the per-role render gating (workshop → Parking + Dispatch
only, Parking pre-selected; production supervisor → all five). Render-assertion style — the
worksheet query depth is covered by test_team_worksheet_api. Self-cleaning module fixture
(J432W-marker rows; purge at setup AND teardown)."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest
from playwright.sync_api import Page, expect

from _common import admin_session, role_session, shot  # noqa: E402

T = 15_000
JOURNEY = "team_worksheet"
YARD_VIN = "J432WYARD1"
LATE_JOB = "J432WLATE"
COLLECT_JOB = "J432WCOL"


def _purge(db) -> None:
    from sqlalchemy import text
    db.execute(text("DELETE FROM icb_mes.chassis_lifecycle_events WHERE chassis_record_id IN "
                    "(SELECT id FROM icb_mes.chassis_records WHERE vin LIKE 'J432W%')"))
    db.execute(text("DELETE FROM icb_mes.production_jobs WHERE job_number LIKE 'J432W%'"))
    db.execute(text("DELETE FROM icb_mes.chassis_records WHERE vin LIKE 'J432W%'"))
    db.commit()


@pytest.fixture(scope="module")
def worksheet_rows():
    """One row per assertion surface: a yard chassis (parking in-flight), an overdue-ETA job
    (parking blocking flag), and a completed job + chassis (dispatch pending-collection)."""
    from app.database import Branch, SessionLocal
    from app.models.mes import ChassisLifecycleEvent, ChassisRecord, ProductionJob
    now = datetime.now(timezone.utc)
    today = now.date()
    with SessionLocal() as db:
        _purge(db)
        branch = db.query(Branch).order_by(Branch.id).first()
        yard = ChassisRecord(vin=YARD_VIN, source="manual", status="in_workshop",
                             customer_name="Journey Yard Ltd")
        done = ChassisRecord(vin="J432WDONE1", source="manual", status="in_workshop",
                             customer_name="Journey Collect Ltd")
        db.add_all([yard, done])
        db.flush()
        db.add(ChassisLifecycleEvent(chassis_record_id=yard.id, cycle_number=1,
                                     event_type="VCL", event_date=today - timedelta(days=1)))
        db.add(ChassisLifecycleEvent(chassis_record_id=done.id, cycle_number=1,
                                     event_type="VCL", event_date=today - timedelta(days=9)))
        db.add_all([
            ProductionJob(branch_id=branch.id, source="workbook", job_number=LATE_JOB,
                          status="planning", customer_name="Journey Overdue Ltd",
                          accepted_at=now - timedelta(days=4),
                          chassis_eta=now - timedelta(days=3)),
            ProductionJob(branch_id=branch.id, source="workbook", job_number=COLLECT_JOB,
                          status="completed", customer_name="Journey Collect Ltd",
                          accepted_at=now - timedelta(days=10),
                          completed_at=now - timedelta(days=9),
                          chassis_record_id=done.id),
        ])
        db.commit()
    yield
    from app.database import SessionLocal as SL
    with SL() as db:
        _purge(db)


def _open_worksheet(page: Page) -> None:
    # Direct goto (session already minted — the v4.26 deep-link rule); see the dashboard
    # journey's note on the nav link's permission gate.
    page.goto("/mes-app/production")
    expect(page.get_by_test_id("team-worksheet")).to_be_visible(timeout=T)


def test_admin_tabs_parking_and_dispatch_data(page: Page, worksheet_rows) -> None:
    admin_session(page)
    _open_worksheet(page)
    ws = page.get_by_test_id("team-worksheet")
    # All 5 tabs render for admin, in floor-flow order.
    for team in ("vacuum", "press", "assembly", "parking", "dispatch"):
        expect(page.get_by_test_id(f"team-tab-{team}")).to_be_visible(timeout=T)
    # Parking: capacity chip + yard pool row + the overdue-ETA blocking flag.
    page.get_by_test_id("team-tab-parking").click()
    expect(page.get_by_test_id("worksheet-capacity")).to_be_visible(timeout=T)
    expect(ws.get_by_text(YARD_VIN).first).to_be_visible(timeout=T)
    expect(ws.get_by_text("chassis ETA overdue").first).to_be_visible(timeout=T)
    shot(page, "01-worksheet-parking-admin", journey=JOURNEY)
    # Dispatch: the completed job awaits collection (with the >7d flag).
    page.get_by_test_id("team-tab-dispatch").click()
    expect(ws.get_by_text(f"J{COLLECT_JOB}").first).to_be_visible(timeout=T)
    expect(ws.get_by_text("pending collection").first).to_be_visible(timeout=T)
    expect(ws.get_by_text("awaiting collection").first).to_be_visible(timeout=T)
    shot(page, "02-worksheet-dispatch-admin", journey=JOURNEY)


def test_admin_date_selector_clamped_and_reloads(page: Page, worksheet_rows) -> None:
    admin_session(page)
    _open_worksheet(page)
    sel = page.get_by_test_id("worksheet-date")
    today = date.today()
    # ±7-day clamp surfaces as the input's min/max (§3.3 N=7 — mirrors the backend 422).
    assert sel.get_attribute("min") == (today - timedelta(days=7)).isoformat()
    assert sel.get_attribute("max") == (today + timedelta(days=7)).isoformat()
    # Changing the date reloads the active tab for that date (header echoes it).
    yesterday = today - timedelta(days=1)
    sel.fill(yesterday.isoformat())
    expect(page.get_by_test_id("team-worksheet")
           .get_by_text(yesterday.strftime("%d %b %Y"))).to_be_visible(timeout=T)
    shot(page, "03-worksheet-date-selector", journey=JOURNEY)


def test_production_supervisor_sees_all_tabs(page: Page, live_server: str, role_users,
                                             worksheet_rows) -> None:
    role_session(page, role_users["production"], base=live_server)
    _open_worksheet(page)
    for team in ("vacuum", "press", "assembly", "parking", "dispatch"):
        expect(page.get_by_test_id(f"team-tab-{team}")).to_be_visible(timeout=T)
    shot(page, "04-worksheet-supervisor", journey=JOURNEY)


def test_workshop_narrowed_to_custody_tabs(page: Page, live_server: str, role_users,
                                           worksheet_rows) -> None:
    role_session(page, role_users["workshop"], base=live_server)
    _open_worksheet(page)
    # §0.8 role-based render: chassis-custody tabs only, Parking pre-selected.
    expect(page.get_by_test_id("team-tab-parking")).to_be_visible(timeout=T)
    expect(page.get_by_test_id("team-tab-dispatch")).to_be_visible(timeout=T)
    for team in ("vacuum", "press", "assembly"):
        expect(page.get_by_test_id(f"team-tab-{team}")).to_have_count(0)
    expect(page.get_by_test_id("worksheet-capacity")).to_be_visible(timeout=T)  # parking active
    shot(page, "05-worksheet-workshop", journey=JOURNEY)
