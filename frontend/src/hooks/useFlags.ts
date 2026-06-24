// WO v4.36b §3.2 — visual-integrity flag data hooks. Thin read-only fetchers over
// /api/visual-integrity/flags/* (the §3.1 derivation service). Each consumer fetches only the slice
// it needs (TopNav → summary; Chassis page → chassis map; Planning → bay map; etc.) — no shared
// provider, so no Layout.tsx/App.tsx contention with CA4's FeedbackWidget.
import { useCallback, useEffect, useState } from 'react'

import { apiGet } from '../lib/api'

export type FlagSeverity = 'sky' | 'amber' | 'red'

/** One flag instance as resolved by the backend (severity already accounts for the per-flag §0.6 bands). */
export interface Flag {
  flag: string
  severity: FlagSeverity
  age_days: number | null
  label: string
  remediation: string
  group: string
  domain: 'chassis' | 'jobs' | 'bays'
  pulse: boolean
}

export interface FlagSummary {
  total: number
  entities: number
  by_flag: Record<string, number>
  by_group: Record<string, number>
  by_severity: Record<FlagSeverity, number>
}

type FlagDomain = 'chassis' | 'jobs' | 'bays'
const ID_KEY: Record<FlagDomain, string> = { chassis: 'chassis_id', jobs: 'job_id', bays: 'bay_id' }

/** Aggregate counts for the nav badge + Health Check dashboard. */
export function useFlagSummary() {
  const [summary, setSummary] = useState<FlagSummary | null>(null)
  const [loading, setLoading] = useState(true)
  const refresh = useCallback(() => {
    setLoading(true)
    apiGet<FlagSummary>('/api/visual-integrity/flags/summary')
      .then(setSummary)
      .catch(() => setSummary(null))      // flags are advisory — a fetch failure must never break a screen
      .finally(() => setLoading(false))
  }, [])
  useEffect(() => { refresh() }, [refresh])
  return { summary, loading, refresh }
}

/** {entityId → Flag[]} for a domain's drill-through list, joined client-side onto the existing rows.
 *  `flag` filters server-side to one enum (drill-through). Failures resolve to an empty map (advisory). */
export function useFlaggedMap(domain: FlagDomain, flag?: string) {
  const [map, setMap] = useState<Map<number, Flag[]>>(new Map())
  const [loading, setLoading] = useState(true)
  const refresh = useCallback(() => {
    setLoading(true)
    const q = flag ? `?flag=${encodeURIComponent(flag)}` : ''
    apiGet<Array<Record<string, unknown>>>(`/api/visual-integrity/flags/${domain}${q}`)
      .then((rows) => {
        const m = new Map<number, Flag[]>()
        for (const r of rows) {
          const id = r[ID_KEY[domain]] as number
          m.set(id, (r.flags as Flag[]) ?? [])
        }
        setMap(m)
      })
      .catch(() => setMap(new Map()))
      .finally(() => setLoading(false))
  }, [domain, flag])
  useEffect(() => { refresh() }, [refresh])
  return { map, loading, refresh }
}

export const useFlaggedChassis = (flag?: string) => useFlaggedMap('chassis', flag)
export const useFlaggedJobs = (flag?: string) => useFlaggedMap('jobs', flag)
export const useFlaggedBays = (flag?: string) => useFlaggedMap('bays', flag)

/** Static flag-registry metadata (label, domain, group, remediation, age bands) — for the Health Check
 *  dashboard grouping + drill-through routing without hard-coding the catalog on the frontend. */
export interface FlagCatalogEntry {
  flag: string
  domain: FlagDomain
  group: string
  label: string
  remediation: string
  pulse: boolean
  bands: Array<{ gt_days: number; severity: FlagSeverity }>
}

export function useFlagCatalog() {
  const [catalog, setCatalog] = useState<Record<string, FlagCatalogEntry>>({})
  const [loading, setLoading] = useState(true)
  useEffect(() => {
    apiGet<Record<string, FlagCatalogEntry>>('/api/visual-integrity/flags/catalog')
      .then(setCatalog)
      .catch(() => setCatalog({}))
      .finally(() => setLoading(false))
  }, [])
  return { catalog, loading }
}
