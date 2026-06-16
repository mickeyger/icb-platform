// TeamWorksheetTabs.tsx — WO v4.32 §3.3: the per-team daily worksheet, rendered as tabs inside
// the Production Dashboard (§0.1 — two surfaces, ONE screen). Data = the §0.4 uniform contract
// (/api/production/team-worksheet — same shape for all 5 teams, team-specific fields nullable),
// so every tab renders through the same row component.
//
// Per-role RENDER choice (§0.8 — sessionRole check, NOT a permission gate; the v4.31 §3.2
// workshop-price-hide pattern): workshop sees only its chassis-custody surfaces (Parking +
// Dispatch, Parking pre-selected); every other role sees all five tabs in floor-flow order
// (Vacuum → Press → Assembly → Parking → Dispatch). v4.32.1 refines the mapping if Burt/Simeon
// want a different lens. Read-only — no actions on any tab (§3.3).
import { useEffect, useMemo, useState } from 'react'
import { CalendarDays, Link2 } from 'lucide-react'
import { Card, SectionTitle } from '../../components/ui/primitives'
import { useAppData } from '../../store/AppDataContext'
import { apiGet } from '../../lib/api'
import { dmy } from '../../lib/format'

interface WorksheetItem {
  job_id: number | null
  job_number: string | null
  chassis_vin: string | null
  customer: string | null
  description: string | null
  location: string | null
  status: string
  since: string | null
  flag: string | null
  body_attached: boolean       // WO v4.35 §0.25 — drives the 🔗 on Vacuum/Press slots
}

interface TeamWorksheet {
  team: string
  date: string
  capacity: { used: number; total: number } | null
  sections: {
    scheduled: WorksheetItem[]; in_flight: WorksheetItem[]; blocking: WorksheetItem[]
    body_attached_today: WorksheetItem[]    // WO v4.35 §0.7 — populated only for the Assembly team
  }
}

const ALL_TEAMS = [
  { key: 'vacuum', label: 'Vacuum' },
  { key: 'press', label: 'Press' },
  { key: 'assembly', label: 'Assembly' },
  { key: 'parking', label: 'Parking' },
  { key: 'dispatch', label: 'Dispatch' },
] as const

const WORKSHOP_TEAM_KEYS = new Set(['parking', 'dispatch'])   // chassis-custody surfaces
const MAX_OFFSET_DAYS = 7                                      // §3.3 lock: ±7 days

function isoToday(): string {
  return new Date().toISOString().slice(0, 10)
}

function isoShift(days: number): string {
  const d = new Date()
  d.setDate(d.getDate() + days)
  return d.toISOString().slice(0, 10)
}

const SECTION_META = [
  { key: 'scheduled', title: 'Scheduled', dot: 'bg-muted' },
  { key: 'in_flight', title: 'In flight', dot: 'bg-status-green' },
  { key: 'blocking', title: 'Blocking', dot: 'bg-status-red' },
] as const

export function TeamWorksheetTabs() {
  const { sessionRole } = useAppData()
  const teams = useMemo(
    () => (sessionRole === 'workshop' ? ALL_TEAMS.filter((t) => WORKSHOP_TEAM_KEYS.has(t.key)) : ALL_TEAMS),
    [sessionRole],
  )
  const [team, setTeam] = useState<string>(teams[0].key)
  const [date, setDate] = useState<string>(isoToday())
  const [data, setData] = useState<TeamWorksheet | null>(null)
  const [loading, setLoading] = useState(false)

  // If the role narrows the tab set (workshop), snap the selection into the allowed list.
  useEffect(() => {
    if (!teams.some((t) => t.key === team)) setTeam(teams[0].key)
  }, [teams, team])

  useEffect(() => {
    let stale = false
    const load = async () => {
      setLoading(true)
      try {
        const ws = await apiGet<TeamWorksheet>(
          `/api/production/team-worksheet?team=${team}&date=${date}`,
        )
        if (!stale) setData(ws)
      } catch {
        if (!stale) setData(null)
      } finally {
        if (!stale) setLoading(false)
      }
    }
    void load()
    const t = setInterval(() => void load(), 30_000)           // §0.3 — same 30s cadence
    return () => {
      stale = true
      clearInterval(t)
    }
  }, [team, date])

  return (
    <Card className="mb-4" data-testid="team-worksheet">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <SectionTitle>Team daily worksheet</SectionTitle>
        <div className="flex items-center gap-2 text-xs text-muted">
          <CalendarDays size={14} />
          <input
            type="date"
            data-testid="worksheet-date"
            value={date}
            min={isoShift(-MAX_OFFSET_DAYS)}
            max={isoShift(MAX_OFFSET_DAYS)}
            onChange={(e) => e.target.value && setDate(e.target.value)}
            className="rounded-md border border-line px-2 py-1 text-sm text-body"
          />
        </div>
      </div>

      {/* Tab strip */}
      <div className="mb-3 flex flex-wrap gap-1 border-b border-line">
        {teams.map((t) => (
          <button
            key={t.key}
            data-testid={`team-tab-${t.key}`}
            onClick={() => setTeam(t.key)}
            className={`-mb-px rounded-t-md border-x border-t px-3 py-1.5 text-sm font-semibold transition ${
              team === t.key
                ? 'border-line bg-white text-primary'
                : 'border-transparent text-muted hover:text-body'
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* Header line: team + date (+ the parking capacity chip, §0.1) */}
      <div className="mb-3 flex items-center gap-3 text-sm">
        <span className="font-semibold text-body">
          {teams.find((t) => t.key === team)?.label} · {data ? dmy(data.date) : dmy(date)}
        </span>
        {data?.capacity && (
          <span
            data-testid="worksheet-capacity"
            className="rounded-full bg-surface-alt px-2 py-0.5 text-[11px] font-semibold text-muted"
          >
            Yard {data.capacity.used}/{data.capacity.total}
          </span>
        )}
        {loading && <span className="text-[11px] text-muted">refreshing…</span>}
      </div>

      {/* Sections (§3.3) — the Assembly tab adds the WO v4.35 §0.7 "Body Attached (today)" 4th section. */}
      {(() => {
        const sections = team === 'assembly'
          ? [...SECTION_META, { key: 'body_attached_today', title: 'Body Attached (today)', dot: 'bg-status-green' }]
          : SECTION_META
        return (
          <div className={`grid gap-3 ${team === 'assembly' ? 'lg:grid-cols-4' : 'lg:grid-cols-3'}`}>
            {sections.map((s) => {
              const items = data?.sections[s.key as keyof TeamWorksheet['sections']] ?? []
              return (
                <div key={s.key} data-testid={`worksheet-${s.key}`} className="rounded-md border border-line p-2.5">
                  <div className="mb-2 flex items-center gap-2">
                    <span className={`h-2 w-2 rounded-full ${s.dot}`} />
                    <span className="text-xs font-semibold uppercase tracking-wide text-muted">{s.title}</span>
                    <span className="ml-auto text-[11px] text-muted">{items.length}</span>
                  </div>
                  {items.length === 0 ? (
                    <div className="py-2 text-sm text-muted">—</div>
                  ) : (
                    /* capped + scrollable — the parking yard can hold dozens of chassis */
                    <ul className="max-h-80 space-y-2 overflow-y-auto pr-1">
                      {items.map((i, idx) => (
                        <li key={idx} className="rounded-md bg-surface-alt/50 p-2 text-sm">
                          <div className="flex items-baseline gap-2">
                            <span className="font-mono text-xs font-semibold text-body">
                              {i.job_number ? `J${i.job_number}` : i.chassis_vin || '—'}
                            </span>
                            {i.body_attached && (
                              <span title="Body attached to this chassis" data-testid="slot-body-attached"
                                    className="text-status-green"><Link2 size={12} /></span>
                            )}
                            {i.location && (
                              <span className="ml-auto rounded bg-white px-1.5 py-0.5 font-mono text-[10px] text-muted">
                                {i.location}
                              </span>
                            )}
                          </div>
                          {/* WO v4.35 §3.3+ — chassis VIN below the job number (VIN-to-VIN matching with
                              the assembly bay tiles). Shown only when a chassis is assigned; full VIN on hover. */}
                          {i.job_number && i.chassis_vin && (
                            <div className="truncate font-mono text-[10px] text-muted" title={i.chassis_vin}
                                 data-testid="slot-vin">
                              {i.chassis_vin}
                            </div>
                          )}
                          <div className="truncate text-xs text-body">{i.customer || '—'}</div>
                          {i.description && (
                            <div className="truncate text-[11px] text-muted">{i.description}</div>
                          )}
                          <div className="mt-0.5 flex items-center gap-2 text-[11px]">
                            <span className="text-muted">{i.status.replace(/_/g, ' ')}</span>
                            {i.since && <span className="text-muted">· since {dmy(i.since)}</span>}
                            {i.flag && (
                              <span className="font-semibold text-status-amber">⚠ {i.flag}</span>
                            )}
                          </div>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              )
            })}
          </div>
        )
      })()}
    </Card>
  )
}
