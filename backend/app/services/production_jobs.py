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
from app.models.mes import BomLine, GeneratedBom, PlanningAck, ProductionJob
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


def send_pre_job_card(db: Session, job_id: int, user) -> JobRow:
    job, calc, _, _ = get_with_costing(db, job_id)
    if calc.is_repair:
        raise RepairQuoteCannotSendPreJobError(
            f"job {job_id} is a repair quote; repairs skip the pre-job card")
    job.pre_job_sent_at = _now()
    job.status = "pre_job_sent"
    db.commit()
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
