"""Active-branch session service (WO v4.16, ADR 0010).

Active branch is session-held in `icb_mes.session_branches` keyed by the costing
UserSession.id. There is no per-user branch mapping (the costing `users` table has
no branch column), so `accessible_branches` = all active branches and the display
default is JHB. List endpoints filter only once a branch is explicitly switched
(`get_switched_branch` → None means "no filter / all accessible").
"""
from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import Branch
from app.models.mes import SessionBranch
from app.schemas.session import BranchInfo, SessionInfo, UserInfo
from app.services.errors import NotFoundError

_DEFAULT_BRANCH_CODE = "JHB"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def accessible_branches(db: Session) -> List[Branch]:
    return db.execute(
        select(Branch).where(Branch.is_active.is_(True)).order_by(Branch.code)
    ).scalars().all()


def _default_branch(db: Session) -> Optional[Branch]:
    return db.execute(
        select(Branch).where(Branch.code == _DEFAULT_BRANCH_CODE)
    ).scalar_one_or_none()


def get_switched_branch(db: Session, session_id: Optional[str]) -> Optional[Branch]:
    """The branch this session explicitly switched to, or None (lists show all)."""
    if not session_id:
        return None
    sb = db.get(SessionBranch, session_id)
    return db.get(Branch, sb.branch_id) if sb is not None else None


def get_active_or_default(db: Session, session_id: Optional[str]) -> Optional[Branch]:
    """The switched branch, else the JHB display default (may be None if unseeded)."""
    return get_switched_branch(db, session_id) or _default_branch(db)


def set_active_branch(db: Session, session_id: Optional[str], branch_id: int, user) -> Branch:
    branch = db.get(Branch, branch_id)
    if branch is None:
        raise NotFoundError(f"branch {branch_id} not found")
    if session_id:  # persist only when there's a real session (cookie)
        sb = db.get(SessionBranch, session_id)
        if sb is None:
            db.add(SessionBranch(session_id=session_id, branch_id=branch_id, updated_at=_now()))
        else:
            sb.branch_id = branch_id
            sb.updated_at = _now()
        db.commit()
    return branch


def build_session_info(db: Session, user, session_id: Optional[str]) -> SessionInfo:
    active = get_active_or_default(db, session_id)
    return SessionInfo(
        user=UserInfo.model_validate(user),
        active_branch=(BranchInfo.model_validate(active) if active is not None else None),
        accessible_branches=[BranchInfo.model_validate(b) for b in accessible_branches(db)],
    )
