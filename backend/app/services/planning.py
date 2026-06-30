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

from sqlalchemy import func, nulls_last, or_, select
from sqlalchemy.orm import Session

from app.database import CalculationRecord, Customer
from app.models.mes import (
    ChassisLifecycleEvent, ChassisRecord, PlanningSlot, ProductionJob, ProductionJobAudit,
    ProductionJobBayEvent, SignOff, Task, WorkOrder,
)
from app.schemas.planning import (
    CapacityCell, PlanningBoard, PlanningJobRef, PlanningSlotItem, WeekRef,
)
from app.services.errors import (
    CellOccupiedError, ChassisEtaError, NotFoundError, RevertNotAllowedError,
)

# WO v4.34.2 §0.3 — the extensible whitelist of job lifecycle statuses a scheduled job may be reverted
# FROM. A scheduled job's production_jobs.status stays 'planning' (ADR 0008 §0.4); once it advances
# (in_production / completed) it is workshop-locked. Future locked-from states simply stay out of this set.
REVERTIBLE_JOB_STATUSES = ("planning",)

# Latest "reverted-to-unscheduled" timestamp per job — drives the §0.8 recency sort of the pool
# (most-recently-reverted job floats to the top so the planner can immediately re-place it).
_LATEST_REVERT = (
    select(func.max(ProductionJobAudit.created_at))
    .where(ProductionJobAudit.production_job_id == ProductionJob.id,
           ProductionJobAudit.new_status == "unscheduled")
    .correlate(ProductionJob)
    .scalar_subquery()
)

# WO v4.35 §3.3+ — the linked chassis VIN, rides the board read in one round-trip so slot + pool cards
# can show the VIN (VIN-to-VIN matching with the Production page + the assembly bays). NULL when unlinked.
_CHASSIS_VIN = (
    select(ChassisRecord.vin)
    .where(ChassisRecord.id == ProductionJob.chassis_record_id)
    .correlate(ProductionJob)
    .scalar_subquery()
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
def _job_ref(job: ProductionJob, calc, customer, vcl_date=None, chassis_vin=None) -> PlanningJobRef:
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
        # Workload metric — pre-discount selling intentional (capacity != revenue). The Planning Board is a
        # workload view; discounted quotes don't reduce production load. Costings views use net_total. (WO v4.30 §0.2a)
        selling_zar=(result.get("selling_zar") if calc else job.selling_zar),
        branch_id=job.branch_id, chassis_eta=job.chassis_eta,
        chassis_received_at=job.chassis_received_at,
        chassis_received_signal=received_signal, chassis_received_source=received_source,
        planned_start_date=job.planned_start_date,
        chassis_vin=chassis_vin,                # WO v4.35 §3.3+
    )


def _slot_item(slot, job, calc, customer, vcl_date=None, chassis_vin=None) -> PlanningSlotItem:
    return PlanningSlotItem(
        id=slot.id, week=slot.week, week_iso=(_iso(slot.week) if slot.week else None),
        bay=slot.bay, lane=slot.lane, slot_position=slot.slot_position, status=slot.status,
        production_job=(_job_ref(job, calc, customer, vcl_date, chassis_vin) if job is not None else None),
    )


def _slot_select(*, branch_id=None, lane=None, week=None, status=None):
    stmt = (select(PlanningSlot, ProductionJob, CalculationRecord, Customer,
                   _LATEST_VCL.label("vcl_date"),      # WO v4.29 D3 read-bridge
                   _CHASSIS_VIN.label("chassis_vin"))  # WO v4.35 §3.3+
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
                   _LATEST_VCL.label("vcl_date"),      # WO v4.29 D3 read-bridge
                   _CHASSIS_VIN.label("chassis_vin"))  # WO v4.35 §3.3+
            .join(CalculationRecord, ProductionJob.calculation_record_id == CalculationRecord.id, isouter=True)
            .join(Customer, CalculationRecord.customer_id == Customer.id, isouter=True)
            .where(ProductionJob.status == "planning"))
    if branch_id is not None:
        stmt = stmt.where(ProductionJob.branch_id == branch_id)
    if exclude_ids:
        stmt = stmt.where(ProductionJob.id.notin_(list(exclude_ids)))
    # WO v4.34.2 §0.8 — most-recently-reverted jobs sort first; never-reverted (NULL) keep id order.
    stmt = stmt.order_by(nulls_last(_LATEST_REVERT.desc()), ProductionJob.id)
    return [_job_ref(j, c, cu, vcl, vin) for (j, c, cu, vcl, vin) in db.execute(stmt).all()]


def _progressed_job_ids(db: Session) -> set:
    """WO v4.36a.5 follow-up — jobs that have LEFT V/P scheduling and must drop off the Planning Board
    (grid AND unscheduled pool): their panels have been dragged onto an assembly bay
    (panels_arrived_in_bay — the JOB-side merge signal), their chassis is merged (a body_attached event),
    or the chassis has moved to Awaiting QA. The PlanningSlot rows are left intact (non-destructive); they
    are simply hidden now that the job is in the assembly / merge / QA phase. Note the JOB status stays
    'planning' through merge+QA (16-Jun ruling — no auto-transition), so without this filter such a job
    leaks into BOTH the grid (via its lingering slot) and the pool (via status='planning')."""
    ids = set(db.execute(
        select(ProductionJobBayEvent.production_job_id)
        .where(ProductionJobBayEvent.event_type == "panels_arrived_in_bay")).scalars().all())
    ids |= set(db.execute(
        select(ProductionJob.id)
        .join(ChassisRecord, ProductionJob.chassis_record_id == ChassisRecord.id)
        .where(or_(
            ChassisRecord.status == "awaiting_qa",
            select(ChassisLifecycleEvent.id).where(
                ChassisLifecycleEvent.chassis_record_id == ChassisRecord.id,
                ChassisLifecycleEvent.event_type == "body_attached").exists()))).scalars().all())
    ids.discard(None)
    return ids


def build_board(db: Session, *, branch_id=None, weeks_count=12, lane=None, start=None) -> PlanningBoard:
    rows = db.execute(_slot_select(branch_id=branch_id, lane=lane)).all()
    # WO v4.36a.5 follow-up — a job whose panels have gone to a bay (or is merged / in Awaiting QA) has left
    # V/P scheduling; drop it from the board entirely (grid below + pool further down). Non-destructive read
    # filter — the slot row stays, so move-panels-back / unschedule still work.
    progressed = _progressed_job_ids(db)
    rows = [r for r in rows if r[0].production_job_id not in progressed]
    all_items = [_slot_item(*r) for r in rows]
    # WO v4.29 D6: show a CONTIGUOUS run of weeks (empty weeks INCLUDED — W17/W18 were being dropped,
    # leaving gaps). When `start` is given (the jump-to control), anchor on that week (normalised to its
    # Monday). Otherwise roll on the CURRENT week so the board is a rolling horizon (now + ahead),
    # falling back to the earliest scheduled week ONLY if every job predates today (never empty).
    # Anchored weeks are Mondays (PlanningSlot.week is normalised to Monday).
    populated = sorted({it.week for it in all_items if it.week})
    this_week = _monday(date.today())
    if start is not None:
        anchor = _monday(start)
    else:
        anchor = this_week if (not populated or populated[-1] >= this_week) else populated[0]
    weeks_sorted = [anchor + timedelta(weeks=i) for i in range(weeks_count)]
    shown_weeks = set(weeks_sorted)
    weeks = [WeekRef(iso=_iso(w), start=w) for w in weeks_sorted]
    slots = [it for it in all_items if it.week in shown_weeks]
    # WO v4.29 D5: natural-numeric bay order (Bay-2 < Bay-10), not ASCII string order.
    lanes = sorted({it.bay for it in all_items if it.bay}, key=_bay_sort_key)
    slotted_ids = {r[0].production_job_id for r in rows if r[0].production_job_id}
    # exclude the progressed jobs from the pool too — they belong to assembly/merge/QA, not the board.
    pool = _unscheduled_pool(db, branch_id=branch_id, exclude_ids=slotted_ids | progressed)
    grid = len(lanes)
    capacity = []
    for w in weeks_sorted:
        wk = [it for it in slots if it.week == w]
        filled = sum(1 for it in wk if it.production_job is not None)
        # Workload metric — pre-discount selling intentional (capacity != revenue). (WO v4.30 §0.2a)
        value = sum((it.production_job.selling_zar or 0) for it in wk if it.production_job is not None)
        capacity.append(CapacityCell(week_iso=_iso(w), filled=filled,
                                      empty=max(0, grid - filled), value_zar=value))
    return PlanningBoard(weeks=weeks, lanes=lanes, slots=slots, unscheduled_pool=pool, capacity=capacity)


# ── writes ────────────────────────────────────────────────────────────────────
def _occupied(db: Session, week: date, bay: str, exclude_slot_id=None) -> bool:
    stmt = select(PlanningSlot).where(PlanningSlot.week == week, PlanningSlot.bay == bay)
    if exclude_slot_id is not None:
        stmt = stmt.where(PlanningSlot.id != exclude_slot_id)
    rows = db.execute(stmt).scalars().all()
    if not rows:
        return False
    # WO v1.39.1 — mirror build_board's read filter in the write guard. A slot whose job has
    # PROGRESSED off the board (panels→bay / body_attached / awaiting_qa) is HIDDEN from the grid
    # (build_board drops it via _progressed_job_ids), so the cell reads EMPTY to the user — its
    # PlanningSlot row is left intact non-destructively. Without this filter that lingering row
    # makes a visibly-empty cell raise "already occupied" (the bug). Only a VISIBLE (non-progressed)
    # slot counts as occupied here, exactly as the board paints it.
    progressed = _progressed_job_ids(db)
    return any(r.production_job_id not in progressed for r in rows)


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


def _assert_revertible(db: Session, slot: PlanningSlot, job: Optional[ProductionJob]) -> None:
    """WO v4.34.2 §0.3 — the state safety rules, enforced HERE (the shared chokepoint) so neither the
    slot-centric DELETE (drag) nor the job-centric POST (modal) can bypass them. Raises
    RevertNotAllowedError (→409) naming the failed rule. An orphan slot (no job) is allowed through as
    cleanup — there is nothing downstream to protect."""
    if slot.status not in ("scheduled",):
        raise RevertNotAllowedError(
            f"slot {slot.id} is '{slot.status}', not 'scheduled' — only a scheduled slot can be reverted")
    if job is None:
        return
    if job.status not in REVERTIBLE_JOB_STATUSES:
        raise RevertNotAllowedError(
            f"job {job.id} is '{job.status}' — only a job still in planning can be reverted "
            f"(workshop-active / completed jobs are locked)")
    started = db.execute(
        select(WorkOrder.id).where(WorkOrder.production_job_id == job.id,
                                   WorkOrder.started_at.isnot(None)).limit(1)).first()
    if started:
        raise RevertNotAllowedError(f"job {job.id} has started in the workshop — cannot revert")
    wo_ids = select(WorkOrder.id).where(WorkOrder.production_job_id == job.id)
    qc = db.execute(
        select(Task.id).where(Task.work_order_id.in_(wo_ids), Task.completed_at.isnot(None)).limit(1)
    ).first() or db.execute(
        select(SignOff.id).where(SignOff.work_order_id.in_(wo_ids)).limit(1)).first()
    if qc:
        raise RevertNotAllowedError(f"job {job.id} has a QC check recorded — cannot revert")
    # WO v4.35 §3.3b/§3.2 — a job physically committed to a bay must NOT silently revert to the pool and
    # orphan the floor. record_panels_arrived_in_bay / record_body_attached are phase-only and never advance
    # job.status (the 16-Jun ruling keeps it 'planning'), so the status/WO/QC checks above can't see them —
    # guard the two committed-state event logs explicitly. Covers BOTH the drag (DELETE) and modal (POST)
    # paths, since both funnel through here.
    panels = db.execute(
        select(ProductionJobBayEvent.id).where(
            ProductionJobBayEvent.production_job_id == job.id,
            ProductionJobBayEvent.event_type == "panels_arrived_in_bay").limit(1)).first()
    if panels:
        raise RevertNotAllowedError(
            f"job {job.id} has panels committed to a bay — move the panels back before unscheduling")
    if job.chassis_record_id is not None:
        cycle = db.execute(
            select(func.max(ChassisLifecycleEvent.cycle_number))
            .where(ChassisLifecycleEvent.chassis_record_id == job.chassis_record_id)).scalar() or 1
        body = db.execute(
            select(ChassisLifecycleEvent.id).where(
                ChassisLifecycleEvent.chassis_record_id == job.chassis_record_id,
                ChassisLifecycleEvent.event_type == "body_attached",
                ChassisLifecycleEvent.cycle_number == cycle).limit(1)).first()
        if body:
            raise RevertNotAllowedError(
                f"job {job.id} has a body attached to its chassis — cannot unschedule")


def unschedule(db: Session, *, slot_id: int, user=None, reason: Optional[str] = None) -> dict:
    """The single guarded scheduled→unscheduled chokepoint (WO v4.34.2). Both the slot DELETE (drag,
    reason=None) and the job-centric POST (modal, optional reason) route through here. Applies the §0.3
    safety rules, writes a production_jobs_audit row (reason optional, ≤500 chars), then deletes the
    slot — the job returns to the pool. Chassis assignment + sign-offs are untouched (slot-only delete)."""
    slot = db.get(PlanningSlot, slot_id)
    if slot is None:
        raise NotFoundError(f"planning slot {slot_id} not found")
    job = db.get(ProductionJob, slot.production_job_id) if slot.production_job_id else None
    _assert_revertible(db, slot, job)
    clean_reason = (reason or "").strip()[:500] or None    # §0.7 — empty accepted; server-cap at 500
    if job is not None:                                    # audit the transition BEFORE the slot row goes
        db.add(ProductionJobAudit(
            production_job_id=job.id, action="revert_to_unscheduled",
            previous_status=slot.status, new_status="unscheduled",
            previous_slot_id=slot.id, previous_lane=slot.lane, previous_bay=slot.bay,
            previous_week=slot.week,
            user_id=getattr(user, "id", None), user_name=getattr(user, "username", None),
            reason=clean_reason))
    jid = slot.production_job_id
    db.delete(slot)                    # DELETE the assignment row only (chassis + sign-offs preserved)
    db.commit()
    return {"unscheduled_slot_id": slot_id, "production_job_id": jid}


def revert_to_unscheduled(db: Session, *, production_job_id: int, user=None,
                          reason: Optional[str] = None) -> dict:
    """WO v4.34.2 §3.2 — job-centric entry for the explicit revert modal. Resolves the job's (single)
    planning slot and delegates to the guarded `unschedule` chokepoint. 404 if the job is unknown;
    RevertNotAllowedError (→409) if it isn't scheduled."""
    job = db.get(ProductionJob, production_job_id)
    if job is None:
        raise NotFoundError(f"production job {production_job_id} not found")
    slot = db.execute(
        select(PlanningSlot).where(PlanningSlot.production_job_id == production_job_id)).scalars().first()
    if slot is None:
        raise RevertNotAllowedError(f"production job {production_job_id} is not scheduled")
    return unschedule(db, slot_id=slot.id, user=user, reason=reason)
