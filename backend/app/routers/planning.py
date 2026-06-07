"""`/api/planning-board` + `/api/planning-slots/*` (WO v4.16, ADR 0008).

Reads (`require_user`) default to the session's active branch. Writes are gated:
schedule/move → `planning.schedule`, unschedule → `planning.unschedule`. The
chassis-ETA gate (422) + occupied-cell (409) are enforced in the service.
"""
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi import status as http_status
from sqlalchemy.orm import Session

from ..database import Branch, User, get_db
from ..deps import active_branch, require_permission, require_user
from ..schemas.planning import MoveRequest, PlanningBoard, PlanningSlotItem, ScheduleRequest
from ..services import planning as svc

# /api/planning-board (board view) and /api/planning-slots (CRUD) — two prefixes, one tag.
board_router = APIRouter(prefix="/api/planning-board", tags=["planning"])
router = APIRouter(prefix="/api/planning-slots", tags=["planning"])


def _effective_branch_id(branch_id: Optional[int], branch: Optional[Branch]) -> Optional[int]:
    return branch_id if branch_id is not None else (branch.id if branch is not None else None)


@board_router.get("", response_model=PlanningBoard)
def get_planning_board(
    weeks: int = Query(8, ge=1, le=52, description="How many contiguous weeks to return (from the first scheduled week)"),
    lane: Optional[str] = Query(None, description="Filter to one lane"),
    branch_id: Optional[int] = Query(None, description="Defaults to the session's active branch"),
    branch: Optional[Branch] = Depends(active_branch),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    """The board grid: weeks × slots with assigned jobs, the unscheduled pool, and capacity."""
    return svc.build_board(db, branch_id=_effective_branch_id(branch_id, branch),
                           weeks_count=weeks, lane=lane)


@router.get("", response_model=list[PlanningSlotItem])
def list_planning_slots(
    week: Optional[date] = Query(None),
    lane: Optional[str] = Query(None),
    status: Optional[str] = Query(None, description="scheduled | unscheduled | ..."),
    branch_id: Optional[int] = Query(None, description="Defaults to the session's active branch"),
    branch: Optional[Branch] = Depends(active_branch),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    """List planning slots, filterable by week / lane / status / branch."""
    return svc.list_slots(db, week=week, lane=lane, status=status,
                          branch_id=_effective_branch_id(branch_id, branch))


@router.post("", response_model=PlanningSlotItem, status_code=http_status.HTTP_201_CREATED)
def schedule_slot(body: ScheduleRequest, db: Session = Depends(get_db),
                  user: User = Depends(require_permission("planning.schedule"))):
    """Schedule a job into a slot. 422 chassis-ETA gate; 409 if the cell/job is occupied."""
    try:
        return svc.schedule(db, production_job_id=body.production_job_id, week=body.week,
                            bay=body.bay, lane=body.lane, slot_position=body.slot_position, user=user)
    except svc.NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except svc.ChassisEtaError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except svc.CellOccupiedError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.post("/{slot_id}/move", response_model=PlanningSlotItem)
def move_slot(slot_id: int, body: MoveRequest, db: Session = Depends(get_db),
              user: User = Depends(require_permission("planning.schedule"))):
    """Reschedule a slot to another week/cell. Same chassis-ETA gate + occupied check."""
    try:
        return svc.move(db, slot_id=slot_id, week=body.week, bay=body.bay,
                        lane=body.lane, slot_position=body.slot_position, user=user)
    except svc.NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except svc.ChassisEtaError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except svc.CellOccupiedError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.delete("/{slot_id}")
def unschedule_slot(slot_id: int, db: Session = Depends(get_db),
                    user: User = Depends(require_permission("planning.unschedule"))):
    """Unschedule (delete the slot row); the job returns to the unscheduled pool."""
    try:
        return svc.unschedule(db, slot_id=slot_id, user=user)
    except svc.NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
