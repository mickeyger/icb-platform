"""WO v4.27 §3.7 — Costing journey (read-path through the Costings module).

Uses the v4.26.1 `_common.py` shell. Drives the Costings module end-to-end in a real browser:
autologin → Costings dashboard renders the live costings → open a costing's detail.

Scope note: the accept → BOM-persist mutation is covered deterministically (and without DB
pollution) by the backend hook tests (`test_v4_27_bom_on_accept`) + the rules-engine parity tests
— driving an irreversible accept through the browser would leave a stray production_job. The full
wizard-driven accept journey (select customer → spec dropdowns → accept) lands with the costing-
wizard rewire (a separate WO); this journey covers the costing UI read-path that exists today.

Run locally (after `npm run build` + `playwright install chromium`):
    pytest backend/tests/journeys/test_costing_journey.py -v
"""
from __future__ import annotations

import re

from playwright.sync_api import Page, expect

from _common import admin_session, shot  # noqa: E402  (sys.path set in conftest)

T = 15_000


def test_costing_journey(page: Page) -> None:
    # 1) Autologin as admin and land on the authenticated shell.
    admin_session(page)

    # 2) Open the Costings module from the top nav.
    nav = page.get_by_test_id("nav-costings")
    expect(nav).to_be_visible(timeout=T)
    nav.click()

    # 3) The dashboard + its table render with the live costings.
    expect(page.get_by_test_id("costings-dashboard")).to_be_visible(timeout=T)
    expect(page.get_by_test_id("costings-table")).to_be_visible(timeout=T)
    shot(page, "01-costings-dashboard", journey="costing")

    # 4) Seeded data is present (mock-seeded CI + real local both have costings).
    rows = page.get_by_test_id("costing-row")
    expect(rows.first).to_be_visible(timeout=T)

    # 5) Open the first costing's detail (read-path; no mutation) — the SPA routes without crashing.
    rows.first.click()
    expect(page).to_have_url(re.compile(r"/costings/.+"), timeout=T)
    expect(page.get_by_test_id("top-nav")).to_be_visible(timeout=T)
    shot(page, "02-costing-detail", journey="costing")
