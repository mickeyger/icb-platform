// PlanningCockpit.tsx — WO Cockpit (Concept 6). An ADDITIVE alternate Planning layout at
// /planning/cockpit: a 3-pane cockpit (collapsible Unscheduled rail · hero timeline · persistent
// inspector) with a collapsible bottom dock for the bay-model flow zones, plus native-fullscreen
// Focus Mode. It reuses the SAME live data + mutators as the board (usePlanning / useCostings) and
// the standalone BayModelLanes / JobCardSections / PlanningAckPanel components.
//
// The week-grid + Unscheduled pool logic below is DUPLICATED from PlanningBoard's LivePlanningBoard
// (those parts are module-private there). KEEP IN SYNC with PlanningBoard.tsx; never edit the original
// — the existing /planning board is frozen for the demo.
import { Fragment, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import {
  GripVertical, CalendarDays, Maximize, Layers, X,
  ChevronsLeft, ChevronsRight, ChevronUp, ChevronDown,
} from 'lucide-react'
import { data } from '../../../data/mockData'
import { zarShort, dmy, monthYear, nextMonths } from '../../../lib/format'
import { Card } from '../../../components/ui/primitives'
import { Spinner, Skeleton, EmptyState, LastUpdated } from '../../../components/ui/feedback'
import { ApiError } from '../../../lib/api'
import { useToast } from '../../../components/ui/toast'
import { useAppData } from '../../../store/AppDataContext'
import { useCostings } from '../../../store/CostingsContext'
import { usePlanning } from '../../../store/PlanningContext'
import { useRefetchOnFocus } from '../../../lib/useRefetchOnFocus'
import { getChassisState, type PlanningJob, type PlanningSlot, type PlanningWeekCol } from '../../../lib/types'
import type { Costing } from '../../../data/costingsData'
import { BayModelLanes } from '../BayModelLanes'
import { PlanningAckPanel } from '../PlanningAckPanel'
import { ChassisBadge, SourceBadge, FooterRow } from './badges'
import { CockpitSlotDetail } from './CockpitSlotDetail'
import { useCockpitLayout } from './useCockpitLayout'

const SLOTS = ['V-1', 'V-2', 'V-3', 'V-4', 'V-5', 'P-1', 'P-2', 'P-3']

// Middle-mouse drag-to-pan for the grid panel (duplicated from PlanningBoard.tsx).
function useMiddleButtonPan<T extends HTMLElement>() {
  const ref = useRef<T>(null)
  useEffect(() => {
    const el = ref.current
    if (!el) return
    let panning = false
    let startX = 0, startY = 0, startLeft = 0, startTop = 0
    const onMove = (e: MouseEvent) => {
      if (!panning) return
      el.scrollLeft = startLeft - (e.clientX - startX)
      el.scrollTop = startTop - (e.clientY - startY)
    }
    const onUp = () => {
      if (!panning) return
      panning = false
      el.style.cursor = ''
      el.style.userSelect = ''
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mouseup', onUp)
    }
    const onDown = (e: MouseEvent) => {
      if (e.button !== 1) return
      panning = true
      startX = e.clientX; startY = e.clientY
      startLeft = el.scrollLeft; startTop = el.scrollTop
      el.style.cursor = 'grabbing'
      el.style.userSelect = 'none'
      e.preventDefault()
      window.addEventListener('mousemove', onMove)
      window.addEventListener('mouseup', onUp)
    }
    el.addEventListener('mousedown', onDown)
    return () => {
      el.removeEventListener('mousedown', onDown)
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mouseup', onUp)
    }
  }, [])
  return ref
}

export function PlanningCockpit() {
  const { mode } = usePlanning()
  if (mode === 'loading') return <CockpitSkeleton />
  if (mode !== 'live') return <CockpitMockNotice />
  return <LiveCockpit />
}

function CockpitSkeleton() {
  return (
    <div className="flex h-full flex-col p-3">
      <div className="mb-3 flex shrink-0 items-center justify-between">
        <h1 className="text-xl font-bold text-body">Planning Cockpit</h1>
        <span className="text-xs text-muted">Loading…</span>
      </div>
      <div className="grid min-h-0 flex-1 grid-cols-[232px_1fr_340px] gap-2">
        <Card className="min-h-0 overflow-y-auto"><Skeleton rows={4} /></Card>
        <Card className="min-h-0 overflow-auto p-0"><Skeleton rows={8} /></Card>
        <Card className="min-h-0 overflow-y-auto"><Skeleton rows={5} /></Card>
      </div>
    </div>
  )
}

// Cockpit duplicates only the LIVE board; offline/mock demos keep using the original board.
function CockpitMockNotice() {
  return (
    <div className="p-6">
      <div className="mb-1 text-[11px] text-muted">MES › Planning › Cockpit (beta)</div>
      <h1 className="mb-3 text-xl font-bold text-body">Planning Cockpit</h1>
      <Card className="max-w-xl">
        <div className="text-sm text-body">
          The Cockpit runs on live planning data and the API isn’t reachable right now (offline / demo
          fallback mode). Use the classic board instead — it renders the bundled demo data.
        </div>
        <Link to="/planning" className="mt-3 inline-flex rounded-md bg-primary px-3 py-1.5 text-sm font-semibold text-white hover:bg-primary-dark">
          Open the Planning Board
        </Link>
      </Card>
    </div>
  )
}

function LiveCockpit() {
  const nav = useNavigate()
  const { board, schedule, move, unschedule, revertToUnscheduled, lastUpdated, refresh, jumpTo, today, nextWindow, prevWindow } = usePlanning()
  useRefetchOnFocus(refresh)
  const { profile, hasPermission } = useAppData()
  const { costings, ackPlanning, markChassisReceived } = useCostings()
  const toast = useToast()
  const layout = useCockpitLayout()
  const rootRef = useRef<HTMLDivElement>(null)
  const panRef = useMiddleButtonPan<HTMLDivElement>()

  const canSchedule = hasPermission('planning.schedule')
  const canUnschedule = hasPermission('planning.unschedule')
  const canTickChassis = hasPermission('production.chassis_received')
  const target = data.kpis.weekly_target_zar
  const byActor = profile.id === 'rep_burt' ? 'BURT' : profile.id

  const ackCandidates = useMemo(
    () => costings.filter((c) => c.status === 'Pre-Job Confirmed' && c.production_job_id != null),
    [costings],
  )

  const [dragPoolJob, setDragPoolJob] = useState<PlanningJob | null>(null)
  const [dragSlot, setDragSlot] = useState<PlanningSlot | null>(null)
  const [spinnerKey, setSpinnerKey] = useState<string | null>(null)
  const [rejectKey, setRejectKey] = useState<string | null>(null)
  const [poolHot, setPoolHot] = useState(false)
  const [ackTarget, setAckTarget] = useState<Costing | null>(null)
  const [sourceFilter, setSourceFilter] = useState<'all' | 'quote' | 'workbook'>('all')
  const matchesSource = (j: PlanningJob) => sourceFilter === 'all' || j.source === sourceFilter

  // Inspector selection (replaces the SidePanel pop-up). Re-derive the LIVE slot by id each render so
  // the inspector follows mutations (the board replaces board.slots on every schedule/move/unschedule).
  const [selectedSlotId, setSelectedSlotId] = useState<number | null>(null)
  const [pinned, setPinned] = useState(false)
  const selectedLiveSlot = useMemo(
    () => (selectedSlotId == null ? null : board.slots.find((s) => s.id === selectedSlotId && s.job) ?? null),
    [board.slots, selectedSlotId],
  )

  // Same-page sync: bay mutations → refetch the grid (PR #39). Identical to the board.
  useEffect(() => {
    const onBoardChange = () => { void refresh() }
    document.addEventListener('icb:planning-refetch', onBoardChange)
    return () => document.removeEventListener('icb:planning-refetch', onBoardChange)
  }, [refresh])

  // When the planner starts dragging a scheduled job's panels (icb:panel-drag), auto-open the dock so
  // the bay drop targets (BayModelLanes) are mounted + visible to receive the drop.
  const setDockOpen = layout.setDockOpen
  useEffect(() => {
    const onPanelDrag = (e: Event) => {
      const active = (e as CustomEvent<{ active?: boolean }>).detail?.active
      if (active) setDockOpen(true)
    }
    document.addEventListener('icb:panel-drag', onPanelDrag)
    return () => document.removeEventListener('icb:panel-drag', onPanelDrag)
  }, [setDockOpen])

  async function markSlotChassisReceived(slot: PlanningSlot) {
    if (!slot.job) return
    const costing = costings.find((c) => c.production_job_id === slot.job!.id)
    if (!costing) {
      toast.push({ kind: 'warn', message: 'Could not match this slot to a costing.' })
      return
    }
    await markChassisReceived(costing.quote_number, todayIso(), byActor)
    await refresh()
  }

  const bays = useMemo(() => {
    const extra = board.bays.filter((b) => !SLOTS.includes(b))
    return [...SLOTS, ...extra]
  }, [board.bays])

  const cellFor = (weekKey: string, bay: string): PlanningSlot | undefined =>
    board.slots.find((s) => s.week_key === weekKey && s.bay === bay)
  const capFor = (weekKey: string) => board.capacity.find((c) => c.week_key === weekKey)
  const laneForBay = (bay: string): string => (bay.startsWith('P') ? 'panelshop' : 'vacuum')
  function flashReject(key: string) {
    setRejectKey(key)
    setTimeout(() => setRejectKey(null), 1800)
  }

  async function dropOnCell(week: PlanningWeekCol, bay: string) {
    const key = `${week.key}:${bay}`
    if (dragSlot) {
      const src = dragSlot
      setDragSlot(null)
      if (src.week_key === week.key && src.bay === bay) return
      try {
        setSpinnerKey(key)
        await move(src.id, { week: week.start, bay, lane: laneForBay(bay) })
      } catch (e) {
        if (e instanceof ApiError && e.status === 409) {
          flashReject(key)
          toast.push({ kind: 'warn', message: 'That cell is already occupied.' })
        }
      } finally {
        setSpinnerKey(null)
      }
      return
    }
    if (dragPoolJob) {
      const job = dragPoolJob
      setDragPoolJob(null)
      if (getChassisState(job) === 'none') {
        toast.push({
          kind: 'warn',
          message:
            'No chassis ETA committed yet — rep should confirm an ETA with the customer/dealer before this job can be scheduled.',
        })
        return
      }
      try {
        setSpinnerKey(key)
        await schedule({ production_job_id: job.id, week: week.start, bay, lane: laneForBay(bay) })
      } catch (e) {
        if (e instanceof ApiError && e.status === 409) {
          flashReject(key)
          toast.push({ kind: 'warn', message: 'That cell is already occupied.' })
        }
      } finally {
        setSpinnerKey(null)
      }
    }
  }

  async function dropOnPool() {
    setPoolHot(false)
    if (!dragSlot) return
    const src = dragSlot
    setDragSlot(null)
    if (!canUnschedule) {
      toast.push({ kind: 'warn', message: "You don't have permission to unschedule jobs." })
      return
    }
    try {
      await unschedule(src.id)
    } catch {
      /* surfaced by the context */
    }
  }

  const poolJobs = board.pool.filter(matchesSource)
  const poolCount = poolJobs.length + ackCandidates.length
  const { leftCollapsed, rightCollapsed, dockOpen, isFullscreen } = layout
  const rightExpanded = !rightCollapsed || !!selectedLiveSlot || pinned
  const gridTemplateColumns = `${leftCollapsed ? '40px' : '232px'} minmax(0,1fr) ${rightExpanded ? '340px' : '40px'}`

  return (
    <div ref={rootRef} className="flex h-full flex-col gap-2 bg-surface-alt/30 p-3">
      {/* ── Toolbar ─────────────────────────────────────────────────────────── */}
      <div className="flex shrink-0 flex-wrap items-center justify-between gap-2">
        <div>
          <div className="mb-0.5 flex items-center gap-2 text-[11px] text-muted">
            MES › Planning › Cockpit
            <span className="rounded bg-primary/10 px-1.5 py-0.5 text-[9px] font-bold uppercase text-primary">beta</span>
          </div>
          <h1 className="text-xl font-bold text-body">Planning Cockpit</h1>
        </div>
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <div className="flex items-center gap-1" title="Filter board by job source">
            {(['all', 'quote', 'workbook'] as const).map((s) => (
              <button
                key={s}
                onClick={() => setSourceFilter(s)}
                className={`rounded-md px-2.5 py-1.5 text-xs font-semibold transition ${
                  sourceFilter === s ? 'bg-primary text-white' : 'border border-line bg-white text-body hover:bg-surface-alt'
                }`}
              >
                {s === 'all' ? 'All' : s === 'quote' ? 'Quote-born' : 'Workbook'}
              </button>
            ))}
          </div>
          <div className="flex items-center gap-1">
            <button onClick={prevWindow} title="Earlier weeks" aria-label="Earlier weeks"
              className="rounded-md border border-line bg-white px-2 py-1.5 text-xs font-semibold hover:bg-surface-alt">‹</button>
            <select
              value=""
              onChange={(e) => { if (e.target.value) jumpTo(e.target.value) }}
              title="Jump to month"
              className="rounded-md border border-line bg-white px-2 py-1.5 text-xs outline-none"
            >
              <option value="">Jump to month…</option>
              {nextMonths(12).map((m) => <option key={m.iso} value={m.iso}>{m.label}</option>)}
            </select>
            <button onClick={nextWindow} title="Later weeks" aria-label="Later weeks"
              className="rounded-md border border-line bg-white px-2 py-1.5 text-xs font-semibold hover:bg-surface-alt">›</button>
            <button onClick={today}
              className="rounded-md border border-line bg-white px-2.5 py-1.5 text-xs font-semibold hover:bg-surface-alt">Today</button>
          </div>
          <span className="hidden rounded-md border border-line bg-white px-3 py-1.5 text-xs lg:inline">
            {board.weeks.length ? `${monthYear(board.weeks[0].start)} · ${board.weeks.length} wks` : `${board.weeks.length} weeks`}
          </span>
          {/* Layout controls */}
          <div className="flex items-center gap-1 border-l border-line pl-2">
            <button onClick={layout.toggleLeft} aria-pressed={leftCollapsed}
              title={leftCollapsed ? 'Show Unscheduled rail' : 'Collapse Unscheduled rail'}
              className="rounded-md border border-line bg-white p-1.5 text-muted hover:bg-surface-alt">
              {leftCollapsed ? <ChevronsRight size={15} /> : <ChevronsLeft size={15} />}
            </button>
            <button onClick={layout.maxHero}
              title="Maximise the timeline (collapse rails + dock)"
              className="rounded-md border border-line bg-white px-2 py-1.5 text-xs font-semibold text-muted hover:bg-surface-alt">
              Max hero
            </button>
            <button onClick={() => layout.toggleFullscreen(rootRef.current)} aria-pressed={isFullscreen}
              title={isFullscreen ? 'Exit full-screen (Esc)' : 'Focus mode — full-screen the cockpit'}
              className={`flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-xs font-semibold transition ${
                isFullscreen ? 'bg-primary text-white' : 'border border-line bg-white text-body hover:bg-surface-alt'
              }`}>
              <Maximize size={14} /> {isFullscreen ? 'Exit full-screen' : 'Focus'}
            </button>
          </div>
        </div>
      </div>

      {/* ── 3-pane body ─────────────────────────────────────────────────────── */}
      <div className="grid min-h-0 flex-1 gap-2" style={{ gridTemplateColumns }}>
        {/* LEFT RAIL — Unscheduled pool (collapsible) */}
        {leftCollapsed ? (
          <button onClick={layout.toggleLeft} title="Show Unscheduled rail"
            className="flex min-h-0 flex-col items-center gap-2 rounded-lg border border-line bg-white py-2 text-muted hover:border-primary/40">
            <ChevronsRight size={15} />
            <span style={{ writingMode: 'vertical-rl' }} className="text-[11px] font-semibold uppercase tracking-wide">
              Unscheduled ({poolCount})
            </span>
          </button>
        ) : (
          <Card className="min-h-0 overflow-y-auto">
            <div
              onDragOver={(e) => { if (dragSlot) { e.preventDefault(); setPoolHot(true) } }}
              onDragLeave={() => setPoolHot(false)}
              onDrop={() => dropOnPool()}
              className={`rounded-md transition ${poolHot ? 'ring-2 ring-status-amber' : ''}`}
            >
              <div className="mb-2 flex items-center justify-between">
                <span className="text-sm font-semibold uppercase tracking-wide text-muted">Unscheduled ({poolCount})</span>
                <button onClick={layout.toggleLeft} title="Collapse rail" className="rounded p-0.5 text-muted hover:bg-surface-alt"><ChevronsLeft size={14} /></button>
              </div>
              {ackCandidates.length > 0 && (
                <div className="mb-3 space-y-2">
                  {ackCandidates.map((c) => (
                    <button
                      key={c.quote_number}
                      onClick={() => setAckTarget(c)}
                      className="flex w-full items-start gap-2 rounded-md border-l-4 border-[#06B6D4] bg-[#06B6D4]/5 p-2 text-left hover:bg-[#06B6D4]/10 animate-pulseRing"
                    >
                      <CalendarDays size={14} className="mt-0.5 text-[#06B6D4]" />
                      <div className="flex-1">
                        <div className="font-mono text-sm font-semibold">#{c.job_number_assigned ?? c.quote_number}</div>
                        <div className="text-xs text-body">{c.customer_name}</div>
                        <div className="mt-1 text-[10px] font-medium text-[#0E7490]">Awaiting Planning ack · click to acknowledge</div>
                      </div>
                    </button>
                  ))}
                </div>
              )}
              <div className="space-y-2">
                {poolJobs.map((job) => (
                  <div
                    key={job.id}
                    draggable={canSchedule}
                    onDragStart={() => { if (canSchedule) setDragPoolJob(job) }}
                    onDragEnd={() => setDragPoolJob(null)}
                    className={`flex items-start gap-2 rounded-md border border-line bg-white p-2 ${
                      canSchedule ? 'cursor-grab active:cursor-grabbing' : ''
                    }`}
                  >
                    {canSchedule && <GripVertical size={14} className="mt-0.5 text-muted" />}
                    <div className="flex-1">
                      <div className="flex flex-wrap items-center justify-between gap-1">
                        <span className="font-mono text-sm font-semibold">#{job.job_number}</span>
                        <span className="flex items-center gap-1">
                          <SourceBadge source={job.source} />
                          <ChassisBadge state={getChassisState(job)} eta={job.chassis_eta} />
                        </span>
                      </div>
                      <div className="text-xs text-body">{job.customer}</div>
                      {job.body_type && <div className="text-[11px] text-muted">{job.body_type}</div>}
                    </div>
                  </div>
                ))}
                {poolJobs.length === 0 && <div className="text-sm text-muted">All scheduled.</div>}
              </div>
              <div className="mt-3 border-t border-line pt-3 text-[11px] text-muted">
                Drag a card onto a slot →{canUnschedule ? ' · drop a scheduled job here to unschedule' : ''}
              </div>
            </div>
          </Card>
        )}

        {/* CENTRE — hero timeline (week grid) */}
        <Card className="flex min-h-0 flex-col overflow-hidden p-0">
          <div ref={panRef} className="min-h-0 flex-1 overflow-auto" title="Tip: hold the middle mouse button and drag to pan">
            {board.weeks.length === 0 ? (
              <EmptyState
                title="No scheduled weeks yet"
                hint="Schedule a job from the unscheduled pool to populate the board."
              />
            ) : (
              <table className="w-full border-collapse text-sm">
                <thead>
                  <tr className="text-white">
                    <th className="sticky left-0 top-0 z-30 bg-primary px-2 py-2 text-left font-semibold">Slot</th>
                    {board.weeks.map((w) => (
                      <th key={w.key} className="sticky top-0 z-20 bg-primary px-2 py-2 text-left font-semibold">
                        {w.key}
                        <div className="text-[10px] font-normal opacity-80">{dmy(w.start)}</div>
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {bays.map((bay, bayIdx) => {
                    const lane = laneForBay(bay)
                    const showLane = bayIdx === 0 || laneForBay(bays[bayIdx - 1]) !== lane
                    return (
                    <Fragment key={bay}>
                      {showLane && (
                        <tr className="border-b border-line">
                          <td colSpan={board.weeks.length + 1} className="sticky left-0 bg-surface-alt px-2 py-1 text-[10px] font-semibold uppercase tracking-wide text-muted">
                            {lane === 'panelshop' ? 'Press' : 'Vacuum'}
                          </td>
                        </tr>
                      )}
                    <tr className="border-b border-line">
                      <td className="sticky left-0 z-10 bg-surface-alt px-2 py-1.5 font-mono text-xs font-semibold shadow-[inset_-1px_0_0_#E5E7EB]">{bay}</td>
                      {board.weeks.map((w) => {
                        const cell = cellFor(w.key, bay)
                        const key = `${w.key}:${bay}`
                        const rejected = rejectKey === key
                        const busy = spinnerKey === key
                        const selected = !!cell?.job && cell.id === selectedSlotId
                        return (
                          <td
                            key={key}
                            onDragOver={(e) => e.preventDefault()}
                            onDrop={() => dropOnCell(w, bay)}
                            className={`relative h-12 px-1 py-1 align-top transition ${
                              rejected ? 'bg-status-red/30 ring-2 ring-status-red' : cell ? '' : 'bg-surface-alt/40'
                            }`}
                          >
                            {busy && (
                              <div className="absolute inset-0 z-10 flex items-center justify-center bg-white/60">
                                <Spinner size={16} className="text-primary" />
                              </div>
                            )}
                            {cell && cell.job ? (
                              <button
                                onClick={() => setSelectedSlotId(cell.id)}
                                data-testid="cockpit-slot-cell"
                                data-job-id={cell.job.id}
                                draggable={canSchedule}
                                onDragStart={(e) => {
                                  if (!canSchedule) { e.preventDefault(); return }
                                  setDragSlot(cell)
                                  if (cell.job) {
                                    e.dataTransfer.setData('application/x-panel-job', String(cell.job.id))
                                    e.dataTransfer.effectAllowed = 'copyMove'
                                    document.dispatchEvent(new CustomEvent('icb:panel-drag', { detail: { active: true } }))
                                  }
                                }}
                                onDragEnd={() => {
                                  setDragSlot(null)
                                  document.dispatchEvent(new CustomEvent('icb:panel-drag', { detail: { active: false } }))
                                }}
                                title={cell.job.customer}
                                className={`flex w-full items-center gap-1 rounded border-l-4 bg-white px-1.5 py-1 text-left hover:border-primary ${
                                  selected ? 'border-primary ring-1 ring-primary' : 'border-status-green'
                                } ${canSchedule ? 'cursor-grab active:cursor-grabbing' : ''} ${matchesSource(cell.job) ? '' : 'opacity-30'}`}
                              >
                                <span className="flex-1">
                                  <span className="font-mono text-xs font-semibold">{cell.job.job_number}</span>
                                  {cell.job.vin && (
                                    <span className="block truncate font-mono text-[10px] text-muted"
                                          title={cell.job.vin} data-testid="cockpit-slot-vin">{cell.job.vin}</span>
                                  )}
                                  <span className="block truncate text-[11px] text-muted">{cell.job.customer}</span>
                                </span>
                                <span className="flex items-center gap-1">
                                  <SourceBadge source={cell.job.source} />
                                  <ChassisBadge state={getChassisState(cell.job)} eta={cell.job.chassis_eta} />
                                </span>
                              </button>
                            ) : null}
                          </td>
                        )
                      })}
                    </tr>
                    </Fragment>
                    )
                  })}
                  <FooterRow
                    label="Filled"
                    cells={board.weeks.map((w) => `${capFor(w.key)?.filled ?? 0}`)}
                    tooltipKey="planning_board.weekly_capacity_footer"
                  />
                  <FooterRow label="Empty" cells={board.weeks.map((w) => `${capFor(w.key)?.empty ?? 0}`)} />
                  <FooterRow label="Value" cells={board.weeks.map((w) => zarShort(capFor(w.key)?.value_zar ?? 0))} strong />
                  <FooterRow
                    label="Gap vs target"
                    cells={board.weeks.map((w) => zarShort((capFor(w.key)?.value_zar ?? 0) - target))}
                    tone={board.weeks.map((w) => ((capFor(w.key)?.value_zar ?? 0) >= target ? 'green' : 'red'))}
                  />
                </tbody>
              </table>
            )}
          </div>
        </Card>

        {/* RIGHT — persistent inspector (replaces the slot pop-up) */}
        {rightExpanded ? (
          <Card className="flex min-h-0 flex-col overflow-hidden p-0">
            <div className="flex shrink-0 items-center justify-between border-b border-line px-3 py-2">
              <span className="text-sm font-semibold text-body">
                {selectedLiveSlot?.job ? `Job #${selectedLiveSlot.job.job_number}` : 'Inspector'}
              </span>
              <div className="flex items-center gap-1">
                <button
                  onClick={() => setPinned((p) => !p)}
                  aria-pressed={pinned}
                  title={pinned ? 'Unpin — let the panel collapse when nothing is selected' : 'Pin the inspector open'}
                  className={`rounded px-1.5 py-0.5 text-[11px] font-semibold ${pinned ? 'bg-primary/10 text-primary' : 'text-muted hover:bg-surface-alt'}`}
                >
                  {pinned ? 'Pinned' : 'Pin'}
                </button>
                <button onClick={() => setSelectedSlotId(null)}
                  title="Clear selection" className="rounded p-1 text-muted hover:bg-surface-alt"><X size={14} /></button>
              </div>
            </div>
            <div className="min-h-0 flex-1 overflow-y-auto p-3">
              {selectedLiveSlot?.job ? (
                <CockpitSlotDetail
                  slot={selectedLiveSlot}
                  canTick={canTickChassis}
                  canRevert={canUnschedule && selectedLiveSlot.job?.status === 'planning'}
                  onMarkReceived={() => markSlotChassisReceived(selectedLiveSlot)}
                  onRevert={async (reason) => {
                    const jid = selectedLiveSlot.job?.id
                    if (jid == null) return
                    try {
                      await revertToUnscheduled(jid, reason)
                      setSelectedSlotId(null)
                    } catch { /* surfaced by the context toast */ }
                  }}
                  onViewProduction={() => {
                    const jn = selectedLiveSlot.job?.job_number
                    nav(jn ? `/production?jobId=${encodeURIComponent(jn)}` : '/production')
                  }}
                />
              ) : (
                <EmptyState title="No job selected" hint="Click a job on the timeline to inspect it here — no pop-up." />
              )}
            </div>
          </Card>
        ) : (
          <button onClick={layout.toggleRight} title="Show inspector"
            className="flex min-h-0 flex-col items-center gap-2 rounded-lg border border-line bg-white py-2 text-muted hover:border-primary/40">
            <ChevronsLeft size={15} />
            <span style={{ writingMode: 'vertical-rl' }} className="text-[11px] font-semibold uppercase tracking-wide">Inspector</span>
          </button>
        )}
      </div>

      {/* ── Bottom dock — bay-model flow zones (collapsed by default) ─────────── */}
      <div className="shrink-0 overflow-hidden rounded-lg border border-line bg-white">
        <button onClick={layout.toggleDock}
          aria-expanded={dockOpen}
          className="flex w-full items-center justify-between px-3 py-2 text-left hover:bg-surface-alt">
          <span className="flex items-center gap-2 text-sm font-semibold text-body">
            <Layers size={15} className="text-primary" />
            Bay model
            <span className="text-xs font-normal text-muted">Parking · Pre-Assembly · Merge · Awaiting QA · Dispatch</span>
          </span>
          {dockOpen ? <ChevronDown size={16} className="text-muted" /> : <ChevronUp size={16} className="text-muted" />}
        </button>
        {dockOpen && (
          <div className="max-h-[44vh] overflow-auto border-t border-line p-3">
            <BayModelLanes />
          </div>
        )}
      </div>

      {/* ── Footer ───────────────────────────────────────────────────────────── */}
      <div className="flex shrink-0 items-center justify-between">
        <LastUpdated at={lastUpdated} onRefresh={refresh} />
        {!canSchedule && (
          <span className="text-[11px] text-muted">Read-only — your role can’t schedule on the board.</span>
        )}
      </div>

      {/* Ack flow stays a modal (reused as-is). */}
      <PlanningAckPanel
        costing={ackTarget}
        onClose={() => setAckTarget(null)}
        onAcknowledge={async (c, payload) => {
          await ackPlanning(c.quote_number, byActor, payload)
          await refresh()
          setAckTarget(null)
        }}
      />
    </div>
  )
}

function todayIso(): string {
  const d = new Date()
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}
