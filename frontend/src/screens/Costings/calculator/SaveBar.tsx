// WO v4.37 §3.2 — Save / version flow for the native Cost Calculator.
// Customer picker → check-duplicate → (modal) replace vs new-revision → approve.
// D-2 (BA-ratified DISPLAY-map): the first costing shows no badge ("Original"),
// revisions show ver1/ver2 via revisionLabel(); the backend value stays 1-based.
import { useEffect, useRef, useState } from 'react'
import { Save, Loader2, Search, Check, X } from 'lucide-react'
import { useToast } from '../../../components/ui/toast'
import { handleApiError, ApiError } from '../../../lib/api'
import { searchCustomers, checkDuplicate, approveCalc } from './useCalculator'
import type { CalcRequest, CustomerLite, DuplicateCheck } from './types'
import { revisionLabel } from './types'

export function SaveBar({ req, disabled, isRepair = false }: {
  req: CalcRequest | null
  disabled?: boolean
  isRepair?: boolean
}) {
  const toast = useToast()
  const [customer, setCustomer] = useState<CustomerLite | null>(null)
  const [query, setQuery] = useState('')
  const [matches, setMatches] = useState<CustomerLite[]>([])
  const [open, setOpen] = useState(false)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState<{ quote: string | null; version: number | null } | null>(null)
  const [dup, setDup] = useState<DuplicateCheck | null>(null)
  const searchTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  // Debounced customer typeahead (paused once a customer is picked).
  useEffect(() => {
    if (customer) return
    if (searchTimer.current) clearTimeout(searchTimer.current)
    if (!query.trim()) { setMatches([]); return }
    searchTimer.current = setTimeout(() => {
      searchCustomers(query).then(setMatches).catch(() => setMatches([]))
    }, 250)
    return () => { if (searchTimer.current) clearTimeout(searchTimer.current) }
  }, [query, customer])

  const pick = (c: CustomerLite) => { setCustomer(c); setQuery(c.name); setOpen(false); setMatches([]); setSaved(null) }
  const clearCustomer = () => { setCustomer(null); setQuery(''); setMatches([]); setSaved(null) }

  async function save(versionAction: 'replace' | 'new_version' | null, nextVersion?: number) {
    if (!req) return
    setSaving(true)
    try {
      const res = await approveCalc(req, {
        customer_id: customer?.id ?? null,
        version_action: versionAction,
        next_version: nextVersion,
        is_repair: isRepair,
      })
      setSaved({ quote: res.quote_number ?? null, version: res.version ?? null })
      setDup(null)
      toast.push({ kind: 'ok', message: res.quote_number ? `Saved as ${res.quote_number}` : 'Costing saved' })
    } catch (e) {
      // A 409 here = a duplicate appeared between the pre-check and the save
      // (race). Surface the choice rather than letting handleApiError re-throw.
      if (e instanceof ApiError && e.status === 409) {
        toast.push({ kind: 'warn', message: e.detail || 'A costing was just saved for this customer — choose Replace or new revision.' })
        if (customer) checkDuplicate(customer.id, req.trailer_type_id, isRepair).then((d) => { if (d.has_duplicate) setDup(d) }).catch(() => {})
      } else {
        handleApiError(e, toast.push)
      }
    } finally { setSaving(false) }
  }

  async function onSave() {
    if (!req) return
    if (customer) {
      try {
        const d = await checkDuplicate(customer.id, req.trailer_type_id, isRepair)
        if (d.has_duplicate) { setDup(d); return }
      } catch { /* fall through to a plain save */ }
    }
    void save(null)
  }

  return (
    <div className="mt-4 rounded-lg border border-line bg-white p-4">
      <div className="mb-2 text-xs font-bold uppercase tracking-wide text-muted">Save costing</div>

      <div className="relative mb-3">
        <label className="mb-1 block text-[11px] font-semibold uppercase tracking-wide text-muted">Customer</label>
        <div className="flex items-center gap-2">
          <div className="relative flex-1">
            <Search size={13} className="absolute left-2 top-1/2 -translate-y-1/2 text-muted" />
            <input
              className="w-full rounded-md border border-line bg-white py-1.5 pl-7 pr-2 text-sm text-body focus:border-primary focus:outline-none"
              placeholder="Search customer…"
              value={query}
              disabled={!!customer}
              onChange={(e) => { setQuery(e.target.value); setOpen(true) }}
              onFocus={() => setOpen(true)}
            />
          </div>
          {customer && (
            <button onClick={clearCustomer} title="Clear customer"
              className="rounded-md border border-line px-2 py-1.5 text-xs text-muted hover:bg-surface-alt">
              <X size={13} />
            </button>
          )}
        </div>
        {open && !customer && matches.length > 0 && (
          <div className="absolute z-10 mt-1 max-h-48 w-full overflow-y-auto rounded-md border border-line bg-white shadow-lg">
            {matches.map((c) => (
              <button key={c.id} onClick={() => pick(c)}
                className="block w-full px-3 py-1.5 text-left text-sm text-body hover:bg-surface-alt">
                {c.name}{c.bp_code ? <span className="ml-2 text-[11px] text-muted">{c.bp_code}</span> : null}
              </button>
            ))}
          </div>
        )}
      </div>

      <div className="flex items-center justify-between">
        <div className="text-xs text-muted">
          {saved ? (
            <span className="flex items-center gap-1 text-status-green">
              <Check size={13} /> {saved.quote ?? 'Saved'}
              {revisionLabel(saved.version) && (
                <span className="ml-1 rounded bg-status-green/15 px-1.5 py-0.5 text-[10px] font-bold uppercase">{revisionLabel(saved.version)}</span>
              )}
            </span>
          ) : customer ? `Saving under ${customer.name}` : 'No customer (saves without one)'}
        </div>
        <button onClick={onSave} disabled={disabled || saving || !req}
          className="flex items-center gap-1.5 rounded-md bg-primary px-3 py-1.5 text-sm font-semibold text-white hover:bg-primary-dark disabled:opacity-50">
          {saving ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />} Save
        </button>
      </div>

      {dup && (
        <DuplicateModal
          dup={dup}
          busy={saving}
          onReplace={() => save('replace')}
          onNewVersion={() => save('new_version', dup.next_version)}
          onCancel={() => setDup(null)}
        />
      )}
    </div>
  )
}

function DuplicateModal({ dup, onReplace, onNewVersion, onCancel, busy }: {
  dup: DuplicateCheck
  onReplace: () => void
  onNewVersion: () => void
  onCancel: () => void
  busy: boolean
}) {
  const nextLabel = revisionLabel(dup.next_version) || `version ${dup.next_version}`
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={onCancel}>
      <div className="w-full max-w-md rounded-lg bg-white p-5 shadow-xl" onClick={(e) => e.stopPropagation()}>
        <div className="mb-2 text-base font-bold text-body">A costing already exists for this customer + body type</div>
        <div className="mb-3 text-sm text-muted">
          {dup.count} existing {dup.count === 1 ? 'costing' : 'costings'}. Save this as a new revision, or replace the existing one(s)?
        </div>
        <div className="mb-4 max-h-40 overflow-y-auto rounded-md border border-line">
          {(dup.records ?? []).map((r) => (
            <div key={r.id} className="flex items-center justify-between border-b border-line/60 px-3 py-1.5 text-xs last:border-0">
              <span className="text-body">
                {r.quote_number ?? `#${r.id}`}
                {revisionLabel(r.version) && <span className="ml-1 text-muted">({revisionLabel(r.version)})</span>}
              </span>
              <span className="text-muted">{r.saved_at}</span>
            </div>
          ))}
        </div>
        <div className="flex items-center justify-end gap-2">
          <button onClick={onCancel} disabled={busy} className="rounded-md border border-line px-3 py-1.5 text-sm text-body hover:bg-surface-alt">Cancel</button>
          <button onClick={onReplace} disabled={busy} className="rounded-md border border-status-red px-3 py-1.5 text-sm font-semibold text-status-red hover:bg-status-red/5">Replace existing</button>
          <button onClick={onNewVersion} disabled={busy} className="rounded-md bg-primary px-3 py-1.5 text-sm font-semibold text-white hover:bg-primary-dark">Save as new {nextLabel}</button>
        </div>
      </div>
    </div>
  )
}
