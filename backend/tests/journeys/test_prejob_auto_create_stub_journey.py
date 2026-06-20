"""WO v4.36a.4 — Pre-Job submit anchors a chassis STUB even for a bare fresh costing.

Drives the real submit-for-check chokepoint (the path that was silently no-opping) via page.request on a
card with NO chassis make/model, and asserts a chassis_records row is anchored + linked. Runs on icb_test
(CI). FK-safe teardown captures the job-linked stub (job→chassis is ON DELETE RESTRICT) before deleting.
"""
from __future__ import annotations

import uuid

import pytest
from playwright.sync_api import Page

from _common import admin_session  # noqa: E402  (sys.path set in conftest)

MARK = "J436A4"


def _csrf(page) -> str:
    from app.database import SessionLocal, UserSession
    sid = next((c["value"] for c in page.context.cookies() if c["name"] == "session_id"), None)
    assert sid, "no session_id cookie — autologin did not establish a session"
    with SessionLocal() as db:
        row = db.get(UserSession, sid)
        return (row.csrf_token if row else "") or ""


def _make_bare_card() -> dict:
    """A draft Pre-Job Card with NO chassis make/model (the bare-fresh-costing case), on an 'accepted'
    job, with signers chosen + body gap set so submit-for-check passes its preconditions. Returns
    {card_id, job_id, calc_id}."""
    from app.database import Branch, CalculationRecord, SessionLocal, User
    from app.models.mes import PrejobCard, PrejobTemplate, ProductionJob
    tag = uuid.uuid4().hex[:6]
    with SessionLocal() as db:
        branch = db.query(Branch).order_by(Branch.id).first()
        tpl = db.query(PrejobTemplate).filter_by(is_active=True).order_by(PrejobTemplate.id).first()
        admin = db.query(User).filter_by(username="admin").first()
        calc = CalculationRecord(quote_number=f"{MARK}-{tag}", status="accepted", branch_id=branch.id,
                                 dimensions_json='{"body_type": "Chiller"}', result_json='{"selling_zar": 1000.0}')
        db.add(calc); db.flush()
        job = ProductionJob(calculation_record_id=calc.id, branch_id=branch.id, status="accepted",
                            job_number=f"{MARK}{tag}", source="quote")          # no chassis yet
        db.add(job); db.flush()
        card = PrejobCard(calculation_id=calc.id, template_id=(tpl.id if tpl else None),
                          body_description=f"{MARK} card", chassis_make_model=None, vin_number=None,
                          body_gap_mm=100, status="draft",
                          sales_rep_user_id=admin.id, planner_user_id=admin.id,
                          sections=[{"name": "S", "items": [{"text": "x"}]}])
        db.add(card); db.commit()
        return {"card_id": card.id, "job_id": job.id, "calc_id": calc.id}


def _chassis_for_job(job_id: int):
    from app.database import SessionLocal
    from app.models.mes import ChassisRecord, ProductionJob
    with SessionLocal() as db:
        job = db.get(ProductionJob, job_id)
        if job is None or job.chassis_record_id is None:
            return None
        c = db.get(ChassisRecord, job.chassis_record_id)
        return {"id": c.id, "make": c.make, "vin": c.vin, "status": c.status,
                "created_via": c.created_via, "deleted_at": c.deleted_at}


def _purge() -> None:
    from app.database import SessionLocal
    from sqlalchemy import text
    with SessionLocal() as db:
        # capture stub chassis linked to our jobs BEFORE the jobs go (job→chassis is ON DELETE RESTRICT)
        ids = [r[0] for r in db.execute(text(
            "SELECT chassis_record_id FROM icb_mes.production_jobs "
            f"WHERE job_number LIKE '{MARK}%' AND chassis_record_id IS NOT NULL")).fetchall()]
        db.execute(text(f"DELETE FROM icb_mes.prejob_cards WHERE body_description LIKE '{MARK}%'"))
        db.execute(text(f"DELETE FROM icb_mes.production_jobs WHERE job_number LIKE '{MARK}%'"))
        if ids:
            db.execute(text("DELETE FROM icb_mes.chassis_lifecycle_events WHERE chassis_record_id = ANY(:i)"), {"i": ids})
            db.execute(text("DELETE FROM icb_mes.chassis_records WHERE id = ANY(:i)"), {"i": ids})
        db.execute(text(f"DELETE FROM icb_costings.calculations WHERE quote_number LIKE '{MARK}%'"))
        db.commit()


@pytest.fixture(autouse=True)
def _clean():
    _purge()
    yield
    _purge()


def test_prejob_submit_anchors_chassis_stub_for_fresh_costing(page: Page, live_server: str) -> None:
    """Asserts the BA-confirmed v4.36a.4 contract: Pre-Job submission always
    anchors a chassis_records row, even when chassis make_model + VIN are
    both NULL at submit time. Previously uncovered by journey tests because
    fixtures pre-injected the chassis they later asserted on; the bare-fresh-
    costing scenario was tested at the API+unit level but never as a journey.
    Discovered via Michael's BA live click-around 19 Jun 2026 (A32755 catch).
    v4.36b will surface this stub as a RED chassis_no_make_model flag."""
    s = _make_bare_card()
    admin_session(page)
    r = page.request.post(f"{live_server}/api/prejob-cards/{s['card_id']}/submit-for-check",
                          data={}, headers={"X-CSRF-Token": _csrf(page), "Origin": live_server})
    assert r.status == 200, r.text()
    ch = _chassis_for_job(s["job_id"])
    assert ch is not None, "Pre-Job submit did not anchor a chassis stub (v4.36a.4 contract)"
    assert ch["make"] is None and ch["vin"] is None                  # a true stub — NULL make + VIN
    assert ch["status"] == "expected" and ch["created_via"] == "pre_job_card"
    assert ch["deleted_at"] is None                                  # live, not a tombstone
