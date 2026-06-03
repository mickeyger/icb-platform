// feedback.tsx — loading / empty primitives (WO v4.17 §3.3). Reused across Phase 2C.
import type { ReactNode } from 'react'

/** Inline spinner — drop into a button during a mutation. */
export function Spinner({ size = 14, className = '' }: { size?: number; className?: string }) {
  return (
    <span
      role="status"
      aria-label="Working"
      className={`inline-block animate-spin rounded-full border-2 border-current border-t-transparent align-[-2px] ${className}`}
      style={{ width: size, height: size }}
    />
  )
}

/** N-row placeholder for a loading table/list. */
export function Skeleton({ rows = 5, className = '' }: { rows?: number; className?: string }) {
  return (
    <div className={`animate-pulse space-y-2 p-3 ${className}`} aria-busy="true" aria-label="Loading">
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="h-8 rounded bg-surface-alt" />
      ))}
    </div>
  )
}

/** Explicit empty-state (no-data / filtered-to-empty / 404). */
export function EmptyState({ title, hint, action }: { title: string; hint?: string; action?: ReactNode }) {
  return (
    <div className="px-4 py-12 text-center">
      <div className="text-sm font-semibold text-body">{title}</div>
      {hint && <div className="mt-1 text-xs text-muted">{hint}</div>}
      {action && <div className="mt-3">{action}</div>}
    </div>
  )
}

/** "Last updated HH:MM" footer for dashboards (WO §3.3). */
export function LastUpdated({ at, onRefresh }: { at: Date | null; onRefresh?: () => void }) {
  const hhmm = at
    ? `${String(at.getHours()).padStart(2, '0')}:${String(at.getMinutes()).padStart(2, '0')}`
    : '—'
  return (
    <div className="mt-2 flex items-center gap-2 text-[11px] text-muted">
      <span>Last updated {hhmm}</span>
      {onRefresh && (
        <button onClick={onRefresh} className="rounded border border-line px-1.5 py-0.5 hover:bg-surface-alt">
          Refresh
        </button>
      )}
    </div>
  )
}
