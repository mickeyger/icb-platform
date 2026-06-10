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
  event_type: 'VCL' | 'DCL' | 'assembly_assigned'   // WO v4.31 §0.4
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
  vin: string
  job_number?: string | null
  customer_name?: string | null
  make?: string | null
  model?: string | null
  status: string
  current_assembly_bay_id?: number | null   // WO v4.31 §0.12 — derived (latest assembly_assigned event)
  source: string
  event_count: number
  latest_event_date?: string | null
}

export interface ChassisRecordDetail extends ChassisRecord {
  contact_person?: string | null
  telephone?: string | null
  description?: string | null
  submit_status?: string | null
  notes?: string | null
  created_at?: string | null
  updated_at?: string | null
  events: ChassisEvent[]
}

export const CHASSIS_STATUS_STYLE: Record<string, string> = {
  received: 'bg-status-amber/15 text-status-amber',
  in_workshop: 'bg-primary-light text-primary',
  in_assembly: 'bg-status-green/15 text-status-green',   // WO v4.31 — on an assembly bay
  dispatched: 'bg-status-green/15 text-status-green',
}

// WO v4.31 §0.3 — a parking or assembly bay (mirrors backend schemas/chassis.py BayOut).
export interface Bay {
  id: number
  code: string
  label?: string | null
  sort_order?: number | null
  is_active: boolean
}
