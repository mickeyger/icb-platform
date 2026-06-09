"""WO v4.29 §3.6 — Pre-Job acknowledge per-role journey (D2), admin + sales + production.

The "Awaiting Planning ack" pulsing cards live on the Planning Board's unscheduled pool; the
Acknowledge action is gated on `planning.acknowledge` (admin + planner + production have it; sales does
not). This journey proves each role reaches the board / ack surface (the D2 deadlock fix makes the ack
itself complete — asserted in test_v4_29_upstream_fixes.py). Each role renders the board without the
auth guard bouncing it — the per-role coverage the admin-only suites lacked.
"""
from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect

from _common import admin_session, role_session, shot  # noqa: E402  (sys.path set in conftest)

T = 15_000


def _open_board(page: Page) -> None:
    nav = page.get_by_test_id("nav-planning")
    expect(nav).to_be_visible(timeout=T)
    nav.click()
    expect(page.get_by_role("heading", name="Planning Board")).to_be_visible(timeout=T)


def test_prejob_ack_board_admin(page: Page) -> None:
    admin_session(page)
    _open_board(page)
    expect(page.get_by_text("Unscheduled").first).to_be_visible(timeout=T)
    shot(page, "01-ack-admin", journey="prejob_ack")


@pytest.mark.parametrize("role", ["sales", "production"])
def test_prejob_ack_board_per_role(page: Page, live_server: str, role_users, role: str) -> None:
    role_session(page, role_users[role], base=live_server)
    _open_board(page)
    expect(page.get_by_text("Unscheduled").first).to_be_visible(timeout=T)
    shot(page, f"02-ack-{role}", journey="prejob_ack")
