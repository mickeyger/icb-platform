// ProductionDashboard.tsx — WO v4.32 §3.2: wired to REAL data (zero data/mockData imports).
// KPI strip = /api/production-jobs/kpis (compute_production_kpis — §0.6 schema-aligned
// defaults); bay heat-map = the 5 real assembly bays with event-derived occupancy (§0.1 shape
// change vs the 8-bay mock); repairs tile = CostingsContext (already live-capable). The mock
// material-alerts / rework-list / labour-efficiency panels are replaced per §0.15: a Materials
// link-card (shortage signals live in Materials → Suggestions), an open-rework KPI tile
// (detailed lists land with the §3.3 team-worksheet tabs), and a labour placeholder (no labour
// booking source until SAP-read, v4.33+). Live-only surface (the BayModelLanes rule): in mock
// mode renders an offline card. 30s tick refetches the real APIs (§0.3).
import { useEffect, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { AlertCircle, ArrowRightCircle, CheckCircle2, Circle, Link2, Package, RefreshCw, Wrench } from 'lucide-react'
import { KpiTile, Card, SectionTitle } from '../../components/ui/primitives'
import { SidePanel } from '../../components/ui/overlays'
import { Spinner } from '../../components/ui/feedback'
import { Tooltip } from '../../components/ui/Tooltip'
import { useToast } from '../../components/ui/toast'
import { JobCardSections } from '../Planning/JobCardSections'
import { useCostings } from '../../store/CostingsContext'
import { useAppData } from '../../store/AppDataContext'
import { handleApiError } from '../../lib/api'
import { useRefetchOnFocus } from '../../lib/useRefetchOnFocus'
import { hhmm, dmy } from '../../lib/format'
import { useProductionDashboard, type BayState, type UtilisedBay } from './useProductionDashboard'
import { TeamWorksheetTabs } from './TeamWorksheetTabs'

// WO v4.35 §0.20 + §3.3b — the bay visual language. The first four are MUST-SHIP; 'pre_assembly' +
// 'ready_to_merge' are the STRETCH panels-event states (surface only once a job's panels are dragged to a
// bay on the Planning Board). Same vocabulary on the Planning bay lanes (BayModelLanes).
const BAY_STATE_UI: Record<BayState, { label: string; tile: string; badge?: string; badgeClass?: string }> = {
  empty:               { label: 'Available', tile: 'cursor-default border border-dashed border-line bg-surface-alt/40' },
  pre_assembly:        { label: 'Panels arrived', tile: 'border border-line border-l-4 border-l-sky-500 bg-sky-50 hover:border-primary', badge: 'Panels in bay', badgeClass: 'bg-sky-100 text-sky-700' },
  ready_to_merge:      { label: 'Ready to merge', tile: 'border border-line border-l-4 border-l-violet-500 bg-violet-50 hover:border-primary', badge: '↔ Ready to merge', badgeClass: 'bg-violet-100 text-violet-700' },
  awaiting_attachment: { label: 'Awaiting attachment', tile: 'border border-line border-l-4 border-l-status-amber bg-white hover:border-primary', badge: 'Awaiting', badgeClass: 'bg-status-amber/15 text-status-amber' },
  attached_today:      { label: 'Body attached today', tile: 'border border-line border-l-4 border-l-status-green bg-status-green/10 hover:border-primary', badge: '🔗 Attached today', badgeClass: 'bg-status-green/20 text-status-green' },
  post_attached:       { label: 'Finishing', tile: 'border border-line border-l-4 border-l-primary bg-primary/5 hover:border-primary', badge: '🔗 Attached', badgeClass: 'bg-primary/15 text-primary' },
}

export function ProductionDashboard() {
  const nav = useNavigate()
  const toast = useToast()
  const [searchParams, setSearchParams] = useSearchParams()
  const { costings } = useCostings()
  const { hasPermission } = useAppData()
  const canMarkAttached = hasPermission('chassis.assembly_assign')   // §0.5 — planner/admin/production
  const repairs = costings.filter((c) => c.quote_type === 'Repair')
  const { mode, kpis, bays, refreshedAt, refresh, markBodyAttached } = useProductionDashboard()
  useRefetchOnFocus(refresh)         // WO v4.35 §3.3b — cross-page sync (3 surfaces): refetch on tab focus
  const [bay, setBay] = useState<UtilisedBay | null>(null)
  const [highlightBayId, setHighlightBayId] = useState<number | null>(null)
  const [attachNotes, setAttachNotes] = useState('')
  const [attachBusy, setAttachBusy] = useState(false)

  // WO v4.32 §3.5 — the Planning Board deep-link (?jobId=, the v4.29 D7 carry-forward).
  // Runs once the live bays have loaded; the param is CLEARED after handling either way
  // (param hygiene — no 404, no silent ignore). Found → scroll + highlight + open the bay
  // panel; not found (dispatched / dropped / not on a bay) → toast per the §3.5 locked copy.
  const jobIdParam = searchParams.get('jobId')
  useEffect(() => {
    if (!jobIdParam || mode !== 'live') return
    const target = bays.find((b) => b.occupied && b.occupant_job_number === jobIdParam)
    setSearchParams({}, { replace: true })
    if (target) {
      setBay(target)
      setHighlightBayId(target.id)
      requestAnimationFrame(() => {
        document
          .querySelector(`[data-bay-code="${target.code}"]`)
          ?.scrollIntoView({ behavior: 'smooth', block: 'center' })
      })
      window.setTimeout(() => setHighlightBayId(null), 4000)
    } else {
      toast.push({ kind: 'warn', message: `Job ${jobIdParam} is no longer in production` })
    }
  }, [jobIdParam, mode, bays, setSearchParams, toast])

  // WO v4.35 §3.3 — reset the optional notes when the open bay changes.
  useEffect(() => setAttachNotes(''), [bay?.id])

  async function doMarkAttached() {
    if (!bay?.occupant_chassis_id || bay.occupant_job_id == null) return
    setAttachBusy(true)
    try {
      await markBodyAttached(bay.occupant_chassis_id, bay.occupant_job_id, attachNotes)
      setBay(null)                       // refetch updated the bays → close the panel
      toast.push({ kind: 'ok', message: 'Body attached ✓' })
    } catch (e) {
      handleApiError(e, toast.push)      // 409/422 → the service's remediation message
    } finally {
      setAttachBusy(false)
    }
  }

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
      <div className="mb-4 grid grid-cols-2 gap-3 md:grid-cols-4 xl:grid-cols-8" data-testid="production-kpis">
        <Tooltip k="production_dashboard.units_in_production_tile">
          <KpiTile label="Units in production" value={kpis?.units_in_production ?? '—'} />
        </Tooltip>
        {/* WO v4.35 §0.6 — the keystone KPI: bodies joined to chassis today. */}
        <Tooltip k="production_dashboard.bodies_attached_today_tile">
          <KpiTile
            label="Bodies attached today"
            value={
              <span className="flex items-center gap-1.5 text-status-green">
                <Link2 size={18} /> {kpis?.bodies_attached_today ?? '—'}
              </span>
            }
            status={kpis && kpis.bodies_attached_today > 0 ? 'GREEN' : undefined}
            sub="body ↔ chassis joined"
          />
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
            {bays.map((b) => {
              const st = (b.state ?? (b.occupied ? 'awaiting_attachment' : 'empty')) as BayState
              const ui = BAY_STATE_UI[st] ?? BAY_STATE_UI.empty
              return (
                <button
                  key={b.id}
                  data-testid="production-bay-tile"
                  data-bay-code={b.code}
                  data-occupied={b.occupied}
                  data-bay-state={st}
                  onClick={() => b.occupied && setBay(b)}
                  className={`flex min-h-[92px] flex-col items-start rounded-md p-2.5 text-left transition ${ui.tile} ${
                    highlightBayId === b.id ? 'ring-2 ring-primary ring-offset-2' : ''
                  }`}
                >
                  <div className="flex w-full items-center justify-between gap-1">
                    <span className="text-xs font-bold text-body">{b.code}</span>
                    {ui.badge && (
                      <span data-testid="bay-badge"
                        className={`whitespace-nowrap rounded px-1.5 py-0.5 text-[9px] font-bold uppercase ${ui.badgeClass}`}>
                        {ui.badge}
                      </span>
                    )}
                  </div>
                  {b.occupied ? (
                    <>
                      <span className="mt-1 font-mono text-xs font-semibold text-body">{b.occupant_vin}</span>
                      <span className="truncate text-[11px] text-muted">{b.occupant_customer || '—'}</span>
                      <span className="mt-auto text-[10px] text-muted">
                        {b.occupant_job_number ? `J${b.occupant_job_number} · ` : ''}{ui.label.toLowerCase()}
                      </span>
                    </>
                  ) : (
                    <span className="m-auto text-[11px] text-muted">Available</span>
                  )}
                </button>
              )
            })}
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
            {/* WO v4.35 §3.3 — body↔chassis lifecycle checklist (makes the causality visible to Burt). */}
            {(() => {
              const attached = bay.state === 'attached_today' || bay.state === 'post_attached'
              const steps = [
                { label: 'Chassis received (VCL)', done: true },
                { label: 'Assigned to assembly bay', done: true },
                { label: 'Body attached', done: attached },
              ]
              return (
                <div className="rounded-md border border-line p-3" data-testid="bay-lifecycle">
                  <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted">Lifecycle</div>
                  <ul className="space-y-1.5 text-sm">
                    {steps.map((s) => (
                      <li key={s.label} className="flex items-center gap-2">
                        {s.done
                          ? <CheckCircle2 size={15} className="shrink-0 text-status-green" />
                          : <Circle size={15} className="shrink-0 text-muted" />}
                        <span className={s.done ? 'text-body' : 'text-muted'}>{s.label}</span>
                      </li>
                    ))}
                  </ul>
                  {bay.body_attached_on && (
                    <div className="mt-2 flex items-center gap-1 text-[11px] font-semibold text-status-green">
                      <Link2 size={12} /> Body attached on {dmy(bay.body_attached_on)}
                    </div>
                  )}
                </div>
              )
            })()}

            {/* WO v4.35 §0.5 — "Mark body attached" affordance: only when awaiting + permitted. */}
            {bay.state === 'awaiting_attachment' && canMarkAttached && (
              <div className="space-y-2 rounded-md border border-status-green/40 bg-status-green/5 p-3"
                   data-testid="mark-attached-section">
                <div className="text-xs font-semibold uppercase tracking-wide text-muted">Body ↔ chassis merge</div>
                <textarea
                  value={attachNotes}
                  onChange={(e) => setAttachNotes(e.target.value.slice(0, 500))}
                  maxLength={500}
                  rows={2}
                  placeholder="Notes (optional)"
                  data-testid="attach-notes"
                  className="w-full rounded-md border border-line bg-surface p-2 text-sm"
                />
                <button
                  onClick={doMarkAttached}
                  disabled={attachBusy}
                  data-testid="mark-body-attached"
                  className="flex w-full items-center justify-center gap-2 rounded-md bg-status-green py-2 font-semibold text-white hover:opacity-90 disabled:opacity-60"
                >
                  {attachBusy ? <Spinner size={14} /> : <Link2 size={14} />} Mark body attached
                </button>
              </div>
            )}
            {bay.state === 'awaiting_attachment' && !canMarkAttached && (
              <div className="rounded-md border border-dashed border-line p-3 text-xs text-muted"
                   data-testid="mark-attached-readonly">
                Awaiting body attachment — only planner / production / admin can record it.
              </div>
            )}

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
