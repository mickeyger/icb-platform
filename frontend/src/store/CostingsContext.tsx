import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react'
import {
  costingsMock,
  liveToCosting,
  ALL_STATUSES,
  type Costing,
  type LiveCalculation,
  type RepairPhaseInsertion,
  type StatusName,
} from '../data/costingsData'

type Mode = 'live' | 'mock' | 'loading'

interface CostingsValue {
  mode: Mode
  costings: Costing[]
  statusCounts: Record<StatusName | 'Total', number>
  refresh: () => Promise<void>
  // Mutations — POST to FastAPI in Live mode; update local state in Mock mode.
  firePreJobCard: (quote: string) => Promise<void>
  confirmPreJobCard: (quote: string) => Promise<void>
  scheduleRepairPhases: (quote: string, phases: RepairPhaseInsertion[]) => Promise<void>
  // Work Order v4 mutators.
  acceptCosting: (quote: string) => Promise<void>
  signoffPreJob: (quote: string, role: 'sales' | 'production', attestation: string, by: string) => Promise<void>
  ackPlanning: (quote: string, by: string) => Promise<void>
  // Work Order v4.2 — chassis ETA capture.
  captureChassisEta: (quote: string, payload: ChassisEtaPayload, by: string) => Promise<void>
  loadChassisCatalogue: () => Promise<ChassisCatalogue | null>
  // Work Order v4.3 — chassis arrival confirmation (tick box on job card).
  markChassisReceived: (quote: string, receivedAt: string | null, by: string) => Promise<void>
}

export interface ChassisEtaPayload {
  chassis_eta: string                        // ISO date
  chassis_vin?: string
  chassis_model?: string
  customer_dealer?: string
  tail_lift_code?: string
  chassis_inhouse_bom?: { category: string; description: string; item_code: string }[]
}

export interface ChassisCatalogue {
  constants: { id: number; category: string; name: string; unit_price: number }[]
  options:   { id: number; kind: string; label: string; axle_count?: number | null; tyre_style?: string | null; price?: number }[]
}

const CostingsContext = createContext<CostingsValue | null>(null)

// Same-origin in unified mode (FastAPI serves the build on :8000); the Vite dev
// server proxies /api -> :8000. Override with VITE_API_BASE only for split hosts.
const API_BASE = import.meta.env.VITE_API_BASE ?? ''
const FETCH_TIMEOUT_MS = 1500

/** Try to mint a costing-app session for the demo user so the MES iframe
 *  inherits it. Safe to call repeatedly: the server returns `already=true`
 *  when a valid session already exists. Silently fails if the FastAPI app
 *  is offline (no harm — the next fetch will fall back to Mock mode). */
async function mesAutoLogin(): Promise<void> {
  try {
    const ctrl = new AbortController()
    const t = setTimeout(() => ctrl.abort(), FETCH_TIMEOUT_MS)
    await fetch(`${API_BASE}/api/mes/autologin`, {
      method: 'POST',
      credentials: 'include',
      signal: ctrl.signal,
    })
    clearTimeout(t)
  } catch {
    /* ignore — Mock mode will take over */
  }
}

async function fetchLiveCalculations(): Promise<LiveCalculation[] | null> {
  try {
    const ctrl = new AbortController()
    const t = setTimeout(() => ctrl.abort(), FETCH_TIMEOUT_MS)
    const res = await fetch(`${API_BASE}/api/calculations?limit=100`, {
      credentials: 'include',
      signal: ctrl.signal,
    })
    clearTimeout(t)
    if (!res.ok) return null
    const data = (await res.json()) as LiveCalculation[]
    return Array.isArray(data) ? data : null
  } catch {
    return null
  }
}

function deriveStatusCounts(rows: Costing[]): Record<StatusName | 'Total', number> {
  const counts = { Total: 0 } as Record<StatusName | 'Total', number>
  for (const s of ALL_STATUSES) counts[s] = 0
  for (const r of rows) {
    counts.Total++
    if ((ALL_STATUSES as string[]).includes(r.status)) counts[r.status]++
  }
  return counts
}

export function CostingsProvider({ children }: { children: ReactNode }) {
  const [mode, setMode] = useState<Mode>('loading')
  const [costings, setCostings] = useState<Costing[]>(costingsMock.costings)
  const liveIdByQuote = useRef<Map<string, number>>(new Map())

  const load = useCallback(async () => {
    // Mint a costing-app session first so the iframe inherits it.
    await mesAutoLogin()
    const live = await fetchLiveCalculations()
    if (live && live.length > 0) {
      const rows = live.map(liveToCosting)
      liveIdByQuote.current = new Map(live.map((r) => [r.quote_number ?? `#${r.id}`, r.id]))
      setCostings(rows)
      setMode('live')
    } else {
      setCostings(costingsMock.costings)
      setMode('mock')
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  const statusCounts = useMemo(() => {
    // In Mock mode we trust the bundled status_counts (it represents a fuller
    // population of 40 costings, not just the 15 sample rows). In Live mode we
    // derive counts from the live rows.
    return mode === 'mock' ? costingsMock.status_counts : deriveStatusCounts(costings)
  }, [mode, costings])

  async function liveTransition(quote: string, path: string, body?: unknown): Promise<Costing | null> {
    const id = liveIdByQuote.current.get(quote)
    if (id == null) return null
    try {
      const res = await fetch(`${API_BASE}/api/calculations/${id}/${path}`, {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: body ? JSON.stringify(body) : undefined,
      })
      if (!res.ok) return null
      await load() // re-fetch the whole list for simplicity
      return costings.find((c) => c.quote_number === quote) ?? null
    } catch {
      return null
    }
  }

  const firePreJobCard = useCallback(
    async (quote: string) => {
      if (mode === 'live') {
        await liveTransition(quote, 'pre-job-card')
        return
      }
      setCostings((prev) =>
        prev.map((c) =>
          c.quote_number === quote && c.status === 'Accepted'
            ? {
                ...c,
                status: 'Pre-Job Sent' as StatusName,
                pre_job_sent_at: new Date().toISOString(),
                pre_job_recipients: ['BURT (Sales Rep)', 'Pieter Coetzee (Production Manager)'],
                pre_job_awaiting_from: ['Pieter Coetzee (Production Manager)'],
                actions_available: ['view', 'view_pre_job_status'],
              }
            : c,
        ),
      )
    },
    [mode],
  )

  const confirmPreJobCard = useCallback(
    async (quote: string) => {
      if (mode === 'live') {
        await liveTransition(quote, 'pre-job-confirm')
        return
      }
      setCostings((prev) =>
        prev.map((c) =>
          c.quote_number === quote && c.status === 'Pre-Job Sent'
            ? {
                ...c,
                status: 'Pre-Job Confirmed' as StatusName,
                pre_job_confirmed_at: new Date().toISOString(),
                job_number_assigned: c.quote_number.replace(/^Q-/, ''),
                actions_available: ['view', 'view_in_planning'],
              }
            : c,
        ),
      )
    },
    [mode],
  )

  // ── Work Order v4 mutators ────────────────────────────────────────────────

  const acceptCosting = useCallback(
    async (quote: string) => {
      if (mode === 'live') {
        // Reuses the EXISTING /api/calculations/{id}/accept endpoint.
        await liveTransition(quote, 'accept')
        return
      }
      setCostings((prev) =>
        prev.map((c) =>
          c.quote_number === quote && c.status === 'Pending'
            ? {
                ...c,
                status: 'Accepted' as StatusName,
                accepted_at: new Date().toISOString(),
                actions_available: ['view', 'pre_job_card'],
              }
            : c,
        ),
      )
    },
    [mode],
  )

  const signoffPreJob = useCallback(
    async (quote: string, role: 'sales' | 'production', attestation: string, by: string) => {
      if (mode === 'live') {
        await liveTransition(quote, 'pre-job-signoff', { role, attestation })
        return
      }
      setCostings((prev) =>
        prev.map((c) => {
          if (c.quote_number !== quote || c.status !== 'Pre-Job Sent') return c
          const now = new Date().toISOString()
          const next: Costing = {
            ...c,
            ...(role === 'sales'
              ? {
                  pre_job_signoff_sales_at: now,
                  pre_job_signoff_sales_by: by,
                  pre_job_signoff_sales_attestation: attestation,
                }
              : {
                  pre_job_signoff_production_at: now,
                  pre_job_signoff_production_by: by,
                  pre_job_signoff_production_attestation: attestation,
                }),
          }
          // Auto-progress to Planning when both signoffs are in (transient
          // pre_job_confirmed in the same in-memory transaction).
          if (next.pre_job_signoff_sales_at && next.pre_job_signoff_production_at) {
            next.status = 'Planning'
            next.pre_job_confirmed_at = now
            next.job_number_assigned = c.quote_number.replace(/^Q-/, '')
            next.actions_available = ['view']
          }
          return next
        }),
      )
    },
    [mode],
  )

  const ackPlanning = useCallback(
    async (quote: string, by: string) => {
      if (mode === 'live') {
        await liveTransition(quote, 'planning-ack')
        return
      }
      setCostings((prev) =>
        prev.map((c) =>
          c.quote_number === quote && c.status === 'Planning' && !c.planning_acknowledged_at
            ? {
                ...c,
                planning_acknowledged_at: new Date().toISOString(),
                planning_acknowledged_by: by,
              }
            : c,
        ),
      )
    },
    [mode],
  )

  // Work Order v4.2 — chassis ETA capture + live catalogue fetch.

  const captureChassisEta = useCallback(
    async (quote: string, payload: ChassisEtaPayload, by: string) => {
      if (mode === 'live') {
        await liveTransition(quote, 'chassis-eta', payload)
        return
      }
      setCostings((prev) =>
        prev.map((c) => {
          if (c.quote_number !== quote || c.status !== 'Planning') return c
          const now = new Date().toISOString()
          const merged = {
            ...(c.chassis_data ?? {}),
            ...(payload.chassis_vin       !== undefined ? { chassis_vin: payload.chassis_vin } : {}),
            ...(payload.chassis_model     !== undefined ? { chassis_model: payload.chassis_model } : {}),
            ...(payload.customer_dealer   !== undefined ? { customer_dealer: payload.customer_dealer } : {}),
            ...(payload.tail_lift_code    !== undefined ? { tail_lift_code: payload.tail_lift_code } : {}),
            ...(payload.chassis_inhouse_bom !== undefined ? { chassis_inhouse_bom: payload.chassis_inhouse_bom } : {}),
          }
          return {
            ...c,
            chassis_eta: payload.chassis_eta,
            chassis_eta_captured_at: now,
            chassis_eta_captured_by: by,
            chassis_data: merged,
          }
        }),
      )
    },
    [mode],
  )

  const catalogueCacheRef = useRef<ChassisCatalogue | null>(null)
  const loadChassisCatalogue = useCallback(async (): Promise<ChassisCatalogue | null> => {
    if (catalogueCacheRef.current) return catalogueCacheRef.current
    try {
      const res = await fetch(`${API_BASE}/api/chassis/catalogue`, {
        credentials: 'include',
        signal: AbortSignal.timeout(2000),
      })
      if (!res.ok) return null
      const data = (await res.json()) as ChassisCatalogue
      catalogueCacheRef.current = data
      return data
    } catch {
      return null
    }
  }, [])

  // Work Order v4.3 — mark chassis received. Pass receivedAt=null to un-tick.
  const markChassisReceived = useCallback(
    async (quote: string, receivedAt: string | null, by: string) => {
      if (mode === 'live') {
        await liveTransition(quote, 'chassis-received', receivedAt === null
          ? { received: false }
          : { received: true, received_at: receivedAt })
        return
      }
      setCostings((prev) =>
        prev.map((c) =>
          c.quote_number === quote
            ? {
                ...c,
                chassis_received_at: receivedAt,
                chassis_received_by: receivedAt ? by : null,
              }
            : c,
        ),
      )
    },
    [mode],
  )

  const scheduleRepairPhases = useCallback(
    async (quote: string, phases: RepairPhaseInsertion[]) => {
      if (mode === 'live') {
        await liveTransition(quote, 'schedule-repair', {
          phases: phases.map((p) => ({
            phase: p.phase,
            bay_id: p.bay_assignment,
            estimated_hours: p.estimated_hours,
          })),
        })
        return
      }
      setCostings((prev) =>
        prev.map((c) =>
          c.quote_number === quote
            ? {
                ...c,
                repair_phases: phases.map((p) => ({
                  phase: p.phase,
                  bay_id: p.bay_assignment,
                  estimated_hours: p.estimated_hours,
                })),
              }
            : c,
        ),
      )
    },
    [mode],
  )

  const value: CostingsValue = {
    mode,
    costings,
    statusCounts,
    refresh: load,
    firePreJobCard,
    confirmPreJobCard,
    scheduleRepairPhases,
    acceptCosting,
    signoffPreJob,
    ackPlanning,
    captureChassisEta,
    loadChassisCatalogue,
    markChassisReceived,
  }

  return <CostingsContext.Provider value={value}>{children}</CostingsContext.Provider>
}

export function useCostings(): CostingsValue {
  const ctx = useContext(CostingsContext)
  if (!ctx) throw new Error('useCostings must be used within CostingsProvider')
  return ctx
}
