// WO v4.36b §0.7 — wraps a flag badge in the one-shot sky pulse. A flag instance pulses on its FIRST
// render to a given user (per the LocalStorage seen-set), then renders steady. Cyan pulseRing is left
// to its existing consumers (D4) — this uses the new sky variant pulseRingSky.
import { useEffect, useState, type ReactNode } from 'react'

import { flagInstanceId, useSeenFlags } from '../../hooks/useSeenFlags'

export function FlagPulse({ domain, entityId, flag, children }: {
  domain: string
  entityId: number | string
  flag: string
  children: ReactNode
}) {
  const { isSeen, markSeen } = useSeenFlags()
  const id = flagInstanceId(domain, entityId, flag)
  const [pulse] = useState(() => !isSeen(id))     // captured once on mount — first session for this user pulses
  useEffect(() => { if (pulse) markSeen(id) }, [pulse, id, markSeen])
  if (!pulse) return <>{children}</>
  return <span className="inline-block rounded-full animate-pulseRingSky">{children}</span>
}
