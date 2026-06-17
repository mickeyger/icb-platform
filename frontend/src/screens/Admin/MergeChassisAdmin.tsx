/** WO v4.36a §3.6 STEP 6 — admin Merge Chassis. Pick a LOSER + a WINNER, review the read-only
 * merge-preview (repoint counts · cycle-renumber plan · warnings · blocking), then confirm: the loser's
 * FKs re-point to the winner and the loser is soft-deleted (deleted_at + merged_into_id), reversible via
 * restore. The preview IS the confirm gate — a `blocking` preview disables the merge button.
 * Accepts ?loser=<id> (the orphan page's "Merge" deep-link pre-fills the loser). */
import { useCallback, useEffect, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { GitMerge, Search, X, AlertTriangle } from 'lucide-react'

import { apiGet, apiPost, ApiError, handleApiError } from '../../lib/api'
import { useToast } from '../../components/ui/toast'
import { Spinner } from '../../components/ui/feedback'

interface ChassisLite { id: number; vin: string | null; customer_name: string | null; make: string | null; status: string }
interface SideSummary { id: number; vin: string | null; make: string | null; status: string; customer_name: string | null; event_count: number }
interface MergePreview {
  loser: SideSummary; winner: SideSummary
  repoint_counts: { production_jobs: number; prejob_cards: number; lifecycle_events: number }
  event_collisions: { cycle_number: number; event_type: string; new_cycle_number: number }[]
  cycles_renumbered: { from: number; to: number }[]
  vin_conflict: boolean; warnings: string[]; blocking: boolean
}

function ChassisPicker({ label, testid, value, onPick }: {
  label: string; testid: string; value: ChassisLite | null; onPick: (c: ChassisLite | null) => void
}) {
  const [q, setQ] = useState('')
  const [results, setResults] = useState<ChassisLite[]>([])

  useEffect(() => {
    if (value || !q.trim()) { setResults([]); return }
    const t = setTimeout(() => {
      apiGet<ChassisLite[]>(`/api/chassis-records?q=${encodeURIComponent(q.trim())}&limit=20`)
        .then(setResults).catch(() => setResults([]))
    }, 250)
    return () => clearTimeout(t)
  }, [q, value])

  if (value) {
    return (
      <div data-testid={`${testid}-selected`} className="rounded-md border border-line bg-surface-alt px-3 py-2 text-sm">
        <div className="mb-0.5 text-xs font-semibold text-muted">{label}</div>
        <div className="flex items-center justify-between gap-2">
          <span><span className="font-mono">{value.vin || `#${value.id}`}</span>
            <span className="text-muted"> · {value.make || '—'} · {value.status}{value.customer_name ? ` · ${value.customer_name}` : ''}</span></span>
          <button onClick={() => { onPick(null); setQ('') }} className="rounded p-1 text-muted hover:bg-white"><X size={14} /></button>
        </div>
      </div>
    )
  }
  return (
    <div>
      <div className="mb-1 text-xs font-semibold text-muted">{label}</div>
      <div className="flex items-center gap-2 rounded-md border border-line bg-white px-2 py-1.5">
        <Search size={14} className="text-muted" />
        <input data-testid={`${testid}-search`} value={q} onChange={(e) => setQ(e.target.value)}
               placeholder="Search VIN / customer / job…" className="flex-1 text-sm outline-none" />
      </div>
      {results.length > 0 && (
        <div className="mt-1 max-h-48 overflow-y-auto rounded-md border border-line bg-white">
          {results.map((c) => (
            <button key={c.id} data-testid={`${testid}-opt-${c.id}`} onClick={() => { onPick(c); setQ('') }}
                    className="block w-full px-3 py-1.5 text-left text-sm hover:bg-surface-alt">
              <span className="font-mono">{c.vin || `#${c.id}`}</span>
              <span className="text-muted"> · {c.make || '—'} · {c.status}{c.customer_name ? ` · ${c.customer_name}` : ''}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

export function MergeChassisAdmin() {
  const toast = useToast()
  const [params] = useSearchParams()
  const [loser, setLoser] = useState<ChassisLite | null>(null)
  const [winner, setWinner] = useState<ChassisLite | null>(null)
  const [preview, setPreview] = useState<MergePreview | null>(null)
  const [loadingPreview, setLoadingPreview] = useState(false)
  const [merging, setMerging] = useState(false)

  // §3.6 — pre-fill the loser ONCE from the orphan page's "Merge" deep-link (?loser=<id>). Guarded so a
  // re-render / same-URL re-nav can't clobber a manual loser re-selection on this destructive screen.
  const prefilled = useRef(false)
  useEffect(() => {
    if (prefilled.current) return
    const lid = params.get('loser')
    if (lid) {
      prefilled.current = true
      apiGet<ChassisLite>(`/api/chassis-records/${lid}`).then(setLoser).catch(() => {})
    }
  }, [params])

  const loadPreview = useCallback(() => {
    if (!loser || !winner) { setPreview(null); return }
    setLoadingPreview(true)
    apiGet<MergePreview>(`/api/admin/chassis/${loser.id}/merge-preview?winner_id=${winner.id}`)
      .then(setPreview)
      .catch((e) => { setPreview(null); handleApiError(e, toast.push) })
      .finally(() => setLoadingPreview(false))
  }, [loser, winner, toast])

  useEffect(() => { loadPreview() }, [loadPreview])

  async function doMerge() {
    if (!loser || !winner || !preview || preview.blocking) return
    setMerging(true)
    try {
      const r = await apiPost<{ repointed: { production_jobs: number; prejob_cards: number; lifecycle_events: number } }>(
        `/api/admin/chassis/${loser.id}/merge`, { winner_id: winner.id })
      const c = r.repointed
      toast.push({ kind: 'ok', message: `Merged — re-pointed ${c.production_jobs} job(s), ${c.prejob_cards} card(s), ${c.lifecycle_events} event(s); loser soft-deleted.` })
      setLoser(null); setWinner(null); setPreview(null)
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) {
        toast.push({ kind: 'warn', message: e.detail || 'That merge conflicts.' })
      } else {
        handleApiError(e, toast.push)
      }
    } finally {
      setMerging(false)
    }
  }

  return (
    <div data-testid="admin-merge-chassis">
      <h1 className="mb-1 flex items-center gap-2 text-lg font-bold text-body">
        <GitMerge size={20} /> Merge Chassis
      </h1>
      <p className="mb-4 text-xs text-muted">
        Consolidate a duplicate (the <b>loser</b>) into the surviving record (the <b>winner</b>). All of the
        loser's jobs, cards and lifecycle history re-point to the winner; the loser is soft-deleted (a
        reversible tombstone), never hard-deleted.
      </p>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <ChassisPicker label="Loser (will be soft-deleted)" testid="merge-loser" value={loser} onPick={setLoser} />
        <ChassisPicker label="Winner (survives)" testid="merge-winner" value={winner} onPick={setWinner} />
      </div>

      {loadingPreview && <div className="flex justify-center py-8"><Spinner size={22} /></div>}

      {preview && !loadingPreview && (
        <div data-testid="merge-preview" className="mt-4 rounded-lg border border-line">
          <div className="border-b border-line bg-surface-alt px-3 py-2 text-sm font-semibold text-body">
            Merge impact — re-point {preview.repoint_counts.production_jobs} job(s) ·
            {' '}{preview.repoint_counts.prejob_cards} card(s) ·
            {' '}{preview.repoint_counts.lifecycle_events} event(s) onto the winner
          </div>
          {preview.blocking && (
            <div data-testid="merge-blocking" className="flex items-start gap-2 border-b border-line bg-status-red/10 px-3 py-2 text-xs text-status-red">
              <AlertTriangle size={14} className="mt-0.5 shrink-0" /> This merge can’t proceed — resolve the blocking item(s) below.
            </div>
          )}
          {preview.warnings.length > 0 && (
            <ul className="space-y-1 border-b border-line px-3 py-2 text-xs text-muted">
              {preview.warnings.map((w, i) => <li key={i} className="flex gap-1.5"><span className="text-status-amber">⚠</span> {w}</li>)}
            </ul>
          )}
          {preview.cycles_renumbered.length > 0 && (
            <div data-testid="merge-renumber" className="border-b border-line px-3 py-2 text-xs">
              <div className="mb-1 font-semibold text-muted">Lifecycle cycles renumbered above the winner's (preserves both histories):</div>
              <ul className="space-y-0.5">
                {preview.cycles_renumbered.map((c, i) => (
                  <li key={i} className="font-mono">cycle {c.from} → cycle {c.to}</li>
                ))}
              </ul>
            </div>
          )}
          <div className="px-3 py-3">
            <button data-testid="merge-confirm" onClick={doMerge} disabled={merging || preview.blocking}
                    className="flex items-center justify-center gap-2 rounded-md bg-status-red px-4 py-2 text-sm font-semibold text-white disabled:opacity-50">
              {merging ? <Spinner size={16} /> : <GitMerge size={14} />} Merge {preview.loser.vin || `#${preview.loser.id}`} into {preview.winner.vin || `#${preview.winner.id}`}
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
