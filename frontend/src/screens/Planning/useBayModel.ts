// useBayModel.ts — WO v4.31 §3.1. Loads the assembly-bay floor state for the Planning Board's
// bay-model lanes and the parking->assembly assign mutation. Lean apiGet/apiPost (mirrors ChassisList)
// + the PlanningContext mutate->refetch pattern; no new heavy context.
//
// Floor state is derived from the chassis list (the events log is the single source of truth, §0.12):
//   - parking pool  = chassis with status 'in_workshop' (booked in via VCL, not yet on a bay)
//   - assembly bays = chassis with status 'in_assembly', keyed by the backend-derived
//                     current_assembly_bay_id (latest assembly_assigned event)
import { useCallback, useEffect, useState } from 'react'
import { apiGet, apiPost, apiDelete, handleApiError, type PushToast } from '../../lib/api'
import type { Bay, ChassisRecord } from '../Chassis/types'

export interface BayModel {
  mode: 'loading' | 'live' | 'mock'
  bays: Bay[]                                    // the 5 assembly bays (sorted) — carry the 6-state + occupant
  parking: ChassisRecord[]                       // booked-in, not yet on a bay (status in_workshop)
  occupantByBay: Record<number, ChassisRecord>   // assembly bay id -> the chassis currently on it
  refresh: () => Promise<Bay[]>                  // resolves with the freshly fetched bay rows
  /** parking -> assembly. Re-throws ApiError(409) (bay occupied) so the caller can flash an inline reject.
   *  Resolves with the post-assign bay rows so the caller can detect a completed merge (ready_to_merge). */
  assign: (recordId: number, bayId: number) => Promise<Bay[]>
  /** WO v4.35 §3.3b — panels -> assembly bay (the JOB-side of the merge). Re-throws ApiError(409)
   *  (idempotency / busy-bay) for the inline reject; resolves with the post-drop bay rows. */
  markPanelsArrived: (productionJobId: number, bayId: number) => Promise<Bay[]>
  /** WO v4.35 §3.3b — the auto-merge confirm: record body_attached for the bay's occupant chassis. */
  markBodyAttached: (chassisId: number, productionJobId: number, notes?: string) => Promise<void>
  /** WO v4.35 §3.3b — the move-panels-back undo: remove a job's panels from its bay (corrects a wrong drop). */
  clearPanels: (productionJobId: number) => Promise<Bay[]>
}

export function useBayModel(pushToast: PushToast): BayModel {
  const [mode, setMode] = useState<BayModel['mode']>('loading')
  const [bays, setBays] = useState<Bay[]>([])
  const [parking, setParking] = useState<ChassisRecord[]>([])
  const [occupantByBay, setOccupantByBay] = useState<Record<number, ChassisRecord>>({})

  const refresh = useCallback(async (): Promise<Bay[]> => {
    try {
      const [bayRows, chassis] = await Promise.all([
        apiGet<Bay[]>('/api/chassis-records/bays/assembly'),
        apiGet<ChassisRecord[]>('/api/chassis-records?limit=200'),
      ])
      const occ: Record<number, ChassisRecord> = {}
      const pool: ChassisRecord[] = []
      for (const c of chassis) {
        if (c.status === 'in_assembly' && c.current_assembly_bay_id != null) {
          occ[c.current_assembly_bay_id] = c
        } else if (c.status === 'in_workshop') {
          pool.push(c)
        }
      }
      setBays(bayRows)
      setParking(pool)
      setOccupantByBay(occ)
      setMode('live')
      return bayRows
    } catch {
      setBays([])
      setParking([])
      setOccupantByBay({})
      setMode('mock')
      return []
    }
  }, [])

  useEffect(() => {
    void refresh()
  }, [refresh])

  const assign = useCallback(
    async (recordId: number, bayId: number): Promise<Bay[]> => {
      try {
        await apiPost(`/api/chassis-records/${recordId}/assembly`, { assembly_bay_id: bayId })
        return await refresh()
      } catch (e) {
        handleApiError(e, pushToast) // 409 (occupied) re-throws → caller shows an inline reject
        throw e
      }
    },
    [refresh, pushToast],
  )

  const markPanelsArrived = useCallback(
    async (productionJobId: number, bayId: number): Promise<Bay[]> => {
      try {
        await apiPost(`/api/production-jobs/${productionJobId}/panels-arrived-in-bay`, { bay_id: bayId })
        return await refresh()
      } catch (e) {
        handleApiError(e, pushToast) // 409 (idempotency / busy-bay) re-throws → caller flashes a reject
        throw e
      }
    },
    [refresh, pushToast],
  )

  const markBodyAttached = useCallback(
    // Thin — the merge-confirm modal owns error handling (so a 409 swap-rule message isn't double-toasted).
    async (chassisId: number, productionJobId: number, notes?: string): Promise<void> => {
      await apiPost(`/api/chassis-records/${chassisId}/body-attached`, {
        production_job_id: productionJobId,
        notes: (notes ?? '').trim() || null,
      })
      await refresh()
    },
    [refresh],
  )

  const clearPanels = useCallback(
    async (productionJobId: number): Promise<Bay[]> => {
      try {
        await apiDelete(`/api/production-jobs/${productionJobId}/panels-arrived-in-bay`)
        return await refresh()
      } catch (e) {
        handleApiError(e, pushToast)
        throw e
      }
    },
    [refresh, pushToast],
  )

  return { mode, bays, parking, occupantByBay, refresh, assign, markPanelsArrived, markBodyAttached,
           clearPanels }
}
