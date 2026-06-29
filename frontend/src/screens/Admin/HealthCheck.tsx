/** WO v4.36b §3.3 — Health Check admin dashboard (/admin/health-check). The consolidation surface the
 * nav "N attention items" badge lands on: every flagged record across the pipeline, aggregated by domain
 * group (Chassis / Jobs / Bays / Sign-offs / Stale Reviews), with click-through to the affected records.
 * Pure read — aggregates the §3.1 flag streams (no new data). Admin-gated by AdminModule (isAdmin). */
import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { Activity, ChevronRight } from 'lucide-react'

import { apiGet } from '../../lib/api'
import { Card } from '../../components/ui/primitives'
import { Skeleton, EmptyState } from '../../components/ui/feedback'
import { useFlagSummary, useFlagCatalog, type FlagCatalogEntry, type Flag } from '../../hooks/useFlags'

const GROUP_ORDER = ['Chassis', 'Jobs', 'Bays', 'Sign-offs', 'Stale Reviews']
const SEV_DOT: Record<string, string> = { red: 'bg-status-red', amber: 'bg-status-amber', sky: 'bg-sky-500' }

interface FlaggedRow {
  chassis_id?: number; job_id?: number; bay_id?: number
  vin?: string | null; make?: string | null; model?: string | null
  customer_name?: string | null; job_number?: string | null; chassis_eta?: string | null
  code?: string | null; status?: string; flags: Flag[]
}

/** Worst severity across a flag's age bands → the dot colour in the group card. */
function worstSeverity(e: FlagCatalogEntry): string {
  const sevs = e.bands.map((b) => b.severity)
  return sevs.includes('red') ? 'red' : sevs.includes('amber') ? 'amber' : 'sky'
}

// WO v4.36c.1 — the three Pre-Job sign-off flags drill to the Outstanding Sign-offs admin
// (/admin/prejob-signoffs); the other 'jobs' flags (the ETA pair) stay on the board until the ETA
// destination design lands (v4.36b.4 post-ship). Keyed on the flag so one domain can split targets.
const SIGNOFF_FLAGS = new Set(['prejob_sent_stale', 'signoff_pending_long', 'signoff_role_pending_5days'])

function drillItem(domain: string, flag: string, r: FlaggedRow): { label: string; href: string } {
  if (domain === 'chassis') {
    const mm = [r.make, r.model].filter(Boolean).join(' ') || '—'
    return { label: `${r.vin || '(no VIN)'} · ${r.customer_name || '—'} · ${mm}`, href: `/chassis/${r.chassis_id}` }
  }
  if (domain === 'jobs') {
    return {
      label: `Job ${r.job_number || r.job_id} · ${r.customer_name || '—'}${r.chassis_eta ? ` · ETA ${r.chassis_eta}` : ''}`,
      href: SIGNOFF_FLAGS.has(flag) ? '/admin/prejob-signoffs' : '/planning',
    }
  }
  return { label: `Bay ${r.code || r.bay_id}`, href: '/planning' }
}

export function HealthCheckAdmin() {
  const { summary, loading } = useFlagSummary()
  const { catalog } = useFlagCatalog()
  const [sel, setSel] = useState<{ flag: string; domain: string; label: string } | null>(null)
  const [drill, setDrill] = useState<FlaggedRow[]>([])
  const [drillLoading, setDrillLoading] = useState(false)

  useEffect(() => {
    if (!sel) { setDrill([]); return }
    let live = true
    setDrillLoading(true)
    apiGet<FlaggedRow[]>(`/api/visual-integrity/flags/${sel.domain}?flag=${encodeURIComponent(sel.flag)}`)
      .then((r) => { if (live) setDrill(r) })
      .catch(() => { if (live) setDrill([]) })
      .finally(() => { if (live) setDrillLoading(false) })
    return () => { live = false }
  }, [sel])

  const groups = useMemo(() => {
    const g: Record<string, FlagCatalogEntry[]> = {}
    for (const e of Object.values(catalog)) (g[e.group] ??= []).push(e)
    return g
  }, [catalog])

  if (loading) return <div className="p-1"><Skeleton rows={6} /></div>

  const total = summary?.total ?? 0
  const byFlag = summary?.by_flag ?? {}
  const byGroup = summary?.by_group ?? {}

  return (
    <div data-testid="health-check">
      <h2 className="mb-1 flex items-center gap-2 text-lg font-bold text-body">
        <Activity size={20} /> Health Check
        <span data-testid="health-total"
              className={`rounded-full px-2 py-0.5 text-sm font-bold ${total > 0 ? 'bg-status-red/15 text-status-red' : 'bg-status-green/15 text-status-green'}`}>
          {total} attention item{total === 1 ? '' : 's'}
        </span>
      </h2>
      <p className="mb-3 text-xs text-muted">
        Every flagged record across the pipeline, grouped by domain. Click a flag to drill to the affected records.
      </p>

      <div className="grid grid-cols-[repeat(auto-fit,minmax(220px,1fr))] gap-3">
        {GROUP_ORDER.map((group) => {
          const entries = (groups[group] ?? []).slice()
            .sort((a, b) => (byFlag[b.flag] ?? 0) - (byFlag[a.flag] ?? 0))
          const gcount = byGroup[group] ?? 0
          return (
            <Card key={group} className="p-3">
              <div data-testid={`health-group-${group.replace(/\s+/g, '-').toLowerCase()}`}
                   className="mb-2 flex items-center justify-between">
                <span className="text-sm font-bold text-body">{group}</span>
                <span className={`tabular-nums text-sm font-bold ${gcount > 0 ? 'text-status-red' : 'text-muted'}`}>{gcount}</span>
              </div>
              <div className="space-y-1">
                {entries.length === 0 && <div className="text-xs text-muted">—</div>}
                {entries.map((e) => {
                  const n = byFlag[e.flag] ?? 0
                  return (
                    <button key={e.flag} data-testid={`health-flag-${e.flag}`} disabled={n === 0}
                            onClick={() => setSel({ flag: e.flag, domain: e.domain, label: e.label })}
                            title={e.remediation}
                            className={`flex w-full items-center justify-between rounded px-2 py-1 text-left text-xs ${
                              n === 0 ? 'cursor-default opacity-40' : 'hover:bg-surface-alt'
                            } ${sel?.flag === e.flag ? 'bg-primary-light/50' : ''}`}>
                      <span className="flex items-center gap-1.5">
                        <span className={`h-2 w-2 rounded-full ${SEV_DOT[worstSeverity(e)]}`} />
                        {e.label}
                      </span>
                      <span className="flex items-center gap-1 font-semibold tabular-nums">
                        {n}{n > 0 && <ChevronRight size={12} />}
                      </span>
                    </button>
                  )
                })}
              </div>
            </Card>
          )
        })}
      </div>

      {sel && (
        <Card className="mt-4 p-3">
          <div data-testid="health-drill" className="mb-2 flex items-center justify-between">
            <span className="text-sm font-bold text-body">{sel.label} — affected records</span>
            <button onClick={() => setSel(null)} className="text-xs text-muted hover:text-body">close</button>
          </div>
          {drillLoading ? <Skeleton rows={3} /> : drill.length === 0 ? (
            <EmptyState title="None" hint="No records match this flag." />
          ) : (
            <ul className="divide-y divide-line" data-testid="health-drill-list">
              {drill.map((r, i) => {
                const { label, href } = drillItem(sel.domain, sel.flag, r)
                return (
                  <li key={i} className="flex items-center justify-between py-1.5 text-sm">
                    <span>{label}</span>
                    <Link to={href} data-testid="health-drill-open"
                          className="text-xs font-semibold text-primary hover:underline">open →</Link>
                  </li>
                )
              })}
            </ul>
          )}
        </Card>
      )}
    </div>
  )
}
