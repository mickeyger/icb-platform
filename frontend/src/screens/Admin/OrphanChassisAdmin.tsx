/** WO v4.36a §3.6 — admin Find Orphan Chassis. Lists LIVE chassis with no production-job and no
 * pre-job-card FK (the authoritative WIDE FK-anchorless set, ANY status — the MICKEYTEST class). Merged
 * (soft-deleted) chassis are excluded.
 * STEP 2: read-only list. STEP 3: the first row-action — "Link a job" (retrofit-link), reusing the §3.5c
 * atomic-link chokepoint. Soft-delete / merge actions land in STEP 4 / 6. */
import { useCallback, useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { AlertTriangle, RefreshCw, ExternalLink, X, Trash2, GitMerge } from 'lucide-react'

import { apiGet, apiPost, apiDelete, ApiError, handleApiError } from '../../lib/api'
import { useToast } from '../../components/ui/toast'
import { Spinner, EmptyState } from '../../components/ui/feedback'
import { type UnlinkedJob } from '../Chassis/chassisShared'

interface OrphanChassis {
  id: number; vin: string | null; make: string | null; status: string
  customer_name: string | null; created_via: string | null; created_source_ref: string | null
}

export function OrphanChassisAdmin() {
  const toast = useToast()
  const nav = useNavigate()
  const [rows, setRows] = useState<OrphanChassis[]>([])
  const [loading, setLoading] = useState(true)
  const [linkTarget, setLinkTarget] = useState<OrphanChassis | null>(null)     // STEP 3 retrofit-link
  const [deleteTarget, setDeleteTarget] = useState<OrphanChassis | null>(null) // STEP 4 soft-delete

  const load = useCallback(() => {
    setLoading(true)
    apiGet<OrphanChassis[]>('/api/admin/chassis/orphans')
      .then(setRows)
      .catch((e) => handleApiError(e, toast.push))
      .finally(() => setLoading(false))
  }, [toast])

  useEffect(() => { load() }, [load])

  return (
    <div data-testid="admin-orphan-chassis">
      <div className="mb-3 flex items-center justify-between">
        <h1 className="flex items-center gap-2 text-lg font-bold text-body">
          <AlertTriangle size={20} className="text-status-amber" /> Find Orphan Chassis
          <span className="text-sm font-normal text-muted">(no linked job — needs recovery)</span>
        </h1>
        <button data-testid="orphan-refresh" onClick={load}
                className="flex items-center gap-1.5 rounded-md border border-line px-3 py-1.5 text-sm font-semibold text-body hover:bg-surface-alt">
          <RefreshCw size={14} /> Refresh
        </button>
      </div>
      <p className="mb-3 text-xs text-muted">
        Live chassis with no production-job and no pre-job-card link (any status). Merged chassis are
        excluded. Link an orphan to its job below; soft-delete + merge actions arrive in the next steps.
      </p>
      {loading ? (
        <div className="flex justify-center py-10"><Spinner size={24} /></div>
      ) : rows.length === 0 ? (
        <EmptyState title="No orphan chassis" hint="Every live chassis is linked to a job or pre-job card." />
      ) : (
        <div className="overflow-x-auto rounded-lg border border-line">
          <table className="w-full text-sm" data-testid="orphan-table">
            <thead className="bg-surface-alt text-left text-xs text-muted">
              <tr>
                <th className="px-3 py-2">VIN</th><th className="px-3 py-2">Make / Model</th>
                <th className="px-3 py-2">Customer</th><th className="px-3 py-2">Status</th>
                <th className="px-3 py-2">Origin</th><th className="px-3 py-2">Source ref</th>
                <th className="px-3 py-2"></th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id} data-testid={`orphan-row-${r.id}`} className="border-t border-line">
                  <td className="px-3 py-2 font-mono">{r.vin || <span className="text-muted">(no VIN)</span>}</td>
                  <td className="px-3 py-2">{r.make || '—'}</td>
                  <td className="px-3 py-2">{r.customer_name || '—'}</td>
                  <td className="px-3 py-2">{r.status}</td>
                  <td className="px-3 py-2">{(r.created_via || '—').replace(/_/g, ' ')}</td>
                  <td className="px-3 py-2 text-muted">{r.created_source_ref || '—'}</td>
                  <td className="whitespace-nowrap px-3 py-2 text-right">
                    <button data-testid={`orphan-link-${r.id}`} onClick={() => setLinkTarget(r)}
                            className="mr-3 rounded-md border border-line px-2 py-1 text-xs font-semibold text-primary hover:bg-surface-alt">
                      Link a job
                    </button>
                    <button data-testid={`orphan-merge-${r.id}`} onClick={() => nav(`/admin/merge-chassis?loser=${r.id}`)}
                            className="mr-3 inline-flex items-center gap-1 rounded-md border border-line px-2 py-1 text-xs font-semibold text-primary hover:bg-surface-alt">
                      <GitMerge size={12} /> Merge
                    </button>
                    <button data-testid={`orphan-delete-${r.id}`} onClick={() => setDeleteTarget(r)}
                            className="mr-3 inline-flex items-center gap-1 rounded-md border border-status-red/40 px-2 py-1 text-xs font-semibold text-status-red hover:bg-status-red/5">
                      <Trash2 size={12} /> Delete
                    </button>
                    <Link to={`/chassis/${r.id}`} className="inline-flex items-center gap-1 text-primary hover:underline">
                      Open <ExternalLink size={12} />
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="border-t border-line bg-surface-alt px-3 py-1.5 text-xs text-muted">
            {rows.length} orphan{rows.length === 1 ? '' : 's'}
          </div>
        </div>
      )}
      {linkTarget && (
        <RetrofitLinkModal orphan={linkTarget} onClose={() => setLinkTarget(null)}
                           onLinked={() => { setLinkTarget(null); load() }} />
      )}
      {deleteTarget && (
        <SoftDeleteModal orphan={deleteTarget} onClose={() => setDeleteTarget(null)}
                         onDeleted={() => { setDeleteTarget(null); load() }} />
      )}
    </div>
  )
}

/** STEP 3 — link an orphan chassis to an unlinked job via POST /api/admin/chassis/{id}/retrofit-link.
 * The backend reuses the §3.5c atomic-link chokepoint; a customer mismatch / already-taken job → 409. */
function RetrofitLinkModal({ orphan, onClose, onLinked }: {
  orphan: OrphanChassis; onClose: () => void; onLinked: () => void
}) {
  const toast = useToast()
  const [jobs, setJobs] = useState<UnlinkedJob[]>([])
  const [jobId, setJobId] = useState<number | null>(null)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    apiGet<UnlinkedJob[]>('/api/production-jobs/unlinked').then(setJobs).catch(() => setJobs([]))
  }, [])

  async function link() {
    if (jobId == null) { toast.push({ kind: 'error', message: 'Pick a job to link.' }); return }
    setSaving(true)
    try {
      await apiPost(`/api/admin/chassis/${orphan.id}/retrofit-link`, { production_job_id: jobId })
      toast.push({ kind: 'ok', message: 'Chassis linked to job.' })
      onLinked()
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) {
        toast.push({ kind: 'warn', message: e.detail || 'That job conflicts with this chassis.' })
      } else {
        handleApiError(e, toast.push)
      }
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-black/40 sm:items-center sm:p-4" onClick={onClose}>
      <div data-testid="orphan-link-modal" onClick={(e) => e.stopPropagation()}
           className="w-full max-w-md rounded-t-2xl bg-white p-5 shadow-xl sm:rounded-2xl">
        <div className="mb-3 flex items-center justify-between">
          <h3 className="text-lg font-bold text-body">Link chassis to a job</h3>
          <button onClick={onClose} className="rounded p-2 hover:bg-surface-alt"><X size={18} /></button>
        </div>
        <p className="mb-3 text-xs text-muted">
          Chassis <span className="font-mono">{orphan.vin || `#${orphan.id}`}</span>
          {orphan.customer_name ? ` · ${orphan.customer_name}` : ''} → pick an unlinked job. The job's
          customer must match (a blank chassis customer adopts it). Sets the real FK link atomically.
        </p>
        <label className="block text-xs"><span className="font-semibold text-muted">Link to job</span>
          <select data-testid="orphan-link-job" value={jobId ?? ''}
                  onChange={(e) => setJobId(e.target.value ? Number(e.target.value) : null)}
                  className="mt-1 w-full rounded-md border border-line bg-white px-2 py-1.5 text-sm text-body">
            <option value="">— select a job —</option>
            {jobs.map((j) => (
              <option key={j.id} value={j.id}>
                {j.job_number || `#${j.id}`}{j.customer ? ` · ${j.customer}` : ''}{j.body_type ? ` · ${j.body_type}` : ''}
              </option>
            ))}
          </select>
        </label>
        <div className="mt-4 flex gap-2">
          <button onClick={onClose} className="flex-1 rounded-md border border-line py-2.5 text-sm font-semibold">Cancel</button>
          <button data-testid="orphan-link-save" onClick={link} disabled={saving || jobId == null}
                  className="flex flex-1 items-center justify-center gap-2 rounded-md bg-primary py-2.5 text-sm font-semibold text-white disabled:opacity-50">
            {saving ? <Spinner size={16} /> : null} Link job
          </button>
        </div>
      </div>
    </div>
  )
}

/** STEP 4 — soft-delete a JUNK orphan via DELETE /api/admin/chassis/{id}?reason=. Reversible (no
 * merged_into_id); the backend refuses if a live job / card / lifecycle-event still references it (409). */
function SoftDeleteModal({ orphan, onClose, onDeleted }: {
  orphan: OrphanChassis; onClose: () => void; onDeleted: () => void
}) {
  const toast = useToast()
  const [reason, setReason] = useState('')
  const [saving, setSaving] = useState(false)

  async function del() {
    setSaving(true)
    try {
      const qs = reason.trim() ? `?reason=${encodeURIComponent(reason.trim())}` : ''
      await apiDelete(`/api/admin/chassis/${orphan.id}${qs}`)
      toast.push({ kind: 'ok', message: 'Chassis soft-deleted (reversible via restore).' })
      onDeleted()
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) {
        toast.push({ kind: 'warn', message: e.detail || 'This chassis can’t be deleted yet.' })
      } else {
        handleApiError(e, toast.push)
      }
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-black/40 sm:items-center sm:p-4" onClick={onClose}>
      <div data-testid="orphan-delete-modal" onClick={(e) => e.stopPropagation()}
           className="w-full max-w-md rounded-t-2xl bg-white p-5 shadow-xl sm:rounded-2xl">
        <div className="mb-3 flex items-center justify-between">
          <h3 className="text-lg font-bold text-body">Soft-delete chassis</h3>
          <button onClick={onClose} className="rounded p-2 hover:bg-surface-alt"><X size={18} /></button>
        </div>
        <p className="mb-3 text-xs text-muted">
          Soft-delete <span className="font-mono">{orphan.vin || `#${orphan.id}`}</span> as junk. It drops
          out of the chassis list + orphan view but stays navigable by id and is reversible via restore.
          Refused if a live job / card / lifecycle event still references it.
        </p>
        <label className="block text-xs"><span className="font-semibold text-muted">Reason (optional)</span>
          <textarea data-testid="orphan-delete-reason" value={reason} onChange={(e) => setReason(e.target.value)} rows={2}
                    placeholder="e.g. duplicate test row" className="mt-1 w-full rounded-md border border-line px-2 py-1.5 text-sm" />
        </label>
        <div className="mt-4 flex gap-2">
          <button onClick={onClose} className="flex-1 rounded-md border border-line py-2.5 text-sm font-semibold">Cancel</button>
          <button data-testid="orphan-delete-confirm" onClick={del} disabled={saving}
                  className="flex flex-1 items-center justify-center gap-2 rounded-md bg-status-red py-2.5 text-sm font-semibold text-white disabled:opacity-50">
            {saving ? <Spinner size={16} /> : <Trash2 size={14} />} Soft-delete
          </button>
        </div>
      </div>
    </div>
  )
}
