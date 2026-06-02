export type Status = 'GREEN' | 'AMBER' | 'RED' | 'GREY'

export interface Meta {
  purpose: string
  version: string
  snapshot_date: string
  currency: string
}

export interface User {
  id: string
  name: string
  role: string
  rep_code: string
  site: string
  avatar_initials: string
}

export interface Kpis {
  orderbook_total_zar: number
  orderbook_jhb: number
  orderbook_ct: number
  invoiced_ytd_zar: number
  active_jobs: number
  planned_jobs: number
  unplanned_jobs: number
  invoiced_jobs: number
  late_jobs: number
  critical_chassis: number
  weekly_target_zar: number
  current_week: string
  completed_today: number
  target_today: number
}

export interface Site {
  id: string
  name: string
  is_primary?: boolean
}

export interface SalesRep {
  code: string
  name: string
  active_jobs: number
  planned: number
  invoiced_ytd: number
  late: number
  critical_chassis: number
}

export interface Customer {
  id: number
  name: string
  contact: string
  default_rep: string
  site: string
}

export interface ChassisModel {
  code: string
  make: string
  model: string
  category: string
  max_payload_kg: number
}

export interface FridgeUnit {
  code: string
  supplier: string
  model: string
  category: string
  approx_weight_kg: number
}

export interface TailLift {
  code: string
  supplier: string
  model: string
  capacity_kg: number
}

export interface BodyType {
  code: string
  name: string
  panel_route: 'VACUUM' | 'PANELSHOP'
  complexity: 'EASY' | 'MEDIUM' | 'HARD'
}

export interface Job {
  job_number: string
  customer_id: number
  rep: string
  site: string
  description: string
  chassis_code: string
  body_type: string
  fridge_code: string
  lift_code: string
  dimensions_mm: { length: number; width: number; height: number }
  cost_zar: number
  selling_zar: number
  gross_profit_zar: number
  markup_pct: number
  status: string
  promised_date: string
  chassis_received: string | null
  invoiced_date?: string
  left_icb_date?: string | null
  current_phase: string
  current_bay: string | null
  progress_pct: number
  is_late: boolean
  days_late?: number
  priority: string
  complexity: string
  next_action?: string
  configurator_demo?: boolean
}

export interface Bay {
  id: string
  name: string
  category: string
  wip_limit: number
  wip_count: number
  status: Status
  current_jobs: string[]
  queue: string[]
  throughput_today: number
  target_today: number
  team: string
  amber_reason?: string
  red_reason?: string
  is_bottleneck?: boolean
}

export interface KanbanJobCard {
  job_number: string
  customer_name: string
  body_type: string
  priority?: string
  promised_date?: string
  complexity?: string
  hours_in_bay?: number
  hours_planned?: number
  assigned_to?: string
  is_over?: boolean
  reason?: string
  hours_waiting?: number
  severity?: string
  completed_at?: string
}

export interface PreAssyKanban {
  bay_id: string
  bay_name: string
  team: string
  wip_count: number
  wip_limit: number
  status: Status
  throughput_today: number
  target_today: number
  throughput_wtd: number
  target_wtd: number
  factory_bottleneck: string
  in_queue: KanbanJobCard[]
  in_progress: KanbanJobCard[]
  waiting: KanbanJobCard[]
  completed_today: KanbanJobCard[]
}

export interface PickingSlipItem {
  sap_item_code: string
  description: string
  qty_required: number
  qty_picked: number
  status: 'picked' | 'short' | 'unchecked' | 'failed'
  shortage?: number
}

export interface SignoffItem {
  id: number
  text: string
  result: 'pass' | 'fail' | null
}

export interface VacuumBayTablet {
  bay_id: string
  bay_name: string
  operator: string
  shift_start: string
  current_work_order: {
    wo_id: string
    job_number: string
    customer_name: string
    body_type: string
    phase: string
    started_at: string
    planned_hours: number
    elapsed_hours: number
    panels_in_cycle: string
    picking_slip: PickingSlipItem[]
    signoff_items: SignoffItem[]
  }
  next_work_orders: { wo_id: string; job_number: string; customer_name: string; scheduled_start: string }[]
}

export interface QcItem {
  id: number
  text: string
  result: 'pass' | 'fail' | 'pending'
  severity?: string
  comment?: string
  photo?: boolean
}

export interface QcSection {
  name: string
  items: QcItem[]
}

export interface QcChecklist {
  wo_id: string
  job_number: string
  customer_name: string
  body_type: string
  started_at: string
  inspector: string
  sections: QcSection[]
  summary: { total: number; passed: number; failed: number; pending: number }
}

export interface PlanningWeek {
  week: string
  start: string
  end: string
  slots_total: number
  slots_filled: number
  slots_empty: number
  value_zar: number
}

export interface SlotAssignment {
  week: string
  slot: string
  job_number: string
  customer_name: string
}

export interface UnscheduledJob {
  job_number: string
  customer_name: string
  rep: string
  promised_date: string
  reason: string
}

export interface PlanningBoard {
  weeks: PlanningWeek[]
  slot_assignments: SlotAssignment[]
  unscheduled: UnscheduledJob[]
}

export interface MaterialAlert {
  sap_item_code: string
  description: string
  qty_needed: number
  qty_available: number
  shortage: number
  first_use_date: string
  severity: 'HIGH' | 'MEDIUM' | 'LOW'
  po_status: string
  affecting_jobs: string[]
}

export interface ReworkTicket {
  ticket: string
  job_number: string
  from_bay: string
  to_bay: string
  reason: string
  severity: string
  opened_at: string
  status: string
}

export interface Vendor {
  id: string
  name: string
  category: string
}

export interface Employee {
  clock_no: string
  name: string
  dept: string
  skills: string[]
}

export interface MockData {
  _meta: Meta
  user: User
  kpis: Kpis
  sites: Site[]
  sales_reps: SalesRep[]
  customers: Customer[]
  chassis_models: ChassisModel[]
  fridge_units: FridgeUnit[]
  tail_lifts: TailLift[]
  body_types: BodyType[]
  jobs: Job[]
  bays: Bay[]
  pre_assy_kanban: PreAssyKanban
  vacuum_bay_tablet: VacuumBayTablet
  qc_checklist_sample: QcChecklist
  planning_board: PlanningBoard
  material_alerts: MaterialAlert[]
  rework_tickets: ReworkTicket[]
  external_vendors: Vendor[]
  employees: Employee[]
}
