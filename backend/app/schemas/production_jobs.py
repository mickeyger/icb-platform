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

from .chassis import ChassisRecordDetail

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


def _net_headline(calc, res, fallback):
    """WO v4.30 §0.2a — the post-discount headline figure for the MES (Costings) revenue views.
    Prefer the calculations.net_total column, then result_json's mirror, then fall back to the
    pre-discount selling price (so it equals selling whenever there is no discount, and for legacy
    rows saved before the discount feature). selling_zar is retained as the pre-discount reference."""
    if calc is not None:
        col = getattr(calc, "net_total", None)
        if col is not None:
            return col
        rj = res.get("net_total")
        if rj is not None:
            return rj
    return fallback


# ── Requests ─────────────────────────────────────────────────────────────────
class PreJobSignoffRequest(BaseModel):
    role: Literal["sales", "production"]
    attestation: str = Field(..., examples=["I, Burt Smith (Sales), confirm the costing is correct."])


class PlanningAckRequest(BaseModel):
    chassis_eta: Optional[date] = Field(default=None, examples=["2026-06-12"])
    notes: Optional[str] = Field(default=None, examples=["Chassis ETA confirmed with dealer."])
    # WO v4.29 D2: the planning-ack panel captures the chassis ETA + rich chassis data in ONE step on
    # the production-job surface. The legacy /api/calculations/{id}/chassis-eta endpoint was status-gated
    # to calc status 'planning' and mismatched the v4.19 pj-centric flow (deadlock — see ADR 0016), so
    # these optional rich fields now persist to production_jobs.chassis_data_json alongside the ETA.
    chassis_vin: Optional[str] = None
    chassis_model: Optional[str] = None
    customer_dealer: Optional[str] = None
    tail_lift_code: Optional[str] = None
    chassis_inhouse_bom: Optional[list] = None


# ── Responses ────────────────────────────────────────────────────────────────
class TimelineEvent(BaseModel):
    event_type: str = Field(..., examples=["pre_job_signoff_sales"])
    occurred_at: datetime
    actor: Optional[str] = None


class ProductionJobListItem(BaseModel):
    """Compact shape for list views."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    calculation_record_id: Optional[int] = None      # Costings join key (v4.19); NULL for workbook jobs (v4.21)
    source: str = "quote"                             # 'quote' | 'workbook' (WO v4.21)
    job_number: Optional[str] = None
    status: ProductionJobStatus
    mes_status: str
    customer: Optional[str] = None
    body_type: Optional[str] = None
    selling_zar: Optional[float] = None              # pre-discount (reference)
    net_total: Optional[float] = None                # WO v4.30 §0.2a — post-discount headline (== selling when no discount)
    branch_code: Optional[str] = None
    accepted_at: Optional[datetime] = None
    planned_start_date: Optional[datetime] = None
    # WO v4.29 — surface the per-role sign-off timestamps so the Costings list/detail can tick each
    # box + show "signed by … at …" as soon as that role signs (the signoff lives on the production_job).
    pre_job_signoff_sales_at: Optional[datetime] = None
    pre_job_signoff_sales_by: Optional[str] = None
    pre_job_signoff_production_at: Optional[datetime] = None
    pre_job_signoff_production_by: Optional[str] = None
    pre_job_confirmed_at: Optional[datetime] = None


class ProductionJobInProgressItem(ProductionJobListItem):
    """WO v4.32 §0.4 — list item + chassis/bay context for the Production Dashboard.
    Chassis fields are None for jobs without a linked chassis_record; bay code only while the
    chassis is in_assembly (event-derived, §0.12). days_in_stage per the §0.6 default (time
    since the latest lifecycle timestamp on the job row)."""
    chassis_vin: Optional[str] = None
    chassis_status: Optional[str] = None             # received | in_workshop | in_assembly | dispatched | returned
    current_assembly_bay_code: Optional[str] = None
    days_in_stage: Optional[int] = None


class BomLineOut(BaseModel):
    """A current-BOM line for the job-card modal (WO v4.31 §3.2). Read-only."""
    model_config = ConfigDict(from_attributes=True)
    sap_code: str
    description: Optional[str] = None
    qty: float
    unit_price: Optional[float] = None       # workshop HIDES this column at render time (frontend; NOT gated here)
    line_total: Optional[float] = None
    section: Optional[str] = None


class GeneratedBomOut(BaseModel):
    """The job's current generated_bom + its lines (WO v4.31 §3.2). Read-only."""
    model_config = ConfigDict(from_attributes=True)
    id: int
    version: int
    bom_status: str                          # complete | incomplete | manual
    grand_total: Optional[float] = None
    generated_at: Optional[datetime] = None
    lines: list[BomLineOut] = []


def bom_to_out(bom, lines) -> GeneratedBomOut:
    """Build GeneratedBomOut from a GeneratedBom row + its BomLine rows (WO v4.31 §3.2)."""
    return GeneratedBomOut(
        id=bom.id, version=bom.version, bom_status=bom.bom_status,
        grand_total=float(bom.grand_total) if bom.grand_total is not None else None,
        generated_at=bom.generated_at,
        lines=[BomLineOut.model_validate(line) for line in lines],
    )


class ProductionJobDetail(BaseModel):
    """Full shape — production_jobs columns + joined costing + derived UI fields."""
    model_config = ConfigDict(from_attributes=True)

    # production_jobs identity / lifecycle
    id: int
    calculation_record_id: Optional[int] = None
    source: str = "quote"                             # 'quote' | 'workbook' (WO v4.21)
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
    selling_zar: Optional[float] = None          # pre-discount (reference)
    net_total: Optional[float] = None            # WO v4.30 §0.2a — post-discount headline (== selling when no discount)
    grand_total: Optional[float] = None          # headline alias — now net_total (was selling_zar)
    gross_profit_zar: Optional[float] = None
    markup_pct: Optional[float] = None
    extras_count: Optional[int] = None
    extras_list: Optional[list] = None
    dimensions_json: Optional[str] = None         # raw (per WO §3.1)
    result_json: Optional[str] = None             # raw (per WO §3.1)

    # ── WO v4.31 §3.2 — job-card modal enrichment (READ-ONLY; no new write paths) ──
    current_bom: Optional[GeneratedBomOut] = None        # current generated_bom + lines
    chassis: Optional[ChassisRecordDetail] = None        # chassis record + events (latest VCL = photos/checklist/notes)
    current_assembly_bay_code: Optional[str] = None      # resolved bay code for bay context; None if not on a bay
    assembly_assigned_at: Optional[datetime] = None      # when assigned to the current bay (duration context)


# ── Builders (from the service join tuple) ───────────────────────────────────
def to_list_item(job, calc, customer, branch_code=None) -> ProductionJobListItem:
    # calc is None for workbook-imported jobs (no originating calculation, v4.21):
    # fall back to the production_jobs carrier columns for customer/body/selling.
    res = (_loads(calc.result_json) or {}) if calc else {}
    dims = (_loads(calc.dimensions_json) or {}) if calc else {}
    return ProductionJobListItem(
        id=job.id,
        calculation_record_id=job.calculation_record_id,
        source=job.source,
        job_number=job.job_number,
        status=job.status,
        mes_status=_mes_status(job.status, bool(calc.is_repair) if calc else False),
        customer=(customer.name if customer else job.customer_name),
        body_type=(dims.get("body_type") if calc else job.description),
        selling_zar=(res.get("selling_zar") if calc else job.selling_zar),
        net_total=_net_headline(calc, res, (res.get("selling_zar") if calc else job.selling_zar)),
        branch_code=branch_code,
        accepted_at=job.accepted_at,
        planned_start_date=job.planned_start_date,
        pre_job_signoff_sales_at=job.pre_job_signoff_sales_at,
        pre_job_signoff_sales_by=job.pre_job_signoff_sales_by,
        pre_job_signoff_production_at=job.pre_job_signoff_production_at,
        pre_job_signoff_production_by=job.pre_job_signoff_production_by,
        pre_job_confirmed_at=job.pre_job_confirmed_at,
    )


def to_detail(job, calc, customer, branch_code=None) -> ProductionJobDetail:
    # calc is None for workbook-imported jobs (v4.21): calc-derived fields resolve to
    # None/defaults; customer/body/selling fall back to the production_jobs carriers.
    res = (_loads(calc.result_json) or {}) if calc else {}
    dims = (_loads(calc.dimensions_json) or {}) if calc else {}
    selling = res.get("selling_zar") if calc else job.selling_zar
    net = _net_headline(calc, res, selling)   # WO v4.30 §0.2a — post-discount headline
    return ProductionJobDetail(
        id=job.id,
        calculation_record_id=job.calculation_record_id,
        source=job.source,
        branch_id=job.branch_id,
        branch_code=branch_code,
        job_number=job.job_number,
        status=job.status,
        mes_status=_mes_status(job.status, bool(calc.is_repair) if calc else False),
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
        quote_number=(calc.quote_number if calc else None),
        customer_id=(calc.customer_id if calc else None),
        customer=(customer.name if customer else job.customer_name),
        is_repair=(bool(calc.is_repair) if calc else False),
        body_type=(dims.get("body_type") if calc else job.description),
        body_category=dims.get("body_category"),
        requires_chassis=dims.get("requires_chassis"),
        chassis_supplied_by=dims.get("chassis_supplied_by"),
        cost_zar=res.get("cost_zar"),
        selling_zar=selling,
        net_total=net,
        grand_total=net,
        gross_profit_zar=res.get("gross_profit_zar"),
        markup_pct=res.get("markup_pct"),
        extras_count=res.get("extras_count"),
        extras_list=res.get("extras_list"),
        dimensions_json=(calc.dimensions_json if calc else None),
        result_json=(calc.result_json if calc else None),
    )
