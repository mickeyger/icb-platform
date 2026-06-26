"""WO v4.37 §3.6 — native Cost Calculator journey (read-path through /costings/new).

Drives the native React Cost Calculator (which replaced the /mes/calculator iframe in
§3.2/§3.3) end-to-end in a real browser: autologin → /costings/new → the native calc
renders the body-type picker and the live cost summary (proving the trailer fetch +
/api/calculate round-trip ran against the seeded DB).

Per the journey convention (_common.py + test_costing_journey.py) browser journeys
cover the READ-PATH; the save / overwrite MUTATIONS are covered deterministically by
the backend tests (test_v4_37_calc_hardening.py) so the browser never pollutes the DB.

Run locally (after `npm run build` + `playwright install chromium`):
    pytest backend/tests/journeys/test_cost_calc_journey.py -v
"""
from __future__ import annotations

from playwright.sync_api import Page, expect

from _common import admin_session, shot  # noqa: E402  (sys.path set in conftest)

T = 15_000


def test_cost_calc_journey(page: Page) -> None:
    # 1) Autologin as admin and land on the authenticated shell.
    admin_session(page)

    # 2) Deep-link the native calculator (the former /mes/calculator iframe route).
    page.goto("/mes-app/costings/new")

    # 3) The native calc mounts: the body-type picker renders once trailers load, and
    #    the cost summary renders after the first debounced /api/calculate returns.
    expect(page.get_by_test_id("cost-calculator")).to_be_visible(timeout=T)
    expect(page.get_by_test_id("calc-body-type")).to_be_visible(timeout=T)
    expect(page.get_by_test_id("calc-cost-summary")).to_be_visible(timeout=T)
    shot(page, "01-native-cost-calculator", journey="cost_calc")

    # 4) The Save affordance is present (the mutation itself is backend-tested, not
    #    driven here — driving an approve through the browser would leave a stray row).
    expect(page.get_by_test_id("calc-save")).to_be_visible(timeout=T)
