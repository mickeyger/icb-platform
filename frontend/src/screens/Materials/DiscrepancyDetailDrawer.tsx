// DiscrepancyDetailDrawer.tsx — opens from the discrepancy flag on the Materials
// Dashboard. Shows the cycle-count history behind an open Stores discrepancy and
// (for buyers) a resolution form. New in WO v4.11 — built on the shared SidePanel.

import { useMemo, useState } from 'react'
import { useMaterials } from '../../store/MaterialsContext'
import { useAppData } from '../../store/AppDataContext'
import { SidePanel } from '../../components/ui/overlays'
import { UrgencyPill } from './components/UrgencyPill'
import { dmy, hhmm } from '../../lib/format'

interface Props {
  sapCode: string | null
  onClose: () => void
}

export function DiscrepancyDetailDrawer({ sapCode, onClose }: Props) {
  const { materials, stockCounts, discrepancies, resolveDiscrepancy } = useMaterials()
  const { hasPermission } = useAppData()
  const [notes, setNotes] = useState('')
  const [busy, setBusy] = useState(false)

  const mat = materials.find((m) => m.sap_code === sapCode)

  // Stock counts for this item that produced an open discrepancy, newest first.
  const rows = useMemo(() => {
    if (!sapCode) return []
    return stockCounts
      .filter((c) => c.sap_code === sapCode)
      .map((c) => ({
        count: c,
        disc: discrepancies.find((d) => d.stock_count_id === c.id),
      }))
      .filter((r) => r.disc)
      .sort((a, b) => (a.count.counted_at ?? '') < (b.count.counted_at ?? '') ? 1 : -1)
  }, [sapCode, stockCounts, discrepancies])

  const open = rows.find((r) => r.disc && !r.disc.resolved_at)
  const canResolve = hasPermission('materials.raise_pr') // buyers resolve discrepancies

  async function handleResolve() {
    if (!open?.disc || !notes.trim() || busy) return
    setBusy(true)
    try {
      await resolveDiscrepancy(open.disc.id, notes.trim())
      setNotes('')
      onClose()
    } finally {
      setBusy(false)
    }
  }

  return (
    <SidePanel
      title={sapCode ? `Discrepancy — ${sapCode}` : 'Discrepancy'}
      open={!!sapCode}
      onClose={onClose}
    >
      <div className="text-sm text-muted">{mat?.description}</div>

      <div className="mt-4 space-y-3">
        {rows.map(({ count, disc }) => {
          const diff = (count.physical_count ?? 0) - count.sap_stock_at_count
          return (
            <div key={count.id} className="rounded-md border border-line p-3 text-xs">
              <div className="flex items-center justify-between">
                <span className="font-semibold">bin {count.bin}</span>
                <UrgencyPill tone={disc?.resolved_at ? 'confirmed' : 'discrepancy'} size="sm" />
              </div>
              <div className="mt-2 grid grid-cols-3 gap-2 text-center">
                <div>
                  <div className="text-muted">SAP</div>
                  <div className="text-base font-bold tabular-nums">{count.sap_stock_at_count}</div>
                </div>
                <div>
                  <div className="text-muted">Physical</div>
                  <div className="text-base font-bold tabular-nums">{count.physical_count ?? '—'}</div>
                </div>
                <div>
                  <div className="text-muted">Diff</div>
                  <div
                    className={`text-base font-bold tabular-nums ${
                      diff < 0 ? 'text-status-red' : diff > 0 ? 'text-status-green' : 'text-body'
                    }`}
                  >
                    {diff > 0 ? `+${diff}` : diff}
                  </div>
                </div>
              </div>
              <div className="mt-2 text-muted">
                Counted by {count.counted_by}
                {count.counted_at && ` · ${dmy(count.counted_at)} ${hhmm(count.counted_at)}`}
              </div>
              {disc && (
                <div className="mt-1 text-muted">
                  Raised to {disc.raised_to_buyer} · {dmy(disc.raised_at)}
                  {disc.resolved_at && ` · resolved ${dmy(disc.resolved_at)}`}
                </div>
              )}
              {disc?.notes && (
                <div className="mt-2 rounded bg-surface-alt p-2 text-body">
                  <span className="font-semibold">Resolution:</span> {disc.notes}
                </div>
              )}
            </div>
          )
        })}
        {rows.length === 0 && (
          <div className="rounded-md border border-dashed border-line p-4 text-center text-xs text-muted">
            No discrepancy history for this item.
          </div>
        )}
      </div>

      {open && canResolve && (
        <div className="mt-5 border-t border-line pt-4">
          <div className="text-xs font-semibold uppercase tracking-wide text-muted">
            Resolve discrepancy
          </div>
          <p className="mt-1 text-xs text-muted">
            Check incoming POs not yet received, mis-issue, theft or damage, then record the outcome.
          </p>
          <textarea
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            rows={3}
            placeholder="Resolution notes…"
            className="mt-2 w-full rounded-md border border-line px-3 py-2 text-sm outline-none focus:border-primary"
          />
          <button
            onClick={handleResolve}
            disabled={!notes.trim() || busy}
            className="mt-2 w-full rounded-md bg-primary px-4 py-2 text-sm font-semibold text-white hover:bg-primary-dark disabled:opacity-40"
          >
            {busy ? 'Resolving…' : 'Mark resolved'}
          </button>
        </div>
      )}
    </SidePanel>
  )
}
