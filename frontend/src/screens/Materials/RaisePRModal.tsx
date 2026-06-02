// RaisePRModal.tsx — confirm dialog before posting PRs to SAP (mocked).
// One PR is created per supplier. Built on the shared Modal overlay.

import { useMemo, useState } from 'react'
import { useMaterials } from '../../store/MaterialsContext'
import { Modal } from '../../components/ui/overlays'
import { Tooltip } from '../../components/ui/Tooltip'
import { zar, dmy } from '../../lib/format'

interface Props {
  suggestionIds: number[]
  onConfirm: (ids: number[]) => Promise<void>
  onClose: () => void
}

export function RaisePRModal({ suggestionIds, onConfirm, onClose }: Props) {
  const { poSuggestions } = useMaterials()
  const [busy, setBusy] = useState(false)

  const items = useMemo(
    () => poSuggestions.filter((s) => suggestionIds.includes(s.id)),
    [poSuggestions, suggestionIds],
  )
  const total = items.reduce((a, s) => a + s.total, 0)
  const supplierGroups = useMemo(() => {
    const groups: Record<string, typeof items> = {}
    items.forEach((i) => {
      ;(groups[i.suggested_supplier] ||= []).push(i)
    })
    return groups
  }, [items])

  return (
    <Modal open onClose={busy ? undefined : onClose} className="max-w-2xl">
      <h2 className="text-lg font-bold text-body">Raise Purchase Requisition(s)</h2>
      <p className="mt-1 text-xs text-muted">
        One PR will be created per supplier. The MES posts via BAPI_PR_CREATE and stores the returned
        PR number on each suggestion. (Mocked in this build — see Proposal §11.10 Q8.)
      </p>

      <div className="mt-4 max-h-80 overflow-y-auto rounded-md border border-line">
        {Object.entries(supplierGroups).map(([supplier, group]) => (
          <div key={supplier} className="border-b border-line last:border-b-0">
            <div className="flex items-center justify-between bg-surface-alt px-3 py-2 text-xs font-semibold text-body">
              <span>
                {supplier} · {group.length} item(s)
              </span>
              <span className="tabular-nums">{zar(group.reduce((a, g) => a + g.total, 0))}</span>
            </div>
            {group.map((s) => (
              <div
                key={s.id}
                className="flex items-center justify-between px-3 py-2 text-xs text-body"
              >
                <span>
                  <span className="font-mono font-semibold">{s.sap_code}</span> × {s.qty}
                  <span className="text-muted"> · need by {dmy(s.need_by)}</span>
                </span>
                <span className="tabular-nums">{zar(s.total)}</span>
              </div>
            ))}
          </div>
        ))}
      </div>

      <div className="mt-5 flex items-center justify-between">
        <strong className="text-sm tabular-nums">Total: {zar(total)}</strong>
        <div className="flex gap-2">
          <button
            onClick={onClose}
            disabled={busy}
            className="rounded-md border border-line bg-white px-4 py-2 text-sm font-semibold text-body hover:bg-surface-alt disabled:opacity-40"
          >
            Cancel
          </button>
          <Tooltip k="po_suggestion_queue.raise_pr_button">
            <button
              onClick={async () => {
                setBusy(true)
                await onConfirm(suggestionIds)
                setBusy(false)
              }}
              disabled={busy}
              className="rounded-md bg-primary px-4 py-2 text-sm font-semibold text-white hover:bg-primary-dark disabled:opacity-60"
            >
              {busy ? 'Posting to SAP…' : 'Confirm & Raise'}
            </button>
          </Tooltip>
        </div>
      </div>
    </Modal>
  )
}
