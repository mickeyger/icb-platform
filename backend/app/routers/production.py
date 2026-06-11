"""WO v4.32 §0.4 — `/api/production/*` generic production aggregations.

One endpoint for now: the per-team daily worksheet (the §3.3 load-bearing contract — see
`services/team_worksheet.py` + ADR 0019). Read-only, require-user, branch-filtered "where
attributable" (§0.7). Thin handler: validation (team allow-list, ±7-day date clamp) lives in
the service so future consumers inherit it.
"""
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..database import Branch, User, get_db
from ..deps import active_branch, require_user
from ..schemas.team_worksheet import TeamWorksheet
from ..services import team_worksheet as svc

router = APIRouter(prefix="/api/production", tags=["production"])


@router.get("/team-worksheet", response_model=TeamWorksheet)
def team_worksheet(
    team: str = Query(..., description="vacuum | press | assembly | parking | dispatch"),
    date_param: Optional[date] = Query(None, alias="date",
                                       description="Defaults to today; ±7 days allowed (§3.3)"),
    branch_id: Optional[int] = Query(None, description="Override the session's active branch"),
    branch: Optional[Branch] = Depends(active_branch),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    """The selected team's daily worksheet: scheduled / in-flight / blocking (WO v4.32 §3.3)."""
    eff_branch = branch_id if branch_id is not None else (branch.id if branch is not None else None)
    return svc.build_team_worksheet(db, team, for_date=date_param, branch_id=eff_branch)
