// WO v4.36b §0.6 — generic ageing pill. Thresholds are PER-CALL-SITE props (Michael, §3.1 review),
// NOT a single global ramp: `green`/`amber` are the inclusive upper day-bounds of those bands and
// `red` is the lower bound of the red band. Default ramp green<=2 / amber 3-4 / red>=5 (Option C,
// 21 Jun). Used where the frontend colourises a raw age without a backend flag (e.g. days-in-state on
// a bay tile); flag badges themselves carry the backend-resolved severity (see FlagBadge).
//
// Per-flag overrides from the §1 catalog — pass at the call site:
//   bay_post_attached_stale  → green=3 amber=4 red=5
//   awaiting_qa_stale        → green=3 amber=6 red=7
//   bay_ready_to_merge_stale → green=1 amber=1 red=2   (amber-only flag in §1)
const STYLE = {
  green: 'bg-status-green/15 text-status-green',
  amber: 'bg-status-amber/15 text-status-amber',
  red: 'bg-status-red/15 text-status-red',
} as const

export function AgeingPill({ days, green = 2, amber = 4, red = 5, label, testid = 'ageing-pill' }: {
  days: number
  green?: number
  amber?: number
  red?: number
  label?: string
  testid?: string
}) {
  const sev: keyof typeof STYLE = days >= red ? 'red' : days <= green ? 'green' : 'amber'
  return (
    <span
      data-testid={testid}
      aria-label={`${days} days (green<=${green}, amber<=${amber}, red>=${red})`}
      className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-semibold ${STYLE[sev]}`}
    >
      {label ? `${label} ` : ''}<span className="tabular-nums">{days}d</span>
    </span>
  )
}
