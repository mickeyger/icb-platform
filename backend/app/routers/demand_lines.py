"""`/api/demand-lines` — Weekly Material Forecast read-model (WO v4.15, ADR 0008).

One endpoint, two shapes: raw demand lines, or — with ?group_by=week|sap — an
aggregated rollup ({sap_code, week_bucket?, total_qty, job_count}).
"""
from typing import List, Optional, Union

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..database import User, get_db
from ..deps import require_user
from ..schemas.demand_lines import DemandLineItem, DemandRollup
from ..services import demand_lines as svc

router = APIRouter(prefix="/api/demand-lines", tags=["demand-lines"])


@router.get("", response_model=List[Union[DemandRollup, DemandLineItem]])
def list_demand_lines(
    sap_code: Optional[str] = Query(None, description="Filter by SAP code"),
    week_bucket: Optional[str] = Query(None, description="Filter by ISO week bucket e.g. 2026-W23"),
    group_by: Optional[str] = Query(None, pattern="^(week|sap)$",
                                    description="Rollup mode: 'week' (per sap×week) or 'sap' (per sap)"),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    """Raw demand lines, or an aggregated rollup when group_by is set."""
    if group_by:
        return svc.rollup_demand(db, group_by=group_by, sap_code=sap_code, week_bucket=week_bucket)
    return svc.list_demand(db, sap_code=sap_code, week_bucket=week_bucket)
