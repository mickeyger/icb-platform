"""Planning Board schemas (WO v4.16, ADR 0008) — PlanningBoard.tsx contract."""
from datetime import date, datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


class WeekRef(BaseModel):
    iso: str          # "2026-W23"
    start: date       # Monday of the week


class PlanningJobRef(BaseModel):
    """Compact production-job summary for a board cell / the unscheduled pool."""
    id: int
    job_number: Optional[str] = None
    status: Optional[str] = None
    source: str = "quote"                   # 'quote' | 'workbook' (WO v4.22 source-column fork)
    customer: Optional[str] = None
    body_type: Optional[str] = None
    selling_zar: Optional[float] = None
    branch_id: Optional[int] = None
    chassis_eta: Optional[datetime] = None
    chassis_received_at: Optional[datetime] = None       # legacy column (DEPRECATED-as-write, ADR 0016)
    # WO v4.29 D3 read-bridge (§0.3): authoritative chassis-received signal — latest VCL event date,
    # else the legacy column. `source` is 'vcl' | 'legacy' | None for the cell tooltip.
    chassis_received_signal: Optional[datetime] = None
    chassis_received_source: Optional[str] = None
    planned_start_date: Optional[datetime] = None


class PlanningSlotItem(BaseModel):
    id: int
    week: Optional[date] = None
    week_iso: Optional[str] = None
    bay: Optional[str] = None
    lane: Optional[str] = None
    slot_position: Optional[int] = None
    status: Optional[str] = None
    production_job: Optional[PlanningJobRef] = None


class CapacityCell(BaseModel):
    week_iso: str
    filled: int
    empty: int
    value_zar: float


class PlanningBoard(BaseModel):
    weeks: List[WeekRef]
    lanes: List[str]                       # the slot/bay grid identifiers
    slots: List[PlanningSlotItem]
    unscheduled_pool: List[PlanningJobRef]
    capacity: List[CapacityCell]


class ScheduleRequest(BaseModel):
    model_config = ConfigDict(json_schema_extra={"example": {
        "production_job_id": 1, "week": "2026-06-01", "bay": "V-1",
        "lane": "vacuum", "slot_position": 1}})
    production_job_id: int
    week: date                             # any date in the target week (normalised to Monday)
    bay: str                               # the cell identifier (e.g. "V-1")
    lane: Optional[str] = None
    slot_position: Optional[int] = None


class MoveRequest(BaseModel):
    model_config = ConfigDict(json_schema_extra={"example": {
        "week": "2026-06-08", "bay": "V-2", "lane": "vacuum", "slot_position": 2}})
    week: date
    bay: str
    lane: Optional[str] = None
    slot_position: Optional[int] = None


class RevertRequest(BaseModel):
    """WO v4.34.2 §0.7 — optional reason for a scheduled → unscheduled revert. ≤500 chars
    (Pydantic enforces → 422); empty/omitted is accepted (one-click revert for fast reshuffles)."""
    reason: Optional[str] = Field(default=None, max_length=500)
