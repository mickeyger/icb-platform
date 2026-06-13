import { useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import {
  ArrowLeft,
  Printer,
  Send,
  Wrench,
  Truck,
  CheckCircle2,
  Circle,
  XCircle,
  AlertCircle,
  ShieldCheck,
  Lock,
} from 'lucide-react'
import { useCostings } from '../../store/CostingsContext'
import { apiGet } from '../../lib/api'
import { useAppData } from '../../store/AppDataContext'
import { Card, SectionTitle, StatusPill } from '../../components/ui/primitives'
import { Toast } from '../../components/ui/overlays'
import { Tooltip } from '../../components/ui/Tooltip'
import { zar, dmy, hhmm } from '../../lib/format'
import { demoBom, demoBomTotal } from '../../data/mockData'
import { STATUS_STYLES, StatusPillCosting } from './statusPalette'
import { PreJobCardModal } from './PreJobCardModal'
import { RepairPhasePanel } from './RepairPhasePanel'
import { PreJobSignoffModal } from './PreJobSignoffModal'
import { BottleneckIndicator } from './BottleneckIndicator'
import type { Costing } from '../../data/costingsData'
import type { Status } from '../../data/types'

// WO v4.33 §0.21 — the new flow's live sign-off state (read from prejob_cards via
// /by-calculation). When a row exists it SUPERSEDES the legacy production_jobs sign-off
// widget below: the new flow never writes the legacy sales/production_signoff_at columns
// ("planner ≠ production"), so the old widget would be both a duplicate surface and
// permanently un-tickable. One card → one sign-off surface.
interface PrejobCardStatus {
  id: number; status: string; reject_reason: string | null
  sales_rep_signoff_at: string | null; sales_rep_username: string | null
  planner_signoff_at: string | null; planner_username: string | null
}

export function CostingDetail() {
  const { quote = '' } = useParams<{ quote: string }>()
  const nav = useNavigate()
  const { mode, costings, refresh, scheduleRepairPhases, signoffPreJob, markChassisReceived } = useCostings()
  const { hasPermission, profile } = useAppData()
  const [toast, setToast] = useState('')
  const [preJobOpen, setPreJobOpen] = useState(false)
  const [repairOpen, setRepairOpen] = useState(false)
  const [signoffRole, setSignoffRole] = useState<'sales' | 'production' | null>(null)
  const [chassisReceivedDate, setChassisReceivedDate] = useState('')
  const [prejobCard, setPrejobCard] = useState<PrejobCardStatus | null>(null)

  const c = costings.find((x) => x.quote_number === decodeURIComponent(quote))

  useEffect(() => {
    if (!toast) return
    const t = setTimeout(() => setToast(''), 2200)
    return () => clearTimeout(t)
  }, [toast])

  // §0.21 — does a Pre-Job Card row exist for this calculation? Live mode only (demo data has
  // no calc id / API). Re-runs when the costing's status flips (submit → Pre-Job Sent, both
  // checks → confirmed) so the panel tracks the card without a manual reload.
  useEffect(() => {
    const calcId = c?.calculation_id ?? null
    if (mode !== 'live' || calcId == null) { setPrejobCard(null); return }
    let cancelled = false
    apiGet<PrejobCardStatus | null>(`/api/prejob-cards/by-calculation/${calcId}`)
      .then((card) => { if (!cancelled) setPrejobCard(card) })
      .catch(() => { if (!cancelled) setPrejobCard(null) })
    return () => { cancelled = true }
  }, [mode, c?.calculation_id, c?.status, c?.pre_job_confirmed_at])

  if (!c) {
    return (
      <div className="p-6">
        <Link to="/costings" className="mb-4 inline-flex items-center gap-1 text-sm text-primary">
          <ArrowLeft size={14} /> Back to Costings
        </Link>
        <Card>
          <p className="text-sm text-muted">Costing <span className="font-mono">{quote}</span> not found in the current data set.</p>
        </Card>
      </div>
    )
  }

  const style = STATUS_STYLES[c.status]
  const canPreJob = hasPermission('costings.pre_job_card')

  return (
    <div className="p-4">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
        <div>
          <Link to="/costings" className="mb-1 inline-flex items-center gap-1 text-xs text-primary">
            <ArrowLeft size={12} /> Back to Costings
          </Link>
          <h1 className="flex flex-wrap items-center gap-3 text-xl font-bold text-body">
            <span className="font-mono">{c.quote_number}</span>
            <StatusPillCosting
              status={c.status}
              pulsing={c.status === 'Planning' && !c.planning_acknowledged_at}
            />
            {c.quote_type === 'Repair' && (
              <span className="rounded bg-[#7E22CE]/10 px-2 py-0.5 text-[11px] font-bold uppercase text-[#7E22CE]">Repair</span>
            )}
            {c.status === 'Pre-Job Sent' && !prejobCard && (
              <BottleneckIndicator
                salesAt={c.pre_job_signoff_sales_at ?? null}
                productionAt={c.pre_job_signoff_production_at ?? null}
                size="md"
              />
            )}
          </h1>
          <p className="text-sm text-muted">{c.customer_name} · {c.body_type}</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {canPreJob && c.status === 'Accepted' && (
            <button
              onClick={() => setPreJobOpen(true)}
              className="flex items-center gap-1 rounded-md bg-status-amber px-3 py-2 text-sm font-semibold text-white hover:opacity-90"
            >
              <Send size={14} /> Send Pre-Job Card
            </button>
          )}
          {c.status === 'Repair' && (
            <button
              onClick={() => setRepairOpen(true)}
              className="flex items-center gap-1 rounded-md bg-[#7E22CE] px-3 py-2 text-sm font-semibold text-white hover:opacity-90"
            >
              <Wrench size={14} /> Schedule into MES
            </button>
          )}
          <button
            onClick={() => setToast('PDF generated — sent to printer')}
            className="flex items-center gap-1 rounded-md bg-primary px-3 py-2 text-sm font-semibold text-white hover:bg-primary-dark"
          >
            <Printer size={14} /> Print costing PDF (MES style)
          </button>
        </div>
      </div>

      <div className="mb-4 grid gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <SectionTitle>Configuration</SectionTitle>
          <dl className="grid grid-cols-2 gap-3 text-sm">
            <Row label="Customer" value={c.customer_name} />
            <Row label="Body type" value={c.body_type} />
            <Row label="Quote type" value={c.quote_type} />
            <Row label="Site" value={c.site} />
            <Row
              label="Chassis"
              value={c.requires_chassis ? (c.chassis_supplied_by === 'in-house' ? 'In-house' : 'Customer supplied') : 'Not required'}
              icon={c.requires_chassis ? <Truck size={13} className="text-muted" /> : undefined}
            />
            <Row label="Created by" value={c.created_by} />
            <Row label="Created" value={`${dmy(c.created_at)} ${hhmm(c.created_at)}`} />
            <Row label="Markup" value={`${c.markup_pct}%`} />
          </dl>

          {c.extras_list && c.extras_list.length > 0 && (
            <div className="mt-4">
              <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted">Extras ({c.extras_count})</div>
              <div className="flex flex-wrap gap-1.5">
                {c.extras_list.map((x) => (
                  <span key={x} className="rounded-full bg-surface-alt px-2 py-0.5 text-xs">{x}</span>
                ))}
              </div>
            </div>
          )}

          {c.quote_type === 'Repair' && c.repair_scope && (
            <div className="mt-4 rounded-md border border-[#7E22CE]/30 bg-[#7E22CE]/5 p-3">
              <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-[#7E22CE]">Repair scope</div>
              <p className="text-sm text-body">{c.repair_scope}</p>
              {c.repair_phase_entry && (
                <p className="mt-2 text-xs text-muted"><strong>Phase entry plan: </strong>{c.repair_phase_entry}</p>
              )}
            </div>
          )}
        </Card>

        <Card>
          <SectionTitle>Totals</SectionTitle>
          <dl className="space-y-2 text-sm">
            <TotalRow label="Cost" value={c.cost_zar} />
            {/* WO v4.30 §0.2a — net_total is the headline; when a discount exists, show the pre-discount
                selling as "before discount" + the discount, then the highlighted Net total. No decoration
                when there's no discount (net == selling). */}
            {(c.discount_amount ?? 0) > 0 ? (
              <>
                <TotalRow label="Before discount" value={c.gross_selling_zar ?? c.selling_zar} muted />
                <TotalRow label="Discount" valueText={`- ${zar(c.discount_amount ?? 0)}`} muted />
                <TotalRow label="Net total" value={c.selling_zar} highlight />
              </>
            ) : (
              <TotalRow label="Selling price" value={c.selling_zar} highlight />
            )}
            <TotalRow label="Gross profit" value={c.gross_profit_zar} muted />
            <TotalRow label="Markup" valueText={`${c.markup_pct}%`} muted />
          </dl>
        </Card>
      </div>

      {prejobCard ? (
        /* §0.21 — a Pre-Job Card row exists → it IS the single sign-off surface. */
        <PreJobCardStatusPanel card={prejobCard} onView={() => setPreJobOpen(true)} />
      ) : (c.status === 'Pre-Job Sent' || c.pre_job_signoff_sales_at || c.pre_job_signoff_production_at || c.pre_job_confirmed_at) ? (
        <Tooltip k="costings_detail.prejob_signoff_section">
          {/* WO v4.29 — keep this section visible AFTER confirmation so the sign-off provenance
              (who + when, both roles) is retained on the record, not just while awaiting.
              §0.21: LEGACY path only — renders when no prejob_cards row supersedes it (rows
              in-flight at the v4.33 cutover complete here; new cards never reach this). */}
          <Card data-testid="prejob-legacy-signoff" className={`mb-4 ${c.pre_job_signoff_sales_at && c.pre_job_signoff_production_at ? 'border-status-green' : 'border-status-amber'}`}>
            <SectionTitle>Pre-Job Card sign-offs</SectionTitle>
            <p className="mb-3 text-xs text-muted">
              {c.pre_job_signoff_sales_at && c.pre_job_signoff_production_at
                ? 'Both sign-offs confirmed — retained below for the record (who signed off and when).'
                : 'Two role-gated sign-offs required. When BOTH are confirmed the job auto-moves to Planning status and appears on the Planning Board (Unscheduled lane).'}
            </p>
            <div className="space-y-2">
              <SignoffCheck
                role="sales"
                label="Sales Rep confirms client requirements are correct"
                at={c.pre_job_signoff_sales_at ?? null}
                by={c.pre_job_signoff_sales_by ?? null}
                canSign={hasPermission('costings.signoff_sales')}
                userName={profile.name}
                userRole={profile.role}
                onTick={() => setSignoffRole('sales')}
              />
              <SignoffCheck
                role="production"
                label="Production confirms feasibility & capacity"
                at={c.pre_job_signoff_production_at ?? null}
                by={c.pre_job_signoff_production_by ?? null}
                canSign={hasPermission('costings.signoff_production')}
                userName={profile.name}
                userRole={profile.role}
                onTick={() => setSignoffRole('production')}
              />
            </div>
          </Card>
        </Tooltip>
      ) : null}

      <Card className="mb-4 p-0">
        <div className="p-4 pb-2"><SectionTitle>Bill of materials (illustrative)</SectionTitle></div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-primary text-left text-white">
              <tr>
                <th className="px-3 py-2 font-semibold">Item</th>
                <th className="px-3 py-2 font-semibold">Description</th>
                <th className="px-3 py-2 text-right font-semibold">Qty</th>
                <th className="px-3 py-2 text-right font-semibold">Cost</th>
              </tr>
            </thead>
            <tbody>
              {demoBom.map((l, i) => (
                <tr key={l.sap_item_code} className={i % 2 ? 'bg-surface-alt' : 'bg-white'}>
                  <td className="px-3 py-2 font-mono text-xs">{l.sap_item_code}</td>
                  <td className="px-3 py-2">{l.description}</td>
                  <td className="px-3 py-2 text-right tabular-nums">{l.qty}</td>
                  <td className="px-3 py-2 text-right tabular-nums">{zar(l.cost_zar)}</td>
                </tr>
              ))}
              <tr className="border-t border-line font-semibold">
                <td className="px-3 py-2" colSpan={3}>Total cost</td>
                <td className="px-3 py-2 text-right tabular-nums">{zar(demoBomTotal)}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <p className="px-4 py-2 text-[11px] text-muted">
          Mock BOM (reconciled to the demo job 32891). In Live mode the full BOM would come from the costing app's detail endpoint.
        </p>
      </Card>

      {/* v4.3 — Chassis-received tick box (only after chassis ETA captured) */}
      {c.chassis_eta && (
        <Tooltip k="costings_detail.chassis_received_tick">
          <Card className={`mb-4 border-l-4 ${c.chassis_received_at ? 'border-status-green' : 'border-status-amber'}`}>
            <SectionTitle>Chassis received</SectionTitle>
            <div className="flex flex-wrap items-start gap-4">
              <button
                type="button"
                disabled={!hasPermission('production.chassis_received')}
                onClick={async () => {
                  const by = profile.id === 'rep_burt' ? 'BURT' : profile.id
                  if (c.chassis_received_at) {
                    await markChassisReceived(c.quote_number, null, by)
                    setToast(`Chassis-received tick removed`)
                  } else {
                    const dateIso = chassisReceivedDate || new Date().toISOString().slice(0, 10)
                    await markChassisReceived(c.quote_number, dateIso, by)
                    setToast(`Chassis received recorded for ${c.quote_number}`)
                  }
                }}
                className={`flex h-12 w-12 shrink-0 items-center justify-center rounded-md border-2 transition disabled:cursor-not-allowed disabled:opacity-50 ${
                  c.chassis_received_at
                    ? 'border-status-green bg-status-green text-white'
                    : 'border-status-amber bg-white text-status-amber hover:bg-status-amber/10'
                }`}
                title={hasPermission('production.chassis_received') ? (c.chassis_received_at ? 'Un-tick (mistake correction)' : 'Tick to mark chassis received') : 'Requires Planning role'}
              >
                {c.chassis_received_at ? <CheckCircle2 size={22} /> : <Circle size={22} />}
              </button>
              <div className="flex-1 min-w-[260px]">
                {c.chassis_received_at ? (
                  <div className="space-y-1 text-sm">
                    <div className="font-semibold text-status-green">Chassis received and confirmed.</div>
                    <div className="text-xs text-muted">
                      <ShieldCheck size={11} className="mr-1 inline-block text-status-green" />
                      Received on <strong>{dmy(c.chassis_received_at)}</strong> · ticked by <strong>{c.chassis_received_by}</strong>
                    </div>
                    {c.chassis_eta && (
                      <div className="text-xs text-muted">
                        Planner ETA was {dmy(c.chassis_eta)} —
                        {(() => {
                          const eta = new Date(c.chassis_eta + 'T00:00:00Z').getTime()
                          const got = new Date(c.chassis_received_at + 'T00:00:00Z').getTime()
                          const days = Math.round((got - eta) / 86_400_000)
                          if (days === 0) return ' on time.'
                          if (days < 0) return ` ${Math.abs(days)} day${Math.abs(days) === 1 ? '' : 's'} early.`
                          return ` ${days} day${days === 1 ? '' : 's'} late.`
                        })()}
                      </div>
                    )}
                  </div>
                ) : (
                  <div className="space-y-2">
                    <p className="text-sm text-body">
                      Tick the box when the chassis physically arrives at Icecold.
                      Planner ETA: <strong>{dmy(c.chassis_eta)}</strong> (captured by {c.chassis_eta_captured_by ?? '—'}).
                    </p>
                    <label className="block text-xs text-muted">
                      <span className="font-semibold">Received date</span>
                      <input
                        type="date"
                        value={chassisReceivedDate || new Date().toISOString().slice(0, 10)}
                        max={new Date().toISOString().slice(0, 10)}
                        disabled={!hasPermission('production.chassis_received')}
                        onChange={(e) => setChassisReceivedDate(e.target.value)}
                        className="mt-1 rounded-md border border-line bg-white px-2 py-1 text-sm disabled:bg-surface-alt"
                      />
                      <span className="ml-2 text-[10px] text-muted">(defaults to today; adjust if chassis arrived earlier)</span>
                    </label>
                    {!hasPermission('production.chassis_received') && (
                      <p className="text-[11px] text-muted">
                        <Lock size={11} className="mr-1 inline-block" /> Requires Planning role.
                      </p>
                    )}
                  </div>
                )}
              </div>
            </div>
          </Card>
        </Tooltip>
      )}

      <Card>
        <SectionTitle>Status history</SectionTitle>
        {mode === 'live' && c.production_job_id
          ? <LiveTimeline pjId={c.production_job_id} />
          : <StatusTimeline c={c} statusHex={style.hex} />}
      </Card>

      <PreJobCardModal
        costing={preJobOpen ? c : null}
        onClose={() => setPreJobOpen(false)}
        onConfirm={async () => {
          // WO v4.33 §0.21 — submit drives pre_job_sent server-side; just refresh + navigate.
          await refresh()
          setPreJobOpen(false)
          setToast(`Pre-Job Card sent for check`)
          nav('/costings')
        }}
      />
      <RepairPhasePanel
        costing={repairOpen ? c : null}
        onClose={() => setRepairOpen(false)}
        onSchedule={async (target, phases) => {
          await scheduleRepairPhases(target.quote_number, phases)
          setRepairOpen(false)
          setToast(`Repair plan inserted into MES (${phases.length} phase${phases.length === 1 ? '' : 's'})`)
        }}
      />

      <PreJobSignoffModal
        open={!!signoffRole}
        role={signoffRole ?? 'sales'}
        costing={c}
        userName={profile.name}
        userRoleLabel={profile.role}
        onClose={() => setSignoffRole(null)}
        onConfirm={async (attestation) => {
          const r = signoffRole!
          // Use the rep_code where we have one (Burt -> 'BURT'), else profile.id.
          const by = profile.id === 'rep_burt' ? 'BURT' : profile.id
          await signoffPreJob(c.quote_number, r, attestation, by)
          setSignoffRole(null)
          setToast(`Sign-off recorded (${r === 'sales' ? 'Sales Rep' : 'Production'})`)
        }}
      />

      <Toast message={toast} show={!!toast} />
    </div>
  )
}

// WO v4.33 §0.21 — the new-flow status panel. Reads prejob_cards (the source of truth) and is
// the SINGLE sign-off surface once a card exists; "View Pre-Job Card" reopens the same modal
// (read-only when sent/confirmed), and the email/PDF helpers re-run the §0.11/§3.6 routes.
function PreJobCardStatusPanel({ card, onView }: { card: PrejobCardStatus; onView: () => void }) {
  const rejected = card.status === 'draft' && !!card.reject_reason
  const pill: { s: Status; label: string } =
    card.status === 'pre_job_confirmed' ? { s: 'GREEN', label: 'Pre-Job Confirmed' }
      : card.status === 'sent_for_check' ? { s: 'AMBER', label: 'Sent for check' }
        : rejected ? { s: 'RED', label: 'Rejected — back at draft' }
          : { s: 'GREY', label: 'Draft' }
  const border = pill.s === 'GREEN' ? 'border-status-green' : pill.s === 'RED' ? 'border-status-red' : 'border-status-amber'

  const openEmail = async () => {
    try {
      const e = await apiGet<{ mailto: string }>(`/api/prejob-cards/${card.id}/email`)
      window.location.href = e.mailto                     // §0.11 — opens the user's mail client
    } catch { /* no mail client / offline — non-fatal, the deep-links live in the card too */ }
  }

  return (
    <Tooltip k="costings_detail.prejob_signoff_section">
      <Card data-testid="prejob-status-panel" className={`mb-4 ${border}`}>
        <div className="mb-2 flex flex-wrap items-center gap-2">
          <SectionTitle>Pre-Job Card</SectionTitle>
          <StatusPill status={pill.s} label={pill.label} />
        </div>
        <p className="mb-3 text-xs text-muted">
          The live Pre-Job Card record — both checks below drive confirmation (§0.21 supersedes
          the legacy job-level sign-off).
        </p>
        {rejected && (
          <div className="mb-3 rounded-md border border-status-red/40 bg-status-red/5 p-2 text-xs text-status-red">
            {card.reject_reason}
          </div>
        )}
        <div className="space-y-2">
          <SignoffRow label="Sales Rep" at={card.sales_rep_signoff_at} who={card.sales_rep_username} />
          <SignoffRow label="Planner" at={card.planner_signoff_at} who={card.planner_username} />
        </div>
        <div className="mt-3 flex flex-wrap gap-2">
          <button data-testid="prejob-panel-view" onClick={onView}
            className="rounded-md bg-primary px-3 py-1.5 text-sm font-semibold text-white hover:bg-primary-dark">
            View Pre-Job Card →
          </button>
          <button onClick={() => void openEmail()}
            className="flex items-center gap-1 rounded-md border border-line px-3 py-1.5 text-sm hover:bg-surface-alt">
            <Send size={14} /> Open email draft
          </button>
          <button onClick={() => window.open(`/api/prejob-cards/${card.id}/pdf`, '_blank')}
            className="flex items-center gap-1 rounded-md border border-line px-3 py-1.5 text-sm hover:bg-surface-alt">
            <Printer size={14} /> Download PDF
          </button>
        </div>
      </Card>
    </Tooltip>
  )
}

function SignoffRow({ label, at, who }: { label: string; at: string | null; who: string | null }) {
  const signed = !!at
  return (
    <div className={`flex items-center gap-3 rounded-md border p-3 ${signed ? 'border-status-green/40 bg-status-green/5' : 'border-line bg-white'}`}>
      <span className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-full ${signed ? 'bg-status-green text-white' : 'bg-surface-alt text-muted'}`}>
        {signed ? <CheckCircle2 size={16} /> : <Circle size={14} />}
      </span>
      <div className="flex-1 text-sm">
        <span className="font-semibold text-body">{label}:</span>{' '}
        {signed
          ? <span className="text-status-green">{who ?? '—'} · {dmy(at!)} {hhmm(at!)}</span>
          : <span className="text-muted">awaiting sign-off{who ? ` — assigned: ${who}` : ' — unassigned'}</span>}
      </div>
    </div>
  )
}

function SignoffCheck({
  role,
  label,
  at,
  by,
  canSign,
  userName,
  userRole,
  onTick,
}: {
  role: 'sales' | 'production'
  label: string
  at: string | null
  by: string | null
  canSign: boolean
  userName: string
  userRole: string
  onTick: () => void
}) {
  const signed = !!at
  const tooltipKey =
    role === 'sales'
      ? 'costings_detail.prejob_signoff_sales_check'
      : 'costings_detail.prejob_signoff_production_check'
  const requiredRole = role === 'sales' ? 'Sales Rep' : 'Production Manager'
  return (
    <Tooltip k={tooltipKey}>
      <div className={`rounded-md border p-3 ${signed ? 'border-status-green/40 bg-status-green/5' : 'border-line bg-white'}`}>
        <label className={`flex items-start gap-3 ${signed ? '' : canSign ? 'cursor-pointer' : 'cursor-not-allowed opacity-70'}`}>
          <button
            type="button"
            disabled={signed || !canSign}
            onClick={onTick}
            className={`mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded border ${
              signed
                ? 'border-status-green bg-status-green text-white'
                : canSign
                  ? 'border-primary bg-white text-primary hover:bg-primary-light'
                  : 'border-line bg-surface-alt text-muted'
            }`}
            title={signed ? 'Signed' : canSign ? `Sign as ${requiredRole}` : `Disabled — requires ${requiredRole} role`}
          >
            {signed ? <CheckCircle2 size={16} /> : !canSign ? <Lock size={13} /> : null}
          </button>
          <div className="flex-1">
            <div className={`text-sm font-semibold ${signed ? 'text-status-green' : 'text-body'}`}>{label}</div>
            {!signed && (canSign ? (
              <div className="mt-1 text-xs text-muted">
                You are signed in as <strong>{userName}</strong> ({userRole}). Click the box to open the formal attestation modal.
              </div>
            ) : (
              <div className="mt-1 text-xs text-muted">
                Disabled — requires <strong>{requiredRole}</strong> role to sign off. You are signed in as {userName} ({userRole}).
              </div>
            ))}
          </div>
          {/* WO v4.29 — signed-off stamp to the RIGHT of the label (date + time + who) */}
          {signed && (
            <div className="shrink-0 self-center text-right text-xs text-muted">
              <div className="font-semibold text-status-green">
                <ShieldCheck size={12} className="mr-1 inline-block" /> Signed by {by}
              </div>
              <div className="tabular-nums">{dmy(at)} {hhmm(at!)}</div>
            </div>
          )}
        </label>
      </div>
    </Tooltip>
  )
}

function Row({ label, value, icon }: { label: string; value: string; icon?: React.ReactNode }) {
  return (
    <div>
      <dt className="text-xs uppercase tracking-wide text-muted">{label}</dt>
      <dd className="flex items-center gap-1 text-body">{value} {icon}</dd>
    </div>
  )
}

function TotalRow({
  label,
  value,
  valueText,
  highlight,
  muted,
}: {
  label: string
  value?: number
  valueText?: string
  highlight?: boolean
  muted?: boolean
}) {
  return (
    <div className="flex items-center justify-between">
      <dt className={muted ? 'text-muted' : 'text-body'}>{label}</dt>
      <dd className={`tabular-nums ${highlight ? 'text-lg font-bold text-primary' : 'font-semibold'}`}>
        {valueText ?? (value != null ? zar(value) : '—')}
      </dd>
    </div>
  )
}

function StatusTimeline({ c, statusHex }: { c: Costing; statusHex: string }) {
  const steps = [
    {
      label: 'Created',
      at: c.created_at,
      kind: 'done' as const,
      detail: `by ${c.created_by}`,
    },
    {
      label: 'Accepted',
      at: c.accepted_at,
      kind: (c.accepted_at || c.status === 'Repair' || c.status === 'Pre-Job Sent' || c.status === 'Pre-Job Confirmed' ? 'done' : c.status === 'Rejected' ? 'rejected' : 'pending') as 'done' | 'pending' | 'rejected',
      detail: c.status === 'Rejected' ? c.rejection_reason : undefined,
    },
    {
      label: 'Pre-Job Sent',
      at: c.pre_job_sent_at,
      kind: (c.pre_job_sent_at ? 'done' : c.status === 'Repair' ? 'skipped' : 'pending') as 'done' | 'pending' | 'skipped',
    },
    {
      label: 'Pre-Job Confirmed',
      at: c.pre_job_confirmed_at,
      kind: (c.pre_job_confirmed_at ? 'done' : c.status === 'Repair' ? 'skipped' : 'pending') as 'done' | 'pending' | 'skipped',
      detail: c.job_number_assigned ? `Job number ${c.job_number_assigned} issued` : undefined,
    },
  ]
  return (
    <ol className="space-y-3">
      {steps.map((s, i) => {
        const Icon =
          s.kind === 'done'
            ? CheckCircle2
            : s.kind === 'rejected'
              ? XCircle
              : s.kind === 'skipped'
                ? Circle
                : AlertCircle
        const colour =
          s.kind === 'done'
            ? 'text-status-green'
            : s.kind === 'rejected'
              ? 'text-status-red'
              : s.kind === 'skipped'
                ? 'text-muted'
                : 'text-status-amber'
        return (
          <li key={i} className="flex items-start gap-3">
            <Icon size={20} className={colour} />
            <div className="flex-1">
              <div className="text-sm font-semibold text-body" style={s.kind === 'done' ? { color: statusHex } : undefined}>
                {s.label}
              </div>
              {s.at && <div className="text-xs text-muted">{dmy(s.at)} {hhmm(s.at)}</div>}
              {s.detail && <div className="text-xs text-muted">{s.detail}</div>}
            </div>
          </li>
        )
      })}
    </ol>
  )
}

// WO v4.19 — live lifecycle timeline from the production-job (derived from its
// timestamp columns server-side). Falls back to the derived StatusTimeline when
// there's no production_job (pre-accept) or the API is unreachable.
const TIMELINE_LABELS: Record<string, string> = {
  accepted: 'Accepted into production',
  pre_job_sent: 'Pre-Job Card sent',
  pre_job_signoff_sales: 'Sales sign-off',
  pre_job_signoff_production: 'Production sign-off',
  pre_job_confirmed: 'Pre-Job confirmed',
  planning_ack: 'Planning acknowledged',
  chassis_received: 'Chassis received',
}

function LiveTimeline({ pjId }: { pjId: number }) {
  const [events, setEvents] = useState<{ event_type: string; occurred_at: string; actor: string | null }[] | null>(null)
  const [err, setErr] = useState(false)
  useEffect(() => {
    let alive = true
    apiGet<{ event_type: string; occurred_at: string; actor: string | null }[]>(`/api/production-jobs/${pjId}/timeline`)
      .then((e) => { if (alive) setEvents(e) })
      .catch(() => { if (alive) setErr(true) })
    return () => { alive = false }
  }, [pjId])

  if (err) return <p className="text-xs text-muted">Live timeline unavailable.</p>
  if (!events) return <p className="text-xs text-muted">Loading timeline…</p>
  if (events.length === 0) return <p className="text-xs text-muted">No lifecycle events recorded yet.</p>
  return (
    <ol className="space-y-3">
      {events.map((e, i) => (
        <li key={i} className="flex items-start gap-3">
          <CheckCircle2 size={20} className="text-status-green" />
          <div className="flex-1">
            <div className="text-sm font-semibold text-body">
              {TIMELINE_LABELS[e.event_type] ?? e.event_type.replace(/_/g, ' ')}
            </div>
            <div className="text-xs text-muted">
              {dmy(e.occurred_at)} {hhmm(e.occurred_at)}{e.actor ? ` · ${e.actor}` : ''}
            </div>
          </div>
        </li>
      ))}
    </ol>
  )
}
