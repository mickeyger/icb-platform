/** WO v4.34.1 §3.3 — dealer picker for the Planning-ack panel. Sources the customers flagged
 * is_dealer=true (the §3.7 seed — ~25 chassis suppliers) from GET /api/customers?is_dealer=true.
 * Stores the dealer_id (FK → icb_costings.customers) and carries the name for display. An off-list
 * current dealer_id (e.g. one later un-flagged) stays selectable so editing never silently drops it.
 * The <select> supports native type-to-filter; the set is small enough not to need a full typeahead. */
import { useEffect, useState } from 'react'

import { apiGet } from '../../lib/api'

export interface Dealer { id: number; name: string; bp_code: string; is_dealer: boolean }

let _cache: Dealer[] | null = null     // module-level — the dealer set is small + static within a session

export function useDealers(): Dealer[] {
  const [dealers, setDealers] = useState<Dealer[]>(_cache ?? [])
  useEffect(() => {
    if (_cache) return
    let live = true
    apiGet<Dealer[]>('/api/customers?is_dealer=true')
      .then((r) => { _cache = r; if (live) setDealers(r) })
      .catch(() => { /* picker falls back to the preserved current value only */ })
    return () => { live = false }
  }, [])
  return dealers
}

/** Reset the module cache — used by tests / after the §3.7 seed flips new dealer flags. */
export function resetDealerCache(): void { _cache = null }

export function DealerSelect({
  value, valueName, onChange, disabled, testid,
}: {
  value: number | null | undefined
  valueName?: string | null
  onChange: (id: number | null, name: string) => void
  disabled?: boolean
  testid?: string
}) {
  const dealers = useDealers()
  const cur = value ?? null
  const inList = cur != null && dealers.some((d) => d.id === cur)

  return (
    <select
      data-testid={testid}
      value={cur ?? ''}
      disabled={disabled}
      onChange={(e) => {
        const id = e.target.value ? Number(e.target.value) : null
        const name = id == null ? '' : (dealers.find((d) => d.id === id)?.name ?? valueName ?? '')
        onChange(id, name)
      }}
      className="mt-1 w-full rounded-md border border-line bg-white px-2 py-1.5 text-sm text-body disabled:bg-surface-alt"
    >
      <option value="">— select dealer —</option>
      {cur != null && !inList && <option value={cur}>{valueName || `Dealer #${cur}`} (current)</option>}
      {dealers.map((d) => (
        <option key={d.id} value={d.id}>{d.name}</option>
      ))}
    </select>
  )
}
