const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

// ZAR with thousands separators, e.g. R177,006,839
export function zar(value: number, opts: { decimals?: boolean } = {}): string {
  const n = opts.decimals ? value : Math.round(value)
  return 'R' + n.toLocaleString('en-ZA', {
    minimumFractionDigits: opts.decimals ? 2 : 0,
    maximumFractionDigits: opts.decimals ? 2 : 0,
  })
}

// Compact ZAR, e.g. R177.0M / R162k
export function zarShort(value: number): string {
  if (Math.abs(value) >= 1_000_000) return 'R' + (value / 1_000_000).toFixed(1) + 'M'
  if (Math.abs(value) >= 1_000) return 'R' + Math.round(value / 1_000) + 'k'
  return 'R' + value
}

// DD MMM YYYY, e.g. 29 May 2026
export function dmy(iso: string | null | undefined): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (isNaN(d.getTime())) return '—'
  return `${String(d.getDate()).padStart(2, '0')} ${MONTHS[d.getMonth()]} ${d.getFullYear()}`
}

// "Jun 2026" from an ISO date string (WO v4.29 planning jump). String-sliced (TZ-safe for YYYY-MM-DD).
export function monthYear(iso: string | null | undefined): string {
  if (!iso || iso.length < 7) return '—'
  const m = parseInt(iso.slice(5, 7), 10) - 1
  return `${MONTHS[m] ?? '?'} ${iso.slice(0, 4)}`
}

// First-of-month ISO + label for the current month and the next n-1 (WO v4.29 planning month-jump).
// Returns e.g. [{iso:'2026-06-01', label:'Jun 2026'}, ...]; values are Monday-normalised server-side.
export function nextMonths(n: number): { iso: string; label: string }[] {
  const out: { iso: string; label: string }[] = []
  const now = new Date()
  let y = now.getFullYear()
  let m = now.getMonth()
  for (let i = 0; i < n; i++) {
    out.push({ iso: `${y}-${String(m + 1).padStart(2, '0')}-01`, label: `${MONTHS[m]} ${y}` })
    if (++m > 11) { m = 0; y += 1 }
  }
  return out
}

// 24-hour HH:MM
export function hhmm(iso: string | Date): string {
  const d = typeof iso === 'string' ? new Date(iso) : iso
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}

// 4.3 -> "4h 18m"
export function hoursToHm(hours: number): string {
  const h = Math.floor(hours)
  const m = Math.round((hours - h) * 60)
  return `${h}h ${String(m).padStart(2, '0')}m`
}

// Display a purchase-requisition number consistently as PR-{seq} (WO v4.19 §0.6).
// The backend bulk-raise returns SAP-style numerics (e.g. "4500123456"); the
// mockup renders PR-{seq}. Idempotent — leaves an already-prefixed value alone.
export function formatPrNumber(raw: string | number | null | undefined): string {
  if (raw == null || raw === '') return '—'
  const s = String(raw).trim()
  return /^pr[-\s]/i.test(s) ? s : `PR-${s}`
}
