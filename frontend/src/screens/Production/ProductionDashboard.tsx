import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip as RechartsTooltip,
  Legend,
  ResponsiveContainer,
  CartesianGrid,
} from 'recharts'
import { AlertCircle, RefreshCw, ArrowRightCircle, Wrench } from 'lucide-react'
import { data, labourEfficiency } from '../../data/mockData'
import { useAppData } from '../../store/AppDataContext'
import { findBottleneck, statusBg, severityToStatus, statusText } from '../../lib/status'
import { KpiTile, Card, StatusPill, SectionTitle } from '../../components/ui/primitives'
import { SidePanel } from '../../components/ui/overlays'
import { JobDetailStub } from '../../components/JobDetailStub'
import { Tooltip } from '../../components/ui/Tooltip'
import { useCostings } from '../../store/CostingsContext'
import { hhmm } from '../../lib/format'
import type { Bay, MaterialAlert } from '../../data/types'

export function ProductionDashboard() {
  const nav = useNavigate()
  const { unitsInProduction, reworkTickets } = useAppData()
  const { costings } = useCostings()
  const repairs = costings.filter((c) => c.quote_type === 'Repair')
  const [refreshed, setRefreshed] = useState(new Date())
  const [bay, setBay] = useState<Bay | null>(null)
  const [alert, setAlert] = useState<MaterialAlert | null>(null)
  const [jobNum, setJobNum] = useState<string | null>(null)

  useEffect(() => {
    const t = setInterval(() => setRefreshed(new Date()), 30000)
    return () => clearInterval(t)
  }, [])

  const bays = data.bays
  const delayed = data.jobs.filter((j) => j.is_late).length
  const bottleneck = findBottleneck(bays)
  const k = data.kpis

  return (
    <div className="p-4">
      {/* Banner */}
      <div className="mb-4 flex items-center justify-between">
        <h1 className="text-xl font-bold text-body">
          Production · {hhmm(refreshed)} · JHB Plant
        </h1>
        <div className="flex items-center gap-1.5 text-xs text-muted">
          <RefreshCw size={13} /> Auto-refresh 30s · last {hhmm(refreshed)}
        </div>
      </div>

      {/* KPI strip */}
      <div className="mb-4 grid grid-cols-2 gap-3 md:grid-cols-6">
        <Tooltip k="production_dashboard.units_in_production_tile">
          <KpiTile label="Units in production" value={unitsInProduction} />
        </Tooltip>
        <Tooltip k="production_dashboard.delayed_units_tile">
          <KpiTile label="Delayed units" value={delayed} status={delayed ? 'RED' : 'GREEN'} />
        </Tooltip>
        <Tooltip k="production_dashboard.bottleneck_tile">
          <KpiTile label="Bottleneck" value={<span className="text-lg">{bottleneck?.name ?? '—'}</span>} />
        </Tooltip>
        <Tooltip k="production_dashboard.daily_output_tile">
          <KpiTile label="Daily output" value={k.completed_today} sub={`Target ${k.target_today}`} />
        </Tooltip>
        <Tooltip k="production_dashboard.today_vs_target_tile">
          <KpiTile
            label="Today vs target"
            value={`${k.completed_today} / ${k.target_today}`}
            status={k.completed_today >= k.target_today ? 'GREEN' : 'AMBER'}
          />
        </Tooltip>
        <Tooltip k="production_dashboard.critical_chassis_tile">
          <KpiTile label="Critical chassis" value={k.critical_chassis} status={k.critical_chassis > 0 ? 'AMBER' : 'GREEN'} />
        </Tooltip>
        <Tooltip k="production_dashboard.repair_jobs_tile">
          <KpiTile
            label="Repair jobs"
            value={
              <span className="flex items-center gap-1.5 text-[#7E22CE]">
                <Wrench size={18} /> {repairs.length}
              </span>
            }
            sub={repairs.length ? `Across ${Math.min(repairs.length, 5)} customers` : 'None in flight'}
          />
        </Tooltip>
      </div>

      {/* Heat-map */}
      <Tooltip k="production_dashboard.bay_utilisation_heatmap">
        <Card className="mb-4">
          <SectionTitle>Bay utilisation</SectionTitle>
          <div className="grid grid-cols-3 gap-2 sm:grid-cols-5 lg:grid-cols-8">
            {bays.map((b) => (
              <Tooltip key={b.id} k="production_dashboard.bay_tile_click_drilldown">
                <button
                  onClick={() => setBay(b)}
                  className={`flex flex-col items-start rounded-md px-2.5 py-2 text-left text-white transition hover:opacity-90 ${statusBg[b.status]} ${
                    b.status === 'RED' ? 'animate-pulseRed' : ''
                  }`}
                >
                  <span className="text-xs font-bold">{b.id}</span>
                  <span className="text-[10px] leading-tight opacity-90">{b.name}</span>
                  <span className="mt-1 text-[10px] font-semibold">
                    {b.wip_count}/{b.wip_limit} WIP
                  </span>
                </button>
              </Tooltip>
            ))}
          </div>
        </Card>
      </Tooltip>

      {/* Materials + rework */}
      <div className="mb-4 grid gap-4 lg:grid-cols-2">
        <Tooltip k="production_dashboard.material_shortage_alerts">
        <Card>
          <SectionTitle>Material shortage alerts</SectionTitle>
          <ul className="space-y-2">
            {data.material_alerts.map((m) => (
              <li key={m.sap_item_code}>
                <button
                  onClick={() => setAlert(m)}
                  className="flex w-full items-start gap-2 rounded-md p-2 text-left hover:bg-surface-alt"
                >
                  <span className={`mt-1 h-2.5 w-2.5 rounded-full ${statusBg[severityToStatus(m.severity)]}`} />
                  <div className="flex-1">
                    <div className="font-mono text-sm font-semibold text-body">{m.sap_item_code}</div>
                    <div className="text-xs text-muted">
                      {m.shortage} short · {m.affecting_jobs.map((j) => 'J' + j).join(', ')}
                    </div>
                  </div>
                  <StatusPill status={severityToStatus(m.severity)} label={m.severity} />
                </button>
              </li>
            ))}
          </ul>
        </Card>
        </Tooltip>

        <Tooltip k="production_dashboard.rework_queue_panel">
        <Card>
          <SectionTitle>Rework queue</SectionTitle>
          {reworkTickets.length === 0 ? (
            <p className="text-sm text-muted">No critical reworks today.</p>
          ) : (
            <ul className="space-y-2">
              {reworkTickets.map((r) => (
                <li key={r.ticket}>
                  <button
                    onClick={() => setJobNum(r.job_number)}
                    className="flex w-full items-center gap-2 rounded-md p-2 text-left hover:bg-surface-alt"
                  >
                    <Wrench size={15} className={statusText[severityToStatus(r.severity)]} />
                    <div className="flex-1">
                      <span className="font-mono text-sm font-semibold">{r.ticket}</span>{' '}
                      <span className="text-sm">J{r.job_number}</span>
                      <div className="text-xs text-muted">
                        {r.from_bay} → {r.to_bay} · {r.reason}
                      </div>
                    </div>
                    <StatusPill status={severityToStatus(r.severity)} label={r.severity} />
                  </button>
                </li>
              ))}
            </ul>
          )}
        </Card>
        </Tooltip>
      </div>

      {/* Labour efficiency */}
      <Tooltip k="production_dashboard.labour_efficiency_chart">
      <Card>
        <SectionTitle>Labour efficiency — today by team (hours)</SectionTitle>
        <div className="h-64">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={labourEfficiency} margin={{ top: 8, right: 8, bottom: 0, left: -16 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#E5E7EB" />
              <XAxis dataKey="team" tick={{ fontSize: 12 }} />
              <YAxis tick={{ fontSize: 12 }} />
              <RechartsTooltip />
              <Legend />
              <Bar dataKey="planned" name="Planned" fill="#94A3B8" radius={[3, 3, 0, 0]} />
              <Bar dataKey="booked" name="Booked" fill="#0E4D8C" radius={[3, 3, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </Card>
      </Tooltip>

      {/* Bay side panel */}
      <SidePanel title={bay ? `${bay.id} · ${bay.name}` : ''} open={!!bay} onClose={() => setBay(null)}>
        {bay && (
          <div className="space-y-4">
            <div className="flex items-center gap-2">
              <StatusPill status={bay.status} />
              <span className="text-sm text-muted">{bay.team}</span>
            </div>
            {(bay.amber_reason || bay.red_reason) && (
              <div className="flex items-start gap-2 rounded-md bg-surface-alt p-3 text-sm">
                <AlertCircle size={16} className={statusText[bay.status]} />
                <span>{bay.red_reason ?? bay.amber_reason}</span>
              </div>
            )}
            <div className="grid grid-cols-2 gap-3 text-sm">
              <Stat label="WIP" value={`${bay.wip_count} / ${bay.wip_limit}`} />
              <Stat label="Throughput" value={`${bay.throughput_today} / ${bay.target_today}`} />
            </div>
            <PanelList title="Current jobs" jobs={bay.current_jobs} onPick={setJobNum} />
            <PanelList title="Queue" jobs={bay.queue} onPick={setJobNum} />
            <button
              onClick={() => nav('/kanban/pre-assy')}
              className="flex w-full items-center justify-center gap-2 rounded-md bg-primary py-2.5 text-sm font-semibold text-white hover:bg-primary-dark"
            >
              <ArrowRightCircle size={16} /> Open bay Kanban
            </button>
          </div>
        )}
      </SidePanel>

      {/* Material alert side panel */}
      <SidePanel title={alert ? alert.sap_item_code : ''} open={!!alert} onClose={() => setAlert(null)}>
        {alert && (
          <div className="space-y-3 text-sm">
            <div className="text-body">{alert.description}</div>
            <div className="flex items-center gap-2">
              <StatusPill status={severityToStatus(alert.severity)} label={alert.severity} />
            </div>
            <div className="grid grid-cols-3 gap-2 rounded-md bg-surface-alt p-3 text-center">
              <Stat label="Needed" value={String(alert.qty_needed)} />
              <Stat label="Available" value={String(alert.qty_available)} />
              <Stat label="Short" value={String(alert.shortage)} />
            </div>
            <Stat label="PO status" value={alert.po_status} />
            <PanelList title="Affecting jobs" jobs={alert.affecting_jobs} onPick={setJobNum} />
          </div>
        )}
      </SidePanel>

      <JobDetailStub jobNumber={jobNum} onClose={() => setJobNum(null)} />
    </div>
  )
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-xs uppercase tracking-wide text-muted">{label}</div>
      <div className="font-semibold text-body">{value}</div>
    </div>
  )
}

function PanelList({
  title,
  jobs,
  onPick,
}: {
  title: string
  jobs: string[]
  onPick: (j: string) => void
}) {
  return (
    <div>
      <div className="mb-1 text-xs uppercase tracking-wide text-muted">{title}</div>
      {jobs.length === 0 ? (
        <div className="text-sm text-muted">—</div>
      ) : (
        <div className="flex flex-wrap gap-1.5">
          {jobs.map((j) => (
            <button
              key={j}
              onClick={() => onPick(j)}
              className="rounded-md border border-line px-2 py-1 font-mono text-xs hover:border-primary hover:text-primary"
            >
              {j}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
