/** WO v4.28 §0.8 — chassis list. Read-path: lists chassis_records (search by VIN / customer /
 * job), click a row → detail. Tablet-friendly rows. */
import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Truck, Search } from 'lucide-react'

import { apiGet, handleApiError } from '../../lib/api'
import { useToast } from '../../components/ui/toast'
import { Card } from '../../components/ui/primitives'
import { Skeleton, EmptyState } from '../../components/ui/feedback'
import { CHASSIS_STATUS_STYLE, type ChassisRecord } from './types'

function StatusPill({ status }: { status: string }) {
  const cls = CHASSIS_STATUS_STYLE[status] ?? 'bg-surface-alt text-muted'
  return (
    <span className={`inline-block rounded-full px-2 py-0.5 text-[11px] font-semibold ${cls}`}>
      {status.replace(/_/g, ' ')}
    </span>
  )
}

export function ChassisList() {
  const nav = useNavigate()
  const toast = useToast()
  const [rows, setRows] = useState<ChassisRecord[]>([])
  const [loading, setLoading] = useState(true)
  const [q, setQ] = useState('')

  useEffect(() => {
    let live = true
    setLoading(true)
    apiGet<ChassisRecord[]>('/api/chassis-records?limit=200')
      .then((r) => { if (live) setRows(r) })
      .catch((e) => handleApiError(e, toast.push))
      .finally(() => { if (live) setLoading(false) })
    return () => { live = false }
  }, [toast])

  const filtered = useMemo(() => {
    const ql = q.trim().toLowerCase()
    if (!ql) return rows
    return rows.filter((r) =>
      (r.vin || '').toLowerCase().includes(ql) ||
      (r.customer_name || '').toLowerCase().includes(ql) ||
      (r.job_number || '').toLowerCase().includes(ql))
  }, [rows, q])

  return (
    <div className="p-4" data-testid="chassis-list">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
        <h1 className="flex items-center gap-2 text-xl font-bold text-body">
          <Truck size={22} /> Chassis
          <span className="text-sm font-normal text-muted">({filtered.length})</span>
        </h1>
      </div>

      <div className="mb-3 flex items-center gap-2 rounded-md border border-line bg-white px-3 py-2">
        <Search size={16} className="text-muted" />
        <input
          data-testid="chassis-search"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Search VIN, customer, or job number…"
          className="flex-1 text-sm outline-none"
        />
        {q && <button onClick={() => setQ('')} className="text-xs text-muted hover:text-body">clear</button>}
      </div>

      {loading ? (
        <Skeleton rows={8} />
      ) : filtered.length === 0 ? (
        <EmptyState title="No chassis found" hint="No chassis records match the current search." />
      ) : (
        <Card className="p-0">
          <div className="overflow-x-auto">
            <table className="w-full text-sm" data-testid="chassis-table">
              <thead className="bg-primary text-left text-white">
                <tr>
                  <th className="px-3 py-2 font-semibold">VIN</th>
                  <th className="px-3 py-2 font-semibold">Customer</th>
                  <th className="px-3 py-2 font-semibold">Make / Model</th>
                  <th className="px-3 py-2 font-semibold">Job</th>
                  <th className="px-3 py-2 text-center font-semibold">Cycles</th>
                  <th className="px-3 py-2 font-semibold">Last activity</th>
                  <th className="px-3 py-2 font-semibold">Status</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((r, i) => (
                  <tr
                    key={r.id}
                    data-testid="chassis-row"
                    data-id={r.id}
                    onClick={() => nav(`/chassis/${r.id}`)}
                    className={`cursor-pointer border-b border-line hover:bg-primary-light/40 ${i % 2 ? 'bg-surface-alt' : 'bg-white'}`}
                  >
                    <td className="px-3 py-2 font-mono text-xs font-semibold">{r.vin}</td>
                    <td className="px-3 py-2">{r.customer_name || '—'}</td>
                    <td className="px-3 py-2">{[r.make, r.model].filter(Boolean).join(' ') || '—'}</td>
                    <td className="px-3 py-2 font-mono text-xs">{r.job_number || '—'}</td>
                    <td className="px-3 py-2 text-center tabular-nums">{r.event_count}</td>
                    <td className="px-3 py-2 text-xs text-muted">{r.latest_event_date || '—'}</td>
                    <td className="px-3 py-2"><StatusPill status={r.status} /></td>
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
