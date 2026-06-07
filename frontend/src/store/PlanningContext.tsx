// PlanningContext.tsx — live/mock board state + scheduling mutators for the
// Planning Board (WO v4.18, Phase 2C-2). Mirrors MaterialsContext: in LIVE mode
// it reads GET /api/planning-board and POSTs schedule / move / unschedule
// (pessimistic → await → refetch); offline it reports MOCK mode so the screen
// renders the bundled offline demo (the legacy CostingsContext-driven pool — §0.5).
//
// Scope (§0.1): this context owns only the board grid + scheduling. The
// planning-ack panel and the SlotDetail chassis-received tick stay on the legacy
// CostingsContext until 2C-3 (v4.19) — they are NOT moved here.

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react'
import { apiDelete, apiGet, apiPost, handleApiError, mesAutoLogin } from '../lib/api'
import { useToast } from '../components/ui/toast'
import { useAppData } from './AppDataContext'
import type {
  ApiPlanningBoard,
  ApiPlanningJobRef,
  ApiPlanningSlotItem,
  MoveInput,
  PlanningBoardView,
  PlanningJob,
  PlanningSlot,
  ScheduleInput,
} from '../lib/types'

export type ApiMode = 'live' | 'mock' | 'loading'

const EMPTY_BOARD: PlanningBoardView = { weeks: [], bays: [], slots: [], pool: [], capacity: [] }

// ── mappers (API → domain) ────────────────────────────────────────────────────
function addDays(iso: string, days: number): string {
  const d = new Date(`${iso}T00:00:00Z`)
  d.setUTCDate(d.getUTCDate() + days)
  return d.toISOString().slice(0, 10)
}

const apiToJob = (j: ApiPlanningJobRef): PlanningJob => ({
  id: j.id,
  job_number: j.job_number ?? String(j.id),
  customer: j.customer ?? '—',
  body_type: j.body_type,
  selling_zar: j.selling_zar,
  status: j.status,
  source: j.source ?? 'quote',
  chassis_eta: j.chassis_eta,
  chassis_received_at: j.chassis_received_at,
  chassis_received_signal: j.chassis_received_signal ?? null,   // WO v4.29 D3
  chassis_received_source: j.chassis_received_source ?? null,
})

const apiToSlot = (s: ApiPlanningSlotItem): PlanningSlot => ({
  id: s.id,
  week_key: s.week_iso ?? s.week ?? '',
  week_start: s.week ?? '',
  bay: s.bay ?? '',
  lane: s.lane,
  slot_position: s.slot_position,
  job: s.production_job ? apiToJob(s.production_job) : null,
})

const apiToBoard = (b: ApiPlanningBoard): PlanningBoardView => ({
  weeks: b.weeks.map((w) => ({ key: w.iso, start: w.start, end: addDays(w.start, 4) })),
  bays: b.lanes,
  slots: b.slots.map(apiToSlot),
  pool: b.unscheduled_pool.map(apiToJob),
  capacity: b.capacity.map((c) => ({
    week_key: c.week_iso,
    filled: c.filled,
    empty: c.empty,
    value_zar: c.value_zar,
  })),
})

// ── Context ─────────────────────────────────────────────────────────────────
interface PlanningValue {
  mode: ApiMode
  lastUpdated: Date | null
  board: PlanningBoardView
  refresh: () => Promise<void>
  // Mutators — pessimistic in live mode (await API → refetch). Inert in mock
  // (the offline demo schedules via the screen's legacy local-state path, §0.5).
  schedule: (input: ScheduleInput) => Promise<void>
  move: (slotId: number, input: MoveInput) => Promise<void>
  unschedule: (slotId: number) => Promise<void>
}

const PlanningContext = createContext<PlanningValue | null>(null)

export function PlanningProvider({ children }: { children: ReactNode }) {
  const toast = useToast()
  const { activeBranch } = useAppData()
  const [mode, setMode] = useState<ApiMode>('loading')
  const [board, setBoard] = useState<PlanningBoardView>(EMPTY_BOARD)
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null)

  // refetch() = board read only (no autologin). The server scopes the board to
  // the session's active branch, so a branch switch needs only a refetch (§3.5).
  const refetch = useCallback(async () => {
    try {
      const b = await apiGet<ApiPlanningBoard>('/api/planning-board?weeks=8')
      setBoard(apiToBoard(b))
      setMode('live')
    } catch {
      // Offline / unauthorised → mock mode: the screen renders the bundled demo.
      setBoard(EMPTY_BOARD)
      setMode('mock')
    }
    setLastUpdated(new Date())
  }, [])

  // Bootstrap once on mount: deduped autologin → board read.
  useEffect(() => {
    void (async () => {
      await mesAutoLogin()
      await refetch()
    })()
  }, [refetch])

  // Branch-changed signal (§4.4): re-scope on an actual active-branch switch.
  // Skip the initial null→branch resolution — bootstrap already loaded.
  const prevBranchId = useRef<number | null | undefined>(undefined)
  useEffect(() => {
    const id = activeBranch?.id ?? null
    const prev = prevBranchId.current
    prevBranchId.current = id
    // Refetch only on a real branch switch — skip mount + the initial
    // null→default-branch resolution (bootstrap already loaded that branch).
    if (prev === undefined || prev === null || id === null) return
    if (prev !== id) void refetch()
  }, [activeBranch?.id, refetch])

  const schedule = useCallback(
    async (input: ScheduleInput) => {
      if (mode !== 'live') return
      try {
        await apiPost<ApiPlanningSlotItem>('/api/planning-slots', {
          production_job_id: input.production_job_id,
          week: input.week,
          bay: input.bay,
          lane: input.lane ?? null,
          slot_position: input.slot_position ?? null,
        })
        await refetch()
      } catch (e) {
        handleApiError(e, toast.push) // 409 re-throws → screen renders inline cell-reject
        throw e
      }
    },
    [mode, refetch, toast],
  )

  const move = useCallback(
    async (slotId: number, input: MoveInput) => {
      if (mode !== 'live') return
      try {
        await apiPost<ApiPlanningSlotItem>(`/api/planning-slots/${slotId}/move`, {
          week: input.week,
          bay: input.bay,
          lane: input.lane ?? null,
          slot_position: input.slot_position ?? null,
        })
        await refetch()
      } catch (e) {
        handleApiError(e, toast.push)
        throw e
      }
    },
    [mode, refetch, toast],
  )

  const unschedule = useCallback(
    async (slotId: number) => {
      if (mode !== 'live') return
      try {
        await apiDelete(`/api/planning-slots/${slotId}`)
        await refetch()
      } catch (e) {
        handleApiError(e, toast.push)
        throw e
      }
    },
    [mode, refetch, toast],
  )

  const value = useMemo<PlanningValue>(
    () => ({ mode, lastUpdated, board, refresh: refetch, schedule, move, unschedule }),
    [mode, lastUpdated, board, refetch, schedule, move, unschedule],
  )

  return <PlanningContext.Provider value={value}>{children}</PlanningContext.Provider>
}

export function usePlanning(): PlanningValue {
  const ctx = useContext(PlanningContext)
  if (!ctx) throw new Error('usePlanning must be used within PlanningProvider')
  return ctx
}
