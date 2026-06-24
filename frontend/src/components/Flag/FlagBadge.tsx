// WO v4.36b §0.5 — the flag badge. A sky/amber/red rounded pill + age count + hover tooltip
// (plain title= per §3.0 Subagent B — NOT the Tips-gated <Tooltip>). Severity is the backend-resolved
// value (the per-flag §0.6 bands are applied server-side in visual_integrity.py). Mirrors the house
// StatusPill (ChassisList:26-32); always falls back to a neutral style for an unknown severity.
import { type Flag } from '../../hooks/useFlags'
import { FlagPulse } from './FlagPulse'

const SEV_STYLE: Record<string, string> = {
  sky: 'bg-sky-100 text-sky-700',                       // matches awaiting_qa / pre_assembly house sky
  amber: 'bg-status-amber/15 text-status-amber',
  red: 'bg-status-red/15 text-status-red',
}

export function FlagBadge({ flag, domain, entityId }: {
  flag: Flag
  domain?: string
  entityId?: number | string
}) {
  const cls = SEV_STYLE[flag.severity] ?? 'bg-surface-alt text-muted'
  const ageTxt = flag.age_days != null ? `${flag.age_days}d` : ''
  const title = `${flag.label}`
    + (flag.age_days != null ? ` · ${flag.age_days} day${flag.age_days === 1 ? '' : 's'}` : '')
    + ` — ${flag.remediation}`
  const pill = (
    <span data-testid={`flag-${flag.flag}`} title={title}
          className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-semibold ${cls}`}>
      {flag.label}
      {ageTxt && <span className="tabular-nums opacity-70">{ageTxt}</span>}
    </span>
  )
  // pulse only when the flag is pulse-eligible AND we can identify the instance for the seen-set
  if (flag.pulse && domain != null && entityId != null) {
    return <FlagPulse domain={domain} entityId={entityId} flag={flag.flag}>{pill}</FlagPulse>
  }
  return pill
}

/** Render an entity's flags as a wrapping cluster — the common row/tile case. Renders nothing when clean. */
export function FlagBadges({ flags, domain, entityId }: {
  flags?: Flag[]
  domain?: string
  entityId?: number | string
}) {
  if (!flags || flags.length === 0) return null
  return (
    <span className="inline-flex flex-wrap items-center gap-1" data-testid="flag-badges">
      {flags.map((f) => <FlagBadge key={f.flag} flag={f} domain={domain} entityId={entityId} />)}
    </span>
  )
}
