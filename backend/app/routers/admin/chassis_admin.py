"""WO v4.36a §3.6 — admin Merge Chassis + Find Orphan Chassis (all require_admin).

Built least-destructive-first. STEP 2 ships the READ-ONLY Find-Orphan list; retrofit-link /
soft-delete / merge-preview / merge / restore land in later steps on this same router. Domain failures
raise ChassisIntegrityError (mapped to 409/422 by the global handler in main.py)."""
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ...database import User, get_db
from ...deps import require_admin
from ...schemas.chassis import ChassisRecordDetail
from ...services import chassis as chassis_svc
from ...services import integrity

router = APIRouter(prefix="/api/admin/chassis", tags=["admin-chassis"])


@router.get("/orphans")
def list_orphans(db: Session = Depends(get_db), user: User = Depends(require_admin)):
    """§3.6 — the authoritative WIDE Find-Orphan list: LIVE chassis (deleted_at IS NULL) with NO
    production_job and NO prejob_card FK, ANY status (catches MICKEYTEST-class 'received' orphans the
    narrow Inv3 health-check scope misses). A merged loser (deleted_at set) is excluded. Read-only."""
    return integrity.find_anchorless_chassis(db, statuses=None)


class RetrofitLinkBody(BaseModel):
    production_job_id: int


@router.post("/{chassis_id}/retrofit-link", response_model=ChassisRecordDetail)
def retrofit_link(chassis_id: int, body: RetrofitLinkBody,
                  db: Session = Depends(get_db), user: User = Depends(require_admin)):
    """§3.6 STEP 3 — admin recovery: link an orphan chassis to an unlinked job (atomic FK + job_number
    via the §3.5c chokepoint). ChassisIntegrityError → 409/422 via the global handler."""
    chassis_svc.retrofit_link(db, chassis_id, body.production_job_id, who=user.username)
    return chassis_svc.get_detail(db, chassis_id)


@router.delete("/{chassis_id}", response_model=ChassisRecordDetail)
def soft_delete(chassis_id: int, reason: str | None = None,
                db: Session = Depends(get_db), user: User = Depends(require_admin)):
    """§3.6 STEP 4 — soft-delete a JUNK orphan (deliberate, reversible; no merged_into_id). Refuses if a
    live job / card / lifecycle-event still references it (409). The optional reason is appended to notes."""
    chassis_svc.soft_delete_chassis(db, chassis_id, who=user.username, reason=reason)
    return chassis_svc.get_detail(db, chassis_id)
