/** WO v4.28 §0.8 — chassis detail + multi-cycle lifecycle history + VCL/DCL capture (write-path).
 * Groups events by cycle; each cycle shows its VCL (book-in) + DCL (dispatch). Capture buttons are
 * permission-gated (admin sees both); the backend enforces chassis.vcl / chassis.dcl regardless. */
import { useCallback, useEffect, useMemo, useState } from 'react'
import { useParams, Link } from 'react-router-dom'
import { ArrowLeft, Truck, LogIn, LogOut, Image, Pencil, X, RotateCcw, AlertTriangle, FileDown } from 'lucide-react'

import { apiGet, apiPatch, apiPost, ApiError, handleApiError } from '../../lib/api'
import { useToast } from '../../components/ui/toast'
import { useAppData } from '../../store/AppDataContext'
import { Card } from '../../components/ui/primitives'
import { Skeleton, EmptyState, Spinner } from '../../components/ui/feedback'
import { CHASSIS_STATUS_STYLE, CHASSIS_PROVENANCE, type ChassisEvent, type ChassisRecordDetail } from './types'
import { VclDclForm, type ChecklistItem } from './VclDclForm'
import { ChassisFieldsForm, type ChassisFieldValues } from './ChassisFieldsForm'
import { data as mockData } from '../../data/mockData'
import { type UnlinkedJob, type ChassisPrefill, VIN_PROVENANCE } from './chassisShared'

function ProvenancePill({ via, source }: { via?: string | null; source: string }) {
  const p = via ? CHASSIS_PROVENANCE[via] : undefined
  const label = p?.label ?? source.replace(/_/g, ' ')
  const style = p?.style ?? 'bg-surface-alt text-muted'
  return <span className={`inline-block rounded-full px-2.5 py-1 text-xs font-semibold ${style}`}>{label}</span>
}

// WO v4.34.1 §3.4b — VIN provenance pill (where a captured VIN came from).
const VIN_SOURCE: Record<string, string> = {
  chassis_page_manual: 'VIN · manually captured',
  vcl: 'VIN · from VCL',
}
function VinSourcePill({ source }: { source?: string | null }) {
  if (!source) return null
  const label = VIN_SOURCE[source] ?? `VIN · ${source.replace(/_/g, ' ')}`
  return (
    <span data-testid="chassis-vin-source"
          className="inline-block rounded-full bg-primary-light/60 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-primary">
      {label}
    </span>
  )
}

function Field({ label, value }: { label: string; value?: string | null }) {
  return (
    <div>
      <div className="text-[11px] font-semibold uppercase tracking-wide text-muted">{label}</div>
      <div className="text-sm text-body">{value || '—'}</div>
    </div>
  )
}

function EventCard({ ev }: { ev: ChassisEvent }) {
  const isVcl = ev.event_type === 'VCL'
  const checklist = ev.checklist_json && typeof ev.checklist_json === 'object'
    ? Object.entries(ev.checklist_json as Record<string, unknown>) : []
  return (
    <div data-testid="chassis-event" data-event-type={ev.event_type}
         className="rounded-md border border-line bg-white p-3">
      <div className="mb-1 flex items-center gap-2">
        <span className={`inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[11px] font-bold ${isVcl ? 'bg-status-amber/15 text-status-amber' : 'bg-status-green/15 text-status-green'}`}>
          {isVcl ? <LogIn size={12} /> : <LogOut size={12} />} {ev.event_type}
        </span>
        <span className="text-sm font-semibold text-body">{ev.event_date || 'date not set'}</span>
        {ev.legacy_reference && <span className="text-xs text-muted">ref: {ev.legacy_reference}</span>}
      </div>
      {checklist.length > 0 && (
        <dl className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
          {checklist.map(([k, v]) => (
            <div key={k} className="flex justify-between gap-2">
              <dt className="text-muted">{k.replace(/_/g, ' ')}</dt>
              <dd className="font-medium text-body">{v === true ? '✓' : v === false ? '✗' : String(v)}</dd>
            </div>
          ))}
        </dl>
      )}
      {ev.photos.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-2">
          {ev.photos.map((p) => (
            <a key={p.id} href={p.url || '#'} target="_blank" rel="noreferrer"
               className="flex items-center gap-1 rounded border border-line px-2 py-1 text-xs text-primary hover:bg-primary-light">
              <Image size={12} /> {p.original_filename || `photo ${p.id}`}
            </a>
          ))}
        </div>
      )}
      {ev.notes && <p className="mt-2 text-xs text-muted">{ev.notes}</p>}
    </div>
  )
}

export function ChassisDetail() {
  const { id } = useParams<{ id: string }>()
  const toast = useToast()
  const { hasPermission, isAdmin } = useAppData()
  const [rec, setRec] = useState<ChassisRecordDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [checklists, setChecklists] = useState<Record<string, ChecklistItem[]>>({})
  const [capture, setCapture] = useState<'VCL' | 'DCL' | null>(null)
  const [editing, setEditing] = useState(false)
  const [capturingVin, setCapturingVin] = useState(false)
  const [restoring, setRestoring] = useState(false)

  const load = useCallback(() => {
    setLoading(true)
    apiGet<ChassisRecordDetail>(`/api/chassis-records/${id}`)
      .then(setRec)
      .catch((e) => handleApiError(e, toast.push))
      .finally(() => setLoading(false))
  }, [id, toast])

  // WO v4.36a §3.6 STEP 7 — restore a soft-deleted / merged tombstone (admin only; clears deleted_at +
  // merged_into_id, does NOT re-point FKs).
  async function restore() {
    if (!rec) return
    setRestoring(true)
    try {
      await apiPatch(`/api/admin/chassis/${rec.id}/restore`, {})
      toast.push({ kind: 'ok', message: 'Chassis restored.' })
      load()
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) toast.push({ kind: 'warn', message: e.detail || 'Can’t restore.' })
      else handleApiError(e, toast.push)
    } finally {
      setRestoring(false)
    }
  }

  useEffect(() => { load() }, [load])
  useEffect(() => {
    apiGet<Record<string, ChecklistItem[]>>('/api/chassis-records/checklists')
      .then(setChecklists).catch(() => { /* templates optional for read */ })
  }, [])

  const cycles = useMemo(() => {
    if (!rec) return [] as { cycle: number; events: ChassisEvent[] }[]
    const by = new Map<number, ChassisEvent[]>()
    for (const e of rec.events) {
      if (!by.has(e.cycle_number)) by.set(e.cycle_number, [])
      by.get(e.cycle_number)!.push(e)
    }
    return [...by.entries()].sort((a, b) => a[0] - b[0])
      .map(([cycle, events]) => ({ cycle, events: events.sort((a, b) => a.event_type.localeCompare(b.event_type)) }))
  }, [rec])

  if (loading) return <div className="p-4"><Skeleton rows={8} /></div>
  if (!rec) return <div className="p-4"><EmptyState title="Chassis not found" hint="This chassis record does not exist." /></div>

  const statusCls = CHASSIS_STATUS_STYLE[rec.status] ?? 'bg-surface-alt text-muted'
  const canVcl = isAdmin || hasPermission('chassis.vcl')
  const canDcl = isAdmin || hasPermission('chassis.dcl')
  const canEdit = isAdmin || hasPermission('chassis.update')

  return (
    <div className="p-4" data-testid="chassis-detail">
      <Link to="/chassis" className="mb-3 inline-flex items-center gap-1 text-sm text-primary hover:underline">
        <ArrowLeft size={14} /> Back to chassis
      </Link>

      {/* §3.6 STEP 7 — tombstone banner: a soft-deleted / merged chassis is navigable by id but hidden from
          lists; admins can restore it (clears deleted_at + merged_into_id, no FK re-point). */}
      {rec.deleted_at && (
        <div data-testid="chassis-tombstone" className="mb-3 flex flex-wrap items-center justify-between gap-2 rounded-md border border-status-red/40 bg-status-red/10 px-3 py-2 text-sm text-status-red">
          <span className="flex items-center gap-2">
            <AlertTriangle size={16} className="shrink-0" />
            {rec.merged_into_id
              ? <>This chassis was <b>merged into</b>{' '}
                  <Link to={`/chassis/${rec.merged_into_id}`} className="font-mono underline">{rec.merged_into_vin || `#${rec.merged_into_id}`}</Link>.</>
              : <>This chassis was <b>soft-deleted</b>.</>}
            {' '}It’s hidden from lists (kept for audit).
          </span>
          {isAdmin && (
            <button data-testid="chassis-restore" onClick={restore} disabled={restoring}
                    className="flex items-center gap-1.5 rounded-md border border-status-red bg-white px-3 py-1.5 text-xs font-semibold text-status-red hover:bg-status-red/5 disabled:opacity-50">
              {restoring ? <Spinner size={14} /> : <RotateCcw size={14} />} Restore
            </button>
          )}
        </div>
      )}

      <Card className="mb-4 p-4">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
          <h1 className="flex flex-wrap items-center gap-2 text-lg font-bold text-body">
            <Truck size={20} />
            {rec.vin
              ? <span className="font-mono">{rec.vin}</span>
              : <span className="font-mono text-muted">(no VIN yet)</span>}
            <VinSourcePill source={rec.vin_source} />
          </h1>
          <div className="flex items-center gap-2">
            <ProvenancePill via={rec.created_via} source={rec.source} />
            <span className={`rounded-full px-2.5 py-1 text-xs font-semibold ${statusCls}`}>{rec.status.replace(/_/g, ' ')}</span>
          </div>
        </div>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <Field label="Customer" value={rec.customer_name} />
          <Field label="Dealer" value={rec.dealer_name} />
          <Field label="Contact" value={rec.contact_person} />
          <Field label="Telephone" value={rec.telephone} />
          <Field label="Job number" value={rec.job_number} />
          <Field label="Make" value={rec.make} />
          <Field label="Model" value={rec.model} />
          <Field label="Description" value={rec.description} />
          <Field label="Cycles" value={String(cycles.length)} />
          <Field label="Origin ref" value={rec.created_source_ref} />
        </div>
        <div className="mt-4 flex flex-wrap gap-2">
          {/* §3.6 STEP 7 — no mutating actions on a tombstone (restore via the banner first) */}
          {/* WO v4.36c §3.4 — customer collection note for a QC-passed (dispatched) chassis. Opens the
              reportlab PDF inline (regenerated on demand from the signoff); §0.8 customer-facing. */}
          {rec.status === 'dispatched' && (
            <a data-testid="chassis-collection-note" href={`/api/qc/collection-note/${rec.id}`}
               target="_blank" rel="noopener noreferrer"
               className="flex items-center gap-1.5 rounded-md border border-status-green bg-status-green/10 px-4 py-2.5 text-sm font-semibold text-status-green hover:bg-status-green/20">
              <FileDown size={16} /> Download collection note
            </a>
          )}
          {!rec.deleted_at && canEdit && (
            <button data-testid="chassis-edit" onClick={() => setEditing(true)}
                    className="flex items-center gap-1.5 rounded-md border border-line px-4 py-2.5 text-sm font-semibold text-body hover:bg-surface-alt">
              <Pencil size={16} /> Edit details
            </button>
          )}
          {/* WO v4.34.1 §3.4b (Gap A) — late VIN capture: only when the VIN is still NULL (the
              backend enforces NULL→value write-once) and the user can edit chassis (planner/admin). */}
          {canEdit && !rec.vin && (
            <button data-testid="chassis-capture-vin" onClick={() => setCapturingVin(true)}
                    className="flex items-center gap-1.5 rounded-md border border-primary bg-primary-light/40 px-4 py-2.5 text-sm font-semibold text-primary hover:bg-primary-light">
              <Pencil size={16} /> Capture VIN
            </button>
          )}
          {canVcl && (
            <button data-testid="chassis-capture-vcl" onClick={() => setCapture('VCL')}
                    className="flex items-center gap-1.5 rounded-md bg-status-amber px-4 py-2.5 text-sm font-semibold text-white hover:opacity-90">
              <LogIn size={16} /> Capture VCL (book-in)
            </button>
          )}
          {canDcl && (
            <button data-testid="chassis-capture-dcl" onClick={() => setCapture('DCL')}
                    className="flex items-center gap-1.5 rounded-md bg-status-green px-4 py-2.5 text-sm font-semibold text-white hover:opacity-90">
              <LogOut size={16} /> Capture DCL (dispatch)
            </button>
          )}
        </div>
      </Card>

      <h2 className="mb-2 text-sm font-bold uppercase tracking-wide text-muted">Lifecycle history</h2>
      {cycles.length === 0 ? (
        <EmptyState title="No lifecycle events yet" hint="VCL / DCL events will appear here once captured." />
      ) : (
        <div className="space-y-4">
          {cycles.map(({ cycle, events }) => (
            <div key={cycle} data-testid="chassis-cycle">
              <div className="mb-1 text-xs font-bold text-body">Cycle {cycle}</div>
              <div className="grid gap-2 sm:grid-cols-2">
                {events.map((ev) => <EventCard key={ev.id} ev={ev} />)}
              </div>
            </div>
          ))}
        </div>
      )}

      {editing && (
        <EditChassisModal rec={rec} onClose={() => setEditing(false)}
                          onSaved={() => { setEditing(false); load() }} />
      )}
      {capturingVin && (
        <CaptureVinModal recordId={rec.id} onClose={() => setCapturingVin(false)}
                         onSaved={() => { setCapturingVin(false); load() }} />
      )}
      {capture && (
        <VclDclForm
          recordId={rec.id}
          eventType={capture}
          items={checklists[capture] ?? []}
          onClose={() => setCapture(null)}
          onSaved={() => { setCapture(null); load() }}
        />
      )}
    </div>
  )
}

/** WO v4.34 §3.7 / v4.36a §3.5c — edit an existing chassis (chassis.update). Make/model uses the DDM
 * dropdown (preserving an off-list legacy value). The JOB field is symmetric with the Add-Chassis modal so
 * the edit door isn't a MICKEYTEST-class bypass: when the chassis is LINKED (a production job's FK points
 * at it) the job is read-only (swap via admin Merge); when UNLINKED it's a dropdown of unlinked jobs that
 * atomically creates the FK link on save. Customer auto-fills from the selected job. PATCHes changed fields. */
function EditChassisModal({ rec, onClose, onSaved }: {
  rec: ChassisRecordDetail
  onClose: () => void
  onSaved: () => void
}) {
  const toast = useToast()
  const isLinked = rec.linked_job_id != null              // §3.5c — authoritative FK link
  // WO v4.36b — chassis-field unification: a single ChassisFieldValues-shaped form, fed into the shared
  // ChassisFieldsForm (same component the Planning-ack panel uses). All fields land on chassis_records.
  const [form, setForm] = useState<ChassisFieldValues>({
    customer_name: rec.customer_name ?? '',
    make: rec.make ?? '',
    dealer_id: rec.dealer_id ?? null,
    dealer_name: rec.dealer_name ?? '',
    chassis_eta: rec.chassis_eta ?? '',                   // §3.5e — the linked job's Delivery ETA
    contact_person: rec.contact_person ?? '',
    telephone: rec.telephone ?? '',
    vin: rec.vin ?? '',                                   // read-only here (write-once; captured separately)
    tail_lift_code: rec.tail_lift_code ?? '',
    description: rec.description ?? '',
    notes: rec.notes ?? '',
  })
  const [jobId, setJobId] = useState<number | null>(null)  // unlinked → the job to link on save
  const [jobs, setJobs] = useState<UnlinkedJob[]>([])
  const [customerPrefilled, setCustomerPrefilled] = useState(false)
  const [etaPrefilled, setEtaPrefilled] = useState(false)
  const [saving, setSaving] = useState(false)
  const onField = (patch: Partial<ChassisFieldValues>) => setForm((f) => ({ ...f, ...patch }))

  // §3.5c — an UNLINKED chassis can be linked here; load the unlinked-jobs dropdown (reused endpoint).
  useEffect(() => {
    if (isLinked) return
    apiGet<UnlinkedJob[]>('/api/production-jobs/unlinked').then(setJobs).catch(() => setJobs([]))
  }, [isLinked])

  // §3.5c — selecting a job auto-populates Customer + ETA (mirrors create §3.5b). VIN is NOT touched here.
  useEffect(() => {
    if (isLinked || jobId == null) { setCustomerPrefilled(false); return }
    let live = true
    apiGet<ChassisPrefill>(`/api/production-jobs/${jobId}/chassis-prefill`).then((p) => {
      if (!live) return
      if (p.customer_name) { setForm((f) => ({ ...f, customer_name: p.customer_name! })); setCustomerPrefilled(true) }
      else setCustomerPrefilled(false)
      if (p.chassis_eta) { setForm((f) => ({ ...f, chassis_eta: p.chassis_eta! })); setEtaPrefilled(true) } else setEtaPrefilled(false)
    }).catch(() => {})
    return () => { live = false }
  }, [jobId, isLinked])

  async function save() {
    setSaving(true)
    try {
      const body: Record<string, unknown> = {
        customer_name: form.customer_name.trim() || null,
        contact_person: form.contact_person.trim() || null,
        telephone: form.telephone.trim() || null,
        make: form.make.trim() || null,
        dealer_id: form.dealer_id,                        // WO v4.36b — now editable here (validated is_dealer)
        tail_lift_code: form.tail_lift_code.trim() || null,
        description: form.description.trim() || null,
        notes: form.notes.trim() || null,
      }
      // §3.5c — never send job_number/production_job_id for a LINKED chassis (FK is read-only — swap = Merge).
      // For an UNLINKED chassis, sending production_job_id atomically links it (backend stamps job_number).
      if (!isLinked && jobId != null) body.production_job_id = jobId
      if (isLinked || jobId != null) body.chassis_eta = form.chassis_eta || null   // §3.5e — persists onto the linked job
      await apiPatch(`/api/chassis-records/${rec.id}`, body)
      toast.push({ kind: 'ok', message: 'Chassis updated.' })
      onSaved()
    } catch (e) {
      // §0.9 — 409 (customer mismatch vs the job, or job already taken) surfaces inline with remediation.
      if (e instanceof ApiError && e.status === 409) {
        toast.push({ kind: 'warn', message: e.detail || 'That conflicts with the current chassis state.' })
      } else {
        handleApiError(e, toast.push)
      }
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-black/40 sm:items-center sm:p-4" onClick={onClose}>
      <div data-testid="chassis-edit-form" onClick={(e) => e.stopPropagation()}
           className="max-h-[92vh] w-full max-w-md overflow-y-auto rounded-t-2xl bg-white p-5 shadow-xl sm:rounded-2xl">
        <div className="mb-3 flex items-center justify-between">
          <h3 className="text-lg font-bold text-body">Edit chassis <span className="font-mono text-sm text-muted">{rec.vin || '(no VIN)'}</span></h3>
          <button onClick={onClose} className="rounded p-2 hover:bg-surface-alt"><X size={20} /></button>
        </div>
        {/* §3.5c (BA ruling) — VIN is read-only here: write-once (§0.3). Correct a wrong/legacy VIN via admin
            Merge Chassis; a NULL VIN is captured via the Capture VIN button on the detail page. */}
        {rec.vin && (
          <p data-testid="chassis-edit-vin-note" className="-mt-1 mb-3 text-[10px] text-muted">
            VIN <span className="font-mono">{rec.vin}</span>{rec.vin_source ? ` · captured at ${VIN_PROVENANCE[rec.vin_source] ?? 'upstream'}` : ''} — write-once. Use admin Merge Chassis to correct a wrong VIN.
          </p>
        )}
        <div className="space-y-3">
          {/* §3.5c — JOB first (drives the customer prefill), symmetric with the Add-Chassis modal */}
          {isLinked ? (
            <div className="block text-xs">
              <span className="font-semibold text-muted">Job number</span>
              <div data-testid="chassis-edit-job-locked"
                   className="mt-1 w-full rounded-md border border-line bg-surface-alt px-2 py-1.5 font-mono text-sm text-body">
                {rec.linked_job_number || `#${rec.linked_job_id}`}
              </div>
              <span className="mt-1 block text-[10px] text-muted">
                Linked to Job {rec.linked_job_number || rec.linked_job_id} ({rec.linked_customer ?? '—'}). To swap, use admin Merge Chassis.
              </span>
            </div>
          ) : (
            <label className="block text-xs"><span className="font-semibold text-muted">Link to job</span>
              <select data-testid="chassis-edit-job" value={jobId ?? ''}
                      onChange={(e) => {
                        const v = e.target.value ? Number(e.target.value) : null
                        setJobId(v)
                        if (v == null) {                              // deselect → restore the originals
                          if (customerPrefilled) { onField({ customer_name: rec.customer_name ?? '' }); setCustomerPrefilled(false) }
                          onField({ chassis_eta: rec.chassis_eta ?? '' }); setEtaPrefilled(false)
                        }
                      }}
                      className="mt-1 w-full rounded-md border border-line bg-white px-2 py-1.5 text-sm text-body">
                <option value="">— no job —</option>
                {jobs.map((j) => (
                  <option key={j.id} value={j.id}>
                    {j.job_number || `#${j.id}`}{j.customer ? ` · ${j.customer}` : ''}{j.body_type ? ` · ${j.body_type}` : ''}
                  </option>
                ))}
              </select>
              {jobId == null && rec.job_number && (
                <span data-testid="chassis-edit-job-orphan" className="mt-1 block text-[10px] text-muted">
                  Unlinked provenance: <span className="font-mono">{rec.job_number}</span> — pick a job above to create a real link.
                </span>
              )}
            </label>
          )}
          {/* WO v4.36b — the shared chassis-fields form (the SAME component the Planning-ack panel uses, so
              both screens present these fields identically over chassis_records). VIN is hidden here: it shows
              read-only in the note above + is captured via the separate write-once Capture-VIN button. */}
          <ChassisFieldsForm
            values={form} onChange={onField} tailLifts={mockData.tail_lifts} testidPrefix="chassis-edit"
            hidden={['vin']}
            locks={{ eta: !isLinked && jobId == null }}
            etaHint={!isLinked && jobId == null ? 'Links to the job’s ETA — link a job to capture it.' : undefined}
          />
        </div>
        <div className="mt-4 flex gap-2">
          <button onClick={onClose} className="flex-1 rounded-md border border-line py-2.5 text-sm font-semibold">Cancel</button>
          <button data-testid="chassis-edit-save" onClick={save} disabled={saving}
                  className="flex flex-1 items-center justify-center gap-2 rounded-md bg-primary py-2.5 text-sm font-semibold text-white disabled:opacity-50">
            {saving ? <Spinner size={16} /> : null} Save changes
          </button>
        </div>
      </div>
    </div>
  )
}

/** WO v4.34.1 §3.4b (Gap A) — late VIN capture. Shown only while the VIN is NULL; the backend
 * accepts a NULL→value write once and stamps vin_source='chassis_page_manual'. A 409 (already set,
 * or duplicate VIN) surfaces as a toast. */
function CaptureVinModal({ recordId, onClose, onSaved }: {
  recordId: number
  onClose: () => void
  onSaved: () => void
}) {
  const toast = useToast()
  const [vin, setVin] = useState('')
  const [saving, setSaving] = useState(false)

  async function save() {
    if (!vin.trim()) { toast.push({ kind: 'error', message: 'VIN is required.' }); return }
    setSaving(true)
    try {
      await apiPost(`/api/chassis-records/${recordId}/vin`, { vin: vin.trim() })
      toast.push({ kind: 'ok', message: 'VIN captured.' })
      onSaved()
    } catch (e) {
      handleApiError(e, toast.push)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-black/40 sm:items-center sm:p-4" onClick={onClose}>
      <div data-testid="chassis-capture-vin-form" onClick={(e) => e.stopPropagation()}
           className="w-full max-w-md rounded-t-2xl bg-white p-5 shadow-xl sm:rounded-2xl">
        <div className="mb-3 flex items-center justify-between">
          <h3 className="text-lg font-bold text-body">Capture VIN</h3>
          <button onClick={onClose} className="rounded p-2 hover:bg-surface-alt"><X size={20} /></button>
        </div>
        <p className="mb-3 text-xs text-muted">
          Enter the chassis VIN. It can be set once here while it is still blank — afterwards it is
          read-only on this page (an attested VIN can't be silently rewritten).
        </p>
        <label className="block text-xs"><span className="font-semibold text-muted">VIN <span className="text-status-red">*</span></span>
          <input data-testid="chassis-capture-vin-input" value={vin} onChange={(e) => setVin(e.target.value)}
                 autoFocus placeholder="Vehicle ID / VIN"
                 className="mt-1 w-full rounded-md border border-line px-2 py-1.5 font-mono text-sm" /></label>
        <div className="mt-4 flex gap-2">
          <button onClick={onClose} className="flex-1 rounded-md border border-line py-2.5 text-sm font-semibold">Cancel</button>
          <button data-testid="chassis-capture-vin-save" onClick={save} disabled={saving}
                  className="flex flex-1 items-center justify-center gap-2 rounded-md bg-primary py-2.5 text-sm font-semibold text-white disabled:opacity-50">
            {saving ? <Spinner size={16} /> : null} Capture VIN
          </button>
        </div>
      </div>
    </div>
  )
}
