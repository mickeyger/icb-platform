"""`/api/production-jobs/*` — the MES production-job lifecycle API (WO v4.14).

A NEW, parallel surface (ADR 0008). The existing Jinja-side `/api/calculations/*`
MES handlers are untouched and retire in Phase 4. Thin handlers: each delegates
to `app.services.production_jobs` and maps the typed service errors to HTTP.
All endpoints require an authenticated session (`require_user` -> 401 for /api).
"""
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi import status as http_status
from sqlalchemy.orm import Session

from ..database import User, get_db
from ..deps import require_user
from ..schemas.production_jobs import (
    PlanningAckRequest, PreJobSignoffRequest, ProductionJobDetail,
    ProductionJobListItem, TimelineEvent, to_detail, to_list_item,
)
from ..services import production_jobs as svc

router = APIRouter(prefix="/api/production-jobs", tags=["production-jobs"])


def _detail(row) -> ProductionJobDetail:
    job, calc, customer, branch_code = row
    return to_detail(job, calc, customer, branch_code)


@router.get("", response_model=list[ProductionJobListItem])
def list_production_jobs(
    status: Optional[str] = Query(None, description="Single or comma-separated production_jobs status values"),
    branch_id: Optional[int] = Query(None, description="Filter to one branch (optional in Phase 2B; see v4.16)"),
    accepted_since: Optional[date] = Query(None, description="Only jobs accepted on/after this date"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    """List production jobs (compact), filterable by status / branch / accepted date."""
    statuses = [s.strip() for s in status.split(",") if s.strip()] if status else None
    rows = svc.list_jobs(db, status=statuses, branch_id=branch_id,
                         accepted_since=accepted_since, limit=limit, offset=offset)
    return [to_list_item(job, calc, customer, bc) for (job, calc, customer, bc) in rows]


@router.get("/{job_id}", response_model=ProductionJobDetail)
def get_production_job(job_id: int, db: Session = Depends(get_db), user: User = Depends(require_user)):
    """Full detail for one job, including joined costing data (customer, body, money)."""
    try:
        return _detail(svc.get_with_costing(db, job_id))
    except svc.NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/from-calculation/{calculation_id}", response_model=ProductionJobDetail)
def accept_from_calculation(
    calculation_id: int, response: Response,
    db: Session = Depends(get_db), user: User = Depends(require_user),
):
    """Accept an already-accepted calculation into production. Idempotent:
    201 if a new job is created, 200 if one already exists for that calculation."""
    try:
        row, created = svc.accept_calculation(db, calculation_id, user)
    except svc.NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except svc.CalculationNotAcceptedError as e:
        raise HTTPException(status_code=422, detail=str(e))
    response.status_code = http_status.HTTP_201_CREATED if created else http_status.HTTP_200_OK
    return _detail(row)


@router.post("/{job_id}/pre-job-card", response_model=ProductionJobDetail)
def send_pre_job_card(job_id: int, db: Session = Depends(get_db), user: User = Depends(require_user)):
    """Send the pre-job card (status -> pre_job_sent). 422 for repair quotes."""
    try:
        return _detail(svc.send_pre_job_card(db, job_id, user))
    except svc.NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except svc.RepairQuoteCannotSendPreJobError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.post("/{job_id}/pre-job-signoff", response_model=ProductionJobDetail)
def pre_job_signoff(
    job_id: int, body: PreJobSignoffRequest,
    db: Session = Depends(get_db), user: User = Depends(require_user),
):
    """Record a sales or production sign-off. When both are present, the job
    auto-progresses to pre_job_confirmed."""
    try:
        return _detail(svc.record_signoff(db, job_id, body.role, body.attestation, user))
    except svc.NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/{job_id}/planning-ack", response_model=ProductionJobDetail)
def planning_ack(
    job_id: int, body: PlanningAckRequest,
    db: Session = Depends(get_db), user: User = Depends(require_user),
):
    """Planning acknowledges the job (status -> planning). Requires pre_job_confirmed."""
    try:
        return _detail(svc.record_planning_ack(db, job_id, body.chassis_eta, body.notes, user))
    except svc.NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except svc.WrongStatusForTransitionError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.post("/{job_id}/chassis-received", response_model=ProductionJobDetail)
def chassis_received(job_id: int, db: Session = Depends(get_db), user: User = Depends(require_user)):
    """Confirm the chassis has physically arrived."""
    try:
        return _detail(svc.mark_chassis_received(db, job_id, user))
    except svc.NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/{job_id}/timeline", response_model=list[TimelineEvent])
def production_job_timeline(job_id: int, db: Session = Depends(get_db), user: User = Depends(require_user)):
    """Derived lifecycle timeline (from the job's timestamp columns), oldest-first."""
    try:
        return svc.build_timeline(db, job_id)
    except svc.NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
