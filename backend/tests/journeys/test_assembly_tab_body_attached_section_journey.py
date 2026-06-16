"""WO v4.35 §3.6 — Production Dashboard body_attached UI: 4-state bay tiles, KPI tile, Assembly
"Body Attached (today)" section, and the permission-gated "Mark body attached" affordance.

Browser (Playwright) assertions over the real screen, backed by P435 factory data on the shared
journey DB. The event-recording behaviour itself is covered by test_body_attached_event_journey.
"""
from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect

from _common import admin_session, role_session, shot  # noqa: E402
import _v435 as h  # noqa: E402

T = 15_000


@pytest.fixture(autouse=True)
def _clean():
    h.purge()
    yield
    h.purge()


def _open_production(page: Page) -> None:
    nav = page.get_by_test_id("nav-production_dashboard")
    expect(nav).to_be_visible(timeout=T)
    nav.click()
    page.wait_for_selector("[data-testid='production-kpis']", timeout=T)


def _tile(page: Page, bay_code: str):
    return page.locator(f"[data-testid='production-bay-tile'][data-bay-code='{bay_code}']")


# ── 4-state bay tiles + KPI ──────────────────────────────────────────────────────
def test_bay_tiles_render_states_and_kpi(page: Page, live_server: str) -> None:
    awaiting = h.make_assembly_job()
    attached = h.make_assembly_job(attached=True)
    admin_session(page)
    _open_production(page)
    expect(_tile(page, awaiting["bay_code"])).to_have_attribute("data-bay-state", "awaiting_attachment", timeout=T)
    expect(_tile(page, attached["bay_code"])).to_have_attribute("data-bay-state", "attached_today", timeout=T)
    # the attached tile carries the 🔗 badge
    expect(_tile(page, attached["bay_code"]).get_by_test_id("bay-badge")).to_be_visible()
    # the keystone KPI tile is present
    expect(page.get_by_text("Bodies attached today")).to_be_visible(timeout=T)
    shot(page, "01-bay-states-kpi", journey="bay_model")


# ── Assembly tab "Body Attached (today)" section ─────────────────────────────────
def test_assembly_section_lists_today(page: Page, live_server: str) -> None:
    s = h.make_assembly_job(attached=True)
    admin_session(page)
    _open_production(page)
    page.get_by_test_id("team-tab-assembly").click()
    section = page.get_by_test_id("worksheet-body_attached_today")
    expect(section).to_be_visible(timeout=T)
    expect(section).to_contain_text("P435")            # my attached job/chassis is listed (marker)
    shot(page, "02-assembly-section", journey="bay_model")


# ── SidePanel affordance: admin/planner see it; workshop/sales get a read-only note ──
def test_sidepanel_affordance_visible_for_admin(page: Page, live_server: str) -> None:
    s = h.make_assembly_job()                          # awaiting → the "Mark body attached" target
    admin_session(page)
    _open_production(page)
    _tile(page, s["bay_code"]).click()
    expect(page.get_by_test_id("bay-lifecycle")).to_be_visible(timeout=T)
    expect(page.get_by_test_id("mark-attached-section")).to_be_visible()
    expect(page.get_by_test_id("mark-body-attached")).to_be_visible()
    shot(page, "03-mark-attached-affordance", journey="bay_model")


def test_sidepanel_readonly_for_workshop(page: Page, live_server: str, role_users) -> None:
    s = h.make_assembly_job()
    role_session(page, role_users["workshop"], base=live_server)
    _open_production(page)
    _tile(page, s["bay_code"]).click()
    expect(page.get_by_test_id("bay-lifecycle")).to_be_visible(timeout=T)
    expect(page.get_by_test_id("mark-attached-readonly")).to_be_visible()
    expect(page.get_by_test_id("mark-body-attached")).to_have_count(0)   # §0.24 — no write affordance
    shot(page, "04-workshop-readonly", journey="bay_model")
