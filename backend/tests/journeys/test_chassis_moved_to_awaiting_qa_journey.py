"""WO v4.36a.1 — the Awaiting-QA handoff: drag a body-attached bay tile onto the new AWAITING QA zone.

The drag itself is an HTML5 DataTransfer drop (unreliable to drive headlessly); this exercises the SAME
chokepoint the drop calls — POST /api/chassis-records/{id}/move-to-awaiting-qa — via page.request, plus the
status-promoting outcome (status='awaiting_qa' atomically with the event), the bay-clearing derivation (the
bay falls to 'empty' for free — current_occupants gates on in_assembly), the guards (body-attached
precondition / idempotency), role gating (Q5 workshop = RO), and the UI: the Planning bay tile carries the
'drag to QA' affordance, then clears, and the chassis lands in the AWAITING QA zone. Runs on icb_test (CI).

WO v4.36a.3 extension: when the bay also held the job's PANELS, body_attached CONSUMES them, so the
move-to-QA must clear the bay on the PANEL side too (state 'empty', not a stray 'pre_assembly'). The
original suite only asserted chassis-side clearing — that gap is what let the BA's bug through.
"""
from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect

from _common import admin_session, role_session, shot  # noqa: E402  (sys.path set in conftest)
import _v435 as h  # noqa: E402

T = 15_000
JOURNEY = "awaiting_qa"


@pytest.fixture(autouse=True)
def _clean():
    h.purge()
    yield
    h.purge()


def _move(page, base, chassis_id, notes=None):
    return h.api_post(page, base, f"/api/chassis-records/{chassis_id}/move-to-awaiting-qa",
                      {"notes": notes} if notes is not None else {})


# ── the handoff (the drag's outcome): status promotes + the bay clears ────────────
def test_move_promotes_status_and_clears_bay(page: Page, live_server: str) -> None:
    s = h.make_assembly_job(attached=True)                     # chassis on a bay, body attached → attached_today
    admin_session(page)
    assert h.bay_merge_state(s["bay_id"]) == "attached_today"
    r = _move(page, live_server, s["chassis_id"], notes="QC ready")
    assert r.status == 201, r.text()
    assert r.json()["event_type"] == "moved_to_awaiting_qa"
    assert h.chassis_status(s["chassis_id"]) == "awaiting_qa"  # status-promoting (not phase-only)
    assert h.bay_merge_state(s["bay_id"]) == "empty"           # the status write clears the bay — no derivation change


# ── guards (backend is the source of truth) ──────────────────────────────────────
def test_move_requires_body_attached_422(page: Page, live_server: str) -> None:
    s = h.make_assembly_job(attached=False)                    # on a bay, NO body → awaiting_attachment
    admin_session(page)
    assert h.bay_merge_state(s["bay_id"]) == "awaiting_attachment"
    r = _move(page, live_server, s["chassis_id"])
    assert r.status == 422 and "body" in r.text().lower()
    assert h.chassis_status(s["chassis_id"]) == "in_assembly"  # unchanged — the move was refused


def test_move_idempotent(page: Page, live_server: str) -> None:
    s = h.make_assembly_job(attached=True)
    admin_session(page)
    assert _move(page, live_server, s["chassis_id"]).status == 201
    r = _move(page, live_server, s["chassis_id"])              # already moved
    assert r.status in (409, 422)                              # already awaiting_qa (status guard fires)


# ── role gating (Q5 — workshop is read-only, no move affordance) ──────────────────
def test_workshop_cannot_move(page: Page, live_server: str, role_users) -> None:
    s = h.make_assembly_job(attached=True)
    role_session(page, role_users["workshop"], base=live_server)
    r = _move(page, live_server, s["chassis_id"])
    assert r.status == 403
    assert h.chassis_status(s["chassis_id"]) == "in_assembly"  # untouched


# ── UI: the bay tile is draggable, then clears; the chassis appears in the zone ───
def test_planning_zone_drag_affordance_and_bay_clear(page: Page, live_server: str) -> None:
    s = h.make_assembly_job(attached=True)
    admin_session(page)
    nav = page.get_by_test_id("nav-planning")
    expect(nav).to_be_visible(timeout=T)
    nav.click()
    expect(page.get_by_test_id("bay-model")).to_be_visible(timeout=T)
    expect(page.get_by_test_id("awaiting-qa-zone")).to_be_visible(timeout=T)
    tile = page.locator(f'[data-testid="assembly-bay"][data-bay-id="{s["bay_id"]}"]')
    expect(tile).to_have_attribute("data-bay-state", "attached_today", timeout=T)
    expect(tile).to_have_attribute("draggable", "true", timeout=T)
    expect(tile.get_by_test_id("qa-drag-hint")).to_be_visible(timeout=T)     # the 'drag to QA →' affordance
    shot(page, "01-attached-tile-draggable", journey=JOURNEY)
    # the drop's chokepoint, then reload to see the post-move board (the bay clears, the chassis lands in QA)
    assert _move(page, live_server, s["chassis_id"], notes="QC ready").status == 201
    page.reload()
    expect(page.get_by_test_id("bay-model")).to_be_visible(timeout=T)
    expect(page.locator(f'[data-testid="pre-assembly-empty"][data-bay-id="{s["bay_id"]}"]')).to_have_attribute(
        "data-bay-state", "empty", timeout=T)                                # bay flipped to empty → Pre-Assembly lane
    card = page.locator('[data-testid="awaiting-qa-chassis"]', has_text=s["vin"])
    expect(card).to_be_visible(timeout=T)                                    # chassis now in the AWAITING QA zone
    shot(page, "02-moved-to-qa-zone", journey=JOURNEY)


# ── WO v4.36a.3 — panel-side bay state clears with the body (the BA click-around catch) ───────────
def test_panels_consumed_clear_with_body_on_move_to_qa(page: Page, live_server: str) -> None:
    """Asserts BOTH chassis-side AND panel-side bay state clear after forward-to-QA — panel-side clearing
    was the v4.36a.3 catch (the gap: the original journey only asserted chassis-side clearing). Once
    body_attached fires, the job's panels are CONSUMED (part of the body); when the body moves to QA the bay
    must derive 'empty', NOT 'pre_assembly' with a stray 'move panels back' affordance. The panels event row
    is NOT deleted (consumed ≠ removed) — and move-back on consumed panels is refused (409)."""
    s = h.make_assembly_job(attached=False)                    # chassis on a bay, no body yet
    admin_session(page)
    panels = h.api_post(page, live_server, f"/api/production-jobs/{s['job_id']}/panels-arrived-in-bay",
                        {"bay_id": s["bay_id"]})
    assert panels.status == 201, panels.text()
    assert h.bay_merge_state(s["bay_id"]) == "ready_to_merge"   # panels loose + matched chassis, no body
    body = h.api_post(page, live_server, f"/api/chassis-records/{s['chassis_id']}/body-attached",
                      {"production_job_id": s["job_id"]})
    assert body.status == 201, body.text()
    assert h.bay_merge_state(s["bay_id"]) == "attached_today"   # panels now CONSUMED (no longer loose)
    # §0.4 — move-back on consumed panels is a 409 (they're part of the body, not loose)
    r409 = h.api_delete(page, live_server, f"/api/production-jobs/{s['job_id']}/panels-arrived-in-bay")
    assert r409.status == 409 and "body" in r409.text().lower()
    # move the body to QA → the bay clears on BOTH sides
    assert _move(page, live_server, s["chassis_id"]).status == 201
    assert h.chassis_status(s["chassis_id"]) == "awaiting_qa"
    assert h.bay_merge_state(s["bay_id"]) == "empty"           # ← v4.36a.3 fix: NOT 'pre_assembly'
    assert h.panels_event_count(s["job_id"]) == 1             # the panels event persists (consumed, not removed)
