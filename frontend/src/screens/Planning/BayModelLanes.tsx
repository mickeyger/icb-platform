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
import { FlagBadges } from '../../components/Flag/FlagBadge'   // WO v4.36b §3.2 — bay-tile flags
import { AgeingPill } from '../../components/Flag/AgeingPill'   // WO v4.36b §3.7 — colour-coded day-counter
import { useFlaggedBays } from '../../hooks/useFlags'

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

// WO v4.36a.1 — the chassis a bay-tile drag dropped onto the Awaiting-QA zone (the confirm modal's subject).
interface QaPrompt {
  bayCode: string
  chassisId: number
  vin: string
  customerName: string
}

// MIME for a bay-tile -> Awaiting-QA drag (decoupled, mirrors the §3.3b panel-job DataTransfer pattern).
const QA_MIME = 'application/x-awaiting-qa'

// WO v4.36a.2 — the chassis a bay-tile drag dropped onto the Parking pool (the return-confirm modal's subject).
interface ParkingPrompt {
  bayCode: string
  chassisId: number
  vin: string
  customerName: string
}

// MIME for a bay-tile -> Parking (return) drag. Disjoint from QA_MIME: a tile is EITHER QA-draggable
// (body attached) OR parking-draggable (no body), never both — the bay state decides.
const PARK_MIME = 'application/x-return-to-parking'

// WO v4.36a.5 — days a chassis has been on its bay, from the assembly_assigned event date (BayOut.since).
// Day 0 = same calendar day, Day 1 = next day, etc. Returns null when there's no date (no counter shown).
function dayCount(since?: string | null): number | null {
  if (!since) return null
  const start = new Date(`${since.slice(0, 10)}T00:00:00`).getTime()
  if (Number.isNaN(start)) return null
  const today = new Date(); today.setHours(0, 0, 0, 0)
  const days = Math.floor((today.getTime() - start) / 86_400_000)
  return days >= 0 ? days : 0
}

// v1.39.1 backport (Item 8): removed the hardcoded VISUAL-ONLY Pre-Assembly demo cards (interface + const
// + the placeholder Card below). The live pre_assembly bay state (a bay holding panels but no chassis yet)
// is already rendered in the MERGE tiles from useBayModel's `bays` — the demo block was redundant cruft.

export function BayModelLanes() {
  const toast = useToast()
  const { map: bayFlags } = useFlaggedBays()   // WO v4.36b §3.2 — {bay_id → Flag[]} for the assembly tiles
  const { hasPermission, isAdmin } = useAppData()
  const canAssign = isAdmin || hasPermission('chassis.assembly_assign')
  const { mode, bays, parking, occupantByBay, awaitingQa, refresh, assign, markPanelsArrived,
          markBodyAttached, clearPanels, moveToAwaitingQa, returnToParking } = useBayModel(toast.push)
  const [drag, setDrag] = useState<ChassisRecord | null>(null)
  const [rejectBay, setRejectBay] = useState<number | null>(null)
  const [busyBay, setBusyBay] = useState<number | null>(null)
  const [panelDragActive, setPanelDragActive] = useState(false)   // a slot-cell panel-job drag is in flight
  const [panelHoverBay, setPanelHoverBay] = useState<number | null>(null)
  const [mergePrompt, setMergePrompt] = useState<MergePrompt | null>(null)
  const [mergeBusy, setMergeBusy] = useState(false)
  // WO v4.36a.1 — the Awaiting-QA handoff: a bay-tile drag (attached_today / post_attached) lights up the
  // zone below, and a drop opens the confirm-with-notes modal before the status-promoting move.
  const [qaDragActive, setQaDragActive] = useState(false)
  const [qaHover, setQaHover] = useState(false)
  const [qaPrompt, setQaPrompt] = useState<QaPrompt | null>(null)
  const [qaNotes, setQaNotes] = useState('')
  const [qaBusy, setQaBusy] = useState(false)
  // WO v4.36a.2 — return-to-parking: a pre-merge bay-tile drag onto the Parking pool, to free the bay for
  // a more urgent job. Mirror of the QA flow (disjoint by bay state) + an optional re-prioritisation reason.
  const [parkingDragActive, setParkingDragActive] = useState(false)
  const [parkingHover, setParkingHover] = useState(false)
  const [parkingPrompt, setParkingPrompt] = useState<ParkingPrompt | null>(null)
  const [parkingReason, setParkingReason] = useState('')
  const [parkingBusy, setParkingBusy] = useState(false)
  // WO — the bay right-click "unlink panels" context menu: the bay it's open for + the cursor anchor.
  const [ctxMenu, setCtxMenu] = useState<{ bayId: number; x: number; y: number } | null>(null)

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

  // WO v4.36a.1 — a bay-tile drag announces itself on `document` so the Awaiting-QA zone lights up as the
  // drop target for its duration (the cue without which the planner can't see where to drop). Same decoupled
  // pattern as §3.3b's panel-drag — no shared context between the bay tiles and the zone.
  useEffect(() => {
    const onQaDrag = (e: Event) => {
      const active = !!(e as CustomEvent).detail?.active
      setQaDragActive(active)
      if (!active) setQaHover(false)
    }
    document.addEventListener('icb:awaiting-qa-drag', onQaDrag)
    return () => document.removeEventListener('icb:awaiting-qa-drag', onQaDrag)
  }, [])

  // WO v4.36a.2 — a pre-merge bay-tile drag announces itself so the Parking pool lights up as the drop
  // target for its duration (same decoupled CustomEvent pattern as the QA + panel drags).
  useEffect(() => {
    const onParkDrag = (e: Event) => {
      const active = !!(e as CustomEvent).detail?.active
      setParkingDragActive(active)
      if (!active) setParkingHover(false)
    }
    document.addEventListener('icb:return-to-parking-drag', onParkDrag)
    return () => document.removeEventListener('icb:return-to-parking-drag', onParkDrag)
  }, [])

  // WO — close the right-click "unlink panels" menu on click-away / Escape / scroll / resize. Registered
  // only while the menu is open; the opening right-click's mousedown fires BEFORE this binds, so it can't
  // self-close. The menu container stops mousedown propagation so clicks on its own buttons don't close it.
  useEffect(() => {
    if (!ctxMenu) return
    const close = () => setCtxMenu(null)
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setCtxMenu(null) }
    document.addEventListener('mousedown', close)
    document.addEventListener('keydown', onKey)
    window.addEventListener('scroll', close, true)
    window.addEventListener('resize', close)
    return () => {
      document.removeEventListener('mousedown', close)
      document.removeEventListener('keydown', onKey)
      window.removeEventListener('scroll', close, true)
      window.removeEventListener('resize', close)
    }
  }, [ctxMenu])

  if (mode === 'mock') return null // bay model is a live-only surface (API unreachable → offline demo)

  function afterDrop(rows: Bay[], bayId: number) {
    const b = rows.find((x) => x.id === bayId)
    if (!b) return
    if (b.state === 'ready_to_merge' && b.occupant_chassis_id && b.occupant_job_id) {
      setMergePrompt({
        bayCode: b.code,
        bayId: b.id,
        chassisId: b.occupant_chassis_id,
        jobId: b.occupant_job_id,
        jobNumber: b.occupant_job_number ?? String(b.occupant_job_id),
        vin: b.occupant_vin ?? '—',
      })
    } else if (b.mismatch) {
      // §3.3b UX — the drop landed on a bay whose chassis is a DIFFERENT job: legible warning, not a silent
      // no-merge. The panels were still recorded; the operator can move them off with ✕ and re-drop.
      toast.push({
        kind: 'warn',
        message: `Panels placed on ${b.code}, but its chassis is a different job — they won’t merge. `
          + `Move them to the bay holding the matching chassis, or remove them with ✕.`,
      })
    }
  }

  async function onClearPanels(bay: Bay) {
    if (!canAssign || bay.panels_job_id == null) return
    try {
      setBusyBay(bay.id)
      await clearPanels(bay.panels_job_id)
      toast.push({ kind: 'ok', message: `Panels moved off ${bay.code}.` })
    } catch (e) {
      if (e instanceof ApiError) toast.push({ kind: 'warn', message: e.detail || 'Could not move the panels back.' })
    } finally {
      setBusyBay(null)
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
      afterDrop(rows, bayId)        // assigning the chassis may complete a merge (panels already here)
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
      afterDrop(rows, bayId)        // panels arriving may complete a merge (chassis already here)
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

  // WO v4.36a.1 — bay-tile drag SOURCE (attached_today / post_attached). DataTransfer carries the chassis id;
  // the CustomEvent lights up the zone. effectAllowed='move' so the cursor reads as a move, not a copy.
  function onTileDragStart(e: React.DragEvent, chassisId: number) {
    e.dataTransfer.setData(QA_MIME, String(chassisId))
    e.dataTransfer.effectAllowed = 'move'
    document.dispatchEvent(new CustomEvent('icb:awaiting-qa-drag', { detail: { active: true } }))
  }
  function onTileDragEnd() {
    document.dispatchEvent(new CustomEvent('icb:awaiting-qa-drag', { detail: { active: false } }))
  }

  // A drop on the zone opens the confirm-with-notes modal (the move itself is deferred to confirmMoveToQa).
  function onZoneDrop(e: React.DragEvent) {
    e.preventDefault()
    setQaHover(false)
    const raw = e.dataTransfer.getData(QA_MIME)
    if (!raw || !canAssign) return
    const chassisId = Number(raw)
    let bayCode = '—'
    let occ: ChassisRecord | undefined
    for (const b of bays) {
      const o = occupantByBay[b.id]
      if (o && o.id === chassisId) { bayCode = b.code; occ = o; break }
    }
    setQaNotes('')
    setQaPrompt({ bayCode, chassisId, vin: occ?.vin ?? '—', customerName: occ?.customer_name ?? '—' })
  }

  async function confirmMoveToQa() {
    if (!qaPrompt) return
    setQaBusy(true)
    try {
      await moveToAwaitingQa(qaPrompt.chassisId, qaNotes)
      toast.push({ kind: 'ok', message: `Moved to Awaiting QA — ${qaPrompt.vin}. Bay ${qaPrompt.bayCode} is now free.` })
      setQaPrompt(null)
    } catch (e) {
      if (e instanceof ApiError && (e.status === 409 || e.status === 422)) {
        toast.push({ kind: 'warn', message: e.detail || 'Could not move to Awaiting QA — refresh and retry.' })
      } else {
        handleApiError(e, toast.push)
      }
    } finally {
      setQaBusy(false)
    }
  }

  // WO v4.36a.2 — bay-tile drag SOURCE for the pre-merge return to Parking (awaiting_attachment /
  // ready_to_merge). Same DataTransfer + CustomEvent shape as the QA drag, but a different MIME so the
  // Parking pool (not the QA zone) is the drop target.
  function onParkingTileDragStart(e: React.DragEvent, chassisId: number) {
    e.dataTransfer.setData(PARK_MIME, String(chassisId))
    e.dataTransfer.effectAllowed = 'move'
    document.dispatchEvent(new CustomEvent('icb:return-to-parking-drag', { detail: { active: true } }))
  }
  function onParkingTileDragEnd() {
    document.dispatchEvent(new CustomEvent('icb:return-to-parking-drag', { detail: { active: false } }))
  }

  // A drop on the Parking pool opens the confirm-with-reason modal (the move is deferred to confirm).
  function onParkingDrop(e: React.DragEvent) {
    e.preventDefault()
    setParkingHover(false)
    const raw = e.dataTransfer.getData(PARK_MIME)
    if (!raw || !canAssign) return
    const chassisId = Number(raw)
    let bayCode = '—'
    let occ: ChassisRecord | undefined
    for (const b of bays) {
      const o = occupantByBay[b.id]
      if (o && o.id === chassisId) { bayCode = b.code; occ = o; break }
    }
    setParkingReason('')
    setParkingPrompt({ bayCode, chassisId, vin: occ?.vin ?? '—', customerName: occ?.customer_name ?? '—' })
  }

  async function confirmReturnToParking() {
    if (!parkingPrompt) return
    setParkingBusy(true)
    try {
      await returnToParking(parkingPrompt.chassisId, parkingReason)
      toast.push({ kind: 'ok', message: `Returned to parking — ${parkingPrompt.vin}. Bay ${parkingPrompt.bayCode} is now free.` })
      setParkingPrompt(null)
    } catch (e) {
      if (e instanceof ApiError && (e.status === 409 || e.status === 422)) {
        toast.push({ kind: 'warn', message: e.detail || 'Could not move to parking — refresh and retry.' })
      } else {
        handleApiError(e, toast.push)
      }
    } finally {
      setParkingBusy(false)
    }
  }

  const freeBays = bays.filter((b) => !occupantByBay[b.id] && (b.state ?? 'empty') === 'empty').length

  return (
    <div className="mt-4 grid grid-cols-[260px_1fr] gap-4" data-testid="bay-model">
      {/* Parking pool — booked-in chassis awaiting an assembly bay (status in_workshop). WO v4.36a.2: also
          a DROP TARGET for a pre-merge bay-tile drag (return a chassis to parking to free the bay). */}
      <Card
        data-testid="parking-zone"
        data-park-drop-active={parkingDragActive && canAssign ? 'true' : 'false'}
        className={`self-start${parkingDragActive && canAssign ? (parkingHover ? ' ring-2 ring-status-amber' : ' ring-1 ring-status-amber/50') : ''}`}
        onDragOver={(e) => {
          if (canAssign && e.dataTransfer.types.includes(PARK_MIME)) { e.preventDefault(); setParkingHover(true) }
        }}
        onDragLeave={() => setParkingHover(false)}
        onDrop={onParkingDrop}
      >
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
        <div className={`mt-3 border-t pt-3 text-[11px] ${
          parkingDragActive && canAssign ? 'border-status-amber font-medium text-status-amber' : 'border-line text-muted'
        }`}>
          {parkingDragActive && canAssign
            ? '↩ Drop here to return the chassis to parking'
            : <>Booked-in, awaiting a bay.{canAssign ? ' Drag onto an assembly bay →' : ''}</>}
        </div>
      </Card>

      {/* WO v4.36a.5 — right column splits the (mis-named) Assembly stage into PRE-ASSEMBLY (panels build
          down the chute) above MERGE (chassis joins the body at the chute end). VISUAL ONLY for the Burt
          demo; functional wiring + V/P counters + colour-coded ageing land in v4.36b. */}
      <div className="flex flex-col gap-4">
        {/* v1.39.1 (Item 8): LIVE Pre-Assembly card — the pre_assembly bays from useBayModel's `bays` (panels
            built down the chute, no chassis yet), driven by REAL data (not the deleted hardcoded demo cards).
            Rendered HERE only; the Merge grid's inline pre_assembly branch is removed below to avoid a double-render. */}
        <Card>
          {(() => {
            // v1.39.2 Phase 1 — Pre-Assembly is now a proper LANE (state-based, D3): EMPTY bays are panel
            // drop targets; pre_assembly bays are building. Reuses the native-DnD drop (onBayDrop →
            // panels-arrived) + clear_panels_arrived (the ✕ drag-back). The build-progress bar + manual
            // drag-to-advance land in Phase 2 (after the schema migration). The Merge lane below still
            // renders all 5 bays for the chassis/merge side, so empty bays appear in both views — a
            // Phase-1 presentation point flagged for BA review (whether to filter the Merge lane).
            const preBays = bays.filter((b) => {
              const s = b.state ?? 'empty'
              return s === 'empty' || s === 'pre_assembly'
            })
            const building = preBays.filter((b) => (b.state ?? 'empty') === 'pre_assembly').length
            return (
              <>
                <div className="mb-2 flex items-center justify-between">
                  <span className="text-sm font-semibold uppercase tracking-wide text-muted">Pre-Assembly</span>
                  <span className="text-[11px] text-muted">
                    {building} {building === 1 ? 'bay' : 'bays'} building · {preBays.length - building} free
                  </span>
                </div>
                {preBays.length > 0 ? (
                  <div className="grid grid-cols-[repeat(auto-fit,minmax(132px,1fr))] gap-2">
                    {preBays.map((bay) => {
                      const state = (bay.state ?? 'empty') as BayState
                      const isEmpty = state === 'empty'
                      const ui = BAY_TILE[state]
                      const jobNo = bay.panels_job_number ?? bay.occupant_job_number ?? bay.panels_job_id ?? '—'
                      const rejected = rejectBay === bay.id
                      const busy = busyBay === bay.id
                      // R3/R4 — only EMPTY bays highlight + accept a panel-set drop; occupied (building) bays
                      // reject (no drop handlers). The drag SOURCE (a scheduled slot-cell) is already gated on
                      // canSchedule (D2: readiness == scheduled), so not-ready / unscheduled jobs aren't draggable.
                      const dropCue = panelDragActive && canAssign && isEmpty
                        ? (panelHoverBay === bay.id ? ' ring-2 ring-sky-500' : ' ring-1 ring-sky-400/50')
                        : ''
                      return (
                        <div
                          key={bay.id}
                          data-testid={isEmpty ? 'pre-assembly-empty' : 'pre-assembly-bay'}
                          data-bay-id={bay.id}
                          data-bay-code={bay.code}
                          data-bay-state={state}
                          onDragOver={(e) => {
                            if (!canAssign || !isEmpty) return
                            const isPanel = e.dataTransfer.types.includes('application/x-panel-job')
                            if (drag || isPanel) e.preventDefault()
                          }}
                          onDragEnter={(e) => {
                            if (canAssign && isEmpty && e.dataTransfer.types.includes('application/x-panel-job')) setPanelHoverBay(bay.id)
                          }}
                          onDragLeave={() => setPanelHoverBay((b) => (b === bay.id ? null : b))}
                          onDrop={(e) => { if (isEmpty) onBayDrop(e, bay.id) }}
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
                            {!isEmpty && ui.badge ? (
                              <span className={`rounded px-1 text-[10px] font-medium ${ui.badgeClass}`}>{ui.badge}</span>
                            ) : null}
                          </div>
                          {isEmpty ? (
                            <div className="flex min-h-[42px] items-center justify-center gap-1 text-center text-[11px] text-muted">
                              <Plus size={12} /> drop a ready panel-set
                            </div>
                          ) : (
                            <>
                              <div className="font-mono text-xs font-semibold text-sky-700">Panels in bay</div>
                              <div className="truncate text-[11px] text-muted">Job {jobNo}</div>
                              {bay.panels_chassis_vin && (
                                <div className="truncate text-[11px] text-muted">{bay.panels_chassis_vin}</div>
                              )}
                              {bay.panels_customer_name && (
                                <div className="truncate text-[11px] text-muted">{bay.panels_customer_name}</div>
                              )}
                              {canAssign && bay.panels_job_id != null && (
                                <button
                                  data-testid="clear-panels-pre"
                                  onClick={() => void onClearPanels(bay)}
                                  title="Move this job's panels back out of the bay (reversible until the chassis attaches)"
                                  className="mt-1 w-full rounded border border-line px-1.5 py-0.5 text-[10px] text-muted hover:bg-surface-alt"
                                >
                                  ✕ move panels back
                                </button>
                              )}
                            </>
                          )}
                        </div>
                      )
                    })}
                  </div>
                ) : (
                  <div className="rounded-md border border-dashed border-line p-4 text-center text-xs text-muted">
                    All bays are in Merge — no empty or building pre-assembly bays right now.
                  </div>
                )}
                <div className="mt-3 border-t border-line pt-3 text-[11px] text-muted">
                  Drop a scheduled job's ready panels on an empty bay to start the body · it builds down the chute · the chassis joins it in Merge below.
                </div>
              </>
            )
          })()}
        </Card>

        {/* MERGE bays — drop targets for a parked chassis AND for a scheduled job's panels. */}
        <Card>
        <div className="mb-2 flex items-center justify-between">
          <span className="text-sm font-semibold uppercase tracking-wide text-muted">Merge</span>
          <span className="text-[11px] text-muted">{bays.length} bays · {freeBays} free</span>
        </div>
        <div className="grid grid-cols-[repeat(auto-fit,minmax(132px,1fr))] gap-2">
          {bays.map((bay) => {
            const occ = occupantByBay[bay.id]
            const state: BayState = bay.state ?? (occ ? 'awaiting_attachment' : 'empty')
            const ui = BAY_TILE[state]
            const mismatch = !!bay.mismatch                 // §3.3b — panels + a chassis from different jobs
            const hasPanels = bay.panels_job_id != null
            const rejected = rejectBay === bay.id
            const busy = busyBay === bay.id
            // §3.3b drag-visual-feedback — during a panel-job drag, light up every bay as a drop target;
            // the bay under the cursor gets the stronger ring (standard dragenter/dragleave emphasis).
            const dropCue = panelDragActive && canAssign
              ? (panelHoverBay === bay.id ? ' ring-2 ring-primary' : ' ring-1 ring-primary/40')
              : ''
            // §0.6 — a body-attached, on-bay chassis can be dragged off to the QA zone. The affordance is
            // permission-gated (canAssign): workshop/sales get no drag handle (Q5 RO).
            const isQaDraggable = canAssign && occ != null && (state === 'attached_today' || state === 'post_attached')
            // §0.x — a chassis on a bay BEFORE a merge (no body attached) can be dragged back to Parking.
            // Disjoint from isQaDraggable by state, so each tile has exactly one drag behaviour.
            const isParkingDraggable = canAssign && occ != null && (state === 'awaiting_attachment' || state === 'ready_to_merge')
            return (
              <div
                key={bay.id}
                data-testid="assembly-bay"
                data-bay-id={bay.id}
                data-bay-code={bay.code}
                data-bay-state={state}
                draggable={isQaDraggable || isParkingDraggable}
                onDragStart={(e) => {
                  if (isQaDraggable && occ) onTileDragStart(e, occ.id)
                  else if (isParkingDraggable && occ) onParkingTileDragStart(e, occ.id)
                }}
                onDragEnd={() => { onTileDragEnd(); onParkingTileDragEnd() }}
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
                onContextMenu={(e) => { if (!canAssign) return; e.preventDefault(); setCtxMenu({ bayId: bay.id, x: e.clientX, y: e.clientY }) }}
                className={`relative rounded-md p-2 transition ${
                  rejected
                    ? 'border-2 border-status-red bg-status-red/20'
                    : mismatch
                      ? 'border border-line border-l-4 border-l-status-red bg-status-red/5'
                      : ui.border
                }${dropCue}${isQaDraggable || isParkingDraggable ? ' cursor-grab active:cursor-grabbing' : ''}`}
              >
                {busy && (
                  <div className="absolute inset-0 z-10 flex items-center justify-center rounded-md bg-white/60 text-[11px] text-muted">
                    working…
                  </div>
                )}
                <div className="flex items-center justify-between text-[11px] text-muted">
                  <span>{bay.code}</span>
                  <span className="flex items-center gap-1">
                    {/* WO v4.36a.5 — days on the bay since assembly_assigned (computed; MERGE occupant tiles only) */}
                    {/* WO v4.36b §3.7 — AgeingPill colours the days-on-bay by the §0.6 default ramp
                        (green<=2 / amber 3-4 / red>=5); keeps the day-counter testid. */}
                    {occ && dayCount(bay.since) !== null && (
                      <AgeingPill days={dayCount(bay.since)!} testid="day-counter" />
                    )}
                    {mismatch ? (
                      <span data-testid="bay-mismatch" title="The panels and the chassis in this bay are different jobs — they won’t merge."
                            className="rounded px-1 text-[10px] font-medium bg-status-red/15 text-status-red">⚠ Different jobs</span>
                    ) : ui.badge ? (
                      <span className={`rounded px-1 text-[10px] font-medium ${ui.badgeClass}`}>{ui.badge}</span>
                    ) : null}
                  </span>
                </div>
                {occ ? (
                  <>
                    <div className="font-mono text-xs font-semibold">{occ.vin}</div>
                    <div className="truncate text-[11px] text-muted">{occ.customer_name || '—'}</div>
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
                {(bayFlags.get(bay.id)?.length ?? 0) > 0 && (
                  <div className="mt-1"><FlagBadges flags={bayFlags.get(bay.id)} domain="bays" entityId={bay.id} /></div>
                )}
                {mismatch && (
                  <div className="mt-0.5 truncate text-[10px] text-status-red">
                    panels: job {bay.panels_job_number ?? bay.panels_job_id} (different job)
                  </div>
                )}
                {isQaDraggable && (
                  <div data-testid="qa-drag-hint"
                       className="mt-1 flex items-center gap-1 text-[10px] font-medium text-sky-700">
                    <GripVertical size={11} className="shrink-0" /> drag to QA →
                  </div>
                )}
                {isParkingDraggable && (
                  <div data-testid="parking-drag-hint"
                       className="mt-1 flex items-center gap-1 text-[10px] font-medium text-status-amber">
                    <GripVertical size={11} className="shrink-0" /> ← drag to parking
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
                {hasPanels && canAssign && (
                  <button
                    data-testid="clear-panels"
                    onClick={() => void onClearPanels(bay)}
                    title="Remove this job’s panels from the bay (e.g. dropped on the wrong bay)"
                    className="mt-1 w-full rounded border border-line px-1.5 py-0.5 text-[10px] text-muted hover:bg-surface-alt"
                  >
                    ✕ move panels back
                  </button>
                )}
              </div>
            )
          })}
          {bays.length === 0 && <div className="text-sm text-muted">No assembly bays.</div>}
        </div>
        <div className="mt-3 border-t border-line pt-3 text-[11px] text-muted">
          {canAssign
            ? 'Drop a chassis or a scheduled job’s panels · body attaches when both meet (same job).'
            : 'A job’s chassis and its panels meet here · the body attaches when both are in the bay.'}
        </div>
        </Card>
      </div>

      {/* WO v4.36a.1 — AWAITING QA zone: full-width, below the assembly bays (workflow flows PARKING →
          ASSEMBLY → AWAITING QA). Drop target for a bay-tile drag; an inverted parking lot of chassis that
          have left their bay for QC. The drop opens the confirm-with-notes modal; the move is status-promoting
          (bay clears + chassis lands here on refresh). */}
      <Card
        data-testid="awaiting-qa-zone"
        data-qa-drop-active={qaDragActive && canAssign ? 'true' : 'false'}
        className={`col-span-2${qaDragActive && canAssign ? (qaHover ? ' ring-2 ring-sky-500' : ' ring-1 ring-sky-400/50') : ''}`}
        onDragOver={(e) => {
          if (canAssign && e.dataTransfer.types.includes(QA_MIME)) { e.preventDefault(); setQaHover(true) }
        }}
        onDragLeave={() => setQaHover(false)}
        onDrop={onZoneDrop}
      >
        <div className="mb-2 flex items-center justify-between">
          <span className="text-sm font-semibold uppercase tracking-wide text-muted">Awaiting QA</span>
          <span className="text-[11px] text-muted">{awaitingQa.length} chassis</span>
        </div>
        {awaitingQa.length > 0 ? (
          <div className="flex flex-wrap gap-2">
            {awaitingQa.map((c) => (
              <div
                key={c.chassis_id}
                data-testid="awaiting-qa-chassis"
                data-id={c.chassis_id}
                className="w-[184px] rounded-md border border-line border-l-4 border-l-sky-500 bg-sky-50 p-2"
              >
                <div className="flex items-center justify-between">
                  <span className="font-mono text-xs font-semibold">{c.vin || '—'}</span>
                  <span className="rounded px-1 text-[10px] font-medium bg-sky-100 text-sky-700">QA</span>
                </div>
                <div className="truncate text-xs text-body">{c.customer_name || '—'}</div>
                <div className="truncate text-[11px] text-muted">
                  {[c.make, c.model].filter(Boolean).join(' ') || '—'}
                  {c.job_number ? ` · ${c.job_number}` : ''}
                </div>
              </div>
            ))}
          </div>
        ) : (
          <div
            className={`rounded-md border border-dashed p-4 text-center text-xs ${
              qaDragActive && canAssign ? 'border-sky-400 bg-sky-50 text-sky-700' : 'border-line text-muted'
            }`}
          >
            {canAssign
              ? 'Drag a completed (body-attached) chassis here to free the bay.'
              : 'No chassis awaiting QA.'}
          </div>
        )}
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

      {/* WO v4.36a.1 — Awaiting-QA confirm: opened by a drop on the zone; optional handover note (the
          v4.34.2 confirm-modal pattern). Confirm fires the status-promoting move (bay clears + chassis lands
          in the zone on refresh). */}
      {qaPrompt && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
          data-testid="qa-prompt"
          onClick={() => { if (!qaBusy) setQaPrompt(null) }}
        >
          <div className="w-full max-w-sm rounded-lg bg-white p-5 shadow-xl" onClick={(e) => e.stopPropagation()}>
            <div className="text-sm font-semibold text-body">Move to Awaiting QA — {qaPrompt.bayCode}</div>
            <p className="mt-2 text-sm text-muted">
              Chassis <span className="font-mono text-body">{qaPrompt.vin}</span>
              {qaPrompt.customerName !== '—' ? <> ({qaPrompt.customerName})</> : null} leaves the bay and joins
              the QA queue. Bay <span className="font-semibold text-body">{qaPrompt.bayCode}</span> frees up.
            </p>
            <label className="mt-3 block text-[11px] font-semibold uppercase tracking-wide text-muted">
              Handover note (optional)
            </label>
            <textarea
              data-testid="qa-notes"
              value={qaNotes}
              onChange={(e) => setQaNotes(e.target.value)}
              rows={2}
              maxLength={500}
              placeholder="e.g. minor paint touch-up flagged for QC"
              className="mt-1 w-full rounded-md border border-line p-2 text-sm focus:border-primary focus:outline-none"
            />
            <div className="mt-4 flex justify-end gap-2">
              <button
                onClick={() => setQaPrompt(null)}
                disabled={qaBusy}
                className="rounded-md border border-line px-3 py-1.5 text-sm text-body hover:bg-surface-alt disabled:opacity-50"
              >
                Cancel
              </button>
              <button
                onClick={() => void confirmMoveToQa()}
                data-testid="qa-confirm"
                disabled={qaBusy}
                className="rounded-md bg-sky-600 px-3 py-1.5 text-sm font-semibold text-white hover:bg-sky-700 disabled:opacity-50"
              >
                {qaBusy ? 'Moving…' : 'Move to QA'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* WO v4.36a.2 — return-to-parking confirm: opened by a drop on the Parking pool; optional
          re-prioritisation reason (the v4.34.2 unschedule-revert pattern). Confirm frees the bay + the
          chassis reappears in Parking on refresh. */}
      {parkingPrompt && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
          data-testid="parking-prompt"
          onClick={() => { if (!parkingBusy) setParkingPrompt(null) }}
        >
          <div className="w-full max-w-sm rounded-lg bg-white p-5 shadow-xl" onClick={(e) => e.stopPropagation()}>
            <div className="text-sm font-semibold text-body">Return to parking — {parkingPrompt.bayCode}</div>
            <p className="mt-2 text-sm text-muted">
              Chassis <span className="font-mono text-body">{parkingPrompt.vin}</span>
              {parkingPrompt.customerName !== '—' ? <> ({parkingPrompt.customerName})</> : null} leaves the bay
              and goes back to the parking pool. Bay <span className="font-semibold text-body">{parkingPrompt.bayCode}</span> frees
              up for a more urgent job.
            </p>
            <label className="mt-3 block text-[11px] font-semibold uppercase tracking-wide text-muted">
              Reason (optional)
            </label>
            <textarea
              data-testid="parking-reason"
              value={parkingReason}
              onChange={(e) => setParkingReason(e.target.value)}
              rows={2}
              maxLength={500}
              placeholder="e.g. bumped for a rush order"
              className="mt-1 w-full rounded-md border border-line p-2 text-sm focus:border-primary focus:outline-none"
            />
            <div className="mt-4 flex justify-end gap-2">
              <button
                onClick={() => setParkingPrompt(null)}
                disabled={parkingBusy}
                className="rounded-md border border-line px-3 py-1.5 text-sm text-body hover:bg-surface-alt disabled:opacity-50"
              >
                Cancel
              </button>
              <button
                onClick={() => void confirmReturnToParking()}
                data-testid="parking-confirm"
                disabled={parkingBusy}
                className="rounded-md bg-status-amber px-3 py-1.5 text-sm font-semibold text-white hover:bg-status-amber/90 disabled:opacity-50"
              >
                {parkingBusy ? 'Moving…' : '↩ Move to parking'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* WO — bay right-click context menu: shows which job + chassis the bay's panels belong to, and an
          Unlink action (reuses the move-panels-back DELETE) so the operator can free a bay blocked by a
          crossed-panels drop and return that job to the planner. */}
      {ctxMenu && (() => {
        const bay = bays.find((b) => b.id === ctxMenu.bayId)
        if (!bay) return null                                  // refetched away → auto-close on next render
        const hasPanels = bay.panels_job_id != null
        const x = Math.max(8, Math.min(ctxMenu.x, window.innerWidth - 250))   // keep on-screen
        const y = Math.max(8, Math.min(ctxMenu.y, window.innerHeight - 180))
        return (
          <div
            data-testid="bay-context-menu"
            onMouseDown={(e) => e.stopPropagation()}           // so clicks inside don't trigger the close listener
            style={{ left: x, top: y }}
            className="fixed z-50 w-60 rounded-md border border-line bg-white p-3 text-xs shadow-xl"
          >
            <div className="mb-1.5 font-semibold text-body">Bay {bay.code}</div>
            {hasPanels ? (
              <div className="space-y-0.5 text-muted">
                <div>Panels: <span className="font-semibold text-body">Job {bay.panels_job_number ?? bay.panels_job_id}</span></div>
                <div>Chassis VIN: <span className="font-mono text-body">{bay.panels_chassis_vin ?? '—'}</span></div>
                <div>Customer: <span className="text-body">{bay.panels_customer_name ?? '—'}</span></div>
              </div>
            ) : (
              <div className="text-muted">No panels on this bay.</div>
            )}
            {bay.occupant_chassis_id != null && (
              <div className="mt-2 border-t border-line pt-2 text-muted">
                Chassis on bay: <span className="font-semibold text-body">Job {bay.occupant_job_number ?? '—'}</span>
                {' · '}<span className="font-mono text-body">{bay.occupant_vin ?? '—'}</span>
              </div>
            )}
            {bay.mismatch && (
              <div className="mt-2 rounded bg-status-red/10 px-2 py-1 text-[10px] text-status-red">
                ⚠ The panels and the chassis are different jobs — they won’t merge.
              </div>
            )}
            {hasPanels && canAssign && (
              <button
                data-testid="unlink-panels"
                onClick={() => { const b = bay; setCtxMenu(null); void onClearPanels(b) }}
                className="mt-2 w-full rounded bg-status-red/10 px-2 py-1.5 text-[11px] font-semibold text-status-red hover:bg-status-red/20"
              >
                Unlink panels — return job to planner
              </button>
            )}
          </div>
        )
      })()}
    </div>
  )
}
