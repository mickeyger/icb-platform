// UrgencyPill.tsx — coloured status pill shared across the Materials screens.
// Tailwind port of the BA scaffolding; colours map to the repo's status palette
// (status-red / status-amber / status-green / status-grey + brand primary).

type Tone =
  | 'critical'
  | 'order_now'
  | 'advisory'
  | 'comfortable'
  | 'confirmed'
  | 'discrepancy'
  | 'pending'
  | 'raised'
  | 'deferred'

const TONE: Record<Tone, { bg: string; label: string }> = {
  critical:    { bg: 'bg-status-red',   label: 'CRITICAL' },
  order_now:   { bg: 'bg-status-amber', label: 'ORDER NOW' },
  advisory:    { bg: 'bg-status-green', label: 'ADVISORY' },
  comfortable: { bg: 'bg-status-green', label: 'COMFORTABLE' },
  confirmed:   { bg: 'bg-status-green', label: 'CONFIRMED' },
  discrepancy: { bg: 'bg-status-red',   label: 'DISCREPANCY' },
  pending:     { bg: 'bg-status-amber', label: 'PENDING' },
  raised:      { bg: 'bg-primary',      label: 'RAISED' },
  deferred:    { bg: 'bg-status-grey',  label: 'DEFERRED' },
}

interface Props {
  tone: Tone
  /** Optional trailing text, e.g. " · T-3" or " · OPEN". */
  suffix?: string
  size?: 'sm' | 'md'
}

export function UrgencyPill({ tone, suffix, size = 'md' }: Props) {
  const t = TONE[tone]
  const sizing = size === 'sm' ? 'px-2 py-0.5 text-[10px]' : 'px-2.5 py-0.5 text-[11px]'
  return (
    <span
      className={`inline-flex items-center whitespace-nowrap rounded-full font-semibold uppercase tracking-wide text-white ${t.bg} ${sizing}`}
    >
      {t.label}
      {suffix ?? ''}
    </span>
  )
}
