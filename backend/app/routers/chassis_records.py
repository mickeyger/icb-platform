"""WO v4.28 §3.3 — chassis lifecycle API (/api/chassis-records). Thin router → services.chassis.

Distinct from the existing /api/chassis (catalogue) and /api/chassis-register (v4.22 raw archive).
Reads are require_user; mutations gate on the v4.28 permission keys (chassis.create/update/vcl/dcl).
"""
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from ..database import User, get_db
from ..deps import require_permission, require_user
from ..schemas.chassis import (
    AssemblyAssignRequest, AwaitingQaOut, BayOut, BodyAttachedRequest, ChassisAuditRow, ChassisCreateResult,
    ChassisEventCapture, ChassisEventOut, ChassisModelOut, ChassisPhotoOut, ChassisRecordCreate,
    ChassisRecordDetail, ChassisRecordOut, ChassisRecordUpdate, ChassisVinCapture,
    MoveToAwaitingQaRequest, ReturnToParkingRequest,
)
from ..services import chassis as svc

router = APIRouter(prefix="/api/chassis-records", tags=["chassis"])


@router.get("", response_model=List[ChassisRecordOut])
def list_records(q: Optional[str] = Query(None), status: Optional[str] = Query(None),
                 limit: int = Query(50, le=200), offset: int = Query(0, ge=0),
                 db: Session = Depends(get_db), user: User = Depends(require_user)):
    return svc.list_chassis(db, q=q, status=status, limit=limit, offset=offset)


@router.get("/checklists")
def checklists(user: User = Depends(require_user)):
    """VCL/DCL checklist templates (DATA, not UI-hard-coded — Workshop-refine placeholder, v4.28)."""
    return svc.CHASSIS_CHECKLIST_TEMPLATES


# WO v4.34 §3.7 — literal path, MUST precede the /{record_id} catch-all below (FastAPI matches in
# declaration order; after it, "models" would 422 as a failed int-parse of record_id).
@router.get("/models", response_model=List[ChassisModelOut])
def chassis_models(db: Session = Depends(get_db), user: User = Depends(require_user)):
    """The chassis-type DDM (active rows) feeding the make/model dropdowns. Read-only (admin CRUD v4.35)."""
    return svc.list_chassis_models(db)


@router.get("/bays/assembly", response_model=List[BayOut])
def bays_assembly(db: Session = Depends(get_db), user: User = Depends(require_user)):
    """WO v4.31 §0.3 — the 5 inside assembly bays (Planning Board assembly lane).
    WO v4.32 §0.4 extends the response with per-bay utilisation (occupant chassis/job + since,
    event-derived per §0.12) — additive fields; v4.31 consumers are unaffected."""
    return svc.assembly_bays_utilisation(db)


@router.get("/bays/parking", response_model=List[BayOut])
def bays_parking(db: Session = Depends(get_db), user: User = Depends(require_user)):
    """WO v4.31 §0.3 — the ~24 outside parking bays (Planning Board parking lane)."""
    return svc.list_parking_bays(db)


@router.get("/awaiting-qa", response_model=List[AwaitingQaOut])
def awaiting_qa(db: Session = Depends(get_db), user: User = Depends(require_user)):
    """WO v4.36a.1 §0.7 — chassis currently in the Awaiting-QA queue (status='awaiting_qa'), feeding the
    Planning Board AWAITING QA zone. Read-only; any authenticated user (the zone is informational)."""
    return svc.list_awaiting_qa(db)


@router.get("/photos/{photo_id}")
def serve_photo(photo_id: int, db: Session = Depends(get_db), user: User = Depends(require_user)):
    photo, path = svc.get_photo_file(db, photo_id)
    return FileResponse(path, media_type=photo.content_type or "application/octet-stream",
                        filename=photo.original_filename or f"photo-{photo_id}")


@router.get("/{record_id}", response_model=ChassisRecordDetail)
def get_record(record_id: int, db: Session = Depends(get_db), user: User = Depends(require_user)):
    return svc.get_detail(db, record_id)


@router.post("", response_model=ChassisCreateResult, status_code=201)
def create_record(payload: ChassisRecordCreate, db: Session = Depends(get_db),
                  user: User = Depends(require_permission("chassis.create"))):
    """WO v4.36a §0.6/§0.7/§0.8 — Add-Chassis: strict-VIN + atomic job link + merge-into-placeholder, OR
    AUTO-ADOPT when the VIN already belongs to a live chassis (adopted=True → AdoptionNotificationModal)."""
    rec = svc.create_chassis(db, payload, who=user.username)
    adopted = bool(getattr(rec, "adopted", False))
    message = (
        f"VIN {rec.vin} is already on chassis {rec.id} (customer {rec.customer_name or '—'}). "
        "This job has been linked to that chassis; its details have been adopted."
    ) if adopted else None
    return ChassisCreateResult(chassis=svc.get_detail(db, rec.id), adopted=adopted,
                               adopted_chassis_id=(rec.id if adopted else None), message=message)


@router.patch("/{record_id}", response_model=ChassisRecordDetail)
def update_record(record_id: int, payload: ChassisRecordUpdate, db: Session = Depends(get_db),
                  user: User = Depends(require_permission("chassis.update"))):
    # WO v4.36.5 §3.1 — sole-editor gate: production is read-only on attributes (admin/planner edit),
    # optimistic-locked on version, and the change is trailed in chassis_records_audit.
    svc.update_chassis(db, record_id, payload, who=user.username, actor_role=user.role, actor_id=user.id)
    return svc.get_detail(db, record_id)


@router.get("/{record_id}/audit", response_model=List[ChassisAuditRow])
def chassis_audit(record_id: int, limit: int = Query(50, le=200), offset: int = Query(0, ge=0),
                  db: Session = Depends(get_db), user: User = Depends(require_permission("chassis.update"))):
    """WO v4.36.5 §3.4 — the per-field change history for a chassis (chassis_records_audit), most-recent-first.
    Gated on chassis.update: the audience that EDITS chassis is the audience that reviews who changed what
    (the BA's parallel-run forensic view). edited_by_name is a snapshot → a single bounded read, no join."""
    return svc.list_chassis_audit(db, record_id, limit=limit, offset=offset)


@router.post("/{record_id}/vin", response_model=ChassisRecordDetail)
def capture_vin(record_id: int, payload: ChassisVinCapture, db: Session = Depends(get_db),
                user: User = Depends(require_permission("chassis.update"))):
    """WO v4.34.1 §3.4b (Gap A) — late VIN capture (planner/admin via chassis.update). The service
    enforces the NULL→value write-once guard + stamps vin_source='chassis_page_manual'."""
    svc.capture_vin(db, record_id, payload.vin, who=user.username)
    return svc.get_detail(db, record_id)


@router.post("/{record_id}/vcl", response_model=ChassisEventOut, status_code=201)
def capture_vcl(record_id: int, payload: ChassisEventCapture, db: Session = Depends(get_db),
                user: User = Depends(require_permission("chassis.vcl"))):
    return svc.capture_event(db, record_id, "VCL", payload, who=user.username)


@router.post("/{record_id}/dcl", response_model=ChassisEventOut, status_code=201)
def capture_dcl(record_id: int, payload: ChassisEventCapture, db: Session = Depends(get_db),
                user: User = Depends(require_permission("chassis.dcl"))):
    return svc.capture_event(db, record_id, "DCL", payload, who=user.username)


@router.post("/{record_id}/assembly", response_model=ChassisEventOut, status_code=201)
def assign_assembly(record_id: int, payload: AssemblyAssignRequest, db: Session = Depends(get_db),
                    user: User = Depends(require_permission("chassis.assembly_assign"))):
    """WO v4.31 §0.4 — assign a booked-in chassis to an assembly bay (parking -> assembly)."""
    return svc.assign_assembly_bay(db, record_id, payload.assembly_bay_id, who=user.username,
                                   event_date=payload.event_date, notes=payload.notes)


@router.post("/{record_id}/body-attached", response_model=ChassisEventOut, status_code=201)
def body_attached(record_id: int, payload: BodyAttachedRequest, db: Session = Depends(get_db),
                  user: User = Depends(require_permission("chassis.assembly_assign"))):
    """WO v4.35 §0.5 — record the body_attached phase event (the bay-side "Mark body attached").
    Gated on `chassis.assembly_assign` (planner/admin/production; workshop + sales → 403). The §0.4
    pre-conditions (on a bay + job in_production) and the §0.22 swap rule (DEV-1 planner-attested-VIN
    signal) are enforced in services.chassis.record_body_attached — the single chokepoint."""
    return svc.record_body_attached(db, record_id, payload.production_job_id, who=user.username,
                                    notes=payload.notes)


@router.post("/{record_id}/move-to-awaiting-qa", response_model=ChassisEventOut, status_code=201)
def move_to_awaiting_qa(record_id: int, payload: MoveToAwaitingQaRequest, db: Session = Depends(get_db),
                        user: User = Depends(require_permission("chassis.assembly_assign"))):
    """WO v4.36a.1 §0.5 — move a body-attached chassis off its bay into the Awaiting-QA queue. Gated on
    `chassis.assembly_assign` (planner/admin/production; workshop + sales → 403), matching body-attached.
    The pre-conditions (on a bay + body attached + not already moved) AND the atomic status promotion to
    'awaiting_qa' are enforced in services.chassis.record_moved_to_awaiting_qa — the single chokepoint."""
    return svc.record_moved_to_awaiting_qa(db, record_id, who=user.username, notes=payload.notes)


@router.post("/{record_id}/return-to-parking", status_code=200)
def return_to_parking(record_id: int, payload: ReturnToParkingRequest, db: Session = Depends(get_db),
                      user: User = Depends(require_permission("chassis.assembly_assign"))):
    """WO v4.36a.2 — move a chassis off its assembly bay back to the parking pool, to free the bay for a
    more urgent job. Gated `chassis.assembly_assign` (planner/admin/production; workshop + sales → 403),
    matching the other yard moves. Allowed ONLY before a merge — the 'no body_attached' precondition + the
    status flip + the optional audit are enforced in services.chassis.return_chassis_to_parking (the single
    chokepoint). The full user is passed so the re-prioritisation audit can record who."""
    return svc.return_chassis_to_parking(db, record_id, user, reason=payload.reason)


@router.post("/{record_id}/events/{event_id}/photos", response_model=List[ChassisPhotoOut],
             status_code=201)
def upload_photos(record_id: int, event_id: int, files: List[UploadFile] = File(...),
                  db: Session = Depends(get_db),
                  user: User = Depends(require_permission("chassis.update"))):
    return svc.add_photos(db, record_id, event_id, files, who=user.username)
