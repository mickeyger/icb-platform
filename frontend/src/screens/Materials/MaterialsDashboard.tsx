// MaterialsDashboard.tsx — Screen 1 of the Materials/Buying/Stores suite.
// Buyer's home: items needed against planned starts, urgency-sorted, click-to-raise.
// Hosts the Weekly Material Forecast as a tab (?tab=forecast) per WO v4.11 §3.2.
// Companion: Mockup Brief Addendum v1.5 §3; Work Order v4.11 §3.1.

import { useMemo, useState, type ReactNode } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { Search, Flag } from 'lucide-react'
import {
  useMaterials,
  classifyUrgency,
  type Urgency,
} from '../../store/MaterialsContext'
import { Card } from '../../components/ui/primitives'
import { Tooltip } from '../../components/ui/Tooltip'
import { zarShort, dmy } from '../../lib/format'
import { UrgencyPill } from './components/UrgencyPill'
import { MaterialsKpiStrip } from './components/MaterialsKpiStrip'
import { DiscrepancyDetailDrawer } from './DiscrepancyDetailDrawer'
import { WeeklyMaterialForecast } from './WeeklyMaterialForecast'
import { LastUpdated } from '../../components/ui/feedback'

type UrgencyFilter = 'all' | Urgency

export function MaterialsDashboard() {
  const [params, setParams] = useSearchParams()
  const tab = params.get('tab') === 'forecast' ? 'forecast' : 'dashboard'

  return (
    <div className="p-4">
      <div className="mb-1 text-[11px] text-muted">MES › Materials &amp; Buying</div>
      <h1 className="text-xl font-bold text-body">Materials &amp; Buying Dashboard</h1>
      <p className="mb-3 text-xs text-muted">
        Replaces the MATERIAL PLANNING sheet · auto-computed from BOMs and the Planning Board
      </p>

      {/* Tab strip: Dashboard | Forecast */}
      <div className="mb-4 flex gap-1 border-b border-line">
        <TabButton active={tab === 'dashboard'} onClick={() => setParams({})} k="materials_dashboard.screen_title">
          Dashboard
        </TabButton>
        <TabButton
          active={tab === 'forecast'}
          onClick={() => setParams({ tab: 'forecast' })}
          k="weekly_material_forecast.screen_title"
        >
          Weekly Forecast
        </TabButton>
      </div>

      {tab === 'forecast' ? <WeeklyMaterialForecast /> : <DashboardTab />}
    </div>
  )
}

function TabButton({
  active,
  onClick,
  children,
  k,
}: {
  active: boolean
  onClick: () => void
  children: ReactNode
  k: string
}) {
  return (
    <Tooltip k={k}>
      <button
        onClick={onClick}
        className={`-mb-px border-b-2 px-4 py-2 text-sm font-semibold transition ${
          active
            ? 'border-primary text-primary'
            : 'border-transparent text-muted hover:text-body'
        }`}
      >
        {children}
      </button>
    </Tooltip>
  )
}

function DashboardTab() {
  const { materials, stockPositions, demandLines, poSuggestions, discrepancies, stockCounts, lastUpdated, refresh } =
    useMaterials()
  const navigate = useNavigate()
  const [urgency, setUrgency] = useState<UrgencyFilter>('all')
  const [supplierFilter, setSupplierFilter] = useState<string>('all')
  const [search, setSearch] = useState('')
  const [discDrawer, setDiscDrawer] = useState<string | null>(null)

  // Per-material aggregate row.
  const rows = useMemo(() => {
    return materials.map((m) => {
      const stock = stockPositions.find((s) => s.sap_code === m.sap_code)
      const demand = demandLines.filter((d) => d.sap_code === m.sap_code)
      const totalQty = demand.reduce((a, d) => a + d.qty, 0)
      const nextNeedBy = demand.length ? demand.map((d) => d.need_by).sort()[0] : null
      const free = (stock?.free ?? 0) - totalQty
      const u: Urgency = nextNeedBy ? classifyUrgency(nextNeedBy, m.lead_days) : 'comfortable'
      const hasOpenDiscrepancy = stockCounts.some(
        (c) =>
          c.sap_code === m.sap_code &&
          c.status === 'discrepancy' &&
          discrepancies.some((d) => d.stock_count_id === c.id && !d.resolved_at),
      )
      const daysToNeed = nextNeedBy
        ? Math.ceil((+new Date(nextNeedBy) - Date.now()) / 86_400_000)
        : null
      return { m, stock, totalQty, nextNeedBy, free, urgency: u, hasOpenDiscrepancy, daysToNeed }
    })
  }, [materials, stockPositions, demandLines, stockCounts, discrepancies])

  const counts = useMemo(
    () => ({
      critical: rows.filter((r) => r.urgency === 'critical').length,
      order_now: rows.filter((r) => r.urgency === 'order_now').length,
      comfortable: rows.filter((r) => r.urgency === 'comfortable' || r.urgency === 'advisory').length,
      open_pos: stockPositions.filter((s) => s.open_po_qty > 0).length,
      open_po_value: stockPositions
        .filter((s) => s.open_po_qty > 0)
        .reduce(
          (a, s) => a + s.open_po_qty * (materials.find((m) => m.sap_code === s.sap_code)?.last_price ?? 0),
          0,
        ),
    }),
    [rows, stockPositions, materials],
  )

  const supplierList = useMemo(
    () => Array.from(new Set(materials.map((m) => m.supplier))).sort(),
    [materials],
  )

  const filteredRows = useMemo(() => {
    const order = { critical: 0, order_now: 1, advisory: 2, comfortable: 3 } as const
    const ql = search.trim().toLowerCase()
    return rows
      .filter((r) => {
        if (urgency !== 'all' && r.urgency !== urgency) return false
        if (supplierFilter !== 'all' && r.m.supplier !== supplierFilter) return false
        if (
          ql &&
          !r.m.sap_code.toLowerCase().includes(ql) &&
          !r.m.description.toLowerCase().includes(ql)
        )
          return false
        return true
      })
      .sort((a, b) => {
        if (order[a.urgency] !== order[b.urgency]) return order[a.urgency] - order[b.urgency]
        return (a.nextNeedBy ?? '') < (b.nextNeedBy ?? '') ? -1 : 1
      })
  }, [rows, urgency, supplierFilter, search])

  function handleRaisePR(sapCode: string) {
    const sugg = poSuggestions.find((s) => s.sap_code === sapCode && s.status === 'pending')
    navigate(sugg ? `/materials/suggestions?focus=${sugg.id}` : '/materials/suggestions')
  }

  const FILTERS: { key: UrgencyFilter; label: string; count: number }[] = [
    { key: 'all', label: 'All', count: rows.length },
    { key: 'critical', label: 'Critical', count: counts.critical },
    { key: 'order_now', label: 'Order Now', count: counts.order_now },
    { key: 'comfortable', label: 'Comfortable', count: counts.comfortable },
  ]

  return (
    <>
      <MaterialsKpiStrip
        tiles={[
          {
            label: 'Critical · T-0 to T-10',
            value: counts.critical,
            tone: 'critical',
            sub: 'short for jobs starting < 10 days',
            onClick: () => setUrgency('critical'),
            k: 'materials_dashboard.kpi_critical',
          },
          {
            label: 'Order Now · T-10 to T-15',
            value: counts.order_now,
            tone: 'warn',
            sub: 'raise a PR within 5 days',
            onClick: () => setUrgency('order_now'),
            k: 'materials_dashboard.kpi_order_now',
          },
          {
            label: 'Comfortable · T-15+',
            value: counts.comfortable,
            tone: 'ok',
            sub: 'covered by stock or open POs',
            onClick: () => setUrgency('comfortable'),
            k: 'materials_dashboard.kpi_comfortable',
          },
          {
            label: 'Open POs · value',
            value: counts.open_pos,
            sub: `${zarShort(counts.open_po_value)} committed`,
            k: 'materials_dashboard.kpi_open_pos',
          },
        ]}
      />

      {/* Filter row */}
      <div className="mb-3 flex flex-wrap items-center gap-2">
        {FILTERS.map((f) => {
          const on = urgency === f.key
          return (
            <button
              key={f.key}
              onClick={() => setUrgency(f.key)}
              className={`flex items-center gap-1 rounded-full border px-3 py-1 text-xs font-semibold ${
                on ? 'border-primary bg-primary text-white' : 'border-line bg-white text-body hover:bg-surface-alt'
              }`}
            >
              {f.label}
              <span
                className={`rounded-full px-1.5 py-0.5 text-[10px] ${on ? 'bg-white/20' : 'bg-surface-alt text-muted'}`}
              >
                {f.count}
              </span>
            </button>
          )
        })}
        <div className="ml-auto flex items-center gap-2">
          <Tooltip k="materials_dashboard.filter_supplier">
            <select
              value={supplierFilter}
              onChange={(e) => setSupplierFilter(e.target.value)}
              className="rounded-md border border-line bg-white px-2 py-1.5 text-xs outline-none"
            >
              <option value="all">All suppliers</option>
              {supplierList.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </Tooltip>
          <Tooltip k="materials_dashboard.filter_search">
            <div className="flex items-center gap-1.5 rounded-md border border-line bg-white px-2 py-1.5">
              <Search size={14} className="text-muted" />
              <input
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="SAP code or description…"
                className="w-48 text-xs outline-none"
              />
            </div>
          </Tooltip>
        </div>
      </div>

      {/* Table */}
      <Card className="p-0">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-primary text-left text-white">
              <tr>
                <th className="px-3 py-2 font-semibold">SAP code</th>
                <th className="px-3 py-2 font-semibold">Description</th>
                <th className="px-3 py-2 font-semibold">Need-by</th>
                <th className="px-3 py-2 text-right font-semibold">Qty</th>
                <th className="px-3 py-2 text-right font-semibold">SAP stock</th>
                <th className="px-3 py-2 text-right font-semibold">Free</th>
                <th className="px-3 py-2 font-semibold">Open POs</th>
                <th className="px-3 py-2 font-semibold">Supplier</th>
                <th className="px-3 py-2 text-right font-semibold">Lead</th>
                <th className="px-3 py-2 font-semibold">Status</th>
                <th className="px-3 py-2 font-semibold">Action</th>
              </tr>
            </thead>
            <tbody>
              {filteredRows.map((r, i) => (
                <tr
                  key={r.m.sap_code}
                  className={`border-b border-line ${i % 2 ? 'bg-surface-alt' : 'bg-white'}`}
                >
                  <td className="px-3 py-2 font-mono text-xs font-semibold">
                    {r.m.sap_code}
                    {r.hasOpenDiscrepancy && (
                      <Tooltip k="materials_dashboard.discrepancy_flag_icon">
                        <button
                          onClick={() => setDiscDrawer(r.m.sap_code)}
                          className="ml-1.5 inline-flex align-middle text-status-red hover:opacity-70"
                          aria-label="Open Stores discrepancy"
                        >
                          <Flag size={13} />
                        </button>
                      </Tooltip>
                    )}
                  </td>
                  <td className="px-3 py-2">{r.m.description}</td>
                  <td className="px-3 py-2 text-xs text-muted">{r.nextNeedBy ? dmy(r.nextNeedBy) : '—'}</td>
                  <td className="px-3 py-2 text-right tabular-nums">{r.totalQty}</td>
                  <td className="px-3 py-2 text-right tabular-nums">{r.stock?.sap_stock ?? 0}</td>
                  <td className="px-3 py-2 text-right tabular-nums">
                    <span className={r.free < 0 ? 'font-semibold text-status-red' : 'font-semibold text-status-green'}>
                      {r.free >= 0 ? `+${r.free}` : r.free}
                    </span>
                  </td>
                  <td className="px-3 py-2 text-xs">
                    {r.stock?.open_po_qty
                      ? `${r.stock.open_po_qty} (eta ${dmy(r.stock.open_po_eta!)})`
                      : '0'}
                  </td>
                  <td className="px-3 py-2">{r.m.supplier}</td>
                  <td className="px-3 py-2 text-right text-xs">{r.m.lead_days}d</td>
                  <td className="px-3 py-2">
                    <UrgencyPill
                      tone={r.urgency}
                      suffix={r.daysToNeed != null ? ` · T-${r.daysToNeed}` : ''}
                    />
                  </td>
                  <td className="px-3 py-2">
                    {r.urgency === 'critical' || r.urgency === 'order_now' ? (
                      <Tooltip k="materials_dashboard.table_action_raise_pr">
                        <button
                          onClick={() => handleRaisePR(r.m.sap_code)}
                          className="rounded-md bg-primary px-2.5 py-1 text-xs font-semibold text-white hover:bg-primary-dark"
                        >
                          Raise PR ›
                        </button>
                      </Tooltip>
                    ) : (
                      <span className="text-muted">—</span>
                    )}
                  </td>
                </tr>
              ))}
              {filteredRows.length === 0 && (
                <tr>
                  <td colSpan={11} className="px-4 py-12 text-center text-sm text-muted">
                    No materials match the current filters.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </Card>

      <div className="mt-2 text-[11px] text-muted">
        Showing {filteredRows.length} of {rows.length} items · sorted by urgency
      </div>
      <LastUpdated at={lastUpdated} onRefresh={refresh} />

      <div className="mt-4 rounded-md border border-status-amber/40 bg-status-amber/5 p-3 text-[11px] text-body">
        <div className="mb-1 text-xs font-bold text-status-amber">How this dashboard works</div>
        • Items computed from every accepted job's BOM × planned start date from the Planning Board.
        <br />• Stock figures pulled live from SAP (mocked here); urgency compared against supplier lead time.
        <br />• Raise PR posts to SAP via BAPI_PR_CREATE (subject to SAP scoping — see Proposal §11.10 Q8).
      </div>

      <DiscrepancyDetailDrawer sapCode={discDrawer} onClose={() => setDiscDrawer(null)} />
    </>
  )
}
