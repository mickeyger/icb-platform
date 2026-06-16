import type { StatusName } from '../../data/costingsData'

// Hex colours from icb_tooltips.json -> ui_directives.status_palette.
// Re-declared here as plain Tailwind class strings so they tree-shake cleanly.
export interface StatusStyle {
  pillBg: string
  pillText: string
  border: string
  // Hex variant (used in cells/badges where we can't tailwind-conjure utility classes).
  hex: string
}

export const STATUS_STYLES: Record<StatusName, StatusStyle> = {
  'Pending':           { pillBg: 'bg-status-grey',  pillText: 'text-white', border: 'border-status-grey',  hex: '#94A3B8' },
  'Accepted':          { pillBg: 'bg-[#2563EB]',    pillText: 'text-white', border: 'border-[#2563EB]',    hex: '#2563EB' },
  'Pre-Job Sent':      { pillBg: 'bg-status-amber', pillText: 'text-white', border: 'border-status-amber', hex: '#F59E0B' },
  'Pre-Job Confirmed': { pillBg: 'bg-status-green', pillText: 'text-white', border: 'border-status-green', hex: '#16A34A' },
  'Rejected':          { pillBg: 'bg-status-red',   pillText: 'text-white', border: 'border-status-red',   hex: '#DC2626' },
  'Repair':            { pillBg: 'bg-[#7E22CE]',    pillText: 'text-white', border: 'border-[#7E22CE]',    hex: '#7E22CE' },
  'Planning':          { pillBg: 'bg-[#06B6D4]',    pillText: 'text-white', border: 'border-[#06B6D4]',    hex: '#06B6D4' },
}

// Neutral fallback for a costing whose status is OUTSIDE the sales-pipeline vocabulary — e.g. one whose
// production job has advanced to 'In Production' / 'Completed' (backend maps the production_jobs enum
// through to mes_status). Without this, STATUS_STYLES[unknown] is undefined and reading .pillBg
// white-screens the whole Costings dashboard. (WO v4.35 §3.3b hotfix — found during the demo click-around.)
export const DEFAULT_STATUS_STYLE: StatusStyle = {
  pillBg: 'bg-status-grey', pillText: 'text-white', border: 'border-status-grey', hex: '#94A3B8',
}

/** Style for any status string, tolerant of values not in STATUS_STYLES (→ neutral grey pill). */
export function styleForStatus(status: string): StatusStyle {
  return (STATUS_STYLES as Record<string, StatusStyle>)[status] ?? DEFAULT_STATUS_STYLE
}

/** Human label — the backend may send a title-cased enum with an underscore (e.g. 'In_Production'). */
export function prettyStatus(status: string): string {
  return status.replace(/_/g, ' ')
}

export function statusFilterTooltipKey(status: StatusName): string {
  switch (status) {
    case 'Pending':           return 'costings_dashboard.filter_status_pending'
    case 'Accepted':          return 'costings_dashboard.filter_status_accepted'
    case 'Pre-Job Sent':      return 'costings_dashboard.filter_status_prejob_sent'
    case 'Pre-Job Confirmed': return 'costings_dashboard.filter_status_prejob_confirmed'
    case 'Rejected':          return 'costings_dashboard.filter_status_rejected'
    case 'Repair':            return 'costings_dashboard.filter_status_repair'
    case 'Planning':          return 'costings_dashboard.filter_status_planning'
  }
}

/**
 * Status pill. When `pulsing` is true (Planning state without ack), the pill
 * emits a soft cyan box-shadow ring (tailwind `animate-pulseRing`).
 */
export function StatusPillCosting({
  status,
  pulsing = false,
}: {
  status: StatusName
  pulsing?: boolean
}) {
  const s = styleForStatus(status)
  // Flag B (WO v4.19 §0.4): "Accepted" = recorded in the orderbook, NOT dispatched
  // to departments (that's "Pre-Job Sent"). Clarify the record-event semantics on
  // hover rather than relabel the pill.
  const title =
    status === 'Accepted'
      ? 'Job is in the orderbook. The Pre-Job Card has not been sent to departments yet.'
      : undefined
  return (
    <span
      title={title}
      className={`inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wide ${s.pillBg} ${s.pillText} ${
        pulsing ? 'animate-pulseRing' : ''
      }`}
    >
      {prettyStatus(status)}
    </span>
  )
}
