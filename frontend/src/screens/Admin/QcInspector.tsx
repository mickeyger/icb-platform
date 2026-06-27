/** WO v4.36c §3.2 — Kenny's QC inspection screen (custom admin screen at /admin/qc).
 *
 * One screen, two views, driven by the `?chassis=` query param (keeps it inside the existing
 * /admin/:resource dispatcher — no App.tsx edit, no v4.38 deep-link trap):
 *   - no param  → the QC inbox (chassis awaiting QA, with AgeingPill + a "failed Nx" badge)
 *   - ?chassis= → the inspection form (per-category pass/fail + notes; sign-off when all verdicted)
 *
 * The backend is the source of truth: each verdict is POSTed as it's set, the sign-off completeness +
 * overall verdict are computed server-side (§3.1), and on a PASS the chassis transitions to
 * 'dispatched' / on a FAIL it returns to 'awaiting_qa' with the QC cycle incremented.
 */
import { useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { ArrowLeft, CheckCircle2, ClipboardList, XCircle } from 'lucide-react'

import { Card } from '../../components/ui/primitives'
import { Skeleton, EmptyState } from '../../components/ui/feedback'
import { useToast } from '../../components/ui/toast'
import { handleApiError } from '../../lib/api'
import { dmy } from '../../lib/format'
import { AgeingPill } from '../../components/Flag/AgeingPill'
import {
  recordVerdict, submitSignoff, useInspection, useQcInbox,
  type QcInboxRow, type Verdict,
} from '../../hooks/useQc'

function daysSince(iso: string | null): number {
  if (!iso) return 0
  return Math.max(0, Math.floor((Date.now() - new Date(iso).getTime()) / 86_400_000))
}

export function QcInspector() {
  const [params, setParams] = useSearchParams()
  const chassisParam = params.get('chassis')
  const chassisId = chassisParam ? Number(chassisParam) : null
  if (chassisId != null && !Number.isNaN(chassisId)) {
    return <InspectionForm chassisId={chassisId} onBack={() => setParams({})} />
  }
  return <QcInbox onOpen={(id) => setParams({ chassis: String(id) })} />
}

// ── Inbox ──────────────────────────────────────────────────────────────────
function QcInbox({ onOpen }: { onOpen: (chassisId: number) => void }) {
  const { rows, loading } = useQcInbox()
  return (
    <div data-testid="qc-inbox">
      <h2 className="mb-1 flex items-center gap-2 text-lg font-bold text-body">
        <ClipboardList size={20} /> QC inspection inbox
        <span className="text-sm font-normal text-muted">({rows.length})</span>
      </h2>
      <p className="mb-3 text-xs text-muted">Chassis awaiting QA. Open a chassis to run the inspection,
        then sign off — a pass dispatches it; a fail returns it here for re-inspection.</p>

      {loading ? <Skeleton rows={5} /> : rows.length === 0 ? (
        <EmptyState title="Nothing awaiting QC" hint="No chassis are in the Awaiting-QA queue right now." />
      ) : (
        <Card className="p-0">
          <div className="overflow-x-auto">
            <table className="w-full text-sm" data-testid="qc-inbox-table">
              <thead className="bg-primary text-left text-white">
                <tr>
                  <th className="px-3 py-2 font-semibold">Job</th>
                  <th className="px-3 py-2 font-semibold">Chassis</th>
                  <th className="px-3 py-2 font-semibold">Customer</th>
                  <th className="px-3 py-2 text-center font-semibold">Awaiting</th>
                  <th className="px-3 py-2 font-semibold">Inspect</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r: QcInboxRow, i) => (
                  <tr key={r.chassis_id} data-testid={`qc-row-${r.chassis_id}`}
                    className={`border-b border-line ${i % 2 ? 'bg-surface-alt' : 'bg-white'}`}>
                    <td className="px-3 py-2 font-mono text-xs font-semibold">{r.job_number ?? '—'}</td>
                    <td className="px-3 py-2">
                      <div className="font-mono text-xs">{r.vin ?? '—'}</div>
                      <div className="text-xs text-muted">{[r.make, r.model].filter(Boolean).join(' ') || '—'}</div>
                      {r.failed_count > 0 && (
                        <span data-testid={`qc-failed-badge-${r.chassis_id}`}
                          className="mt-1 inline-block rounded-full bg-status-red/15 px-2 py-0.5 text-[11px] font-semibold text-status-red">
                          failed {r.failed_count}×
                        </span>
                      )}
                    </td>
                    <td className="px-3 py-2">{r.customer_name ?? '—'}</td>
                    <td className="px-3 py-2 text-center">
                      <AgeingPill days={daysSince(r.awaiting_since)} green={3} amber={6} red={7}
                        label="d" testid={`qc-age-${r.chassis_id}`} />
                    </td>
                    <td className="px-3 py-2">
                      <button data-testid={`qc-inspect-${r.chassis_id}`} onClick={() => onOpen(r.chassis_id)}
                        className="rounded bg-primary px-3 py-1 text-xs font-semibold text-white hover:bg-primary-dark">
                        Inspect →
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}
    </div>
  )
}

// ── Inspection form ──────────────────────────────────────────────────────────
function InspectionForm({ chassisId, onBack }: { chassisId: number; onBack: () => void }) {
  const toast = useToast()
  const { data, loading, refresh } = useInspection(chassisId)
  const [verdicts, setVerdicts] = useState<Record<number, Verdict | null>>({})
  const [notes, setNotes] = useState<Record<number, string>>({})
  const [signoffNotes, setSignoffNotes] = useState('')
  const [busy, setBusy] = useState(false)

  // Seed local state from the server's open-cycle verdicts whenever the inspection (re)loads.
  useEffect(() => {
    if (!data) return
    setVerdicts(Object.fromEntries(data.categories.map((c) => [c.category_id, c.verdict])))
    setNotes(Object.fromEntries(data.categories.map((c) => [c.category_id, c.notes ?? ''])))
  }, [data])

  const allVerdicted = useMemo(
    () => !!data && data.categories.length > 0 && data.categories.every((c) => verdicts[c.category_id]),
    [data, verdicts])

  const setVerdict = (categoryId: number, v: Verdict) => {
    setVerdicts((prev) => ({ ...prev, [categoryId]: v }))
    recordVerdict(chassisId, categoryId, v, notes[categoryId] || null)
      .catch((e) => handleApiError(e, toast.push))      // backend is source of truth; surface, don't swallow
  }
  const flushNote = (categoryId: number) => {
    const v = verdicts[categoryId]
    if (!v) return                                       // a note without a verdict isn't persisted yet
    recordVerdict(chassisId, categoryId, v, notes[categoryId] || null)
      .catch((e) => handleApiError(e, toast.push))
  }

  const doSignoff = async () => {
    setBusy(true)
    try {
      const res = await submitSignoff(chassisId, signoffNotes.trim() || null)
      toast.push(res.overall_verdict === 'pass'
        ? { kind: 'ok', message: 'QC passed — chassis dispatched. Collection PDF available.' }
        : { kind: 'warn', message: 'QC failed — chassis returned to Awaiting QA for re-inspection.' })
      onBack()
    } catch (e) { handleApiError(e, toast.push) } finally { setBusy(false) }
  }

  if (loading) return <div data-testid="qc-form"><Skeleton rows={7} /></div>
  if (!data) return <EmptyState title="Chassis not found" hint="It may have been dispatched or removed." />

  return (
    <div data-testid="qc-form">
      <button onClick={onBack} data-testid="qc-back"
        className="mb-3 flex items-center gap-1 text-sm text-primary hover:underline">
        <ArrowLeft size={14} /> Back to inbox
      </button>

      <div className="mb-3 rounded-lg border border-line bg-surface-alt p-3">
        <h2 className="flex items-center gap-2 text-lg font-bold text-body">
          <ClipboardList size={20} /> QC inspection
          {data.cycle_number > 1 && (
            <span data-testid="qc-reinspection" className="rounded-full bg-status-amber/15 px-2 py-0.5 text-xs font-semibold text-status-amber">
              Re-inspection #{data.cycle_number}
            </span>
          )}
        </h2>
        <p className="mt-1 text-xs text-muted">
          <span className="font-mono font-semibold">{data.vin ?? '—'}</span>
          {' · '}{[data.make, data.model].filter(Boolean).join(' ') || '—'}
          {' · '}{data.customer_name ?? '—'}
        </p>
        {data.prior_signoffs.some((s) => s.overall_verdict === 'fail') && (
          <p className="mt-1 text-xs text-status-red">
            Previously failed {data.prior_signoffs.filter((s) => s.overall_verdict === 'fail').length}× —
            last: {dmy(data.prior_signoffs.find((s) => s.overall_verdict === 'fail')?.created_at ?? null)}
          </p>
        )}
      </div>

      <div className="space-y-2">
        {data.categories.map((c) => {
          const v = verdicts[c.category_id]
          return (
            <div key={c.category_id} data-testid={`qc-cat-${c.category_id}`}
              className="rounded-md border border-line bg-white p-3">
              <div className="flex items-center justify-between gap-3">
                <span className="font-semibold text-body">{c.name}</span>
                <div className="flex gap-1">
                  <button data-testid={`qc-pass-${c.category_id}`} onClick={() => setVerdict(c.category_id, 'pass')}
                    className={`flex items-center gap-1 rounded px-3 py-1 text-xs font-semibold ${
                      v === 'pass' ? 'bg-status-green text-white' : 'bg-surface-alt text-muted hover:text-status-green'}`}>
                    <CheckCircle2 size={14} /> Pass
                  </button>
                  <button data-testid={`qc-fail-${c.category_id}`} onClick={() => setVerdict(c.category_id, 'fail')}
                    className={`flex items-center gap-1 rounded px-3 py-1 text-xs font-semibold ${
                      v === 'fail' ? 'bg-status-red text-white' : 'bg-surface-alt text-muted hover:text-status-red'}`}>
                    <XCircle size={14} /> Fail
                  </button>
                </div>
              </div>
              <textarea data-testid={`qc-notes-${c.category_id}`} value={notes[c.category_id] ?? ''}
                onChange={(e) => setNotes((p) => ({ ...p, [c.category_id]: e.target.value }))}
                onBlur={() => flushNote(c.category_id)}
                placeholder={v === 'fail' ? 'Describe the defect…' : 'Notes (optional)'}
                rows={v === 'fail' ? 2 : 1}
                className="mt-2 w-full rounded border border-line px-2 py-1 text-sm" />
            </div>
          )
        })}
      </div>

      <div className="mt-4 rounded-lg border border-line bg-surface-alt p-3">
        <textarea data-testid="qc-signoff-notes" value={signoffNotes}
          onChange={(e) => setSignoffNotes(e.target.value)} placeholder="Overall sign-off notes (optional)"
          rows={2} className="mb-2 w-full rounded border border-line px-2 py-1 text-sm" />
        <button data-testid="qc-signoff" disabled={!allVerdicted || busy} onClick={doSignoff}
          className={`w-full rounded-lg px-4 py-2 text-sm font-bold text-white ${
            allVerdicted && !busy ? 'bg-primary hover:bg-primary-dark' : 'cursor-not-allowed bg-line text-muted'}`}>
          {busy ? 'Signing off…' : allVerdicted ? 'Sign off inspection' : 'Sign off (all categories need a verdict)'}
        </button>
      </div>
      {/* refresh is wired so a future "reset" can re-pull server state */}
      <button onClick={refresh} className="sr-only" aria-hidden tabIndex={-1}>refresh</button>
    </div>
  )
}
