// WO v4.36c §3.2 — QC inbox + inspection hooks. Per-consumer fetchers over /api/qc/* (the §3.1
// service) — no shared provider (mirrors useFlags.ts; no Layout/App contention with CA4's widget).
import { useCallback, useEffect, useState } from 'react'

import { apiGet, apiPost } from '../lib/api'

export interface QcInboxRow {
  chassis_id: number
  vin: string | null
  make: string | null
  model: string | null
  customer_name: string | null
  job_number: string | null
  awaiting_since: string | null
  failed_count: number
}

export type Verdict = 'pass' | 'fail'

export interface QcCategory {
  category_id: number
  name: string
  sort_order: number
  verdict: Verdict | null
  notes: string | null
}

export interface PriorSignoff {
  cycle_number: number
  overall_verdict: string
  notes: string | null
  created_at: string | null
}

export interface QcInspection {
  chassis_id: number
  vin: string | null
  make: string | null
  model: string | null
  customer_name: string | null
  status: string
  cycle_number: number
  categories: QcCategory[]
  prior_signoffs: PriorSignoff[]
}

export interface SignoffResult {
  chassis_id: number
  cycle_number: number
  overall_verdict: Verdict
  new_status: string
  pdf_available: boolean
}

/** Kenny's QC inbox — chassis awaiting QA, with awaiting-since + failed_count. */
export function useQcInbox() {
  const [rows, setRows] = useState<QcInboxRow[]>([])
  const [loading, setLoading] = useState(true)
  const refresh = useCallback(() => {
    setLoading(true)
    apiGet<QcInboxRow[]>('/api/qc/awaiting')
      .then(setRows)
      .catch(() => setRows([]))
      .finally(() => setLoading(false))
  }, [])
  useEffect(() => { refresh() }, [refresh])
  return { rows, loading, refresh }
}

/** Current inspection state for one chassis (categories with any open-cycle verdicts + prior signoffs). */
export function useInspection(chassisId: number | null) {
  const [data, setData] = useState<QcInspection | null>(null)
  const [loading, setLoading] = useState(true)
  const refresh = useCallback(() => {
    if (chassisId == null) { setData(null); setLoading(false); return }
    setLoading(true)
    apiGet<QcInspection>(`/api/qc/inspection/${chassisId}`)
      .then(setData)
      .catch(() => setData(null))
      .finally(() => setLoading(false))
  }, [chassisId])
  useEffect(() => { refresh() }, [refresh])
  return { data, loading, refresh }
}

// ── mutations (callers wrap in try/catch → handleApiError; the backend is the source of truth) ──
export const recordVerdict = (chassisId: number, categoryId: number, verdict: Verdict, notes: string | null) =>
  apiPost(`/api/qc/inspection/${chassisId}/category/${categoryId}`, { verdict, notes })

export const submitSignoff = (chassisId: number, notes: string | null) =>
  apiPost<SignoffResult>(`/api/qc/signoff/${chassisId}`, { notes })
