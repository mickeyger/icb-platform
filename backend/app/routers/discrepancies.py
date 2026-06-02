"""`/api/discrepancies/*` — the buyer's discrepancy queue (WO v4.15, ADR 0008)."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..database import User, get_db
from ..deps import require_user
from ..schemas.discrepancies import DiscrepancyListItem, ResolveRequest
from ..services import discrepancies as svc

router = APIRouter(prefix="/api/discrepancies", tags=["discrepancies"])


@router.get("", response_model=list[DiscrepancyListItem])
def list_discrepancies(
    resolved: Optional[bool] = Query(None, description="Filter by resolved true/false"),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    """List discrepancies (newest first), optionally filtered by resolved state."""
    return svc.list_discrepancies(db, resolved=resolved)


@router.post("/{discrepancy_id}/resolve", response_model=DiscrepancyListItem)
def resolve_discrepancy(
    discrepancy_id: int, body: ResolveRequest,
    db: Session = Depends(get_db), user: User = Depends(require_user),
):
    """Resolve a discrepancy (sets resolved_at). 422 if already resolved."""
    try:
        return svc.resolve_discrepancy(
            db, discrepancy_id=discrepancy_id, resolution_notes=body.resolution_notes, user=user,
        )
    except svc.NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except svc.InvalidStateError as e:
        raise HTTPException(status_code=422, detail=str(e))
