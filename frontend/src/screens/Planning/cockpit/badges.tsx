// badges.tsx — Duplicated from PlanningBoard's private ChassisBadge / SourceBadge / FooterRow for the
// additive Planning Cockpit. KEEP IN SYNC with PlanningBoard.tsx; never edit the original (demo-frozen).
import { dmy } from '../../../lib/format'
import { Tooltip } from '../../../components/ui/Tooltip'
import type { ChassisState } from '../../../lib/types'

// §3.3 — amber "ETA committed" pill: chassis in transit (chassis_received_at IS NULL, chassis_eta set).
export function ChassisBadge({ state, eta }: { state: ChassisState; eta: string | null }) {
  if (state !== 'eta_committed') return null
  return (
    <span
      title={eta ? `Chassis ETA ${dmy(eta)} (Path B) — not yet received` : 'Chassis ETA committed (Path B)'}
      className="whitespace-nowrap rounded bg-status-amber/15 px-1.5 py-0.5 text-[9px] font-bold uppercase text-status-amber"
    >
      ETA committed
    </span>
  )
}

// §3.4 — source badge: WB = imported from the planning workbook, Q = quote-born (accepted costing).
export function SourceBadge({ source }: { source: string }) {
  const workbook = source === 'workbook'
  return (
    <span
      title={workbook ? 'Imported from the planning workbook' : 'Quote-born (accepted costing)'}
      className={`whitespace-nowrap rounded px-1 py-0.5 text-[9px] font-bold uppercase ${
        workbook ? 'bg-primary/15 text-primary' : 'bg-status-green/15 text-status-green'
      }`}
    >
      {workbook ? 'WB' : 'Q'}
    </span>
  )
}

// Capacity footer row (Filled / Empty / Value / Gap vs target).
export function FooterRow({
  label,
  cells,
  strong,
  tone,
  tooltipKey,
}: {
  label: string
  cells: string[]
  strong?: boolean
  tone?: ('green' | 'red')[]
  tooltipKey?: string
}) {
  const row = (
    <tr className="border-t border-line bg-surface-alt">
      <td className="sticky left-0 z-10 bg-surface-alt px-2 py-1.5 text-xs font-semibold text-muted shadow-[inset_-1px_0_0_#E5E7EB]">{label}</td>
      {cells.map((c, i) => (
        <td
          key={i}
          className={`px-2 py-1.5 text-xs tabular-nums ${strong ? 'font-bold text-body' : 'text-body'} ${
            tone ? (tone[i] === 'green' ? 'text-status-green' : 'text-status-red') : ''
          }`}
        >
          {c}
        </td>
      ))}
    </tr>
  )
  return tooltipKey ? <Tooltip k={tooltipKey}>{row}</Tooltip> : row
}
