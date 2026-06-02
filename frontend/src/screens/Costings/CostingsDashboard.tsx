import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import {
  Search,
  Plus,
  Eye,
  Send,
  Pencil,
  Wrench,
  Truck,
  Filter,
  RadioTower,
  Database,
  ThumbsUp,
} from 'lucide-react'
import { useCostings } from '../../store/CostingsContext'
import { useAppData } from '../../store/AppDataContext'
import { ALL_STATUSES, type Costing, type StatusName } from '../../data/costingsData'
import { Tooltip } from '../../components/ui/Tooltip'
import { Card } from '../../components/ui/primitives'
import { STATUS_STYLES, StatusPillCosting, statusFilterTooltipKey } from './statusPalette'
import { PreJobCardModal } from './PreJobCardModal'
import { RepairPhasePanel } from './RepairPhasePanel'
import { AcceptModal } from './AcceptModal'
import { BottleneckIndicator } from './BottleneckIndicator'
import { zarShort, dmy } from '../../lib/format'

export function CostingsDashboard() {
  const nav = useNavigate()
  const { mode, costings, statusCounts, firePreJobCard, scheduleRepairPhases, acceptCosting } = useCostings()
  const { profile, hasPermission } = useAppData()
  const [filter, setFilter] = useState<Set<StatusName>>(new Set())
  const [q, setQ] = useState('')
  // Default scope is "mine" so the demo opens on Burt's own work, but flip to
  // "all" automatically once Live mode confirms — the FastAPI session user (the
  // autologin 'admin' user) rarely matches the React profile's rep code, so
  // "mine" would filter the live list to nothing.
  const [scope, setScope] = useState<'mine' | 'all'>('mine')
  const [userPickedScope, setUserPickedScope] = useState(false)
  useEffect(() => {
    if (mode === 'live' && !userPickedScope) setScope('all')
  }, [mode, userPickedScope])
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [preJobTarget, setPreJobTarget] = useState<Costing | null>(null)
  const [repairTarget, setRepairTarget] = useState<Costing | null>(null)
  const [acceptTarget, setAcceptTarget] = useState<Costing | null>(null)

  const canViewAll = hasPermission('costings.view_all')
  const canCreate = hasPermission('costings.create')
  const canPreJob = hasPermission('costings.pre_job_card')
  const canAccept = hasPermission('costings.accept')

  const filtered = useMemo(() => {
    const ql = q.trim().toLowerCase()
    return costings.filter((c) => {
      // "My costings" only makes sense in Mock mode for the Sales Rep demo
      // profile (Burt). In Live mode the data's created_by is the FastAPI
      // username (e.g. 'admin'), unrelated to the React profile — the auto
      // scope-flip above sets scope='all' on first Live load so nothing's
      // hidden, but if the user manually picks "Mine" we honour it.
      if (scope === 'mine' && mode === 'mock' && profile.id === 'rep_burt' && c.created_by !== 'BURT') {
        return false
      }
      if (filter.size && !filter.has(c.status)) return false
      if (!ql) return true
      return (
        c.customer_name.toLowerCase().includes(ql) ||
        c.quote_number.toLowerCase().includes(ql) ||
        c.body_type.toLowerCase().includes(ql)
      )
    })
  }, [costings, q, filter, scope, profile, mode])

  function toggleStatus(s: StatusName) {
    setFilter((prev) => {
      const next = new Set(prev)
      next.has(s) ? next.delete(s) : next.add(s)
      return next
    })
  }

  function toggleSelect(qn: string) {
    setSelected((prev) => {
      const next = new Set(prev)
      next.has(qn) ? next.delete(qn) : next.add(qn)
      return next
    })
  }

  const checkedRows = filtered.filter((c) => selected.has(c.quote_number))
  const bulkPreJobReady =
    checkedRows.length > 0 && checkedRows.every((c) => c.status === 'Accepted')

  async function handleBulkPreJob() {
    for (const c of checkedRows) await firePreJobCard(c.quote_number)
    setSelected(new Set())
  }

  return (
    <div className="p-4">
      {/* Header */}
      <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
        <Tooltip k="costings_dashboard.header_title">
          <h1 className="flex items-center gap-2 text-xl font-bold text-body">
            Costings
            <ModePill mode={mode} />
          </h1>
        </Tooltip>
        <div className="flex flex-wrap items-center gap-2">
          {canViewAll && (
            <div className="flex overflow-hidden rounded-md border border-line bg-white text-xs">
              <Tooltip k="costings_dashboard.filter_my_costings">
                <button
                  onClick={() => { setScope('mine'); setUserPickedScope(true) }}
                  className={`flex items-center gap-1 px-3 py-1.5 ${
                    scope === 'mine' ? 'bg-primary text-white' : 'text-body hover:bg-surface-alt'
                  }`}
                >
                  <Filter size={13} /> My costings
                </button>
              </Tooltip>
              <button
                onClick={() => { setScope('all'); setUserPickedScope(true) }}
                className={`px-3 py-1.5 ${scope === 'all' ? 'bg-primary text-white' : 'text-body hover:bg-surface-alt'}`}
              >
                All
              </button>
            </div>
          )}
          {canCreate && (
            <Tooltip k="costings_dashboard.create_new_costing_button">
              <Link
                to="/costings/new"
                className="flex items-center gap-1 rounded-md bg-primary px-3 py-1.5 text-sm font-semibold text-white hover:bg-primary-dark"
              >
                <Plus size={15} /> New Costing
              </Link>
            </Tooltip>
          )}
        </div>
      </div>

      {/* Status filter chips */}
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <button
          onClick={() => setFilter(new Set())}
          className={`flex items-center gap-1 rounded-full border px-3 py-1 text-xs font-semibold ${
            filter.size === 0
              ? 'border-primary bg-primary text-white'
              : 'border-line bg-white text-body hover:bg-surface-alt'
          }`}
        >
          All
          <span className={`rounded-full px-1.5 py-0.5 text-[10px] ${filter.size === 0 ? 'bg-white/20' : 'bg-surface-alt text-muted'}`}>
            {statusCounts.Total}
          </span>
        </button>
        {ALL_STATUSES.map((s) => {
          const on = filter.has(s)
          const style = STATUS_STYLES[s]
          return (
            <Tooltip key={s} k={statusFilterTooltipKey(s)}>
              <button
                onClick={() => toggleStatus(s)}
                className={`flex items-center gap-1 rounded-full border px-3 py-1 text-xs font-semibold transition ${
                  on
                    ? `${style.pillBg} ${style.pillText} ${style.border}`
                    : 'border-line bg-white text-body hover:bg-surface-alt'
                }`}
              >
                <span className={`h-2 w-2 rounded-full ${on ? 'bg-white/80' : style.pillBg}`} />
                {s}
                <span className={`rounded-full px-1.5 py-0.5 text-[10px] ${on ? 'bg-white/20' : 'bg-surface-alt text-muted'}`}>
                  {statusCounts[s] ?? 0}
                </span>
              </button>
            </Tooltip>
          )
        })}
      </div>

      {/* Search */}
      <Tooltip k="costings_dashboard.search_box">
        <div className="mb-3 flex items-center gap-2 rounded-md border border-line bg-white px-3 py-2">
          <Search size={16} className="text-muted" />
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search customer, quote number, body type…"
            className="flex-1 text-sm outline-none"
          />
          {q && (
            <button onClick={() => setQ('')} className="text-xs text-muted hover:text-body">
              clear
            </button>
          )}
        </div>
      </Tooltip>

      {/* Bulk-action bar */}
      {selected.size > 0 && (
        <div className="mb-3 flex items-center gap-2 rounded-md border border-primary bg-primary-light px-3 py-2 text-sm">
          <span className="font-semibold text-primary">{selected.size} selected</span>
          <button
            onClick={handleBulkPreJob}
            disabled={!bulkPreJobReady}
            className="ml-auto flex items-center gap-1 rounded-md bg-primary px-3 py-1.5 text-xs font-semibold text-white hover:bg-primary-dark disabled:opacity-40"
          >
            <Send size={13} /> Send Pre-Job Cards ({selected.size})
          </button>
          <button onClick={() => setSelected(new Set())} className="text-xs text-primary hover:underline">
            Clear
          </button>
        </div>
      )}

      {/* Table */}
      <Card className="p-0">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-primary text-left text-white">
              <tr>
                <th className="px-2 py-2"></th>
                <Tooltip k="costings_dashboard.column_quote_number"><th className="px-3 py-2 font-semibold">Quote #</th></Tooltip>
                <Tooltip k="costings_dashboard.column_customer"><th className="px-3 py-2 font-semibold">Customer</th></Tooltip>
                <Tooltip k="costings_dashboard.column_body_type"><th className="px-3 py-2 font-semibold">Body type</th></Tooltip>
                <Tooltip k="costings_dashboard.column_extras_count"><th className="px-3 py-2 text-center font-semibold">Extras</th></Tooltip>
                <Tooltip k="costings_dashboard.column_created_by"><th className="px-3 py-2 font-semibold">Rep</th></Tooltip>
                <Tooltip k="costings_dashboard.column_created_date"><th className="px-3 py-2 font-semibold">Created</th></Tooltip>
                <th className="px-3 py-2 text-right font-semibold">Selling</th>
                <Tooltip k="costings_dashboard.column_status_badge"><th className="px-3 py-2 font-semibold">Status</th></Tooltip>
                <th className="px-3 py-2 font-semibold">Actions</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((c, i) => (
                <tr
                  key={c.quote_number}
                  className={`cursor-pointer border-b border-line hover:bg-primary-light/40 ${
                    i % 2 ? 'bg-surface-alt' : 'bg-white'
                  }`}
                  onClick={() => nav(`/costings/${encodeURIComponent(c.quote_number)}`)}
                >
                  <td className="px-2 py-2" onClick={(e) => e.stopPropagation()}>
                    <input
                      type="checkbox"
                      checked={selected.has(c.quote_number)}
                      onChange={() => toggleSelect(c.quote_number)}
                      className="h-4 w-4 cursor-pointer"
                    />
                  </td>
                  <td className="px-3 py-2 font-mono text-xs font-semibold">{c.quote_number}</td>
                  <td className="px-3 py-2">{c.customer_name}</td>
                  <td className="px-3 py-2">
                    <span>{c.body_type.replace(/\s*\(REPAIR\)$/i, '')}</span>
                    {c.requires_chassis && (
                      <span title="Requires chassis" className="ml-1 inline-flex">
                        <Truck size={12} className="text-muted" />
                      </span>
                    )}
                    {c.quote_type === 'Repair' && (
                      <span className="ml-1 inline-flex items-center rounded bg-[#7E22CE]/10 px-1.5 py-0.5 text-[10px] font-bold uppercase text-[#7E22CE]">
                        Repair
                      </span>
                    )}
                  </td>
                  <td className="px-3 py-2 text-center">
                    {c.extras_count > 0 ? (
                      <span className="inline-flex h-5 w-5 items-center justify-center rounded-full bg-surface-alt text-[11px] font-bold text-muted">
                        {c.extras_count}
                      </span>
                    ) : (
                      <span className="text-muted">—</span>
                    )}
                  </td>
                  <td className="px-3 py-2 font-mono text-xs">{c.created_by}</td>
                  <td className="px-3 py-2 text-xs text-muted">{dmy(c.created_at)}</td>
                  <td className="px-3 py-2 text-right tabular-nums">{zarShort(c.selling_zar)}</td>
                  <td className="px-3 py-2">
                    <StatusPillCosting
                      status={c.status}
                      pulsing={c.status === 'Planning' && !c.planning_acknowledged_at}
                    />
                    {c.status === 'Pre-Job Sent' && (
                      <BottleneckIndicator
                        salesAt={c.pre_job_signoff_sales_at ?? null}
                        productionAt={c.pre_job_signoff_production_at ?? null}
                      />
                    )}
                  </td>
                  <td className="px-3 py-2" onClick={(e) => e.stopPropagation()}>
                    <div className="flex flex-wrap items-center gap-1">
                      <Tooltip k="costings_dashboard.view_button">
                        <Link
                          to={`/costings/${encodeURIComponent(c.quote_number)}`}
                          className="flex items-center gap-1 rounded-md border border-line bg-white px-2 py-1 text-xs font-semibold text-primary hover:bg-primary-light"
                        >
                          <Eye size={12} /> View
                        </Link>
                      </Tooltip>
                      {canAccept && c.status === 'Pending' && (
                        <Tooltip k="costings_dashboard.accept_button">
                          <button
                            onClick={() => setAcceptTarget(c)}
                            className="flex items-center gap-1 rounded-md bg-[#2563EB] px-2 py-1 text-xs font-semibold text-white hover:opacity-90"
                          >
                            <ThumbsUp size={12} /> Accept
                          </button>
                        </Tooltip>
                      )}
                      {canPreJob && c.status === 'Accepted' && (
                        <Tooltip k="costings_dashboard.pre_job_card_button">
                          <button
                            onClick={() => setPreJobTarget(c)}
                            className="flex items-center gap-1 rounded-md bg-status-amber px-2 py-1 text-xs font-semibold text-white hover:opacity-90"
                          >
                            <Send size={12} /> Pre-Job Card
                          </button>
                        </Tooltip>
                      )}
                      {c.status === 'Pending' && c.created_by === profile.id.replace('rep_', '').toUpperCase() && (
                        <button className="flex items-center gap-1 rounded-md border border-line bg-white px-2 py-1 text-xs font-semibold text-body hover:bg-surface-alt">
                          <Pencil size={12} /> Edit
                        </button>
                      )}
                      {c.status === 'Repair' && (
                        <button
                          onClick={() => setRepairTarget(c)}
                          className="flex items-center gap-1 rounded-md bg-[#7E22CE] px-2 py-1 text-xs font-semibold text-white hover:opacity-90"
                        >
                          <Wrench size={12} /> Schedule
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
              {filtered.length === 0 && (
                <tr>
                  <td colSpan={10} className="px-4 py-12 text-center text-sm text-muted">
                    No costings match the current filters.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </Card>

      <PreJobCardModal
        costing={preJobTarget}
        onClose={() => setPreJobTarget(null)}
        onConfirm={async (c) => {
          await firePreJobCard(c.quote_number)
          setPreJobTarget(null)
        }}
      />
      <RepairPhasePanel
        costing={repairTarget}
        onClose={() => setRepairTarget(null)}
        onSchedule={async (c, phases) => {
          await scheduleRepairPhases(c.quote_number, phases)
          setRepairTarget(null)
        }}
      />
      <AcceptModal
        costing={acceptTarget}
        onClose={() => setAcceptTarget(null)}
        onConfirm={async (c) => {
          await acceptCosting(c.quote_number)
          setAcceptTarget(null)
        }}
      />
    </div>
  )
}

function ModePill({ mode }: { mode: 'live' | 'mock' | 'loading' }) {
  if (mode === 'loading') {
    return (
      <span className="rounded-full bg-surface-alt px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide text-muted">
        Loading…
      </span>
    )
  }
  const live = mode === 'live'
  return (
    <span
      title={live ? 'Live data from /api/calculations' : 'Bundled mock data (FastAPI app unreachable)'}
      className={`flex items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide ${
        live ? 'bg-status-green/15 text-status-green' : 'bg-surface-alt text-muted'
      }`}
    >
      {live ? <RadioTower size={11} /> : <Database size={11} />}
      {live ? 'Live' : 'Mock'}
    </span>
  )
}
