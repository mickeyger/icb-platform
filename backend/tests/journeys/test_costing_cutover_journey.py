"""WO v4.30 §3.6 — Cost Calculator cutover smoke journey (admin + sales).

Post-cutover the Cost Calculator (server-rendered Jinja at /calculator) is served from icb-platform. This
smoke confirms the cutover didn't break the calculator or its per-role access:

  * both ADMIN and a SALES rep can open the calculator — sales reps create costings as part of the normal
    flow (WO §0.9), so the cutover must keep them in;
  * a NEW costing defaults the ratio dropdown to 55% (the v4.30 enhancement), exercised per role.

Per Testing Strategy v1.1, the smoke covers admin + the primary affected operational role (sales).

Selector note: the calculator is Jinja (no React data-testids); it's driven by its stable element IDs
(#trailer-select, #f-ratio) — the contract the calculator JS itself binds to via getElementById.
"""
from __future__ import annotations

from playwright.sync_api import Page, expect

from _common import admin_session, role_session, shot  # noqa: E402  (sys.path set in conftest)

T = 15_000
JOURNEY = "costing_cutover"


def _open_calculator(page: Page) -> None:
    page.goto("/calculator")
    expect(page.locator("#trailer-select")).to_be_visible(timeout=T)
    expect(page.locator("#f-ratio")).to_be_visible(timeout=T)


def test_calculator_admin_loads_and_defaults_ratio_55(page: Page) -> None:
    admin_session(page)
    _open_calculator(page)
    # WO v4.30 — a NEW costing defaults the ratio dropdown to 55% (option value 0.55).
    expect(page.locator("#f-ratio")).to_have_value("0.55", timeout=T)
    shot(page, "01-calculator-admin", journey=JOURNEY)


def test_calculator_sales_can_access(page: Page, live_server: str, role_users) -> None:
    # Sales reps create costings (WO §0.9) — the cutover must preserve their calculator access.
    role_session(page, role_users["sales"], base=live_server)
    _open_calculator(page)
    expect(page.locator("#f-ratio")).to_have_value("0.55", timeout=T)
    shot(page, "02-calculator-sales", journey=JOURNEY)
