"""`/api/po-suggestions/*` — Buying / PO Suggestion Queue (WO v4.15, ADR 0008).

raise/defer follow the §0.4 lock (single-id raise, pr_number=f"PR-{seq}", SAP mocked).
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..database import User, get_db
from ..deps import require_user
from ..schemas.po_suggestions import (
    DeferRequest, POSuggestionListItem, SuggestionStatus, Urgency,
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
def raise_pr(suggestion_id: int, db: Session = Depends(get_db), user: User = Depends(require_user)):
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
    db: Session = Depends(get_db), user: User = Depends(require_user),
):
    """Defer a suggestion until a date (status=deferred). 422 if already raised."""
    try:
        return svc.defer_suggestion(db, suggestion_id=suggestion_id, deferred_until=body.deferred_until, user=user)
    except svc.NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except svc.InvalidStateError as e:
        raise HTTPException(status_code=422, detail=str(e))
