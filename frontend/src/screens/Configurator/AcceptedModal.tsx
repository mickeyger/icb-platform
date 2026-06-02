import { useEffect, useState } from 'react'
import { Check, Loader2 } from 'lucide-react'
import { Modal } from '../../components/ui/overlays'

const NOTIFICATIONS = ['Drawing Office', 'Production Planner', 'Materials Bridge', 'Finance', 'Customer']

export function AcceptedModal({
  open,
  jobNumber,
  onClose,
}: {
  open: boolean
  jobNumber: string
  onClose: () => void
}) {
  const [fired, setFired] = useState(0)

  useEffect(() => {
    if (!open) {
      setFired(0)
      return
    }
    const timers = NOTIFICATIONS.map((_, i) =>
      setTimeout(() => setFired((f) => Math.max(f, i + 1)), 600 + i * 1000),
    )
    // auto-redirect after the fan-out completes
    const redirect = setTimeout(onClose, 600 + NOTIFICATIONS.length * 1000 + 1200)
    return () => {
      timers.forEach(clearTimeout)
      clearTimeout(redirect)
    }
  }, [open, onClose])

  return (
    <Modal open={open}>
      <div className="text-center">
        <div className="mx-auto mb-3 flex h-14 w-14 items-center justify-center rounded-full bg-status-green text-white">
          <Check size={28} />
        </div>
        <h2 className="text-xl font-bold text-body">Job Number {jobNumber} assigned</h2>
        <p className="mt-1 text-sm text-muted">Quotation accepted — notifying the factory.</p>
      </div>
      <ul className="mt-5 space-y-2">
        {NOTIFICATIONS.map((n, i) => {
          const done = i < fired
          return (
            <li
              key={n}
              className={`flex items-center gap-3 rounded-md border px-3 py-2 text-sm transition ${
                done ? 'border-status-green/40 bg-status-green/10' : 'border-line bg-white'
              }`}
            >
              <span className={`flex h-6 w-6 items-center justify-center rounded-full ${done ? 'bg-status-green text-white' : 'bg-surface-alt text-muted'}`}>
                {done ? <Check size={14} /> : <Loader2 size={14} className="animate-spin" />}
              </span>
              <span className={done ? 'font-medium text-body' : 'text-muted'}>
                Notify {n}
              </span>
              {done && <span className="ml-auto text-xs font-semibold uppercase text-status-green">Sent</span>}
            </li>
          )
        })}
      </ul>
      <button
        onClick={onClose}
        className="mt-5 w-full rounded-md bg-primary py-2.5 text-sm font-semibold text-white hover:bg-primary-dark"
      >
        Continue to Production Dashboard
      </button>
    </Modal>
  )
}
