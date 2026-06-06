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

from app.models.mes import ChassisLifecycleEvent, ChassisPhoto, ChassisRecord
from app.schemas.chassis import (
    ChassisEventOut, ChassisPhotoOut, ChassisRecordDetail, ChassisRecordOut,
)

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
_STATUS_FOR = {"VCL": "in_workshop", "DCL": "dispatched"}


def _now():
    return datetime.now(timezone.utc)


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
    out = []
    for r in recs:
        n, latest = agg.get(r.id, (0, None))
        o = ChassisRecordOut.model_validate(r)
        o.event_count, o.latest_event_date = n, latest
        out.append(o)
    return out


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
            photos_by_ev.setdefault(p.lifecycle_event_id, []).append(ChassisPhotoOut.model_validate(p))
    detail = ChassisRecordDetail.model_validate(rec)
    detail.event_count = len(events)
    detail.latest_event_date = max((e.event_date for e in events if e.event_date), default=None)
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
                        created_by=who, updated_by=who,
                        **payload.model_dump(exclude={"vin"}, exclude_none=True))
    db.add(rec)
    db.commit()
    db.refresh(rec)
    return rec


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
    rec.updated_by = who
    db.commit()
    db.refresh(evt)
    return evt
