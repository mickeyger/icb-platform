/** WO v4.34 §3.7 — the chassis-type DDM dropdown, shared by the Pre-Job Card modal, the Planning
 * ack panel, and Chassis +New/edit. ONE controlled vocabulary (replaces free-text + the old
 * hardcoded frontend list) so chassis_records.make + token substitution stay consistent. Stores the
 * human display string ("Isuzu FTR 850 AMT (MY22)") — not the code — so it reads cleanly in every
 * consumer. An off-list current value (legacy free-text) is preserved as a selectable option, so
 * editing an existing record never silently drops a value the DDM doesn't yet contain. */
import { useEffect, useState } from 'react'

import { apiGet } from '../../lib/api'
import type { ChassisModel } from './types'

let _cache: ChassisModel[] | null = null     // module-level — the DDM is small + static within a session

export function useChassisModels(): ChassisModel[] {
  const [models, setModels] = useState<ChassisModel[]>(_cache ?? [])
  useEffect(() => {
    if (_cache) return
    let live = true
    apiGet<ChassisModel[]>('/api/chassis-records/models')
      .then((r) => { _cache = r; if (live) setModels(r) })
      .catch(() => { /* dropdown falls back to the preserved current value only */ })
    return () => { live = false }
  }, [])
  return models
}

export function chassisModelLabel(m: ChassisModel): string {
  return `${m.make} ${m.model}`.trim()
}

export function ChassisModelSelect({
  value, onChange, disabled, testid,
}: {
  value: string | null | undefined
  onChange: (v: string) => void
  disabled?: boolean
  testid?: string
}) {
  const models = useChassisModels()
  const labels = models.map(chassisModelLabel)
  const cur = (value ?? '').trim()
  const offList = cur && !labels.includes(cur)      // legacy free-text not in the DDM — keep it selectable

  return (
    <select
      data-testid={testid}
      value={cur}
      disabled={disabled}
      onChange={(e) => onChange(e.target.value)}
      className="mt-1 w-full rounded-md border border-line bg-white px-2 py-1.5 text-sm text-body disabled:bg-surface-alt"
    >
      <option value="">— select chassis type —</option>
      {offList && <option value={cur}>{cur} (current)</option>}
      {models.map((m) => (
        <option key={m.code} value={chassisModelLabel(m)}>{chassisModelLabel(m)}</option>
      ))}
    </select>
  )
}
