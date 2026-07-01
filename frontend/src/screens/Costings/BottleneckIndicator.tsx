import { Hourglass } from 'lucide-react'
import { Tooltip } from '../../components/ui/Tooltip'
import { hhmm, dmy } from '../../lib/format'

/**
 * Pre-Job Sent bottleneck sub-pill (Work Order v4.1 §5.7).
 * Sits under the Pre-Job Sent status pill and surfaces which sign-off is
 * outstanding. Three states derived purely from the two timestamps.
 * Renders nothing when both timestamps are set (status auto-progresses).
 */
export function BottleneckIndicator({
  salesAt,
  productionAt,
  size = 'sm',
}: {
  salesAt: string | null
  productionAt: string | null
  size?: 'sm' | 'md'
}) {
  if (salesAt && productionAt) return null
  const awaitingSales = !salesAt
  const awaitingProd  = !productionAt
  const label =
    awaitingSales && awaitingProd ? 'Awaiting Sales + Prod'
    : awaitingSales                 ? 'Awaiting Sales'
                                    : 'Awaiting Production'
  const ts = (s: string | null) => (s ? `${hhmm(s)} ${dmy(s)}` : '')
  const tip =
    awaitingSales && awaitingProd
      ? 'Pre-Job Card sent to Sales Rep and Production Manager. Neither has signed off yet.'
      : awaitingSales
        ? `Production Manager signed off at ${ts(productionAt)}. Sales Rep still to confirm.`
        : `Sales Rep signed off at ${ts(salesAt)}. Production Manager still to confirm.`
  const sz =
    size === 'md'
      ? 'mt-1.5 px-2.5 py-1 text-xs'
      : 'mt-1 px-2 py-0.5 text-[11px]'
  return (
    <Tooltip text={tip}>
      <span
        className={`inline-flex items-center gap-1 rounded border border-amber-200 bg-amber-50 text-amber-800 ${sz}`}
      >
        <Hourglass size={size === 'md' ? 13 : 11} />
        {label}
      </span>
    </Tooltip>
  )
}
