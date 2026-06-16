"""WO v4.35 §3.6 — shared helpers for the body_attached journey suites.

Kept out of _common.py (which every journey imports) to limit blast radius. Provides: CSRF-aware
page.request POSTs (the SPA's fetch idiom), P435-marked lifecycle factories, a free-bay finder, and a
self-healing purge. The journey server shares this DB, so factory rows are visible to the browser.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone

MARK = "P435"


# ── CSRF-aware API (mirrors the SPA fetch wrapper; the session row carries the token) ──
def csrf(page) -> str:
    from app.database import SessionLocal, UserSession
    sid = next((c["value"] for c in page.context.cookies() if c["name"] == "session_id"), None)
    assert sid, "no session_id cookie — autologin did not establish a session"
    with SessionLocal() as db:
        row = db.get(UserSession, sid)
        assert row is not None, "session row missing"
        return row.csrf_token or ""


def api_post(page, base: str, path: str, body: dict):
    return page.request.post(f"{base}{path}", data=body,
                             headers={"X-CSRF-Token": csrf(page), "Origin": base})


# ── lifecycle factories (P435-marked) ──────────────────────────────────────────
def _free_bay(db):
    """An assembly bay with no current in_assembly occupant (so the occupancy/state assertions are
    deterministic). Skips the test if all 5 are occupied on this DB."""
    import pytest
    from app.services.chassis import current_occupants, list_assembly_bays
    occ = current_occupants(db)
    for bay in list_assembly_bays(db):
        if bay.id not in occ:
            return bay
    pytest.skip("no free assembly bay on this DB")


def make_assembly_job(*, attached: bool = False, attested_vin: "str | None" = None,
                      vin: "str | None" = None) -> dict:
    """A P435 in_production job whose chassis is on a (free) assembly bay (VCL + assembly_assigned
    events). attached=True adds a body_attached event today. attested_vin sets a confirmed Pre-Job
    Card attesting that VIN (the DEV-1 swap-rule signal). Returns ids + bay + vin."""
    from app.database import Branch, CalculationRecord, SessionLocal
    from app.models.mes import (
        ChassisLifecycleEvent, ChassisRecord, PrejobCard, PrejobTemplate, ProductionJob,
    )
    tag = uuid.uuid4().hex[:6]
    vin = vin or f"{MARK}{tag}"
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        jhb = db.query(Branch).order_by(Branch.id).first()
        bay = _free_bay(db)
        bay_id, bay_code = bay.id, bay.code
        calc = CalculationRecord(quote_number=f"{MARK}-{tag}", status="in_production", branch_id=jhb.id,
                                 dimensions_json='{"body_type": "Chiller"}',
                                 result_json='{"selling_zar": 1000.0}')
        db.add(calc); db.flush()
        ch = ChassisRecord(make=f"{MARK} Test", model="X", vin=vin, status="in_assembly", source="manual",
                           created_via="manual_chassis_menu", created_by="t")
        db.add(ch); db.flush()
        job = ProductionJob(calculation_record_id=calc.id, branch_id=jhb.id, status="in_production",
                            job_number=f"{MARK}{tag}", chassis_record_id=ch.id)
        db.add(job); db.flush()
        db.add(ChassisLifecycleEvent(chassis_record_id=ch.id, cycle_number=1, event_type="VCL",
                                     event_date=(now.date()), created_by="t"))
        db.add(ChassisLifecycleEvent(chassis_record_id=ch.id, cycle_number=1, event_type="assembly_assigned",
                                     assembly_bay_id=bay_id, event_date=now.date(), created_by="t"))
        if attached:
            db.add(ChassisLifecycleEvent(chassis_record_id=ch.id, cycle_number=1, event_type="body_attached",
                                         event_date=now.date(), created_by="t"))
        if attested_vin is not None:
            tpl = db.query(PrejobTemplate).filter_by(is_active=True).first()
            db.add(PrejobCard(
                calculation_id=calc.id, template_id=(tpl.id if tpl else None),
                body_description=f"{MARK} card", sections=[{"name": "S", "items": [{"text": "x"}]}],
                vin_number=attested_vin, status="pre_job_confirmed", planner_signoff_at=now,
                planner_attestation="attested at ack"))
        db.commit()
        return {"chassis_id": ch.id, "job_id": job.id, "bay_id": bay_id, "bay_code": bay_code,
                "calc_id": calc.id, "vin": vin}


def body_attached_event_count(chassis_id: int) -> int:
    from app.database import SessionLocal
    from app.models.mes import ChassisLifecycleEvent
    from sqlalchemy import select
    with SessionLocal() as db:
        return len(db.execute(
            select(ChassisLifecycleEvent.id).where(
                ChassisLifecycleEvent.chassis_record_id == chassis_id,
                ChassisLifecycleEvent.event_type == "body_attached")).all())


def chassis_status(chassis_id: int) -> str:
    from app.database import SessionLocal
    from app.models.mes import ChassisRecord
    with SessionLocal() as db:
        return db.get(ChassisRecord, chassis_id).status


def purge():
    from app.database import SessionLocal
    from sqlalchemy import text
    with SessionLocal() as db:
        # FK-safe: events + cards (→ chassis SET NULL / calc RESTRICT) then jobs, then chassis, then calcs.
        db.execute(text("DELETE FROM icb_mes.chassis_lifecycle_events WHERE chassis_record_id IN "
                        "(SELECT id FROM icb_mes.chassis_records WHERE make LIKE 'P435%')"))
        db.execute(text("DELETE FROM icb_mes.prejob_cards WHERE body_description LIKE 'P435%'"))
        db.execute(text("DELETE FROM icb_mes.planning_slots WHERE production_job_id IN "
                        "(SELECT id FROM icb_mes.production_jobs WHERE job_number LIKE 'P435%')"))
        db.execute(text("DELETE FROM icb_mes.production_jobs WHERE job_number LIKE 'P435%'"))
        db.execute(text("DELETE FROM icb_mes.chassis_records WHERE make LIKE 'P435%'"))
        db.execute(text("DELETE FROM icb_costings.calculations WHERE quote_number LIKE 'P435%'"))
        db.commit()
