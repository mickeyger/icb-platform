"""WO v4.35 §3.6 — the Burt demo walkthrough, focused on the body_attached keystone moment.

The upstream lifecycle (costing → pre-job → sign-offs → ack → schedule → vacuum) is covered by the
existing costing / prejob / planning journeys; this asserts the NEW moment end-to-end through the real
UI: a planner opens an in-assembly bay, marks the body attached, and the screen responds (bay flips,
KPI ticks, Assembly section gains the job) while the v4.34.4 invariants stay clean.
"""
from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect

from _common import admin_session, shot  # noqa: E402
import _v435 as h  # noqa: E402

T = 15_000


@pytest.fixture(autouse=True)
def _clean():
    h.purge()
    yield
    h.purge()


def _kpi_attached_today() -> int:
    from app.database import SessionLocal
    from app.services.production_jobs import compute_production_kpis
    with SessionLocal() as db:
        return compute_production_kpis(db)["bodies_attached_today"]


def _invariant_violations() -> int:
    """Total v4.34.4 invariant violations across the DB. We assert the body_attached action introduces
    NO NEW ones (a before/after delta) — NOT that the seed is globally clean: the icb_test seed
    (seed_from_mockup) predates these invariants, whereas the v4.35 demo DB is gated clean."""
    from app.database import SessionLocal
    from app.services import integrity
    with SessionLocal() as db:
        r = integrity.run_health_checks(db)
        return (len(r["invariant_1_confirmed_cards_without_job"])
                + len(r["invariant_2_calc_status_strays"])
                + len(r["invariant_3_anchorless_chassis"]))


def test_mark_body_attached_end_to_end(page: Page, live_server: str) -> None:
    s = h.make_assembly_job()                          # an in-assembly bay awaiting attachment
    kpi_before = _kpi_attached_today()
    viol_before = _invariant_violations()              # baseline (seed may carry pre-existing ones)

    admin_session(page)
    h.open_production(page)                             # robust nav (visible → click → wait → reload-retry)
    tile = page.locator(f"[data-testid='production-bay-tile'][data-bay-code='{s['bay_code']}']")
    expect(tile).to_have_attribute("data-bay-state", "awaiting_attachment", timeout=T)

    # The demo moment: open the bay → the lifecycle shows Body attached ○ → mark it.
    tile.click()
    expect(page.get_by_test_id("bay-lifecycle")).to_be_visible(timeout=T)
    page.get_by_test_id("attach-notes").fill("Body mated to chassis — demo")
    page.get_by_test_id("mark-body-attached").click()

    # The screen responds: the bay flips to attached_today (pessimistic refetch).
    expect(tile).to_have_attribute("data-bay-state", "attached_today", timeout=T)
    shot(page, "01-after-attach", journey="production_dashboard")

    # Backend truth: one event, status unchanged (DEV-2), KPI ticked, invariants still clean.
    assert h.body_attached_event_count(s["chassis_id"]) == 1
    assert h.chassis_status(s["chassis_id"]) == "in_assembly"
    assert _kpi_attached_today() == kpi_before + 1
    assert _invariant_violations() == viol_before      # body_attached introduced NO new violation

    # The Assembly tab "Body Attached (today)" section now lists the job.
    page.get_by_test_id("team-tab-assembly").click()
    expect(page.get_by_test_id("worksheet-body_attached_today")).to_contain_text("P435", timeout=T)
