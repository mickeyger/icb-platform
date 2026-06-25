// WO v4.37 §3.2 — per-consumer data hooks for the native Cost Calculator.
// Per §0.15 (architectural reuse) the calculator subscribes to its own data via
// these hooks rather than a global provider. All calls go through lib/api
// (credentials + CSRF + ApiError); the backend is the already-native calc engine.
import { useCallback, useEffect, useRef, useState } from 'react'
import { apiGet, apiPost, mesAutoLogin } from '../../../lib/api'
import type {
  TrailerType, BomRow, CalcRequest, CalcResult,
  CustomerLite, DuplicateCheck, ApproveExtras,
} from './types'

/** Trailer-type list for the body-type dropdown (fetched once on mount). */
export function useTrailers() {
  const [trailers, setTrailers] = useState<TrailerType[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => {
    let alive = true
    // Wait for the dev-mode autologin session (a no-op in prod) before the first
    // authed fetch so the trailer list doesn't race ahead of the session cookie.
    mesAutoLogin()
      .then(() => apiGet<TrailerType[]>('/api/trailers'))
      .then((d) => { if (alive) { setTrailers(d); setError(null) } })
      .catch(() => { if (alive) setError('Could not load body types.') })
      .finally(() => { if (alive) setLoading(false) })
    return () => { alive = false }
  }, [])
  return { trailers, loading, error }
}

/** The selected trailer's BOM rows (re-fetched when the trailer changes). */
export function useTrailerBom(trailerId: number | null) {
  const [bom, setBom] = useState<BomRow[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => {
    if (trailerId == null) { setBom([]); return }
    let alive = true
    setLoading(true)
    apiGet<BomRow[]>(`/api/trailers/${trailerId}/bom`)
      .then((d) => { if (alive) { setBom(d); setError(null) } })
      .catch(() => { if (alive) setError('Could not load the body template.') })
      .finally(() => { if (alive) setLoading(false) })
    return () => { alive = false }
  }, [trailerId])
  return { bom, loading, error }
}

/** Debounced live calculate. calculate(req) schedules a POST /api/calculate; the
 *  latest result + a `calculating` flag drive the summary/BOM panels. A sequence
 *  guard drops stale responses so fast edits never render an out-of-order total. */
export function useLiveCalc(debounceMs = 250) {
  const [result, setResult] = useState<CalcResult | null>(null)
  const [calculating, setCalculating] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const seq = useRef(0)

  const calculate = useCallback((req: CalcRequest) => {
    if (timer.current) clearTimeout(timer.current)
    timer.current = setTimeout(() => {
      const mySeq = ++seq.current
      setCalculating(true)
      apiPost<CalcResult>('/api/calculate', req)
        .then((d) => { if (mySeq === seq.current) { setResult(d); setError(null) } })
        .catch(() => { if (mySeq === seq.current) setError('Calculation failed — check your inputs.') })
        .finally(() => { if (mySeq === seq.current) setCalculating(false) })
    }, debounceMs)
  }, [debounceMs])

  useEffect(() => () => { if (timer.current) clearTimeout(timer.current) }, [])
  return { result, calculating, error, calculate }
}

/** Customer typeahead for the save flow. */
export async function searchCustomers(q: string): Promise<CustomerLite[]> {
  if (!q.trim()) return []
  return apiGet<CustomerLite[]>(`/api/customers?q=${encodeURIComponent(q)}&limit=20`)
}

/** Revision-family duplicate check before saving a new costing. */
export async function checkDuplicate(
  customerId: number, trailerId: number, isRepair: boolean,
): Promise<DuplicateCheck> {
  return apiGet<DuplicateCheck>(
    `/api/check-duplicate?customer_id=${customerId}&trailer_type_id=${trailerId}&is_repair=${isRepair}`,
  )
}

/** Save / approve a costing (create, replace, new-version, or overwrite-edit). */
export async function approveCalc(req: CalcRequest, extras: ApproveExtras): Promise<CalcResult> {
  return apiPost<CalcResult>('/api/approve', { ...req, ...extras })
}

/** Load an existing costing for editing (carries the optimistic-lock etag). */
export async function loadCalculation(recordId: number): Promise<Record<string, unknown>> {
  return apiGet<Record<string, unknown>>(`/api/calculations/${recordId}`)
}
