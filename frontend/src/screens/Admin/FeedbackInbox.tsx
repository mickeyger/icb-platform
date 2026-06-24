// FeedbackInbox — admin triage view for the Feedback Portal (WO v4.38).
// Lists submitted tickets, filters by status, and drills into a detail panel where
// an admin reads the report + AI triage + screenshot and moves the ticket through
// its lifecycle. Admin-gated by the backend (/api/admin/feedback require_admin).
import { useCallback, useEffect, useState } from 'react'
import { RefreshCw } from 'lucide-react'
import { apiGet, apiPatch } from '../../lib/api'
import { SidePanel } from '../../components/ui/overlays'

const STATUSES = ['submitted', 'triaged', 'in_progress', 'resolved', 'closed'] as const
type Status = (typeof STATUSES)[number]

interface Summary {
  id: number
  created_at: string | null
  submitter_name: string
  page_url: string
  issue_type: string | null
  severity: string | null
  summary: string
  status: string
  assigned_to: string
  has_screenshot: boolean
}
interface HistoryEntry {
  at: string
  by: string
  from: string | null
  to: string
  note: string | null
}
interface Detail extends Summary {
  user_text: string
  probable_cause: string
  clarifying_questions: string[]
  user_answers: unknown
  ai_model: string | null
  resolution_notes: string
  updated_at: string | null
  screenshot_url: string | null
  status_history: HistoryEntry[]
}

const SEV_CLS: Record<string, string> = {
  blocker: 'bg-status-red text-white',
  major: 'bg-status-amber text-white',
  minor: 'bg-amber-100 text-amber-800',
  nice: 'bg-surface-alt text-muted',
}
const STATUS_LABEL: Record<string, string> = {
  submitted: 'Submitted', triaged: 'Triaged', in_progress: 'In progress', resolved: 'Resolved', closed: 'Closed',
}

function when(iso: string | null): string {
  if (!iso) return ''
  try { return new Date(iso).toLocaleString() } catch { return iso }
}

export function FeedbackInbox() {
  const [rows, setRows] = useState<Summary[]>([])
  const [loading, setLoading] = useState(true)
  const [filter, setFilter] = useState<Status | 'all'>('all')
  const [detail, setDetail] = useState<Detail | null>(null)
  const [saving, setSaving] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const q = filter === 'all' ? '' : `?status=${filter}`
      setRows(await apiGet<Summary[]>(`/api/admin/feedback${q}`))
    } catch {
      setRows([])
    } finally {
      setLoading(false)
    }
  }, [filter])

  useEffect(() => { void load() }, [load])

  const openDetail = useCallback(async (id: number) => {
    try { setDetail(await apiGet<Detail>(`/api/admin/feedback/${id}`)) } catch { /* gone */ }
  }, [])

  const patch = useCallback(async (id: number, body: Record<string, unknown>) => {
    setSaving(true)
    try {
      const d = await apiPatch<Detail>(`/api/admin/feedback/${id}`, body)
      setDetail(d)
      void load()
    } catch {
      /* surfaced by global handler in real flows; inbox stays usable */
    } finally {
      setSaving(false)
    }
  }, [load])

  return (
    <div className="p-6" data-testid="feedback-inbox">
      <div className="mb-4 flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-body">Feedback inbox</h1>
          <p className="text-sm text-muted">In-app issue reports from the shop floor (WO v4.38).</p>
        </div>
        <button onClick={() => void load()} className="flex items-center gap-2 rounded-lg border border-line px-3 py-2 text-sm text-muted hover:bg-surface-alt">
          <RefreshCw size={15} className={loading ? 'animate-spin' : ''} /> Refresh
        </button>
      </div>

      <div className="mb-4 flex flex-wrap gap-2">
        {(['all', ...STATUSES] as const).map((s) => (
          <button
            key={s}
            data-testid={`feedback-filter-${s}`}
            onClick={() => setFilter(s)}
            className={`rounded-full px-3 py-1 text-xs font-medium ${filter === s ? 'bg-primary text-white' : 'bg-surface-alt text-muted hover:bg-line'}`}
          >
            {s === 'all' ? 'All' : STATUS_LABEL[s]}
          </button>
        ))}
      </div>

      <div className="overflow-hidden rounded-xl border border-line bg-white">
        <table className="w-full text-sm">
          <thead className="bg-surface-alt text-left text-xs uppercase tracking-wide text-muted">
            <tr>
              <th className="px-3 py-2">#</th>
              <th className="px-3 py-2">Severity</th>
              <th className="px-3 py-2">Type</th>
              <th className="px-3 py-2">Summary</th>
              <th className="px-3 py-2">From</th>
              <th className="px-3 py-2">When</th>
              <th className="px-3 py-2">Status</th>
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 && !loading && (
              <tr><td colSpan={7} className="px-3 py-8 text-center text-muted">No feedback yet.</td></tr>
            )}
            {rows.map((r) => (
              <tr
                key={r.id}
                data-testid={`feedback-row-${r.id}`}
                onClick={() => void openDetail(r.id)}
                className="cursor-pointer border-t border-line hover:bg-surface-alt"
              >
                <td className="px-3 py-2 text-muted">{r.id}</td>
                <td className="px-3 py-2">
                  {r.severity ? (
                    <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${SEV_CLS[r.severity] || 'bg-surface-alt text-muted'}`}>{r.severity}</span>
                  ) : <span className="text-xs text-muted">—</span>}
                </td>
                <td className="px-3 py-2 text-muted">{r.issue_type || '—'}</td>
                <td className="px-3 py-2 text-body">{r.summary}</td>
                <td className="px-3 py-2 text-muted">{r.submitter_name}</td>
                <td className="px-3 py-2 text-muted">{when(r.created_at)}</td>
                <td className="px-3 py-2"><span className="text-xs text-muted">{STATUS_LABEL[r.status] || r.status}</span></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <SidePanel
        open={!!detail}
        onClose={() => setDetail(null)}
        title={detail ? `Ticket #${detail.id}` : ''}
        width="w-[480px]"
      >
        {detail && (
          <div className="space-y-4" data-testid="feedback-detail">
            <div className="flex flex-wrap items-center gap-2">
              {detail.severity && (
                <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${SEV_CLS[detail.severity] || 'bg-surface-alt text-muted'}`}>{detail.severity}</span>
              )}
              {detail.issue_type && <span className="rounded-full bg-surface-alt px-2 py-0.5 text-xs text-muted">{detail.issue_type}</span>}
              {detail.ai_model && <span className="text-xs text-muted">via {detail.ai_model}</span>}
            </div>

            <Field label="Report">
              <p className="whitespace-pre-wrap text-sm text-body">{detail.user_text}</p>
            </Field>
            {detail.summary && <Field label="AI summary"><p className="text-sm text-body">{detail.summary}</p></Field>}
            {detail.probable_cause && <Field label="AI probable cause"><p className="text-sm text-body">{detail.probable_cause}</p></Field>}

            {detail.clarifying_questions.length > 0 && (
              <Field label="Clarifying questions">
                <ul className="list-disc space-y-1 pl-4 text-sm text-body">
                  {detail.clarifying_questions.map((q, i) => <li key={i}>{q}</li>)}
                </ul>
                {detail.user_answers != null && (
                  <pre className="mt-2 overflow-x-auto rounded bg-surface-alt p-2 text-xs text-muted">{JSON.stringify(detail.user_answers, null, 2)}</pre>
                )}
              </Field>
            )}

            <Field label="Page">
              <p className="break-all text-xs text-muted">{detail.page_url || '(unknown)'}</p>
            </Field>

            {detail.screenshot_url && (
              <Field label="Screenshot">
                <a href={detail.screenshot_url} target="_blank" rel="noreferrer">
                  <img src={detail.screenshot_url} alt="report screenshot" className="w-full rounded border border-line" />
                </a>
              </Field>
            )}

            <div className="border-t border-line pt-3">
              <Field label="Status">
                <select
                  data-testid="feedback-status-select"
                  value={detail.status}
                  disabled={saving}
                  onChange={(e) => void patch(detail.id, { status: e.target.value })}
                  className="w-full rounded-lg border border-line p-2 text-sm focus:border-primary focus:outline-none"
                >
                  {STATUSES.map((s) => <option key={s} value={s}>{STATUS_LABEL[s]}</option>)}
                </select>
              </Field>
              <Field label="Assigned to">
                <input
                  defaultValue={detail.assigned_to}
                  onBlur={(e) => { if (e.target.value !== detail.assigned_to) void patch(detail.id, { assigned_to: e.target.value }) }}
                  placeholder="(unassigned)"
                  className="w-full rounded-lg border border-line p-2 text-sm focus:border-primary focus:outline-none"
                />
              </Field>
              <Field label="Resolution notes">
                <textarea
                  defaultValue={detail.resolution_notes}
                  rows={3}
                  onBlur={(e) => { if (e.target.value !== detail.resolution_notes) void patch(detail.id, { resolution_notes: e.target.value }) }}
                  className="w-full resize-none rounded-lg border border-line p-2 text-sm focus:border-primary focus:outline-none"
                />
              </Field>
              {detail.updated_at && <p className="text-xs text-muted">Updated {when(detail.updated_at)}</p>}
            </div>

            {detail.status_history.length > 0 && (
              <div className="border-t border-line pt-3" data-testid="feedback-history">
                <div className="mb-1 text-xs font-medium uppercase tracking-wide text-muted">History</div>
                <ol className="space-y-1">
                  {detail.status_history.map((h, i) => (
                    <li key={i} className="text-xs text-muted">
                      <span className="text-body">{when(h.at)}</span> · {h.by}
                      {' · '}
                      {h.from ? `${STATUS_LABEL[h.from] || h.from} → ` : ''}
                      <span className="font-medium text-body">{STATUS_LABEL[h.to] || h.to}</span>
                      {h.note ? ` · ${h.note}` : ''}
                    </li>
                  ))}
                </ol>
              </div>
            )}
          </div>
        )}
      </SidePanel>
    </div>
  )
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="mb-1 text-xs font-medium uppercase tracking-wide text-muted">{label}</div>
      {children}
    </div>
  )
}
