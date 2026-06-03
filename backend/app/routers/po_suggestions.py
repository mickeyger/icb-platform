"""`/api/po-suggestions/*` — Buying / PO Suggestion Queue (WO v4.15, ADR 0008).

raise/defer follow the §0.4 lock (single-id raise, pr_number=f"PR-{seq}", SAP mocked).
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..database import User, get_db
from ..deps import require_permission, require_user
from ..schemas.po_suggestions import (
    BulkRaiseRequest, BulkRaiseResponse, DeferRequest, OverrideSupplierRequest,
    POSuggestionListItem, SuggestionStatus, Urgency,
)
from ..services import po_suggestions as svc

router = APIRouter(prefix="/api/po-suggestions", tags=["po-suggestions"])


@router.get("", response_model=list[POSuggestionListItem])
def list_po_suggestions(
    status: Optional[SuggestionStatus] = Query(None, description="pending | raised | deferred"),
    urgency: Optional[Urgency] = Query(None, description="critical | order_now | advisory"),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    """List PO suggestions (by id), filterable by status / urgency."""
    return svc.list_suggestions(db, status=status, urgency=urgency)


@router.post("/{suggestion_id}/raise", response_model=POSuggestionListItem)
def raise_pr(suggestion_id: int, db: Session = Depends(get_db),
             user: User = Depends(require_permission("buying.raise_pr"))):
    """Raise a PR (mock SAP): assigns pr_number=PR-{seq}, status=raised. 422 if already raised."""
    try:
        return svc.raise_pr(db, suggestion_id=suggestion_id, user=user)
    except svc.NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except svc.InvalidStateError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.post("/{suggestion_id}/defer", response_model=POSuggestionListItem)
def defer_suggestion(
    suggestion_id: int, body: DeferRequest,
    db: Session = Depends(get_db), user: User = Depends(require_permission("buying.defer_pr")),
):
    """Defer a suggestion until a date (status=deferred). 422 if already raised."""
    try:
        return svc.defer_suggestion(db, suggestion_id=suggestion_id, deferred_until=body.deferred_until, user=user)
    except svc.NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except svc.InvalidStateError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.post("/{suggestion_id}/override-supplier", response_model=POSuggestionListItem)
def override_supplier(
    suggestion_id: int, body: OverrideSupplierRequest,
    db: Session = Depends(get_db), user: User = Depends(require_permission("buying.override_supplier")),
):
    """Override the suggested supplier (recomputes total). 422 if already raised."""
    try:
        return svc.override_supplier(db, suggestion_id=suggestion_id,
                                     supplier_name=body.supplier_name, last_price=body.last_price, user=user)
    except svc.NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except svc.InvalidStateError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.post("/raise", response_model=BulkRaiseResponse)
def bulk_raise(
    body: BulkRaiseRequest,
    db: Session = Depends(get_db), user: User = Depends(require_permission("buying.bulk_raise")),
):
    """Bulk-raise PRs: one PR-{seq} per supplier group. Already-raised ids are skipped."""
    return svc.bulk_raise(db, ids=body.ids, user=user)
