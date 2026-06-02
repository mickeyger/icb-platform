"""`/api/stock-counts/*` — Stores Reconciliation (WO v4.15, ADR 0008)."""
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi import status as http_status
from sqlalchemy.orm import Session

from ..database import Branch, User, get_db
from ..deps import active_branch, require_permission, require_user
from ..schemas.discrepancies import DiscrepancyListItem
from ..schemas.stock_counts import (
    CountStatus, RaiseDiscrepancyRequest, RecordCountRequest, StockCountListItem,
)
from ..services import stock_counts as svc

router = APIRouter(prefix="/api/stock-counts", tags=["stock-counts"])


@router.get("", response_model=list[StockCountListItem])
def list_stock_counts(
    status: Optional[CountStatus] = Query(None, description="confirmed | discrepancy | pending"),
    branch_id: Optional[int] = Query(None, description="Filter to one branch"),
    counted_since: Optional[date] = Query(None, description="Only counts on/after this date"),
    branch: Optional[Branch] = Depends(active_branch),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    """List cycle counts (newest first), filterable by status / branch / date.
    branch_id defaults to the session's active branch when omitted (WO v4.16)."""
    eff_branch = branch_id if branch_id is not None else (branch.id if branch is not None else None)
    return svc.list_counts(db, status=status, branch_id=eff_branch, counted_since=counted_since)


@router.post("", response_model=StockCountListItem, status_code=http_status.HTTP_201_CREATED)
def record_count(body: RecordCountRequest, branch: Optional[Branch] = Depends(active_branch),
                 db: Session = Depends(get_db),
                 user: User = Depends(require_permission("stores.count"))):
    """Record a cycle count under the chosen / active branch (JHB default).
    Auto-classifies confirmed (physical == SAP) vs discrepancy."""
    eff_branch = body.branch_id if body.branch_id is not None else (branch.id if branch is not None else None)
    return svc.record_count(
        db, sap_code=body.sap_code, bin=body.bin, physical_count=body.physical_count,
        branch_id=eff_branch, user=user,
    )


@router.post("/{stock_count_id}/raise-discrepancy", response_model=DiscrepancyListItem,
             status_code=http_status.HTTP_201_CREATED)
def raise_discrepancy(
    stock_count_id: int, body: RaiseDiscrepancyRequest,
    db: Session = Depends(get_db), user: User = Depends(require_permission("stores.raise_discrepancy")),
):
    """Create a discrepancy from a discrepancy-status count. 422 if the count is not a discrepancy."""
    try:
        return svc.raise_discrepancy(
            db, stock_count_id=stock_count_id, raised_to_buyer_user_id=body.raised_to_buyer_user_id,
            raised_to_buyer_name=body.raised_to_buyer_name, notes=body.notes, user=user,
        )
    except svc.NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except svc.InvalidStateError as e:
        raise HTTPException(status_code=422, detail=str(e))
