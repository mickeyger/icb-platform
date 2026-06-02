import { Check, ThumbsUp } from 'lucide-react'
import { Modal } from '../../components/ui/overlays'
import { zar, dmy } from '../../lib/format'
import { StatusPillCosting } from './statusPalette'
import type { Costing } from '../../data/costingsData'

/**
 * Move a Pending costing to Accepted from the dashboard, without re-opening
 * the wizard. Work Order v4 §5.1.
 */
export function AcceptModal({
  costing,
  onClose,
  onConfirm,
}: {
  costing: Costing | null
  onClose: () => void
  onConfirm: (c: Costing) => void | Promise<void>
}) {
  return (
    <Modal open={!!costing} onClose={onClose} className="max-w-lg">
      {costing && (
        <div>
          <div className="mb-3 flex items-center gap-2">
            <div className="flex h-10 w-10 items-center justify-center rounded-full bg-[#2563EB]/15 text-[#2563EB]">
              <ThumbsUp size={20} />
            </div>
            <div>
              <h3 className="text-lg font-bold text-body">Confirm customer acceptance</h3>
              <p className="text-xs text-muted">Step 2 — moves the costing from Pending to Accepted.</p>
            </div>
          </div>

          <div className="mb-3 rounded-md border border-line bg-surface-alt p-3 text-sm">
            <div className="flex items-center justify-between">
              <span className="font-mono font-semibold">{costing.quote_number}</span>
              <StatusPillCosting status={costing.status} />
            </div>
            <div className="mt-1 text-body">{costing.customer_name}</div>
            <div className="text-xs text-muted">{costing.body_type} · Created {dmy(costing.created_at)}</div>
            <div className="mt-2 border-t border-line pt-2 text-sm">
              Quote total: <span className="font-semibold tabular-nums">{zar(costing.selling_zar)}</span>
            </div>
          </div>

          <p className="mb-4 text-sm text-body">
            Confirm that customer <strong>{costing.customer_name}</strong> has accepted quote
            {' '}<strong className="font-mono">{costing.quote_number}</strong>. This unlocks the
            Pre-Job Card button on this row.
          </p>

          <div className="flex justify-end gap-2">
            <button onClick={onClose} className="rounded-md border border-line px-4 py-2 text-sm">Cancel</button>
            <button
              onClick={() => onConfirm(costing)}
              className="flex items-center gap-1 rounded-md bg-[#2563EB] px-4 py-2 text-sm font-semibold text-white hover:opacity-90"
            >
              <Check size={14} /> Confirm acceptance
            </button>
          </div>
        </div>
      )}
    </Modal>
  )
}
