"""WO v4.28 — chassis lifecycle API schemas (chassis_records + lifecycle_events + photos)."""
from datetime import date, datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


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
    vin: Optional[str] = None                     # WO v4.34 §0.3 — NULL until receive ('expected' pipeline rows)
    job_number: Optional[str] = None
    customer_name: Optional[str] = None
    make: Optional[str] = None
    model: Optional[str] = None
    status: str
    current_assembly_bay_id: Optional[int] = None  # WO v4.31 §0.12 — DERIVED (latest assembly_assigned event), not a column
    source: str
    created_via: Optional[str] = None             # WO v4.34 §0.4 — provenance pill (pre_job_card | planning_job_create | manual_chassis_menu | legacy_import_v4_28)
    created_source_ref: Optional[str] = None      # e.g. "A32744/06/2026" or "Planning · Job 32791"
    dealer_id: Optional[int] = None               # WO v4.34.1 §0.3 — supplying dealer (customers.is_dealer)
    dealer_name: Optional[str] = None             # WO v4.34.1 §3.4 — resolved cross-schema (router/service fills)
    vin_source: Optional[str] = None              # WO v4.34.1 §0.17 — VIN provenance (vcl | chassis_page_manual | …)
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


class ChassisVinCapture(BaseModel):
    """WO v4.34.1 §3.4b (Gap A) — late VIN capture on the Chassis page. Deliberately separate from
    ChassisRecordUpdate (which has NO vin field): the VIN is write-once, guarded server-side to a
    NULL→value transition only, stamping vin_source='chassis_page_manual'."""
    vin: str


class ChassisModelOut(BaseModel):
    """WO v4.34 §3.7 — one chassis-type DDM entry feeding the make/model dropdowns (Planning ack,
    Pre-Job Card, Chassis +New/edit). Read-only in v4.34; admin CRUD is v4.35."""
    model_config = ConfigDict(from_attributes=True)
    id: int
    code: str
    make: str
    model: str
    category: Optional[str] = None
    max_payload_kg: Optional[int] = None


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


class BodyAttachedRequest(BaseModel):
    """WO v4.35 §0.5 — mark the body attached to the chassis in its assembly bay."""
    production_job_id: int
    notes: Optional[str] = Field(default=None, max_length=500)


class BayOut(BaseModel):
    """A parking or assembly bay (master reference data, WO v4.31 §0.3).

    WO v4.32 §0.4 extends the ASSEMBLY response with utilisation fields (per-bay occupant +
    since), derived from the latest 'assembly_assigned' event (§0.12 — event-derived, no
    denormalised column). All optional/None for parking bays and pre-v4.32 consumers, so the
    v4.31 contract (useBayModel reads id/code/label) is unchanged."""
    model_config = ConfigDict(from_attributes=True)
    id: int
    code: str
    label: Optional[str] = None
    sort_order: Optional[int] = None
    is_active: bool = True
    # ── WO v4.32 utilisation (assembly bays only; None = free / not computed) ──
    occupied: bool = False
    occupant_chassis_id: Optional[int] = None
    occupant_vin: Optional[str] = None
    occupant_customer: Optional[str] = None
    occupant_job_id: Optional[int] = None
    occupant_job_number: Optional[str] = None
    since: Optional[date] = None                  # assembly_assigned event_date (business date)
    # ── WO v4.35 §0.20 — the MUST-SHIP 4-state bay machine (event-derived). The 2 panels-event
    # states (pre_assembly / ready_to_merge) are STRETCH; for MUST-SHIP a bay is one of:
    # 'empty' | 'awaiting_attachment' | 'attached_today' | 'post_attached'.
    state: Optional[str] = None
    body_attached_on: Optional[date] = None       # latest body_attached event_date for the occupant
