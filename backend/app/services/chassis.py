"""WO v4.28 §3 — chassis lifecycle service (chassis_records + VCL/DCL events).

Thin router → these functions. VCL opens a new cycle; DCL closes the open (VCL-without-DCL) cycle
(§0 lock). Typed failures raise HTTPException (404/409/422) so the router stays thin.

The checklist templates below are a **Workshop-refine placeholder** (WO v4.28 — the real VCL/DCL
forms weren't available at build time). They're served as DATA (not hard-coded into the UI) so a
future micro-WO can move them to an admin-owned table without touching code.
"""
from datetime import date, datetime, timezone

from fastapi import HTTPException
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.database import Customer            # WO v4.34.1 §3.4 — cross-schema dealer-name resolve
from app.models.mes import (
    AssemblyBay, ChassisLifecycleEvent, ChassisPhoto, ChassisRecord, ParkingBay, ProductionJob,
)
from app.schemas.chassis import (
    ChassisEventOut, ChassisPhotoOut, ChassisRecordDetail, ChassisRecordOut,
)
from app.services import file_store

# Workshop-refine placeholder checklists (WO v4.28). type: 'bool' (toggle) | 'text'.
CHASSIS_CHECKLIST_TEMPLATES = {
    "VCL": [
        {"key": "exterior_damage", "label": "Exterior / body damage noted", "type": "bool"},
        {"key": "tyres", "label": "Tyres condition OK", "type": "bool"},
        {"key": "lights", "label": "Lights working", "type": "bool"},
        {"key": "mirrors", "label": "Mirrors intact", "type": "bool"},
        {"key": "glass", "label": "Glass / windscreen OK", "type": "bool"},
        {"key": "fuel_level", "label": "Fuel level", "type": "text"},
        {"key": "mileage", "label": "Mileage / hours", "type": "text"},
        {"key": "keys", "label": "Keys received", "type": "bool"},
        {"key": "documents", "label": "Documents received", "type": "bool"},
        # WO v4.33 §0.8 — the customer's specified cab-to-body gap; Simeon enters/verifies it
        # here. capture_event lifts a numeric value through to chassis_records.body_gap_mm so
        # Pre-Job Cards can pre-populate (template-driven field: no UI change needed).
        {"key": "body_gap_mm", "label": "Body gap (mm) — customer spec", "type": "text"},
    ],
    "DCL": [
        {"key": "workmanship", "label": "Workmanship / finish OK", "type": "bool"},
        {"key": "fittings_secure", "label": "Fittings secure", "type": "bool"},
        {"key": "doors_seals", "label": "Doors / seals OK", "type": "bool"},
        {"key": "cleanliness", "label": "Cleanliness OK", "type": "bool"},
        {"key": "lights_retest", "label": "Lights re-test passed", "type": "bool"},
        {"key": "customer_walkaround", "label": "Customer walkaround done", "type": "bool"},
        {"key": "signoff_name", "label": "Dispatch sign-off (name)", "type": "text"},
    ],
}
# WO v4.35 §3.1 (DEV-4) — the canonical chassis lifecycle event types. event_type has NO DB CHECK
# constraint (VARCHAR(24), validated app-side), so this set is the single source of truth; every
# event-insertion path validates against it before db.add(). 'assembly_assigned' is written by
# assign_assembly_bay(); 'body_attached' (WO v4.35) is written by record_body_attached() — a PHASE
# marker (DEV-2): it is logged as an event but deliberately does NOT change chassis_records.status,
# which stays 'in_assembly' (status promotion is a v4.36+ workshop-tablet concern).
ALLOWED_EVENT_TYPES = {"VCL", "DCL", "assembly_assigned", "body_attached"}

# WO v4.35 §3.3b (STRETCH) — the JOB-side bay events live in a SEPARATE table (production_job_bay_events)
# with their OWN allowlist; deliberately NOT folded into ALLOWED_EVENT_TYPES so a job-bay event can never
# slip into the chassis_lifecycle_events insert path (ADR 0025 footnote C — audit/event tables by entity).
ALLOWED_BAY_EVENT_TYPES = {"panels_arrived_in_bay"}

# event_type -> the chassis_records.status it WRITES. Phase markers (assembly_assigned via
# assign_assembly_bay; body_attached) are intentionally absent — they don't move the status column.
_STATUS_FOR = {"VCL": "in_workshop", "DCL": "dispatched"}


def _now():
    return datetime.now(timezone.utc)


def _dealer_names(db: Session, dealer_ids) -> dict:
    """WO v4.34.1 §3.4 — batch-resolve dealer_id → customers.name (cross-schema icb_costings)."""
    ids = {d for d in dealer_ids if d}
    if not ids:
        return {}
    return {cid: name for cid, name in db.execute(
        select(Customer.id, Customer.name).where(Customer.id.in_(ids))).all()}


def list_chassis(db: Session, *, q=None, status=None, limit=50, offset=0) -> list[ChassisRecordOut]:
    stmt = select(ChassisRecord)
    if status:
        stmt = stmt.where(ChassisRecord.status == status)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(ChassisRecord.vin.ilike(like), ChassisRecord.job_number.ilike(like),
                              ChassisRecord.customer_name.ilike(like)))
    stmt = stmt.order_by(ChassisRecord.updated_at.desc().nullslast(), ChassisRecord.id.desc())
    recs = db.execute(stmt.limit(limit).offset(offset)).scalars().all()
    if not recs:
        return []
    ids = [r.id for r in recs]
    aggs = db.execute(
        select(ChassisLifecycleEvent.chassis_record_id, func.count().label("n"),
               func.max(ChassisLifecycleEvent.event_date).label("latest"))
        .where(ChassisLifecycleEvent.chassis_record_id.in_(ids))
        .group_by(ChassisLifecycleEvent.chassis_record_id)
    ).all()
    agg = {r[0]: (r[1], r[2]) for r in aggs}
    # Current assembly bay (derived, §0.12) for the in_assembly rows on this page — one batched query.
    in_assembly_ids = [r.id for r in recs if r.status == "in_assembly"]
    bay_by_rec: dict = {}
    if in_assembly_ids:
        for rec_id, bay_id in db.execute(
            select(ChassisLifecycleEvent.chassis_record_id, ChassisLifecycleEvent.assembly_bay_id)
            .where(ChassisLifecycleEvent.chassis_record_id.in_(in_assembly_ids),
                   ChassisLifecycleEvent.event_type == "assembly_assigned")
            .order_by(ChassisLifecycleEvent.chassis_record_id, ChassisLifecycleEvent.id.desc())
        ).all():
            bay_by_rec.setdefault(rec_id, bay_id)        # first per record = latest (id desc)
    dealer_names = _dealer_names(db, (r.dealer_id for r in recs))   # §3.4 — batch cross-schema resolve
    out = []
    for r in recs:
        n, latest = agg.get(r.id, (0, None))
        o = ChassisRecordOut.model_validate(r)
        o.event_count, o.latest_event_date = n, latest
        o.current_assembly_bay_id = bay_by_rec.get(r.id)
        o.dealer_name = dealer_names.get(r.dealer_id)
        out.append(o)
    return out


def list_chassis_models(db: Session):
    """WO v4.34 §3.7 — the active chassis-type DDM, ordered for the make/model dropdowns. ONE
    controlled vocabulary across Planning ack, Pre-Job Card, and Chassis +New/edit (read-only;
    admin CRUD is v4.35)."""
    from app.models.mes import ChassisModel
    return db.execute(
        select(ChassisModel).where(ChassisModel.is_active.is_(True))
        .order_by(ChassisModel.sort_order, ChassisModel.make, ChassisModel.model)
    ).scalars().all()


def get_detail(db: Session, record_id: int) -> ChassisRecordDetail:
    rec = db.get(ChassisRecord, record_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="chassis record not found")
    events = db.execute(
        select(ChassisLifecycleEvent).where(ChassisLifecycleEvent.chassis_record_id == record_id)
        .order_by(ChassisLifecycleEvent.cycle_number, ChassisLifecycleEvent.event_type)
    ).scalars().all()
    ev_ids = [e.id for e in events]
    photos_by_ev: dict = {}
    if ev_ids:
        for p in db.execute(select(ChassisPhoto).where(
                ChassisPhoto.lifecycle_event_id.in_(ev_ids))).scalars().all():
            po = ChassisPhotoOut.model_validate(p)
            po.url = f"/api/chassis-records/photos/{p.id}"
            photos_by_ev.setdefault(p.lifecycle_event_id, []).append(po)
    detail = ChassisRecordDetail.model_validate(rec)
    detail.event_count = len(events)
    detail.latest_event_date = max((e.event_date for e in events if e.event_date), default=None)
    detail.dealer_name = _dealer_names(db, [rec.dealer_id]).get(rec.dealer_id)   # §3.4 — cross-schema resolve
    if rec.status == "in_assembly":                  # current bay derived from the latest event (§0.12)
        aa = [e for e in events if e.event_type == "assembly_assigned"]
        detail.current_assembly_bay_id = max(aa, key=lambda e: e.id).assembly_bay_id if aa else None
    out_events = []
    for e in events:
        eo = ChassisEventOut.model_validate(e)
        eo.photos = photos_by_ev.get(e.id, [])
        out_events.append(eo)
    detail.events = out_events
    return detail


def create_chassis(db: Session, payload, who: str) -> ChassisRecord:
    vin = (payload.vin or "").strip()
    if not vin:
        raise HTTPException(status_code=422, detail="vin is required")
    if db.execute(select(ChassisRecord.id).where(ChassisRecord.vin == vin)).first():
        raise HTTPException(status_code=409, detail=f"chassis with VIN {vin} already exists")
    rec = ChassisRecord(vin=vin[:32], source="manual", status="received",
                        created_via="manual_chassis_menu",       # WO v4.34 §0.4 — provenance
                        created_by=who, updated_by=who,
                        **payload.model_dump(exclude={"vin"}, exclude_none=True))
    db.add(rec)
    db.commit()
    db.refresh(rec)
    return rec


def create_expected_chassis(db: Session, *, make, vin, body_gap_mm, created_via,
                            created_source_ref, who, source=None) -> ChassisRecord:
    """WO v4.34 §0.3/§0.5 — the SINGLE creation point for a pipeline 'expected' chassis, shared by
    both touchpoints (Pre-Job submit §3.2 + Planning ack §3.3) so the rows are identical by
    construction. `vin` may be NULL (unknown until receive — NULLs don't collide on
    uq_chassis_records_vin); `make` is truncated to the column width (64). `created_via` is the
    canonical provenance (VARCHAR(32)); `source` is the legacy VARCHAR(16) field — a short honest
    token ('pre_job_card' / 'planning_ack'), defaulting to created_via truncated. FLUSHES, never
    commits — the caller's transaction owns the commit, keeping the insert atomic with its
    touchpoint."""
    chassis = ChassisRecord(
        vin=((vin or "").strip()[:32] or None),
        status="expected",
        source=(source or created_via)[:16],
        created_via=created_via,
        created_source_ref=((created_source_ref or "")[:64] or None),
        make=((make or "").strip()[:64] or None),
        body_gap_mm=body_gap_mm,
        created_by=who, updated_by=who,
    )
    db.add(chassis)
    db.flush()                                            # populate id for the caller's FK link
    return chassis


def update_chassis(db: Session, record_id: int, payload, who: str) -> ChassisRecord:
    rec = db.get(ChassisRecord, record_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="chassis record not found")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(rec, k, v)
    rec.updated_by = who
    db.commit()
    db.refresh(rec)
    return rec


def capture_vin(db: Session, record_id: int, vin: str, who: str) -> ChassisRecord:
    """WO v4.34.1 §3.4b (Gap A) — late VIN capture from the Chassis page.

    The backend NULL-state guard: a VIN write is accepted ONLY when the current value IS NULL —
    a one-way NULL→value transition. This is the FIRST real backend enforcement of the sign-off
    integrity that v4.34 implemented frontend-only (ADR 0022 footnote): an attested/known VIN can
    never be silently rewritten through this path. Stamps vin_source='chassis_page_manual' for
    provenance, and refuses a value already anchoring another chassis (uq_chassis_records_vin)."""
    rec = db.get(ChassisRecord, record_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="chassis record not found")
    vin = (vin or "").strip()
    if not vin:
        raise HTTPException(status_code=422, detail="vin is required")
    if rec.vin:                                            # NULL-state guard — write-once
        raise HTTPException(status_code=409,
                            detail=f"VIN already set ({rec.vin}); it cannot be overwritten from the Chassis page")
    vin = vin[:32]
    clash = db.execute(select(ChassisRecord.id).where(
        ChassisRecord.vin == vin, ChassisRecord.id != record_id)).first()
    if clash:
        raise HTTPException(status_code=409, detail=f"VIN {vin} already anchors another chassis record")
    rec.vin = vin
    rec.vin_source = "chassis_page_manual"
    rec.updated_by = who
    db.commit()
    db.refresh(rec)
    return rec


def capture_event(db: Session, record_id: int, event_type: str, payload, who: str) -> ChassisLifecycleEvent:
    if event_type not in ("VCL", "DCL"):
        raise HTTPException(status_code=422, detail="event_type must be VCL or DCL")
    rec = db.get(ChassisRecord, record_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="chassis record not found")
    events = db.execute(
        select(ChassisLifecycleEvent).where(ChassisLifecycleEvent.chassis_record_id == record_id)
    ).scalars().all()

    if payload.cycle_number is not None:
        cycle = payload.cycle_number
    elif event_type == "VCL":
        cycle = (max((e.cycle_number for e in events), default=0)) + 1   # VCL opens a fresh cycle
    else:  # DCL closes the highest cycle that has a VCL but no DCL
        vcl_cycles = {e.cycle_number for e in events if e.event_type == "VCL"}
        dcl_cycles = {e.cycle_number for e in events if e.event_type == "DCL"}
        open_cycles = sorted(vcl_cycles - dcl_cycles)
        if not open_cycles:
            raise HTTPException(status_code=422, detail="no open cycle to dispatch (capture a VCL first)")
        cycle = open_cycles[-1]

    if any(e.cycle_number == cycle and e.event_type == event_type for e in events):
        raise HTTPException(status_code=409, detail=f"{event_type} already captured for cycle {cycle}")

    evt = ChassisLifecycleEvent(
        chassis_record_id=record_id, cycle_number=cycle, event_type=event_type,
        event_date=payload.event_date or date.today(), checklist_json=payload.checklist_json,
        notes=payload.notes, created_by=who)
    db.add(evt)
    rec.status = _STATUS_FOR[event_type]
    # WO v4.33 §0.8 — lift Simeon's Body Gap entry from the VCL checklist through to the
    # record column (Pre-Job Cards pre-populate from chassis_records.body_gap_mm).
    if event_type == "VCL" and payload.checklist_json:
        raw = str(payload.checklist_json.get("body_gap_mm", "") or "")
        digits = "".join(ch for ch in raw if ch.isdigit())
        if digits:
            rec.body_gap_mm = int(digits)
    rec.updated_by = who
    db.commit()
    db.refresh(evt)
    return evt


def _current_assembly_bay_id(db: Session, record_id: int):
    """The assembly bay a chassis is CURRENTLY on — the latest 'assembly_assigned' event's bay
    (WO v4.31 §0.12: the events log is the single source of truth; no denormalised column). Callers
    gate on status == 'in_assembly' to tell "on a bay now" from a dispatched chassis's history."""
    return db.execute(
        select(ChassisLifecycleEvent.assembly_bay_id)
        .where(ChassisLifecycleEvent.chassis_record_id == record_id,
               ChassisLifecycleEvent.event_type == "assembly_assigned")
        .order_by(ChassisLifecycleEvent.id.desc()).limit(1)
    ).scalar()


def assign_assembly_bay(db: Session, record_id: int, bay_id: int, who: str,
                        event_date=None, notes=None) -> ChassisLifecycleEvent:
    """WO v4.31 §0.4/§0.12 — attribute a booked-in chassis to an assembly bay (parking -> assembly).

    UPSERTs the single 'assembly_assigned' event for the chassis's open cycle (the destination bay lives
    on the EVENT — the single source of truth) and moves chassis_records.status to 'in_assembly'. No
    denormalised bay column (§0.12). One chassis per bay (occupancy guard, BA lock 2026-06-10);
    re-assigning moves the chassis to a different (free) bay.
    """
    rec = db.get(ChassisRecord, record_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="chassis record not found")
    bay = db.get(AssemblyBay, bay_id)
    if bay is None or not bay.is_active:
        raise HTTPException(status_code=404, detail="assembly bay not found")
    # Occupancy guard: at most one chassis per assembly bay (Phase-3; yard coordination is Phase 4).
    # Derived from the events log — a bay is occupied iff another in_assembly chassis's latest
    # assembly_assigned event points at it (§0.12: no denormalised bay column).
    for other_id, other_vin in db.execute(
        select(ChassisRecord.id, ChassisRecord.vin)
        .where(ChassisRecord.status == "in_assembly", ChassisRecord.id != record_id)
    ).all():
        if _current_assembly_bay_id(db, other_id) == bay_id:
            raise HTTPException(status_code=409,
                                detail=f"assembly bay {bay.code} is already occupied by {other_vin}")
    # Must be booked in: assign against the highest open (VCL-without-DCL) cycle.
    events = db.execute(
        select(ChassisLifecycleEvent).where(ChassisLifecycleEvent.chassis_record_id == record_id)
    ).scalars().all()
    open_cycles = sorted({e.cycle_number for e in events if e.event_type == "VCL"}
                         - {e.cycle_number for e in events if e.event_type == "DCL"})
    if not open_cycles:
        raise HTTPException(status_code=422,
                            detail="no open workshop cycle — capture a VCL (book-in) first")
    cycle = open_cycles[-1]
    # UPSERT the single assembly_assigned event for this cycle (re-assign = move to a different bay).
    evt = next((e for e in events
                if e.cycle_number == cycle and e.event_type == "assembly_assigned"), None)
    if evt is None:
        evt = ChassisLifecycleEvent(chassis_record_id=record_id, cycle_number=cycle,
                                    event_type="assembly_assigned", created_by=who)
        db.add(evt)
    evt.assembly_bay_id = bay_id
    evt.event_date = event_date or date.today()
    if notes is not None:
        evt.notes = notes
    rec.status = "in_assembly"                  # §0.12: denormalise STATE onto status (no bay column)
    rec.updated_by = who
    db.commit()
    db.refresh(evt)
    return evt


def list_assembly_bays(db: Session):
    return db.execute(
        select(AssemblyBay).where(AssemblyBay.is_active.is_(True))
        .order_by(AssemblyBay.sort_order, AssemblyBay.id)
    ).scalars().all()


def list_parking_bays(db: Session):
    return db.execute(
        select(ParkingBay).where(ParkingBay.is_active.is_(True))
        .order_by(ParkingBay.sort_order, ParkingBay.id)
    ).scalars().all()


def current_occupants(db: Session) -> dict:
    """WO v4.32 §0.4 — {assembly_bay_id: occupant} for every occupied assembly bay, derived from
    the latest 'assembly_assigned' event of each in_assembly chassis (§0.12 — events are the
    single source of truth; this is the batched form of _current_assembly_bay_id). Occupant =
    {chassis_id, vin, customer_name, since, job_id, job_number} (job fields None when no
    production job links the chassis)."""
    rows = db.execute(
        select(ChassisRecord.id, ChassisRecord.vin, ChassisRecord.customer_name,
               ChassisLifecycleEvent.assembly_bay_id, ChassisLifecycleEvent.event_date,
               ChassisLifecycleEvent.created_at)
        .join(ChassisLifecycleEvent, ChassisLifecycleEvent.chassis_record_id == ChassisRecord.id)
        .where(ChassisRecord.status == "in_assembly",
               ChassisLifecycleEvent.event_type == "assembly_assigned")
        .order_by(ChassisRecord.id, ChassisLifecycleEvent.id.desc())
    ).all()
    latest_by_chassis: dict = {}
    for cid, vin, cust, bay_id, ev_date, created in rows:
        latest_by_chassis.setdefault(cid, (vin, cust, bay_id, ev_date, created))  # first = latest (id desc)
    job_by_chassis: dict = {}
    if latest_by_chassis:
        for jid, jnum, crid in db.execute(
            select(ProductionJob.id, ProductionJob.job_number, ProductionJob.chassis_record_id)
            .where(ProductionJob.chassis_record_id.in_(list(latest_by_chassis)))
        ).all():
            job_by_chassis.setdefault(crid, (jid, jnum))
    occupants: dict = {}
    for cid, (vin, cust, bay_id, ev_date, created) in latest_by_chassis.items():
        jid, jnum = job_by_chassis.get(cid, (None, None))
        occupants[bay_id] = {
            "chassis_id": cid, "vin": vin, "customer_name": cust,
            "since": ev_date or (created.date() if created else None),
            "job_id": jid, "job_number": jnum,
        }
    return occupants


def assembly_bays_utilisation(db: Session) -> list:
    """WO v4.32 §0.4 / v4.35 §3.3b — the 5 assembly bays + per-bay utilisation and 6-state. BayOut.state
    is derived by compute_bay_merge_readiness (the SINGLE source of truth, shared with the §3.3b auto-merge
    prompt): empty · pre_assembly · ready_to_merge · awaiting_attachment · attached_today · post_attached.
    Additive extension of the v4.31 /bays/assembly response — v4.31 consumers (useBayModel reads id/code/
    label) are unaffected; occupant fields stay optional."""
    from app.schemas.chassis import BayOut
    occupants = current_occupants(db)                # batched once; passed into the per-bay helper
    out = []
    for bay in list_assembly_bays(db):
        o = BayOut.model_validate(bay)
        r = compute_bay_merge_readiness(db, bay.id, occupants=occupants)
        o.state = r["state"]
        o.body_attached_on = r["body_attached_on"]
        o.mismatch = r["mismatch"]                   # §3.3b UX — panels + chassis are different jobs
        o.panels_job_id = r["panels_job_id"]         # the job whose panels are on the bay (move-back undo)
        o.panels_job_number = r["panels_job_number"]
        occ = occupants.get(bay.id)
        if occ:
            o.occupied = True
            o.occupant_chassis_id = occ["chassis_id"]
            o.occupant_vin = occ["vin"]
            o.occupant_customer = occ["customer_name"]
            o.occupant_job_id = occ["job_id"]
            o.occupant_job_number = occ["job_number"]
            o.since = occ["since"]
        elif r["state"] == "pre_assembly":           # panels staged; chassis not yet on the bay (§3.3b)
            o.occupant_job_id = r["production_job_id"]
            o.occupant_job_number = r["production_job_number"]
        out.append(o)
    return out


def _latest_body_attached_dates(db: Session, chassis_ids: list) -> dict:
    """{chassis_id: latest body_attached event_date} for the given chassis (WO v4.35 §0.20 derivation)."""
    if not chassis_ids:
        return {}
    out: dict = {}
    for cid, ev_date in db.execute(
        select(ChassisLifecycleEvent.chassis_record_id, ChassisLifecycleEvent.event_date)
        .where(ChassisLifecycleEvent.chassis_record_id.in_(chassis_ids),
               ChassisLifecycleEvent.event_type == "body_attached")
        .order_by(ChassisLifecycleEvent.chassis_record_id, ChassisLifecycleEvent.id.desc())
    ).all():
        out.setdefault(cid, ev_date)                 # first per chassis = latest (id desc)
    return out


def _panels_for_bay(db: Session, bay_id: int):
    """(production_job_id, job_number) of the panels currently in a bay, or (None, None) — the latest
    'panels_arrived_in_bay' event for the bay (WO v4.35 §3.3b)."""
    from app.models.mes import ProductionJobBayEvent
    row = db.execute(
        select(ProductionJobBayEvent.production_job_id, ProductionJob.job_number)
        .join(ProductionJob, ProductionJob.id == ProductionJobBayEvent.production_job_id)
        .where(ProductionJobBayEvent.bay_id == bay_id,
               ProductionJobBayEvent.event_type == "panels_arrived_in_bay")
        .order_by(ProductionJobBayEvent.id.desc()).limit(1)
    ).first()
    return (row[0], row[1]) if row else (None, None)


def compute_bay_merge_readiness(db: Session, bay_id: int, *, occupants=None) -> dict:
    """WO v4.35 §3.3b (§0.19–0.21) — THE single source of truth for a bay's merge state, shared by the
    6-state tile derivation (assembly_bays_utilisation) AND the auto-merge prompt firing logic, so the two
    never diverge (BA-ratified). 'ready' (state 'ready_to_merge') ⟺ the bay holds the job's panels
    (panels_arrived_in_bay) AND its chassis (assembly_assigned, the SAME production job) AND the body is not
    attached yet. The match is by job identity: the panels event's production_job IS the chassis occupant's
    job — and the occupant job is the one whose production_jobs.chassis_record_id is the assembly_assigned
    chassis, so this is exactly the BA's "chassis_record_id matches the chassis of the assembly_assigned
    event" condition. Pass `occupants` (current_occupants) to avoid re-querying it per bay.

    States: empty (nothing) · pre_assembly (panels, no chassis) · ready_to_merge (matched, no body) ·
    awaiting_attachment (chassis, no matching panels, no body) · attached_today · post_attached."""
    occ = (occupants if occupants is not None else current_occupants(db)).get(bay_id)
    panels_job_id, panels_job_number = _panels_for_bay(db, bay_id)
    att = _latest_body_attached_dates(db, [occ["chassis_id"]]).get(occ["chassis_id"]) if occ else None
    occ_job_id = occ["job_id"] if occ else None
    matched = panels_job_id is not None and occ_job_id is not None and panels_job_id == occ_job_id
    today = date.today()
    if occ is None:
        state = "pre_assembly" if panels_job_id is not None else "empty"
    elif att is not None:
        state = "attached_today" if att >= today else "post_attached"
    elif matched:
        state = "ready_to_merge"
    else:
        state = "awaiting_attachment"
    return {
        "state": state,
        "ready": state == "ready_to_merge",
        "has_panels": panels_job_id is not None,
        "has_chassis": occ is not None,
        "matched": matched,
        # WO v4.35 §3.3b UX — panels + a chassis that belong to DIFFERENT jobs (a wrong-bay drop). The
        # state stays 'awaiting_attachment' (the 6-state machine is unchanged); this flag drives a "different
        # jobs — not linked" cue so the silent non-merge becomes legible.
        "mismatch": (panels_job_id is not None and occ_job_id is not None and not matched),
        "body_attached_on": att,
        "production_job_id": occ_job_id if occ else panels_job_id,
        "production_job_number": (occ["job_number"] if occ else panels_job_number),
        "panels_job_id": panels_job_id,            # the job whose panels are on the bay (for the move-back undo)
        "panels_job_number": panels_job_number,
        "chassis_id": occ["chassis_id"] if occ else None,
    }


def _latest_cycle(db: Session, record_id: int) -> int:
    return db.execute(select(func.max(ChassisLifecycleEvent.cycle_number))
                      .where(ChassisLifecycleEvent.chassis_record_id == record_id)).scalar() or 1


def _has_event(db: Session, record_id: int, etype: str, cycle: int) -> bool:
    return db.execute(
        select(ChassisLifecycleEvent.id).where(
            ChassisLifecycleEvent.chassis_record_id == record_id,
            ChassisLifecycleEvent.event_type == etype,
            ChassisLifecycleEvent.cycle_number == cycle).limit(1)).first() is not None


def record_body_attached(db: Session, record_id: int, production_job_id: int, who: str,
                         notes=None) -> ChassisLifecycleEvent:
    """WO v4.35 §3.2 — the body_attached chokepoint (DEV-2 PHASE-only: logs the event, chassis_records
    .status stays 'in_assembly'). Pre-conditions (§0.4): the chassis has a prior assembly_assigned event
    (it's on a bay), and the linked production_job is 'in_production' (actor permission is gated at the
    router). Validation (§0.22): no double-linkage, and the swap rule via the planner-attestation SIGNAL
    (DEV-1) — if the job's Pre-Job Card attested a VIN at planning-ack (vin_number set AND
    planner_signoff_at set), the chassis VIN must match. Idempotent: 409 if already attached this cycle."""
    from app.models.mes import PrejobCard
    rec = db.get(ChassisRecord, record_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="chassis record not found")
    job = db.get(ProductionJob, production_job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="production job not found")
    if job.status not in ("planning", "in_production"):
        raise HTTPException(status_code=422,
                            detail=f"job {job.job_number or job.id} is '{job.status}' — a body can only be "
                                   "attached to a job in planning or production")
    # WO v4.35 (16 Jun ruling) — pre-condition LOOSENED to accept 'planning' too, and we deliberately do
    # NOT auto-transition planning -> in_production here. Post-attachment the job stays at its current
    # status (parallel to DEV-2: chassis stays 'in_assembly'). Both "stale-looking" fields are intentional:
    # the body_attached EVENT is the meaningful moment (bay tile + KPI + Assembly section); status promotion
    # lands with the v4.36 QC sprint.
    cycle = _latest_cycle(db, record_id)
    if not _has_event(db, record_id, "assembly_assigned", cycle):
        raise HTTPException(status_code=422,
                            detail="chassis is not on an assembly bay — assign it to a bay first")
    if _has_event(db, record_id, "body_attached", cycle):
        raise HTTPException(status_code=409, detail="body already attached for this chassis cycle")
    if job.chassis_record_id not in (None, record_id):
        raise HTTPException(status_code=409,
                            detail=f"job {job.job_number or job.id} is already linked to a different chassis")
    # §0.22 swap rule — DEV-1 signal: a Pre-Job Card VIN attested at planning ack locks the chassis.
    card = db.execute(select(PrejobCard).where(PrejobCard.calculation_id == job.calculation_record_id)
                      .order_by(PrejobCard.id.desc())).scalars().first()
    if card is not None and card.vin_number and card.planner_signoff_at is not None:
        if (rec.vin or "") != card.vin_number:
            raise HTTPException(
                status_code=409,
                detail=(f"Cannot attach this chassis — planner attested to VIN {card.vin_number} at "
                        f"planning ack (this chassis is VIN {rec.vin or 'unknown'})."))
    evt = ChassisLifecycleEvent(chassis_record_id=record_id, cycle_number=cycle,
                                event_type="body_attached", event_date=date.today(),
                                notes=notes, created_by=who)
    db.add(evt)
    if job.chassis_record_id is None:
        job.chassis_record_id = record_id            # complete the body↔chassis link (the merge)
    rec.updated_by = who                             # touch only; status stays 'in_assembly' (DEV-2)
    db.commit()
    db.refresh(evt)
    return evt


def record_panels_arrived_in_bay(db: Session, production_job_id: int, bay_id: int, *,
                                 user_id=None, notes=None, event_type: str = "panels_arrived_in_bay"):
    """WO v4.35 §3.3b — the panels-arrived chokepoint (the JOB-side of the merge; mirrors
    record_body_attached). Writes to production_job_bay_events (NOT chassis_lifecycle_events). Validation:
    (1) event_type allowlisted; (2) job + active bay exist; (3) a job's panels live in exactly ONE bay —
    re-drop → 409 (idempotency / double-linkage); (4) a bay holds exactly ONE job's panels — drop on a bay
    already holding another job's panels → 409 (busy-bay). The backend is the source of truth; the UI does
    not gate these — it surfaces the 409 remediation text (§3.3b consideration 1 & 2)."""
    from app.models.mes import ProductionJobBayEvent
    if event_type not in ALLOWED_BAY_EVENT_TYPES:
        raise HTTPException(status_code=422, detail=f"event type '{event_type}' is not allowed")
    job = db.get(ProductionJob, production_job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="production job not found")
    bay = db.get(AssemblyBay, bay_id)
    if bay is None or not bay.is_active:
        raise HTTPException(status_code=404, detail="assembly bay not found")
    job_ref = job.job_number or job.id
    # (3) double-linkage / idempotency — the job's panels are already in a bay
    existing = db.execute(
        select(ProductionJobBayEvent).where(
            ProductionJobBayEvent.production_job_id == production_job_id,
            ProductionJobBayEvent.event_type == "panels_arrived_in_bay")
        .order_by(ProductionJobBayEvent.id.desc())).scalars().first()
    if existing is not None:
        prior = db.get(AssemblyBay, existing.bay_id)
        prior_code = prior.code if prior else f"bay {existing.bay_id}"
        if existing.bay_id == bay_id:
            raise HTTPException(status_code=409,
                                detail=f"panels for job {job_ref} are already in {prior_code}")
        raise HTTPException(status_code=409,
                            detail=(f"panels for job {job_ref} are already in {prior_code} — "
                                    "move them back before assigning to another bay"))
    # (4) busy-bay — the bay already holds another job's panels
    other = db.execute(
        select(ProductionJobBayEvent).where(
            ProductionJobBayEvent.bay_id == bay_id,
            ProductionJobBayEvent.event_type == "panels_arrived_in_bay")
        .order_by(ProductionJobBayEvent.id.desc())).scalars().first()
    if other is not None:
        raise HTTPException(status_code=409, detail=f"{bay.code} already holds panels for another job")
    evt = ProductionJobBayEvent(production_job_id=production_job_id, bay_id=bay_id,
                                event_type=event_type, user_id=user_id, notes=notes)
    db.add(evt)
    db.commit()
    db.refresh(evt)
    return evt


def clear_panels_arrived(db: Session, production_job_id: int) -> dict:
    """WO v4.35 §3.3b — the move-panels-back undo: remove a job's panels_arrived_in_bay event(s) so a
    wrong-bay drop can be corrected without a full reseed (the one-bay-per-job rule otherwise strands the
    panels). Idempotent — returns the count removed (0 if the job had none). 404 if the job is unknown."""
    from app.models.mes import ProductionJobBayEvent
    job = db.get(ProductionJob, production_job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="production job not found")
    removed = db.query(ProductionJobBayEvent).filter(
        ProductionJobBayEvent.production_job_id == production_job_id,
        ProductionJobBayEvent.event_type == "panels_arrived_in_bay").delete(synchronize_session=False)
    db.commit()
    return {"production_job_id": production_job_id, "removed": int(removed or 0)}


def add_photos(db: Session, record_id: int, event_id: int, files, who: str) -> list[ChassisPhotoOut]:
    """Attach uploaded photos to a lifecycle event (validates the event belongs to the chassis)."""
    evt = db.get(ChassisLifecycleEvent, event_id)
    if evt is None or evt.chassis_record_id != record_id:
        raise HTTPException(status_code=404, detail="lifecycle event not found for this chassis")
    out: list[ChassisPhotoOut] = []
    for up in files:
        photo = ChassisPhoto(lifecycle_event_id=event_id, original_filename=up.filename,
                             content_type=up.content_type, uploaded_by=who, file_path="")
        db.add(photo)
        db.flush()                                       # assign photo.id for the path
        rel = file_store.save_chassis_photo(record_id, evt.cycle_number, evt.event_type,
                                            photo.id, up.filename or "photo", up.file)
        photo.file_path = rel
        try:
            photo.size_bytes = file_store.chassis_photo_abspath(rel).stat().st_size
        except OSError:
            pass
        po = ChassisPhotoOut.model_validate(photo)
        po.url = f"/api/chassis-records/photos/{photo.id}"
        out.append(po)
    db.commit()
    return out


def get_photo_file(db: Session, photo_id: int):
    photo = db.get(ChassisPhoto, photo_id)
    if photo is None:
        raise HTTPException(status_code=404, detail="photo not found")
    path = file_store.chassis_photo_abspath(photo.file_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="photo file missing")
    return photo, str(path)
