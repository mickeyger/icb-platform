import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { data, unitsInProduction } from '../data/mockData'
import type { MockData, ReworkTicket } from '../data/types'
import { costingsMock, ROLE_PERMISSIONS, type DemoUserProfile, type PermissionKey } from '../data/costingsData'
import { apiGet, apiPost, handleApiError, mesAutoLogin, setCsrfToken } from '../lib/api'
import { useToast } from '../components/ui/toast'

// ── Live session (WO v4.17) ───────────────────────────────────────────────────
export type ApiMode = 'live' | 'mock' | 'loading'

export interface BranchRef {
  id: number
  code: string
  name: string
}

interface SessionInfo {
  user: { id: number; username: string; role?: string | null }
  active_branch: BranchRef | null
  accessible_branches: BranchRef[]
  permissions: string[]
  csrf_token?: string | null
}

// The 15 server-tracked mutation permission keys (ADR 0010). Read/nav keys are NOT
// server-gated (read-side gating deferred), so in live mode hasPermission is
// permissive for anything outside this set. The mockup's materials.* keys alias to
// the renamed server keys.
const SERVER_KEYS = new Set<string>([
  'production.accept', 'production.pre_job_card', 'production.signoff_sales',
  'production.signoff_production', 'production.chassis_received',
  'planning.acknowledge', 'planning.schedule', 'planning.unschedule',
  'stores.count', 'stores.raise_discrepancy',
  'buying.resolve_discrepancy', 'buying.raise_pr', 'buying.defer_pr',
  'buying.override_supplier', 'buying.bulk_raise',
  'chassis.assembly_assign',       // WO v4.31 — true per-role gating for the parking->assembly assign
])
const KEY_ALIAS: Record<string, string> = {
  'materials.count': 'stores.count',
  'materials.raise_pr': 'buying.raise_pr',
  'materials.override_supplier': 'buying.override_supplier',
  'materials.bulk_raise': 'buying.bulk_raise',
}

interface AcceptedJob {
  job_number: string
  customer_name: string
  description: string
  selling_zar: number
  accepted_at: string
}

interface AppDataValue {
  data: MockData
  acceptedJobs: AcceptedJob[]
  addAcceptedJob: (job: AcceptedJob) => void
  unitsInProduction: number
  reworkTickets: ReworkTicket[]
  addReworkTicket: (ticket: ReworkTicket) => void
  tooltipsEnabled: boolean
  setTooltipsEnabled: (v: boolean) => void
  // Permission model + demo user-switcher (Addendum v1.2.1).
  profile: DemoUserProfile
  setProfile: (p: DemoUserProfile) => void
  hasPermission: (k: PermissionKey) => boolean
  permissions: PermissionKey[]
  // Live session (WO v4.17).
  apiMode: ApiMode
  isAdmin: boolean              // WO v4.25 — live session user.role === 'admin' (admin inspection gate)
  sessionRole: string | null    // WO v4.31 §3.2 — live session user.role (render-time choices, e.g. workshop price hide)
  activeBranch: BranchRef | null
  // Branch picker (WO v4.18).
  accessibleBranches: BranchRef[]
  switchBranch: (branchId: number) => Promise<void>
}

const AppDataContext = createContext<AppDataValue | null>(null)

export function AppDataProvider({ children }: { children: ReactNode }) {
  const [acceptedJobs, setAcceptedJobs] = useState<AcceptedJob[]>([])
  const [reworkTickets, setReworkTickets] = useState<ReworkTicket[]>(data.rework_tickets)
  const [tooltipsEnabled, setTooltipsEnabled] = useState(true)
  const [profile, setProfile] = useState<DemoUserProfile>(
    () =>
      costingsMock.demo_user_profiles.find((p) => p.id === costingsMock.logged_in_user.id) ??
      costingsMock.demo_user_profiles[0],
  )

  // Live session bootstrap: mint a session, then read GET /api/session. On failure,
  // fall back to mock mode + the demo profile-switcher.
  const toast = useToast()
  const [apiMode, setApiMode] = useState<ApiMode>('loading')
  const [sessionPerms, setSessionPerms] = useState<Set<string>>(new Set())
  const [activeBranch, setActiveBranch] = useState<BranchRef | null>(null)
  const [accessibleBranches, setAccessibleBranches] = useState<BranchRef[]>([])
  const [sessionRole, setSessionRole] = useState<string | null>(null)  // WO v4.25 (admin gate)

  useEffect(() => {
    let alive = true
    void (async () => {
      await mesAutoLogin()
      try {
        const s = await apiGet<SessionInfo>('/api/session')
        if (!alive) return
        setSessionPerms(new Set(s.permissions))
        setSessionRole(s.user?.role ?? null)
        setActiveBranch(s.active_branch)
        setAccessibleBranches(s.accessible_branches)
        setCsrfToken(s.csrf_token ?? null)
        setApiMode('live')
      } catch {
        if (alive) setApiMode('mock')
      }
    })()
    return () => {
      alive = false
    }
  }, [])

  // Branch switch (WO v4.18 §4.4): POST the new branch, then update session
  // state. The activeBranch change is the "branch-changed" signal that the
  // branch-scoped contexts (Planning, Materials) watch via useEffect to refetch.
  const switchBranch = useCallback(
    async (branchId: number) => {
      if (branchId === activeBranch?.id) return
      try {
        const s = await apiPost<SessionInfo>('/api/session/branch', { branch_id: branchId })
        setSessionPerms(new Set(s.permissions))
        setSessionRole(s.user?.role ?? null)
        setActiveBranch(s.active_branch)
        setAccessibleBranches(s.accessible_branches)
        setCsrfToken(s.csrf_token ?? null)
      } catch (e) {
        handleApiError(e, toast.push)
      }
    },
    [activeBranch?.id, toast],
  )

  const mockPermissions = useMemo<PermissionKey[]>(() => ROLE_PERMISSIONS[profile.id] ?? [], [profile])

  const value = useMemo<AppDataValue>(() => {
    const hasPermission = (k: PermissionKey): boolean => {
      if (apiMode === 'live') {
        const serverKey = KEY_ALIAS[k] ?? k
        return SERVER_KEYS.has(serverKey) ? sessionPerms.has(serverKey) : true
      }
      return mockPermissions.includes(k)
    }
    return {
      data,
      acceptedJobs,
      addAcceptedJob: (job) =>
        setAcceptedJobs((prev) =>
          prev.some((j) => j.job_number === job.job_number) ? prev : [...prev, job],
        ),
      unitsInProduction: unitsInProduction() + acceptedJobs.length,
      reworkTickets,
      addReworkTicket: (ticket) =>
        setReworkTickets((prev) =>
          prev.some((t) => t.ticket === ticket.ticket) ? prev : [ticket, ...prev],
        ),
      tooltipsEnabled,
      setTooltipsEnabled,
      profile,
      setProfile,
      hasPermission,
      permissions: mockPermissions,
      apiMode,
      isAdmin: apiMode === 'live' && sessionRole === 'admin',
      sessionRole: apiMode === 'live' ? sessionRole : null,
      activeBranch,
      accessibleBranches,
      switchBranch,
    }
  }, [acceptedJobs, reworkTickets, tooltipsEnabled, profile, mockPermissions, apiMode, sessionPerms, sessionRole, activeBranch, accessibleBranches, switchBranch])

  return <AppDataContext.Provider value={value}>{children}</AppDataContext.Provider>
}

export function useAppData(): AppDataValue {
  const ctx = useContext(AppDataContext)
  if (!ctx) throw new Error('useAppData must be used within AppDataProvider')
  return ctx
}
