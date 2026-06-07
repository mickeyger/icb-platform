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
    ChassisEventCapture, ChassisEventOut, ChassisPhotoOut, ChassisRecordCreate,
    ChassisRecordDetail, ChassisRecordOut, ChassisRecordUpdate,
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


@router.get("/photos/{photo_id}")
def serve_photo(photo_id: int, db: Session = Depends(get_db), user: User = Depends(require_user)):
    photo, path = svc.get_photo_file(db, photo_id)
    return FileResponse(path, media_type=photo.content_type or "application/octet-stream",
                        filename=photo.original_filename or f"photo-{photo_id}")


@router.get("/{record_id}", response_model=ChassisRecordDetail)
def get_record(record_id: int, db: Session = Depends(get_db), user: User = Depends(require_user)):
    return svc.get_detail(db, record_id)


@router.post("", response_model=ChassisRecordDetail, status_code=201)
def create_record(payload: ChassisRecordCreate, db: Session = Depends(get_db),
                  user: User = Depends(require_permission("chassis.create"))):
    rec = svc.create_chassis(db, payload, who=user.username)
    return svc.get_detail(db, rec.id)


@router.patch("/{record_id}", response_model=ChassisRecordDetail)
def update_record(record_id: int, payload: ChassisRecordUpdate, db: Session = Depends(get_db),
                  user: User = Depends(require_permission("chassis.update"))):
    svc.update_chassis(db, record_id, payload, who=user.username)
    return svc.get_detail(db, record_id)


@router.post("/{record_id}/vcl", response_model=ChassisEventOut, status_code=201)
def capture_vcl(record_id: int, payload: ChassisEventCapture, db: Session = Depends(get_db),
                user: User = Depends(require_permission("chassis.vcl"))):
    return svc.capture_event(db, record_id, "VCL", payload, who=user.username)


@router.post("/{record_id}/dcl", response_model=ChassisEventOut, status_code=201)
def capture_dcl(record_id: int, payload: ChassisEventCapture, db: Session = Depends(get_db),
                user: User = Depends(require_permission("chassis.dcl"))):
    return svc.capture_event(db, record_id, "DCL", payload, who=user.username)


@router.post("/{record_id}/events/{event_id}/photos", response_model=List[ChassisPhotoOut],
             status_code=201)
def upload_photos(record_id: int, event_id: int, files: List[UploadFile] = File(...),
                  db: Session = Depends(get_db),
                  user: User = Depends(require_permission("chassis.update"))):
    return svc.add_photos(db, record_id, event_id, files, who=user.username)
