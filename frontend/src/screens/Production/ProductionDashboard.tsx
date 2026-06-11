// ProductionDashboard.tsx — WO v4.32 §3.2: wired to REAL data (zero data/mockData imports).
// KPI strip = /api/production-jobs/kpis (compute_production_kpis — §0.6 schema-aligned
// defaults); bay heat-map = the 5 real assembly bays with event-derived occupancy (§0.1 shape
// change vs the 8-bay mock); repairs tile = CostingsContext (already live-capable). The mock
// material-alerts / rework-list / labour-efficiency panels are replaced per §0.15: a Materials
// link-card (shortage signals live in Materials → Suggestions), an open-rework KPI tile
// (detailed lists land with the §3.3 team-worksheet tabs), and a labour placeholder (no labour
// booking source until SAP-read, v4.33+). Live-only surface (the BayModelLanes rule): in mock
// mode renders an offline card. 30s tick refetches the real APIs (§0.3).
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { AlertCircle, ArrowRightCircle, Package, RefreshCw, Wrench } from 'lucide-react'
import { KpiTile, Card, SectionTitle } from '../../components/ui/primitives'
import { SidePanel } from '../../components/ui/overlays'
import { Tooltip } from '../../components/ui/Tooltip'
import { JobCardSections } from '../Planning/JobCardSections'
import { useCostings } from '../../store/CostingsContext'
import { hhmm, dmy } from '../../lib/format'
import { useProductionDashboard, type UtilisedBay } from './useProductionDashboard'
import { TeamWorksheetTabs } from './TeamWorksheetTabs'

export function ProductionDashboard() {
  const nav = useNavigate()
  const { costings } = useCostings()
  const repairs = costings.filter((c) => c.quote_type === 'Repair')
  const { mode, kpis, bays, refreshedAt } = useProductionDashboard()
  const [bay, setBay] = useState<UtilisedBay | null>(null)

  if (mode === 'mock') {
    return (
      <div className="p-4">
        <h1 className="mb-4 text-xl font-bold text-body">Production</h1>
        <Card data-testid="production-offline">
          <div className="flex items-start gap-2 text-sm text-muted">
            <AlertCircle size={16} className="mt-0.5 shrink-0" />
            <span>
              The Production Dashboard is wired to live data (WO v4.32) and needs the FastAPI
              backend. Start the API and reload — there is no mock fallback for this screen.
            </span>
          </div>
        </Card>
      </div>
    )
  }

  const delayed = kpis?.delayed
  const bottleneck = kpis?.bottleneck ?? null
  const occupiedCount = bays.filter((b) => b.occupied).length

  return (
    <div className="p-4">
      {/* Banner */}
      <div className="mb-4 flex items-center justify-between">
        <h1 className="text-xl font-bold text-body">Production</h1>
        <div
          className="flex items-center gap-1.5 text-xs text-muted"
          data-testid="dashboard-refreshed-at"
          data-refreshed={refreshedAt?.toISOString() ?? ''}
        >
          <RefreshCw size={13} /> Auto-refresh 30s · last {refreshedAt ? hhmm(refreshedAt) : '—'}
        </div>
      </div>

      {/* KPI strip — real values from compute_production_kpis (§0.6 defaults) */}
      <div className="mb-4 grid grid-cols-2 gap-3 md:grid-cols-7" data-testid="production-kpis">
        <Tooltip k="production_dashboard.units_in_production_tile">
          <KpiTile label="Units in production" value={kpis?.units_in_production ?? '—'} />
        </Tooltip>
        <Tooltip k="production_dashboard.delayed_units_tile">
          <KpiTile
            label="Delayed units"
            value={delayed?.total ?? '—'}
            status={delayed && delayed.total > 0 ? 'RED' : 'GREEN'}
            sub={delayed ? `${delayed.start_slipped} start · ${delayed.chassis_slipped} chassis` : undefined}
          />
        </Tooltip>
        <Tooltip k="production_dashboard.bottleneck_tile">
          <KpiTile
            label="Bottleneck"
            value={<span className="text-lg">{bottleneck?.job_number ?? '—'}</span>}
            sub={bottleneck ? `${bottleneck.days_in_stage}d · ${bottleneck.status.replace(/_/g, ' ')}` : 'nothing stuck > 2d'}
          />
        </Tooltip>
        <Tooltip k="production_dashboard.daily_output_tile">
          {/* §0.6 no-target-line branch: no target is seeded, so no "Target N" sub renders. */}
          <KpiTile
            label="Completed today"
            value={kpis?.completed_today ?? '—'}
            sub={kpis?.target_today != null ? `Target ${kpis.target_today}` : undefined}
          />
        </Tooltip>
        <Tooltip k="production_dashboard.critical_chassis_tile">
          <KpiTile
            label="Critical chassis"
            value={kpis?.critical_chassis ?? '—'}
            status={kpis && kpis.critical_chassis > 0 ? 'AMBER' : 'GREEN'}
            sub="ETA passed, not received"
          />
        </Tooltip>
        <Tooltip k="production_dashboard.open_rework_tile">
          <KpiTile
            label="Open rework"
            value={kpis?.open_rework ?? '—'}
            status={kpis && kpis.open_rework > 0 ? 'AMBER' : 'GREEN'}
            sub="details on team worksheets"
          />
        </Tooltip>
        <Tooltip k="production_dashboard.repair_jobs_tile">
          <KpiTile
            label="Repair jobs"
            value={
              <span className="flex items-center gap-1.5 text-[#7E22CE]">
                <Wrench size={18} /> {repairs.length}
              </span>
            }
            sub={repairs.length ? 'from Costings' : 'None in flight'}
          />
        </Tooltip>
      </div>

      {/* Bay heat-map — the 5 REAL assembly bays (§0.1; occupancy event-derived per §0.12) */}
      <Tooltip k="production_dashboard.bay_utilisation_heatmap">
        <Card className="mb-4">
          <div className="flex items-center justify-between">
            <SectionTitle>Assembly bay utilisation</SectionTitle>
            <span className="text-[11px] text-muted">
              {bays.length} bays · {bays.length - occupiedCount} free
            </span>
          </div>
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-5">
            {bays.map((b) => (
              <button
                key={b.id}
                data-testid="production-bay-tile"
                data-bay-code={b.code}
                data-occupied={b.occupied}
                onClick={() => b.occupied && setBay(b)}
                className={`flex min-h-[84px] flex-col items-start rounded-md p-2.5 text-left transition ${
                  b.occupied
                    ? 'border border-line border-l-4 border-l-status-green bg-white hover:border-primary'
                    : 'cursor-default border border-dashed border-line bg-surface-alt/40'
                }`}
              >
                <span className="text-xs font-bold text-body">{b.code}</span>
                {b.occupied ? (
                  <>
                    <span className="mt-1 font-mono text-xs font-semibold text-body">{b.occupant_vin}</span>
                    <span className="truncate text-[11px] text-muted">{b.occupant_customer || '—'}</span>
                    <span className="mt-auto text-[10px] text-muted">
                      {b.occupant_job_number ? `J${b.occupant_job_number} · ` : ''}
                      since {b.since ? dmy(b.since) : '—'}
                    </span>
                  </>
                ) : (
                  <span className="m-auto text-[11px] text-muted">Free</span>
                )}
              </button>
            ))}
            {bays.length === 0 && <div className="text-sm text-muted">No assembly bays configured.</div>}
          </div>
        </Card>
      </Tooltip>

      {/* Per-team daily worksheet — §0.1 surface (b); tabs + date selector + per-role render (§3.3) */}
      <TeamWorksheetTabs />

      {/* §0.15 replacement panels — honest signals only */}
      <div className="mb-4 grid gap-4 lg:grid-cols-2">
        <Card data-testid="dashboard-materials-link">
          <SectionTitle>Material shortages</SectionTitle>
          <p className="mb-3 text-sm text-muted">
            Shortage signals are owned by the Materials module (live PO suggestions + demand vs.
            stock), not duplicated here.
          </p>
          <button
            onClick={() => nav('/materials/suggestions')}
            className="flex items-center gap-2 rounded-md border border-line px-3 py-2 text-sm font-semibold text-primary hover:bg-surface-alt"
          >
            <Package size={15} /> Open Materials → Suggestions <ArrowRightCircle size={15} />
          </button>
        </Card>
        <Card data-testid="dashboard-labour-placeholder">
          <SectionTitle>Labour efficiency</SectionTitle>
          <p className="text-sm text-muted">
            Labour booking data lands with the SAP integration (v4.33+). This panel stays empty
            rather than rendering illustrative numbers.
          </p>
        </Card>
      </div>

      {/* Bay side panel — occupant + the v4.31 job card (consume-only; §3.5 deep-link target) */}
      <SidePanel
        title={bay ? `${bay.code}${bay.occupant_vin ? ` · ${bay.occupant_vin}` : ''}` : ''}
        open={!!bay}
        onClose={() => setBay(null)}
      >
        {bay && (
          <div className="space-y-4" data-testid="production-bay-panel">
            <div className="grid grid-cols-2 gap-3 rounded-md bg-surface-alt p-3 text-sm">
              <div>
                <div className="text-xs uppercase tracking-wide text-muted">Customer</div>
                <div className="font-semibold text-body">{bay.occupant_customer || '—'}</div>
              </div>
              <div>
                <div className="text-xs uppercase tracking-wide text-muted">On bay since</div>
                <div className="font-semibold text-body">{bay.since ? dmy(bay.since) : '—'}</div>
              </div>
            </div>
            {bay.occupant_job_id != null ? (
              <JobCardSections jobId={bay.occupant_job_id} />
            ) : (
              <div className="rounded-md border border-dashed border-line p-3 text-sm text-muted">
                No production job linked to this chassis yet.
              </div>
            )}
          </div>
        )}
      </SidePanel>
    </div>
  )
}
