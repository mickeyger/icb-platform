// useBayModel.ts — WO v4.31 §3.1. Loads the assembly-bay floor state for the Planning Board's
// bay-model lanes and the parking->assembly assign mutation. Lean apiGet/apiPost (mirrors ChassisList)
// + the PlanningContext mutate->refetch pattern; no new heavy context.
//
// Floor state is derived from the chassis list (the events log is the single source of truth, §0.12):
//   - parking pool  = chassis with status 'in_workshop' (booked in via VCL, not yet on a bay)
//   - assembly bays = chassis with status 'in_assembly', keyed by the backend-derived
//                     current_assembly_bay_id (latest assembly_assigned event)
import { useCallback, useEffect, useState } from 'react'
import { apiGet, apiPost, handleApiError, type PushToast } from '../../lib/api'
import type { Bay, ChassisRecord } from '../Chassis/types'

export interface BayModel {
  mode: 'loading' | 'live' | 'mock'
  bays: Bay[]                                    // the 5 assembly bays (sorted)
  parking: ChassisRecord[]                       // booked-in, not yet on a bay (status in_workshop)
  occupantByBay: Record<number, ChassisRecord>   // assembly bay id -> the chassis currently on it
  refresh: () => Promise<void>
  /** parking -> assembly. Re-throws ApiError(409) (bay occupied) so the caller can flash an inline reject. */
  assign: (recordId: number, bayId: number) => Promise<void>
}

export function useBayModel(pushToast: PushToast): BayModel {
  const [mode, setMode] = useState<BayModel['mode']>('loading')
  const [bays, setBays] = useState<Bay[]>([])
  const [parking, setParking] = useState<ChassisRecord[]>([])
  const [occupantByBay, setOccupantByBay] = useState<Record<number, ChassisRecord>>({})

  const refresh = useCallback(async () => {
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
    } catch {
      setBays([])
      setParking([])
      setOccupantByBay({})
      setMode('mock')
    }
  }, [])

  useEffect(() => {
    void refresh()
  }, [refresh])

  const assign = useCallback(
    async (recordId: number, bayId: number) => {
      try {
        await apiPost(`/api/chassis-records/${recordId}/assembly`, { assembly_bay_id: bayId })
        await refresh()
      } catch (e) {
        handleApiError(e, pushToast) // 409 (occupied) re-throws → caller shows an inline reject
        throw e
      }
    },
    [refresh, pushToast],
  )

  return { mode, bays, parking, occupantByBay, refresh, assign }
}
