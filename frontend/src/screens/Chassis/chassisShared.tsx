// WO v4.36a §3.5c — pieces shared by the Add-Chassis (create) and Edit-Chassis modals: the unlinked-jobs
// list shape, the prefill shape, the VIN provenance label map, the strict-VIN regex, and the "auto-filled"
// badge. Lifted from ChassisList.tsx so create + edit stay in sync — the edit door was the bypass vector.

export interface UnlinkedJob {
  id: number; job_number: string | null; customer: string | null; body_type: string | null
}

export interface ChassisPrefill {
  chassis_id?: number | null   // WO v4.36.5 §3.3 — the linked chassis id (for the ack's "Edit on Chassis page" link)
  customer_name: string | null; customer_id: number | null; chassis_type: string | null
  dealer_id: number | null; dealer_name: string | null; vin_number: string | null; vin_source: string | null
  chassis_eta: string | null   // §3.5e — the linked job's Delivery ETA (YYYY-MM-DD)
  // WO v4.36b — chassis-field unification: the rest of the linked chassis fields, so the Planning-ack seed
  // reads chassis_records (single source of truth), not the costing blob.
  contact_person?: string | null; telephone?: string | null; description?: string | null
  chassis_notes?: string | null; tail_lift_code?: string | null
}

// Human label for the VIN-captured provenance note.
export const VIN_PROVENANCE: Record<string, string> = {
  pre_job_card: 'Pre-Job', planning_ack: 'Planning Ack', chassis_page_manual: 'Chassis page',
  vcl: 'VCL', vcl_form: 'VCL',
}

// Strict VIN (§0.1) — mirrors the backend VIN_RE; used to decide whether a captured VIN is safe to LOCK.
// A legacy/non-conforming captured VIN stays editable so it can be corrected (locking it would dead-end).
export const VIN_RE = /^[A-HJ-NPR-Z0-9]{17}$/

export function FilledBadge() {
  return <span className="ml-1 rounded bg-primary/10 px-1 text-[9px] font-medium text-primary align-middle">auto-filled</span>
}
