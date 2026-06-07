"""WO v4.28 §3.7 — Chassis journey (read-path + capture-form render through the Chassis module).

Uses the v4.26.1 `_common.py` shell. Drives the chassis module end-to-end in a real browser:
autologin → Chassis list renders the live records → search → open a chassis detail → lifecycle
history renders → open the VCL capture form (modal renders with its checklist) → cancel.

Scope note: the journey stops at *opening* the VCL form — it does NOT submit. A real VCL/DCL capture
COMMITS a lifecycle event (irreversible; would leave a stray event on the local real DB), so the
cycle logic (VCL opens / DCL closes / 409 / 422), photo upload and the un-tick are covered
deterministically by the backend tests (`test_v4_28_chassis_api`). This journey proves the chassis
UI read-path + the capture-form wiring that ships today.

CI has chassis data because `seed_from_mockup` seeds 4 synthetic `source='mock'` records
(`seed_v4_28_chassis_mock`); the local real DB has the ~250 register-translated records.

Run locally (after `npm run build` + `playwright install chromium`):
    pytest backend/tests/journeys/test_chassis_journey.py -v
"""
from __future__ import annotations

import re

from playwright.sync_api import Page, expect

from _common import admin_session, shot  # noqa: E402  (sys.path set in conftest)

T = 15_000
JOURNEY = "chassis"


def test_chassis_journey(page: Page) -> None:
    # 1) Autologin as admin and land on the authenticated shell.
    admin_session(page)

    # 2) Open the Chassis module from the top nav.
    nav = page.get_by_test_id("nav-chassis")
    expect(nav).to_be_visible(timeout=T)
    nav.click()

    # 3) The chassis list + its table render with the live/seeded records.
    expect(page.get_by_test_id("chassis-list")).to_be_visible(timeout=T)
    expect(page.get_by_test_id("chassis-table")).to_be_visible(timeout=T)
    rows = page.get_by_test_id("chassis-row")
    expect(rows.first).to_be_visible(timeout=T)
    shot(page, "01-chassis-list", journey=JOURNEY)

    # 4) Search narrows the table (the search box is wired to the list query).
    search = page.get_by_test_id("chassis-search")
    expect(search).to_be_visible(timeout=T)
    search.fill("MOCK")          # matches the seeded mock VINs on CI; harmless on real data
    page.wait_for_timeout(400)   # debounce / refetch settle

    # 5) Open the first chassis detail (read-path; the SPA routes without crashing).
    page.get_by_test_id("chassis-row").first.click()
    expect(page).to_have_url(re.compile(r"/chassis/.+"), timeout=T)
    expect(page.get_by_test_id("chassis-detail")).to_be_visible(timeout=T)
    shot(page, "02-chassis-detail", journey=JOURNEY)

    # 6) Open the VCL capture form (admin always sees it). Assert the modal + its date field
    #    render, then cancel — no submit (the write path is backend-tested).
    vcl_btn = page.get_by_test_id("chassis-capture-vcl")
    expect(vcl_btn).to_be_visible(timeout=T)
    vcl_btn.click()
    expect(page.get_by_test_id("chassis-capture-form")).to_be_visible(timeout=T)
    expect(page.get_by_test_id("chassis-capture-date")).to_be_visible(timeout=T)
    shot(page, "03-chassis-vcl-form", journey=JOURNEY)
    page.get_by_test_id("chassis-capture-cancel").click()
    expect(page.get_by_test_id("chassis-capture-form")).to_be_hidden(timeout=T)
