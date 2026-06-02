import type { Status, Bay } from '../data/types'

// Tailwind class fragments per status.
export const statusBg: Record<Status, string> = {
  GREEN: 'bg-status-green',
  AMBER: 'bg-status-amber',
  RED: 'bg-status-red',
  GREY: 'bg-status-grey',
}

export const statusText: Record<Status, string> = {
  GREEN: 'text-status-green',
  AMBER: 'text-status-amber',
  RED: 'text-status-red',
  GREY: 'text-status-grey',
}

export const statusBorder: Record<Status, string> = {
  GREEN: 'border-status-green',
  AMBER: 'border-status-amber',
  RED: 'border-status-red',
  GREY: 'border-status-grey',
}

export const statusLabel: Record<Status, string> = {
  GREEN: 'Running',
  AMBER: 'Warning',
  RED: 'Blocked',
  GREY: 'Off-shift',
}

// Severity (material alerts / QC) → status colour.
export function severityToStatus(sev: string): Status {
  switch (sev.toUpperCase()) {
    case 'HIGH':
    case 'CRITICAL':
      return 'RED'
    case 'MEDIUM':
    case 'MAJOR':
      return 'AMBER'
    default:
      return 'GREY'
  }
}

// Bottleneck = flagged bay, else the bay with the longest queue at WIP limit.
export function findBottleneck(bays: Bay[]): Bay | undefined {
  const flagged = bays.find((b) => b.is_bottleneck)
  if (flagged) return flagged
  return [...bays]
    .filter((b) => b.wip_count >= b.wip_limit)
    .sort((a, b) => b.queue.length - a.queue.length)[0]
}
