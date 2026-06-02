"""Pydantic schemas for the /api/production-jobs surface (WO v4.14).

Response contract is a SUPERSET (per the v4.14 review): the production_jobs
columns + the spec's joined costing fields, PLUS UI-friendly derived fields so
Phase 2C wiring is near drop-in:
  * `status` is the production_jobs enum (lowercase) AND `mes_status` is the
    title-case label the React UI filters on ("Pre-Job Sent", "Repair", ...).
  * flat money fields (cost_zar/selling_zar/gross_profit_zar/markup_pct +
    grand_total alias) parsed from calculations.result_json.
  * body_type/body_category/requires_chassis/chassis_supplied_by from
    calculations.dimensions_json; `customer` (name) from the joined Customer.
  * `chassis_data` / `repair_phases` parsed from the *_json text columns.

Cross-schema data arrives as a (ProductionJob, CalculationRecord, Customer|None,
branch_code) tuple from the service join helper; `to_list_item` / `to_detail`
build the response models.
"""
from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

ProductionJobStatus = Literal[
    "accepted", "pre_job_sent", "pre_job_confirmed", "planning", "in_production", "completed"
]

_MES_STATUS = {
    "accepted": "Accepted",
    "pre_job_sent": "Pre-Job Sent",
    "pre_job_confirmed": "Pre-Job Confirmed",
    "planning": "Planning",
    "in_production": "In Production",
    "completed": "Completed",
}


def _loads(raw: Optional[str]) -> Optional[Any]:
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return None


def _mes_status(status: str, is_repair: bool) -> str:
    return "Repair" if is_repair else _MES_STATUS.get(status, status)


# ── Requests ─────────────────────────────────────────────────────────────────
class PreJobSignoffRequest(BaseModel):
    role: Literal["sales", "production"]
    attestation: str = Field(..., examples=["I, Burt Smith (Sales), confirm the costing is correct."])


class PlanningAckRequest(BaseModel):
    chassis_eta: Optional[date] = Field(default=None, examples=["2026-06-12"])
    notes: Optional[str] = Field(default=None, examples=["Chassis ETA confirmed with dealer."])


# ── Responses ────────────────────────────────────────────────────────────────
class TimelineEvent(BaseModel):
    event_type: str = Field(..., examples=["pre_job_signoff_sales"])
    occurred_at: datetime
    actor: Optional[str] = None


class ProductionJobListItem(BaseModel):
    """Compact shape for list views."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    job_number: Optional[str] = None
    status: ProductionJobStatus
    mes_status: str
    customer: Optional[str] = None
    body_type: Optional[str] = None
    selling_zar: Optional[float] = None
    branch_code: Optional[str] = None
    accepted_at: Optional[datetime] = None
    planned_start_date: Optional[datetime] = None


class ProductionJobDetail(BaseModel):
    """Full shape — production_jobs columns + joined costing + derived UI fields."""
    model_config = ConfigDict(from_attributes=True)

    # production_jobs identity / lifecycle
    id: int
    calculation_record_id: int
    branch_id: Optional[int] = None
    branch_code: Optional[str] = None
    job_number: Optional[str] = None
    status: ProductionJobStatus
    mes_status: str
    accepted_at: Optional[datetime] = None
    pre_job_sent_at: Optional[datetime] = None
    pre_job_confirmed_at: Optional[datetime] = None
    job_number_assigned: Optional[str] = None
    pre_job_signoff_sales_at: Optional[datetime] = None
    pre_job_signoff_sales_by: Optional[str] = None
    pre_job_signoff_sales_attestation: Optional[str] = None
    pre_job_signoff_production_at: Optional[datetime] = None
    pre_job_signoff_production_by: Optional[str] = None
    pre_job_signoff_production_attestation: Optional[str] = None
    planning_acknowledged_at: Optional[datetime] = None
    planning_acknowledged_by: Optional[str] = None
    chassis_eta: Optional[datetime] = None
    chassis_eta_captured_at: Optional[datetime] = None
    chassis_eta_captured_by: Optional[str] = None
    chassis_data: Optional[Any] = None          # parsed from chassis_data_json
    chassis_received_at: Optional[datetime] = None
    chassis_received_by: Optional[str] = None
    repair_phases: Optional[Any] = None          # parsed from repair_phases_json
    planned_start_date: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    # joined costing fields (icb_costings.calculations + customer)
    quote_number: Optional[str] = None
    customer_id: Optional[int] = None
    customer: Optional[str] = None
    is_repair: bool = False
    body_type: Optional[str] = None
    body_category: Optional[str] = None
    requires_chassis: Optional[bool] = None
    chassis_supplied_by: Optional[str] = None
    cost_zar: Optional[float] = None
    selling_zar: Optional[float] = None
    grand_total: Optional[float] = None          # alias of selling_zar (React reads grand_total)
    gross_profit_zar: Optional[float] = None
    markup_pct: Optional[float] = None
    extras_count: Optional[int] = None
    extras_list: Optional[list] = None
    dimensions_json: Optional[str] = None         # raw (per WO §3.1)
    result_json: Optional[str] = None             # raw (per WO §3.1)


# ── Builders (from the service join tuple) ───────────────────────────────────
def to_list_item(job, calc, customer, branch_code=None) -> ProductionJobListItem:
    res = _loads(calc.result_json) or {}
    dims = _loads(calc.dimensions_json) or {}
    return ProductionJobListItem(
        id=job.id,
        job_number=job.job_number,
        status=job.status,
        mes_status=_mes_status(job.status, bool(calc.is_repair)),
        customer=(customer.name if customer else None),
        body_type=dims.get("body_type"),
        selling_zar=res.get("selling_zar"),
        branch_code=branch_code,
        accepted_at=job.accepted_at,
        planned_start_date=job.planned_start_date,
    )


def to_detail(job, calc, customer, branch_code=None) -> ProductionJobDetail:
    res = _loads(calc.result_json) or {}
    dims = _loads(calc.dimensions_json) or {}
    selling = res.get("selling_zar")
    return ProductionJobDetail(
        id=job.id,
        calculation_record_id=job.calculation_record_id,
        branch_id=job.branch_id,
        branch_code=branch_code,
        job_number=job.job_number,
        status=job.status,
        mes_status=_mes_status(job.status, bool(calc.is_repair)),
        accepted_at=job.accepted_at,
        pre_job_sent_at=job.pre_job_sent_at,
        pre_job_confirmed_at=job.pre_job_confirmed_at,
        job_number_assigned=job.job_number_assigned,
        pre_job_signoff_sales_at=job.pre_job_signoff_sales_at,
        pre_job_signoff_sales_by=job.pre_job_signoff_sales_by,
        pre_job_signoff_sales_attestation=job.pre_job_signoff_sales_attestation,
        pre_job_signoff_production_at=job.pre_job_signoff_production_at,
        pre_job_signoff_production_by=job.pre_job_signoff_production_by,
        pre_job_signoff_production_attestation=job.pre_job_signoff_production_attestation,
        planning_acknowledged_at=job.planning_acknowledged_at,
        planning_acknowledged_by=job.planning_acknowledged_by,
        chassis_eta=job.chassis_eta,
        chassis_eta_captured_at=job.chassis_eta_captured_at,
        chassis_eta_captured_by=job.chassis_eta_captured_by,
        chassis_data=_loads(job.chassis_data_json),
        chassis_received_at=job.chassis_received_at,
        chassis_received_by=job.chassis_received_by,
        repair_phases=_loads(job.repair_phases_json),
        planned_start_date=job.planned_start_date,
        completed_at=job.completed_at,
        created_at=job.created_at,
        updated_at=job.updated_at,
        quote_number=calc.quote_number,
        customer_id=calc.customer_id,
        customer=(customer.name if customer else None),
        is_repair=bool(calc.is_repair),
        body_type=dims.get("body_type"),
        body_category=dims.get("body_category"),
        requires_chassis=dims.get("requires_chassis"),
        chassis_supplied_by=dims.get("chassis_supplied_by"),
        cost_zar=res.get("cost_zar"),
        selling_zar=selling,
        grand_total=selling,
        gross_profit_zar=res.get("gross_profit_zar"),
        markup_pct=res.get("markup_pct"),
        extras_count=res.get("extras_count"),
        extras_list=res.get("extras_list"),
        dimensions_json=calc.dimensions_json,
        result_json=calc.result_json,
    )
