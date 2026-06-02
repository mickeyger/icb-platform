import { useEffect, type ReactNode } from 'react'
import { X } from 'lucide-react'

// SidePanel — slides in from the right --------------------------------------
export function SidePanel({
  title,
  open,
  onClose,
  children,
  width = 'w-[420px]',
}: {
  title: ReactNode
  open: boolean
  onClose: () => void
  children: ReactNode
  width?: string
}) {
  if (!open) return null
  return (
    <div className="fixed inset-0 z-40">
      <div className="absolute inset-0 bg-black/30" onClick={onClose} />
      <aside
        className={`absolute right-0 top-0 h-full ${width} max-w-[90vw] animate-slideIn overflow-y-auto bg-white shadow-2xl`}
      >
        <header className="sticky top-0 flex items-center justify-between border-b border-line bg-primary px-4 py-3 text-white">
          <div className="font-semibold">{title}</div>
          <button onClick={onClose} aria-label="Close" className="rounded p-1 hover:bg-white/15">
            <X size={18} />
          </button>
        </header>
        <div className="p-4">{children}</div>
      </aside>
    </div>
  )
}

// Modal — centred ------------------------------------------------------------
export function Modal({
  open,
  onClose,
  children,
  className = 'max-w-lg',
}: {
  open: boolean
  onClose?: () => void
  children: ReactNode
  className?: string
}) {
  useEffect(() => {
    if (!open || !onClose) return
    const h = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', h)
    return () => window.removeEventListener('keydown', h)
  }, [open, onClose])

  if (!open) return null
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-black/40" onClick={onClose} />
      <div className={`relative w-full ${className} rounded-xl bg-white p-6 shadow-2xl`}>{children}</div>
    </div>
  )
}

// Toast ----------------------------------------------------------------------
export function Toast({ message, show }: { message: string; show: boolean }) {
  if (!show) return null
  return (
    <div className="fixed bottom-6 left-1/2 z-50 -translate-x-1/2 rounded-lg bg-body px-4 py-2.5 text-sm text-white shadow-lg">
      {message}
    </div>
  )
}
