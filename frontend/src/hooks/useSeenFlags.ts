// WO v4.36b §0.5/§0.7 — per-user "seen flags" set with a 7-day TTL, LocalStorage-backed. Drives the
// §0.7 pulse rule: a flag newly crossed into a flagged state pulses sky on first render to EACH user,
// then stays steady. The seen-set is keyed per demo/session user so switching profiles re-pulses.
//
// Shape + defensive try/catch mirror useCockpitLayout.ts (the newer colon-namespaced convention); the
// TTL prune + per-user keying are the genuinely new bits (no existing LocalStorage key has a TTL).
import { useCallback, useMemo } from 'react'

import { useAppData } from '../store/AppDataContext'

const TTL_MS = 7 * 24 * 60 * 60 * 1000
type SeenMap = Record<string, number>      // flagInstanceId → first-seen epoch ms

const keyFor = (userId: string) => `icb:seen-flags:${userId}`

function read(userId: string): SeenMap {
  try {
    const raw = localStorage.getItem(keyFor(userId))
    if (!raw) return {}
    const parsed = JSON.parse(raw) as SeenMap
    const now = Date.now()
    const fresh: SeenMap = {}
    for (const [id, t] of Object.entries(parsed)) {
      if (typeof t === 'number' && now - t < TTL_MS) fresh[id] = t   // prune entries past the 7-day TTL
    }
    return fresh
  } catch {
    return {}                                // private mode / quota / corrupt — non-fatal
  }
}

function write(userId: string, map: SeenMap): void {
  try {
    localStorage.setItem(keyFor(userId), JSON.stringify(map))
  } catch {
    /* private mode / quota — non-fatal */
  }
}

/** A stable id for one flag instance: domain+entity+flag (e.g. "chassis:42:chassis_no_vin"). */
export function flagInstanceId(domain: string, entityId: number | string, flag: string): string {
  return `${domain}:${entityId}:${flag}`
}

export function useSeenFlags() {
  const { profile } = useAppData()
  const userId = String(profile?.id ?? 'anon')
  const isSeen = useCallback((id: string) => id in read(userId), [userId])
  const markSeen = useCallback((id: string) => {
    const m = read(userId)
    if (!(id in m)) {
      m[id] = Date.now()
      write(userId, m)
    }
  }, [userId])
  return useMemo(() => ({ isSeen, markSeen }), [isSeen, markSeen])
}
