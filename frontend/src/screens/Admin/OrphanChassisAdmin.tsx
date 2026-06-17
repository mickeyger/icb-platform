/** WO v4.36a §3.6 STEP 2 — admin Find Orphan Chassis (READ-ONLY). Lists LIVE chassis with no
 * production-job and no pre-job-card FK (the authoritative WIDE FK-anchorless set, ANY status — the
 * MICKEYTEST class). Merged chassis (soft-deleted) are excluded. Row recovery actions (retrofit-link /
 * soft-delete / merge) land incrementally in STEP 3 / 4 / 6 — no ghost affordances until then. */
import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { AlertTriangle, RefreshCw, ExternalLink } from 'lucide-react'

import { apiGet, handleApiError } from '../../lib/api'
import { useToast } from '../../components/ui/toast'
import { Spinner, EmptyState } from '../../components/ui/feedback'

interface OrphanChassis {
  id: number; vin: string | null; make: string | null; status: string
  customer_name: string | null; created_via: string | null; created_source_ref: string | null
}

export function OrphanChassisAdmin() {
  const toast = useToast()
  const [rows, setRows] = useState<OrphanChassis[]>([])
  const [loading, setLoading] = useState(true)

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
        excluded. Recovery actions (link a job · soft-delete · merge) arrive in the next steps.
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
                  <td className="px-3 py-2 text-right">
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
    </div>
  )
}
