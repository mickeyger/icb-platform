"""WO v4.36c — Kenny's QC inspection + dispatch endpoints.

Auth (§3.0 §2c — writes gate on DB permission keys, the codebase-native pattern; §0.4's "module
constant" premise was corrected): reads + per-category verdicts gate on require_permission("qc.inspect")
(granted to qc_inspector/planner/production in migration 0028); the sign-off — the only status-flipping
write — gates on require_permission("qc.signoff") (qc_inspector). admin is a code-level wildcard. The
dispatch-zone read is shared planning data, so it gates on require_user only."""
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import User, get_db
from ..deps import require_permission, require_user
from ..services import qc as _qc

router = APIRouter(prefix="/api/qc", tags=["qc"])

_INSPECT = require_permission("qc.inspect")
_SIGNOFF = require_permission("qc.signoff")


class CategoryVerdictIn(BaseModel):
    verdict: str                 # 'pass' | 'fail' (validated in the service)
    notes: Optional[str] = None


class SignoffIn(BaseModel):
    notes: Optional[str] = None


@router.get("/awaiting")
def qc_awaiting(db: Session = Depends(get_db), user: User = Depends(_INSPECT)):
    """Kenny's QC inbox — live chassis awaiting QA, with awaiting-since + failed_count."""
    return _qc.list_awaiting(db)


@router.get("/dispatched")
def qc_dispatched(db: Session = Depends(get_db), user: User = Depends(require_user)):
    """Dispatch-zone feed (§3.5) — live chassis in 'dispatched'."""
    return _qc.list_dispatched(db)


@router.get("/inspection/{chassis_id}")
def qc_inspection(chassis_id: int, db: Session = Depends(get_db), user: User = Depends(_INSPECT)):
    """Current inspection state: chassis header + active categories (with any open-cycle verdicts) +
    prior-cycle signoffs."""
    return _qc.get_inspection(db, chassis_id)


@router.post("/inspection/{chassis_id}/category/{category_id}")
def qc_record_category(chassis_id: int, category_id: int, payload: CategoryVerdictIn,
                       db: Session = Depends(get_db), user: User = Depends(_INSPECT)):
    """Record/overwrite one category's verdict for the open QC cycle (idempotent within the cycle)."""
    return _qc.record_category_verdict(db, chassis_id, category_id,
                                       verdict=payload.verdict, notes=payload.notes, user=user)


@router.post("/signoff/{chassis_id}")
def qc_signoff(chassis_id: int, payload: Optional[SignoffIn] = None,
               db: Session = Depends(get_db), user: User = Depends(_SIGNOFF)):
    """Finalize the open QC cycle (locked, completeness-checked). PASS -> dispatched; FAIL -> stays
    awaiting_qa with an immutable fail signoff. Returns the new status + whether a collection PDF is
    available (pass)."""
    return _qc.signoff(db, chassis_id, notes=(payload.notes if payload else None), user=user)


@router.get("/collection-note/{chassis_id}")
def qc_collection_note(chassis_id: int, db: Session = Depends(get_db), user: User = Depends(require_user)):
    """The customer collection note PDF for a QC-passed chassis (regenerated on demand from the
    immutable signoff; §0.8 customer-facing — no defect detail). Any authenticated user may fetch it."""
    from fastapi.responses import Response as RawResponse
    data = _qc.collection_note_pdf(db, chassis_id)
    return RawResponse(content=data, media_type="application/pdf",
                       headers={"Content-Disposition": f'inline; filename="collection-note-{chassis_id}.pdf"'})
