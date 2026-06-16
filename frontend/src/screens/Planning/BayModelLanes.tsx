// BayModelLanes.tsx — WO v4.31 §3.1 + v4.35 §3.3b. The bay-model row beneath the week-grid: a Parking
// pool (booked-in chassis awaiting a bay) + the 5 Assembly bays. Two drag interactions land here:
//   1. parking chassis -> bay  (v4.31)   — the CHASSIS side of the build (status -> in_assembly).
//   2. a scheduled V-/P- slot-cell -> bay (v4.35 §3.3b) — the PANELS side of the merge. The slot-cell
//      lives in PlanningBoard; it crosses the component boundary via an HTML5 DataTransfer payload
//      ('application/x-panel-job') + a document 'icb:panel-drag' CustomEvent (for the drop-target cue),
//      so the two components stay decoupled (no shared context — §3.0 ratified).
// When a bay holds BOTH a job's panels and its chassis (same job), it is 'ready_to_merge' and an auto-merge
// prompt offers to mark the body attached (the existing body_attached chokepoint). One chassis per bay and
// one job's panels per bay are enforced by the backend (409 → inline reject); the UI does not gate.
// Affordances are gated on chassis.assembly_assign; without it the lanes are view-only (Q5 workshop = RO).
import { useEffect, useState } from 'react'
import { GripVertical, Plus } from 'lucide-react'
import { Card } from '../../components/ui/primitives'
import { useToast } from '../../components/ui/toast'
import { useAppData } from '../../store/AppDataContext'
import { ApiError, handleApiError } from '../../lib/api'
import { useRefetchOnFocus } from '../../lib/useRefetchOnFocus'
import { useBayModel } from './useBayModel'
import type { Bay, BayState, ChassisRecord } from '../Chassis/types'

// Compact per-state tile language for the lanes (same vocabulary/colours as the Production dashboard tiles).
const BAY_TILE: Record<BayState, { border: string; badge?: string; badgeClass?: string }> = {
  empty:               { border: 'border border-dashed border-line bg-surface-alt/40' },
  pre_assembly:        { border: 'border border-line border-l-4 border-l-sky-500 bg-sky-50', badge: 'Panels', badgeClass: 'bg-sky-100 text-sky-700' },
  ready_to_merge:      { border: 'border border-line border-l-4 border-l-violet-500 bg-violet-50', badge: '↔ Merge', badgeClass: 'bg-violet-100 text-violet-700' },
  awaiting_attachment: { border: 'border border-line border-l-4 border-l-status-amber bg-white', badge: 'Awaiting', badgeClass: 'bg-status-amber/15 text-status-amber' },
  attached_today:      { border: 'border border-line border-l-4 border-l-status-green bg-status-green/10', badge: '🔗 Attached', badgeClass: 'bg-status-green/20 text-status-green' },
  post_attached:       { border: 'border border-line border-l-4 border-l-primary bg-primary/5', badge: '🔗 Done', badgeClass: 'bg-primary/15 text-primary' },
}

interface MergePrompt {
  bayCode: string
  bayId: number
  chassisId: number
  jobId: number
  jobNumber: string
  vin: string
}

export function BayModelLanes() {
  const toast = useToast()
  const { hasPermission, isAdmin } = useAppData()
  const canAssign = isAdmin || hasPermission('chassis.assembly_assign')
  const { mode, bays, parking, occupantByBay, refresh, assign, markPanelsArrived, markBodyAttached } =
    useBayModel(toast.push)
  const [drag, setDrag] = useState<ChassisRecord | null>(null)
  const [rejectBay, setRejectBay] = useState<number | null>(null)
  const [busyBay, setBusyBay] = useState<number | null>(null)
  const [panelDragActive, setPanelDragActive] = useState(false)   // a slot-cell panel-job drag is in flight
  const [panelHoverBay, setPanelHoverBay] = useState<number | null>(null)
  const [mergePrompt, setMergePrompt] = useState<MergePrompt | null>(null)
  const [mergeBusy, setMergeBusy] = useState(false)

  useRefetchOnFocus(refresh)        // §3.3b — cross-page sync: the lanes refetch on tab focus

  // §3.3b — a panel-job drag from a PlanningBoard slot-cell announces itself on `document`; light up the
  // bays as drop targets for the duration (the cue without which the planner can't see where to drop).
  useEffect(() => {
    const onPanelDrag = (e: Event) => {
      const active = !!(e as CustomEvent).detail?.active
      setPanelDragActive(active)
      if (!active) setPanelHoverBay(null)
    }
    document.addEventListener('icb:panel-drag', onPanelDrag)
    return () => document.removeEventListener('icb:panel-drag', onPanelDrag)
  }, [])

  if (mode === 'mock') return null // bay model is a live-only surface (API unreachable → offline demo)

  function maybePromptMerge(rows: Bay[], bayId: number) {
    const b = rows.find((x) => x.id === bayId)
    if (b && b.state === 'ready_to_merge' && b.occupant_chassis_id && b.occupant_job_id) {
      setMergePrompt({
        bayCode: b.code,
        bayId: b.id,
        chassisId: b.occupant_chassis_id,
        jobId: b.occupant_job_id,
        jobNumber: b.occupant_job_number ?? String(b.occupant_job_id),
        vin: b.occupant_vin ?? '—',
      })
    }
  }

  function rejectFlash(bayId: number, message: string) {
    setRejectBay(bayId)
    setTimeout(() => setRejectBay(null), 1800)
    toast.push({ kind: 'warn', message })
  }

  async function dropChassisOnBay(bayId: number) {
    const chassis = drag
    setDrag(null)
    if (!chassis || !canAssign) return
    try {
      setBusyBay(bayId)
      const rows = await assign(chassis.id, bayId)
      maybePromptMerge(rows, bayId)        // assigning the chassis may complete a merge (panels already here)
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) rejectFlash(bayId, e.detail || 'That bay is already occupied.')
    } finally {
      setBusyBay(null)
    }
  }

  async function dropPanelsOnBay(jobId: number, bayId: number) {
    if (!canAssign) return
    try {
      setBusyBay(bayId)
      const rows = await markPanelsArrived(jobId, bayId)
      maybePromptMerge(rows, bayId)        // panels arriving may complete a merge (chassis already here)
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) rejectFlash(bayId, e.detail || 'Those panels can’t go in this bay.')
    } finally {
      setBusyBay(null)
    }
  }

  function onBayDrop(e: React.DragEvent, bayId: number) {
    setPanelHoverBay(null)
    const panelJobId = e.dataTransfer.getData('application/x-panel-job')
    if (panelJobId) {
      e.preventDefault()
      void dropPanelsOnBay(Number(panelJobId), bayId)
    } else {
      void dropChassisOnBay(bayId)
    }
  }

  function openMergePromptFor(b: Bay) {
    if (b.occupant_chassis_id && b.occupant_job_id) {
      setMergePrompt({
        bayCode: b.code,
        bayId: b.id,
        chassisId: b.occupant_chassis_id,
        jobId: b.occupant_job_id,
        jobNumber: b.occupant_job_number ?? String(b.occupant_job_id),
        vin: b.occupant_vin ?? '—',
      })
    }
  }

  async function confirmMerge() {
    if (!mergePrompt) return
    setMergeBusy(true)
    try {
      await markBodyAttached(mergePrompt.chassisId, mergePrompt.jobId)
      toast.push({ kind: 'ok', message: `Body attached — job ${mergePrompt.jobNumber}.` })
      setMergePrompt(null)
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) {
        toast.push({ kind: 'warn', message: e.detail || 'Could not mark the body attached — refresh and retry.' })
      } else {
        handleApiError(e, toast.push)
      }
    } finally {
      setMergeBusy(false)
    }
  }

  const freeBays = bays.filter((b) => !occupantByBay[b.id] && (b.state ?? 'empty') === 'empty').length

  return (
    <div className="mt-4 grid grid-cols-[260px_1fr] gap-4" data-testid="bay-model">
      {/* Parking pool — booked-in chassis awaiting an assembly bay (status in_workshop). */}
      <Card className="self-start">
        <div className="mb-2 flex items-center justify-between">
          <span className="text-sm font-semibold uppercase tracking-wide text-muted">Parking</span>
          <span className="text-[11px] text-muted">24 bays</span>
        </div>
        <div className="max-h-64 space-y-2 overflow-y-auto pr-1">
          {parking.map((c) => (
            <div
              key={c.id}
              data-testid="parking-chassis"
              data-id={c.id}
              draggable={canAssign}
              onDragStart={() => { if (canAssign) setDrag(c) }}
              onDragEnd={() => setDrag(null)}
              className={`flex items-start gap-2 rounded-md border border-line border-l-4 border-l-status-amber bg-white p-2 ${
                canAssign ? 'cursor-grab active:cursor-grabbing' : ''
              }`}
            >
              {canAssign && <GripVertical size={14} className="mt-0.5 shrink-0 text-muted" />}
              <div className="min-w-0 flex-1">
                <div className="font-mono text-xs font-semibold">{c.vin}</div>
                <div className="truncate text-xs text-body">{c.customer_name || '—'}</div>
                <div className="truncate text-[11px] text-muted">
                  {[c.make, c.model].filter(Boolean).join(' ') || '—'}
                </div>
              </div>
            </div>
          ))}
          {parking.length === 0 && <div className="text-sm text-muted">No chassis in parking.</div>}
        </div>
        <div className="mt-3 border-t border-line pt-3 text-[11px] text-muted">
          Booked-in, awaiting a bay.{canAssign ? ' Drag onto an assembly bay →' : ''}
        </div>
      </Card>

      {/* Assembly bays — drop targets for a parked chassis AND for a scheduled job's panels. */}
      <Card>
        <div className="mb-2 flex items-center justify-between">
          <span className="text-sm font-semibold uppercase tracking-wide text-muted">Assembly</span>
          <span className="text-[11px] text-muted">{bays.length} bays · {freeBays} free</span>
        </div>
        <div className="grid grid-cols-[repeat(auto-fit,minmax(132px,1fr))] gap-2">
          {bays.map((bay) => {
            const occ = occupantByBay[bay.id]
            const state: BayState = bay.state ?? (occ ? 'awaiting_attachment' : 'empty')
            const ui = BAY_TILE[state]
            const rejected = rejectBay === bay.id
            const busy = busyBay === bay.id
            // §3.3b drag-visual-feedback — during a panel-job drag, light up every bay as a drop target;
            // the bay under the cursor gets the stronger ring (standard dragenter/dragleave emphasis).
            const dropCue = panelDragActive && canAssign
              ? (panelHoverBay === bay.id ? ' ring-2 ring-primary' : ' ring-1 ring-primary/40')
              : ''
            return (
              <div
                key={bay.id}
                data-testid="assembly-bay"
                data-bay-id={bay.id}
                data-bay-code={bay.code}
                data-bay-state={state}
                onDragOver={(e) => {
                  if (!canAssign) return
                  const isPanel = e.dataTransfer.types.includes('application/x-panel-job')
                  if (drag || isPanel) e.preventDefault()   // widened guard — chassis OR panel-job drag
                }}
                onDragEnter={(e) => {
                  if (canAssign && e.dataTransfer.types.includes('application/x-panel-job')) setPanelHoverBay(bay.id)
                }}
                onDragLeave={() => setPanelHoverBay((b) => (b === bay.id ? null : b))}
                onDrop={(e) => onBayDrop(e, bay.id)}
                className={`relative rounded-md p-2 transition ${
                  rejected ? 'border-2 border-status-red bg-status-red/20' : ui.border
                }${dropCue}`}
              >
                {busy && (
                  <div className="absolute inset-0 z-10 flex items-center justify-center rounded-md bg-white/60 text-[11px] text-muted">
                    working…
                  </div>
                )}
                <div className="flex items-center justify-between text-[11px] text-muted">
                  <span>{bay.code}</span>
                  {ui.badge && (
                    <span className={`rounded px-1 text-[10px] font-medium ${ui.badgeClass}`}>{ui.badge}</span>
                  )}
                </div>
                {occ ? (
                  <>
                    <div className="font-mono text-xs font-semibold">{occ.vin}</div>
                    <div className="truncate text-[11px] text-muted">{occ.customer_name || '—'}</div>
                  </>
                ) : state === 'pre_assembly' ? (
                  <>
                    <div className="font-mono text-xs font-semibold text-sky-700">Panels in bay</div>
                    <div className="truncate text-[11px] text-muted">Job {bay.occupant_job_number ?? '—'}</div>
                  </>
                ) : (
                  <div className="flex min-h-[32px] items-center justify-center text-[11px] text-muted">
                    {canAssign ? (
                      <><Plus size={12} className="mr-1" /> drop a chassis</>
                    ) : (
                      'empty'
                    )}
                  </div>
                )}
                {state === 'ready_to_merge' && canAssign && (
                  <button
                    data-testid="merge-button"
                    onClick={() => openMergePromptFor(bay)}
                    className="mt-1 w-full rounded bg-violet-600 px-1.5 py-1 text-[11px] font-semibold text-white hover:bg-violet-700"
                  >
                    ↔ Mark body attached
                  </button>
                )}
              </div>
            )
          })}
          {bays.length === 0 && <div className="text-sm text-muted">No assembly bays.</div>}
        </div>
        <div className="mt-3 border-t border-line pt-3 text-[11px] text-muted">
          Drop a chassis or a scheduled job’s panels · body attaches when both meet (same job).
        </div>
      </Card>

      {/* §3.3b auto-merge prompt — fires when a drop leaves the bay ready_to_merge (panels + chassis, same job). */}
      {mergePrompt && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
          data-testid="merge-prompt"
          onClick={() => { if (!mergeBusy) setMergePrompt(null) }}
        >
          <div className="w-full max-w-sm rounded-lg bg-white p-5 shadow-xl" onClick={(e) => e.stopPropagation()}>
            <div className="text-sm font-semibold text-body">Ready to merge — {mergePrompt.bayCode}</div>
            <p className="mt-2 text-sm text-muted">
              Job <span className="font-mono font-semibold text-body">{mergePrompt.jobNumber}</span> — the panels and
              the chassis <span className="font-mono text-body">{mergePrompt.vin}</span> are both in this bay. Mark the
              body attached now?
            </p>
            <div className="mt-4 flex justify-end gap-2">
              <button
                onClick={() => setMergePrompt(null)}
                disabled={mergeBusy}
                className="rounded-md border border-line px-3 py-1.5 text-sm text-body hover:bg-surface-alt disabled:opacity-50"
              >
                Not yet
              </button>
              <button
                onClick={() => void confirmMerge()}
                data-testid="merge-confirm"
                disabled={mergeBusy}
                className="rounded-md bg-primary px-3 py-1.5 text-sm font-semibold text-white hover:bg-primary-dark disabled:opacity-50"
              >
                {mergeBusy ? 'Merging…' : '🔗 Mark body attached'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
