"""`/api/production-jobs/*` — the MES production-job lifecycle API (WO v4.14).

A NEW, parallel surface (ADR 0008). The existing Jinja-side `/api/calculations/*`
MES handlers are untouched and retire in Phase 4. Thin handlers: each delegates
to `app.services.production_jobs` and maps the typed service errors to HTTP.
All endpoints require an authenticated session (`require_user` -> 401 for /api).
"""
from datetime import date, datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi import status as http_status
from sqlalchemy.orm import Session

from ..database import Branch, User, get_db
from ..deps import active_branch, require_permission, require_user, user_can
from ..models.mes import AssemblyBay
from ..schemas.production_jobs import (
    PlanningAckRequest, PreJobSignoffRequest, ProductionJobDetail,
    ProductionJobInProgressItem, ProductionJobListItem, TimelineEvent,
    bom_to_out, to_detail, to_list_item,
)
from ..schemas.planning import RevertRequest
from ..services import chassis as chassis_svc
from ..services import planning as planning_svc
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
    branch: Optional[Branch] = Depends(active_branch),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    """List production jobs (compact), filterable by status / branch / accepted date.
    branch_id defaults to the session's active branch when omitted (WO v4.16)."""
    statuses = [s.strip() for s in status.split(",") if s.strip()] if status else None
    eff_branch = branch_id if branch_id is not None else (branch.id if branch is not None else None)
    rows = svc.list_jobs(db, status=statuses, branch_id=eff_branch,
                         accepted_since=accepted_since, limit=limit, offset=offset)
    retired = svc.sap_retired(db)                        # WO v4.34 §0.9 — site flag, computed once
    items = [to_list_item(job, calc, customer, bc) for (job, calc, customer, bc) in rows]
    for it in items:
        it.sap_retired = retired
    return items


@router.post("/{job_id}/revert-to-unscheduled")
def revert_to_unscheduled(job_id: int, body: RevertRequest, db: Session = Depends(get_db),
                          user: User = Depends(require_permission("planning.unschedule"))):
    """WO v4.34.2 — move a SCHEDULED job back to the Unscheduled pool (planner/admin; workshop/sales
    lack `planning.unschedule` → 403). The explicit, reason-capturing path; delegates to the SAME guarded
    planning.unschedule chokepoint as the drag-to-pool DELETE, so the §0.3 safety rules + audit apply to
    both. Chassis assignment + sign-offs are preserved (slot-only delete)."""
    try:
        return planning_svc.revert_to_unscheduled(
            db, production_job_id=job_id, user=user, reason=body.reason)
    except planning_svc.NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except planning_svc.RevertNotAllowedError as e:
        raise HTTPException(status_code=409, detail=str(e))


# WO v4.32 §0.4 — the two dashboard aggregations. Both are literal paths and MUST be declared
# BEFORE the /{job_id} catch-all below (FastAPI matches in declaration order; after it they
# would 422 as failed int-parses of "in-progress"/"kpis").
@router.get("/in-progress", response_model=list[ProductionJobInProgressItem])
def list_in_progress_jobs(
    branch_id: Optional[int] = Query(None, description="Override the session's active branch"),
    branch: Optional[Branch] = Depends(active_branch),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    """In-flight jobs (status planning / in_production — §0.6) + chassis/bay context for the
    Production Dashboard (WO v4.32). Read-only."""
    eff_branch = branch_id if branch_id is not None else (branch.id if branch is not None else None)
    out = []
    for (row, vin, ch_status, bay_code, days) in svc.list_in_progress(db, branch_id=eff_branch):
        job, calc, customer, bc = row
        item = ProductionJobInProgressItem(**to_list_item(job, calc, customer, bc).model_dump())
        item.chassis_vin = vin
        item.chassis_status = ch_status
        item.current_assembly_bay_code = bay_code
        item.days_in_stage = days
        out.append(item)
    return out


@router.get("/kpis")
def production_kpis(
    branch_id: Optional[int] = Query(None, description="Override the session's active branch"),
    branch: Optional[Branch] = Depends(active_branch),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    """WO v4.32 §0.4/§0.6 — the Production Dashboard metric values. ONE computation
    (compute_production_kpis — §0.5 parity-by-construction; Management Dashboard v4.33+ becomes
    the second caller). Plain dict + as_of, mirroring /api/dashboard/kpis (v4.31). Read-only;
    refreshed by the dashboard's 30s tick (§0.3)."""
    eff_branch = branch_id if branch_id is not None else (branch.id if branch is not None else None)
    now = datetime.now(timezone.utc)
    return {**svc.compute_production_kpis(db, branch_id=eff_branch, now=now),
            "as_of": now.isoformat()}


@router.get("/{job_id}", response_model=ProductionJobDetail)
def get_production_job(job_id: int, db: Session = Depends(get_db), user: User = Depends(require_user)):
    """Full detail for one job + WO v4.31 §3.2 read-only enrichment: current BOM lines, chassis
    (latest VCL photos/checklist/notes), and bay context. All additive + read-only (no write paths)."""
    try:
        job, calc, customer, branch_code = svc.get_with_costing(db, job_id)
    except svc.NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    detail = to_detail(job, calc, customer, branch_code)
    # §3.2 enrichment — current generated_bom + chassis-with-latest-VCL + bay context.
    bom = svc.load_current_bom(db, job)
    if bom is not None:
        detail.current_bom = bom_to_out(*bom)
    if job.chassis_record_id:
        try:
            chassis = chassis_svc.get_detail(db, job.chassis_record_id)
        except HTTPException:
            chassis = None                  # dangling FK -> frontend renders the "Chassis pending" placeholder
        if chassis is not None:
            detail.chassis = chassis
            if chassis.current_assembly_bay_id:
                bay = db.get(AssemblyBay, chassis.current_assembly_bay_id)
                detail.current_assembly_bay_code = bay.code if bay else None
                aa = [e for e in chassis.events if e.event_type == "assembly_assigned"]
                if aa:
                    detail.assembly_assigned_at = max(aa, key=lambda e: e.id).created_at
    return detail


@router.post("/from-calculation/{calculation_id}", response_model=ProductionJobDetail)
def accept_from_calculation(
    calculation_id: int, response: Response,
    branch: Optional[Branch] = Depends(active_branch),
    db: Session = Depends(get_db), user: User = Depends(require_permission("production.accept")),
):
    """Accept an already-accepted calculation into production. Idempotent:
    201 if a new job is created, 200 if one already exists for that calculation.
    The session's active branch covers calcs with no branch_id (WO v4.29 D1)."""
    try:
        row, created = svc.accept_calculation(
            db, calculation_id, user,
            fallback_branch_id=(branch.id if branch is not None else None),
        )
    except svc.NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except (svc.CalculationNotAcceptedError, svc.BranchUnavailableError) as e:
        raise HTTPException(status_code=422, detail=str(e))
    response.status_code = http_status.HTTP_201_CREATED if created else http_status.HTTP_200_OK
    return _detail(row)


@router.post("/{job_id}/pre-job-card", response_model=ProductionJobDetail)
def send_pre_job_card(job_id: int, db: Session = Depends(get_db),
                      user: User = Depends(require_permission("production.pre_job_card"))):
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
    """Record a sales or production sign-off (per-role gated). When both are
    present, the job auto-progresses to pre_job_confirmed."""
    perm = "production.signoff_sales" if body.role == "sales" else "production.signoff_production"
    if not user_can(user, perm, db):
        raise HTTPException(status_code=403, detail=f"Permission denied: {perm}")
    try:
        return _detail(svc.record_signoff(db, job_id, body.role, body.attestation, user))
    except svc.NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/{job_id}/planning-ack", response_model=ProductionJobDetail)
def planning_ack(
    job_id: int, body: PlanningAckRequest,
    db: Session = Depends(get_db), user: User = Depends(require_permission("planning.acknowledge")),
):
    """Planning acknowledges the job (status -> planning). Requires pre_job_confirmed.
    Captures the chassis ETA + rich chassis data in one step (WO v4.29 D2)."""
    chassis_data = {
        "chassis_vin": body.chassis_vin, "chassis_model": body.chassis_model,
        "customer_dealer": body.customer_dealer, "tail_lift_code": body.tail_lift_code,
        "chassis_inhouse_bom": body.chassis_inhouse_bom,
        "dealer_id": body.dealer_id,              # WO v4.34.1 §0.3 — structured chassis supplier
    }
    try:
        return _detail(svc.record_planning_ack(
            db, job_id, body.chassis_eta, body.notes, user, chassis_data=chassis_data,
            job_number=body.job_number))
    except svc.NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except svc.WrongStatusForTransitionError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.post("/{job_id}/chassis-received", response_model=ProductionJobDetail)
def chassis_received(job_id: int, db: Session = Depends(get_db),
                     user: User = Depends(require_permission("production.chassis_received"))):
    """Confirm the chassis has physically arrived."""
    try:
        return _detail(svc.mark_chassis_received(db, job_id, user))
    except svc.NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/{job_id}/chassis-received", response_model=ProductionJobDetail)
def chassis_received_untick(job_id: int, db: Session = Depends(get_db),
                            user: User = Depends(require_permission("production.chassis_received"))):
    """WO v4.28 (Flag E) — reverse a chassis-received tick (re-enables the chassis-ETA gate)."""
    try:
        return _detail(svc.unmark_chassis_received(db, job_id, user))
    except svc.NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/{job_id}/timeline", response_model=list[TimelineEvent])
def production_job_timeline(job_id: int, db: Session = Depends(get_db), user: User = Depends(require_user)):
    """Derived lifecycle timeline (from the job's timestamp columns), oldest-first."""
    try:
        return svc.build_timeline(db, job_id)
    except svc.NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
