import { useEffect, useState } from 'react'
import { Check, Shield } from 'lucide-react'
import { Modal } from '../../components/ui/overlays'
import { hhmm, dmy } from '../../lib/format'
import type { Costing } from '../../data/costingsData'

/**
 * Two-step formal attestation modal (Work Order v4 §5.3).
 *
 * Inner "I confirm" checkbox must be ticked before the Confirm Sign-off
 * button enables — intentional friction to prevent accidental clicks. The
 * dynamic attestation text substitutes user name, role, quote number and
 * current time; that exact text is stored alongside the signoff timestamp.
 */
export function PreJobSignoffModal({
  open,
  role,
  costing,
  userName,
  userRoleLabel,
  onClose,
  onConfirm,
}: {
  open: boolean
  role: 'sales' | 'production'
  costing: Costing | null
  userName: string
  userRoleLabel: string
  onClose: () => void
  onConfirm: (attestation: string) => void | Promise<void>
}) {
  const [acknowledged, setAcknowledged] = useState(false)
  const [now, setNow] = useState(() => new Date())

  // Refresh the timestamp once when the modal opens so the captured text
  // matches the moment of intent.
  useEffect(() => {
    if (open) {
      setNow(new Date())
      setAcknowledged(false)
    }
  }, [open])

  if (!open || !costing) return null

  const attestationText =
    role === 'sales'
      ? `I, ${userName} (${userRoleLabel}), confirm that I have reviewed the client requirements for quote ${costing.quote_number} and verify them as true and correct. This electronic confirmation is recorded with timestamp and user identity.`
      : `I, ${userName} (${userRoleLabel}), confirm that the build for quote ${costing.quote_number} is feasible, the capacity is available, and the configuration has been reviewed for production. This electronic confirmation is recorded with timestamp and user identity.`

  return (
    <Modal open={open} onClose={onClose} className="max-w-xl">
      <div className="mb-3 flex items-center gap-2">
        <div className="flex h-10 w-10 items-center justify-center rounded-full bg-primary-light text-primary">
          <Shield size={20} />
        </div>
        <div>
          <h3 className="text-lg font-bold text-body">Confirm Pre-Job Sign-off</h3>
          <p className="text-xs text-muted">Step 3 — formal review gate.</p>
        </div>
      </div>

      <div className="mb-3 rounded-md border border-line bg-surface-alt p-3 text-sm">
        <div className="font-mono font-semibold">{costing.quote_number}</div>
        <div className="text-body">{costing.customer_name}</div>
        <div className="text-xs text-muted">{costing.body_type}</div>
        <div className="my-2 border-t border-line" />
        <dl className="grid grid-cols-3 gap-2 text-xs">
          <div><dt className="text-muted">Sign-off role</dt><dd className="font-semibold uppercase tracking-wide">{role === 'sales' ? 'Sales Rep' : 'Production'}</dd></div>
          <div><dt className="text-muted">Signing user</dt><dd className="font-semibold">{userName}</dd></div>
          <div><dt className="text-muted">Time</dt><dd className="font-semibold">{hhmm(now.toISOString())} · {dmy(now.toISOString())}</dd></div>
        </dl>
      </div>

      <div className="mb-3 rounded-md border-l-4 border-primary bg-primary-light/40 p-3 text-sm italic text-body">
        "{attestationText}"
      </div>

      <label className="mb-4 flex items-start gap-2 text-sm text-body">
        <input
          type="checkbox"
          checked={acknowledged}
          onChange={(e) => setAcknowledged(e.target.checked)}
          className="mt-0.5 h-4 w-4"
        />
        <span>
          I confirm the statement above and authorise this sign-off to be recorded against my user account.
        </span>
      </label>

      <div className="flex justify-end gap-2">
        <button onClick={onClose} className="rounded-md border border-line px-4 py-2 text-sm">Cancel</button>
        <button
          disabled={!acknowledged}
          onClick={() => onConfirm(attestationText)}
          className="flex items-center gap-1 rounded-md bg-status-green px-4 py-2 text-sm font-semibold text-white hover:opacity-90 disabled:opacity-40"
        >
          <Check size={14} /> Confirm Sign-off
        </button>
      </div>
    </Modal>
  )
}
