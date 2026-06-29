"""WO v4.36e §3.4 — Dispatch-zone resilience journey (the v4.36c §3.6 deferral).

Regression-protection for the v4.36c flex-coupling that forced the dispatch-zone revert. The Dispatch
zone lives in the shared ``BayModelLanes``; on the Planning Board that section is wrapped in a
``shrink-0`` + ``max-h-[44vh]`` + ``overflow-y-auto`` container (PlanningBoard.tsx, §3.2 Phase B) so its
height can't perturb the ``flex-1`` week grid above it. This journey locks that invariant at the test
level: a future change that re-couples ``BayModelLanes``' height to the week grid will fail LOUDLY here
(slot-cell reflow / unbounded wrapper) instead of silently regressing — the exact gap the v4.36c revert
exposed and the §3.1 Playwright trace caught as a latent "slot-cell not stable" flake.

Render/structure-assertion style (the v4.29 prevention shift); read-only (the zone does no writes).
Self-cleaning module fixture (DZJ-marker rows; purge at setup AND teardown — the v4.32 self-healing rule).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from playwright.sync_api import Page, expect

from _common import admin_session, shot  # noqa: E402  (sys.path set in conftest)

T = 15_000
JOURNEY = "dispatch_zone"
DISP_VIN = "DZJVIN700"      # the dispatched chassis the zone renders a tile for
SCHED_JOB = "DZJ001"        # a current-week scheduled job → a week-grid slot-cell
DISP_JOB = "DZJ002"         # the dispatched chassis's job (for the tile's job_number)


def _purge(db) -> None:
    from sqlalchemy import text
    db.execute(text("DELETE FROM icb_mes.planning_slots WHERE bay = 'V-77'"))
    db.execute(text("DELETE FROM icb_mes.production_jobs WHERE job_number LIKE 'DZJ%'"))
    db.execute(text("DELETE FROM icb_mes.chassis_records WHERE vin LIKE 'DZJ%'"))
    db.commit()


@pytest.fixture(scope="module")
def dispatch_data():
    """The two anchors the journey needs: (1) a current-week scheduled job → a week-grid ``slot-cell``;
    (2) a ``dispatched`` chassis (+ its job, for the tile's job_number) → a tile in the Dispatch zone
    (``/api/qc/dispatched``). Module-scoped + self-cleaning."""
    from app.database import Branch, SessionLocal
    from app.models.mes import ChassisRecord, PlanningSlot, ProductionJob
    now = datetime.now(timezone.utc)
    today = now.date()
    monday = today - timedelta(days=today.weekday())
    with SessionLocal() as db:
        _purge(db)
        branch = db.query(Branch).order_by(Branch.id).first()
        # (1) a current-week scheduled job → a slot-cell in the week grid (the stability anchor).
        sched = ProductionJob(branch_id=branch.id, source="workbook", job_number=SCHED_JOB,
                              status="in_production", customer_name="DZJ Schedule Ltd",
                              description="DZJ scheduled body", accepted_at=now - timedelta(days=1))
        db.add(sched)
        db.flush()
        db.add(PlanningSlot(production_job_id=sched.id, week=monday, bay="V-77",
                            lane="vacuum", slot_position=77, status="scheduled"))
        # (2) a dispatched chassis → a tile in the Dispatch zone.
        rec = ChassisRecord(vin=DISP_VIN, source="manual", status="dispatched",
                            customer_name="DZJ Dispatch Ltd", make="Hino", model="500")
        db.add(rec)
        db.flush()
        db.add(ProductionJob(branch_id=branch.id, source="workbook", job_number=DISP_JOB,
                             status="completed", customer_name="DZJ Dispatch Ltd",
                             chassis_record_id=rec.id, accepted_at=now - timedelta(days=3)))
        db.commit()
    yield
    from app.database import SessionLocal as SL
    with SL() as db:
        _purge(db)


def test_dispatch_zone_renders_without_disrupting_grid(page: Page, dispatch_data) -> None:
    admin_session(page)
    nav = page.get_by_test_id("nav-planning")
    expect(nav).to_be_visible(timeout=T)
    nav.click()

    # Week grid is up — capture a slot-cell's position BEFORE the dispatch fetch grows the bay model.
    cell = page.get_by_test_id("slot-cell").first
    expect(cell).to_be_visible(timeout=T)
    box1 = cell.bounding_box()

    # Phase A — the Dispatch zone renders in the shared BayModelLanes, with our dispatched tile.
    expect(page.get_by_test_id("dispatch-zone")).to_be_visible(timeout=T)
    expect(page.get_by_test_id("dispatch-chassis").filter(has_text=DISP_VIN).first).to_be_visible(timeout=T)

    # Phase B — the bay-model section is height-BOUNDED + scroll-contained, so its growth (incl. the async
    # dispatch render just asserted) cannot perturb the flex-1 week grid. Lock the bound structurally.
    wrap = page.get_by_test_id("bay-model-wrap")
    expect(wrap).to_be_visible(timeout=T)
    m = wrap.evaluate("el => ({ ch: el.clientHeight, sh: el.scrollHeight, cls: el.className })")
    vh = page.viewport_size["height"]
    assert "max-h-" in m["cls"], f"bay-model-wrap lost its max-h bound: {m['cls']!r}"
    assert m["ch"] <= vh * 0.46, f"bay-model-wrap not height-bounded: clientHeight={m['ch']} (> 0.46*{vh})"

    # The week-grid slot-cell did NOT move while the dispatch zone loaded + grew (the symptom that flaked).
    page.wait_for_timeout(800)   # let any reflow settle
    box2 = cell.bounding_box()
    assert box1 and box2, "slot-cell bounding box unavailable"
    assert abs(box1["y"] - box2["y"]) < 3 and abs(box1["x"] - box2["x"]) < 3, \
        f"week-grid slot-cell reflowed after the dispatch zone loaded (flex coupling regressed): {box1} -> {box2}"

    # Isolation invariant — scrolling the bounded bay-model section must not move the week grid.
    wrap.evaluate("el => { el.scrollTop = el.scrollTop + 200 }")
    page.wait_for_timeout(300)
    box3 = cell.bounding_box()
    assert box3 and abs(box1["y"] - box3["y"]) < 3, \
        f"scrolling the bay model moved the week grid (not isolated): {box1} -> {box3}"

    shot(page, "01-dispatch-zone-grid-stable", journey=JOURNEY)
