"""WO v4.32 §3.3 — per-team daily worksheet (the load-bearing contract; ADR 0019).

ONE function builds ONE uniform shape for all five teams — the frontend renders every tab with
the same component (§8: "don't write 5 separate endpoints"). Sections are fixed:

  * scheduled — work expected for the selected date (slots this week; expected chassis
    arrivals; completed jobs pending collection)
  * in_flight — work physically underway / present (in-progress slots; occupied assembly
    bays; chassis in the yard; chassis collected on the date)
  * blocking  — attention items (open rework routed to the team's bays; overdue chassis ETAs)

Team sources (§0.6 sensible defaults, BA-approved 10 Jun PM):
  vacuum / press — planning_slots for the WEEK containing the date (slots are week-granular;
      "today's scheduled" = this week's lane slots). press maps to lane='panelshop' (the v4.16
      seed vocabulary — P-1..3 slots; the UI label is "Press").
  assembly — occupied bays from the latest assembly_assigned events (§0.12 event-derived).
  parking — booked-in chassis awaiting a bay (status in_workshop); capacity chip from the
      parking_bays master (~24; informational — no formal yard allocation until Phase 4).
  dispatch — completed jobs whose chassis hasn't DCL'd (pending collection) + chassis
      collected (DCL) on the date.

Branch filter is "where attributable" (§0.7): chassis_records / planning_slots / rework_tickets
have no branch_id — rows filter through their linked production job; rows with no job link are
shown for every branch (JHB-only reality today).

Rework→team mapping is by routed_to_bay prefix (V- / P- / A|AssemblyBay). Legacy mock values
('GRP-2', 'PA-1', 'QC-1') match no team: they surface in the global open_rework KPI only.
"""
import json
from datetime import date as date_type, datetime, timedelta, timezone
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import CalculationRecord, Customer
from app.models.mes import (
    ChassisLifecycleEvent, ChassisRecord, ParkingBay, PlanningSlot, ProductionJob, ReworkTicket,
)
from app.schemas.team_worksheet import (
    TeamWorksheet, WorksheetCapacity, WorksheetItem, WorksheetSections,
)
from app.services.chassis import current_occupants, list_assembly_bays
from app.services.production_jobs import IN_FLIGHT_STATUSES, chassis_received

TEAMS = ("vacuum", "press", "assembly", "parking", "dispatch")
MAX_DATE_OFFSET_DAYS = 7                       # §3.3 lock: date selector allows ±7 days

_TEAM_LANE = {"vacuum": "vacuum", "press": "panelshop"}
_REWORK_PREFIX = {"vacuum": ("V-",), "press": ("P-",), "assembly": ("A-", "AssemblyBay")}


def _today() -> date_type:
    return datetime.now(timezone.utc).date()


def _body_type(calc) -> Optional[str]:
    if calc is None or not calc.dimensions_json:
        return None
    try:
        return (json.loads(calc.dimensions_json) or {}).get("body_type")
    except (ValueError, TypeError):
        return None


def _job_item(job, customer_name, calc, *, location, status, since=None, flag=None,
              chassis_vin=None) -> WorksheetItem:
    return WorksheetItem(
        job_id=job.id, job_number=job.job_number, chassis_vin=chassis_vin,
        customer=(customer_name or job.customer_name),
        description=(_body_type(calc) or job.description),
        location=location, status=status, since=since, flag=flag,
    )


def _rework_blocking(db: Session, team: str) -> list[WorksheetItem]:
    prefixes = _REWORK_PREFIX.get(team)
    if not prefixes:
        return []
    items = []
    for t in db.execute(select(ReworkTicket).where(ReworkTicket.status == "open")).scalars().all():
        bay = t.routed_to_bay or ""
        if bay.startswith(prefixes):
            items.append(WorksheetItem(
                description=t.notes, location=t.routed_to_bay, status="rework",
                since=(t.created_at.date() if t.created_at else None),
                flag=f"open rework {t.ticket_code}" if t.ticket_code else "open rework",
            ))
    return items


def _slot_team(db: Session, team: str, for_date: date_type, branch_id) -> WorksheetSections:
    """vacuum / press — planning_slots for the week containing for_date, joined to the job."""
    monday = for_date - timedelta(days=for_date.weekday())
    stmt = (
        select(PlanningSlot, ProductionJob, CalculationRecord, Customer)
        .join(ProductionJob, PlanningSlot.production_job_id == ProductionJob.id)
        .join(CalculationRecord, ProductionJob.calculation_record_id == CalculationRecord.id, isouter=True)
        .join(Customer, CalculationRecord.customer_id == Customer.id, isouter=True)
        .where(PlanningSlot.week == monday, PlanningSlot.lane == _TEAM_LANE[team])
        .order_by(PlanningSlot.bay, PlanningSlot.slot_position)
    )
    if branch_id is not None:
        stmt = stmt.where(ProductionJob.branch_id == branch_id)
    scheduled, in_flight = [], []
    for slot, job, calc, customer in db.execute(stmt).all():
        item = _job_item(job, (customer.name if customer else None), calc,
                         location=slot.bay, status=(slot.status or "scheduled"))
        if slot.status == "in_progress":
            in_flight.append(item)
        elif slot.status != "completed":
            scheduled.append(item)
    return WorksheetSections(scheduled=scheduled, in_flight=in_flight,
                             blocking=_rework_blocking(db, team))


def _jobs_for_chassis(db: Session, chassis_ids) -> dict:
    """{chassis_record_id: (job, customer_name, calc)} via the costing join (first job wins)."""
    if not chassis_ids:
        return {}
    rows = db.execute(
        select(ProductionJob, CalculationRecord, Customer)
        .join(CalculationRecord, ProductionJob.calculation_record_id == CalculationRecord.id, isouter=True)
        .join(Customer, CalculationRecord.customer_id == Customer.id, isouter=True)
        .where(ProductionJob.chassis_record_id.in_(list(chassis_ids)))
    ).all()
    out = {}
    for job, calc, customer in rows:
        out.setdefault(job.chassis_record_id, (job, (customer.name if customer else None), calc))
    return out


def _branch_visible(job, branch_id) -> bool:
    """§0.7 'where attributable': no linked job → visible in every branch."""
    return branch_id is None or job is None or job.branch_id == branch_id


def _assembly_team(db: Session, branch_id) -> WorksheetSections:
    bays_by_id = {b.id: b for b in list_assembly_bays(db)}
    occupants = current_occupants(db)
    job_ctx = _jobs_for_chassis(db, [o["chassis_id"] for o in occupants.values()])
    in_flight = []
    for bay_id, occ in sorted(occupants.items(),
                              key=lambda kv: (bays_by_id[kv[0]].sort_order or 0) if kv[0] in bays_by_id else 99):
        bay = bays_by_id.get(bay_id)
        job, customer_name, calc = job_ctx.get(occ["chassis_id"], (None, None, None))
        if not _branch_visible(job, branch_id):
            continue
        if job is not None:
            item = _job_item(job, customer_name, calc, location=(bay.code if bay else None),
                             status="in_assembly", since=occ["since"], chassis_vin=occ["vin"])
        else:
            item = WorksheetItem(chassis_vin=occ["vin"], customer=occ["customer_name"],
                                 location=(bay.code if bay else None), status="in_assembly",
                                 since=occ["since"])
        in_flight.append(item)
    return WorksheetSections(scheduled=[], in_flight=in_flight,
                             blocking=_rework_blocking(db, "assembly"))


def _parking_team(db: Session, for_date: date_type,
                  branch_id) -> tuple[WorksheetSections, WorksheetCapacity]:
    # in_flight — booked-in chassis awaiting a bay (the BayModelLanes parking-pool derivation).
    chassis = db.execute(
        select(ChassisRecord).where(ChassisRecord.status == "in_workshop")
    ).scalars().all()
    job_ctx = _jobs_for_chassis(db, [c.id for c in chassis])
    vcl_since: dict = {}
    if chassis:
        for cid, ev_date in db.execute(
            select(ChassisLifecycleEvent.chassis_record_id, ChassisLifecycleEvent.event_date)
            .where(ChassisLifecycleEvent.chassis_record_id.in_([c.id for c in chassis]),
                   ChassisLifecycleEvent.event_type == "VCL")
            .order_by(ChassisLifecycleEvent.chassis_record_id, ChassisLifecycleEvent.id.desc())
        ).all():
            vcl_since.setdefault(cid, ev_date)
    in_flight = []
    for c in chassis:
        job, customer_name, calc = job_ctx.get(c.id, (None, None, None))
        if not _branch_visible(job, branch_id):
            continue
        if job is not None:
            in_flight.append(_job_item(job, customer_name, calc, location="Yard",
                                       status="in_workshop", since=vcl_since.get(c.id),
                                       chassis_vin=c.vin))
        else:
            in_flight.append(WorksheetItem(chassis_vin=c.vin, customer=c.customer_name,
                                           location="Yard", status="in_workshop",
                                           since=vcl_since.get(c.id)))

    # scheduled / blocking — chassis-ETA view over in-flight jobs (branch-filtered).
    stmt = (
        select(ProductionJob, CalculationRecord, Customer)
        .join(CalculationRecord, ProductionJob.calculation_record_id == CalculationRecord.id, isouter=True)
        .join(Customer, CalculationRecord.customer_id == Customer.id, isouter=True)
        .where(ProductionJob.status.in_(IN_FLIGHT_STATUSES),
               ProductionJob.chassis_eta.isnot(None))
    )
    if branch_id is not None:
        stmt = stmt.where(ProductionJob.branch_id == branch_id)
    ch_status = {c.id: c.status for c in chassis}
    scheduled, blocking = [], []
    for job, calc, customer in db.execute(stmt).all():
        # received-check needs the chassis status even when it's not in the yard pool:
        st = ch_status.get(job.chassis_record_id)
        if st is None and job.chassis_record_id:
            rec = db.get(ChassisRecord, job.chassis_record_id)
            st = rec.status if rec else None
        if chassis_received(job, st):
            continue
        eta = job.chassis_eta.date() if job.chassis_eta else None
        customer_name = customer.name if customer else None
        if eta == for_date:
            scheduled.append(_job_item(job, customer_name, calc, location="Yard",
                                       status="expected_arrival", since=eta))
        elif eta is not None and eta < for_date:
            overdue = (for_date - eta).days
            blocking.append(_job_item(job, customer_name, calc, location="Yard",
                                      status="chassis_overdue", since=eta,
                                      flag=f"chassis ETA overdue {overdue}d"))
    used = len(in_flight)
    total = len(db.execute(
        select(ParkingBay.id).where(ParkingBay.is_active.is_(True))).all())
    return WorksheetSections(scheduled=scheduled, in_flight=in_flight, blocking=blocking), \
        WorksheetCapacity(used=used, total=total)


def _dispatch_team(db: Session, for_date: date_type, branch_id) -> WorksheetSections:
    # scheduled — completed jobs pending collection (linked chassis not yet dispatched).
    stmt = (
        select(ProductionJob, CalculationRecord, Customer, ChassisRecord)
        .join(ChassisRecord, ProductionJob.chassis_record_id == ChassisRecord.id)
        .join(CalculationRecord, ProductionJob.calculation_record_id == CalculationRecord.id, isouter=True)
        .join(Customer, CalculationRecord.customer_id == Customer.id, isouter=True)
        .where(ProductionJob.completed_at.isnot(None), ChassisRecord.status != "dispatched")
    )
    if branch_id is not None:
        stmt = stmt.where(ProductionJob.branch_id == branch_id)
    scheduled = []
    for job, calc, customer, rec in db.execute(stmt).all():
        completed = job.completed_at.date() if job.completed_at else None
        waiting = (for_date - completed).days if completed else None
        scheduled.append(_job_item(
            job, (customer.name if customer else None), calc,
            location=("Yard" if rec.status == "in_workshop" else None),
            status="pending_collection", since=completed, chassis_vin=rec.vin,
            flag=(f"awaiting collection {waiting}d" if waiting is not None and waiting > 7 else None),
        ))

    # in_flight — chassis collected (DCL) on the selected date.
    in_flight = []
    rows = db.execute(
        select(ChassisLifecycleEvent, ChassisRecord)
        .join(ChassisRecord, ChassisLifecycleEvent.chassis_record_id == ChassisRecord.id)
        .where(ChassisLifecycleEvent.event_type == "DCL",
               ChassisLifecycleEvent.event_date == for_date)
    ).all()
    job_ctx = _jobs_for_chassis(db, [rec.id for _, rec in rows])
    for evt, rec in rows:
        job, customer_name, calc = job_ctx.get(rec.id, (None, None, None))
        if not _branch_visible(job, branch_id):
            continue
        if job is not None:
            in_flight.append(_job_item(job, customer_name, calc, location=None,
                                       status="dispatched", since=evt.event_date,
                                       chassis_vin=rec.vin))
        else:
            in_flight.append(WorksheetItem(chassis_vin=rec.vin, customer=rec.customer_name,
                                           status="dispatched", since=evt.event_date))
    return WorksheetSections(scheduled=scheduled, in_flight=in_flight, blocking=[])


def build_team_worksheet(db: Session, team: str, for_date: Optional[date_type] = None,
                         branch_id: Optional[int] = None) -> TeamWorksheet:
    """The §0.4 endpoint body. 422 on unknown team or a date beyond ±7 days (§3.3 N=7 lock)."""
    if team not in TEAMS:
        raise HTTPException(status_code=422,
                            detail=f"team must be one of {', '.join(TEAMS)}")
    for_date = for_date or _today()
    if abs((for_date - _today()).days) > MAX_DATE_OFFSET_DAYS:
        raise HTTPException(status_code=422,
                            detail=f"date must be within ±{MAX_DATE_OFFSET_DAYS} days of today")

    capacity = None
    if team in ("vacuum", "press"):
        sections = _slot_team(db, team, for_date, branch_id)
    elif team == "assembly":
        sections = _assembly_team(db, branch_id)
    elif team == "parking":
        sections, capacity = _parking_team(db, for_date, branch_id)
    else:  # dispatch
        sections = _dispatch_team(db, for_date, branch_id)
    return TeamWorksheet(team=team, date=for_date, capacity=capacity, sections=sections)
