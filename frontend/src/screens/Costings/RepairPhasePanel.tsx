import { useEffect, useMemo, useState } from 'react'
import { Wrench, ArrowRightCircle } from 'lucide-react'
import { SidePanel } from '../../components/ui/overlays'
import { Tooltip } from '../../components/ui/Tooltip'
import { data } from '../../data/mockData'
import { costingsMock, type Costing, type RepairPhaseInsertion } from '../../data/costingsData'

// Phase Entry Points the planner can target — same vocabulary the production
// dashboard uses for bays + the existing bays[] data.
const PHASES = [
  { key: 'VACUUM',     label: 'Vacuum',     bayPrefix: 'VAC' },
  { key: 'PRE_ASSY',   label: 'Pre-Assy',   bayPrefix: 'PA' },
  { key: 'ASSEMBLY',   label: 'Assembly',   bayPrefix: 'ASSY' },
  { key: 'LAMINATION', label: 'Lamination', bayPrefix: 'LAM' },
  { key: 'DOORS',      label: 'Doors',      bayPrefix: 'DR' },
  { key: 'GRP',        label: 'GRP',        bayPrefix: 'GRP' },
  { key: 'FINAL_QC',   label: 'Final QC',   bayPrefix: 'QC' },
]

interface RowState {
  enabled: boolean
  bay_assignment: string
  estimated_hours: number
}

export function RepairPhasePanel({
  costing,
  onClose,
  onSchedule,
}: {
  costing: Costing | null
  onClose: () => void
  onSchedule: (c: Costing, phases: RepairPhaseInsertion[]) => void | Promise<void>
}) {
  // Seed defaults from the repair_insertion_sample for the demo quote, else empty.
  const seed = useMemo<Record<string, RowState>>(() => {
    const map: Record<string, RowState> = {}
    PHASES.forEach((p) => {
      map[p.key] = { enabled: false, bay_assignment: '', estimated_hours: 0 }
    })
    if (costing?.quote_number === costingsMock.repair_insertion_sample.quote_number) {
      for (const ins of costingsMock.repair_insertion_sample.phase_insertions) {
        const key = ins.phase.toUpperCase()
        if (map[key]) {
          map[key] = {
            enabled: true,
            bay_assignment: ins.bay_assignment,
            estimated_hours: ins.estimated_hours,
          }
        }
      }
    }
    return map
  }, [costing])

  const [state, setState] = useState(seed)
  useEffect(() => setState(seed), [seed])

  function patch(key: string, p: Partial<RowState>) {
    setState((prev) => ({ ...prev, [key]: { ...prev[key], ...p } }))
  }

  function baysFor(prefix: string): string[] {
    return data.bays.filter((b) => b.id.startsWith(prefix + '-')).map((b) => b.id)
  }

  const totalHours = Object.values(state)
    .filter((s) => s.enabled)
    .reduce((sum, s) => sum + (Number.isFinite(s.estimated_hours) ? s.estimated_hours : 0), 0)
  const phaseCount = Object.values(state).filter((s) => s.enabled).length

  function handleInsert() {
    if (!costing) return
    const phases: RepairPhaseInsertion[] = Object.entries(state)
      .filter(([, s]) => s.enabled)
      .map(([phase, s]) => {
        const ref = PHASES.find((p) => p.key === phase)!
        return {
          phase: ref.label,
          work: '',
          estimated_hours: s.estimated_hours || 0,
          bay_assignment: s.bay_assignment || ref.bayPrefix + '-1',
          status: 'scheduled',
        }
      })
    onSchedule(costing, phases)
  }

  return (
    <SidePanel title={costing ? `Repair · ${costing.quote_number}` : ''} open={!!costing} onClose={onClose} width="w-[520px]">
      {costing && (
        <div className="space-y-4">
          <div className="rounded-md border border-line bg-surface-alt p-3">
            <div className="text-sm font-semibold text-body">{costing.customer_name}</div>
            <div className="text-xs text-muted">{costing.body_type}</div>
            {costing.repair_scope && (
              <div className="mt-2 text-sm text-body">
                <span className="text-xs font-semibold uppercase tracking-wide text-muted">Scope · </span>
                {costing.repair_scope}
              </div>
            )}
          </div>

          <Tooltip k="planning_board.repair_insert_button">
            <div className="text-xs font-semibold uppercase tracking-wide text-muted">Phase entry points</div>
          </Tooltip>

          <div className="space-y-2">
            {PHASES.map((p) => {
              const s = state[p.key]
              return (
                <div
                  key={p.key}
                  className={`rounded-md border p-3 transition ${
                    s.enabled ? 'border-[#7E22CE] bg-[#7E22CE]/5' : 'border-line bg-white'
                  }`}
                >
                  <label className="flex cursor-pointer items-center gap-2">
                    <input
                      type="checkbox"
                      checked={s.enabled}
                      onChange={(e) => patch(p.key, { enabled: e.target.checked })}
                      className="h-4 w-4"
                    />
                    <span className="flex-1 text-sm font-semibold text-body">{p.label}</span>
                  </label>
                  {s.enabled && (
                    <div className="mt-2 grid grid-cols-2 gap-2 text-sm">
                      <label className="text-xs">
                        <span className="text-muted">Bay</span>
                        <select
                          value={s.bay_assignment}
                          onChange={(e) => patch(p.key, { bay_assignment: e.target.value })}
                          className="mt-1 w-full rounded border border-line px-2 py-1 text-sm"
                        >
                          <option value="">— select —</option>
                          {baysFor(p.bayPrefix).map((b) => (
                            <option key={b} value={b}>{b}</option>
                          ))}
                        </select>
                      </label>
                      <label className="text-xs">
                        <span className="text-muted">Est. hours</span>
                        <input
                          type="number"
                          min={0}
                          step={0.5}
                          value={s.estimated_hours || ''}
                          onChange={(e) => patch(p.key, { estimated_hours: parseFloat(e.target.value) || 0 })}
                          className="mt-1 w-full rounded border border-line px-2 py-1 text-sm"
                        />
                      </label>
                    </div>
                  )}
                </div>
              )
            })}
          </div>

          <div className="flex items-center justify-between rounded-md bg-surface-alt p-3 text-sm">
            <span className="text-muted">Total: <strong>{phaseCount}</strong> phase{phaseCount === 1 ? '' : 's'} · <strong>{totalHours}h</strong></span>
            <button
              onClick={handleInsert}
              disabled={phaseCount === 0}
              className="flex items-center gap-1 rounded-md bg-[#7E22CE] px-4 py-2 text-sm font-semibold text-white hover:opacity-90 disabled:opacity-40"
            >
              <ArrowRightCircle size={14} /> Insert into MES
            </button>
          </div>

          <div className="flex items-start gap-2 rounded-md border border-dashed border-line bg-white p-3 text-xs text-muted">
            <Wrench size={14} className="mt-0.5 shrink-0" />
            <span>
              Work orders are created in each selected bay at the requested hours. The Planning Board will
              render them in purple to distinguish repair flow from new builds.
            </span>
          </div>
        </div>
      )}
    </SidePanel>
  )
}
