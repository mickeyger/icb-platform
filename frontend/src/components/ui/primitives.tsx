import type { HTMLAttributes, ReactNode } from 'react'
import type { Status } from '../../data/types'
import { statusBg } from '../../lib/status'
import { zar } from '../../lib/format'

// Card -----------------------------------------------------------------------
// WO v4.32: forwards rest props (data-testid etc.) — Card-level testids silently
// vanished before this; journeys select on them.
export function Card({
  children,
  className = '',
  onClick,
  ...rest
}: {
  children: ReactNode
  className?: string
  onClick?: () => void
} & HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      onClick={onClick}
      className={`rounded-lg border border-line bg-white p-4 ${
        onClick ? 'cursor-pointer hover:border-primary/40' : ''
      } ${className}`}
      {...rest}
    >
      {children}
    </div>
  )
}

// Status pill ----------------------------------------------------------------
export function StatusPill({
  status,
  label,
  className = '',
}: {
  status: Status
  label?: string
  className?: string
}) {
  return (
    <span
      className={`inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wide text-white ${statusBg[status]} ${className}`}
    >
      {label ?? status}
    </span>
  )
}

// Status dot -----------------------------------------------------------------
export function StatusDot({ status, pulse = false }: { status: Status; pulse?: boolean }) {
  return (
    <span
      className={`inline-block h-2.5 w-2.5 rounded-full ${statusBg[status]} ${
        status === 'RED' && pulse ? 'animate-pulseRed' : ''
      }`}
    />
  )
}

// KPI tile -------------------------------------------------------------------
export function KpiTile({
  label,
  value,
  sub,
  status,
  big = false,
}: {
  label: string
  value: ReactNode
  sub?: ReactNode
  status?: Status
  big?: boolean
}) {
  return (
    <div className="rounded-lg border border-line bg-white p-4">
      <div className="text-xs font-medium uppercase tracking-wide text-muted">{label}</div>
      <div className={`mt-1 flex items-center gap-2 font-bold text-body ${big ? 'text-4xl' : 'text-2xl'}`}>
        {value}
        {status && <StatusDot status={status} />}
      </div>
      {sub && <div className="mt-1 text-xs text-muted">{sub}</div>}
    </div>
  )
}

// Money ----------------------------------------------------------------------
export function Money({ value, className = '' }: { value: number; className?: string }) {
  return <span className={`tabular-nums ${className}`}>{zar(value)}</span>
}

// Section heading ------------------------------------------------------------
export function SectionTitle({ children }: { children: ReactNode }) {
  return (
    <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-muted">{children}</h2>
  )
}
