import { createContext, useContext, useMemo, useState, type ReactNode } from 'react'
import { data, unitsInProduction } from '../data/mockData'
import type { MockData, ReworkTicket } from '../data/types'
import { costingsMock, ROLE_PERMISSIONS, type DemoUserProfile, type PermissionKey } from '../data/costingsData'

interface AcceptedJob {
  job_number: string
  customer_name: string
  description: string
  selling_zar: number
  accepted_at: string
}

interface AppDataValue {
  data: MockData
  // Configurator → Production
  acceptedJobs: AcceptedJob[]
  addAcceptedJob: (job: AcceptedJob) => void
  unitsInProduction: number
  // QC → rework
  reworkTickets: ReworkTicket[]
  addReworkTicket: (ticket: ReworkTicket) => void
  // Demo settings
  tooltipsEnabled: boolean
  setTooltipsEnabled: (v: boolean) => void
  // Permission model + demo user-switcher (Addendum v1.2.1)
  profile: DemoUserProfile
  setProfile: (p: DemoUserProfile) => void
  hasPermission: (k: PermissionKey) => boolean
  permissions: PermissionKey[]
}

const AppDataContext = createContext<AppDataValue | null>(null)

export function AppDataProvider({ children }: { children: ReactNode }) {
  const [acceptedJobs, setAcceptedJobs] = useState<AcceptedJob[]>([])
  const [reworkTickets, setReworkTickets] = useState<ReworkTicket[]>(
    data.rework_tickets,
  )
  const [tooltipsEnabled, setTooltipsEnabled] = useState(true)
  // Default profile = the JSON's logged_in_user (Burt). The user-switcher in
  // TopNav swaps this at runtime to demonstrate the permission model.
  const [profile, setProfile] = useState<DemoUserProfile>(
    () =>
      costingsMock.demo_user_profiles.find((p) => p.id === costingsMock.logged_in_user.id) ??
      costingsMock.demo_user_profiles[0],
  )
  const permissions = useMemo<PermissionKey[]>(
    () => ROLE_PERMISSIONS[profile.id] ?? [],
    [profile],
  )

  const value = useMemo<AppDataValue>(
    () => ({
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
      hasPermission: (k) => permissions.includes(k),
      permissions,
    }),
    [acceptedJobs, reworkTickets, tooltipsEnabled, profile, permissions],
  )

  return <AppDataContext.Provider value={value}>{children}</AppDataContext.Provider>
}

export function useAppData(): AppDataValue {
  const ctx = useContext(AppDataContext)
  if (!ctx) throw new Error('useAppData must be used within AppDataProvider')
  return ctx
}
