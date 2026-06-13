"""Business logic for the production-jobs lifecycle (WO v4.14, ADR 0008).

Routers stay thin: they call these functions and map the typed exceptions below
to HTTP responses. The cross-schema FK (production_jobs.calculation_record_id ->
icb_costings.calculations.id) is DB-only (ADR 0006), so every read joins
explicitly via `get_with_costing` / `list_jobs` (the §3.4 pattern).
"""
from __future__ import annotations

import json
from datetime import date, datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.database import Branch, CalculationRecord, Customer
from app.models.mes import (
    AssemblyBay, BomLine, ChassisLifecycleEvent, ChassisRecord, GeneratedBom, PlanningAck,
    ProductionJob, ReworkTicket,
)
from app.schemas.production_jobs import TimelineEvent


# ── Typed errors (router maps to HTTP) ───────────────────────────────────────
class ServiceError(Exception):
    """Base for service-layer errors."""


class NotFoundError(ServiceError):
    """Requested entity does not exist (-> 404)."""


class CalculationNotAcceptedError(ServiceError):
    """from-calculation called on a calc that is not status='accepted' (-> 422)."""


class RepairQuoteCannotSendPreJobError(ServiceError):
    """Repair quotes skip the pre-job flow (Addendum v1.2.1) (-> 422)."""


class WrongStatusForTransitionError(ServiceError):
    """Lifecycle action invalid for the job's current status (-> 422)."""


class BranchUnavailableError(ServiceError):
    """A job can't be created because its source calc has no branch and no default
    branch is seeded (WO v4.29 D1) (-> 422)."""


JobRow = tuple[ProductionJob, CalculationRecord, Optional[Customer], Optional[str]]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _to_dt(d: Optional[date]) -> Optional[datetime]:
    if d is None:
        return None
    if isinstance(d, datetime):
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)


def _job_number_from_quote(quote_number: Optional[str]) -> Optional[str]:
    return quote_number.split("-")[-1] if quote_number else None


def _resolve_branch_id(db: Session, calc, fallback_branch_id: Optional[int]) -> Optional[int]:
    """Branch for a new production job. WO v4.29 D1: some MES-native (A-series) calcs
    were created with a NULL branch_id, but icb_mes.production_jobs.branch_id is NOT
    NULL (migration 0005) — so `branch_id=calc.branch_id` IntegrityError'd the accept
    (and the retry pill 500'd). Fall back to the caller's active branch, else the
    configured default (JHB). Returns None only if the default branch isn't seeded."""
    if calc.branch_id is not None:
        return calc.branch_id
    if fallback_branch_id is not None:
        return fallback_branch_id
    row = db.execute(
        select(Branch).where(Branch.code == settings.DEFAULT_BRANCH_CODE)
    ).scalar_one_or_none()
    return row.id if row is not None else None


# ── Cross-schema reads (§3.4) ────────────────────────────────────────────────
def _base_select():
    return (
        select(ProductionJob, CalculationRecord, Customer, Branch)
        # LEFT join: workbook-imported jobs (v4.21) have a NULL calculation_record_id and
        # no calc row — an inner join would silently drop them from every list/detail read.
        .join(CalculationRecord, ProductionJob.calculation_record_id == CalculationRecord.id, isouter=True)
        .join(Customer, CalculationRecord.customer_id == Customer.id, isouter=True)
        .join(Branch, ProductionJob.branch_id == Branch.id, isouter=True)
    )


def _row(result_row) -> JobRow:
    job, calc, customer, branch = result_row
    return job, calc, customer, (branch.code if branch else None)


def get_with_costing(db: Session, job_id: int) -> JobRow:
    """Return (ProductionJob, CalculationRecord, Customer|None, branch_code) or raise NotFound."""
    row = db.execute(_base_select().where(ProductionJob.id == job_id)).first()
    if row is None:
        raise NotFoundError(f"production job {job_id} not found")
    return _row(row)


def load_current_bom(db: Session, job) -> Optional[tuple]:
    """The job's current generated_bom + its lines (WO v4.31 §3.2 — read-only). None if no current BOM.
    Returns (GeneratedBom, list[BomLine]); lines ordered by line_order."""
    bom_id = getattr(job, "current_bom_id", None)
    if not bom_id:
        return None
    bom = db.get(GeneratedBom, bom_id)
    if bom is None:
        return None
    lines = db.execute(
        select(BomLine).where(BomLine.generated_bom_id == bom_id)
        .order_by(BomLine.line_order, BomLine.id)
    ).scalars().all()
    return bom, lines


def list_jobs(db: Session, *, status: Optional[list[str]] = None, branch_id: Optional[int] = None,
              accepted_since: Optional[date] = None, limit: int = 50, offset: int = 0) -> list[JobRow]:
    stmt = _base_select()
    if status:
        stmt = stmt.where(ProductionJob.status.in_(status))
    if branch_id is not None:
        stmt = stmt.where(ProductionJob.branch_id == branch_id)
    if accepted_since is not None:
        stmt = stmt.where(ProductionJob.accepted_at >= _to_dt(accepted_since))
    stmt = stmt.order_by(ProductionJob.accepted_at.desc().nullslast(), ProductionJob.id.desc())
    stmt = stmt.limit(limit).offset(offset)
    return [_row(r) for r in db.execute(stmt).all()]


# ── Mutations ────────────────────────────────────────────────────────────────
def accept_calculation(db: Session, calculation_id: int, user,
                       fallback_branch_id: Optional[int] = None) -> tuple[JobRow, bool]:
    """Create (or return existing) production job for an accepted calculation.
    Returns (row, created). Idempotent: existing -> (row, False).
    `fallback_branch_id` (the caller's active branch) covers calcs with a NULL
    branch_id (WO v4.29 D1)."""
    calc = db.get(CalculationRecord, calculation_id)
    if calc is None:
        raise NotFoundError(f"calculation {calculation_id} not found")
    if calc.status != "accepted":
        raise CalculationNotAcceptedError(
            f"calculation {calculation_id} has status '{calc.status}'; must be 'accepted'")

    existing = db.execute(
        select(ProductionJob).where(ProductionJob.calculation_record_id == calculation_id)
    ).scalar_one_or_none()
    if existing is not None:
        return get_with_costing(db, existing.id), False

    branch_id = _resolve_branch_id(db, calc, fallback_branch_id)
    if branch_id is None:
        raise BranchUnavailableError(
            f"calculation {calculation_id} has no branch and the default branch "
            f"'{settings.DEFAULT_BRANCH_CODE}' is not seeded")

    job = ProductionJob(
        calculation_record_id=calc.id,
        branch_id=branch_id,
        job_number=_job_number_from_quote(calc.quote_number),
        status="accepted",
        accepted_at=_now(),
    )
    db.add(job)
    db.flush()   # assign job.id so the BOM-on-accept rows can FK to it

    # WO v4.27 §3.4 — generate + persist the BOM on accept (defaults-fill; incomplete never blocks,
    # §0.5). Skip only the admin 'manual' escape. Lazy import avoids a service-layer import cycle.
    if job.bom_status != "manual":
        from app.services.bom_on_accept import generate_and_persist_bom
        generate_and_persist_bom(db, job)

    db.commit()
    db.refresh(job)
    return get_with_costing(db, job.id), True


def send_pre_job_card(db: Session, job_id: int, user, commit: bool = True) -> JobRow:
    # commit=False lets a caller fold this transition into a larger single transaction (WO v4.34
    # §3.2: the Pre-Job submit owns one commit covering card flip + job transition + chassis insert
    # atomically). The standalone router path keeps commit=True.
    job, calc, _, _ = get_with_costing(db, job_id)
    if calc.is_repair:
        raise RepairQuoteCannotSendPreJobError(
            f"job {job_id} is a repair quote; repairs skip the pre-job card")
    job.pre_job_sent_at = _now()
    job.status = "pre_job_sent"
    db.commit() if commit else db.flush()
    return get_with_costing(db, job_id)


def record_signoff(db: Session, job_id: int, role: str, attestation: str, user) -> JobRow:
    job, _, _, _ = get_with_costing(db, job_id)
    actor = getattr(user, "username", None)
    now = _now()
    if role == "sales":
        job.pre_job_signoff_sales_at = now
        job.pre_job_signoff_sales_by = actor
        job.pre_job_signoff_sales_attestation = attestation
    else:  # production (PreJobSignoffRequest validates the literal)
        job.pre_job_signoff_production_at = now
        job.pre_job_signoff_production_by = actor
        job.pre_job_signoff_production_attestation = attestation
    # Both signoffs present -> confirmed.
    if job.pre_job_signoff_sales_at and job.pre_job_signoff_production_at:
        job.status = "pre_job_confirmed"
        if job.pre_job_confirmed_at is None:
            job.pre_job_confirmed_at = now
    db.commit()
    return get_with_costing(db, job_id)


def record_planning_ack(db: Session, job_id: int, chassis_eta: Optional[date],
                        notes: Optional[str], user, chassis_data: Optional[dict] = None) -> JobRow:
    job, _, _, _ = get_with_costing(db, job_id)
    if job.status != "pre_job_confirmed":
        raise WrongStatusForTransitionError(
            f"job {job_id} is '{job.status}'; planning-ack requires 'pre_job_confirmed'")
    actor = getattr(user, "username", None)
    now = _now()
    eta_dt = _to_dt(chassis_eta)
    db.add(PlanningAck(
        production_job_id=job.id,
        acknowledged_by_user_id=getattr(user, "id", None),
        acknowledged_by_name=actor,
        acknowledged_at=now,
        chassis_eta_at_ack=eta_dt,
        notes=notes,
    ))
    job.planning_acknowledged_at = now
    job.planning_acknowledged_by = actor
    if eta_dt is not None:
        job.chassis_eta = eta_dt
        job.chassis_eta_captured_at = now
        job.chassis_eta_captured_by = actor
    # WO v4.29 D2: persist rich chassis data captured at ack (VIN/model/dealer/tail-lift/in-house BOM)
    # onto the production job — replaces the deadlocked legacy calc /chassis-eta call (ADR 0016).
    if chassis_data:
        merged = {}
        if job.chassis_data_json:
            try:
                merged = json.loads(job.chassis_data_json) or {}
            except (ValueError, TypeError):
                merged = {}
        merged.update({k: v for k, v in chassis_data.items() if v is not None})
        job.chassis_data_json = json.dumps(merged) if merged else None
    job.status = "planning"
    db.commit()
    return get_with_costing(db, job_id)


def mark_chassis_received(db: Session, job_id: int, user) -> JobRow:
    job, _, _, _ = get_with_costing(db, job_id)
    job.chassis_received_at = _now()
    job.chassis_received_by = getattr(user, "username", None)
    db.commit()
    return get_with_costing(db, job_id)


def unmark_chassis_received(db: Session, job_id: int, user) -> JobRow:
    """WO v4.28 (Flag E) — reverse a chassis-received tick (clears the receipt). Re-enables the
    planning chassis-ETA gate, which is bypassed while chassis_received_at is set."""
    job, _, _, _ = get_with_costing(db, job_id)
    job.chassis_received_at = None
    job.chassis_received_by = None
    db.commit()
    return get_with_costing(db, job_id)


def build_timeline(db: Session, job_id: int) -> list[TimelineEvent]:
    job, _, _, _ = get_with_costing(db, job_id)
    # (event_type, timestamp, actor) for each populated lifecycle column.
    candidates = [
        ("accepted", job.accepted_at, None),
        ("pre_job_sent", job.pre_job_sent_at, None),
        ("pre_job_signoff_sales", job.pre_job_signoff_sales_at, job.pre_job_signoff_sales_by),
        ("pre_job_signoff_production", job.pre_job_signoff_production_at, job.pre_job_signoff_production_by),
        # pre_job_confirmed is an auto-transition implied by the two signoffs above,
        # so it is intentionally NOT a separate timeline event (keeps the round-trip
        # at 5 events per WO §3.10).
        ("planning_ack", job.planning_acknowledged_at, job.planning_acknowledged_by),
        ("chassis_eta_captured", job.chassis_eta_captured_at, job.chassis_eta_captured_by),
        ("chassis_received", job.chassis_received_at, job.chassis_received_by),
        ("completed", job.completed_at, None),
    ]
    events = [TimelineEvent(event_type=t, occurred_at=ts, actor=a) for (t, ts, a) in candidates if ts]
    events.sort(key=lambda e: e.occurred_at)
    return events


# ── WO v4.32 — Production Dashboard aggregations (§0.4/§0.6; read-only) ───────
# In-flight per the §0.6 schema-aligned default: production_jobs statuses only.
# (in_workshop / in_assembly are CHASSIS statuses — the team split derives from the
# linked chassis_records.status, not from the job enum.)
IN_FLIGHT_STATUSES = ("planning", "in_production")


def _aware(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def stage_entered_at(job) -> Optional[datetime]:
    """§0.6 default: when the job entered its CURRENT stage = the latest populated lifecycle
    timestamp on the row (the same column set build_timeline reads). Falls back to created_at."""
    candidates = [job.accepted_at, job.pre_job_sent_at, job.pre_job_confirmed_at,
                  job.planning_acknowledged_at, job.chassis_received_at, job.planned_start_date]
    vals = [_aware(t) for t in candidates if t is not None]
    return max(vals) if vals else _aware(job.created_at)


def chassis_received(job, chassis_status: Optional[str]) -> bool:
    """§0.6 default for 'chassis on site': the legacy tick (chassis_received_at) OR the linked
    chassis_record has been booked in (VCL → in_workshop / onward). 'received' alone is just a
    created record, NOT a booked-in chassis."""
    if job.chassis_received_at is not None:
        return True
    return chassis_status in ("in_workshop", "in_assembly", "dispatched")


def _chassis_status_map(db: Session, jobs) -> dict:
    ids = [j.chassis_record_id for j in jobs if j.chassis_record_id]
    if not ids:
        return {}
    return {cid: st for cid, st in db.execute(
        select(ChassisRecord.id, ChassisRecord.status).where(ChassisRecord.id.in_(ids))).all()}


def compute_production_kpis(db: Session, branch_id: Optional[int] = None,
                            now: Optional[datetime] = None) -> dict:
    """The Production Dashboard metric values (WO v4.32 §0.4/§0.6) — ONE computation, shared by
    every consumer (the §0.5 parity-by-construction pattern; Management Dashboard v4.33+ becomes
    the second caller). §0.6 schema-aligned defaults, BA-approved 10 Jun PM:
      * units_in_production: jobs in IN_FLIGHT_STATUSES (branch-filtered).
      * delayed: start_slipped (planned_start_date < today, still 'planning') +
        chassis_slipped (chassis_eta < today, chassis not received/booked-in).
      * critical_chassis == chassis_slipped (the chassis-risk subset).
      * bottleneck: in-flight job longest in its current stage, only if > 2 days; else None.
      * completed_today: completed_at on today's date (branch-filtered).
      * open_rework: rework_tickets.status='open' — table has NO branch column, so the count is
        global ("filter where attributable", §0.7).
      * target_today: None — no target exists in seed data (§0.6 no-target-line branch).
    """
    now = now or _now()
    today = now.date()
    stmt = select(ProductionJob).where(ProductionJob.status.in_(IN_FLIGHT_STATUSES))
    if branch_id is not None:
        stmt = stmt.where(ProductionJob.branch_id == branch_id)
    jobs = db.execute(stmt).scalars().all()
    ch_status = _chassis_status_map(db, jobs)

    start_slipped, chassis_slipped = set(), set()
    bottleneck = None
    for j in jobs:
        psd = _aware(j.planned_start_date)
        if j.status == "planning" and psd is not None and psd.date() < today:
            start_slipped.add(j.id)
        eta = _aware(j.chassis_eta)
        if (eta is not None and eta.date() < today
                and not chassis_received(j, ch_status.get(j.chassis_record_id))):
            chassis_slipped.add(j.id)
        entered = stage_entered_at(j)
        if entered is not None:
            days = (now - entered).days
            if days > 2 and (bottleneck is None or days > bottleneck["days_in_stage"]):
                bottleneck = {"job_id": j.id, "job_number": j.job_number,
                              "status": j.status, "days_in_stage": days}

    day_start = datetime(today.year, today.month, today.day, tzinfo=timezone.utc)
    completed_stmt = (select(ProductionJob.id)
                      .where(ProductionJob.completed_at >= day_start))
    if branch_id is not None:
        completed_stmt = completed_stmt.where(ProductionJob.branch_id == branch_id)
    completed_today = len(db.execute(completed_stmt).all())

    open_rework = len(db.execute(
        select(ReworkTicket.id).where(ReworkTicket.status == "open")).all())

    return {
        "units_in_production": len(jobs),
        "delayed": {
            "total": len(start_slipped | chassis_slipped),
            "start_slipped": len(start_slipped),
            "chassis_slipped": len(chassis_slipped),
        },
        "critical_chassis": len(chassis_slipped),
        "bottleneck": bottleneck,
        "completed_today": completed_today,
        "target_today": None,                      # §0.6: no target in seed → no target line
        "open_rework": open_rework,
    }


def list_in_progress(db: Session, branch_id: Optional[int] = None,
                     now: Optional[datetime] = None) -> list[tuple]:
    """WO v4.32 §0.4 — in-flight jobs (+ joined costing) enriched with chassis/bay context.
    Returns [(JobRow, chassis_vin, chassis_status, bay_code, days_in_stage)] for the
    /in-progress endpoint; bay code derives from the latest assembly_assigned event (§0.12)."""
    now = now or _now()
    rows = list_jobs(db, status=list(IN_FLIGHT_STATUSES), branch_id=branch_id, limit=500)
    jobs = [r[0] for r in rows]
    ch_ids = [j.chassis_record_id for j in jobs if j.chassis_record_id]
    vin_status: dict = {}
    bay_code_by_chassis: dict = {}
    if ch_ids:
        for cid, vin, st in db.execute(
            select(ChassisRecord.id, ChassisRecord.vin, ChassisRecord.status)
            .where(ChassisRecord.id.in_(ch_ids))
        ).all():
            vin_status[cid] = (vin, st)
        for cid, code in db.execute(
            select(ChassisLifecycleEvent.chassis_record_id, AssemblyBay.code)
            .join(AssemblyBay, AssemblyBay.id == ChassisLifecycleEvent.assembly_bay_id)
            .where(ChassisLifecycleEvent.chassis_record_id.in_(ch_ids),
                   ChassisLifecycleEvent.event_type == "assembly_assigned")
            .order_by(ChassisLifecycleEvent.chassis_record_id, ChassisLifecycleEvent.id.desc())
        ).all():
            bay_code_by_chassis.setdefault(cid, code)        # first per chassis = latest
    out = []
    for row in rows:
        job = row[0]
        vin, st = vin_status.get(job.chassis_record_id, (None, None))
        bay_code = bay_code_by_chassis.get(job.chassis_record_id) if st == "in_assembly" else None
        entered = stage_entered_at(job)
        days = (now - entered).days if entered is not None else None
        out.append((row, vin, st, bay_code, days))
    return out
