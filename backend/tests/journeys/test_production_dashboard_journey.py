"""WO v4.32 §3.6 — Production Dashboard per-role journey: admin + production + workshop.

Per Testing Strategy v1.1 (§0.8): admin + the primary affected roles. Covers the §0.9 list:
deep-link from Planning (the re-enabled v4.29 D7 button → ?jobId= → bay highlight + side
panel), KPI strip render on real values, 5-bay heat-map render, the §0.3 auto-refresh tick
(asserted on the data-refreshed attribute — survives screenshot timing noise), stale-jobId
toast + param clear, and workshop's read-only view. Render-assertion style (v4.29 prevention
shift) — the aggregation math depth is covered by test_production_kpis_api. Self-cleaning
module fixture (J432-marker rows; purge at setup AND teardown — the v4.32 self-healing rule).
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest
from playwright.sync_api import Page, expect

from _common import admin_session, role_session, shot  # noqa: E402  (sys.path set in conftest)

T = 15_000
JOURNEY = "production_dashboard"
JOB_NUM = "J432DL1"
VIN = "J432DLVIN1"


def _purge(db) -> None:
    from sqlalchemy import text
    db.execute(text("DELETE FROM icb_mes.chassis_lifecycle_events WHERE chassis_record_id IN "
                    "(SELECT id FROM icb_mes.chassis_records WHERE vin LIKE 'J432DL%')"))
    db.execute(text("DELETE FROM icb_mes.planning_slots WHERE bay = 'V-88'"))
    db.execute(text("DELETE FROM icb_mes.production_jobs WHERE job_number LIKE 'J432DL%'"))
    db.execute(text("DELETE FROM icb_mes.chassis_records WHERE vin LIKE 'J432DL%'"))
    db.commit()


@pytest.fixture(scope="module")
def bay_job():
    """A chassis on a FREE assembly bay + its in_production job + a current-week planning slot
    (so the Planning Board slot panel can deep-link it). Yields the bay code."""
    from app.database import Branch, SessionLocal
    from app.models.mes import (
        AssemblyBay, ChassisLifecycleEvent, ChassisRecord, PlanningSlot, ProductionJob,
    )
    from app.services.chassis import current_occupants
    now = datetime.now(timezone.utc)
    today = now.date()
    monday = today - timedelta(days=today.weekday())
    with SessionLocal() as db:
        _purge(db)
        branch = db.query(Branch).order_by(Branch.id).first()
        occupied = set(current_occupants(db))
        bay = (db.query(AssemblyBay).filter_by(is_active=True)
               .filter(~AssemblyBay.id.in_(occupied or {0}))
               .order_by(AssemblyBay.sort_order).first())
        if bay is None:
            pytest.skip("no free assembly bay on this DB")
        rec = ChassisRecord(vin=VIN, source="manual", status="in_assembly",
                            customer_name="Journey Deep-Link Ltd", make="Isuzu", model="FTR")
        db.add(rec)
        db.flush()
        db.add(ChassisLifecycleEvent(chassis_record_id=rec.id, cycle_number=1,
                                     event_type="VCL", event_date=today - timedelta(days=2)))
        db.add(ChassisLifecycleEvent(chassis_record_id=rec.id, cycle_number=1,
                                     event_type="assembly_assigned", assembly_bay_id=bay.id,
                                     event_date=today - timedelta(days=1)))
        job = ProductionJob(branch_id=branch.id, source="workbook", job_number=JOB_NUM,
                            status="in_production", customer_name="Journey Deep-Link Ltd",
                            description="Journey Freezer Body", chassis_record_id=rec.id,
                            accepted_at=now - timedelta(days=2))
        db.add(job)
        db.flush()
        db.add(PlanningSlot(production_job_id=job.id, week=monday, bay="V-88",
                            lane="vacuum", slot_position=88, status="scheduled"))
        db.commit()
        bay_code = bay.code
    yield bay_code
    from app.database import SessionLocal as SL
    with SL() as db:
        _purge(db)


def _open_production(page: Page) -> None:
    # Direct goto (session already minted — the v4.26 deep-link rule). The nav link itself is
    # permission-gated (production.view) and its testid is nav-production_dashboard; the
    # journey's contract is the SCREEN, not the nav chrome.
    page.goto("/mes-app/production")
    expect(page.get_by_test_id("production-kpis")).to_be_visible(timeout=T)


def test_admin_kpis_heatmap_and_refresh_tick(page: Page, bay_job) -> None:
    admin_session(page)
    _open_production(page)
    # KPI strip on real values: every §0.6 tile renders.
    for label in ("Units in production", "Delayed units", "Bottleneck", "Completed today",
                  "Critical chassis", "Open rework", "Repair jobs"):
        expect(page.get_by_test_id("production-kpis").get_by_text(label)).to_be_visible(timeout=T)
    # 5-bay heat-map (the §0.1 shape change vs the 8-bay mock) with our occupant rendered.
    expect(page.get_by_test_id("production-bay-tile")).to_have_count(5, timeout=T)
    expect(page.get_by_text(VIN).first).to_be_visible(timeout=T)
    shot(page, "01-dashboard-admin", journey=JOURNEY)
    # §0.3 auto-refresh tick — the data-refreshed attribute must ADVANCE within one cycle.
    el = page.get_by_test_id("dashboard-refreshed-at")
    t1 = el.get_attribute("data-refreshed")
    page.wait_for_function(
        "([sel, prev]) => document.querySelector(sel)?.getAttribute('data-refreshed') !== prev",
        arg=["[data-testid=dashboard-refreshed-at]", t1], timeout=40_000,
    )
    assert el.get_attribute("data-refreshed") != t1


def test_admin_deep_link_from_planning_board(page: Page, bay_job) -> None:
    admin_session(page)
    nav = page.get_by_test_id("nav-planning")
    expect(nav).to_be_visible(timeout=T)
    nav.click()
    # Open the slot panel for our job, then the re-enabled D7 button (§3.5).
    cell = page.get_by_test_id("slot-cell").filter(has_text=JOB_NUM).first
    expect(cell).to_be_visible(timeout=T)
    cell.click()
    btn = page.get_by_test_id("view-in-production")
    expect(btn).to_be_enabled(timeout=T)                       # the v4.29 D7 button is LIVE again
    btn.click()
    # Lands on /production?jobId=… → bay panel opens on the right bay; param then clears.
    expect(page.get_by_test_id("production-bay-panel")).to_be_visible(timeout=T)
    expect(page.get_by_test_id("production-bay-panel").get_by_text(VIN).first).to_be_visible(timeout=T)
    page.wait_for_function("() => !window.location.search.includes('jobId')", timeout=T)
    shot(page, "02-deep-link-bay-panel", journey=JOURNEY)


def test_admin_stale_job_id_toasts_and_clears(page: Page, bay_job) -> None:
    admin_session(page)
    page.goto("/mes-app/production?jobId=ZZZ9999")
    expect(page.get_by_text("Job ZZZ9999 is no longer in production")).to_be_visible(timeout=T)
    page.wait_for_function("() => !window.location.search.includes('jobId')", timeout=T)
    shot(page, "03-stale-jobid-toast", journey=JOURNEY)


def test_production_supervisor_drills_bay_panel(page: Page, live_server: str, role_users, bay_job) -> None:
    role_session(page, role_users["production"], base=live_server)
    _open_production(page)
    expect(page.get_by_test_id("production-bay-tile")).to_have_count(5, timeout=T)
    page.get_by_test_id("production-bay-tile").filter(has_text=VIN).first.click()
    expect(page.get_by_test_id("production-bay-panel")).to_be_visible(timeout=T)
    shot(page, "04-supervisor-bay-panel", journey=JOURNEY)


def test_workshop_sees_dashboard_readonly(page: Page, live_server: str, role_users, bay_job) -> None:
    role_session(page, role_users["workshop"], base=live_server)
    _open_production(page)
    # Read-only render: KPI strip + heat-map visible; worksheet narrowed to chassis-custody tabs.
    expect(page.get_by_test_id("production-bay-tile")).to_have_count(5, timeout=T)
    expect(page.get_by_test_id("team-tab-parking")).to_be_visible(timeout=T)
    expect(page.get_by_test_id("team-tab-dispatch")).to_be_visible(timeout=T)
    expect(page.get_by_test_id("team-tab-vacuum")).to_have_count(0)
    shot(page, "05-workshop-readonly", journey=JOURNEY)
