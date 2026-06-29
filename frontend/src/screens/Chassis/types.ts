// WO v4.28 — chassis lifecycle domain types (mirror backend app/schemas/chassis.py).
export interface ChassisEventPhoto {
  id: number
  original_filename?: string | null
  content_type?: string | null
  caption?: string | null
  url?: string | null
}

export interface ChassisEvent {
  id: number
  cycle_number: number
  // WO v4.31 §0.4 · v4.35 body_attached · v4.36a.1 moved_to_awaiting_qa (status-promoting handoff)
  event_type: 'VCL' | 'DCL' | 'assembly_assigned' | 'body_attached' | 'moved_to_awaiting_qa'
  assembly_bay_id?: number | null                   // set only on assembly_assigned events
  event_date?: string | null
  legacy_reference?: string | null
  checklist_json?: Record<string, unknown> | null
  notes?: string | null
  created_by?: string | null
  photos: ChassisEventPhoto[]
}

export interface ChassisRecord {
  id: number
  vin: string | null                         // WO v4.34 §0.3 — NULL until receive ('expected' rows)
  job_number?: string | null
  customer_name?: string | null
  make?: string | null
  model?: string | null
  status: string
  current_assembly_bay_id?: number | null   // WO v4.31 §0.12 — derived (latest assembly_assigned event)
  source: string
  created_via?: string | null               // WO v4.34 §0.4 — provenance pill
  created_source_ref?: string | null
  dealer_id?: number | null                 // WO v4.34.1 §0.3 — supplying dealer (customers.is_dealer)
  dealer_name?: string | null               // WO v4.34.1 §3.4 — resolved cross-schema
  vin_source?: string | null                // WO v4.34.1 §0.17 — VIN provenance (chassis_page_manual = Gap A)
  event_count: number
  latest_event_date?: string | null
}

// WO v4.36a.1 §0.7 — one chassis in the Awaiting-QA Planning Board zone (mirrors backend
// schemas/chassis.py AwaitingQaOut). Fed by GET /api/chassis-records/awaiting-qa.
export interface AwaitingQaRow {
  chassis_id: number
  vin?: string | null
  make?: string | null
  model?: string | null
  customer_name?: string | null
  job_number?: string | null
}

// WO v4.34 §3.7 — one chassis-type DDM entry (mirrors backend schemas/chassis.py ChassisModelOut).
export interface ChassisModel {
  id: number
  code: string
  make: string
  model: string
  category?: string | null
  max_payload_kg?: number | null
}

export interface ChassisRecordDetail extends ChassisRecord {
  contact_person?: string | null
  telephone?: string | null
  description?: string | null
  submit_status?: string | null
  notes?: string | null
  tail_lift_code?: string | null   // WO v4.36b — chassis-field unification (Edit modal Tail-lift)
  created_at?: string | null
  updated_at?: string | null
  // WO v4.36a §3.5c — authoritative job link (production_jobs.chassis_record_id back-ref); drives the
  // Edit modal: linked → job_number read-only ("swap via Merge"); unlinked → the job dropdown.
  linked_job_id?: number | null
  linked_job_number?: string | null
  linked_customer?: string | null
  // WO v4.36a §3.6 STEP 7 — tombstone state (soft-deleted / merged); drives the detail banner + Restore.
  deleted_at?: string | null
  merged_into_id?: number | null
  merged_into_vin?: string | null
  chassis_eta?: string | null   // §3.5e — the linked job's Delivery ETA (YYYY-MM-DD)
  version?: number              // WO v4.36.5 §3.3 — optimistic-lock etag; echoed back on PATCH (stale → 409)
  events: ChassisEvent[]
}

// WO v4.36.5 §3.4 — one chassis_records_audit entry (mirrors backend schemas/chassis.py ChassisAuditRow).
export interface ChassisAuditRow {
  id: number
  field_name: string
  old_value?: string | null
  new_value?: string | null
  source?: string | null
  edited_by_name?: string | null   // write-time snapshot
  created_at?: string | null
}

export const CHASSIS_STATUS_STYLE: Record<string, string> = {
  expected: 'bg-primary-light/60 text-primary',          // WO v4.34 §0.3 — pipeline placeholder (no VIN yet)
  expected_orphaned: 'bg-status-red/15 text-status-red',  // §0.6 — auto-created then released (reject)
  received: 'bg-status-amber/15 text-status-amber',
  in_workshop: 'bg-primary-light text-primary',
  in_assembly: 'bg-status-green/15 text-status-green',   // WO v4.31 — on an assembly bay
  awaiting_qa: 'bg-sky-100 text-sky-700',                // WO v4.36a.1 — body attached, moved off the bay to QA
  dispatched: 'bg-status-green/15 text-status-green',
}

// WO v4.34 §0.4 — provenance pill: how a chassis row was created. Falls back to the raw token
// when an unknown created_via appears (legacy rows carry source instead).
export const CHASSIS_PROVENANCE: Record<string, { label: string; style: string }> = {
  pre_job_card:       { label: 'Auto · Pre-Job', style: 'bg-primary-light/60 text-primary' },
  planning_job_create:{ label: 'Auto · Planning', style: 'bg-primary-light/60 text-primary' },
  manual_chassis_menu:{ label: 'Manual', style: 'bg-surface-alt text-body' },
  legacy_import_v4_28:{ label: 'Imported', style: 'bg-surface-alt text-muted' },
}

// WO v4.31 §0.3 — a parking or assembly bay (mirrors backend schemas/chassis.py BayOut).
/** WO v4.35 §3.3b — the assembly-bay 6-state machine (event-derived; backend
 *  services.chassis.compute_bay_merge_readiness is the single source of truth). The first four are
 *  MUST-SHIP; 'pre_assembly' + 'ready_to_merge' are the STRETCH panels-event states. */
export type BayState =
  | 'empty'
  | 'pre_assembly'
  | 'ready_to_merge'
  | 'awaiting_attachment'
  | 'attached_today'
  | 'post_attached'

export interface Bay {
  id: number
  code: string
  label?: string | null
  sort_order?: number | null
  is_active: boolean
  // WO v4.32 §0.4 / v4.35 §0.20 + §3.3b — assembly-bay utilisation + state (present on /bays/assembly
  // only; parking bays omit these). Additive — v4.31 consumers read id/code/label only.
  occupied?: boolean
  occupant_chassis_id?: number | null
  occupant_vin?: string | null
  occupant_customer?: string | null
  occupant_job_id?: number | null
  occupant_job_number?: string | null
  since?: string | null
  state?: BayState | null
  body_attached_on?: string | null
  // WO v4.35 §3.3b UX — panels + a chassis from DIFFERENT jobs (wrong-bay drop), + the panels job (so the
  // move-panels-back undo knows what to clear).
  mismatch?: boolean
  panels_job_id?: number | null
  panels_job_number?: string | null
  // WO — the panels-job's OWN linked chassis VIN + customer, for the bay right-click "unlink panels" menu.
  panels_chassis_vin?: string | null
  panels_customer_name?: string | null
}
