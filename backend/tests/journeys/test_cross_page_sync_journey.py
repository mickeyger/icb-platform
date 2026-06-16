"""WO v4.35 §3.3b (STRETCH) — cross-page sync via refetch-on-focus (Q6; websockets are v4.36+).

An action taken on one page should be reflected on the others when the operator switches back. The hook
(useRefetchOnFocus) is wired on three surfaces; this proves the mechanism on two of them:

  * the Planning bay lanes — which have NO polling, so a focus-driven flip is UNAMBIGUOUS (nothing else
    could have refetched); and
  * the Production dashboard bay tiles — flipping within a window far shorter than the 30s poll.

The change is made out-of-band via the API (as if another user did it on another page); the open page is
never reloaded — only a focus event is dispatched.
"""
from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect

from _common import admin_session  # noqa: E402  (sys.path set in conftest)
import _v435 as h  # noqa: E402

T = 15_000
FOCUS = "() => window.dispatchEvent(new Event('focus'))"   # the operator switching back to this tab


@pytest.fixture(autouse=True)
def _clean():
    h.purge()
    yield
    h.purge()


# ── Planning bay lanes — no poll, so the flip can ONLY be the focus-refetch ───────
def test_planning_bay_lanes_refetch_on_focus(page: Page, live_server: str) -> None:
    s = h.make_assembly_job()                                  # chassis on a bay → awaiting_attachment
    admin_session(page)
    nav = page.get_by_test_id("nav-planning")
    expect(nav).to_be_visible(timeout=T)
    nav.click()
    expect(page.get_by_test_id("bay-model")).to_be_visible(timeout=T)
    tile = page.locator(f'[data-testid="assembly-bay"][data-bay-id="{s["bay_id"]}"]')
    expect(tile).to_have_attribute("data-bay-state", "awaiting_attachment", timeout=T)

    # Out-of-band change (as if a planner dropped the panels on another page): bay → ready_to_merge in the DB.
    r = h.api_post(page, live_server, f"/api/production-jobs/{s['job_id']}/panels-arrived-in-bay",
                   {"bay_id": s["bay_id"]})
    assert r.status == 201, r.text()

    page.evaluate(FOCUS)                                       # NO page.reload(); Planning has no poll
    expect(tile).to_have_attribute("data-bay-state", "ready_to_merge", timeout=T)


# ── Production dashboard tiles — flips on focus well inside the 30s poll window ───
def test_production_dashboard_refetches_on_focus(page: Page, live_server: str) -> None:
    s = h.make_assembly_job()
    admin_session(page)
    h.open_production(page)
    tile = page.locator(f'[data-bay-code="{s["bay_code"]}"]')
    expect(tile).to_have_attribute("data-bay-state", "awaiting_attachment", timeout=T)

    # Mark the body attached out-of-band (as if recorded on the Planning merge prompt).
    r = h.api_post(page, live_server, f"/api/chassis-records/{s['chassis_id']}/body-attached",
                   {"production_job_id": s["job_id"]})
    assert r.status == 201, r.text()

    page.evaluate(FOCUS)
    # 15s is still well under the 30s poll, so the flip is the focus-refetch, not the interval tick
    # (and matches the suite convention for this identical attached_today flip).
    expect(tile).to_have_attribute("data-bay-state", "attached_today", timeout=T)
