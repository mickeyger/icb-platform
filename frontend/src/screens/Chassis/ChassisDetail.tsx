/** WO v4.28 §0.8 — chassis detail + multi-cycle lifecycle history + VCL/DCL capture (write-path).
 * Groups events by cycle; each cycle shows its VCL (book-in) + DCL (dispatch). Capture buttons are
 * permission-gated (admin sees both); the backend enforces chassis.vcl / chassis.dcl regardless. */
import { useCallback, useEffect, useMemo, useState } from 'react'
import { useParams, Link } from 'react-router-dom'
import { ArrowLeft, Truck, LogIn, LogOut, Image, Pencil, X } from 'lucide-react'

import { apiGet, apiPatch, handleApiError } from '../../lib/api'
import { useToast } from '../../components/ui/toast'
import { useAppData } from '../../store/AppDataContext'
import { Card } from '../../components/ui/primitives'
import { Skeleton, EmptyState, Spinner } from '../../components/ui/feedback'
import { CHASSIS_STATUS_STYLE, CHASSIS_PROVENANCE, type ChassisEvent, type ChassisRecordDetail } from './types'
import { VclDclForm, type ChecklistItem } from './VclDclForm'
import { ChassisModelSelect } from './ChassisModelSelect'

function ProvenancePill({ via, source }: { via?: string | null; source: string }) {
  const p = via ? CHASSIS_PROVENANCE[via] : undefined
  const label = p?.label ?? source.replace(/_/g, ' ')
  const style = p?.style ?? 'bg-surface-alt text-muted'
  return <span className={`inline-block rounded-full px-2.5 py-1 text-xs font-semibold ${style}`}>{label}</span>
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

  const load = useCallback(() => {
    setLoading(true)
    apiGet<ChassisRecordDetail>(`/api/chassis-records/${id}`)
      .then(setRec)
      .catch((e) => handleApiError(e, toast.push))
      .finally(() => setLoading(false))
  }, [id, toast])

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

      <Card className="mb-4 p-4">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
          <h1 className="flex items-center gap-2 text-lg font-bold text-body">
            <Truck size={20} /> <span className="font-mono">{rec.vin}</span>
          </h1>
          <div className="flex items-center gap-2">
            <ProvenancePill via={rec.created_via} source={rec.source} />
            <span className={`rounded-full px-2.5 py-1 text-xs font-semibold ${statusCls}`}>{rec.status.replace(/_/g, ' ')}</span>
          </div>
        </div>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <Field label="Customer" value={rec.customer_name} />
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
          {canEdit && (
            <button data-testid="chassis-edit" onClick={() => setEditing(true)}
                    className="flex items-center gap-1.5 rounded-md border border-line px-4 py-2.5 text-sm font-semibold text-body hover:bg-surface-alt">
              <Pencil size={16} /> Edit details
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

/** WO v4.34 §3.7 — edit an existing chassis (chassis.update). Make/model uses the DDM dropdown
 * (preserving an off-list legacy value); other fields are free-text. PATCHes only changed fields. */
function EditChassisModal({ rec, onClose, onSaved }: {
  rec: ChassisRecordDetail
  onClose: () => void
  onSaved: () => void
}) {
  const toast = useToast()
  const [form, setForm] = useState({
    customer_name: rec.customer_name ?? '',
    contact_person: rec.contact_person ?? '',
    telephone: rec.telephone ?? '',
    job_number: rec.job_number ?? '',
    make: rec.make ?? '',
    description: rec.description ?? '',
    notes: rec.notes ?? '',
  })
  const [saving, setSaving] = useState(false)
  const set = (k: keyof typeof form, v: string) => setForm((f) => ({ ...f, [k]: v }))

  async function save() {
    setSaving(true)
    try {
      await apiPatch(`/api/chassis-records/${rec.id}`, {
        customer_name: form.customer_name.trim() || null,
        contact_person: form.contact_person.trim() || null,
        telephone: form.telephone.trim() || null,
        job_number: form.job_number.trim() || null,
        make: form.make.trim() || null,
        description: form.description.trim() || null,
        notes: form.notes.trim() || null,
      })
      toast.push({ kind: 'ok', message: 'Chassis updated.' })
      onSaved()
    } catch (e) {
      handleApiError(e, toast.push)
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
        <div className="space-y-3">
          <label className="block text-xs"><span className="font-semibold text-muted">Customer</span>
            <input data-testid="chassis-edit-customer" value={form.customer_name} onChange={(e) => set('customer_name', e.target.value)}
                   className="mt-1 w-full rounded-md border border-line px-2 py-1.5 text-sm" /></label>
          <div className="grid grid-cols-2 gap-3">
            <label className="block text-xs"><span className="font-semibold text-muted">Contact</span>
              <input value={form.contact_person} onChange={(e) => set('contact_person', e.target.value)}
                     className="mt-1 w-full rounded-md border border-line px-2 py-1.5 text-sm" /></label>
            <label className="block text-xs"><span className="font-semibold text-muted">Telephone</span>
              <input value={form.telephone} onChange={(e) => set('telephone', e.target.value)}
                     className="mt-1 w-full rounded-md border border-line px-2 py-1.5 text-sm" /></label>
          </div>
          <label className="block text-xs"><span className="font-semibold text-muted">Chassis type</span>
            <ChassisModelSelect testid="chassis-edit-make" value={form.make} onChange={(v) => set('make', v)} /></label>
          <label className="block text-xs"><span className="font-semibold text-muted">Job number</span>
            <input data-testid="chassis-edit-job" value={form.job_number} onChange={(e) => set('job_number', e.target.value)}
                   className="mt-1 w-full rounded-md border border-line px-2 py-1.5 font-mono text-sm" /></label>
          <label className="block text-xs"><span className="font-semibold text-muted">Description</span>
            <input value={form.description} onChange={(e) => set('description', e.target.value)}
                   className="mt-1 w-full rounded-md border border-line px-2 py-1.5 text-sm" /></label>
          <label className="block text-xs"><span className="font-semibold text-muted">Notes</span>
            <textarea value={form.notes} onChange={(e) => set('notes', e.target.value)} rows={2}
                      className="mt-1 w-full rounded-md border border-line px-2 py-1.5 text-sm" /></label>
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
