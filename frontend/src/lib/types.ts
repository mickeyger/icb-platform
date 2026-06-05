// lib/types.ts — shared Planning Board types (WO v4.18 §4.5, Phase 2C-2).
//
// Two layers:
//   • Api* types mirror the v4.16 `/api/planning-board` response verbatim.
//   • The domain view (PlanningBoardView / PlanningSlot / PlanningJob) is what
//     the screen renders. PlanningContext maps Api* → domain (live) and the
//     mockup seed → domain (mock fallback), so the board renders identically.
//
// Naming note: the domain board type is `PlanningBoardView` (not `PlanningBoard`)
// to avoid colliding with the `PlanningBoard` screen component.

// ── Chassis state (drives the §3.3 slot badge + the §3.2 case-(a) client guard) ─
export type ChassisState = 'none' | 'eta_committed' | 'received'

/** Derive the chassis state from the two production-job columns.
 *  received → 'received'; ETA set but not received → 'eta_committed' (Path B);
 *  neither → 'none' (case (a): no ETA committed yet). */
export function getChassisState(
  job: { chassis_eta: string | null; chassis_received_at: string | null },
): ChassisState {
  if (job.chassis_received_at) return 'received'
  if (job.chassis_eta) return 'eta_committed'
  return 'none'
}

// ── Domain view (rendered by PlanningBoard.tsx) ────────────────────────────────
export interface PlanningJob {
  id: number                 // production_job id (live) — used as the schedule key
  job_number: string
  customer: string
  body_type: string | null
  selling_zar: number | null
  status: string | null
  source: string             // 'quote' | 'workbook' (WO v4.22 source-column fork)
  chassis_eta: string | null
  chassis_received_at: string | null
}

export interface PlanningSlot {
  id: number                 // planning_slot id (live) — used to move / unschedule
  week_key: string           // canonical week key (matches PlanningWeekCol.key)
  week_start: string         // ISO date (Monday) — sent as `week` on schedule/move
  bay: string                // grid row id, e.g. "V-1"
  lane: string | null        // route grouping, e.g. "vacuum" | "panelshop"
  slot_position: number | null
  job: PlanningJob | null
}

export interface PlanningWeekCol {
  key: string                // "2026-W23"
  start: string              // ISO date (Monday)
  end: string                // ISO date (Friday) — start + 4 days
}

export interface PlanningCapacity {
  week_key: string
  filled: number
  empty: number
  value_zar: number
}

export interface PlanningBoardView {
  weeks: PlanningWeekCol[]
  bays: string[]             // distinct bay/row ids returned by the server
  slots: PlanningSlot[]
  pool: PlanningJob[]        // unscheduled_pool (production_jobs status='planning')
  capacity: PlanningCapacity[]
}

// ── Mutation inputs (mapped to the v4.16 Schedule/Move request bodies) ─────────
export interface ScheduleInput {
  production_job_id: number
  week: string               // any ISO date in the target week (server → Monday)
  bay: string                // the cell id, e.g. "V-1"
  lane?: string | null
  slot_position?: number | null
}

export interface MoveInput {
  week: string
  bay: string
  lane?: string | null
  slot_position?: number | null
}

// ── API response shapes (v4.16 — app/schemas/planning.py) ──────────────────────
export interface ApiPlanningJobRef {
  id: number
  job_number: string | null
  status: string | null
  source: string | null      // 'quote' | 'workbook' (WO v4.22)
  customer: string | null
  body_type: string | null
  selling_zar: number | null
  branch_id: number | null
  chassis_eta: string | null
  chassis_received_at: string | null
  planned_start_date: string | null
}

export interface ApiPlanningSlotItem {
  id: number
  week: string | null        // ISO date (Monday)
  week_iso: string | null    // "2026-W23"
  bay: string | null
  lane: string | null
  slot_position: number | null
  status: string | null
  production_job: ApiPlanningJobRef | null
}

export interface ApiCapacityCell {
  week_iso: string
  filled: number
  empty: number
  value_zar: number
}

export interface ApiWeekRef {
  iso: string
  start: string              // ISO date (Monday)
}

export interface ApiPlanningBoard {
  weeks: ApiWeekRef[]
  lanes: string[]            // distinct bay ids (server field is named `lanes`)
  slots: ApiPlanningSlotItem[]
  unscheduled_pool: ApiPlanningJobRef[]
  capacity: ApiCapacityCell[]
}
