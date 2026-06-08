"""Planning Board service (WO v4.16, ADR 0008).

Board = planning_slots ⋈ production_jobs ⋈ (icb_costings) calculations ⋈ customers.
The chassis-ETA gate (preserved from WO v4.4/v4.6) is enforced server-side on
schedule + move. Schedule sets production_jobs.planned_start_date and slot
status='scheduled'; the job's lifecycle status stays 'planning' (§0.4). Unschedule
DELETEs the slot row (an assignment) — the job returns to the unscheduled pool.
"""
import json
import re
from datetime import date, datetime, timedelta, timezone
from typing import List, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import CalculationRecord, Customer
from app.models.mes import ChassisLifecycleEvent, PlanningSlot, ProductionJob
from app.schemas.planning import (
    CapacityCell, PlanningBoard, PlanningJobRef, PlanningSlotItem, WeekRef,
)
from app.services.errors import (
    CellOccupiedError, ChassisEtaError, NotFoundError,
)


# ── date helpers ──────────────────────────────────────────────────────────────
def _iso(d: date) -> str:
    y, w, _ = d.isocalendar()
    return f"{y}-W{w:02d}"


def _monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


def _friday_eod(monday: date) -> datetime:
    fri = monday + timedelta(days=4)
    return datetime(fri.year, fri.month, fri.day, 23, 59, 59, tzinfo=timezone.utc)


# ── chassis-received signal (WO v4.29 D3 read-bridge, §0.3) ─────────────────────
# Latest VCL (book-in) event date for a job's linked chassis_record — the authoritative
# "chassis received" signal. NULL when the job has no chassis_record or no VCL yet.
# Correlated scalar subquery so it rides the board read in one round-trip.
_LATEST_VCL = (
    select(func.max(ChassisLifecycleEvent.event_date))
    .where(ChassisLifecycleEvent.chassis_record_id == ProductionJob.chassis_record_id,
           ChassisLifecycleEvent.event_type == "VCL")
    .correlate(ProductionJob)
    .scalar_subquery()
)


def _date_to_dt(d) -> Optional[datetime]:
    if d is None:
        return None
    if isinstance(d, datetime):
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)


def _has_vcl(db: Session, job: ProductionJob) -> bool:
    """True if the job's linked chassis_record has at least one VCL event (D3 signal)."""
    if job is None or job.chassis_record_id is None:
        return False
    return db.execute(
        select(ChassisLifecycleEvent.id).where(
            ChassisLifecycleEvent.chassis_record_id == job.chassis_record_id,
            ChassisLifecycleEvent.event_type == "VCL").limit(1)
    ).first() is not None


def _chassis_received(db: Session, job: ProductionJob) -> bool:
    """Read-bridge precedence (§0.3): a VCL event (authoritative) OR the legacy
    chassis_received_at column (transitional fallback). Bypasses the chassis gate."""
    return (job is not None
            and (job.chassis_received_at is not None or _has_vcl(db, job)))


def eta_gate_reason(job: ProductionJob, target_week: date, *, received: bool) -> Optional[str]:
    """Rejection reason if scheduling `job` into `target_week` violates the chassis gate, else None.

    WO v4.29 D4 (§0.4 revised; BA 7-Jun): `received` (the D3 signal — VCL event or the legacy
    chassis_received_at column) bypasses the gate. Otherwise BLOCK when no ETA is captured — the
    inverted-symptom fix: a job with neither receipt nor ETA was previously schedulable. The original
    within-target-week guard is RETAINED (Michael's call to keep it): an ETA after the target week
    still blocks. So the gate BLOCKS iff: not received AND (no ETA OR ETA after the target week).
    """
    if received:
        return None
    eta = job.chassis_eta
    if eta is None:
        return ("chassis not received and no ETA captured — capture a chassis ETA "
                "or mark the chassis received before scheduling")
    eta_dt = eta if eta.tzinfo else eta.replace(tzinfo=timezone.utc)
    fri = _friday_eod(_monday(target_week))
    if eta_dt > fri:
        gap = (eta_dt.date() - fri.date()).days
        return (f"chassis ETA {eta_dt.date()} is after the target week (ends {fri.date()}); "
                f"~{gap} day(s) short — mark chassis received or pick a later week")
    return None


# ── bay natural-numeric sort (WO v4.29 D5) ──────────────────────────────────────
_BAY_RE = re.compile(r"^(.*?)(\d+)\s*$")


def _bay_sort_key(bay: str):
    """Natural sort so 'Bay-2' < 'Bay-10'; groups by prefix (Bay-/V-/P-)."""
    m = _BAY_RE.match(bay or "")
    return (m.group(1), int(m.group(2))) if m else (bay or "", -1)


# ── reads ─────────────────────────────────────────────────────────────────────
def _job_ref(job: ProductionJob, calc, customer, vcl_date=None) -> PlanningJobRef:
    result = json.loads(calc.result_json) if calc and calc.result_json else {}
    dims = json.loads(calc.dimensions_json) if calc and calc.dimensions_json else {}
    # WO v4.29 D3 read-bridge (§0.3): the chassis-received signal prefers the latest VCL event
    # date (authoritative); falls back to the legacy chassis_received_at column for back-compat.
    if vcl_date is not None:
        received_signal, received_source = _date_to_dt(vcl_date), "vcl"
    elif job.chassis_received_at is not None:
        received_signal, received_source = job.chassis_received_at, "legacy"
    else:
        received_signal, received_source = None, None
    return PlanningJobRef(
        id=job.id, job_number=job.job_number, status=job.status,
        source=job.source,                      # WO v4.22 source-column fork
        # carrier fallback for workbook-imported jobs (no calc/customer join), v4.21
        customer=(customer.name if customer is not None else job.customer_name),
        body_type=(dims.get("body_type") or job.description),
        selling_zar=(result.get("selling_zar") if calc else job.selling_zar),
        branch_id=job.branch_id, chassis_eta=job.chassis_eta,
        chassis_received_at=job.chassis_received_at,
        chassis_received_signal=received_signal, chassis_received_source=received_source,
        planned_start_date=job.planned_start_date,
    )


def _slot_item(slot, job, calc, customer, vcl_date=None) -> PlanningSlotItem:
    return PlanningSlotItem(
        id=slot.id, week=slot.week, week_iso=(_iso(slot.week) if slot.week else None),
        bay=slot.bay, lane=slot.lane, slot_position=slot.slot_position, status=slot.status,
        production_job=(_job_ref(job, calc, customer, vcl_date) if job is not None else None),
    )


def _slot_select(*, branch_id=None, lane=None, week=None, status=None):
    stmt = (select(PlanningSlot, ProductionJob, CalculationRecord, Customer,
                   _LATEST_VCL.label("vcl_date"))      # WO v4.29 D3 read-bridge
            .join(ProductionJob, PlanningSlot.production_job_id == ProductionJob.id, isouter=True)
            .join(CalculationRecord, ProductionJob.calculation_record_id == CalculationRecord.id, isouter=True)
            .join(Customer, CalculationRecord.customer_id == Customer.id, isouter=True))
    if branch_id is not None:
        stmt = stmt.where(ProductionJob.branch_id == branch_id)
    if lane is not None:
        stmt = stmt.where(PlanningSlot.lane == lane)
    if week is not None:
        stmt = stmt.where(PlanningSlot.week == _monday(week))
    if status is not None:
        stmt = stmt.where(PlanningSlot.status == status)
    return stmt.order_by(PlanningSlot.week, PlanningSlot.bay)


def list_slots(db: Session, *, week=None, lane=None, status=None, branch_id=None) -> List[PlanningSlotItem]:
    rows = db.execute(_slot_select(branch_id=branch_id, lane=lane, week=week, status=status)).all()
    return [_slot_item(*r) for r in rows]


def _slot_item_by_id(db: Session, slot_id: int) -> Optional[PlanningSlotItem]:
    row = db.execute(_slot_select().where(PlanningSlot.id == slot_id)).first()
    return _slot_item(*row) if row else None


def _unscheduled_pool(db: Session, *, branch_id=None, exclude_ids=()) -> List[PlanningJobRef]:
    stmt = (select(ProductionJob, CalculationRecord, Customer,
                   _LATEST_VCL.label("vcl_date"))      # WO v4.29 D3 read-bridge
            .join(CalculationRecord, ProductionJob.calculation_record_id == CalculationRecord.id, isouter=True)
            .join(Customer, CalculationRecord.customer_id == Customer.id, isouter=True)
            .where(ProductionJob.status == "planning"))
    if branch_id is not None:
        stmt = stmt.where(ProductionJob.branch_id == branch_id)
    if exclude_ids:
        stmt = stmt.where(ProductionJob.id.notin_(list(exclude_ids)))
    return [_job_ref(j, c, cu, vcl) for (j, c, cu, vcl) in db.execute(stmt.order_by(ProductionJob.id)).all()]


def build_board(db: Session, *, branch_id=None, weeks_count=12, lane=None) -> PlanningBoard:
    rows = db.execute(_slot_select(branch_id=branch_id, lane=lane)).all()
    all_items = [_slot_item(*r) for r in rows]
    # WO v4.29 D6: show a CONTIGUOUS run of weeks (empty weeks INCLUDED — W17/W18 were being dropped,
    # leaving gaps). Anchor on the CURRENT week so the board is a rolling horizon (now + ahead) rather
    # than drifting into the past on the earliest-ever scheduled week. Fall back to the earliest
    # scheduled week ONLY if every scheduled job predates today (so the board is never empty).
    # Anchored weeks are Mondays (PlanningSlot.week is normalised to Monday).
    populated = sorted({it.week for it in all_items if it.week})
    this_week = _monday(date.today())
    anchor = this_week if (not populated or populated[-1] >= this_week) else populated[0]
    weeks_sorted = [anchor + timedelta(weeks=i) for i in range(weeks_count)]
    shown_weeks = set(weeks_sorted)
    weeks = [WeekRef(iso=_iso(w), start=w) for w in weeks_sorted]
    slots = [it for it in all_items if it.week in shown_weeks]
    # WO v4.29 D5: natural-numeric bay order (Bay-2 < Bay-10), not ASCII string order.
    lanes = sorted({it.bay for it in all_items if it.bay}, key=_bay_sort_key)
    slotted_ids = {r[0].production_job_id for r in rows if r[0].production_job_id}
    pool = _unscheduled_pool(db, branch_id=branch_id, exclude_ids=slotted_ids)
    grid = len(lanes)
    capacity = []
    for w in weeks_sorted:
        wk = [it for it in slots if it.week == w]
        filled = sum(1 for it in wk if it.production_job is not None)
        value = sum((it.production_job.selling_zar or 0) for it in wk if it.production_job is not None)
        capacity.append(CapacityCell(week_iso=_iso(w), filled=filled,
                                      empty=max(0, grid - filled), value_zar=value))
    return PlanningBoard(weeks=weeks, lanes=lanes, slots=slots, unscheduled_pool=pool, capacity=capacity)


# ── writes ────────────────────────────────────────────────────────────────────
def _occupied(db: Session, week: date, bay: str, exclude_slot_id=None) -> bool:
    stmt = select(PlanningSlot).where(PlanningSlot.week == week, PlanningSlot.bay == bay)
    if exclude_slot_id is not None:
        stmt = stmt.where(PlanningSlot.id != exclude_slot_id)
    return db.execute(stmt).first() is not None


def _set_start(job: ProductionJob, monday: date) -> None:
    job.planned_start_date = datetime(monday.year, monday.month, monday.day, tzinfo=timezone.utc)


def schedule(db: Session, *, production_job_id: int, week: date, bay: str,
             lane=None, slot_position=None, user=None) -> PlanningSlotItem:
    job = db.get(ProductionJob, production_job_id)
    if job is None:
        raise NotFoundError(f"production job {production_job_id} not found")
    if db.execute(select(PlanningSlot).where(
            PlanningSlot.production_job_id == production_job_id)).first() is not None:
        raise CellOccupiedError(f"production job {production_job_id} is already scheduled; use move")
    monday = _monday(week)
    reason = eta_gate_reason(job, monday, received=_chassis_received(db, job))
    if reason:
        raise ChassisEtaError(reason)
    if _occupied(db, monday, bay):
        raise CellOccupiedError(f"slot {bay} in week {_iso(monday)} is already occupied")
    slot = PlanningSlot(production_job_id=production_job_id, week=monday, bay=bay,
                        lane=lane, slot_position=slot_position, status="scheduled")
    db.add(slot)
    _set_start(job, monday)            # §0.4: planned_start_date set; job.status stays 'planning'
    db.commit()
    db.refresh(slot)
    return _slot_item_by_id(db, slot.id)


def move(db: Session, *, slot_id: int, week: date, bay: str,
         lane=None, slot_position=None, user=None) -> PlanningSlotItem:
    slot = db.get(PlanningSlot, slot_id)
    if slot is None:
        raise NotFoundError(f"planning slot {slot_id} not found")
    job = db.get(ProductionJob, slot.production_job_id) if slot.production_job_id else None
    monday = _monday(week)
    if job is not None:
        reason = eta_gate_reason(job, monday, received=_chassis_received(db, job))
        if reason:
            raise ChassisEtaError(reason)
    target_bay = bay or slot.bay
    if _occupied(db, monday, target_bay, exclude_slot_id=slot_id):
        raise CellOccupiedError(f"slot {target_bay} in week {_iso(monday)} is already occupied")
    slot.week = monday
    slot.bay = target_bay
    if lane is not None:
        slot.lane = lane
    if slot_position is not None:
        slot.slot_position = slot_position
    if job is not None:
        _set_start(job, monday)
    db.commit()
    return _slot_item_by_id(db, slot_id)


def unschedule(db: Session, *, slot_id: int, user=None) -> dict:
    slot = db.get(PlanningSlot, slot_id)
    if slot is None:
        raise NotFoundError(f"planning slot {slot_id} not found")
    jid = slot.production_job_id
    db.delete(slot)                    # DELETE the assignment row; job returns to the pool
    db.commit()
    return {"unscheduled_slot_id": slot_id, "production_job_id": jid}
