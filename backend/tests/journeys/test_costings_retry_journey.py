"""WO v4.29 §3.6 — Costings retry-pill per-role journey (D1), admin + sales.

The "Retry job creation" pill lives on the Costings dashboard for an Accepted costing whose
production job wasn't created (the D1 partial state, now fixed server-side). This journey proves both
roles reach the Costings dashboard surface where the pill renders; the retry call itself
(from-calculation) is asserted server-side in test_v4_29_upstream_fixes.py (driving an irreversible
accept through the browser would leave a stray production_job — same policy as test_costing_journey).
"""
from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect

from _common import admin_session, role_session, shot  # noqa: E402  (sys.path set in conftest)

T = 15_000


def _open_costings(page: Page) -> None:
    nav = page.get_by_test_id("nav-costings")
    expect(nav).to_be_visible(timeout=T)
    nav.click()
    expect(page.get_by_test_id("costings-dashboard")).to_be_visible(timeout=T)
    expect(page.get_by_test_id("costings-table")).to_be_visible(timeout=T)


def test_costings_dashboard_admin(page: Page) -> None:
    admin_session(page)
    _open_costings(page)
    expect(page.get_by_test_id("costing-row").first).to_be_visible(timeout=T)
    shot(page, "01-costings-admin", journey="costings_retry")


def test_costings_dashboard_sales(page: Page, live_server: str, role_users) -> None:
    role_session(page, role_users["sales"], base=live_server)
    _open_costings(page)
    expect(page.get_by_test_id("costing-row").first).to_be_visible(timeout=T)
    shot(page, "02-costings-sales", journey="costings_retry")
