"""WO v4.35 §3.6 — body_attached event recording: pre-conditions, swap rule, gating, idempotency.

Exercises the record_body_attached chokepoint via its real endpoint (page.request, CSRF + role session)
+ SessionLocal DB assertions — the robust pattern for backend guarantees. body_attached is phase-only
(DEV-2): the event is logged but chassis_records.status stays 'in_assembly'.
"""
from __future__ import annotations

import pytest
from playwright.sync_api import Page

from _common import admin_session, role_session  # noqa: E402
import _v435 as h  # noqa: E402


@pytest.fixture(autouse=True)
def _clean():
    h.purge()
    yield
    h.purge()


def _post_attach(page, base, chassis_id, job_id, notes=None):
    return h.api_post(page, base, f"/api/chassis-records/{chassis_id}/body-attached",
                      {"production_job_id": job_id, "notes": notes})


# ── happy path (admin) — event logged, status unchanged (DEV-2) ──────────────────
def test_mark_body_attached_succeeds(page: Page, live_server: str) -> None:
    s = h.make_assembly_job()
    admin_session(page)
    r = _post_attach(page, live_server, s["chassis_id"], s["job_id"], "merged on the floor")
    assert r.status == 201, r.text()
    assert h.body_attached_event_count(s["chassis_id"]) == 1
    assert h.chassis_status(s["chassis_id"]) == "in_assembly"   # DEV-2 — phase-only, no status move


def test_planner_can_mark(page: Page, live_server: str, role_users) -> None:
    s = h.make_assembly_job()
    role_session(page, role_users["planner"], base=live_server)
    assert _post_attach(page, live_server, s["chassis_id"], s["job_id"]).status == 201


# ── pre-conditions (§0.4) ────────────────────────────────────────────────────────
def test_blocked_when_job_not_in_production(page: Page, live_server: str) -> None:
    s = h.make_assembly_job()
    from app.database import SessionLocal
    from app.models.mes import ProductionJob
    with SessionLocal() as db:                          # demote the job out of production
        db.get(ProductionJob, s["job_id"]).status = "planning"
        db.commit()
    admin_session(page)
    r = _post_attach(page, live_server, s["chassis_id"], s["job_id"])
    assert r.status == 422 and "in_production" in r.text()
    assert h.body_attached_event_count(s["chassis_id"]) == 0


def test_blocked_when_not_on_a_bay(page: Page, live_server: str) -> None:
    s = h.make_assembly_job()
    from app.database import SessionLocal
    from app.models.mes import ChassisLifecycleEvent
    from sqlalchemy import text
    with SessionLocal() as db:                          # remove the assembly_assigned event
        db.execute(text("DELETE FROM icb_mes.chassis_lifecycle_events WHERE chassis_record_id=:c "
                        "AND event_type='assembly_assigned'"), {"c": s["chassis_id"]})
        db.commit()
    admin_session(page)
    r = _post_attach(page, live_server, s["chassis_id"], s["job_id"])
    assert r.status == 422 and "bay" in r.text()
    assert h.body_attached_event_count(s["chassis_id"]) == 0


# ── §0.22 swap rule (DEV-1 planner-attestation signal) ───────────────────────────
def test_swap_blocked_when_attested_vin_mismatches(page: Page, live_server: str) -> None:
    s = h.make_assembly_job(attested_vin="ATTESTEDDIFFERENT1")   # card attests a DIFFERENT vin
    admin_session(page)
    r = _post_attach(page, live_server, s["chassis_id"], s["job_id"])
    assert r.status == 409 and "attested" in r.text()
    assert h.body_attached_event_count(s["chassis_id"]) == 0


def test_attach_allowed_when_attested_vin_matches(page: Page, live_server: str) -> None:
    s = h.make_assembly_job(vin="MATCHVIN000000001", attested_vin="MATCHVIN000000001")
    admin_session(page)
    assert _post_attach(page, live_server, s["chassis_id"], s["job_id"]).status == 201


# ── §0.22 double-linkage ─────────────────────────────────────────────────────────
def test_double_linkage_blocked(page: Page, live_server: str) -> None:
    a = h.make_assembly_job()                          # job A linked to chassis A
    b = h.make_assembly_job()                          # chassis B (on its own bay)
    admin_session(page)
    # attach chassis B to job A — but job A is already linked to chassis A
    r = _post_attach(page, live_server, b["chassis_id"], a["job_id"])
    assert r.status == 409 and "different chassis" in r.text()


# ── idempotency: a second mark on the same cycle is a 409, not a silent double ───
def test_idempotent_409_on_second_mark(page: Page, live_server: str) -> None:
    s = h.make_assembly_job(attached=True)             # already attached this cycle
    admin_session(page)
    r = _post_attach(page, live_server, s["chassis_id"], s["job_id"])
    assert r.status == 409 and "already attached" in r.text()
    assert h.body_attached_event_count(s["chassis_id"]) == 1   # unchanged


# ── §0.24 workshop is read-only: 403 on a direct call ────────────────────────────
def test_workshop_forbidden(page: Page, live_server: str, role_users) -> None:
    s = h.make_assembly_job()
    role_session(page, role_users["workshop"], base=live_server)
    r = _post_attach(page, live_server, s["chassis_id"], s["job_id"])
    assert r.status == 403
    assert h.body_attached_event_count(s["chassis_id"]) == 0
