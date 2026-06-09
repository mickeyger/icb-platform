"""WO v4.29 §3.6 — Chassis → Planning link journey (D3 read-bridge), admin role.

Drives the Chassis module in a real browser: autologin as admin → Chassis list renders the live
chassis records → open a record's detail (VCL/DCL capture surface). The VCL→Planning read-bridge
itself (chassis_received_signal) is asserted deterministically in test_v4_29_upstream_fixes.py; this
journey proves the admin-role chassis UI path renders end-to-end.

Run locally (after `npm run build` + `playwright install chromium`):
    pytest backend/tests/journeys/test_chassis_link_journey.py -v
"""
from __future__ import annotations

from playwright.sync_api import Page, expect

from _common import admin_session, shot  # noqa: E402  (sys.path set in conftest)

T = 15_000


def test_chassis_link_journey_admin(page: Page) -> None:
    admin_session(page)

    nav = page.get_by_test_id("nav-chassis")
    expect(nav).to_be_visible(timeout=T)
    nav.click()

    expect(page.get_by_test_id("chassis-list")).to_be_visible(timeout=T)
    expect(page.get_by_test_id("chassis-table")).to_be_visible(timeout=T)
    rows = page.get_by_test_id("chassis-row")
    expect(rows.first).to_be_visible(timeout=T)
    shot(page, "01-chassis-list", journey="chassis_link")

    # Open a chassis record → the detail + VCL capture surface (the D3 write path) render.
    rows.first.click()
    expect(page.get_by_test_id("chassis-detail")).to_be_visible(timeout=T)
    expect(page.get_by_test_id("chassis-capture-vcl")).to_be_visible(timeout=T)
    shot(page, "02-chassis-detail", journey="chassis_link")
