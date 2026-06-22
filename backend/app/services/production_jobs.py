"""Business logic for the production-jobs lifecycle (WO v4.14, ADR 0008).

Routers stay thin: they call these functions and map the typed exceptions below
to HTTP responses. The cross-schema FK (production_jobs.calculation_record_id ->
icb_costings.calculations.id) is DB-only (ADR 0006), so every read joins
explicitly via `get_with_costing` / `list_jobs` (the §3.4 pattern).
"""
from __future__ import annotations

import json
import re
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
    """WO v4.34 §0.7 — the NUMERIC core of the quote (A32744/06/2026 → 32744; legacy Q-32891 →
    32891): the first run of digits, after any letter prefix and before the /MM/YYYY. UNIQUE was
    dropped in migration 0020 (numeric cores collide across letter prefixes; id stays the PK)."""
    if not quote_number:
        return None
    m = re.search(r"\d+", quote_number)
    return m.group(0) if m else None


def sap_retired(db: Session) -> bool:
    """WO v4.34 §0.9 — the site-level SAP_RETIRED flag (icb_costings.admin_settings, seeded FALSE
    by 0020). When TRUE, new jobs lock their quote-derived job_number and the Planning-ack override
    is refused (and hidden). The admin UI to flip it is v4.35."""
    from app.database import AdminSetting
    row = db.query(AdminSetting).filter_by(key="SAP_RETIRED").first()
    return bool(row and str(row.value).strip().lower() in ("true", "1", "yes"))


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
        job_number=_job_number_from_quote(calc.quote_number),   # §0.7 — numeric core
        job_number_source="quote_derived",
        job_number_locked=sap_retired(db),                      # §0.9 — lock once SAP is retired
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


def _planning_ref(job: ProductionJob) -> str:
    """§0.4 — the originating reference for a Planning-created chassis: the job number when set,
    else a stable id form (workbook jobs may carry no job_number)."""
    return f"Planning · Job {job.job_number}" if job.job_number else f"Planning · job {job.id}"


def _auto_create_chassis_at_ack(db: Session, job: ProductionJob,
                                chassis_data: Optional[dict], who) -> None:
    """WO v4.34 §3.3 (§0.5b) — at Planning ack, anchor the pipeline chassis from the chassis MODEL
    captured in the ack, IF the job isn't already linked. A card-driven job is already linked via
    §3.2's card+job cross-link, so this no-ops for the common path; it covers jobs that reached
    Planning WITHOUT a Pre-Job-Card chassis (workbook imports, or a card with no make/model).

    Mirrors §3.2's 'same INSERT pattern' exactly: status='expected', vin=NULL AT CREATE — keeping vin
    NULL on the INSERT avoids any uq_chassis_records_vin collision AND the cross-job aliasing a
    VIN-adopt would risk (a VIN can already anchor another job). The VIN (attested at pre-job, or
    captured at ack) is then stamped onto the row by record_planning_ack's propagation step right
    after this (guarded against overwrite + clash), so the Chassis page reflects the ack. Runs inside
    record_planning_ack's transaction (atomic with the ack); the FOR UPDATE lock on the job makes
    the job-FK guard a true idempotency key under concurrent acks on the same job."""
    if job.chassis_record_id is not None:
        return                                            # already linked (§3.2 or a prior ack) — idempotent
    make = (((chassis_data or {}).get("chassis_model")) or "").strip()
    if not make:
        return                                            # no chassis model entered — graceful no-op
    from app.services.chassis import create_expected_chassis
    chassis = create_expected_chassis(
        db, make=make, vin=None,                          # VIN unknown until VCL receive (mirrors §3.2)
        body_gap_mm=None, created_via="planning_job_create", source="planning_ack",  # source is VARCHAR(16)
        created_source_ref=_planning_ref(job), who=who)
    job.chassis_record_id = chassis.id


def list_unlinked_jobs(db: Session) -> list[dict]:
    """WO v4.36a §0.6 — production jobs with no chassis linked yet (chassis_record_id IS NULL), for the
    Add-Chassis job dropdown. Excludes terminal jobs. Returns {id, job_number, customer, body_type}."""
    from app.database import CalculationRecord, Customer
    rows = db.execute(
        select(ProductionJob.id, ProductionJob.job_number, Customer.name, CalculationRecord.dimensions_json)
        .select_from(ProductionJob)
        .outerjoin(CalculationRecord, CalculationRecord.id == ProductionJob.calculation_record_id)
        .outerjoin(Customer, Customer.id == CalculationRecord.customer_id)
        .where(ProductionJob.chassis_record_id.is_(None),
               ProductionJob.status.notin_(("completed", "dispatched", "cancelled")))
        .order_by(ProductionJob.job_number)
    ).all()
    out = []
    for jid, jn, cust, dims in rows:
        body_type = None
        if dims:
            try:
                body_type = (json.loads(dims) or {}).get("body_type")
            except (ValueError, TypeError):
                body_type = None
        out.append({"id": jid, "job_number": jn, "customer": cust, "body_type": body_type})
    return out


def chassis_prefill(db: Session, job_id: int) -> dict:
    """WO v4.36a §3.5b — prefill data for the Add-Chassis modal when a job is selected: the customer +
    anything already captured UPSTREAM (chassis type / dealer / VIN at Pre-Job or Planning-Ack), reading
    production_jobs + the linked prejob_card + the linked chassis. Each field is None unless captured."""
    from app.database import CalculationRecord, Customer
    from app.models.mes import ChassisRecord, PrejobCard
    job = db.get(ProductionJob, job_id)
    if job is None:
        raise NotFoundError(f"production job {job_id} not found")
    customer_name = customer_id = None
    card = None
    if job.calculation_record_id:
        calc = db.get(CalculationRecord, job.calculation_record_id)
        if calc and calc.customer_id:
            c = db.get(Customer, calc.customer_id)
            if c:
                customer_name, customer_id = c.name, c.id
        card = db.execute(
            select(PrejobCard).where(PrejobCard.calculation_id == job.calculation_record_id)
            .order_by(PrejobCard.id.desc())).scalars().first()
    chassis = db.get(ChassisRecord, job.chassis_record_id) if job.chassis_record_id else None
    chassis_type = (chassis.make if chassis and chassis.make else None) \
        or (card.chassis_make_model if card and card.chassis_make_model else None)
    vin_number = (chassis.vin if chassis and chassis.vin else None) \
        or (card.vin_number if card and card.vin_number else None)
    vin_source = None
    if vin_number:
        vin_source = (chassis.vin_source if chassis and chassis.vin else None) \
            or ("pre_job_card" if card and card.vin_number else None)
    dealer_id = chassis.dealer_id if chassis else None
    dealer_name = (db.get(Customer, dealer_id).name if dealer_id and db.get(Customer, dealer_id) else None)
    return {"customer_name": customer_name, "customer_id": customer_id, "chassis_type": chassis_type,
            "dealer_id": dealer_id, "dealer_name": dealer_name, "vin_number": vin_number,
            "vin_source": vin_source,
            # WO v4.36b — chassis-field unification: surface the rest of the linked chassis fields so the
            # Planning-ack panel seeds from chassis_records (single source of truth), not the costing blob.
            "contact_person": (chassis.contact_person if chassis else None),
            "telephone": (chassis.telephone if chassis else None),
            "description": (chassis.description if chassis else None),
            "chassis_notes": (chassis.notes if chassis else None),
            "tail_lift_code": (chassis.tail_lift_code if chassis else None),
            # §3.5e — the job's Delivery ETA (production_jobs.chassis_eta) as a YYYY-MM-DD string, for the
            # Add-Chassis modal's ETA auto-populate.
            "chassis_eta": (job.chassis_eta.date().isoformat() if job.chassis_eta else None)}


def record_planning_ack(db: Session, job_id: int, chassis_eta: Optional[date],
                        notes: Optional[str], user, chassis_data: Optional[dict] = None,
                        job_number: Optional[str] = None) -> JobRow:
    # §3.3 — lock the job row so concurrent acks serialize (the loser re-reads 'planning' and 422s
    # before the chassis auto-create); makes the job-FK idempotency guard race-safe.
    db.execute(select(ProductionJob).where(ProductionJob.id == job_id).with_for_update())
    job, calc, _, _ = get_with_costing(db, job_id)
    if job.status != "pre_job_confirmed":
        raise WrongStatusForTransitionError(
            f"job {job_id} is '{job.status}'; planning-ack requires 'pre_job_confirmed'")
    # WO v4.34 §0.8 — optional job-number override (an SAP-assigned number during the parallel run)
    # → source 'sap_assigned'. Refused when the number is locked or SAP_RETIRED (§0.9 forces
    # quote-derived); blank or unchanged input keeps the quote-derived value.
    if job_number is not None:
        new_jn = job_number.strip()
        if (new_jn and new_jn != (job.job_number or "")
                and not job.job_number_locked and not sap_retired(db)):
            job.job_number = new_jn
            job.job_number_source = "sap_assigned"
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
    # WO v4.34 §3.3 (§0.5b) — anchor the pipeline chassis from the ack's chassis info (idempotent;
    # no-op when the job is already linked via §3.2). Inside this transaction → atomic with the ack.
    _auto_create_chassis_at_ack(db, job, chassis_data, getattr(user, "username", None))
    # WO v4.34 (ack follow-up, BA 2026-06-14) — the acknowledged job's final number + its VIN land on
    # the LINKED chassis so the Chassis page reflects the ack. The VIN is the one attested on the
    # Pre-Job Card OR captured here when the card left it blank. No-op when no chassis is linked; never
    # overwrites an existing VIN, and skips a value already anchoring another chassis
    # (uq_chassis_records_vin) so the ack can't fail on a VIN clash.
    from app.services import chassis_integrity as ci   # lazy — chassis_integrity imports ServiceError from here
    if job.chassis_record_id:
        chassis = db.get(ChassisRecord, job.chassis_record_id)
        if chassis is not None:
            if job.job_number:
                chassis.job_number = job.job_number
            # WO v4.36a §0.5 — VIN format validated (422 on bad format), clash no longer SILENTLY swallowed:
            # write-once NULL→value with a 409 on clash; a DIFFERENT VIN presented for a chassis that already
            # has one is surfaced (409), not dropped.
            vin = ci.validate_vin_format((chassis_data or {}).get("chassis_vin"))
            if vin and not chassis.vin:
                ci.validate_vin_uniqueness(db, vin, exclude_id=chassis.id)        # 409 on clash (was silent)
                chassis.vin = vin
                chassis.vin_source = chassis.vin_source or "planning_ack"
            elif vin and chassis.vin and ci.normalize_vin(vin) != chassis.vin:
                raise ci.ChassisIntegrityError(
                    f"VIN {ci.normalize_vin(vin)} differs from this chassis's VIN {chassis.vin}. "
                    "Use Merge Chassis to swap the chassis.", status_code=409)
            # WO v4.34.1 §0.3 / v4.36a §0.5 — stamp the planner's chosen supplier, validated as a dealer
            # (is_dealer=true → 422 otherwise). Explicit choice → last-write wins; None leaves it untouched.
            dealer_id = (chassis_data or {}).get("dealer_id")
            if dealer_id is not None:
                chassis.dealer_id = ci.validate_dealer(db, dealer_id)
            # WO v4.36b — chassis-field unification: the ack persists the chassis fields onto chassis_records
            # (single source of truth), not just the costing chassis_data blob. The panel sends the attested
            # make when §3.9-locked, so make<-chassis_model equals the attested value (safe). VIN keeps its
            # dedicated write-once path above; ETA stays on the job; the blob is still written (belt-and-braces).
            cd = chassis_data or {}
            if cd.get("chassis_model"):
                chassis.make = (cd["chassis_model"] or "").strip()[:64] or None
            _widths = {"customer_name": 128, "contact_person": 128, "telephone": 64,
                       "description": 255, "notes": None, "tail_lift_code": 64}
            for col, w in _widths.items():
                if cd.get(col) is not None:
                    val = (cd[col] or "").strip()
                    setattr(chassis, col, (val[:w] if w else val) or None)
            chassis.updated_by = actor
    job.status = "planning"
    # hotfix (fix/prejob-card-status-sync) — keep the costing's status in lock-step so the Costings
    # dashboard shows 'Planning' and the costing surfaces as an unscheduled Planning card.
    if calc is not None and calc.status != "declined":
        calc.status = "planning"
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
    # WO v4.36a.1 — 'awaiting_qa' is PAST in_assembly (body attached, moved to the QA queue): the chassis
    # is unambiguously booked-in/on-site, so it belongs in this set alongside in_assembly/dispatched.
    return chassis_status in ("in_workshop", "in_assembly", "awaiting_qa", "dispatched")


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

    # WO v4.35 §0.6 — bodies attached today. chassis_lifecycle_events has no branch column (like
    # open_rework) → counted "where attributable" (global). event_date is the business attach date.
    from app.models.mes import ChassisLifecycleEvent
    bodies_attached_today = len(db.execute(
        select(ChassisLifecycleEvent.id).where(
            ChassisLifecycleEvent.event_type == "body_attached",
            ChassisLifecycleEvent.event_date == today)).all())

    return {
        "units_in_production": len(jobs),
        "bodies_attached_today": bodies_attached_today,
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
