"""Demand-line service (WO v4.15, ADR 0008) — Weekly Material Forecast read-model.

`rollup_demand` powers ?group_by=week|sap: group_by=week -> one row per
(sap_code, week_bucket); group_by=sap -> one row per sap_code. job_count is the
distinct count of job_ref in the group; total_qty the summed qty.
"""
from typing import List, Optional

from sqlalchemy import distinct, func, select
from sqlalchemy.orm import Session

from app.models.mes import DemandLine
from app.schemas.demand_lines import DemandLineItem, DemandRollup


def list_demand(db: Session, *, sap_code: Optional[str] = None,
                week_bucket: Optional[str] = None) -> List[DemandLineItem]:
    stmt = select(DemandLine)
    if sap_code:
        stmt = stmt.where(DemandLine.sap_code == sap_code)
    if week_bucket:
        stmt = stmt.where(DemandLine.week_bucket == week_bucket)
    stmt = stmt.order_by(DemandLine.week_bucket, DemandLine.sap_code, DemandLine.id)
    return [DemandLineItem.model_validate(d) for d in db.execute(stmt).scalars().all()]


def rollup_demand(db: Session, *, group_by: str = "week", sap_code: Optional[str] = None,
                  week_bucket: Optional[str] = None) -> List[DemandRollup]:
    by_week = group_by != "sap"
    qty = func.coalesce(func.sum(DemandLine.qty), 0.0)
    jobs = func.count(distinct(DemandLine.job_ref))
    if by_week:
        grp = [DemandLine.sap_code, DemandLine.week_bucket]
        cols = [DemandLine.sap_code, DemandLine.week_bucket, qty, jobs]
    else:
        grp = [DemandLine.sap_code]
        cols = [DemandLine.sap_code, qty, jobs]
    stmt = select(*cols)
    if sap_code:
        stmt = stmt.where(DemandLine.sap_code == sap_code)
    if week_bucket:
        stmt = stmt.where(DemandLine.week_bucket == week_bucket)
    stmt = stmt.group_by(*grp).order_by(*grp)
    out: List[DemandRollup] = []
    for r in db.execute(stmt).all():
        if by_week:
            out.append(DemandRollup(sap_code=r[0], week_bucket=r[1],
                                    total_qty=float(r[2] or 0), job_count=int(r[3] or 0)))
        else:
            out.append(DemandRollup(sap_code=r[0], week_bucket=None,
                                    total_qty=float(r[1] or 0), job_count=int(r[2] or 0)))
    return out
