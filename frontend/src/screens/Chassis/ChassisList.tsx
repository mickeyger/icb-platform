/** WO v4.28 §0.8 — chassis list. Read-path: lists chassis_records (search by VIN / customer /
 * job), click a row → detail. Tablet-friendly rows.
 * WO v4.34 §3.7 — +New (planner/admin), status-filter chips incl. Expected / Expected(Orphaned),
 * and a provenance pill (created_via) so auto-created pipeline rows are distinguishable at a glance. */
import { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Truck, Search, Plus, X } from 'lucide-react'

import { apiGet, apiPost, handleApiError } from '../../lib/api'
import { useToast } from '../../components/ui/toast'
import { useAppData } from '../../store/AppDataContext'
import { Card } from '../../components/ui/primitives'
import { Skeleton, EmptyState, Spinner } from '../../components/ui/feedback'
import { CHASSIS_STATUS_STYLE, CHASSIS_PROVENANCE, type ChassisRecord } from './types'
import { ChassisModelSelect } from './ChassisModelSelect'
import { DealerSelect } from './DealerSelect'

interface UnlinkedJob { id: number; job_number: string | null; customer: string | null; body_type: string | null }
interface ChassisCreateResult {
  chassis: { id: number; vin: string | null; customer_name: string | null; make: string | null }
  adopted: boolean
  adopted_chassis_id: number | null
  message: string | null
}

function StatusPill({ status }: { status: string }) {
  const cls = CHASSIS_STATUS_STYLE[status] ?? 'bg-surface-alt text-muted'
  return (
    <span className={`inline-block rounded-full px-2 py-0.5 text-[11px] font-semibold ${cls}`}>
      {status.replace(/_/g, ' ')}
    </span>
  )
}

function ProvenancePill({ via, source }: { via?: string | null; source: string }) {
  const p = via ? CHASSIS_PROVENANCE[via] : undefined
  const label = p?.label ?? source.replace(/_/g, ' ')
  const style = p?.style ?? 'bg-surface-alt text-muted'
  return <span className={`inline-block rounded-full px-2 py-0.5 text-[10px] font-semibold ${style}`}>{label}</span>
}

// WO v4.34 §3.7 — status chips; the two pipeline statuses lead (Michael's interest), then All + the rest.
const STATUS_CHIPS: { key: string; label: string }[] = [
  { key: '', label: 'All' },
  { key: 'expected', label: 'Expected' },
  { key: 'expected_orphaned', label: 'Expected (Orphaned)' },
  { key: 'received', label: 'Received' },
  { key: 'in_workshop', label: 'In workshop' },
  { key: 'in_assembly', label: 'In assembly' },
  { key: 'dispatched', label: 'Dispatched' },
]

export function ChassisList() {
  const nav = useNavigate()
  const toast = useToast()
  const { hasPermission, isAdmin } = useAppData()
  const [rows, setRows] = useState<ChassisRecord[]>([])
  const [loading, setLoading] = useState(true)
  const [q, setQ] = useState('')
  const [statusFilter, setStatusFilter] = useState('')
  const [showCreate, setShowCreate] = useState(false)

  const canCreate = isAdmin || hasPermission('chassis.create')

  const load = useCallback(() => {
    setLoading(true)
    apiGet<ChassisRecord[]>('/api/chassis-records?limit=200')
      .then(setRows)
      .catch((e) => handleApiError(e, toast.push))
      .finally(() => setLoading(false))
  }, [toast])

  useEffect(() => { load() }, [load])

  const filtered = useMemo(() => {
    const ql = q.trim().toLowerCase()
    return rows.filter((r) => {
      if (statusFilter && r.status !== statusFilter) return false
      if (!ql) return true
      return (r.vin || '').toLowerCase().includes(ql) ||
        (r.customer_name || '').toLowerCase().includes(ql) ||
        (r.dealer_name || '').toLowerCase().includes(ql) ||
        (r.job_number || '').toLowerCase().includes(ql)
    })
  }, [rows, q, statusFilter])

  const counts = useMemo(() => {
    const c: Record<string, number> = {}
    for (const r of rows) c[r.status] = (c[r.status] ?? 0) + 1
    return c
  }, [rows])

  return (
    <div className="p-4" data-testid="chassis-list">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
        <h1 className="flex items-center gap-2 text-xl font-bold text-body">
          <Truck size={22} /> Chassis
          <span className="text-sm font-normal text-muted">({filtered.length})</span>
        </h1>
        {canCreate && (
          <button data-testid="chassis-new" onClick={() => setShowCreate(true)}
                  className="flex items-center gap-1.5 rounded-md bg-primary px-3 py-2 text-sm font-semibold text-white hover:opacity-90">
            <Plus size={16} /> New chassis
          </button>
        )}
      </div>

      <div className="mb-3 flex items-center gap-2 rounded-md border border-line bg-white px-3 py-2">
        <Search size={16} className="text-muted" />
        <input data-testid="chassis-search" value={q} onChange={(e) => setQ(e.target.value)}
               placeholder="Search VIN, customer, or job number…" className="flex-1 text-sm outline-none" />
        {q && <button onClick={() => setQ('')} className="text-xs text-muted hover:text-body">clear</button>}
      </div>

      <div className="mb-3 flex flex-wrap gap-1.5" data-testid="chassis-status-filters">
        {STATUS_CHIPS.map((chip) => {
          const active = statusFilter === chip.key
          const n = chip.key ? (counts[chip.key] ?? 0) : rows.length
          return (
            <button key={chip.key || 'all'} data-testid={`chassis-filter-${chip.key || 'all'}`}
                    onClick={() => setStatusFilter(chip.key)}
                    className={`rounded-full px-3 py-1 text-xs font-semibold ${active ? 'bg-primary text-white' : 'bg-surface-alt text-muted hover:text-body'}`}>
              {chip.label} <span className="tabular-nums opacity-70">{n}</span>
            </button>
          )
        })}
      </div>

      {loading ? (
        <Skeleton rows={8} />
      ) : filtered.length === 0 ? (
        <EmptyState title="No chassis found" hint="No chassis records match the current filter." />
      ) : (
        <Card className="p-0">
          <div className="overflow-x-auto">
            <table className="w-full text-sm" data-testid="chassis-table">
              <thead className="bg-primary text-left text-white">
                <tr>
                  <th className="px-3 py-2 font-semibold">VIN</th>
                  <th className="px-3 py-2 font-semibold">Customer</th>
                  <th className="px-3 py-2 font-semibold">Dealer</th>
                  <th className="px-3 py-2 font-semibold">Make / Model</th>
                  <th className="px-3 py-2 font-semibold">Job</th>
                  <th className="px-3 py-2 font-semibold">Origin</th>
                  <th className="px-3 py-2 text-center font-semibold">Cycles</th>
                  <th className="px-3 py-2 font-semibold">Last activity</th>
                  <th className="px-3 py-2 font-semibold">Status</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((r, i) => {
                  // WO v4.34.1 §3.4 — same-entity render: when the supplying dealer IS the body
                  // customer (one customers row, is_dealer=true), badge the Customer cell
                  // "customer + dealer" rather than repeating the name in both columns.
                  const sameEntity = !!r.dealer_id && !!r.dealer_name && !!r.customer_name &&
                    r.dealer_name.trim().toLowerCase() === r.customer_name.trim().toLowerCase()
                  return (
                  <tr key={r.id} data-testid="chassis-row" data-id={r.id}
                      onClick={() => nav(`/chassis/${r.id}`)}
                      className={`cursor-pointer border-b border-line hover:bg-primary-light/40 ${i % 2 ? 'bg-surface-alt' : 'bg-white'}`}>
                    <td className="px-3 py-2 font-mono text-xs font-semibold">{r.vin || <span className="text-muted">—</span>}</td>
                    <td className="px-3 py-2" data-testid="chassis-cell-customer">
                      {r.customer_name || '—'}
                      {sameEntity && (
                        <span className="ml-1.5 rounded-full bg-primary-light/60 px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wide text-primary">
                          customer + dealer
                        </span>
                      )}
                    </td>
                    <td className="px-3 py-2 text-xs" data-testid="chassis-cell-dealer">
                      {!r.dealer_id ? <span className="text-muted">—</span>
                        : sameEntity ? <span className="text-muted">= customer</span>
                        : (r.dealer_name || <span className="text-muted">Dealer #{r.dealer_id}</span>)}
                    </td>
                    <td className="px-3 py-2">{[r.make, r.model].filter(Boolean).join(' ') || '—'}</td>
                    <td className="px-3 py-2 font-mono text-xs">{r.job_number || '—'}</td>
                    <td className="px-3 py-2"><ProvenancePill via={r.created_via} source={r.source} /></td>
                    <td className="px-3 py-2 text-center tabular-nums">{r.event_count}</td>
                    <td className="px-3 py-2 text-xs text-muted">{r.latest_event_date || '—'}</td>
                    <td className="px-3 py-2"><StatusPill status={r.status} /></td>
                  </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      {showCreate && (
        <CreateChassisModal onClose={() => setShowCreate(false)}
                            onCreated={() => { setShowCreate(false); load() }} />
      )}
    </div>
  )
}

/** WO v4.34 §3.7 — manual chassis create (planner / admin). Make/model comes from the DDM dropdown
 * (no free-text); the backend stamps created_via='manual_chassis_menu'. */
// WO v4.36a §0.8 — informational modal shown when a typed VIN matched an existing live chassis and the
// selected job was AUTO-ADOPTED onto it (no duplicate created). Single [Got it]; no Cancel (already done).
function AdoptionNotificationModal({ result, onClose }: { result: ChassisCreateResult; onClose: () => void }) {
  const ch = result.chassis
  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/40 p-4"
         data-testid="adoption-modal" onClick={onClose}>
      <div className="w-full max-w-sm rounded-lg bg-white p-5 shadow-xl" onClick={(e) => e.stopPropagation()}>
        <h3 className="text-base font-bold text-body">VIN already on record — chassis adopted</h3>
        <p className="mt-2 text-sm text-muted" data-testid="adoption-message">{result.message}</p>
        <div className="mt-3 rounded-md border border-line bg-surface-alt/40 p-2 text-xs">
          <div className="font-mono font-semibold text-body">{ch.vin}</div>
          <div className="text-muted">{ch.customer_name || '—'}{ch.make ? ` · ${ch.make}` : ''}</div>
        </div>
        <div className="mt-4 flex justify-end">
          <button data-testid="adoption-got-it" onClick={onClose}
                  className="rounded-md bg-primary px-3 py-1.5 text-sm font-semibold text-white hover:bg-primary-dark">
            Got it
          </button>
        </div>
      </div>
    </div>
  )
}

function CreateChassisModal({ onClose, onCreated }: { onClose: () => void; onCreated: () => void }) {
  const toast = useToast()
  const [vin, setVin] = useState('')
  const [customer, setCustomer] = useState('')
  const [make, setMake] = useState('')
  const [jobId, setJobId] = useState<number | null>(null)
  const [dealerId, setDealerId] = useState<number | null>(null)
  const [jobs, setJobs] = useState<UnlinkedJob[]>([])
  const [saving, setSaving] = useState(false)
  const [adoption, setAdoption] = useState<ChassisCreateResult | null>(null)

  useEffect(() => {
    // §0.6 — the job dropdown lists only jobs with no chassis linked yet.
    apiGet<UnlinkedJob[]>('/api/production-jobs/unlinked').then(setJobs).catch(() => setJobs([]))
  }, [])

  async function save() {
    if (!vin.trim()) { toast.push({ kind: 'error', message: 'VIN is required.' }); return }
    if (!make.trim()) { toast.push({ kind: 'error', message: 'Chassis type is required.' }); return }
    setSaving(true)
    try {
      const result = await apiPost<ChassisCreateResult>('/api/chassis-records', {
        vin: vin.trim(), customer_name: customer.trim() || null, make: make.trim() || null,
        production_job_id: jobId, dealer_id: dealerId,
      })
      if (result.adopted) {
        setAdoption(result)                 // §0.8 — surface the adoption before closing
      } else {
        toast.push({ kind: 'ok', message: `Chassis ${result.chassis.vin} created.` })
        onCreated(); onClose()
      }
    } catch (e) {
      handleApiError(e, toast.push)         // chassis_integrity 422/409 surfaces with full remediation text
    } finally {
      setSaving(false)
    }
  }

  if (adoption) {
    return <AdoptionNotificationModal result={adoption} onClose={() => { onCreated(); onClose() }} />
  }

  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-black/40 sm:items-center sm:p-4" onClick={onClose}>
      <div data-testid="chassis-create-form" onClick={(e) => e.stopPropagation()}
           className="max-h-[92vh] w-full max-w-md overflow-y-auto rounded-t-2xl bg-white p-5 shadow-xl sm:rounded-2xl">
        <div className="mb-3 flex items-center justify-between">
          <h3 className="text-lg font-bold text-body">New chassis</h3>
          <button onClick={onClose} className="rounded p-2 hover:bg-surface-alt"><X size={20} /></button>
        </div>
        <div className="space-y-3">
          <label className="block text-xs">
            <span className="font-semibold text-muted">VIN <span className="text-status-red">*</span></span>
            <input data-testid="chassis-create-vin" value={vin} onChange={(e) => setVin(e.target.value)}
                   placeholder="17 characters — no I, O or Q"
                   className="mt-1 w-full rounded-md border border-line px-2 py-1.5 font-mono text-sm" />
          </label>
          <label className="block text-xs">
            <span className="font-semibold text-muted">Chassis type <span className="text-status-red">*</span></span>
            <ChassisModelSelect testid="chassis-create-make" value={make} onChange={setMake} />
          </label>
          <label className="block text-xs">
            <span className="font-semibold text-muted">Link to job</span>
            <select data-testid="chassis-create-job" value={jobId ?? ''}
                    onChange={(e) => setJobId(e.target.value ? Number(e.target.value) : null)}
                    className="mt-1 w-full rounded-md border border-line bg-white px-2 py-1.5 text-sm text-body">
              <option value="">— no job —</option>
              {jobs.map((j) => (
                <option key={j.id} value={j.id}>
                  {j.job_number || `#${j.id}`}{j.customer ? ` · ${j.customer}` : ''}{j.body_type ? ` · ${j.body_type}` : ''}
                </option>
              ))}
            </select>
          </label>
          <label className="block text-xs">
            <span className="font-semibold text-muted">Customer</span>
            <input data-testid="chassis-create-customer" value={customer} onChange={(e) => setCustomer(e.target.value)}
                   className="mt-1 w-full rounded-md border border-line px-2 py-1.5 text-sm" />
          </label>
          <label className="block text-xs">
            <span className="font-semibold text-muted">Supplying dealer</span>
            <DealerSelect value={dealerId} onChange={(id) => setDealerId(id)} testid="chassis-create-dealer" />
          </label>
        </div>
        <div className="mt-4 flex gap-2">
          <button onClick={onClose} className="flex-1 rounded-md border border-line py-2.5 text-sm font-semibold">Cancel</button>
          <button data-testid="chassis-create-save" onClick={save} disabled={saving}
                  className="flex flex-1 items-center justify-center gap-2 rounded-md bg-primary py-2.5 text-sm font-semibold text-white disabled:opacity-50">
            {saving ? <Spinner size={16} /> : null} Create
          </button>
        </div>
      </div>
    </div>
  )
}
