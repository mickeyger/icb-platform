// useProductionDashboard.ts — WO v4.32 §3.2. Loads the wired Production Dashboard state:
// real KPI values (/api/production-jobs/kpis — compute_production_kpis, §0.6 defaults) + the
// 5-bay utilisation (/api/chassis-records/bays/assembly, §0.4 extension). Lean apiGet + the
// useBayModel live/mock fallback idiom; the §0.3 30s tick lives here so the screen stays dumb.
import { useCallback, useEffect, useRef, useState } from 'react'
import { apiGet } from '../../lib/api'
import type { Bay } from '../Chassis/types'

export interface ProductionKpis {
  units_in_production: number
  delayed: { total: number; start_slipped: number; chassis_slipped: number }
  critical_chassis: number
  bottleneck: { job_id: number; job_number: string | null; status: string; days_in_stage: number } | null
  completed_today: number
  target_today: number | null            // §0.6 — null = no target seeded → render no target line
  open_rework: number
  as_of: string
}

/** v4.31 Bay + the v4.32 §0.4 utilisation extension (additive — defined locally so the
 *  v4.31 Chassis/types.ts surface stays untouched). */
export type UtilisedBay = Bay & {
  occupied: boolean
  occupant_chassis_id?: number | null
  occupant_vin?: string | null
  occupant_customer?: string | null
  occupant_job_id?: number | null
  occupant_job_number?: string | null
  since?: string | null
}

const REFRESH_MS = 30_000               // §0.3 lock: keep the 30s pattern, no faster polling

export interface ProductionDashboardState {
  mode: 'loading' | 'live' | 'mock'
  kpis: ProductionKpis | null
  bays: UtilisedBay[]
  refreshedAt: Date | null
  refresh: () => Promise<void>
}

export function useProductionDashboard(): ProductionDashboardState {
  const [mode, setMode] = useState<ProductionDashboardState['mode']>('loading')
  const [kpis, setKpis] = useState<ProductionKpis | null>(null)
  const [bays, setBays] = useState<UtilisedBay[]>([])
  const [refreshedAt, setRefreshedAt] = useState<Date | null>(null)
  const timer = useRef<ReturnType<typeof setInterval> | null>(null)

  const refresh = useCallback(async () => {
    try {
      const [k, b] = await Promise.all([
        apiGet<ProductionKpis>('/api/production-jobs/kpis'),
        apiGet<UtilisedBay[]>('/api/chassis-records/bays/assembly'),
      ])
      setKpis(k)
      setBays(b)
      setRefreshedAt(new Date())
      setMode('live')
    } catch {
      setKpis(null)
      setBays([])
      setMode('mock')                    // API unreachable → offline/demo (the BayModelLanes rule)
    }
  }, [])

  useEffect(() => {
    void refresh()
    timer.current = setInterval(() => void refresh(), REFRESH_MS)
    return () => {
      if (timer.current) clearInterval(timer.current)
    }
  }, [refresh])

  return { mode, kpis, bays, refreshedAt, refresh }
}
