/** WO v4.33.1 §3.1 — admin "Outstanding Pre-Job Sign-offs" nav-aid. Lists prejob_cards in
 * 'sent_for_check' (awaiting sign-off) with per-role status + age + filter chips, and deep-links to
 * the existing /prejob/{id}/signoff/{role} pages (admin can act on either via wildcard perms).
 * Read-only — no mutations here; the actual sign-off happens on the linked page. */
import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { ClipboardCheck } from 'lucide-react'

import { apiGet, handleApiError } from '../../lib/api'
import { useToast } from '../../components/ui/toast'
import { Card } from '../../components/ui/primitives'
import { Skeleton, EmptyState } from '../../components/ui/feedback'
import { dmy } from '../../lib/format'

interface Outstanding {
  id: number
  quote_number: string | null
  customer_name: string | null
  sent_for_check_at: string | null
  sales_rep_username: string | null
  sales_rep_signoff_at: string | null
  planner_username: string | null
  planner_signoff_at: string | null
}

type Filter = 'all' | 'sales' | 'planner' | 'both'
const CHIPS: { key: Filter; label: string }[] = [
  { key: 'all', label: 'All' },
  { key: 'sales', label: 'Sales pending' },
  { key: 'planner', label: 'Planner pending' },
  { key: 'both', label: 'Both pending' },
]

function daysWaiting(iso: string | null): number | null {
  if (!iso) return null
  return Math.max(0, Math.floor((Date.now() - new Date(iso).getTime()) / 86_400_000))
}

function SignStatus({ at, who }: { at: string | null; who: string | null }) {
  if (at) return <span className="text-status-green">✓ signed {dmy(at)}</span>
  return <span className="text-status-amber">pending{who ? ` · ${who}` : ''}</span>
}

export function OutstandingPrejobSignoffsPage() {
  const toast = useToast()
  const [rows, setRows] = useState<Outstanding[]>([])
  const [loading, setLoading] = useState(true)
  const [filter, setFilter] = useState<Filter>('all')

  useEffect(() => {
    let live = true
    apiGet<Outstanding[]>('/api/prejob-cards/outstanding')
      .then((r) => { if (live) setRows(r) })
      .catch((e) => handleApiError(e, toast.push))
      .finally(() => { if (live) setLoading(false) })
    return () => { live = false }
  }, [toast])

  const counts = useMemo(() => ({
    all: rows.length,
    sales: rows.filter((r) => !r.sales_rep_signoff_at).length,
    planner: rows.filter((r) => !r.planner_signoff_at).length,
    both: rows.filter((r) => !r.sales_rep_signoff_at && !r.planner_signoff_at).length,
  }), [rows])

  const filtered = useMemo(() => rows.filter((r) => {
    const salesPending = !r.sales_rep_signoff_at
    const plannerPending = !r.planner_signoff_at
    if (filter === 'sales') return salesPending
    if (filter === 'planner') return plannerPending
    if (filter === 'both') return salesPending && plannerPending
    return true
  }), [rows, filter])

  return (
    <div data-testid="outstanding-signoffs">
      <h2 className="mb-1 flex items-center gap-2 text-lg font-bold text-body">
        <ClipboardCheck size={20} /> Outstanding Pre-Job sign-offs
        <span className="text-sm font-normal text-muted">({filtered.length})</span>
      </h2>
      <p className="mb-3 text-xs text-muted">
        Cards awaiting sign-off (sent for check). Open either role&rsquo;s sign-off page directly —
        admin can sign on behalf of either.
      </p>

      <div className="mb-3 flex flex-wrap gap-1.5" data-testid="outstanding-filters">
        {CHIPS.map((c) => (
          <button key={c.key} data-testid={`outstanding-filter-${c.key}`} onClick={() => setFilter(c.key)}
            className={`rounded-full px-3 py-1 text-xs font-semibold ${filter === c.key ? 'bg-primary text-white' : 'bg-surface-alt text-muted hover:text-body'}`}>
            {c.label} <span className="tabular-nums opacity-70">{counts[c.key]}</span>
          </button>
        ))}
      </div>

      {loading ? <Skeleton rows={6} /> : filtered.length === 0 ? (
        <EmptyState title="Nothing outstanding" hint="No Pre-Job Cards are awaiting sign-off for this filter." />
      ) : (
        <Card className="p-0">
          <div className="overflow-x-auto">
            <table className="w-full text-sm" data-testid="outstanding-table">
              <thead className="bg-primary text-left text-white">
                <tr>
                  <th className="px-3 py-2 font-semibold">Costing</th>
                  <th className="px-3 py-2 font-semibold">Customer</th>
                  <th className="px-3 py-2 font-semibold">Submitted</th>
                  <th className="px-3 py-2 font-semibold">Sales Rep</th>
                  <th className="px-3 py-2 font-semibold">Planner</th>
                  <th className="px-3 py-2 text-center font-semibold">Days</th>
                  <th className="px-3 py-2 font-semibold">Open sign-off</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((r, i) => (
                  <tr key={r.id} data-testid="outstanding-row" data-id={r.id}
                    className={`border-b border-line ${i % 2 ? 'bg-surface-alt' : 'bg-white'}`}>
                    <td className="px-3 py-2 font-mono text-xs font-semibold">{r.quote_number ?? '—'}</td>
                    <td className="px-3 py-2">{r.customer_name ?? '—'}</td>
                    <td className="px-3 py-2 text-xs text-muted">{r.sent_for_check_at ? dmy(r.sent_for_check_at) : '—'}</td>
                    <td className="px-3 py-2 text-xs"><SignStatus at={r.sales_rep_signoff_at} who={r.sales_rep_username} /></td>
                    <td className="px-3 py-2 text-xs"><SignStatus at={r.planner_signoff_at} who={r.planner_username} /></td>
                    <td className="px-3 py-2 text-center tabular-nums">{daysWaiting(r.sent_for_check_at) ?? '—'}</td>
                    <td className="px-3 py-2">
                      <div className="flex gap-1.5">
                        <Link data-testid={`outstanding-open-sales-${r.id}`} to={`/prejob/${r.id}/signoff/sales`}
                          className="rounded border border-line px-2 py-1 text-xs font-semibold text-primary hover:bg-primary-light">Sales</Link>
                        <Link data-testid={`outstanding-open-planner-${r.id}`} to={`/prejob/${r.id}/signoff/planner`}
                          className="rounded border border-line px-2 py-1 text-xs font-semibold text-primary hover:bg-primary-light">Planner</Link>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}
    </div>
  )
}
