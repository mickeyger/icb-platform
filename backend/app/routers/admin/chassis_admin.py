"""WO v4.36a §3.6 — admin Merge Chassis + Find Orphan Chassis (all require_admin).

Built least-destructive-first. STEP 2 ships the READ-ONLY Find-Orphan list; retrofit-link /
soft-delete / merge-preview / merge / restore land in later steps on this same router. Domain failures
raise ChassisIntegrityError (mapped to 409/422 by the global handler in main.py)."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ...database import User, get_db
from ...deps import require_admin
from ...services import integrity

router = APIRouter(prefix="/api/admin/chassis", tags=["admin-chassis"])


@router.get("/orphans")
def list_orphans(db: Session = Depends(get_db), user: User = Depends(require_admin)):
    """§3.6 — the authoritative WIDE Find-Orphan list: LIVE chassis (deleted_at IS NULL) with NO
    production_job and NO prejob_card FK, ANY status (catches MICKEYTEST-class 'received' orphans the
    narrow Inv3 health-check scope misses). A merged loser (deleted_at set) is excluded. Read-only."""
    return integrity.find_anchorless_chassis(db, statuses=None)
