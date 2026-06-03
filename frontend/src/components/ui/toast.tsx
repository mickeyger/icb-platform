// toast.tsx — app-wide toast service (WO v4.17 §3.2). Wraps the dumb Toast styling
// so error-UX can fire from the data layer (contexts) as well as screens. Reused
// across Phase 2C. The existing screen-local `Toast` in overlays.tsx stays valid.
import { createContext, useCallback, useContext, useState, type ReactNode } from 'react'

export type ToastKind = 'error' | 'warn' | 'ok'

interface ToastItem {
  id: number
  kind: ToastKind
  message: string
}

interface ToastValue {
  push: (t: { kind: ToastKind; message: string }) => void
}

const ToastCtx = createContext<ToastValue | null>(null)

let _seq = 0
const KIND_MS: Record<ToastKind, number> = { error: 5000, warn: 6000, ok: 4000 }
const KIND_CLS: Record<ToastKind, string> = {
  error: 'bg-status-red text-white',
  warn: 'bg-status-amber text-white',
  ok: 'bg-status-green text-white',
}

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([])

  const remove = useCallback((id: number) => {
    setItems((xs) => xs.filter((x) => x.id !== id))
  }, [])

  const push = useCallback(
    (t: { kind: ToastKind; message: string }) => {
      const id = ++_seq
      setItems((xs) => [...xs, { id, ...t }])
      setTimeout(() => remove(id), KIND_MS[t.kind])
    },
    [remove],
  )

  return (
    <ToastCtx.Provider value={{ push }}>
      {children}
      <div className="pointer-events-none fixed bottom-6 left-1/2 z-[60] flex -translate-x-1/2 flex-col items-center gap-2">
        {items.map((it) => (
          <div
            key={it.id}
            role="status"
            onClick={() => remove(it.id)}
            className={`pointer-events-auto cursor-pointer rounded-lg px-4 py-2.5 text-sm shadow-lg ${KIND_CLS[it.kind]}`}
          >
            {it.message}
          </div>
        ))}
      </div>
    </ToastCtx.Provider>
  )
}

export function useToast(): ToastValue {
  const ctx = useContext(ToastCtx)
  if (!ctx) throw new Error('useToast must be used within ToastProvider')
  return ctx
}
