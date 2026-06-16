"""WO v4.35 §3.3b (STRETCH) — Planning panel-drag-to-bay → merge flow.

The drag itself is an HTML5 DataTransfer drop (unreliable to drive headlessly); this exercises the SAME
chokepoint the drop calls — POST /api/production-jobs/{id}/panels-arrived-in-bay — via page.request, plus
the resulting 6-state derivation, the auto-merge completion (body_attached), the guards (idempotency /
busy-bay), role gating (Q5), and ONE UI assertion that the Planning bay tile renders 'ready_to_merge'.
"""
from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect

from _common import admin_session, role_session, shot  # noqa: E402  (sys.path set in conftest)
import _v435 as h  # noqa: E402

T = 15_000
JOURNEY = "planning_drag"


@pytest.fixture(autouse=True)
def _clean():
    h.purge()
    yield
    h.purge()


def _panels(page, base, job_id, bay_id):
    return h.api_post(page, base, f"/api/production-jobs/{job_id}/panels-arrived-in-bay", {"bay_id": bay_id})


# ── the merge flow (the drag's outcome) ──────────────────────────────────────────
def test_panels_arrived_makes_bay_ready_to_merge(page: Page, live_server: str) -> None:
    s = h.make_assembly_job()                                  # chassis on a bay → awaiting_attachment
    admin_session(page)
    assert h.bay_merge_state(s["bay_id"]) == "awaiting_attachment"
    r = _panels(page, live_server, s["job_id"], s["bay_id"])
    assert r.status == 201, r.text()
    merge = r.json()["merge"]
    assert merge["ready"] is True and merge["state"] == "ready_to_merge"
    assert h.panels_event_count(s["job_id"]) == 1
    assert h.bay_merge_state(s["bay_id"]) == "ready_to_merge"


def test_ready_to_merge_then_body_attached_completes_merge(page: Page, live_server: str) -> None:
    s = h.make_assembly_job()
    admin_session(page)
    assert _panels(page, live_server, s["job_id"], s["bay_id"]).status == 201
    assert h.bay_merge_state(s["bay_id"]) == "ready_to_merge"
    # the auto-merge prompt's confirm action → the body_attached chokepoint
    r = h.api_post(page, live_server, f"/api/chassis-records/{s['chassis_id']}/body-attached",
                   {"production_job_id": s["job_id"]})
    assert r.status == 201, r.text()
    assert h.body_attached_event_count(s["chassis_id"]) == 1
    assert h.bay_merge_state(s["bay_id"]) == "attached_today"


# ── guards (§3.3b considerations 1 & 2 — backend is the source of truth) ──────────
def test_idempotent_panels_409(page: Page, live_server: str) -> None:
    s = h.make_assembly_job()
    admin_session(page)
    assert _panels(page, live_server, s["job_id"], s["bay_id"]).status == 201
    r = _panels(page, live_server, s["job_id"], s["bay_id"])               # same job, same bay
    assert r.status == 409 and "already in" in r.text()
    assert h.panels_event_count(s["job_id"]) == 1


def test_busy_bay_409(page: Page, live_server: str) -> None:
    a = h.make_assembly_job()
    b = h.make_assembly_job()                                              # a different job + bay
    admin_session(page)
    assert _panels(page, live_server, a["job_id"], a["bay_id"]).status == 201
    r = _panels(page, live_server, b["job_id"], a["bay_id"])              # b's panels onto a's bay
    assert r.status == 409 and "already holds panels" in r.text()
    assert h.panels_event_count(b["job_id"]) == 0


# ── move-panels-back undo + mismatch legibility (the demo click-around finds) ────
def test_clear_panels_moves_them_back(page: Page, live_server: str) -> None:
    s = h.make_assembly_job()
    admin_session(page)
    assert _panels(page, live_server, s["job_id"], s["bay_id"]).status == 201
    assert h.panels_event_count(s["job_id"]) == 1 and h.bay_merge_state(s["bay_id"]) == "ready_to_merge"
    r = h.api_delete(page, live_server, f"/api/production-jobs/{s['job_id']}/panels-arrived-in-bay")
    assert r.status == 200, r.text()
    assert r.json()["removed"] == 1
    assert h.panels_event_count(s["job_id"]) == 0
    assert h.bay_merge_state(s["bay_id"]) == "awaiting_attachment"   # back to chassis-only, no orphan


def test_panels_on_a_different_jobs_chassis_is_a_mismatch(page: Page, live_server: str) -> None:
    a = h.make_assembly_job()
    b = h.make_assembly_job()                                # a different job + chassis on its own bay
    admin_session(page)
    # drop b's panels onto a's bay (which holds a's chassis) → panels + chassis are different jobs
    r = _panels(page, live_server, b["job_id"], a["bay_id"])
    assert r.status == 201, r.text()
    merge = r.json()["merge"]
    assert merge["mismatch"] is True and merge["ready"] is False
    assert h.bay_merge_state(a["bay_id"]) == "awaiting_attachment"   # NOT ready_to_merge — different jobs


# ── role gating (Q5 — workshop is read-only) ─────────────────────────────────────
def test_workshop_cannot_arrive_panels(page: Page, live_server: str, role_users) -> None:
    s = h.make_assembly_job()
    role_session(page, role_users["workshop"], base=live_server)
    r = _panels(page, live_server, s["job_id"], s["bay_id"])
    assert r.status == 403
    assert h.panels_event_count(s["job_id"]) == 0


# ── Production side panel — mark-attached visibility (the demo click-around find) ──
def test_production_shows_mark_attached_for_ready_to_merge(page: Page, live_server: str) -> None:
    s = h.make_assembly_job()                                  # linked job + chassis on a bay
    admin_session(page)
    assert _panels(page, live_server, s["job_id"], s["bay_id"]).status == 201   # → ready_to_merge
    h.open_production(page)
    page.locator(f'[data-bay-code="{s["bay_code"]}"]').click()
    expect(page.get_by_test_id("mark-body-attached")).to_be_visible(timeout=T)  # actionable, not absent


def test_production_no_job_hint_for_unlinked_chassis(page: Page, live_server: str) -> None:
    u = h.assign_unlinked_chassis()                            # chassis on a bay, NO linked job
    admin_session(page)
    h.open_production(page)
    page.locator(f'[data-bay-code="{u["bay_code"]}"]').click()
    expect(page.get_by_test_id("mark-attached-no-job")).to_be_visible(timeout=T)   # legible, not a dead button
    expect(page.get_by_test_id("mark-body-attached")).to_have_count(0)


# ── UI: the Planning bay tile renders the new 'ready_to_merge' state + merge affordance ──
def test_planning_bay_tile_renders_ready_to_merge(page: Page, live_server: str) -> None:
    s = h.make_assembly_job()
    admin_session(page)
    assert _panels(page, live_server, s["job_id"], s["bay_id"]).status == 201
    nav = page.get_by_test_id("nav-planning")
    expect(nav).to_be_visible(timeout=T)
    nav.click()
    expect(page.get_by_test_id("bay-model")).to_be_visible(timeout=T)
    tile = page.locator(f'[data-testid="assembly-bay"][data-bay-id="{s["bay_id"]}"]')
    expect(tile).to_have_attribute("data-bay-state", "ready_to_merge", timeout=T)
    expect(tile.get_by_test_id("merge-button")).to_be_visible(timeout=T)
    shot(page, "01-planning-ready-to-merge", journey=JOURNEY)
