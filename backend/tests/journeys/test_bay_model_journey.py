"""WO v4.31 §3.5 — Bay-model (four-lane Planning Board) per-role journey: admin + workshop.

Per Testing Strategy v1.1: admin + the primary affected role. Workshop RECEIVES assembly
assignments (no chassis.assembly_assign grant — §3.1 role table), so its render must be
view-only: lanes visible, drag/drop affordances absent. Render-assertion journey (the v4.29
prevention-shift pattern, mirroring test_planning_drag_journey) — the assign mutation depth
(201 / 409 occupancy / 422 no-cycle / 403) is covered by test_chassis_assembly_assign_api.
"""
from __future__ import annotations

import uuid
from datetime import date

import pytest
from playwright.sync_api import Page, expect

from _common import admin_session, role_session, shot  # noqa: E402  (sys.path set in conftest)

T = 15_000
JOURNEY = "bay_model"


@pytest.fixture(scope="module")
def parking_chassis():
    """A booked-in chassis (cycle-1 VCL, status in_workshop) -> renders in the Parking pool.
    Cleaned up at module end (events cascade)."""
    from app.database import SessionLocal
    from app.models.mes import ChassisLifecycleEvent, ChassisRecord
    vin = f"JRNY{uuid.uuid4().hex[:10].upper()}"
    with SessionLocal() as db:
        rec = ChassisRecord(vin=vin, source="manual", status="in_workshop",
                            make="HINO", model="500", customer_name="Journey Logistics")
        db.add(rec)
        db.commit()
        db.refresh(rec)
        db.add(ChassisLifecycleEvent(chassis_record_id=rec.id, cycle_number=1,
                                     event_type="VCL", event_date=date.today()))
        db.commit()
        rid = rec.id
    yield vin
    with SessionLocal() as db:
        rec = db.get(ChassisRecord, rid)
        if rec:
            db.delete(rec)
            db.commit()


def _open_board(page: Page) -> None:
    nav = page.get_by_test_id("nav-planning")
    expect(nav).to_be_visible(timeout=T)
    nav.click()
    expect(page.get_by_test_id("bay-model")).to_be_visible(timeout=T)


def test_bay_model_admin_lanes_and_assign_affordance(page: Page, parking_chassis) -> None:
    admin_session(page)
    _open_board(page)
    bay_model = page.get_by_test_id("bay-model")
    # Parking lane: the booked-in chassis is in the pool.
    expect(bay_model.get_by_text(parking_chassis)).to_be_visible(timeout=T)
    # Assembly lane: the 5 seeded bays render.
    expect(page.get_by_test_id("assembly-bay")).to_have_count(5, timeout=T)
    # Admin (wildcard) has the assign affordance: drag hint + drop-target hint.
    expect(bay_model.get_by_text("Drag onto an assembly bay")).to_be_visible(timeout=T)
    expect(page.get_by_text("drop a chassis").first).to_be_visible(timeout=T)
    shot(page, "01-bay-model-admin", journey=JOURNEY)


def test_bay_model_workshop_is_view_only(page: Page, live_server: str, role_users, parking_chassis) -> None:
    # Workshop receives assignments — sees the lanes, but NO assign affordances (§3.1 role table).
    role_session(page, role_users["workshop"], base=live_server)
    _open_board(page)
    bay_model = page.get_by_test_id("bay-model")
    expect(bay_model.get_by_text(parking_chassis)).to_be_visible(timeout=T)     # lanes visible
    expect(page.get_by_test_id("assembly-bay")).to_have_count(5, timeout=T)
    expect(bay_model.get_by_text("Drag onto an assembly bay")).to_have_count(0)  # no drag hint
    expect(page.get_by_text("drop a chassis")).to_have_count(0)                  # no drop-target hint
    free_bays = page.get_by_test_id("assembly-bay").get_by_text("empty")         # free bays read-only
    expect(free_bays.first).to_be_visible(timeout=T)
    shot(page, "02-bay-model-workshop-readonly", journey=JOURNEY)
