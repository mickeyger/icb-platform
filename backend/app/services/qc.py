"""WO v4.36c — Kenny's QC + Dispatch service (the inspection + sign-off chokepoint).

Design notes grounded in the §3.0 discovery (docs/audit/v4_36c_S3_0_kenny_qc_dispatch_discovery.md):

* QC cycle_number is a QC-ATTEMPT counter, NOT the chassis lifecycle cycle. A QC FAIL returns the
  chassis to 'awaiting_qa' for re-inspection in the SAME lifecycle visit, so the lifecycle cycle does
  not increment — we derive the open QC cycle as 1 + max(qc_signoffs.cycle_number) for the chassis.
  This keeps each re-inspection's per-category rows + signoff a distinct, immutable record (§0.6).

* Sign-off is the only status-flipping write. It takes a FOR UPDATE row-lock on the chassis (mirrors
  record_planning_ack — the ONE locked-transition precedent; the bare chassis transitions are
  lock-free) so concurrent inspectors can't double-sign / double-flip (§3.0 S1/R1). The unique
  constraints on (chassis, cycle, category) and (chassis, cycle) are the DB backstops.

* Every workflow invariant is enforced server-side, not trusted from the UI (§0.12/§0.17): the chassis
  must be live + 'awaiting_qa', the open cycle must not already be signed off (immutability), and ALL
  active categories must have a verdict before sign-off (completeness). overall_verdict is DERIVED
  (fail iff any category failed) — deterministic, no client-supplied verdict.
"""
from datetime import date

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.models.mes import (ChassisRecord, DefectCategory, ProductionJob,
                            QcInspection, QcSignoff)


# ── helpers ──────────────────────────────────────────────────────────────────

def _open_qc_cycle(db: Session, chassis_id: int) -> int:
    """The QC cycle currently being inspected = 1 + the highest signed-off cycle. A fresh chassis
    (no signoffs) is cycle 1; after a FAIL signoff closes cycle N, re-inspection opens cycle N+1."""
    last = db.execute(select(func.max(QcSignoff.cycle_number))
                      .where(QcSignoff.chassis_record_id == chassis_id)).scalar()
    return (last or 0) + 1


def _active_categories(db: Session) -> list[DefectCategory]:
    return list(db.execute(
        select(DefectCategory).where(DefectCategory.is_active.is_(True))
        .order_by(DefectCategory.sort_order, DefectCategory.id)).scalars().all())


def _live_awaiting(db: Session, chassis_id: int) -> ChassisRecord:
    """Load a chassis that must be live + currently awaiting QA, with a FOR UPDATE lock (callers that
    mutate). Raises the same precondition stack as record_moved_to_awaiting_qa."""
    rec = db.execute(select(ChassisRecord).where(ChassisRecord.id == chassis_id)
                     .with_for_update()).scalar_one_or_none()
    if rec is None:
        raise HTTPException(status_code=404, detail="chassis record not found")
    if rec.deleted_at is not None:
        raise HTTPException(status_code=409, detail="this chassis has been deleted")
    if rec.status != "awaiting_qa":
        raise HTTPException(status_code=422,
                            detail=f"chassis is '{rec.status}', not awaiting QA — it cannot be inspected")
    return rec


# ── reads ────────────────────────────────────────────────────────────────────

def list_awaiting(db: Session) -> list[dict]:
    """Kenny's QC inbox: live chassis in 'awaiting_qa', newest first. Each row carries the linked job
    number, the awaiting-since date (for the AgeingPill), and failed_count (prior FAIL signoffs — the
    'failed Nx' badge, §3.0 §6). Batched (3 queries, no N+1) for the §0.9 200ms budget."""
    rows = db.execute(
        select(ChassisRecord.id, ChassisRecord.vin, ChassisRecord.make, ChassisRecord.model,
               ChassisRecord.customer_name, ProductionJob.job_number)
        .outerjoin(ProductionJob, ProductionJob.chassis_record_id == ChassisRecord.id)
        .where(ChassisRecord.status == "awaiting_qa", ChassisRecord.deleted_at.is_(None))
        .order_by(ChassisRecord.id.desc())
    ).all()
    ids = [r[0] for r in rows]
    if not ids:
        return []
    from app.models.mes import ChassisLifecycleEvent
    since = dict(db.execute(
        select(ChassisLifecycleEvent.chassis_record_id, func.max(ChassisLifecycleEvent.event_date))
        .where(ChassisLifecycleEvent.chassis_record_id.in_(ids),
               ChassisLifecycleEvent.event_type == "moved_to_awaiting_qa")
        .group_by(ChassisLifecycleEvent.chassis_record_id)).all())
    fails = dict(db.execute(
        select(QcSignoff.chassis_record_id, func.count(QcSignoff.id))
        .where(QcSignoff.chassis_record_id.in_(ids), QcSignoff.overall_verdict == "fail")
        .group_by(QcSignoff.chassis_record_id)).all())
    return [{"chassis_id": cid, "vin": vin, "make": make, "model": model, "customer_name": cust,
             "job_number": jn,
             "awaiting_since": since[cid].isoformat() if since.get(cid) else None,
             "failed_count": int(fails.get(cid, 0))}
            for cid, vin, make, model, cust, jn in rows]


def list_dispatched(db: Session) -> list[dict]:
    """Dispatch-zone feed (§3.5): live chassis in 'dispatched', newest first. Mirrors list_awaiting_qa."""
    rows = db.execute(
        select(ChassisRecord.id, ChassisRecord.vin, ChassisRecord.make, ChassisRecord.model,
               ChassisRecord.customer_name, ProductionJob.job_number)
        .outerjoin(ProductionJob, ProductionJob.chassis_record_id == ChassisRecord.id)
        .where(ChassisRecord.status == "dispatched", ChassisRecord.deleted_at.is_(None))
        .order_by(ChassisRecord.id.desc())
    ).all()
    return [{"chassis_id": cid, "vin": vin, "make": make, "model": model,
             "customer_name": cust, "job_number": jn}
            for cid, vin, make, model, cust, jn in rows]


def get_inspection(db: Session, chassis_id: int) -> dict:
    """Current inspection state for the form: chassis header, active categories, the open cycle's
    recorded verdicts (so a re-opened form pre-fills), and the prior-cycle signoffs (audit context)."""
    rec = db.get(ChassisRecord, chassis_id)
    if rec is None or rec.deleted_at is not None:
        raise HTTPException(status_code=404, detail="chassis record not found")
    cycle = _open_qc_cycle(db, chassis_id)
    cats = _active_categories(db)
    recorded = {r.category_id: r for r in db.execute(
        select(QcInspection).where(QcInspection.chassis_record_id == chassis_id,
                                   QcInspection.cycle_number == cycle)).scalars().all()}
    signoffs = db.execute(
        select(QcSignoff).where(QcSignoff.chassis_record_id == chassis_id)
        .order_by(QcSignoff.cycle_number.desc())).scalars().all()
    return {
        "chassis_id": rec.id, "vin": rec.vin, "make": rec.make, "model": rec.model,
        "customer_name": rec.customer_name, "status": rec.status, "cycle_number": cycle,
        "categories": [
            {"category_id": c.id, "name": c.name, "sort_order": c.sort_order,
             "verdict": (recorded[c.id].verdict if c.id in recorded else None),
             "notes": (recorded[c.id].notes if c.id in recorded else None)}
            for c in cats],
        "prior_signoffs": [
            {"cycle_number": s.cycle_number, "overall_verdict": s.overall_verdict,
             "notes": s.notes, "created_at": s.created_at.isoformat() if s.created_at else None}
            for s in signoffs],
    }


# ── writes ───────────────────────────────────────────────────────────────────

def record_category_verdict(db: Session, chassis_id: int, category_id: int, *,
                            verdict: str, notes, user) -> dict:
    """Record (or overwrite) a single category's verdict for the OPEN QC cycle. Idempotent within the
    cycle (UPSERT on (chassis, cycle, category)); a re-inspection's cycle+1 keeps the prior cycle's row
    intact. Refuses once the cycle is signed off (immutability, §0.6/S4) and only on a live awaiting_qa
    chassis + an active category. category_name is denormalized so the audit survives a later rename."""
    verdict = (verdict or "").strip().lower()
    if verdict not in ("pass", "fail"):
        raise HTTPException(status_code=422, detail="verdict must be 'pass' or 'fail'")
    _live_awaiting(db, chassis_id)                       # 404/409/422 guards (no mutation yet)
    cycle = _open_qc_cycle(db, chassis_id)
    if db.execute(select(QcSignoff.id).where(QcSignoff.chassis_record_id == chassis_id,
                                             QcSignoff.cycle_number == cycle).limit(1)).first():
        raise HTTPException(status_code=409,
                            detail="this inspection is signed off — start a new inspection to revise")
    cat = db.get(DefectCategory, category_id)
    if cat is None or not cat.is_active:
        raise HTTPException(status_code=404, detail="defect category not found or inactive")
    who = getattr(user, "username", None)
    vals = dict(chassis_record_id=chassis_id, cycle_number=cycle, category_id=category_id,
                category_name=cat.name, inspector_user_id=getattr(user, "id", None),
                verdict=verdict, notes=notes, created_by=who)
    stmt = pg_insert(QcInspection.__table__).values(**vals).on_conflict_do_update(
        index_elements=["chassis_record_id", "cycle_number", "category_id"],
        set_=dict(verdict=verdict, notes=notes, category_name=cat.name,
                  inspector_user_id=getattr(user, "id", None), created_by=who))
    db.execute(stmt)
    db.commit()
    return {"chassis_id": chassis_id, "cycle_number": cycle, "category_id": category_id,
            "verdict": verdict}


def signoff(db: Session, chassis_id: int, *, notes, user) -> dict:
    """Finalize the open QC cycle. Locks the chassis (FOR UPDATE), re-asserts live+awaiting_qa (the
    status precondition doubles as the double-signoff idempotency key — a second call sees 'dispatched'
    or the closed cycle), enforces completeness (every ACTIVE category has a verdict this cycle), then
    DERIVES overall_verdict (fail iff any category failed). PASS -> chassis 'dispatched'; FAIL -> stays
    'awaiting_qa' (the failed signoff persists for audit; re-inspection opens the next cycle). Atomic."""
    rec = _live_awaiting(db, chassis_id)                 # FOR UPDATE lock + 404/409/422
    cycle = _open_qc_cycle(db, chassis_id)
    if db.execute(select(QcSignoff.id).where(QcSignoff.chassis_record_id == chassis_id,
                                             QcSignoff.cycle_number == cycle).limit(1)).first():
        raise HTTPException(status_code=409, detail="this inspection cycle is already signed off")
    cats = _active_categories(db)
    if not cats:
        raise HTTPException(status_code=422, detail="no active defect categories to inspect")
    verdicts = {r.category_id: r.verdict for r in db.execute(
        select(QcInspection).where(QcInspection.chassis_record_id == chassis_id,
                                   QcInspection.cycle_number == cycle)).scalars().all()}
    missing = [c.name for c in cats if c.id not in verdicts]
    if missing:
        raise HTTPException(
            status_code=422,
            detail=f"all categories must have a verdict before sign-off — missing: {', '.join(missing)}")
    overall = "fail" if any(verdicts.get(c.id) == "fail" for c in cats) else "pass"
    who = getattr(user, "username", None)
    db.add(QcSignoff(chassis_record_id=chassis_id, cycle_number=cycle,
                     inspector_user_id=getattr(user, "id", None),
                     overall_verdict=overall, notes=notes, created_by=who))
    if overall == "pass":
        # WO v4.36.5 §3.9 — the dispatch transition routes through the chokepoint (audited, source='qc_passed').
        from app.services.chassis import _apply_chassis_fields
        _apply_chassis_fields(db, rec, {"status": "dispatched"}, who, source="qc_passed", actor_id=getattr(user, "id", None))
    else:
        # FAIL: status stays 'awaiting_qa' (the failed signoff is the audit; re-inspection opens cycle+1).
        rec.updated_by = who
    db.commit()
    return {"chassis_id": chassis_id, "cycle_number": cycle, "overall_verdict": overall,
            "new_status": rec.status, "pdf_available": overall == "pass"}


def collection_note_pdf(db: Session, chassis_id: int) -> bytes:
    """Regenerate the customer collection note for a QC-passed chassis from its latest PASS signoff
    (no stored bytes — §3.0 §3e). 404 if the chassis is gone; 409 if it never passed QC."""
    from app.services.customer_collection_pdf import render_collection_note
    rec = db.get(ChassisRecord, chassis_id)
    if rec is None or rec.deleted_at is not None:
        raise HTTPException(status_code=404, detail="chassis record not found")
    signoff = db.execute(
        select(QcSignoff).where(QcSignoff.chassis_record_id == chassis_id,
                                QcSignoff.overall_verdict == "pass")
        .order_by(QcSignoff.cycle_number.desc())).scalars().first()
    if signoff is None:
        raise HTTPException(status_code=409, detail="no collection note — this chassis has not passed QC")
    return render_collection_note(
        vin=rec.vin, customer_name=rec.customer_name, make=rec.make, model=rec.model,
        description=rec.description, inspection_date=signoff.created_at, inspector_name=signoff.created_by)
