import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { ExternalLink, RadioTower, RefreshCw, AlertCircle, Loader2 } from 'lucide-react'
import { useCostings } from '../../store/CostingsContext'
import { CostingsDashboard } from './CostingsDashboard'

// WO v4.7 — point at the MES-skin fork (/mes/calculator) instead of /calculator.
// The live /calculator route now serves the original dark-Icecold styling and
// must NOT be embedded in the mockup. /mes/calculator inherits the same wizard
// + auth + logic from the live template and overlays the MES skin on top.
const TARGET_URL = '/mes/calculator'

/**
 * Embeds the real costing-app calculator (the 7-step wizard) inside the MES
 * shell. Same page, same auth, same logic — the MES nav stays visible above it.
 *
 * Requires:
 *  - The FastAPI costing app must be running on localhost:8000.
 *  - The user must be signed in to the costing app in this browser session.
 *    (Otherwise the iframe renders the login screen instead.)
 *  - CSP frame-ancestors on the costing app must permit localhost:5173/4173 —
 *    we extended this in app/main.py when the MES integration landed.
 */
export function LiveCalculator() {
  const [reloadKey, setReloadKey] = useState(0)
  // CostingsProvider attempts a dev-mode auto-login on mount; wait for it to
  // finish (mode flips off 'loading') before mounting the iframe so the
  // session cookie is in place when /calculator loads.
  const { mode } = useCostings()

  // v1.39.1 backport (Item 1b): thread a dashboard "Edit" deep-link (/costings/new?edit=<calculation_id>)
  // onto the iframe src so the legacy calculator (calculator.js:2112 reads ?edit=) reopens that calculation
  // for editing. No param → fresh calculator, unchanged.
  const [searchParams] = useSearchParams()
  const editId = searchParams.get('edit')
  const iframeSrc = editId ? `${TARGET_URL}?edit=${encodeURIComponent(editId)}` : TARGET_URL

  return (
    <>
    <div className="flex h-[calc(100vh-96px)] flex-col">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line bg-surface-alt px-4 py-2 text-sm">
        <div className="flex items-center gap-2">
          <RadioTower size={15} className="text-status-green" />
          <span className="font-semibold text-body">New Costing</span>
          <span className="rounded-full bg-status-green/15 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide text-status-green">
            Live
          </span>
          <span className="text-xs text-muted">
            embedded from <span className="font-mono">{TARGET_URL}</span>
          </span>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setReloadKey((k) => k + 1)}
            title="Reload"
            className="flex items-center gap-1 rounded-md border border-line bg-white px-2.5 py-1.5 text-xs font-semibold text-body hover:bg-surface-alt"
          >
            <RefreshCw size={13} /> Reload
          </button>
          <a
            href={TARGET_URL}
            target="_blank"
            rel="noopener noreferrer"
            className="flex items-center gap-1 rounded-md bg-primary px-2.5 py-1.5 text-xs font-semibold text-white hover:bg-primary-dark"
          >
            <ExternalLink size={13} /> Open in new tab
          </a>
        </div>
      </div>

      {mode === 'loading' ? (
        <div className="flex flex-1 items-center justify-center bg-surface-alt text-muted">
          <Loader2 size={18} className="mr-2 animate-spin" />
          Signing into the costing app…
        </div>
      ) : (
        <iframe
          key={reloadKey}
          src={iframeSrc}
          title="Calculator (live costing app)"
          className="flex-1 w-full border-0 bg-white"
          sandbox="allow-same-origin allow-scripts allow-forms allow-popups allow-downloads"
        />
      )}

      <div className="flex items-start gap-2 border-t border-line bg-surface-alt px-4 py-2 text-xs text-muted">
        <AlertCircle size={13} className="mt-0.5 shrink-0 text-status-amber" />
        <span>
          If you see a login screen above, sign in to the costing app at{' '}
          <a href={TARGET_URL} target="_blank" rel="noopener noreferrer" className="font-semibold text-primary hover:underline">
            {TARGET_URL}
          </a>{' '}
          in another tab — your session cookie will then carry into this iframe on reload. When the FastAPI
          app is offline the iframe will fail to load; use “Open in new tab” to confirm the URL.
        </span>
      </div>
    </div>

    {/* WO v4.31 §3.3 (§0.13) — the SAME CostingsDashboard component, compressed embed BELOW the
        calculator (iframe keeps the full viewport on load; scroll down for the dashboard).
        Actions + modals stay live here (permission-gated) — NOT display-only. */}
    <div className="border-t border-line">
      <CostingsDashboard embedded />
    </div>
    </>
  )
}
