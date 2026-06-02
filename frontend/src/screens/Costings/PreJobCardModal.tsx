import { Send, FileText } from 'lucide-react'
import { Modal } from '../../components/ui/overlays'
import { zar, dmy } from '../../lib/format'
import { StatusPillCosting } from './statusPalette'
import type { Costing } from '../../data/costingsData'

export function PreJobCardModal({
  costing,
  onClose,
  onConfirm,
}: {
  costing: Costing | null
  onClose: () => void
  onConfirm: (c: Costing) => void | Promise<void>
}) {
  return (
    <Modal open={!!costing} onClose={onClose} className="max-w-xl">
      {costing && (
        <div>
          <div className="mb-3 flex items-center gap-2">
            <div className="flex h-10 w-10 items-center justify-center rounded-full bg-status-amber/15 text-status-amber">
              <Send size={20} />
            </div>
            <div>
              <h3 className="text-lg font-bold text-body">Send Pre-Job Card</h3>
              <p className="text-xs text-muted">Step 3 — Pre-liminary Job Card to Sales Rep & Production for review.</p>
            </div>
          </div>

          <div className="mb-3 rounded-md border border-line bg-surface-alt p-3 text-sm">
            <div className="flex items-center justify-between">
              <span className="font-mono font-semibold">{costing.quote_number}</span>
              <StatusPillCosting status={costing.status} />
            </div>
            <div className="mt-1 text-body">{costing.customer_name}</div>
            <div className="text-xs text-muted">{costing.body_type} · Created {dmy(costing.created_at)} · {zar(costing.selling_zar)}</div>
          </div>

          <div className="mb-3">
            <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted">Recipients</div>
            <ul className="space-y-1 text-sm">
              <li className="flex items-center justify-between rounded-md border border-line bg-white px-3 py-2">
                <span><strong>Burt Smith</strong> · Sales Rep</span>
                <span className="text-xs text-muted">email + in-app</span>
              </li>
              <li className="flex items-center justify-between rounded-md border border-line bg-white px-3 py-2">
                <span><strong>Pieter Coetzee</strong> · Production Manager</span>
                <span className="text-xs text-muted">email + in-app</span>
              </li>
            </ul>
          </div>

          <div className="mb-3 rounded-md border border-dashed border-line bg-white p-3 text-center text-xs text-muted">
            <FileText size={18} className="mx-auto mb-1 text-muted" />
            Pre-Job Card PDF preview — auto-generated from the costing's BOM and configuration.
          </div>

          <div className="mb-4 rounded-md bg-primary-light/50 px-3 py-2 text-xs text-primary">
            On confirm: status changes to <strong>Pre-Job Sent</strong>. Auto-reminder after 24h if not confirmed.
          </div>

          <div className="flex justify-end gap-2">
            <button onClick={onClose} className="rounded-md border border-line px-4 py-2 text-sm">Cancel</button>
            <button
              onClick={() => onConfirm(costing)}
              className="flex items-center gap-1 rounded-md bg-status-amber px-4 py-2 text-sm font-semibold text-white hover:opacity-90"
            >
              <Send size={14} /> Send Pre-Job Card
            </button>
          </div>
        </div>
      )}
    </Modal>
  )
}
