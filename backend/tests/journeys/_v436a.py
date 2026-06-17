"""WO v4.36a §3.8 — shared substrate for the chassis-integrity journey suites (PJ / AJ / AC + admin
merge / orphan). CSRF-aware page.request API (incl. PATCH), a CONFORMANT-VIN factory, P436A-marked
lifecycle factories, state readers, and an FK-safe self-healing purge. Mirrors _v435.py; kept separate to
limit blast radius. Runs against the shared journey DB (icb_test on CI).

Markers: every factory tags rows with the P436A marker (chassis.make / job.job_number /
calc.quote_number / card.body_description all begin 'P436A') so purge() can reclaim them deterministically.
VINs are conformant ('P436A' + 12 uppercase-hex = 17 chars, all [A-HJ-NPR-Z0-9]).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

MARK = "P436A"


def vin() -> str:
    """A conformant, unique 17-char VIN — 'P436A' (5) + 12 uppercase-hex (A-F/0-9, no I/O/Q) = 17."""
    return f"{MARK}{uuid.uuid4().hex[:12].upper()}"


# ── CSRF-aware API (mirrors _v435 / the SPA fetch wrapper) ───────────────────────
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


def api_patch(page, base: str, path: str, body: dict):
    return page.request.patch(f"{base}{path}", data=body,
                              headers={"X-CSRF-Token": csrf(page), "Origin": base})


def api_delete(page, base: str, path: str):
    return page.request.delete(f"{base}{path}", headers={"X-CSRF-Token": csrf(page), "Origin": base})


# ── master-data handles (reused, never created/mutated) ──────────────────────────
def _branch_customer_template(db):
    from app.database import Branch, Customer
    from app.models.mes import PrejobTemplate
    branch = db.query(Branch).order_by(Branch.id).first()
    cust = db.query(Customer).order_by(Customer.id).first()
    tpl = db.query(PrejobTemplate).filter_by(is_active=True).order_by(PrejobTemplate.id).first()
    return branch, cust, tpl


# ── lifecycle factories (P436A-marked) ───────────────────────────────────────────
def make_unlinked_job(*, chassis_type: str = "Hino 300 614 SWB (EU3)") -> dict:
    """A pre_job_sent job with NO chassis linked (surfaces in /api/production-jobs/unlinked) and a
    sent_for_check card carrying chassis_make_model — so AC auto-populate shows customer + chassis type.
    Returns {job_id, calc_id, customer_name}."""
    from app.database import CalculationRecord, Customer, SessionLocal
    from app.models.mes import PrejobCard, ProductionJob
    tag = uuid.uuid4().hex[:6]
    with SessionLocal() as db:
        branch, cust, tpl = _branch_customer_template(db)
        calc = CalculationRecord(quote_number=f"{MARK}-{tag}", status="pre_job_sent", branch_id=branch.id,
                                 customer_id=cust.id, dimensions_json='{"body_type": "Chiller"}',
                                 result_json='{"selling_zar": 1000.0}')
        db.add(calc); db.flush()
        job = ProductionJob(calculation_record_id=calc.id, branch_id=branch.id, status="pre_job_sent",
                            job_number=f"{MARK}{tag}", source="quote")          # chassis_record_id=None → unlinked
        db.add(job); db.flush()
        db.add(PrejobCard(calculation_id=calc.id, template_id=(tpl.id if tpl else None),
                          body_description=f"{MARK} card", chassis_make_model=chassis_type,
                          sections=[{"name": "S", "items": [{"text": "x"}]}], status="sent_for_check"))
        db.commit()
        return {"job_id": job.id, "calc_id": calc.id, "customer_name": db.get(Customer, cust.id).name}


def make_linked_chassis(*, status: str = "in_workshop", vin_value: "str | None" = None,
                        with_events: bool = False) -> dict:
    """A chassis linked to a P436A job (the authoritative FK). with_events adds a VCL (so it's NOT a
    junk orphan). Returns {chassis_id, job_id, calc_id, vin}."""
    from app.database import CalculationRecord, SessionLocal
    from app.models.mes import ChassisLifecycleEvent, ChassisRecord, ProductionJob
    tag = uuid.uuid4().hex[:6]
    v = vin_value if vin_value is not None else vin()
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        branch, cust, _ = _branch_customer_template(db)
        calc = CalculationRecord(quote_number=f"{MARK}-{tag}", status="planning", branch_id=branch.id,
                                 customer_id=cust.id, dimensions_json='{"body_type": "Chiller"}',
                                 result_json='{"selling_zar": 1000.0}')
        db.add(calc); db.flush()
        ch = ChassisRecord(make=f"{MARK} Test", model="X", vin=v, status=status, source="manual",
                           created_via="manual_chassis_menu", created_by="t")
        db.add(ch); db.flush()
        job = ProductionJob(calculation_record_id=calc.id, branch_id=branch.id, status="planning",
                            job_number=f"{MARK}{tag}", chassis_record_id=ch.id, source="quote")
        db.add(job); db.flush()
        if with_events:
            db.add(ChassisLifecycleEvent(chassis_record_id=ch.id, cycle_number=1, event_type="VCL",
                                         event_date=now.date(), created_by="t"))
        db.commit()
        return {"chassis_id": ch.id, "job_id": job.id, "calc_id": calc.id, "vin": v}


def make_orphan_chassis(*, status: str = "received", vin_value: "str | None" = None) -> dict:
    """A live chassis with NO job and NO card — a wide-scope orphan (status defaults to 'received', i.e.
    the MICKEYTEST class the narrow Inv3 scope would miss). Returns {chassis_id, vin}."""
    from app.database import SessionLocal
    from app.models.mes import ChassisRecord
    v = vin_value if vin_value is not None else vin()
    with SessionLocal() as db:
        ch = ChassisRecord(make=f"{MARK} Orphan", model="X", vin=v, status=status, source="manual",
                           created_via="manual_chassis_menu", created_by="t")
        db.add(ch); db.flush()
        db.commit()
        return {"chassis_id": ch.id, "vin": v}


def make_null_vin_chassis() -> dict:
    """A live chassis with vin=NULL (the capture_vin target). Returns {chassis_id}."""
    from app.database import SessionLocal
    from app.models.mes import ChassisRecord
    with SessionLocal() as db:
        ch = ChassisRecord(make=f"{MARK} NoVin", model="X", vin=None, status="expected", source="manual",
                           created_via="manual_chassis_menu", created_by="t")
        db.add(ch); db.flush()
        db.commit()
        return {"chassis_id": ch.id}


# ── state readers ────────────────────────────────────────────────────────────────
def job_chassis_id(job_id: int):
    from app.database import SessionLocal
    from app.models.mes import ProductionJob
    with SessionLocal() as db:
        return db.get(ProductionJob, job_id).chassis_record_id


def job_chassis_eta(job_id: int):
    from app.database import SessionLocal
    from app.models.mes import ProductionJob
    with SessionLocal() as db:
        j = db.get(ProductionJob, job_id)
        return j.chassis_eta.date().isoformat() if j and j.chassis_eta else None


def chassis_row(chassis_id: int) -> dict:
    from app.database import SessionLocal
    from app.models.mes import ChassisRecord
    with SessionLocal() as db:
        c = db.get(ChassisRecord, chassis_id)
        return {"vin": c.vin, "status": c.status, "deleted_at": c.deleted_at,
                "merged_into_id": c.merged_into_id, "job_number": c.job_number}


def event_cycles(chassis_id: int):
    """Sorted (cycle_number, event_type) for a chassis — for merge renumber assertions."""
    from app.database import SessionLocal
    from app.models.mes import ChassisLifecycleEvent
    from sqlalchemy import select
    with SessionLocal() as db:
        return sorted((e.cycle_number, e.event_type) for e in db.execute(
            select(ChassisLifecycleEvent).where(
                ChassisLifecycleEvent.chassis_record_id == chassis_id)).scalars().all())


def purge():
    """FK-safe reclaim of every P436A-marked row (events + cards → jobs → chassis → calcs). Also clears
    any production_jobs.chassis_eta stamped onto P436A jobs (no separate table)."""
    from app.database import SessionLocal
    from sqlalchemy import text
    with SessionLocal() as db:
        db.execute(text("DELETE FROM icb_mes.chassis_lifecycle_events WHERE chassis_record_id IN "
                        "(SELECT id FROM icb_mes.chassis_records WHERE make LIKE 'P436A%')"))
        db.execute(text("DELETE FROM icb_mes.prejob_cards WHERE body_description LIKE 'P436A%' OR "
                        "calculation_id IN (SELECT id FROM icb_costings.calculations WHERE quote_number LIKE 'P436A%')"))
        db.execute(text("DELETE FROM icb_mes.production_jobs WHERE job_number LIKE 'P436A%'"))
        db.execute(text("DELETE FROM icb_mes.chassis_records WHERE make LIKE 'P436A%'"))
        db.execute(text("DELETE FROM icb_costings.calculations WHERE quote_number LIKE 'P436A%'"))
        db.commit()
