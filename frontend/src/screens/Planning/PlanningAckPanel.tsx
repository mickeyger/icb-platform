import { useEffect, useMemo, useState } from 'react'
import {
  ArrowRightCircle, Lock, Truck, ShieldCheck, Calendar, BookOpen, X, Wrench, AlertCircle, Loader2,
} from 'lucide-react'
import { Link } from 'react-router-dom'
import { SidePanel } from '../../components/ui/overlays'
import { Tooltip } from '../../components/ui/Tooltip'
import { useAppData } from '../../store/AppDataContext'
import { useCostings, type ChassisCatalogue, type ChassisEtaPayload } from '../../store/CostingsContext'
import { data as mockData } from '../../data/mockData'
import { apiGet } from '../../lib/api'
import { ChassisFieldsForm, type ChassisFieldValues, type ChassisFieldLocks } from '../Chassis/ChassisFieldsForm'
import type { ChassisPrefill } from '../Chassis/chassisShared'
import { zar, dmy, hhmm } from '../../lib/format'
import type { Costing } from '../../data/costingsData'

/**
 * Side panel opened when the planner clicks a pulsing Unscheduled card on the
 * Planning Board (Work Order v4 §5.5 + v4.2 §5.4-5.6). Shows the full costing
 * detail, the chassis-capture section (in-house vs external), and an Acknowledge
 * button gated by both `planning.acknowledge` permission AND chassis_eta capture.
 */
export function PlanningAckPanel({
  costing,
  onClose,
  onAcknowledge,
}: {
  costing: Costing | null
  onClose: () => void
  onAcknowledge: (c: Costing, payload: ChassisEtaPayload) => void | Promise<void>
}) {
  const { profile, hasPermission, apiMode } = useAppData()
  const { captureChassisEta, loadChassisCatalogue } = useCostings()
  const canAck = hasPermission('planning.acknowledge')

  // Local chassis-capture state. Initialised from the costing's chassis_data on
  // open, then mutated as the planner edits fields. The Acknowledge button only
  // enables once `eta` is non-empty.
  const inHouse = costing?.chassis_supplied_by === 'in-house'
  // WO v4.34 §3.9 — sign-off integrity: once the linked Pre-Job Card is CONFIRMED with a chassis
  // supplied, that attested spec is the source of truth. chassis_type + VIN lock read-only on the
  // ack so a planner can't silently rewrite what Sales + Production already attested to.
  const card = costing?.prejob_card
  const chassisLocked = card?.status === 'pre_job_confirmed' && !!card?.chassis_make_model
  // §3.9 refine (BA 2026-06-14) — lock the VIN read-only ONLY when one was actually attested at
  // pre-job; if the card left it blank, the planner captures it here at ack (it then lands on the
  // chassis record server-side).
  // WO — broaden the §3.9 lock: lock the VIN read-only when one is KNOWN anywhere — either ATTESTED at
  // pre-job (card.vin_number) OR already CAPTURED on the linked chassis (card.chassis_vin = the live
  // chassis_records.vin, e.g. a Chassis-page manual capture after pre-job). Attested wins as the displayed
  // value (it gates the body_attached swap-rule); else the captured VIN of record. If NEITHER is set the box
  // stays editable so the planner can fill the VIN in when the chassis physically arrives.
  const attestedVin = card?.status === 'pre_job_confirmed' ? (card?.vin_number ?? null) : null
  const knownVin = attestedVin ?? card?.chassis_vin ?? null
  const vinLocked = !!knownVin
  const seed: ChassisEtaPayload = useMemo(() => {
    if (!costing) return { chassis_eta: '' }
    const cd = costing.chassis_data ?? {}
    return {
      chassis_eta: costing.chassis_eta ?? '',
      chassis_vin: (knownVin ?? cd.chassis_vin) ?? '',
      chassis_model: (chassisLocked ? card?.chassis_make_model : cd.chassis_model) ?? '',
      customer_dealer: cd.customer_dealer ?? '',
      dealer_id: cd.dealer_id ?? null,                   // WO v4.34.1 §0.3 — structured chassis supplier
      dealer_name: cd.dealer_name ?? '',
      tail_lift_code: cd.tail_lift_code ?? '',
      chassis_inhouse_bom: cd.chassis_inhouse_bom ?? [],
      job_number: costing.job_number_assigned ?? '',     // WO v4.34 §0.8 — pre-fill the override with the current number
    }
  }, [costing, chassisLocked, vinLocked, knownVin, card])
  const [form, setForm] = useState<ChassisEtaPayload>(seed)
  useEffect(() => setForm(seed), [seed])
  // WO v4.36.5 §3.3 — the linked chassis id (from the prefill), for the read-only "Edit on Chassis page" link.
  const [chassisId, setChassisId] = useState<number | null>(null)

  // WO v4.36b — chassis-field unification: overlay the LIVE linked chassis fields from chassis_records (the
  // single source of truth) so the ack shows what the Chassis page shows — the identity fields
  // (customer/contact/telephone/description/notes) the seed lacks, and the live dealer/type/tail-lift. The
  // seed memo still provides the costing-blob fallback + the §3.9 attested values; this overlays the chassis
  // row when present. costing is a click-time snapshot, so this fires once per open (no mid-edit clobber).
  useEffect(() => {
    const jobId = costing?.production_job_id
    if (!jobId) return
    let live = true
    apiGet<ChassisPrefill>(`/api/production-jobs/${jobId}/chassis-prefill`).then((p) => {
      if (!live) return
      setChassisId(p.chassis_id ?? null)
      setForm((f) => ({
        ...f,
        customer_name: p.customer_name ?? f.customer_name,
        contact_person: p.contact_person ?? f.contact_person,
        telephone: p.telephone ?? f.telephone,
        description: p.description ?? f.description,
        chassis_notes: p.chassis_notes ?? f.chassis_notes,
        chassis_model: chassisLocked ? f.chassis_model : (p.chassis_type ?? f.chassis_model),
        dealer_id: p.dealer_id ?? f.dealer_id,
        dealer_name: p.dealer_name ?? f.dealer_name,
        tail_lift_code: p.tail_lift_code ?? f.tail_lift_code,
        // ETA lives on production_jobs.chassis_eta; prefer the LIVE job value so an ETA captured on the
        // Chassis page seeds the ack (both directions — the Chassis page already reads it via get_detail).
        chassis_eta: p.chassis_eta ?? f.chassis_eta,
      }))
    }).catch(() => {})
    return () => { live = false }
  }, [costing, chassisLocked])

  const etaCaptured = !!form.chassis_eta

  async function handleAcknowledge() {
    if (!costing) return
    const by = profile.id === 'rep_burt' ? 'BURT' : profile.id
    // WO v4.29 D2: in LIVE mode the ack (onAcknowledge → ackPlanning → POST /planning-ack) captures the
    // chassis ETA + rich chassis data on the production job in one step. The legacy calc /chassis-eta
    // endpoint is status-gated to 'planning' and deadlocked the ack (the calc is still 'accepted' at
    // this point), so it now runs in MOCK mode only (offline-demo local state). See ADR 0016.
    if (apiMode !== 'live') {
      await captureChassisEta(costing.quote_number, form, by)
    }
    await onAcknowledge(costing, form)
  }

  return (
    <SidePanel
      title={costing ? `New job · ${costing.quote_number}` : ''}
      open={!!costing}
      onClose={onClose}
      width="w-[560px]"
    >
      {costing && (
        <div className="space-y-4 text-sm">
          <div>
            <div className="text-lg font-semibold text-body">{costing.customer_name}</div>
            <div className="text-xs text-muted">{costing.body_type}</div>
          </div>

          <div className="rounded-md border border-[#06B6D4]/40 bg-[#06B6D4]/10 px-3 py-2 text-xs text-[#0E7490]">
            Status: <strong>Planning (pulsing)</strong> — awaiting Planning acknowledgement.
          </div>

          <div className="grid grid-cols-2 gap-3 rounded-md bg-surface-alt p-3 text-xs">
            <Field label="Job number" value={costing.job_number_assigned ?? '—'} />
            <Field label="Site" value={costing.site} />
            <Field label="Promised" value={costing.promised_date ? dmy(costing.promised_date) : '—'} />
            <Field
              label="Chassis"
              value={costing.requires_chassis ? (inHouse ? 'In-house build' : 'Customer supplied') : 'Not required'}
              icon={costing.requires_chassis ? <Truck size={11} className="text-muted" /> : undefined}
            />
          </div>

          <div>
            <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted">Costing</div>
            <div className="grid grid-cols-3 gap-2 rounded-md bg-surface-alt p-3 text-center text-xs">
              <Stat label="Cost" value={zar(costing.cost_zar)} />
              <Stat label="Selling" value={zar(costing.selling_zar)} highlight />
              <Stat label="GP" value={zar(costing.gross_profit_zar)} />
            </div>
            <div className="mt-1 text-[11px] text-muted">Markup {costing.markup_pct}%</div>
          </div>

          <div>
            <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted">Sign-offs</div>
            <ul className="space-y-1 text-xs">
              <li><ShieldCheck size={11} className="mr-1 inline-block text-status-green" />
                Accepted by customer: <strong>{costing.accepted_at ? `${dmy(costing.accepted_at)} ${hhmm(costing.accepted_at)}` : '—'}</strong>
              </li>
              {/* §0.21 — when a Pre-Job Card supersedes the legacy job sign-offs, show the
                  NEW-flow provenance (Sales Rep + Planner from the card); else the legacy two. */}
              {costing.prejob_card ? (
                <>
                  <li><ShieldCheck size={11} className="mr-1 inline-block text-status-green" />
                    Sales Rep: <strong>{costing.prejob_card.sales_rep_username ?? '—'}</strong> {costing.prejob_card.sales_rep_signoff_at ? `· ${dmy(costing.prejob_card.sales_rep_signoff_at)} ${hhmm(costing.prejob_card.sales_rep_signoff_at)}` : '· awaiting'}
                  </li>
                  <li><ShieldCheck size={11} className="mr-1 inline-block text-status-green" />
                    Planner: <strong>{costing.prejob_card.planner_username ?? '—'}</strong> {costing.prejob_card.planner_signoff_at ? `· ${dmy(costing.prejob_card.planner_signoff_at)} ${hhmm(costing.prejob_card.planner_signoff_at)}` : '· awaiting'}
                  </li>
                </>
              ) : (
                <>
                  <li><ShieldCheck size={11} className="mr-1 inline-block text-status-green" />
                    Sales sign-off: <strong>{costing.pre_job_signoff_sales_by ?? '—'}</strong> {costing.pre_job_signoff_sales_at && `· ${dmy(costing.pre_job_signoff_sales_at)} ${hhmm(costing.pre_job_signoff_sales_at)}`}
                  </li>
                  <li><ShieldCheck size={11} className="mr-1 inline-block text-status-green" />
                    Production sign-off: <strong>{costing.pre_job_signoff_production_by ?? '—'}</strong> {costing.pre_job_signoff_production_at && `· ${dmy(costing.pre_job_signoff_production_at)} ${hhmm(costing.pre_job_signoff_production_at)}`}
                  </li>
                </>
              )}
            </ul>
          </div>

          {/* v4.2 — chassis sections */}
          {costing.requires_chassis && inHouse && (
            <ChassisInHouseSection
              form={form}
              setForm={setForm}
              canEdit={canAck}
              loadCatalogue={loadChassisCatalogue}
            />
          )}
          {costing.requires_chassis && !inHouse && (
            <ChassisExternalSection
              form={form}
              setForm={setForm}
              canEdit={canAck}
              chassisLocked={chassisLocked}
              vinLocked={vinLocked}
              chassisId={chassisId}
            />
          )}

          <div className="rounded-md border border-line bg-white p-3">
            <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted">Acknowledge</div>
            <p className="mb-2 text-xs text-body">
              This job is awaiting acknowledgement by the Planning team before it can be scheduled.
              You are signed in as <strong>{profile.name}</strong> ({profile.role}).
            </p>
            {/* WO v4.34 §0.8 — job-number override (SAP-assigned during the parallel run); hidden
                once SAP_RETIRED or the number is locked (§0.9 forces the quote-derived value). */}
            {canAck && !costing.sap_retired && !costing.job_number_locked && (
              <label className="mb-2 block text-xs text-muted">
                Job number <span className="text-[10px]">(edit only to record an SAP-assigned number)</span>
                <input
                  data-testid="planning-ack-job-number"
                  value={form.job_number ?? ''}
                  onChange={(e) => setForm((f) => ({ ...f, job_number: e.target.value }))}
                  className="mt-1 w-full rounded-md border border-line px-2 py-1.5 text-sm text-body"
                />
              </label>
            )}
            <Tooltip k="planning_board.acknowledge_receipt_button" placement="top">
              {canAck ? (
                <button
                  onClick={handleAcknowledge}
                  disabled={!etaCaptured}
                  title={etaCaptured ? '' : 'Capture the chassis ETA above first'}
                  className="flex w-full items-center justify-center gap-2 rounded-md bg-[#06B6D4] py-2.5 text-sm font-semibold text-white hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40"
                >
                  <ArrowRightCircle size={14} /> Acknowledge receipt — schedule into MES
                </button>
              ) : (
                <button
                  disabled
                  className="flex w-full cursor-not-allowed items-center justify-center gap-2 rounded-md border border-line bg-surface-alt py-2.5 text-sm font-semibold text-muted"
                >
                  <Lock size={13} /> Requires Planning role to acknowledge
                </button>
              )}
            </Tooltip>
            {canAck && !etaCaptured && (
              <p className="mt-2 flex items-center gap-1 text-[11px] text-status-amber">
                <AlertCircle size={12} /> Capture the chassis ETA above first to enable acknowledgement.
              </p>
            )}
          </div>
        </div>
      )}
    </SidePanel>
  )
}

// ── Chassis sections ───────────────────────────────────────────────────────

function ChassisInHouseSection({
  form,
  setForm,
  canEdit,
  loadCatalogue,
}: {
  form: ChassisEtaPayload
  setForm: React.Dispatch<React.SetStateAction<ChassisEtaPayload>>
  canEdit: boolean
  loadCatalogue: () => Promise<ChassisCatalogue | null>
}) {
  const bom = form.chassis_inhouse_bom ?? []
  const [catOpen, setCatOpen] = useState(false)
  const [cat, setCat] = useState<ChassisCatalogue | null>(null)
  const [loadingCat, setLoadingCat] = useState(false)

  async function openLiveCatalogue() {
    setCatOpen(true)
    if (cat) return
    setLoadingCat(true)
    const live = await loadCatalogue()
    setLoadingCat(false)
    setCat(live)
  }

  return (
    <Tooltip k="costings_detail.chassis_inhouse_section">
      <div className="rounded-md border border-primary/30 bg-primary-light/30 p-3">
        <div className="mb-2 flex items-center justify-between">
          <div className="text-xs font-semibold uppercase tracking-wide text-primary">
            In-house chassis · BOM ({bom.length} components)
          </div>
          <button
            onClick={openLiveCatalogue}
            className="flex items-center gap-1 rounded-md border border-primary bg-white px-2 py-1 text-[11px] font-semibold text-primary hover:bg-primary-light"
          >
            <BookOpen size={11} /> Browse live catalogue
          </button>
        </div>
        <div className="overflow-hidden rounded border border-line bg-white text-xs">
          <table className="w-full">
            <thead className="bg-surface-alt text-left">
              <tr>
                <th className="px-2 py-1 font-semibold text-muted">Category</th>
                <th className="px-2 py-1 font-semibold text-muted">Description</th>
                <th className="px-2 py-1 font-mono text-[10px] font-semibold text-muted">Item code</th>
              </tr>
            </thead>
            <tbody>
              {bom.length === 0 ? (
                <tr><td colSpan={3} className="px-2 py-3 text-center text-muted">No in-house chassis BOM captured on the costing.</td></tr>
              ) : bom.map((r, i) => (
                <tr key={i} className={i % 2 ? 'bg-surface-alt' : ''}>
                  <td className="px-2 py-1 font-semibold">{r.category}</td>
                  <td className="px-2 py-1">{r.description}</td>
                  <td className="px-2 py-1 font-mono text-[10px] text-muted">{r.item_code}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <Tooltip k="costings_detail.chassis_eta_picker">
          <label className="mt-3 block text-xs">
            <span className="font-semibold text-muted">Build-ready ETA <span className="text-status-red">*</span></span>
            <input
              type="date"
              value={dateOnly(form.chassis_eta)}
              disabled={!canEdit}
              onChange={(e) => setForm((f) => ({ ...f, chassis_eta: e.target.value }))}
              className="mt-1 w-full rounded-md border border-line bg-white px-2 py-1.5 text-sm disabled:bg-surface-alt disabled:text-muted"
            />
            <span className="mt-1 block text-[10px] text-muted">
              <Calendar size={10} className="mr-1 inline-block" />
              Required — when will the in-house chassis be build-ready for the body fitment?
            </span>
          </label>
        </Tooltip>

        {catOpen && (
          <CataloguePopover loading={loadingCat} cat={cat} onClose={() => setCatOpen(false)} />
        )}
      </div>
    </Tooltip>
  )
}

function ChassisExternalSection({
  form,
  setForm,
  canEdit,
  chassisLocked,
  vinLocked,
  chassisId,
}: {
  form: ChassisEtaPayload
  setForm: React.Dispatch<React.SetStateAction<ChassisEtaPayload>>
  canEdit: boolean
  chassisLocked?: boolean
  vinLocked?: boolean
  chassisId?: number | null
}) {
  // WO v4.36b — chassis-field unification: the ack uses the SAME ChassisFieldsForm as the Chassis page Edit
  // modal, so both present these fields identically over chassis_records. Map the ack form (ChassisEtaPayload)
  // <-> ChassisFieldValues (make<->chassis_model, vin<->chassis_vin, notes<->chassis_notes). §3.9 locks map to
  // per-field read-only; a non-acknowledger (read-only) locks every field.
  const values: ChassisFieldValues = {
    customer_name: form.customer_name ?? '',
    make: form.chassis_model ?? '',
    dealer_id: form.dealer_id ?? null,
    dealer_name: form.dealer_name ?? null,
    chassis_eta: dateOnly(form.chassis_eta),
    contact_person: form.contact_person ?? '',
    telephone: form.telephone ?? '',
    vin: form.chassis_vin ?? '',
    tail_lift_code: form.tail_lift_code ?? '',
    description: form.description ?? '',
    notes: form.chassis_notes ?? '',
  }
  const onField = (patch: Partial<ChassisFieldValues>) => setForm((f) => {
    const n: ChassisEtaPayload = { ...f }
    if ('customer_name' in patch) n.customer_name = patch.customer_name
    if ('make' in patch) n.chassis_model = patch.make
    if ('dealer_id' in patch) n.dealer_id = patch.dealer_id ?? null
    if ('dealer_name' in patch) n.dealer_name = patch.dealer_name ?? undefined
    if ('chassis_eta' in patch) n.chassis_eta = patch.chassis_eta ?? ''
    if ('contact_person' in patch) n.contact_person = patch.contact_person
    if ('telephone' in patch) n.telephone = patch.telephone
    if ('vin' in patch) n.chassis_vin = patch.vin
    if ('tail_lift_code' in patch) n.tail_lift_code = patch.tail_lift_code
    if ('description' in patch) n.description = patch.description
    if ('notes' in patch) n.chassis_notes = patch.notes
    return n
  })
  const locks: ChassisFieldLocks = canEdit
    ? { chassisType: chassisLocked, vin: vinLocked }
    : { customer: true, chassisType: true, dealer: true, eta: true, contact: true, telephone: true,
        vin: true, tailLift: true, description: true, notes: true }

  return (
    <Tooltip k="costings_detail.chassis_external_section">
      <div className="rounded-md border border-status-amber/40 bg-status-amber/5 p-3">
        <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-status-amber">
          External (customer-supplied) chassis
        </div>
        <ChassisFieldsForm
          values={values} onChange={onField} tailLifts={mockData.tail_lifts} testidPrefix="planning-ack"
          locks={locks}
          etaHint={<><Calendar size={10} className="mr-1 inline-block" />Required — when will the customer’s chassis arrive at Icecold?</>}
          vinNote={vinLocked ? 'Attested upstream — locked.' : undefined}
          editNotice={!canEdit ? (
            <>These chassis fields are maintained on the {chassisId
              ? <Link to={`/chassis/${chassisId}`} className="font-semibold text-primary underline">Chassis page</Link>
              : 'Chassis page'}.</>
          ) : undefined}
        />
      </div>
    </Tooltip>
  )
}

// ── Helpers ────────────────────────────────────────────────────────────────

function CataloguePopover({
  loading,
  cat,
  onClose,
}: {
  loading: boolean
  cat: ChassisCatalogue | null
  onClose: () => void
}) {
  return (
    <div className="mt-3 rounded-md border border-line bg-white p-3 text-xs">
      <div className="mb-2 flex items-center justify-between">
        <div className="text-xs font-semibold uppercase tracking-wide text-muted">
          Live chassis catalogue
          {loading && <span className="ml-2 text-muted"><Loader2 size={11} className="inline animate-spin" /> loading…</span>}
        </div>
        <button onClick={onClose} className="rounded p-0.5 text-muted hover:bg-surface-alt"><X size={13} /></button>
      </div>
      {!loading && !cat && (
        <div className="rounded-md border border-dashed border-line bg-surface-alt p-3 text-center text-muted">
          <Wrench size={14} className="mx-auto mb-1" />
          Live catalogue unavailable — the costing app is offline or not authenticated.<br/>
          Use the saved BOM above as the reference.
        </div>
      )}
      {!loading && cat && (
        <div className="space-y-3">
          <CatalogueList label="Fixed (steel + running gear)" rows={cat.constants.map((c) => ({ left: c.category.toUpperCase(), mid: c.name, right: zar(c.unit_price) }))} />
          <CatalogueList label="Selectable options" rows={cat.options.map((o) => ({ left: o.kind.toUpperCase(), mid: o.label + (o.axle_count ? ` · ${o.axle_count}-axle` : '') + (o.tyre_style ? ` · ${o.tyre_style}` : ''), right: zar(o.price ?? 0) }))} />
        </div>
      )}
    </div>
  )
}

function CatalogueList({ label, rows }: { label: string; rows: { left: string; mid: string; right: string }[] }) {
  return (
    <div>
      <div className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-muted">{label} ({rows.length})</div>
      <div className="max-h-48 overflow-y-auto rounded border border-line">
        <table className="w-full text-[11px]">
          <tbody>
            {rows.map((r, i) => (
              <tr key={i} className={i % 2 ? 'bg-surface-alt' : ''}>
                <td className="px-2 py-1 font-semibold text-muted">{r.left}</td>
                <td className="px-2 py-1">{r.mid}</td>
                <td className="px-2 py-1 text-right font-mono text-muted">{r.right}</td>
              </tr>
            ))}
            {rows.length === 0 && (
              <tr><td colSpan={3} className="px-2 py-2 text-center text-muted">No entries.</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function dateOnly(iso: string | null | undefined): string {
  if (!iso) return ''
  return iso.length >= 10 ? iso.slice(0, 10) : iso
}

function Field({ label, value, icon }: { label: string; value: string; icon?: React.ReactNode }) {
  return (
    <div>
      <dt className="text-[10px] uppercase tracking-wide text-muted">{label}</dt>
      <dd className="flex items-center gap-1 text-body">{value} {icon}</dd>
    </div>
  )
}

function Stat({ label, value, highlight }: { label: string; value: string; highlight?: boolean }) {
  return (
    <div>
      <div className="text-[10px] uppercase tracking-wide text-muted">{label}</div>
      <div className={`tabular-nums ${highlight ? 'text-[#06B6D4] font-bold' : 'font-semibold text-body'}`}>{value}</div>
    </div>
  )
}
