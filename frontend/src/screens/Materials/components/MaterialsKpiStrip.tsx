// MaterialsKpiStrip.tsx — 4-tile KPI row shared across the Materials screens.
// Matches the look of the shared KpiTile primitive but adds tone-coloured values
// and click-to-filter behaviour, so it's kept as a Materials-specific component.

import type { ReactNode } from 'react'
import { Tooltip } from '../../../components/ui/Tooltip'

export type KpiTone = 'neutral' | 'critical' | 'warn' | 'ok'

export interface MaterialsKpiTile {
  label: string
  value: ReactNode
  sub?: ReactNode
  tone?: KpiTone
  onClick?: () => void
  /** Optional tooltip key (looked up from icb_tooltips.json). */
  k?: string
}

const TONE: Record<KpiTone, { value: string; dot: string | null }> = {
  neutral:  { value: 'text-body',        dot: null },
  critical: { value: 'text-status-red',  dot: 'bg-status-red' },
  warn:     { value: 'text-status-amber', dot: 'bg-status-amber' },
  ok:       { value: 'text-status-green', dot: 'bg-status-green' },
}

function Tile({ tile }: { tile: MaterialsKpiTile }) {
  const tone = TONE[tile.tone ?? 'neutral']
  const inner = (
    <div
      onClick={tile.onClick}
      className={`rounded-lg border border-line bg-white p-4 ${
        tile.onClick ? 'cursor-pointer transition hover:border-primary/40' : ''
      }`}
    >
      <div className="text-xs font-medium uppercase tracking-wide text-muted">{tile.label}</div>
      <div className="mt-1 flex items-center gap-2">
        <span className={`text-2xl font-bold tabular-nums ${tone.value}`}>{tile.value}</span>
        {tone.dot && <span className={`inline-block h-2.5 w-2.5 rounded-full ${tone.dot}`} />}
      </div>
      {tile.sub && <div className="mt-1 text-xs text-muted">{tile.sub}</div>}
    </div>
  )
  return tile.k ? <Tooltip k={tile.k}>{inner}</Tooltip> : inner
}

export function MaterialsKpiStrip({ tiles }: { tiles: MaterialsKpiTile[] }) {
  return (
    <div className="mb-4 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
      {tiles.map((t, i) => (
        <Tile key={i} tile={t} />
      ))}
    </div>
  )
}
