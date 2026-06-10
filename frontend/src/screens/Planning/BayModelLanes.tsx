// BayModelLanes.tsx — WO v4.31 §3.1. The bay-model row beneath the week-grid: a Parking pool
// (booked-in chassis awaiting a bay) + the 5 Assembly bays as drop targets. Drag a parked chassis
// onto a bay to assign (parking -> assembly); one chassis per bay — a 409 flashes an inline reject,
// reusing the schedule grid's cellOccupied pattern. Pessimistic (assign awaits the API, then the hook
// refetches — no optimistic move). The affordance is gated on chassis.assembly_assign; without it the
// lanes are view-only. Back-to-parking is Phase 4 — deliberately no un-assign affordance here.
import { useState } from 'react'
import { GripVertical, Plus } from 'lucide-react'
import { Card } from '../../components/ui/primitives'
import { useToast } from '../../components/ui/toast'
import { useAppData } from '../../store/AppDataContext'
import { ApiError } from '../../lib/api'
import { useBayModel } from './useBayModel'
import type { ChassisRecord } from '../Chassis/types'

export function BayModelLanes() {
  const toast = useToast()
  const { hasPermission, isAdmin } = useAppData()
  const canAssign = isAdmin || hasPermission('chassis.assembly_assign')
  const { mode, bays, parking, occupantByBay, assign } = useBayModel(toast.push)
  const [drag, setDrag] = useState<ChassisRecord | null>(null)
  const [rejectBay, setRejectBay] = useState<number | null>(null)
  const [busyBay, setBusyBay] = useState<number | null>(null)

  if (mode === 'mock') return null // bay model is a live-only surface (API unreachable → offline demo)

  async function dropOnBay(bayId: number) {
    const chassis = drag
    setDrag(null)
    if (!chassis || !canAssign) return
    try {
      setBusyBay(bayId)
      await assign(chassis.id, bayId)
    } catch (e) {
      // 409 = bay already occupied → inline reject (toast already raised by the hook for other codes).
      if (e instanceof ApiError && e.status === 409) {
        setRejectBay(bayId)
        setTimeout(() => setRejectBay(null), 1800)
      }
    } finally {
      setBusyBay(null)
    }
  }

  const freeBays = bays.filter((b) => !occupantByBay[b.id]).length

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

      {/* Assembly bays — 5 drop targets; one chassis each (status in_assembly). */}
      <Card>
        <div className="mb-2 flex items-center justify-between">
          <span className="text-sm font-semibold uppercase tracking-wide text-muted">Assembly</span>
          <span className="text-[11px] text-muted">{bays.length} bays · {freeBays} free</span>
        </div>
        <div className="grid grid-cols-[repeat(auto-fit,minmax(132px,1fr))] gap-2">
          {bays.map((bay) => {
            const occ = occupantByBay[bay.id]
            const rejected = rejectBay === bay.id
            const busy = busyBay === bay.id
            return (
              <div
                key={bay.id}
                data-testid="assembly-bay"
                data-bay-id={bay.id}
                onDragOver={(e) => { if (canAssign && drag) e.preventDefault() }}
                onDrop={() => void dropOnBay(bay.id)}
                className={`relative rounded-md p-2 transition ${
                  rejected
                    ? 'border-2 border-status-red bg-status-red/20'
                    : occ
                      ? 'border border-line border-l-4 border-l-status-green bg-white'
                      : 'border border-dashed border-line bg-surface-alt/40'
                }`}
              >
                {busy && (
                  <div className="absolute inset-0 z-10 flex items-center justify-center rounded-md bg-white/60 text-[11px] text-muted">
                    assigning…
                  </div>
                )}
                <div className="text-[11px] text-muted">{bay.code}</div>
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
              </div>
            )
          })}
          {bays.length === 0 && <div className="text-sm text-muted">No assembly bays.</div>}
        </div>
        <div className="mt-3 border-t border-line pt-3 text-[11px] text-muted">
          One chassis per bay · status → in_assembly on assign.
        </div>
      </Card>
    </div>
  )
}
