"""WO v4.36a.2 — return a chassis from an assembly bay back to the parking pool (re-prioritise jobs):
drag a pre-merge bay tile onto the Parking pool.

The drag is an HTML5 DataTransfer drop (unreliable to drive headlessly); this exercises the SAME chokepoint
the drop calls — POST /api/chassis-records/{id}/return-to-parking — via page.request, plus the outcome
(status 'in_assembly' → 'in_workshop', the assembly_assigned event deleted, the bay cleared), the
pre-merge guard (409 once a body is attached), the D1 panels-stay case (the bay derives 'pre_assembly',
the panels remain), role gating (workshop = RO), and the UI (the bay tile carries the '← drag to parking'
affordance, then clears, and the chassis reappears in the Parking pool). Runs on icb_test (CI).
"""
from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect

from _common import admin_session, role_session, shot  # noqa: E402  (sys.path set in conftest)
import _v435 as h  # noqa: E402

T = 15_000
JOURNEY = "return_to_parking"


@pytest.fixture(autouse=True)
def _clean():
    h.purge()
    yield
    h.purge()


def _return(page, base, chassis_id, reason=None):
    return h.api_post(page, base, f"/api/chassis-records/{chassis_id}/return-to-parking",
                      {"reason": reason} if reason is not None else {})


def _panels(page, base, job_id, bay_id):
    return h.api_post(page, base, f"/api/production-jobs/{job_id}/panels-arrived-in-bay", {"bay_id": bay_id})


# ── the return (the drag's outcome): status reverts + the bay clears ──────────────
def test_return_reverts_status_and_clears_bay(page: Page, live_server: str) -> None:
    s = h.make_assembly_job(attached=False)                    # chassis on a bay, no body → awaiting_attachment
    admin_session(page)
    assert h.bay_merge_state(s["bay_id"]) == "awaiting_attachment"
    r = _return(page, live_server, s["chassis_id"], reason="rush order needs the bay")
    assert r.status == 200, r.text()
    assert h.chassis_status(s["chassis_id"]) == "in_workshop"   # back in the parking pool
    assert h.bay_merge_state(s["bay_id"]) == "empty"            # the assembly_assigned event is gone


# ── the pre-merge guard: once a body is attached, no return to parking ────────────
def test_return_blocked_after_body_attached_409(page: Page, live_server: str) -> None:
    s = h.make_assembly_job(attached=True)                     # body attached → attached_today
    admin_session(page)
    r = _return(page, live_server, s["chassis_id"])
    assert r.status == 409 and "Awaiting QA" in r.text()
    assert h.chassis_status(s["chassis_id"]) == "in_assembly"  # unchanged — the return was refused


# ── D1: panels staged in the bay STAY — the bay derives pre_assembly ──────────────
def test_return_with_panels_leaves_pre_assembly(page: Page, live_server: str) -> None:
    """Also the v4.36a.3 NON-regression guard: the panel-consumption gate (panels are consumed only when
    the job's chassis has body_attached) must NOT over-reach to this NO-body path — a returned chassis's
    panels stay LOOSE ('pre_assembly'), move-back affordance intact. body_attached is the only gate."""
    s = h.make_assembly_job(attached=False)
    admin_session(page)
    assert _panels(page, live_server, s["job_id"], s["bay_id"]).status == 201
    assert h.bay_merge_state(s["bay_id"]) == "ready_to_merge"   # chassis + its own panels
    assert _return(page, live_server, s["chassis_id"]).status == 200
    assert h.chassis_status(s["chassis_id"]) == "in_workshop"
    assert h.bay_merge_state(s["bay_id"]) == "pre_assembly"     # panels remain, no chassis (D1: not blocked)
    assert h.panels_event_count(s["job_id"]) == 1              # the panels event is untouched


# ── role gating (workshop is read-only, no return affordance) ─────────────────────
def test_workshop_cannot_return(page: Page, live_server: str, role_users) -> None:
    s = h.make_assembly_job(attached=False)
    role_session(page, role_users["workshop"], base=live_server)
    r = _return(page, live_server, s["chassis_id"])
    assert r.status == 403
    assert h.chassis_status(s["chassis_id"]) == "in_assembly"   # untouched


# ── UI: the bay tile is parking-draggable, then clears; the chassis reappears in Parking ──
def test_planning_parking_drag_affordance_and_bay_clear(page: Page, live_server: str) -> None:
    s = h.make_assembly_job(attached=False)
    admin_session(page)
    nav = page.get_by_test_id("nav-planning")
    expect(nav).to_be_visible(timeout=T)
    nav.click()
    expect(page.get_by_test_id("bay-model")).to_be_visible(timeout=T)
    expect(page.get_by_test_id("parking-zone")).to_be_visible(timeout=T)
    tile = page.locator(f'[data-testid="assembly-bay"][data-bay-id="{s["bay_id"]}"]')
    expect(tile).to_have_attribute("data-bay-state", "awaiting_attachment", timeout=T)
    expect(tile).to_have_attribute("draggable", "true", timeout=T)
    expect(tile.get_by_test_id("parking-drag-hint")).to_be_visible(timeout=T)   # '← drag to parking'
    # a body-attached tile must NOT be parking-draggable (it's the QA path instead)
    shot(page, "01-bay-tile-parking-draggable", journey=JOURNEY)
    # the drop's chokepoint, then reload to see the post-return board (bay clears, chassis back in Parking)
    assert _return(page, live_server, s["chassis_id"], reason="bumped for a rush order").status == 200
    page.reload()
    expect(page.get_by_test_id("bay-model")).to_be_visible(timeout=T)
    expect(page.locator(f'[data-testid="pre-assembly-empty"][data-bay-id="{s["bay_id"]}"]')).to_have_attribute(
        "data-bay-state", "empty", timeout=T)                                   # bay flipped to empty → Pre-Assembly lane
    card = page.locator('[data-testid="parking-chassis"]', has_text=s["vin"])
    expect(card).to_be_visible(timeout=T)                                       # chassis back in the Parking pool
    shot(page, "02-returned-to-parking", journey=JOURNEY)
