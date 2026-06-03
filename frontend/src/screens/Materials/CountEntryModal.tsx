// CountEntryModal.tsx — Stores quick cycle-count entry. Scan or key the physical
// count; the system auto-classifies confirmed vs discrepancy. Built on the shared
// Modal overlay. The actor (counted_by) is the active demo profile.

import { useState } from 'react'
import { useMaterials, type StockCount } from '../../store/MaterialsContext'
import { useAppData } from '../../store/AppDataContext'
import { Modal } from '../../components/ui/overlays'
import { Tooltip } from '../../components/ui/Tooltip'

interface Props {
  sapCode: string
  bin: string
  onClose: () => void
  onCounted: (result: StockCount) => void
}

export function CountEntryModal({ sapCode, bin, onClose, onCounted }: Props) {
  const { stockPositions, materials, recordCount } = useMaterials()
  const { profile } = useAppData()
  const mat = materials.find((m) => m.sap_code === sapCode)
  const stock = stockPositions.find((s) => s.sap_code === sapCode)
  const [physical, setPhysical] = useState<string>('')
  const [busy, setBusy] = useState(false)

  async function handleConfirm() {
    const n = Number(physical)
    if (!Number.isFinite(n) || n < 0 || busy) return
    setBusy(true)
    try {
      const result = await recordCount(sapCode, bin, n, profile.name)
      onCounted(result)
    } catch {
      setBusy(false) // error toast already surfaced by the context
    }
  }

  return (
    <Modal open onClose={busy ? undefined : onClose} className="max-w-md">
      <h2 className="text-lg font-bold text-body">Cycle Count</h2>
      <p className="mt-1 text-xs text-muted">
        Scan or enter the physical count for this item. The system flags it if it differs from SAP.
      </p>

      <div className="mt-4 rounded-md bg-surface-alt p-3 text-xs">
        <div>
          <span className="font-mono font-semibold">{sapCode}</span> · bin {bin}
        </div>
        <div className="mt-1 text-muted">{mat?.description}</div>
        <div className="mt-2">
          SAP stock: <strong className="tabular-nums">{stock?.sap_stock ?? 0}</strong>
        </div>
      </div>

      <label className="mt-4 block text-xs font-semibold text-muted">Physical count</label>
      <Tooltip k="stores_reconciliation.count_now_button">
        <input
          autoFocus
          type="number"
          min={0}
          value={physical}
          onChange={(e) => setPhysical(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && physical && handleConfirm()}
          placeholder="Scan or key the count"
          className="mt-1 w-full rounded-md border border-line px-3 py-2.5 text-lg font-semibold outline-none focus:border-primary"
        />
      </Tooltip>

      <div className="mt-5 flex justify-end gap-2">
        <button
          onClick={onClose}
          className="rounded-md border border-line bg-white px-4 py-2 text-sm font-semibold text-body hover:bg-surface-alt"
        >
          Cancel
        </button>
        <button
          onClick={handleConfirm}
          disabled={!physical || busy}
          className="rounded-md bg-primary px-4 py-2 text-sm font-semibold text-white hover:bg-primary-dark disabled:opacity-40"
        >
          {busy ? 'Recording…' : 'Record count'}
        </button>
      </div>
    </Modal>
  )
}
