"""WO v4.32 §0.4/§3.3 — per-team daily worksheet schemas (the load-bearing contract, ADR 0019).

ONE uniform shape for all five teams (vacuum / press / assembly / parking / dispatch):
team-specific fields are simply nullable, so the frontend renders every tab with the same
component. Sections are fixed: scheduled / in_flight / blocking. `capacity` is populated only
where a real ceiling exists (parking: ~24 yard spots — the chip is informational; the yard has
no formal slot allocation until Phase 4).
"""
from datetime import date as date_type
from typing import List, Optional

from pydantic import BaseModel


class WorksheetItem(BaseModel):
    """One row of a team's worksheet. Identity fields are nullable because not every team's
    rows are job-anchored (parking/dispatch rows are chassis-anchored; a slot row may carry
    both)."""
    job_id: Optional[int] = None
    job_number: Optional[str] = None
    chassis_vin: Optional[str] = None
    customer: Optional[str] = None
    description: Optional[str] = None
    location: Optional[str] = None        # slot/bay code ('V-2', 'AssemblyBay-3') or 'Yard'
    status: str                           # domain status driving the status pill
    since: Optional[date_type] = None     # when the row entered its current state (business date)
    flag: Optional[str] = None            # human-readable attention/blocking reason


class WorksheetCapacity(BaseModel):
    used: int
    total: int


class WorksheetSections(BaseModel):
    scheduled: List[WorksheetItem] = []
    in_flight: List[WorksheetItem] = []
    blocking: List[WorksheetItem] = []


class TeamWorksheet(BaseModel):
    team: str                             # vacuum | press | assembly | parking | dispatch
    date: date_type
    capacity: Optional[WorksheetCapacity] = None
    sections: WorksheetSections
