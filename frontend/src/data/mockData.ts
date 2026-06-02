import raw from './icb_mock_data.json'
import type { MockData, Job } from './types'

export const data = raw as unknown as MockData

// The demo job 32891 is flagged configurator_demo:true (last entry in jobs[]).
export const demoJob: Job =
  data.jobs.find((j) => j.configurator_demo) ?? data.jobs[0]

// ---------------------------------------------------------------------------
// Derived / illustrative constants.
// The brief references several fields that are NOT present in icb_mock_data.json.
// To keep the JSON verbatim we define those here, clearly labelled as mock.
// ---------------------------------------------------------------------------

// Screen 1 — Review step. Brief says "use the bom field from the demo job", but
// jobs[] carries no bom. This itemised BOM reconciles to job 32891's
// cost R75,729 / sell R129,156 / markup 65%.
export interface BomLine {
  sap_item_code: string
  description: string
  qty: number
  cost_zar: number
}

export const demoBom: BomLine[] = [
  { sap_item_code: 'NEW-03', description: '056mm PU Panel 2440x1220 32DV (Floor + Walls)', qty: 9, cost_zar: 18450 },
  { sap_item_code: 'STE-PLA-A-0001', description: '1.2mm Galvanised Skin 2440x1220', qty: 6, cost_zar: 7320 },
  { sap_item_code: 'TIM-PIN-A-0012', description: 'Timber Pine 38x38 Pre-Cut (framing)', qty: 22, cost_zar: 3080 },
  { sap_item_code: 'GRP-MPS-A-0040', description: 'GRP Capping & Corner Mouldings', qty: 1, cost_zar: 6450 },
  { sap_item_code: 'DOOR-RR-3220', description: 'Rear Doors, frame, gear & seals', qty: 1, cost_zar: 12900 },
  { sap_item_code: 'FRIDGE-TF-R500T', description: 'Transfrig R500T fridge unit (supply only)', qty: 1, cost_zar: 18600 },
  { sap_item_code: 'CON-AUT-A-0171', description: 'Adhesives, sealants & consumables', qty: 1, cost_zar: 4129 },
  { sap_item_code: 'LAB-ASSY', description: 'Assembly & fitment labour', qty: 1, cost_zar: 4800 },
]

export const demoBomTotal = demoBom.reduce((s, l) => s + l.cost_zar, 0) // 75,729

// Screen 6 — Orderbook breakdown by category (not in kpis). Illustrative.
export const orderbookBreakdown = [
  { label: 'New bodies', value_zar: 120_700_000 },
  { label: 'Buy-outs', value_zar: 12_700_000 },
  { label: 'Repairs', value_zar: 6_300_000 },
]

// Screen 6 — Delivery-risk counts over the next 4 weeks (not in data). Illustrative.
export const deliveryRisk = [
  { status: 'GREEN' as const, label: 'On track', jobs: 142 },
  { status: 'AMBER' as const, label: 'At risk', jobs: 27 },
  { status: 'RED' as const, label: 'Intervention', jobs: 18 },
]

// Screen 6 — Per-rep pipeline value (not in sales_reps). Illustrative, keyed by code.
export const repPipelineValue: Record<string, number> = {
  ATTIE: 8_900_000,
  BURT: 71_400_000,
  JANCO: 32_500_000,
  LOLLIE: 15_700_000,
  MICHAEL: 28_100_000,
  SCOTT: 9_200_000,
  SIPHO: 11_300_000,
  STEVIE: 6_800_000,
  SUZETTE: 5_100_000,
  TERTIUS: 13_400_000,
}

// Screen 5 — Labour efficiency by team today (chart is illustrative per brief).
export const labourEfficiency = [
  { team: 'Vacuum', planned: 48, booked: 44 },
  { team: 'Pre-Assy', planned: 36, booked: 39 },
  { team: 'Assembly', planned: 40, booked: 37 },
  { team: 'Lamination', planned: 24, booked: 22 },
  { team: 'GRP', planned: 32, booked: 19 },
  { team: 'Doors', planned: 28, booked: 27 },
  { team: 'QC', planned: 16, booked: 16 },
]

// Quick lookup helpers ------------------------------------------------------

export const customerById = (id: number) =>
  data.customers.find((c) => c.id === id)

export const jobByNumber = (jobNumber: string): Job | undefined =>
  data.jobs.find((j) => j.job_number === jobNumber)

// Units in production per brief: jobs not in Pipeline/Departed.
export const unitsInProduction = () =>
  data.jobs.filter(
    (j) => !['PIPELINE', 'DEPARTED'].includes(j.status) && !j.configurator_demo,
  ).length
