"""Pydantic schemas for the /api/chassis-register surface (WO v4.22, §3.3).

Read-only chassis lifecycle records loaded from Book1 TRUCK REGISTER 2026.xlsx.
List items are compact; detail adds the multi-cycle history + the preserved
full 112-column source row (`raw_row_json`).
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict


class ChassisRegisterItem(BaseModel):
    """Compact shape for list views."""
    model_config = ConfigDict(from_attributes=True)

    id: int
    job_number: Optional[str] = None
    customer_name: Optional[str] = None
    vehicle_id_no: Optional[str] = None     # VIN
    model: Optional[str] = None
    make: Optional[str] = None
    description: Optional[str] = None
    submit_status: Optional[str] = None
    date_received_1: Optional[date] = None
    date_left_1: Optional[date] = None


class ChassisRegisterDetail(ChassisRegisterItem):
    """Full shape — adds contact details, the 2nd cycle, and raw_row_json."""
    telephone: Optional[str] = None
    contact_person: Optional[str] = None
    vcl_1: Optional[str] = None
    dcl_1: Optional[str] = None
    date_received_2: Optional[date] = None
    vcl_2: Optional[str] = None
    date_left_2: Optional[date] = None
    dcl_2: Optional[str] = None
    raw_row_json: Optional[Any] = None       # full 112-col source row
    imported_at: Optional[datetime] = None
