"""WO v4.29 §3.6 — Planning Board per-role journey (D4/D5/D6), admin + planner (+ sales contrast).

The board's scheduling affordance is gated on `planning.schedule` (a server permission key): admin and
planner can drag/schedule; a role without it (sales) gets the read-only board. This journey proves the
per-role render — the prevention shift that the happy-path-as-admin suites missed. The ETA-gate quadrant
behaviour itself is asserted in test_v4_29_upstream_fixes.py (no irreversible drag here).
"""
from __future__ import annotations

from playwright.sync_api import Page, expect

from _common import admin_session, role_session, shot  # noqa: E402  (sys.path set in conftest)

T = 15_000
READONLY = "Read-only"   # "Read-only — your role can't schedule on the board."


def _open_board(page: Page) -> None:
    nav = page.get_by_test_id("nav-planning")
    expect(nav).to_be_visible(timeout=T)
    nav.click()
    expect(page.get_by_role("heading", name="Planning Board")).to_be_visible(timeout=T)


def test_planning_board_admin_can_schedule(page: Page) -> None:
    admin_session(page)
    _open_board(page)
    expect(page.get_by_text(READONLY)).to_have_count(0)        # admin wildcard -> interactive board
    shot(page, "01-board-admin", journey="planning_drag")


def test_planning_board_planner_can_schedule(page: Page, live_server: str, role_users) -> None:
    role_session(page, role_users["planner"], base=live_server)
    _open_board(page)
    expect(page.get_by_text(READONLY)).to_have_count(0)        # planner has planning.schedule
    shot(page, "02-board-planner", journey="planning_drag")


def test_planning_board_sales_is_readonly(page: Page, live_server: str, role_users) -> None:
    role_session(page, role_users["sales"], base=live_server)
    _open_board(page)
    expect(page.get_by_text(READONLY).first).to_be_visible(timeout=T)   # sales lacks planning.schedule
    shot(page, "03-board-sales-readonly", journey="planning_drag")
