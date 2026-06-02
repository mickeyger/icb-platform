import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ChevronLeft, ChevronRight, Plus, Truck, PackageX, GripVertical, CheckCircle2, AlertTriangle } from 'lucide-react'
import { data } from '../../data/mockData'
import { zarShort, zar, dmy } from '../../lib/format'
import { Card, StatusPill } from '../../components/ui/primitives'
import { SidePanel } from '../../components/ui/overlays'
import { JobDetailStub } from '../../components/JobDetailStub'
import { Tooltip } from '../../components/ui/Tooltip'
import { CalendarDays, Wrench } from 'lucide-react'
import { useCostings } from '../../store/CostingsContext'
import { useAppData } from '../../store/AppDataContext'
import { PlanningAckPanel } from './PlanningAckPanel'
import type { Costing } from '../../data/costingsData'
import type { SlotAssignment, UnscheduledJob } from '../../data/types'

// v4.5 — local extension of SlotAssignment that may carry a per-cell override
// of chassis_received_at when the planner ticks the Planning-Board tick box
// (for cells that aren't linked to a v4 costing — those route through the
// costing-level markChassisReceived mutator instead).
type LocalSlot = SlotAssignment & {
  chassis_received_at?: string | null
  chassis_received_by?: string | null
  // v4.6.1 — ETA snapshot taken at drop time so the cell-move gate doesn't
  // silently bypass when the costing lookup fails (e.g. status change, list
  // refresh between drop and move).
  chassis_eta?: string | null
}

const SLOTS = ['V-1', 'V-2', 'V-3', 'V-4', 'V-5', 'P-1', 'P-2', 'P-3']

export function PlanningBoard() {
  const nav = useNavigate()
  const { costings, ackPlanning, markChassisReceived } = useCostings()
  const { profile, hasPermission } = useAppData()
  const weeks = data.planning_board.weeks
  const target = data.kpis.weekly_target_zar

  const [ackTarget, setAckTarget] = useState<Costing | null>(null)

  // Repair quotes are keyed by either quote_number (Q-XXXXX) or job_number_assigned
  // (just digits). Slot assignments use the digit form. Build a Set of digit-keys
  // for fast O(1) lookup as we render each cell.
  const repairJobNumbers = useMemo(() => {
    const s = new Set<string>()
    for (const c of costings) {
      if (c.quote_type !== 'Repair') continue
      if (c.job_number_assigned) s.add(c.job_number_assigned)
      const digits = c.quote_number.replace(/^Q-/, '')
      s.add(digits)
    }
    return s
  }, [costings])

  const [assignments, setAssignments] = useState<LocalSlot[]>(data.planning_board.slot_assignments)
  const [unscheduled, setUnscheduled] = useState<UnscheduledJob[]>(data.planning_board.unscheduled)
  const [dragJob, setDragJob] = useState<UnscheduledJob | null>(null)
  // v4.4 — drag-and-drop for acknowledged Planning costings (chassis-ETA gated).
  const [dragPlanning, setDragPlanning] = useState<Costing | null>(null)
  // v4.6 — drag a scheduled cell to another slot (move). Enforces the same
  // chassis-ETA gate as v4.4 (skipped when the chassis is already received).
  const [dragCell, setDragCell] = useState<LocalSlot | null>(null)
  const [rejectCell, setRejectCell] = useState<string | null>(null)
  const [rejectReason, setRejectReason] = useState<string | null>(null)
  const [openSlot, setOpenSlot] = useState<LocalSlot | null>(null)
  const [jobNum, setJobNum] = useState<string | null>(null)

  // v4.6.1 — Set of job_numbers that already occupy a slot on the grid. Used to
  // hide Planning costings from the Unscheduled lane once they've been dropped
  // — prevents the user dragging the same card over and over to create clones.
  const scheduledJobNums = useMemo(
    () => new Set(assignments.map((a) => a.job_number)),
    [assignments],
  )

  // Planning-status costings that haven't been scheduled yet — pulsing cards in
  // the Unscheduled lane (Work Order v4 §5.4). v4.6.1: filter out costings that
  // already have a cell on the grid (matched by either job_number form).
  const planningCostings = useMemo(
    () =>
      costings.filter((c) => {
        if (c.status !== 'Planning') return false
        const digits = c.quote_number.replace(/^Q-/, '')
        if (scheduledJobNums.has(digits)) return false
        if (c.job_number_assigned && scheduledJobNums.has(c.job_number_assigned)) return false
        return true
      }),
    [costings, scheduledJobNums],
  )

  const cellFor = (week: string, slot: string): LocalSlot | undefined =>
    assignments.find((a) => a.week === week && a.slot === slot)

  // v4.5 — quick lookup of a Costing by its production job_number (which may be
  // `quote_number.replace(/^Q-/, '')` or the explicit `job_number_assigned`).
  // Used to find the chassis-received state for a cell and to route the tick
  // through markChassisReceived when there's a costing match.
  const costingByJobNum = useMemo(() => {
    const m = new Map<string, Costing>()
    for (const c of costings) {
      m.set(c.quote_number.replace(/^Q-/, ''), c)
      if (c.job_number_assigned) m.set(c.job_number_assigned, c)
    }
    return m
  }, [costings])

  // v4.5 — effective "chassis received" lookup for a cell. Returns {at, by, source}
  // checked in this order: local override → matching v4 costing → legacy data.jobs.
  function chassisReceivedFor(cell: LocalSlot): { at: string | null; by: string | null; source: 'local' | 'costing' | 'legacy' | 'none' } {
    if (cell.chassis_received_at) return { at: cell.chassis_received_at, by: cell.chassis_received_by ?? null, source: 'local' }
    const cost = costingByJobNum.get(cell.job_number)
    if (cost?.chassis_received_at) return { at: cost.chassis_received_at, by: cost.chassis_received_by ?? null, source: 'costing' }
    const job = data.jobs.find((j) => j.job_number === cell.job_number)
    if (job?.chassis_received) return { at: job.chassis_received, by: null, source: 'legacy' }
    return { at: null, by: null, source: 'none' }
  }

  // v4.5 — tick handler. Routes v4-costing matches through markChassisReceived
  // (Live POST or Mock state). For non-costing cells, writes to local slot state.
  async function markCellReceived(cell: LocalSlot, receivedIso: string | null) {
    const by = profile.id === 'rep_burt' ? 'BURT' : profile.id
    const cost = costingByJobNum.get(cell.job_number)
    if (cost) {
      await markChassisReceived(cost.quote_number, receivedIso, by)
      setOpenSlot((s) => (s ? { ...s } : s)) // force re-render of panel
      return
    }
    setAssignments((prev) =>
      prev.map((a) =>
        a.week === cell.week && a.slot === cell.slot
          ? { ...a, chassis_received_at: receivedIso, chassis_received_by: receivedIso ? by : null }
          : a,
      ),
    )
    setOpenSlot((s) =>
      s && s.week === cell.week && s.slot === cell.slot
        ? { ...s, chassis_received_at: receivedIso, chassis_received_by: receivedIso ? by : null }
        : s,
    )
  }

  // material-risk job numbers, for the warning overlay
  const materialRiskJobs = useMemo(
    () => new Set(data.material_alerts.flatMap((m) => m.affecting_jobs)),
    [],
  )

  function onDrop(week: string, slot: string, weekEnd?: string) {
    // v4.6 — Move-scheduled-cell drag path. Allow:
    //   • later weeks always (no constraint).
    //   • earlier weeks if chassis received OR (no chassis_eta) OR weekEnd >= chassis_eta.
    // Block:
    //   • dropping onto an already-occupied cell (other than the source).
    //   • dropping into a week ending before the source's chassis ETA when not received.
    if (dragCell) {
      const src = dragCell
      // No-op drop onto the same slot.
      if (src.week === week && src.slot === slot) { setDragCell(null); return }
      // Refuse to overwrite another job. Planner should clear the target first.
      const occupant = assignments.find((a) => a.week === week && a.slot === slot)
      if (occupant) {
        setRejectCell(`${week}:${slot}`)
        setRejectReason('Slot already has a job. Move that one out first.')
        setTimeout(() => { setRejectCell(null); setRejectReason(null) }, 1800)
        setDragCell(null)
        return
      }
      // Chassis-ETA gate (same rule as v4.4, skipped if chassis already received).
      // v4.6.1 — combine the slot's drop-time ETA snapshot with the costing's
      // current ETA; whichever is non-null wins (costing takes precedence if
      // both differ — the planner may have edited the ETA since the drop).
      const received = chassisReceivedFor(src).at
      if (!received && weekEnd) {
        const cost = costingByJobNum.get(src.job_number)
        const eta = (cost?.chassis_eta ?? src.chassis_eta) || null
        if (eta) {
          const slotWeekEnd = new Date(weekEnd + 'T23:59:59')
          const etaDate = new Date(eta + 'T00:00:00')
          if (slotWeekEnd.getTime() < etaDate.getTime()) {
            setRejectCell(`${week}:${slot}`)
            setRejectReason(`Not allowed — chassis ETA is ${dmy(eta)}. Mark chassis received or pick a later week.`)
            setTimeout(() => { setRejectCell(null); setRejectReason(null) }, 1800)
            setDragCell(null)
            return
          }
        }
      }
      // Move: drop source assignment, add a new one at the target preserving
      // job_number / customer_name / local chassis-received override.
      setAssignments((prev) => [
        ...prev.filter((a) => !(a.week === src.week && a.slot === src.slot)),
        {
          week,
          slot,
          job_number: src.job_number,
          customer_name: src.customer_name,
          chassis_received_at: src.chassis_received_at ?? null,
          chassis_received_by: src.chassis_received_by ?? null,
        },
      ])
      setDragCell(null)
      return
    }
    // v4.4 — Planning costing drag path. Gated by chassis ETA: the slot's
    // week.end must be >= chassis_eta, unless chassis_received_at is set.
    if (dragPlanning) {
      const c = dragPlanning
      const eta = c.chassis_eta || null
      const isReceived = !!c.chassis_received_at
      if (eta && !isReceived && weekEnd) {
        const slotWeekEnd = new Date(weekEnd + 'T23:59:59')
        const etaDate     = new Date(eta + 'T00:00:00')
        if (slotWeekEnd.getTime() < etaDate.getTime()) {
          setRejectCell(`${week}:${slot}`)
          setRejectReason(`Not allowed — chassis ETA is ${dmy(eta)}. Change the ETA or pick a later week.`)
          setTimeout(() => { setRejectCell(null); setRejectReason(null) }, 1800)
          setDragPlanning(null)
          return
        }
      }
      const jobNum = c.job_number_assigned || c.quote_number.replace(/^Q-/, '')
      setAssignments((prev) => [
        ...prev.filter((a) => !(a.week === week && a.slot === slot)),
        {
          week,
          slot,
          job_number: jobNum,
          customer_name: c.customer_name,
          // v4.6.1 — snapshot the ETA + received state at drop time so cell-moves
          // can gate on the slot itself if the costing lookup later fails.
          chassis_eta: c.chassis_eta ?? null,
          chassis_received_at: c.chassis_received_at ?? null,
          chassis_received_by: c.chassis_received_by ?? null,
        },
      ])
      setDragPlanning(null)
      return
    }
    // Unscheduled mock-job drag path (unchanged).
    if (!dragJob) return
    const awaitingChassis = /chassis/i.test(dragJob.reason)
    if (awaitingChassis) {
      setRejectCell(`${week}:${slot}`)
      setRejectReason(null)
      setTimeout(() => setRejectCell(null), 900)
      setDragJob(null)
      return
    }
    setAssignments((prev) => [
      ...prev.filter((a) => !(a.week === week && a.slot === slot)),
      { week, slot, job_number: dragJob.job_number, customer_name: dragJob.customer_name },
    ])
    setUnscheduled((prev) => prev.filter((u) => u.job_number !== dragJob.job_number))
    setDragJob(null)
  }

  function addStubJob() {
    const n = String(40000 + unscheduled.length)
    setUnscheduled((prev) => [
      ...prev,
      { job_number: n, customer_name: 'New enquiry', rep: 'BURT', promised_date: '', reason: 'TO BUILD' },
    ])
  }

  return (
    <div className="p-4">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
        <h1 className="text-xl font-bold text-body">Planning Board</h1>
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <Tooltip k="planning_board.week_navigator">
            <div className="flex items-center gap-1.5">
              <span className="font-semibold">Week {data.kpis.current_week}</span>
              <button className="rounded-md border border-line bg-white p-1.5 hover:bg-surface-alt"><ChevronLeft size={16} /></button>
              <button className="rounded-md border border-line bg-white p-1.5 hover:bg-surface-alt"><ChevronRight size={16} /></button>
              <span className="rounded-md border border-line bg-white px-3 py-1.5">View: 5 weeks</span>
            </div>
          </Tooltip>
          <Tooltip k="planning_board.panel_route_filter">
            <button className="rounded-md border border-line bg-white px-3 py-1.5 hover:bg-surface-alt">Route: Vacuum + Panelshop</button>
          </Tooltip>
          <Tooltip k="planning_board.trailer_view_filter">
            <button className="rounded-md border border-line bg-white px-3 py-1.5 hover:bg-surface-alt">Trailers</button>
          </Tooltip>
          <Tooltip k="planning_board.public_holiday_marker">
            <span className="flex items-center gap-1 rounded-md border border-line bg-surface-alt px-2 py-1 text-xs text-muted">
              <CalendarDays size={13} /> Public holidays enforced
            </span>
          </Tooltip>
          <button onClick={addStubJob} className="flex items-center gap-1 rounded-md bg-primary px-3 py-1.5 font-semibold text-white hover:bg-primary-dark">
            <Plus size={15} /> Job
          </button>
        </div>
      </div>

      <div className="grid grid-cols-[250px_1fr] gap-4">
        {/* Unscheduled panel */}
        <Tooltip k="planning_board.unscheduled_panel">
        <Card className="self-start">
          <div className="mb-2 text-sm font-semibold uppercase tracking-wide text-muted">
            Unscheduled ({unscheduled.length + planningCostings.length})
          </div>
          {/* Work Order v4 — Planning-status costings (pulsing when unack'd) */}
          {planningCostings.length > 0 && (
            <div className="mb-3 space-y-2">
              {planningCostings.map((c) => {
                const unack = !c.planning_acknowledged_at
                // v4.4 — acknowledged cards are draggable into the week grid;
                // pulsing un-ack'd cards stay click-only (open ack panel).
                const draggable = !unack
                const tooltipKey = unack
                  ? 'planning_board.unack_pulsing_card'
                  : 'planning_board.planning_card_draggable'
                return (
                  <Tooltip key={c.quote_number} k={tooltipKey}>
                    <div
                      role="button"
                      tabIndex={0}
                      draggable={draggable}
                      onDragStart={draggable ? () => setDragPlanning(c) : undefined}
                      onDragEnd={draggable ? () => setDragPlanning(null) : undefined}
                      onClick={() => setAckTarget(c)}
                      onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setAckTarget(c) } }}
                      className={`flex w-full items-start gap-2 rounded-md border-l-4 border-[#06B6D4] bg-[#06B6D4]/5 p-2 text-left hover:bg-[#06B6D4]/10 ${
                        unack ? 'animate-pulseRing' : ''
                      } ${draggable ? 'cursor-grab active:cursor-grabbing' : 'cursor-pointer'}`}
                    >
                      {draggable ? (
                        <GripVertical size={14} className="mt-0.5 text-[#06B6D4]" />
                      ) : (
                        <CalendarDays size={14} className="mt-0.5 text-[#06B6D4]" />
                      )}
                      <div className="flex-1">
                        <div className="flex flex-wrap items-center justify-between gap-1">
                          <span className="font-mono text-sm font-semibold">#{c.job_number_assigned ?? c.quote_number}</span>
                          {unack && (
                            <span className="rounded bg-[#06B6D4] px-1.5 py-0.5 text-[9px] font-bold uppercase text-white">
                              New
                            </span>
                          )}
                          {draggable && c.chassis_received_at && (
                            <span className="rounded bg-status-green/15 px-1.5 py-0.5 text-[9px] font-bold uppercase text-status-green">
                              Chassis in
                            </span>
                          )}
                          {draggable && !c.chassis_received_at && c.chassis_eta && (
                            <span
                              title={`Chassis ETA ${dmy(c.chassis_eta)} — drops before this week are blocked`}
                              className="rounded bg-status-amber/15 px-1.5 py-0.5 text-[9px] font-bold uppercase text-status-amber"
                            >
                              ETA {dmy(c.chassis_eta)}
                            </span>
                          )}
                        </div>
                        <div className="text-xs text-body">{c.customer_name}</div>
                        <div className="text-[11px] text-muted">{c.body_type}</div>
                        <div className="mt-1 text-[10px] font-medium text-[#0E7490]">
                          {unack
                            ? 'Awaiting Planning ack'
                            : draggable
                              ? `Ack’d by ${c.planning_acknowledged_by} · drag to schedule`
                              : `Ack’d by ${c.planning_acknowledged_by}`}
                        </div>
                      </div>
                    </div>
                  </Tooltip>
                )
              })}
            </div>
          )}
          <div className="space-y-2">
            {unscheduled.map((u) => (
              <div
                key={u.job_number}
                draggable
                onDragStart={() => setDragJob(u)}
                onDragEnd={() => setDragJob(null)}
                className="flex cursor-grab items-start gap-2 rounded-md border border-line bg-white p-2 active:cursor-grabbing"
              >
                <GripVertical size={14} className="mt-0.5 text-muted" />
                <div className="flex-1">
                  <div className="font-mono text-sm font-semibold">#{u.job_number}</div>
                  <div className="text-xs text-body">{u.customer_name}</div>
                  <div className="text-[11px] text-muted">{u.rep} · {dmy(u.promised_date)}</div>
                  <div className="mt-1 text-[11px] font-medium text-status-amber">{u.reason}</div>
                </div>
              </div>
            ))}
            {unscheduled.length === 0 && planningCostings.length === 0 && (
              <div className="text-sm text-muted">All scheduled.</div>
            )}
          </div>
          <Tooltip k="planning_board.drag_a_job_action">
            <div className="mt-3 border-t border-line pt-3 text-xs text-muted">Drag a card onto a slot →</div>
          </Tooltip>
        </Card>
        </Tooltip>

        {/* Week grid */}
        <Tooltip k="planning_board.main_grid">
        <Card className="overflow-x-auto p-0">
          <table className="w-full border-collapse text-sm">
            <thead>
              <tr className="bg-primary text-white">
                <th className="px-2 py-2 text-left font-semibold">Slot</th>
                {weeks.map((w) => (
                  <th key={w.week} className="px-2 py-2 text-left font-semibold">
                    {w.week}
                    <div className="text-[10px] font-normal opacity-80">{dmy(w.start)}</div>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {SLOTS.map((slot) => (
                <tr key={slot} className="border-b border-line">
                  <td className="bg-surface-alt px-2 py-1.5 font-mono text-xs font-semibold">{slot}</td>
                  {weeks.map((w) => {
                    const cell = cellFor(w.week, slot)
                    const key = `${w.week}:${slot}`
                    const rejected = rejectCell === key
                    const job = cell ? data.jobs.find((j) => j.job_number === cell.job_number) : undefined
                    // v4.5 — Truck icon fires for any cell whose effective chassis-received
                    // state is null (covers legacy jobs, freshly-dropped unscheduled cards,
                    // and dropped v4 costings whose chassis hasn't arrived).
                    const chassisMissing = cell ? !chassisReceivedFor(cell).at : false
                    const matRisk = cell ? materialRiskJobs.has(cell.job_number) : false
                    return (
                      <td
                        key={key}
                        onDragOver={(e) => e.preventDefault()}
                        onDrop={() => onDrop(w.week, slot, w.end)}
                        className={`h-12 px-1 py-1 align-top transition ${
                          rejected ? 'bg-status-red/30 ring-2 ring-status-red' : cell ? '' : 'bg-surface-alt/40'
                        }`}
                      >
                        {cell ? (
                          <button
                            onClick={() => setOpenSlot(cell)}
                            draggable={hasPermission('planning.acknowledge')}
                            onDragStart={(e) => {
                              if (!hasPermission('planning.acknowledge')) { e.preventDefault(); return }
                              setDragCell(cell)
                            }}
                            onDragEnd={() => setDragCell(null)}
                            title={job?.description ?? cell.customer_name}
                            className={`flex w-full items-center gap-1 rounded border-l-4 px-1.5 py-1 text-left hover:border-primary ${
                              hasPermission('planning.acknowledge') ? 'cursor-grab active:cursor-grabbing' : ''
                            } ${
                              repairJobNumbers.has(cell.job_number)
                                ? 'border-[#7E22CE] bg-[#7E22CE]/5'
                                : 'border-status-green bg-white'
                            }`}
                          >
                            <span className="flex-1">
                              <span className="font-mono text-xs font-semibold">{cell.job_number}</span>
                              <span className="block truncate text-[11px] text-muted">{cell.customer_name}</span>
                            </span>
                            {repairJobNumbers.has(cell.job_number) && (
                              <span title="Repair work order" className="inline-flex">
                                <Wrench size={11} className="text-[#7E22CE]" />
                              </span>
                            )}
                            {chassisMissing && (
                              <Tooltip k="planning_board.chassis_warning_overlay">
                                <span title="Chassis not received"><Truck size={13} className="text-status-amber" /></span>
                              </Tooltip>
                            )}
                            {matRisk && (
                              <Tooltip k="planning_board.material_warning_overlay">
                                <span title="Material lead-time risk"><PackageX size={13} className="text-status-red" /></span>
                              </Tooltip>
                            )}
                          </button>
                        ) : rejected ? (
                          <div className="px-1 text-center text-[10px] font-semibold leading-tight text-status-red">
                            {rejectReason ?? 'Chassis not yet received'}
                          </div>
                        ) : null}
                      </td>
                    )
                  })}
                </tr>
              ))}
              {/* Capacity footer (wrapped row-by-row by Tooltip via a tbody-level tooltip is awkward — wrap the four rows in a single group attribute instead) */}
              <FooterRow label="Filled" cells={weeks.map((w) => `${w.slots_filled}`)} tooltipKey="planning_board.weekly_capacity_footer" />
              <FooterRow label="Empty" cells={weeks.map((w) => `${w.slots_empty}`)} />
              <FooterRow label="Value" cells={weeks.map((w) => zarShort(w.value_zar))} strong />
              <FooterRow
                label="Gap vs target"
                cells={weeks.map((w) => zarShort(w.value_zar - target))}
                tone={weeks.map((w) => (w.value_zar >= target ? 'green' : 'red'))}
              />
            </tbody>
          </table>
        </Card>
        </Tooltip>
      </div>

      {/* Slot detail */}
      <SidePanel title={openSlot ? `Job #${openSlot.job_number}` : ''} open={!!openSlot} onClose={() => setOpenSlot(null)}>
        {openSlot && (
          <SlotDetail
            key={`${openSlot.week}:${openSlot.slot}:${openSlot.chassis_received_at ?? ''}`}
            slot={openSlot}
            received={chassisReceivedFor(openSlot)}
            canTick={hasPermission('planning.acknowledge')}
            onMarkReceived={(iso) => markCellReceived(openSlot, iso)}
            onUnmark={() => markCellReceived(openSlot, null)}
            onViewProduction={() => { setOpenSlot(null); nav('/production') }}
            onOpenJob={() => { setJobNum(openSlot.job_number); setOpenSlot(null) }}
          />
        )}
      </SidePanel>

      <JobDetailStub jobNumber={jobNum} onClose={() => setJobNum(null)} />

      <PlanningAckPanel
        costing={ackTarget}
        onClose={() => setAckTarget(null)}
        onAcknowledge={async (c) => {
          const by = profile.id === 'rep_burt' ? 'BURT' : profile.id
          await ackPlanning(c.quote_number, by)
          setAckTarget(null)
        }}
      />
    </div>
  )
}

function FooterRow({
  label,
  cells,
  strong,
  tone,
  tooltipKey,
}: {
  label: string
  cells: string[]
  strong?: boolean
  tone?: ('green' | 'red')[]
  tooltipKey?: string
}) {
  const row = (
    <tr className="border-t border-line bg-surface-alt">
      <td className="px-2 py-1.5 text-xs font-semibold text-muted">{label}</td>
      {cells.map((c, i) => (
        <td
          key={i}
          className={`px-2 py-1.5 text-xs tabular-nums ${strong ? 'font-bold text-body' : 'text-body'} ${
            tone ? (tone[i] === 'green' ? 'text-status-green' : 'text-status-red') : ''
          }`}
        >
          {c}
        </td>
      ))}
    </tr>
  )
  return tooltipKey ? <Tooltip k={tooltipKey}>{row}</Tooltip> : row
}

function todayIso(): string {
  const d = new Date()
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

function SlotDetail({
  slot,
  received,
  canTick,
  onMarkReceived,
  onUnmark,
  onViewProduction,
  onOpenJob,
}: {
  slot: LocalSlot
  received: { at: string | null; by: string | null; source: 'local' | 'costing' | 'legacy' | 'none' }
  canTick: boolean
  onMarkReceived: (iso: string) => void | Promise<void>
  onUnmark: () => void | Promise<void>
  onViewProduction: () => void
  onOpenJob: () => void
}) {
  const job = data.jobs.find((j) => j.job_number === slot.job_number)
  const [ticked, setTicked] = useState(false)
  const [date, setDate] = useState<string>(todayIso())
  const isReceived = !!received.at
  return (
    <div className="space-y-3 text-sm">
      <div className="text-lg font-semibold text-body">{slot.customer_name}</div>
      {job ? (
        <>
          <div className="text-muted">{job.description}</div>
          <div className="flex items-center gap-2">
            <StatusPill status={job.is_late ? 'RED' : 'GREEN'} label={job.status.replace(/_/g, ' ')} />
          </div>
          <div className="grid grid-cols-2 gap-2 rounded-md bg-surface-alt p-3">
            <div><div className="text-xs text-muted">Promised</div>{dmy(job.promised_date)}</div>
            <div><div className="text-xs text-muted">Selling</div>{zar(job.selling_zar)}</div>
          </div>
        </>
      ) : (
        <div className="rounded-md border border-dashed border-line bg-surface-alt p-3 text-muted">
          Scheduled in {slot.week}, slot {slot.slot}. Detail not in mock set.
        </div>
      )}

      {/* v4.5 — Chassis-received tick. */}
      <Tooltip k="planning_board.cell_chassis_received_tick">
        <div className="rounded-md border border-line p-3">
          {isReceived ? (
            <div className="space-y-2">
              <div className="flex items-center gap-2 text-status-green">
                <CheckCircle2 size={18} />
                <span className="font-semibold">Chassis received {dmy(received.at!)}</span>
              </div>
              {received.by && <div className="text-xs text-muted">by {received.by}</div>}
              {received.source === 'local' && canTick && (
                <button
                  onClick={() => { onUnmark(); setTicked(false) }}
                  className="w-full rounded-md border border-line py-1.5 text-xs font-semibold text-muted hover:bg-surface-alt"
                >
                  Un-tick (mistake correction)
                </button>
              )}
              {received.source !== 'local' && (
                <div className="text-xs text-muted">Recorded via {received.source === 'costing' ? 'the costing job-card tick' : 'the legacy job record'}.</div>
              )}
            </div>
          ) : (
            <div className="space-y-2">
              <div className="flex items-center gap-2 text-status-amber">
                <AlertTriangle size={18} />
                <span className="font-semibold">Chassis not yet received</span>
              </div>
              {canTick ? (
                <>
                  <label className="flex items-start gap-2">
                    <input
                      type="checkbox"
                      checked={ticked}
                      onChange={(e) => setTicked(e.target.checked)}
                      className="mt-0.5"
                    />
                    <span className="text-sm">Tick to mark chassis received</span>
                  </label>
                  <div className="flex items-center gap-2">
                    <label className="text-xs text-muted">Received date:</label>
                    <input
                      type="date"
                      value={date}
                      max={todayIso()}
                      onChange={(e) => setDate(e.target.value)}
                      className="rounded-md border border-line px-2 py-1 text-sm"
                    />
                  </div>
                  <button
                    disabled={!ticked || !date}
                    onClick={() => onMarkReceived(date)}
                    className="w-full rounded-md bg-primary py-2 font-semibold text-white hover:bg-primary-dark disabled:cursor-not-allowed disabled:bg-line disabled:text-muted"
                  >
                    Confirm receipt
                  </button>
                </>
              ) : (
                <div className="text-xs text-muted">Only the Planning role can mark a chassis received.</div>
              )}
            </div>
          )}
        </div>
      </Tooltip>

      <button onClick={onOpenJob} className="w-full rounded-md border border-line py-2 font-semibold text-primary hover:bg-surface-alt">Open full job</button>
      <button onClick={onViewProduction} className="w-full rounded-md bg-primary py-2 font-semibold text-white hover:bg-primary-dark">View job in production</button>
    </div>
  )
}
