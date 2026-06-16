"""WO v4.34.2 §3.4 — Scheduled → Unscheduled revert per-role journey (7 scenarios).

Proves the single guarded chokepoint (services/planning.unschedule) behind BOTH the modal
(POST /api/production-jobs/{id}/revert-to-unscheduled) and the drag (DELETE /api/planning-slots/{id})
paths, and — per the BA — that it PRESERVES the v4.34.4 invariants and writes a consistent audit row.

Structure (matched to where each guarantee actually lives):
* Browser (Playwright) — the per-role UI affordance: a planner sees the "↩ Move back to Unscheduled"
  control on a scheduled job; workshop + sales do not.
* page.request (role-scoped API, CSRF from the session row) + SessionLocal DB assertions — the
  behavioural + state proof: modal vs drag, the §0.3 gating (409), the workshop 403, the recency sort,
  and the explicit v4.34.4 invariant + audit-consistency checks. This is the robust pattern for backend
  guarantees (no fragile HTML5-drag simulation — the drag path's contract is the DELETE endpoint).

Marker rows: quote_number / job_number / chassis.make prefixed PLREV; self-healing teardown (CASCADE
from the job clears its audit + work_orders). The journey server shares this DB, so DB setup is visible.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

import pytest
from playwright.sync_api import Page, expect

from _common import admin_session, role_session, shot  # noqa: E402  (sys.path set in conftest)

T = 15_000
MARK = "PLREV"
_RECEIVED = datetime(2026, 1, 1, tzinfo=timezone.utc)


# ── DB helpers (the journey server shares this database) ─────────────────────────
def _csrf(page: Page) -> str:
    """The session's CSRF token (read from the UserSession row keyed by the session_id cookie), so
    page.request can make authenticated unsafe calls the same way the SPA's fetch wrapper does."""
    from app.database import SessionLocal, UserSession
    sid = next((c["value"] for c in page.context.cookies() if c["name"] == "session_id"), None)
    assert sid, "no session_id cookie — autologin did not establish a session"
    with SessionLocal() as db:
        row = db.get(UserSession, sid)
        assert row is not None, "session row missing"
        return row.csrf_token or ""


def _post(page: Page, base: str, path: str, body: dict) -> "object":
    return page.request.post(f"{base}{path}", data=body,
                             headers={"X-CSRF-Token": _csrf(page), "Origin": base})


def _delete(page: Page, base: str, path: str) -> "object":
    return page.request.delete(f"{base}{path}",
                               headers={"X-CSRF-Token": _csrf(page), "Origin": base})


def _make_scheduled(*, started: bool = False, qc: bool = False, chassis: bool = True) -> dict:
    """Create a fresh status='planning' job (+ calc, optional linked chassis), scheduled into a unique
    bay in the CURRENT week (so it shows on the board's default rolling window). started/qc add a
    workshop-started work_order / a completed QC task to exercise the §0.3 gating."""
    from app.database import Branch, CalculationRecord, SessionLocal
    from app.models.mes import ChassisRecord, ProductionJob, Task, WorkOrder
    from app.services import planning as pl

    tag = uuid.uuid4().hex[:6]
    with SessionLocal() as db:
        jhb = db.query(Branch).filter_by(code="JHB").first()
        calc = CalculationRecord(
            quote_number=f"{MARK}-{tag}", status="planning", branch_id=jhb.id,
            dimensions_json='{"body_type": "Revert Test"}', result_json='{"selling_zar": 1000.0}')
        db.add(calc)
        db.flush()
        chassis_id = None
        if chassis:
            ch = ChassisRecord(make=f"{MARK} Chassis {tag}", status="received", source="manual",
                               created_via="manual_chassis_menu", vin=f"{MARK}{tag}")
            db.add(ch)
            db.flush()
            chassis_id = ch.id
        job = ProductionJob(
            calculation_record_id=calc.id, branch_id=jhb.id, status="planning",
            job_number=f"{MARK}{tag}", chassis_received_at=_RECEIVED, chassis_record_id=chassis_id)
        db.add(job)
        db.flush()
        if started or qc:
            wo = WorkOrder(production_job_id=job.id,
                           started_at=(datetime(2026, 1, 2, tzinfo=timezone.utc) if started else None))
            db.add(wo)
            db.flush()
            if qc:
                db.add(Task(work_order_id=wo.id, completed_at=datetime(2026, 1, 3, tzinfo=timezone.utc)))
        db.commit()
        jid, cid = job.id, calc.id

    bay = f"QA-{MARK}-{tag}"
    with SessionLocal() as db:
        slot = pl.schedule(db, production_job_id=jid, week=date.today(), bay=bay, lane="vacuum", user=None)
        sid = slot.id
    return {"job_id": jid, "calc_id": cid, "slot_id": sid, "chassis_id": chassis_id, "bay": bay}


def _audit_rows(job_id: int) -> list:
    from app.database import SessionLocal
    from app.models.mes import ProductionJobAudit
    from sqlalchemy import select
    with SessionLocal() as db:
        return list(db.execute(
            select(ProductionJobAudit).where(ProductionJobAudit.production_job_id == job_id)
            .order_by(ProductionJobAudit.id)).scalars().all())


def _job(job_id: int):
    from app.database import SessionLocal
    from app.models.mes import ProductionJob
    with SessionLocal() as db:
        return db.get(ProductionJob, job_id)


def _calc_status(calc_id: int) -> str:
    from app.database import CalculationRecord, SessionLocal
    with SessionLocal() as db:
        return db.get(CalculationRecord, calc_id).status


def _has_slot(job_id: int) -> bool:
    from app.database import SessionLocal
    from app.models.mes import PlanningSlot
    from sqlalchemy import select
    with SessionLocal() as db:
        return db.execute(
            select(PlanningSlot.id).where(PlanningSlot.production_job_id == job_id)).first() is not None


@pytest.fixture(autouse=True)
def _cleanup():
    yield
    from app.database import SessionLocal
    from sqlalchemy import text
    with SessionLocal() as db:
        db.execute(text("DELETE FROM icb_mes.planning_slots WHERE bay LIKE 'QA-PLREV-%'"))
        # deleting the job CASCADEs its production_jobs_audit + work_orders (+ tasks)
        db.execute(text("DELETE FROM icb_mes.production_jobs WHERE job_number LIKE 'PLREV%'"))
        db.execute(text("DELETE FROM icb_mes.chassis_records WHERE make LIKE 'PLREV%'"))
        db.execute(text("DELETE FROM icb_costings.calculations WHERE quote_number LIKE 'PLREV%'"))
        db.commit()


def _open_board(page: Page) -> None:
    nav = page.get_by_test_id("nav-planning")
    expect(nav).to_be_visible(timeout=T)
    nav.click()
    expect(page.get_by_role("heading", name="Planning Board")).to_be_visible(timeout=T)


def _open_slot(page: Page, job_id: int):
    cell = page.locator(f"[data-testid='slot-cell'][data-job-id='{job_id}']")
    expect(cell).to_be_visible(timeout=T)
    cell.click()


# ── 1. planner CAN revert via the modal affordance; invariants + audit preserved ─
def test_planner_modal_revert_preserves_invariants_and_audits(page: Page, live_server: str, role_users) -> None:
    s = _make_scheduled()
    base = live_server
    # UI affordance: a planner sees the revert control on the scheduled job.
    role_session(page, role_users["planner"], base=base)
    _open_board(page)
    _open_slot(page, s["job_id"])
    expect(page.get_by_test_id("revert-section")).to_be_visible(timeout=T)
    expect(page.get_by_test_id("revert-to-unscheduled")).to_be_visible()
    shot(page, "01-planner-revert-affordance", journey="unschedule_revert")

    # Behaviour via the modal's exact endpoint (CSRF + role session).
    chassis_before = _job(s["job_id"]).chassis_record_id
    r = _post(page, base, f"/api/production-jobs/{s['job_id']}/revert-to-unscheduled",
              {"reason": "Customer pushed the delivery date"})
    assert r.status == 200, r.text()

    # job left the board (no slot), back in the pool, but the JOB itself still exists.
    assert _has_slot(s["job_id"]) is False
    job = _job(s["job_id"])
    assert job is not None                                  # v4.34.4 Invariant 1 — card→job: the job is not deleted
    # Invariant 2 — calc.status unchanged (still in the planning cycle, no pre_job_sent boundary).
    assert _calc_status(s["calc_id"]) == "planning"
    assert job.status == "planning"
    # Invariant 3 — chassis assignment intact (production_jobs.chassis_record_id is the link, kept).
    assert job.chassis_record_id == chassis_before and chassis_before is not None
    # Audit consistency — one row, reason persisted, scheduling transition + slot placement captured.
    rows = _audit_rows(s["job_id"])
    assert len(rows) == 1
    a = rows[0]
    assert a.reason == "Customer pushed the delivery date"
    assert a.previous_status == "scheduled" and a.new_status == "unscheduled"
    assert a.previous_lane == "vacuum" and a.previous_bay == s["bay"]
    assert a.action == "revert_to_unscheduled"


# ── 2. reason is optional (modal, empty) ─────────────────────────────────────────
def test_modal_revert_reason_optional(page: Page, live_server: str, role_users) -> None:
    s = _make_scheduled()
    role_session(page, role_users["planner"], base=live_server)
    r = _post(page, live_server, f"/api/production-jobs/{s['job_id']}/revert-to-unscheduled", {})
    assert r.status == 200, r.text()
    rows = _audit_rows(s["job_id"])
    assert len(rows) == 1 and rows[0].reason is None       # §0.7 — empty reason accepted → NULL


# ── 3. drag-to-pool (the DELETE chokepoint) — same guard, audit reason NULL ───────
def test_drag_path_unschedule_audits_with_null_reason(page: Page, live_server: str, role_users) -> None:
    s = _make_scheduled()
    role_session(page, role_users["planner"], base=live_server)
    r = _delete(page, live_server, f"/api/planning-slots/{s['slot_id']}")
    assert r.status == 200, r.text()
    assert _has_slot(s["job_id"]) is False
    rows = _audit_rows(s["job_id"])
    assert len(rows) == 1
    assert rows[0].reason is None                           # drag path captures no reason
    assert rows[0].previous_status == "scheduled" and rows[0].new_status == "unscheduled"
    # invariants hold on the drag path too
    job = _job(s["job_id"])
    assert job is not None and job.status == "planning" and job.chassis_record_id == s["chassis_id"]
    assert _calc_status(s["calc_id"]) == "planning"


# ── 4. workshop-started job — revert blocked at gating (both paths) ───────────────
def test_workshop_started_revert_blocked(page: Page, live_server: str, role_users) -> None:
    s = _make_scheduled(started=True)
    role_session(page, role_users["planner"], base=live_server)
    r = _post(page, live_server, f"/api/production-jobs/{s['job_id']}/revert-to-unscheduled", {})
    assert r.status == 409, r.text()
    assert _has_slot(s["job_id"]) is True                  # still scheduled — nothing changed
    assert _audit_rows(s["job_id"]) == []                  # no audit row on a blocked revert
    # the drag DELETE is guarded by the SAME chokepoint → also 409
    assert _delete(page, live_server, f"/api/planning-slots/{s['slot_id']}").status == 409


# ── 5. QC-ticked job — revert blocked at gating ──────────────────────────────────
def test_qc_ticked_revert_blocked(page: Page, live_server: str, role_users) -> None:
    s = _make_scheduled(qc=True)
    role_session(page, role_users["planner"], base=live_server)
    r = _post(page, live_server, f"/api/production-jobs/{s['job_id']}/revert-to-unscheduled", {})
    assert r.status == 409, r.text()
    assert _has_slot(s["job_id"]) is True
    assert _audit_rows(s["job_id"]) == []


# ── 6. workshop role — NO affordance in the UI + 403 on a direct call ────────────
def test_workshop_role_no_affordance_and_403(page: Page, live_server: str, role_users) -> None:
    s = _make_scheduled()
    role_session(page, role_users["workshop"], base=live_server)
    _open_board(page)
    _open_slot(page, s["job_id"])
    expect(page.get_by_test_id("revert-section")).to_have_count(0)   # workshop lacks planning.unschedule
    shot(page, "06-workshop-no-affordance", journey="unschedule_revert")
    # direct API call is refused (403) — the server is the source of truth, not the hidden button
    r = _post(page, live_server, f"/api/production-jobs/{s['job_id']}/revert-to-unscheduled", {})
    assert r.status == 403, r.text()
    assert _has_slot(s["job_id"]) is True


# ── 7. revert re-puts the job at the TOP of the Unscheduled pool (§0.8) ───────────
def test_reverted_job_sorts_to_top_of_pool(page: Page, live_server: str, role_users) -> None:
    # Two fresh planning jobs already sit in the pool by id order; scheduling then reverting the OLDER
    # one must float it above the younger (recency sort), proving §0.8.
    older = _make_scheduled()
    younger = _make_scheduled()
    # unschedule both so they're in the pool, reverting the OLDER one LAST → it should sort first.
    role_session(page, role_users["planner"], base=live_server)
    assert _delete(page, live_server, f"/api/planning-slots/{younger['slot_id']}").status == 200
    assert _delete(page, live_server, f"/api/planning-slots/{older['slot_id']}").status == 200

    from app.database import SessionLocal
    from app.services import planning as pl
    with SessionLocal() as db:
        pool_ids = [j.id for j in pl._unscheduled_pool(db)]
    assert older["job_id"] in pool_ids and younger["job_id"] in pool_ids
    # the most-recently-reverted (older job, reverted last) sorts ahead of the younger one
    assert pool_ids.index(older["job_id"]) < pool_ids.index(younger["job_id"])


# ── 8. admin can revert too (Testing Strategy v1.1 — admin + primary role) ────────
def test_admin_can_revert(page: Page, live_server: str) -> None:
    s = _make_scheduled()
    admin_session(page)
    r = _post(page, live_server, f"/api/production-jobs/{s['job_id']}/revert-to-unscheduled",
              {"reason": "admin reshuffle"})
    assert r.status == 200, r.text()
    assert _has_slot(s["job_id"]) is False
    rows = _audit_rows(s["job_id"])
    assert len(rows) == 1 and rows[0].reason == "admin reshuffle"
