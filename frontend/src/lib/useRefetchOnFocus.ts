// useRefetchOnFocus.ts — WO v4.35 §3.3b. Cross-page sync without websockets (Q6 — websockets are
// v4.36+): refetch when the tab regains focus or becomes visible again. Wired on the three surfaces that
// share the body↔chassis floor state — the Production Dashboard, the Planning Board, and the bay-model
// lanes — so an action taken on one page (e.g. panels dragged to a bay, body marked attached) is reflected
// on the others the next time the operator switches back to them. `refresh` must be a stable callback
// (useCallback) so the listeners register once.
import { useEffect } from 'react'

export function useRefetchOnFocus(refresh: () => unknown) {
  useEffect(() => {
    const onVisible = () => {
      if (document.visibilityState === 'visible') void refresh()
    }
    const onFocus = () => void refresh()
    document.addEventListener('visibilitychange', onVisible)
    window.addEventListener('focus', onFocus)
    return () => {
      document.removeEventListener('visibilitychange', onVisible)
      window.removeEventListener('focus', onFocus)
    }
  }, [refresh])
}
