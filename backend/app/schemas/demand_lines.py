"""Demand-line schemas (WO v4.15, ADR 0008).

Read-model for the Weekly Material Forecast. `DemandRollup` backs the
`?group_by=week|sap` aggregation. Per §0.3 demand lines stay a read-model
(job_ref string only; no production_job linkage yet).
"""
from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class DemandLineItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    sap_code: Optional[str] = None
    qty: Optional[float] = None
    need_by: Optional[date] = None
    production_job_id: Optional[int] = None
    job_ref: Optional[str] = None
    bom_line_ref: Optional[str] = None
    week_bucket: Optional[str] = None
    created_at: Optional[datetime] = None


class DemandRollup(BaseModel):
    """One aggregated row. `week_bucket` is populated for group_by=week and
    null for group_by=sap. `job_count` = distinct job_ref in the group."""

    sap_code: Optional[str] = None
    week_bucket: Optional[str] = None
    total_qty: float = 0.0
    job_count: int = 0
