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
    tail_lift_code: Optional[str] = None        # WO v4.36b — chassis-field unification (Edit + ack round-trip)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    # WO v4.36a §3.5c — the AUTHORITATIVE job link (production_jobs.chassis_record_id back-reference), filled
    # by get_detail. Drives the Edit modal: linked → job_number read-only ("swap via Merge"); unlinked → the
    # job dropdown. NOT chassis_records.job_number (free-text/non-unique legacy provenance — not a link).
    linked_job_id: Optional[int] = None
    linked_job_number: Optional[str] = None
    linked_customer: Optional[str] = None
    # WO v4.36a §3.6 STEP 7 — tombstone state (a soft-deleted/merged chassis stays navigable by id). Drives
    # the detail-page banner + Restore affordance. deleted_at/merged_into_id auto-fill from the row;
    # merged_into_vin is resolved in get_detail.
    deleted_at: Optional[datetime] = None
    merged_into_id: Optional[int] = None
    merged_into_vin: Optional[str] = None
    chassis_eta: Optional[date] = None              # WO v4.36a §3.5e — the LINKED job's ETA (get_detail fills it)
    # WO v4.36.5 §3.3 — optimistic-lock version (the etag): the Edit modal echoes this back on PATCH; a stale
    # value → 409. server_default="0" on the column, so existing rows read 0.
    version: int = 0
    events: List[ChassisEventOut] = []


class ChassisRecordCreate(BaseModel):
    vin: str
    job_number: Optional[str] = None
    # WO v4.36a §0.6/§0.7 — the selected job to link (from the unlinked-jobs dropdown; atomically sets
    # production_jobs.chassis_record_id) + the supplying dealer (validated is_dealer=true).
    production_job_id: Optional[int] = None
    dealer_id: Optional[int] = None
    # WO v4.36a §3.5e — Delivery ETA. There is NO chassis_eta column; it persists onto the LINKED job's
    # production_jobs.chassis_eta (the §0.13 single source, set at Planning Ack). Ignored if no job linked.
    chassis_eta: Optional[date] = None
    customer_name: Optional[str] = None
    contact_person: Optional[str] = None
    telephone: Optional[str] = None
    make: Optional[str] = None
    model: Optional[str] = None
    description: Optional[str] = None
    notes: Optional[str] = None
    tail_lift_code: Optional[str] = None         # WO v4.36b — chassis-field unification


class ChassisRecordUpdate(BaseModel):
    job_number: Optional[str] = None
    # WO v4.36a §3.5c — when the chassis is UNLINKED, the Edit modal sends the selected job here to
    # atomically set production_jobs.chassis_record_id (mirrors create). Ignored for a LINKED chassis
    # (job_number is read-only there — swap via admin Merge Chassis), so the edit door can't re-point a link.
    production_job_id: Optional[int] = None
    # WO v4.36a §3.5e — Delivery ETA → persists onto the linked job's production_jobs.chassis_eta (popped
    # before the setattr loop — chassis_records has no chassis_eta column).
    chassis_eta: Optional[date] = None
    customer_name: Optional[str] = None
    contact_person: Optional[str] = None
    telephone: Optional[str] = None
    make: Optional[str] = None
    model: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None
    notes: Optional[str] = None
    # WO v4.36b — chassis-field unification: the Edit modal AND the Planning-ack panel now both write these
    # onto chassis_records (single source of truth). dealer_id validated is_dealer=true; tail_lift_code plain col.
    dealer_id: Optional[int] = None
    tail_lift_code: Optional[str] = None
    # WO v4.36.5 — optimistic lock: the Chassis-page Edit modal echoes the version it loaded; a stale value
    # (someone else saved in between) → 409 "reload". Optional/back-compat: omitted → no concurrency check.
    version: Optional[int] = None


class ChassisAuditRow(BaseModel):                 # WO v4.36.5 §3.4 — one chassis_records_audit entry (read)
    model_config = ConfigDict(from_attributes=True)
    id: int
    field_name: str
    old_value: Optional[str] = None
    new_value: Optional[str] = None
    source: Optional[str] = None
    edited_by_name: Optional[str] = None          # write-time SNAPSHOT (no users-join; survives a user delete)
    created_at: Optional[datetime] = None


class ChassisCreateResult(BaseModel):
    """WO v4.36a §0.8 — the Add-Chassis result envelope. `adopted` = the VIN matched an existing live chassis
    and the selected job was linked to it (the frontend then shows the AdoptionNotificationModal with
    `message` + `chassis`); otherwise a fresh chassis (or a placeholder updated in-place) was created."""
    chassis: ChassisRecordDetail
    adopted: bool = False
    adopted_chassis_id: Optional[int] = None
    message: Optional[str] = None


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


class PanelsArrivedRequest(BaseModel):
    """WO v4.35 §3.3b (STRETCH) — record a job's panels arriving in an assembly bay (the JOB-side of the
    merge; POST /api/production-jobs/{id}/panels-arrived-in-bay)."""
    bay_id: int
    notes: Optional[str] = Field(default=None, max_length=500)


class MoveToAwaitingQaRequest(BaseModel):
    """WO v4.36a.1 §0.5 — move a body-attached chassis off its assembly bay into the QA queue
    (POST /api/chassis-records/{id}/move-to-awaiting-qa). Optional handover note only — the chassis
    identity comes from the path; pre-conditions are enforced server-side."""
    notes: Optional[str] = Field(default=None, max_length=500)


class ReturnToParkingRequest(BaseModel):
    """WO v4.36a.2 — move a chassis off its assembly bay back to the parking pool, before any merge
    (POST /api/chassis-records/{id}/return-to-parking). Optional re-prioritisation reason only."""
    reason: Optional[str] = Field(default=None, max_length=500)


class AwaitingQaOut(BaseModel):
    """WO v4.36a.1 §0.7 — one chassis in the Awaiting-QA Planning Board zone."""
    chassis_id: int
    vin: Optional[str] = None
    make: Optional[str] = None
    model: Optional[str] = None
    customer_name: Optional[str] = None
    job_number: Optional[str] = None


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
    # ── WO v4.35 §0.20 / §3.3b — the bay state (event-derived, by services.chassis.
    # compute_bay_merge_readiness). MUST-SHIP 4: 'empty' | 'awaiting_attachment' | 'attached_today' |
    # 'post_attached'. STRETCH adds the 2 panels-event states: 'pre_assembly' (panels staged, no chassis) |
    # 'ready_to_merge' (panels + chassis, same job, body not yet attached).
    state: Optional[str] = None
    body_attached_on: Optional[date] = None       # latest body_attached event_date for the occupant
    # ── WO v4.35 §3.3b UX — panels-side fields + the mismatch cue ──
    mismatch: bool = False                         # panels + a chassis that belong to DIFFERENT jobs (wrong-bay drop)
    panels_job_id: Optional[int] = None            # the job whose panels are on this bay (drives the move-back undo)
    panels_job_number: Optional[str] = None
    # WO — the panels-job's OWN linked chassis VIN + customer (distinct from the occupant chassis above),
    # for the bay right-click "unlink panels" menu so the operator can identify the blocking job/chassis.
    panels_chassis_vin: Optional[str] = None
    panels_customer_name: Optional[str] = None
