import raw from './icb_costings_data.json'

// MES status names (verbatim from icb_costings_data.json / icb_tooltips.json).
export type StatusName =
  | 'Pending'
  | 'Accepted'
  | 'Pre-Job Sent'
  | 'Pre-Job Confirmed'
  | 'Rejected'
  | 'Repair'
  | 'Planning'

// Permission keys (Addendum v1.2.1 §7 + Work Order v4 §7). Kept as a union of
// literals so missing keys are flagged at compile time.
export type PermissionKey =
  | 'costings.view_own'
  | 'costings.view_all'
  | 'costings.create'
  | 'costings.accept'              // v4
  | 'costings.pre_job_card'
  | 'costings.signoff_sales'       // v4
  | 'costings.signoff_production'  // v4
  | 'costings.admin'
  | 'planning.view'
  | 'planning.acknowledge'         // v4
  | 'planning.schedule'            // v4.18 — drag-drop schedule / move
  | 'planning.unschedule'          // v4.18 — return a slot to the pool
  | 'production.chassis_received'  // v4.19 — chassis arrival confirmation
  | 'production.view'
  | 'management.view'
  | 'tablet.signoff'
  | 'qc.signoff'
  | 'kanban.team_lead'
  // Work Order v4.11 — Materials, Buying & Stores.
  | 'materials.view'
  | 'materials.raise_pr'
  | 'materials.override_supplier'
  | 'materials.count'
  | 'materials.bulk_raise'
  // Work Order v4.28 — Chassis lifecycle module.
  | 'chassis.create'
  | 'chassis.update'
  | 'chassis.vcl'
  | 'chassis.dcl'

export type RoleId =
  | 'rep_burt'
  | 'prod_mgr'
  | 'planning_off'
  | 'owner'
  | 'qc_lead'
  | 'buyer'
  | 'stores'

export interface DemoUserProfile {
  id: RoleId | string
  name: string
  role: string
  icon: string
}

export interface LoggedInUser {
  id: string
  name: string
  rep_code: string
  role: string
  site: string
  permissions: PermissionKey[]
}

export interface Costing {
  quote_number: string
  customer_id: number
  customer_name: string
  body_type: string
  body_category: string
  quote_type: 'New Build' | 'Repair'
  requires_chassis: boolean
  chassis_supplied_by?: 'customer' | 'in-house'
  extras_count: number
  extras_list?: string[]
  created_by: string
  created_at: string
  cost_zar: number
  selling_zar: number              // WO v4.30 §0.2a — post-discount headline (== gross when no discount)
  gross_selling_zar?: number       // pre-discount selling, shown as "before discount" when a discount exists
  discount_amount?: number         // currency discount; > 0 means a discount was applied
  gross_profit_zar: number
  markup_pct: number
  status: StatusName
  accepted_at?: string
  rejected_at?: string
  rejection_reason?: string
  pre_job_sent_at?: string
  pre_job_confirmed_at?: string
  pre_job_recipients?: string[]
  pre_job_awaiting_from?: string[]
  job_number_assigned?: string
  repair_scope?: string
  repair_phase_entry?: string
  repair_phases?: { phase: string; bay_id: string; estimated_hours: number }[]
  // Work Order v4 — sign-off + planning ack fields.
  pre_job_signoff_sales_at?: string | null
  pre_job_signoff_sales_by?: string | null
  pre_job_signoff_sales_attestation?: string | null
  pre_job_signoff_production_at?: string | null
  pre_job_signoff_production_by?: string | null
  pre_job_signoff_production_attestation?: string | null
  planning_acknowledged_at?: string | null
  planning_acknowledged_by?: string | null
  // Work Order v4.2 — chassis ETA capture (gates Planning acknowledgement).
  chassis_eta?: string | null
  chassis_eta_captured_at?: string | null
  chassis_eta_captured_by?: string | null
  chassis_data?: ChassisData | null
  // Work Order v4.3 — chassis arrival confirmation (tick box on job card).
  chassis_received_at?: string | null
  chassis_received_by?: string | null
  promised_date?: string
  site: string
  actions_available: string[]
  // Work Order v4.19 — linked production job id (null = accepted calc with no job
  // yet → the "partial" state that renders a "Retry job creation" button).
  production_job_id?: number | null
}

export interface ChassisBomItem {
  category: string
  description: string
  item_code: string
}

export interface ChassisData {
  chassis_vin?: string
  chassis_model?: string
  customer_dealer?: string
  tail_lift_code?: string
  chassis_inhouse_bom?: ChassisBomItem[]
}

export interface RepairPhaseInsertion {
  phase: string
  work: string
  estimated_hours: number
  bay_assignment: string
  status: string
}

export interface RepairInsertionSample {
  quote_number: string
  customer_name: string
  repair_scope: string
  phase_insertions: RepairPhaseInsertion[]
  total_estimated_hours: number
  promised_date: string
  customer_to_drop_off: string
}

export interface CostingsFile {
  logged_in_user: LoggedInUser
  demo_user_profiles: DemoUserProfile[]
  status_counts: Record<StatusName | 'Total', number>
  costings: Costing[]
  pre_job_card_event_sample: unknown
  pre_job_card_confirmation_sample: unknown
  repair_insertion_sample: RepairInsertionSample
}

export const costingsMock = raw as unknown as CostingsFile

// ---------------------------------------------------------------------------
// Role → permissions table (from Addendum v1.2.1 §7). The JSON only gives Burt's
// permissions; the other three profiles get theirs here.
// ---------------------------------------------------------------------------
export const ROLE_PERMISSIONS: Record<string, PermissionKey[]> = {
  rep_burt: [
    'costings.view_own',
    'costings.view_all',
    'costings.create',
    'costings.accept',
    'costings.pre_job_card',
    'costings.signoff_sales',
    // DEMO ONLY: also granted costings.signoff_production + planning.acknowledge
    // so a single presenter (Burt) can drive the full quote → Planning flow
    // without switching profiles. In production these would stay with the
    // Production Manager + Planning Officer respectively.
    'costings.signoff_production',
    'planning.view',
    'planning.acknowledge',
    'planning.schedule',
    'planning.unschedule',
    'production.chassis_received',
    'production.view',
    'tablet.signoff',
  ],
  prod_mgr: [
    'costings.view_own',
    'costings.view_all',
    'costings.pre_job_card',
    'costings.signoff_production',
    'planning.view',
    'planning.acknowledge',
    'planning.schedule',
    'planning.unschedule',
    'production.chassis_received',
    'production.view',
    'tablet.signoff',
    'kanban.team_lead',
    // v4.11 — read-only Materials Dashboard + Weekly Forecast.
    'materials.view',
  ],
  // v4 — Planning Officer profile. Acknowledges new jobs on the Planning Board;
  // no costings.* mutation rights beyond view_all.
  planning_off: [
    'costings.view_own',
    'costings.view_all',
    'planning.view',
    'planning.acknowledge',
    'planning.schedule',
    'planning.unschedule',
    'production.chassis_received',
    'production.view',
    // v4.11 — read-only Materials Dashboard + Weekly Forecast (planner shares the forecast).
    'materials.view',
  ],
  owner: [
    'costings.view_own',
    'costings.view_all',
    'costings.create',
    'costings.accept',
    'costings.pre_job_card',
    'costings.signoff_sales',
    'costings.signoff_production',
    'costings.admin',
    'planning.view',
    'planning.acknowledge',
    'planning.schedule',
    'planning.unschedule',
    'production.chassis_received',
    'production.view',
    'management.view',
    'tablet.signoff',
    'qc.signoff',
    'kanban.team_lead',
    // v4.11 — read-only Materials Dashboard + Weekly Forecast.
    'materials.view',
  ],
  qc_lead: [
    'costings.view_own',
    'planning.view',
    'production.view',
    'qc.signoff',
  ],
  // v4.11 — Buyer (M. Nkomo). Works primarily in the MES; SAP is the system of
  // record behind it. Senior-buyer rights (override + bulk raise) granted in the
  // demo so a single presenter can walk the full buying flow.
  buyer: [
    'costings.view_own',
    'costings.view_all',
    'production.view',
    'materials.view',
    'materials.raise_pr',
    'materials.override_supplier',
    'materials.bulk_raise',
    // WO v4.11 §3.8 acceptance: "Buyer sees all four". Stores still OWNS the
    // cycle-count screen (it's their daily job); the buyer can also reach it to
    // investigate a flagged discrepancy. Stores remains count-only, so the
    // reciprocal criterion ("Stores can't see Buyer screens") still holds.
    'materials.count',
  ],
  // v4.11 — Stores (P. Mokoena). Owns the cycle-count screen (BA finding 1 Jun
  // 2026). Deliberately NOT granted materials.view so Stores can't see the Buyer
  // screens — the acceptance run checks this separation.
  stores: [
    'production.view',
    'materials.count',
  ],
}

// ---------------------------------------------------------------------------
// /api/calculations payload shape (subset we actually use).
// Returned by the FastAPI costing app.
// ---------------------------------------------------------------------------
export interface LiveCalculation {
  id: number
  quote_number: string | null
  trailer: string
  customer: string
  user: string
  created_at: string
  grand_total: number | null       // WO v4.30 §0.2a — net of discount (the headline)
  gross_total?: number | null      // pre-discount selling
  discount_amount?: number | null
  discount_kind?: string | null
  status: string
  mes_status: StatusName | string
  is_repair: boolean
  pre_job_sent_at: string | null
  pre_job_confirmed_at: string | null
  job_number_assigned: string | null
  repair_phases: { phase: string; bay_id: string; estimated_hours: number }[] | null
  // Work Order v4 — sign-off + planning ack fields.
  pre_job_signoff_sales_at?: string | null
  pre_job_signoff_sales_by?: string | null
  pre_job_signoff_production_at?: string | null
  pre_job_signoff_production_by?: string | null
  planning_acknowledged_at?: string | null
  planning_acknowledged_by?: string | null
  // Work Order v4.2 — chassis ETA capture fields.
  chassis_eta?: string | null
  chassis_eta_captured_at?: string | null
  chassis_eta_captured_by?: string | null
  chassis_data?: ChassisData | null
  // Work Order v4.3 — chassis arrival confirmation.
  chassis_received_at?: string | null
  chassis_received_by?: string | null
}

// Map a live FastAPI row into the Costing shape the dashboard renders.
// We don't have all the rich fields (body_category, extras_list, etc.) from
// the live endpoint, so we synthesize sensible placeholders.
export function liveToCosting(r: LiveCalculation): Costing {
  const status = (r.mes_status as StatusName) || 'Pending'
  return {
    quote_number: r.quote_number || `#${r.id}`,
    customer_id: 0,
    customer_name: r.customer || '—',
    body_type: r.trailer || '—',
    body_category: '',
    quote_type: r.is_repair ? 'Repair' : 'New Build',
    requires_chassis: true,
    extras_count: 0,
    created_by: r.user || '',
    created_at: r.created_at,
    cost_zar: 0,
    selling_zar: r.grand_total ?? 0,                         // net (headline)
    gross_selling_zar: r.gross_total ?? r.grand_total ?? 0,  // pre-discount (for the "before discount" line)
    discount_amount: r.discount_amount ?? 0,
    gross_profit_zar: 0,
    markup_pct: 0,
    status,
    pre_job_sent_at: r.pre_job_sent_at ?? undefined,
    pre_job_confirmed_at: r.pre_job_confirmed_at ?? undefined,
    job_number_assigned: r.job_number_assigned ?? undefined,
    repair_phases: r.repair_phases ?? undefined,
    pre_job_signoff_sales_at: r.pre_job_signoff_sales_at ?? null,
    pre_job_signoff_sales_by: r.pre_job_signoff_sales_by ?? null,
    pre_job_signoff_production_at: r.pre_job_signoff_production_at ?? null,
    pre_job_signoff_production_by: r.pre_job_signoff_production_by ?? null,
    planning_acknowledged_at: r.planning_acknowledged_at ?? null,
    planning_acknowledged_by: r.planning_acknowledged_by ?? null,
    chassis_eta: r.chassis_eta ?? null,
    chassis_eta_captured_at: r.chassis_eta_captured_at ?? null,
    chassis_eta_captured_by: r.chassis_eta_captured_by ?? null,
    chassis_data: r.chassis_data ?? null,
    chassis_received_at: r.chassis_received_at ?? null,
    chassis_received_by: r.chassis_received_by ?? null,
    site: 'JHB',
    actions_available: deriveActions(status, r.is_repair),
  }
}

function deriveActions(status: StatusName, isRepair: boolean): string[] {
  const a: string[] = ['view']
  if (status === 'Pending') { a.push('accept'); a.push('edit') }
  if (status === 'Accepted') a.push('pre_job_card')
  if (isRepair || status === 'Repair') a.push('schedule_into_mes')
  return a
}

// All MES statuses (drives the filter chips order).
export const ALL_STATUSES: StatusName[] = [
  'Pending',
  'Accepted',
  'Pre-Job Sent',
  'Pre-Job Confirmed',
  'Planning',
  'Rejected',
  'Repair',
]
