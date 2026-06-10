"""WO v4.28 — chassis lifecycle API schemas (chassis_records + lifecycle_events + photos)."""
from datetime import date, datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict


class ChassisPhotoOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    lifecycle_event_id: int
    original_filename: Optional[str] = None
    content_type: Optional[str] = None
    size_bytes: Optional[int] = None
    caption: Optional[str] = None
    uploaded_at: Optional[datetime] = None
    uploaded_by: Optional[str] = None
    url: Optional[str] = None                     # download URL (set by the router)


class ChassisEventOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    cycle_number: int
    event_type: str                               # 'VCL' | 'DCL' | 'assembly_assigned'
    assembly_bay_id: Optional[int] = None         # set only on 'assembly_assigned' events
    event_date: Optional[date] = None
    legacy_reference: Optional[str] = None
    checklist_json: Optional[dict] = None
    notes: Optional[str] = None
    created_at: Optional[datetime] = None
    created_by: Optional[str] = None
    photos: List[ChassisPhotoOut] = []


class ChassisRecordOut(BaseModel):                # list item
    model_config = ConfigDict(from_attributes=True)
    id: int
    vin: str
    job_number: Optional[str] = None
    customer_name: Optional[str] = None
    make: Optional[str] = None
    model: Optional[str] = None
    status: str
    current_assembly_bay_id: Optional[int] = None  # WO v4.31 §0.12 — DERIVED (latest assembly_assigned event), not a column
    source: str
    event_count: int = 0
    latest_event_date: Optional[date] = None


class ChassisRecordDetail(ChassisRecordOut):
    contact_person: Optional[str] = None
    telephone: Optional[str] = None
    description: Optional[str] = None
    submit_status: Optional[str] = None
    notes: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    events: List[ChassisEventOut] = []


class ChassisRecordCreate(BaseModel):
    vin: str
    job_number: Optional[str] = None
    customer_name: Optional[str] = None
    contact_person: Optional[str] = None
    telephone: Optional[str] = None
    make: Optional[str] = None
    model: Optional[str] = None
    description: Optional[str] = None
    notes: Optional[str] = None


class ChassisRecordUpdate(BaseModel):
    job_number: Optional[str] = None
    customer_name: Optional[str] = None
    contact_person: Optional[str] = None
    telephone: Optional[str] = None
    make: Optional[str] = None
    model: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None
    notes: Optional[str] = None


class ChassisEventCapture(BaseModel):
    """Capture a VCL (book-in) or DCL (dispatch) event. cycle_number optional — defaults to a fresh
    cycle for VCL, or the open (VCL-without-DCL) cycle for DCL."""
    cycle_number: Optional[int] = None
    event_date: Optional[date] = None
    checklist_json: Optional[dict] = None
    notes: Optional[str] = None


class AssemblyAssignRequest(BaseModel):
    """WO v4.31 §0.4 — assign a booked-in chassis to an assembly bay (parking -> assembly)."""
    assembly_bay_id: int
    event_date: Optional[date] = None
    notes: Optional[str] = None


class BayOut(BaseModel):
    """A parking or assembly bay (master reference data, WO v4.31 §0.3)."""
    model_config = ConfigDict(from_attributes=True)
    id: int
    code: str
    label: Optional[str] = None
    sort_order: Optional[int] = None
    is_active: bool = True
