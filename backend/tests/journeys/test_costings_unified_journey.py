"""WO v4.31 §3.5 — Unified Costings dashboard per-role journey: admin + sales.

Per Testing Strategy v1.1: admin + the primary affected role (sales lives in the dashboard).
Asserts the §0.6/§0.13 contract per role: the SAME component renders full on /costings and
compressed (embedded) below the calculator iframe on /costings/new, with the §3.4 KPI strip
(5 metric tiles) present in BOTH contexts. Read-path only — no mutations.
"""
from __future__ import annotations

from playwright.sync_api import Page, expect

from _common import admin_session, role_session, shot  # noqa: E402  (sys.path set in conftest)

T = 15_000
JOURNEY = "costings_unified"


def _assert_both_contexts(page: Page, prefix: str) -> None:
    # Context 1 — /costings: full dashboard + KPI strip + table.
    nav = page.get_by_test_id("nav-costings")
    expect(nav).to_be_visible(timeout=T)
    nav.click()
    expect(page.get_by_test_id("costings-dashboard")).to_be_visible(timeout=T)
    kpis = page.get_by_test_id("costings-kpis")
    expect(kpis).to_be_visible(timeout=T)
    expect(kpis.get_by_text("Quotes this week")).to_be_visible(timeout=T)
    expect(kpis.get_by_text("Approval rate")).to_be_visible(timeout=T)
    expect(page.get_by_test_id("costings-table")).to_be_visible(timeout=T)
    shot(page, f"{prefix}-costings-full", journey=JOURNEY)

    # Context 2 — /costings/new: calculator iframe on top + the SAME component embedded below.
    page.goto("/mes-app/costings/new")
    expect(page.locator("iframe[title='Calculator (live costing app)']")).to_be_visible(timeout=T)
    embedded = page.get_by_test_id("costings-dashboard-embedded")
    expect(embedded).to_be_visible(timeout=T)
    expect(embedded.get_by_test_id("costings-kpis")).to_be_visible(timeout=T)     # tiles inherited
    expect(embedded.get_by_test_id("costings-table")).to_be_visible(timeout=T)    # actions context
    expect(embedded.get_by_text("New Costing")).to_have_count(0)                  # self-link omitted
    embedded.scroll_into_view_if_needed()
    shot(page, f"{prefix}-costings-new-embedded", journey=JOURNEY)


def test_costings_unified_admin(page: Page) -> None:
    admin_session(page)
    _assert_both_contexts(page, "01-admin")


def test_costings_unified_sales(page: Page, live_server: str, role_users) -> None:
    # Sales reps live in the dashboard (and create costings via the embedded calculator page).
    role_session(page, role_users["sales"], base=live_server)
    _assert_both_contexts(page, "02-sales")
