import raw from './icb_tooltips.json'

interface TooltipsFile {
  tooltips: Record<string, Record<string, string>>
}

const file = raw as unknown as TooltipsFile

// Resolve a dotted key like "nav.planning" → string, or undefined if missing.
export function lookupTooltip(key: string): string | undefined {
  const [group, name] = key.split('.', 2)
  if (!group || !name) return undefined
  return file.tooltips[group]?.[name]
}

// Heuristic: anything over 200 chars renders as a click-to-dismiss popover
// instead of a hover tooltip (per addendum §2).
export const LONG_TOOLTIP_THRESHOLD = 200
