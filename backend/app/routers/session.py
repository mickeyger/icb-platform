"""`/api/session` — current user + active branch, and branch switching (WO v4.16).

No permission gate (§4.2): any authenticated user may switch among accessible
branches. Since the costing `users` table has no branch mapping, all branches are
accessible and the switch only validates that the branch exists (404 otherwise).
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import User, get_db
from ..deps import current_session_id, require_user
from ..schemas.session import BranchSwitchRequest, SessionInfo
from ..services import session as svc

router = APIRouter(prefix="/api/session", tags=["session"])


@router.get("", response_model=SessionInfo)
def get_session(
    session_id: Optional[str] = Depends(current_session_id),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    """Current user + active branch (JHB default) + accessible branches."""
    return svc.build_session_info(db, user, session_id)


@router.post("/branch", response_model=SessionInfo)
def switch_branch(
    body: BranchSwitchRequest,
    session_id: Optional[str] = Depends(current_session_id),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    """Switch the session's active branch (404 if the branch does not exist)."""
    try:
        svc.set_active_branch(db, session_id, body.branch_id, user)
    except svc.NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return svc.build_session_info(db, user, session_id)
