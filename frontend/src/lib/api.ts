// lib/api.ts — shared fetch client for the MES SPA (WO v4.17, Phase 2C-1).
// Generalises the live/mock + credentialed-fetch pattern proven in CostingsContext
// so every context can reuse it. Same-origin in unified mode (FastAPI serves the
// build under /mes-app/); the Vite dev server proxies /api -> :8000. Override with
// VITE_API_BASE for split hosts.

export const API_BASE: string = (import.meta.env.VITE_API_BASE as string | undefined) ?? ''
const TIMEOUT_MS = 10_000

// Session CSRF token (WO v4.18). The backend's csrf_middleware requires an
// X-CSRF-Token header on unsafe methods once a session exists. AppDataContext
// reads the token from GET /api/session and caches it here so apiPost/apiDelete
// send it. Left null in mock mode (mutations never reach the network there).
let _csrfToken: string | null = null
export function setCsrfToken(token: string | null): void {
  _csrfToken = token
}

/** Typed transport error. `status === 0` means network/timeout (→ mock fallback). */
export class ApiError extends Error {
  status: number
  detail?: string
  constructor(status: number, detail?: string) {
    super(detail || `HTTP ${status}`)
    this.name = 'ApiError'
    this.status = status
    this.detail = detail
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const ctrl = new AbortController()
  const timer = setTimeout(() => ctrl.abort(), TIMEOUT_MS)
  let res: Response
  const method = (init?.method ?? 'GET').toUpperCase()
  const csrfHeader: Record<string, string> =
    _csrfToken && method !== 'GET' && method !== 'HEAD' ? { 'X-CSRF-Token': _csrfToken } : {}
  try {
    res = await fetch(`${API_BASE}${path}`, {
      credentials: 'include',
      signal: ctrl.signal,
      ...init,
      headers: { Accept: 'application/json', ...csrfHeader, ...(init?.headers ?? {}) },
    })
  } catch {
    throw new ApiError(0, 'network') // aborted / offline
  } finally {
    clearTimeout(timer)
  }
  if (!res.ok) {
    let detail: string | undefined
    try {
      detail = (await res.json())?.detail
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(res.status, detail)
  }
  if (res.status === 204) return undefined as T
  return (await res.json()) as T
}

export const apiGet = <T>(path: string): Promise<T> => request<T>(path, { method: 'GET' })

export const apiPost = <T>(path: string, body?: unknown): Promise<T> =>
  request<T>(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  })

export const apiDelete = <T>(path: string): Promise<T> => request<T>(path, { method: 'DELETE' })

/** Mint a costing-app session for the demo user so the MES SPA inherits it.
 *  Idempotent server-side; silently no-ops when the API is offline.
 *
 *  Deduplicated (WO v4.18 §3.5): the autologin POST fires at most once per app
 *  load, no matter how many contexts call it on mount. Every refresh path — the
 *  Refresh button, the branch-switch signal — uses a context's `refetch()`
 *  (reads only) and must NOT re-trigger autologin. So `bootstrap = mesAutoLogin
 *  + refetch` runs once on mount; `refetch` runs on every subsequent refresh. */
let _autoLoginPromise: Promise<void> | null = null
export function mesAutoLogin(): Promise<void> {
  if (!_autoLoginPromise) {
    _autoLoginPromise = apiPost('/api/mes/autologin').then(
      () => undefined,
      () => undefined, // offline / unauthorised → mock mode takes over
    )
  }
  return _autoLoginPromise
}

// ── Error → UX mapping (WO §3.2). Mutators call this in their catch block. ──────
export type ToastKind = 'error' | 'warn' | 'ok'
export type PushToast = (t: { kind: ToastKind; message: string }) => void

/** Map a thrown ApiError to the §3.2 treatment. 409 is RE-THROWN so the caller can
 *  show a blocking modal; everything else surfaces a toast (or a login redirect). */
export function handleApiError(err: unknown, pushToast: PushToast): void {
  if (err instanceof ApiError) {
    switch (err.status) {
      case 401:
        window.location.href = `${API_BASE}/login`
        return
      case 403:
        pushToast({ kind: 'error', message: err.detail || "You don't have permission for that action." })
        return
      case 404:
        pushToast({ kind: 'warn', message: err.detail || 'That item no longer exists — refresh to update.' })
        return
      case 409:
        throw err // caller shows a blocking conflict modal
      case 422:
        pushToast({ kind: 'warn', message: err.detail || 'That action could not be completed.' })
        return
      default:
        pushToast({ kind: 'error', message: "Couldn't reach the server. Please try again." })
        return
    }
  }
  pushToast({ kind: 'error', message: 'Unexpected error.' })
}
