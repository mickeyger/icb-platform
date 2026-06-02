import { useState } from 'react'
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip as RechartsTooltip,
  ResponsiveContainer,
  CartesianGrid,
  Legend,
} from 'recharts'
import { Printer, ArrowUpDown } from 'lucide-react'
import { data, orderbookBreakdown, deliveryRisk, repPipelineValue } from '../../data/mockData'
import { zar, zarShort, dmy } from '../../lib/format'
import { statusBg } from '../../lib/status'
import { KpiTile, Card, SectionTitle, StatusPill } from '../../components/ui/primitives'
import { SidePanel, Toast } from '../../components/ui/overlays'
import { Tooltip } from '../../components/ui/Tooltip'
import type { SalesRep } from '../../data/types'

type SortKey = keyof Pick<SalesRep, 'active_jobs' | 'planned' | 'invoiced_ytd' | 'late' | 'critical_chassis'> | 'pipeline'

export function ManagementDashboard() {
  const k = data.kpis
  const [toast, setToast] = useState(false)
  const [rep, setRep] = useState<SalesRep | null>(null)
  const [sortKey, setSortKey] = useState<SortKey>('active_jobs')

  const reps = [...data.sales_reps].sort((a, b) => {
    const av = sortKey === 'pipeline' ? repPipelineValue[a.code] ?? 0 : (a[sortKey] as number)
    const bv = sortKey === 'pipeline' ? repPipelineValue[b.code] ?? 0 : (b[sortKey] as number)
    return bv - av
  })

  const forecast = data.planning_board.weeks.map((w) => ({
    week: w.week,
    planned: w.slots_filled,
    forecast: Math.round(w.slots_filled * 0.92),
  }))

  const maxOrderbook = Math.max(...orderbookBreakdown.map((o) => o.value_zar))

  function printPdf() {
    setToast(true)
    setTimeout(() => setToast(false), 2200)
  }

  return (
    <div className="p-4">
      <div className="mb-4 flex items-center justify-between">
        <h1 className="text-xl font-bold text-body">Management · {dmy(data._meta.snapshot_date)}</h1>
        <Tooltip k="management_dashboard.print_pdf_button">
          <button onClick={printPdf} className="flex items-center gap-2 rounded-md bg-primary px-4 py-2 text-sm font-semibold text-white hover:bg-primary-dark">
            <Printer size={16} /> Print PDF
          </button>
        </Tooltip>
      </div>

      {/* KPI strip */}
      <div className="mb-4 grid grid-cols-2 gap-3 md:grid-cols-5">
        <Tooltip k="management_dashboard.orderbook_total_tile">
          <KpiTile label="Orderbook total" value={zarShort(k.orderbook_total_zar)} big />
        </Tooltip>
        <Tooltip k="management_dashboard.invoiced_ytd_tile">
          <KpiTile label="Invoiced YTD" value={zarShort(k.invoiced_ytd_zar)} big />
        </Tooltip>
        <Tooltip k="management_dashboard.weekly_target_tile">
          <KpiTile label="Weekly target" value={zarShort(k.weekly_target_zar)} big />
        </Tooltip>
        <Tooltip k="management_dashboard.capacity_this_week_tile">
          <KpiTile label="Capacity this week" value="88%" sub="28/32 slots" big />
        </Tooltip>
        <Tooltip k="management_dashboard.late_jobs_tile">
          <KpiTile label="Late jobs" value={k.late_jobs} status="RED" big />
        </Tooltip>
      </div>

      {/* Orderbook + delivery risk */}
      <div className="mb-4 grid gap-4 lg:grid-cols-2">
        <Tooltip k="management_dashboard.orderbook_breakdown_card">
        <Card>
          <SectionTitle>Orderbook breakdown</SectionTitle>
          <div className="space-y-3">
            <Bar label="JHB" value={k.orderbook_jhb} max={k.orderbook_total_zar} />
            <Bar label="Cape Town" value={k.orderbook_ct} max={k.orderbook_total_zar} />
            <div className="my-2 border-t border-line" />
            {orderbookBreakdown.map((o) => (
              <Bar key={o.label} label={o.label} value={o.value_zar} max={maxOrderbook} />
            ))}
          </div>
        </Card>
        </Tooltip>

        <Tooltip k="management_dashboard.delivery_risk_card">
        <Card>
          <SectionTitle>Delivery risk — next 4 weeks</SectionTitle>
          <div className="space-y-3">
            {deliveryRisk.map((r) => (
              <div key={r.status} className="flex items-center gap-3">
                <StatusPill status={r.status} />
                <span className="flex-1 text-sm text-body">{r.label}</span>
                <span className="text-2xl font-bold tabular-nums text-body">{r.jobs}</span>
                <span className="text-xs text-muted">jobs</span>
              </div>
            ))}
            <div className="mt-2 flex h-3 overflow-hidden rounded-full">
              {deliveryRisk.map((r) => (
                <div key={r.status} className={statusBg[r.status]} style={{ flex: r.jobs }} />
              ))}
            </div>
          </div>
        </Card>
        </Tooltip>
      </div>

      {/* Per-rep table */}
      <Tooltip k="management_dashboard.per_rep_performance_table">
      <Card className="mb-4 p-0">
        <div className="p-4 pb-2"><SectionTitle>Per-rep performance</SectionTitle></div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-primary text-left text-white">
              <tr>
                <th className="px-3 py-2 font-semibold">Rep</th>
                <Th label="Total" k="active_jobs" sortKey={sortKey} onSort={setSortKey} />
                <Th label="Planned" k="planned" sortKey={sortKey} onSort={setSortKey} />
                <Th label="Inv YTD" k="invoiced_ytd" sortKey={sortKey} onSort={setSortKey} />
                <Th label="Late" k="late" sortKey={sortKey} onSort={setSortKey} />
                <Th label="Crit" k="critical_chassis" sortKey={sortKey} onSort={setSortKey} />
                <Th label="Pipeline" k="pipeline" sortKey={sortKey} onSort={setSortKey} />
              </tr>
            </thead>
            <tbody>
              {reps.map((r, i) => (
                <Tooltip key={r.code} k="management_dashboard.rep_row_click_drilldown">
                <tr onClick={() => setRep(r)} className={`cursor-pointer hover:bg-primary-light/50 ${i % 2 ? 'bg-surface-alt' : 'bg-white'}`}>
                  <td className="px-3 py-2 font-semibold">{r.code}<span className="ml-2 font-normal text-muted">{r.name}</span></td>
                  <td className="px-3 py-2 tabular-nums">{r.active_jobs}</td>
                  <td className="px-3 py-2 tabular-nums">{r.planned}</td>
                  <td className="px-3 py-2 tabular-nums">{r.invoiced_ytd}</td>
                  <td className={`px-3 py-2 tabular-nums ${r.late > 0 ? 'font-semibold text-status-red' : ''}`}>{r.late}</td>
                  <td className={`px-3 py-2 tabular-nums ${r.critical_chassis > 0 ? 'font-semibold text-status-amber' : ''}`}>{r.critical_chassis}</td>
                  <td className="px-3 py-2 tabular-nums">{zarShort(repPipelineValue[r.code] ?? 0)}</td>
                </tr>
                </Tooltip>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
      </Tooltip>

      {/* Forecast */}
      <Tooltip k="management_dashboard.production_forecast_chart">
      <Card>
        <SectionTitle>Production forecast — next weeks (completions)</SectionTitle>
        <div className="h-64">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={forecast} margin={{ top: 8, right: 16, bottom: 0, left: -16 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#E5E7EB" />
              <XAxis dataKey="week" tick={{ fontSize: 12 }} />
              <YAxis tick={{ fontSize: 12 }} />
              <RechartsTooltip />
              <Legend />
              <Line type="monotone" dataKey="planned" name="Planned" stroke="#0E4D8C" strokeWidth={2} />
              <Line type="monotone" dataKey="forecast" name="Forecast" stroke="#F59E0B" strokeWidth={2} strokeDasharray="5 4" />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </Card>
      </Tooltip>

      {/* Rep drill-through */}
      <SidePanel title={rep ? `${rep.code} · ${rep.name}` : ''} open={!!rep} onClose={() => setRep(null)}>
        {rep && <RepDetail rep={rep} />}
      </SidePanel>

      <Toast message="PDF ready — generating download…" show={toast} />
    </div>
  )
}

function Bar({ label, value, max }: { label: string; value: number; max: number }) {
  return (
    <div>
      <div className="mb-1 flex items-center justify-between text-sm">
        <span className="text-body">{label}</span>
        <span className="font-semibold tabular-nums">{zarShort(value)}</span>
      </div>
      <div className="h-3 overflow-hidden rounded-full bg-surface-alt">
        <div className="h-full rounded-full bg-primary" style={{ width: `${(value / max) * 100}%` }} />
      </div>
    </div>
  )
}

function Th({ label, k, sortKey, onSort }: { label: string; k: SortKey; sortKey: SortKey; onSort: (k: SortKey) => void }) {
  return (
    <th className="px-3 py-2 font-semibold">
      <button onClick={() => onSort(k)} className="flex items-center gap-1">
        {label}
        <ArrowUpDown size={12} className={sortKey === k ? 'opacity-100' : 'opacity-40'} />
      </button>
    </th>
  )
}

function RepDetail({ rep }: { rep: SalesRep }) {
  const jobs = data.jobs.filter((j) => j.rep === rep.code && !j.configurator_demo)
  return (
    <div className="space-y-3 text-sm">
      <div className="grid grid-cols-2 gap-2 rounded-md bg-surface-alt p-3">
        <div><div className="text-xs text-muted">Active jobs</div><span className="text-lg font-bold">{rep.active_jobs}</span></div>
        <div><div className="text-xs text-muted">Pipeline value</div><span className="text-lg font-bold">{zar(repPipelineValue[rep.code] ?? 0)}</span></div>
      </div>
      <div className="text-xs uppercase tracking-wide text-muted">Jobs in this data set</div>
      {jobs.length === 0 ? (
        <p className="text-muted">No detailed jobs for this rep in the mock set.</p>
      ) : (
        <ul className="space-y-2">
          {jobs.map((j) => (
            <li key={j.job_number} className="rounded-md border border-line p-2">
              <div className="flex items-center justify-between">
                <span className="font-mono text-sm font-semibold">#{j.job_number}</span>
                <StatusPill status={j.is_late ? 'RED' : 'GREEN'} label={j.status.replace(/_/g, ' ')} />
              </div>
              <div className="text-xs text-body">{j.description}</div>
              <div className="mt-1 text-xs text-muted">Promised {dmy(j.promised_date)} · {zar(j.selling_zar)}</div>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
