// PrejobSignoffPage.tsx — WO v4.33 §3.5: the Sales-Rep / Planner check sign-off pages
// (/prejob/{id}/signoff/{sales|planner} — deep-linkable from the §3.6 email). Read-only view
// of the populated Pre-Job Card (header, §0.5 sections with notes + sub-items, fridge mode,
// customer notes) + Sign off (attestation modal, §0.12) + Reject (reason modal, §0.14 — back
// to draft). Page gates per Q4: sales page = prejob.signoff_sales; planner page =
// prejob.signoff_planner — admin passes both (wildcard). The backend enforces the same gates.
import { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { AlertTriangle, Check, FileText, Send, X } from 'lucide-react'
import { Card, StatusPill } from '../../components/ui/primitives'
import { Modal } from '../../components/ui/overlays'
import { EmptyState, Spinner } from '../../components/ui/feedback'
import { useToast } from '../../components/ui/toast'
import { useAppData } from '../../store/AppDataContext'
import { apiGet, apiPost, handleApiError } from '../../lib/api'
import { dmy } from '../../lib/format'

interface SectionItem { text: string; note?: string | null; sub_items?: string[] | null }
interface Section { name: string; items: SectionItem[] }
interface PrejobCard {
  id: number; status: string
  body_description: string | null; chassis_make_model: string | null; vin_number: string | null
  body_gap_mm: number | null; body_gap_pending: boolean
  sections: Section[]
  fridge_ordering_mode: string | null; fridge_model: string | null; customer_notes: string | null
  sales_rep_username: string | null; sales_rep_signoff_at: string | null; sales_rep_attestation: string | null
  planner_username: string | null; planner_signoff_at: string | null; planner_attestation: string | null
  quote_number: string | null; customer_name: string | null; template_name: string | null
  reject_reason: string | null
}

const ROLE_META = {
  sales: { label: 'Sales Rep', perm: 'prejob.signoff_sales' as const,
           blurb: 'Confirm the commercial spec matches what was sold to the customer.' },
  planner: { label: 'Planner', perm: 'prejob.signoff_planner' as const,
             blurb: 'Confirm technical feasibility — chassis fits, body gap workable, buildable, slot bookable.' },
}

export function PrejobSignoffPage() {
  const { id, role } = useParams<{ id: string; role: string }>()
  const nav = useNavigate()
  const toast = useToast()
  const { hasPermission, isAdmin, apiMode, profile } = useAppData()
  const meta = role === 'sales' || role === 'planner' ? ROLE_META[role] : null
  const allowed = !!meta && (isAdmin || hasPermission(meta.perm))

  const [card, setCard] = useState<PrejobCard | null>(null)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [attestOpen, setAttestOpen] = useState(false)
  const [attestation, setAttestation] = useState('')
  const [confirmed, setConfirmed] = useState(false)        // §3.2 — required attestation checkbox
  const [rejectOpen, setRejectOpen] = useState(false)
  const [reason, setReason] = useState('')

  const load = useCallback(async () => {
    setLoading(true)
    try { setCard(await apiGet<PrejobCard>(`/api/prejob-cards/${id}`)) }
    catch (e) { handleApiError(e, toast.push); setCard(null) }
    finally { setLoading(false) }
  }, [id, toast.push])

  useEffect(() => { void load() }, [load])

  const mySignoffAt = useMemo(() => (card && role === 'sales'
    ? card.sales_rep_signoff_at : card?.planner_signoff_at) ?? null, [card, role])

  // WO v4.33.1 §3.2 — the fixed legal attestation statement (interpolated), mirroring the legacy
  // PreJobSignoffModal. Stored AS the attestation (with any optional notes appended) so the exact
  // confirmed text is the audit record, not just a re-derivable assumption.
  const boilerplate = card && meta
    ? `I, ${profile.name} (${meta.label}), confirm that I have reviewed the Pre-Job Card for quote `
      + `${card.quote_number ?? '—'} and verify the specifications are true and correct. This `
      + `electronic confirmation is recorded with timestamp and user identity.`
    : ''

  const doSignoff = async () => {
    if (!card || !meta || !confirmed) return
    setBusy(true)
    try {
      const notes = attestation.trim()
      const updated = await apiPost<PrejobCard>(
        `/api/prejob-cards/${card.id}/signoff/${role}`,
        { attestation: notes ? `${boilerplate}\n\n${notes}` : boilerplate })
      setCard(updated)
      setAttestOpen(false)
      toast.push({
        kind: 'ok',
        message: updated.status === 'pre_job_confirmed'
          ? 'Signed — both checks in: Pre-Job CONFIRMED'
          : 'Signed — awaiting the other check sign-off',
      })
    } catch (e) { handleApiError(e, toast.push) } finally { setBusy(false) }
  }

  const doReject = async () => {
    if (!card || !meta) return
    setBusy(true)
    try {
      const updated = await apiPost<PrejobCard>(
        `/api/prejob-cards/${card.id}/reject/${role}`, { reason })
      setCard(updated)
      setRejectOpen(false)
      toast.push({ kind: 'warn', message: 'Rejected — returned to draft for Internal Sales' })
    } catch (e) { handleApiError(e, toast.push) } finally { setBusy(false) }
  }

  if (!meta) {
    return <div className="p-4"><EmptyState title="Unknown sign-off role"
      hint="Valid pages are /prejob/{id}/signoff/sales and /prejob/{id}/signoff/planner." /></div>
  }
  if (apiMode !== 'loading' && !allowed) {
    return <div className="p-4"><EmptyState title={`${meta.label} sign-off is role-gated`}
      hint={`This page needs ${meta.perm} (or admin — §0.3).`} /></div>
  }

  return (
    <div className="mx-auto max-w-3xl p-4" data-testid="prejob-signoff-page">
      {loading ? <Spinner /> : !card ? (
        <EmptyState title="Pre-Job Card not found" hint="The link may be stale." />
      ) : (
        <>
          <div className="mb-3 flex flex-wrap items-center gap-2">
            <div className="flex h-10 w-10 items-center justify-center rounded-full bg-primary-light text-primary">
              <FileText size={20} />
            </div>
            <div className="min-w-0 flex-1">
              <h1 className="text-lg font-bold text-body">
                Pre-Job Card — {meta.label} check
              </h1>
              <p className="text-xs text-muted">
                <span className="font-mono font-semibold">{card.quote_number ?? '—'}</span>
                {' · '}{card.customer_name ?? '—'} · {card.template_name ?? '—'} · {meta.blurb}
              </p>
            </div>
            <StatusPill
              status={card.status === 'pre_job_confirmed' ? 'GREEN'
                : card.status === 'sent_for_check' ? 'AMBER' : 'RED'}
              label={card.status.replace(/_/g, ' ')}
            />
            <button onClick={() => window.open(`/api/prejob-cards/${card.id}/pdf`, '_blank')}
              data-testid="prejob-page-pdf"
              className="rounded-md border border-line px-3 py-1.5 text-sm hover:bg-surface-alt">
              Download PDF
            </button>
          </div>

          {card.status === 'draft' && card.reject_reason && (
            <div className="mb-3 flex items-start gap-2 rounded-md bg-status-amber/15 p-3 text-sm text-status-amber">
              <AlertTriangle size={16} className="mt-0.5 shrink-0" />
              <span>Back at draft — {card.reject_reason}</span>
            </div>
          )}

          {/* Read-only card body */}
          <Card className="mb-3">
            <div className="mb-2 font-mono text-sm font-semibold text-body">{card.body_description ?? '—'}</div>
            <div className="grid gap-1 text-sm text-body md:grid-cols-3">
              <span><span className="text-xs uppercase text-muted">Chassis </span>{card.chassis_make_model ?? '—'}</span>
              <span><span className="text-xs uppercase text-muted">VIN </span><span className="font-mono">{card.vin_number ?? 'TBD'}</span></span>
              <span><span className="text-xs uppercase text-muted">Body gap </span>
                {card.body_gap_mm != null ? `${card.body_gap_mm}mm`
                  : <span className="text-status-amber">Pending — awaiting chassis VCL</span>}
              </span>
            </div>
          </Card>

          {card.sections.map((s, si) => (
            <Card key={si} className="mb-3">
              <div className="mb-1.5 text-sm font-bold uppercase tracking-wide text-body">{s.name}</div>
              <ol className="space-y-1">
                {s.items.map((i, ii) => (
                  <li key={ii} className="flex gap-2 text-sm text-body">
                    <span className="w-5 shrink-0 text-right font-mono text-xs text-muted">{ii + 1}</span>
                    <div className="min-w-0">
                      <div>{i.text}</div>
                      {i.note && <div className="text-xs italic text-muted">Note: {i.note}</div>}
                      {(i.sub_items?.length ?? 0) > 0 && (
                        <ul className="ml-4 list-disc text-xs text-body">
                          {i.sub_items!.map((x, xi) => <li key={xi}>{x}</li>)}
                        </ul>
                      )}
                    </div>
                  </li>
                ))}
              </ol>
            </Card>
          ))}

          <Card className="mb-3 text-sm">
            <div className="grid gap-2 md:grid-cols-2">
              <div>
                <div className="text-xs font-semibold uppercase tracking-wide text-muted">Fridge</div>
                {card.fridge_ordering_mode === 'icb_orders' ? `ICB orders — ${card.fridge_model ?? 'model TBC'}`
                  : card.fridge_ordering_mode === 'customer_supplies' ? 'Customer supplies'
                  : card.fridge_ordering_mode === 'none' ? 'No fridge (cut-out only)' : '—'}
              </div>
              <div>
                <div className="text-xs font-semibold uppercase tracking-wide text-muted">Customer notes</div>
                {card.customer_notes || '—'}
              </div>
            </div>
          </Card>

          {/* Sign-off state */}
          <Card className="mb-4 text-sm">
            <div className="grid gap-2 md:grid-cols-2">
              {([['Sales Rep', card.sales_rep_username, card.sales_rep_signoff_at, card.sales_rep_attestation],
                 ['Planner', card.planner_username, card.planner_signoff_at, card.planner_attestation]] as const)
                .map(([label, who, at, att]) => (
                <div key={label} className="rounded-md bg-surface-alt p-2.5">
                  <div className="text-xs font-semibold uppercase tracking-wide text-muted">{label} check</div>
                  {at ? (
                    <div className="text-status-green">
                      <Check size={13} className="mr-1 inline" />
                      {who ?? '—'} · {dmy(at)}
                      {att && <div className="mt-0.5 text-xs italic text-muted">“{att}”</div>}
                    </div>
                  ) : <div className="text-muted">awaiting sign-off{who ? ` (assigned: ${who})` : ''}</div>}
                </div>
              ))}
            </div>
          </Card>

          {/* Actions */}
          {card.status === 'sent_for_check' && !mySignoffAt && (
            <div className="flex justify-end gap-2">
              <button onClick={() => { setReason(''); setRejectOpen(true) }} data-testid="prejob-reject-btn"
                className="flex items-center gap-1 rounded-md border border-status-red px-4 py-2 text-sm font-semibold text-status-red hover:bg-status-red/10">
                <X size={14} /> Reject
              </button>
              <button onClick={() => { setAttestation(''); setConfirmed(false); setAttestOpen(true) }} data-testid="prejob-signoff-btn"
                className="flex items-center gap-1 rounded-md bg-primary px-4 py-2 text-sm font-semibold text-white hover:bg-primary-dark">
                <Check size={14} /> Sign off as {meta.label}
              </button>
            </div>
          )}
          {card.status === 'sent_for_check' && mySignoffAt && (
            <p className="text-right text-sm text-status-green">✓ Your {meta.label} sign-off is in — awaiting the other check.</p>
          )}
          {card.status === 'pre_job_confirmed' && (
            <div className="flex items-center justify-end gap-3">
              <span className="text-sm font-semibold text-status-green">Pre-Job CONFIRMED — both checks captured.</span>
              <button onClick={() => nav('/costings')} className="rounded-md border border-line px-3 py-1.5 text-sm">To Costings</button>
            </div>
          )}

          {/* Attestation modal (§0.12) */}
          <Modal open={attestOpen} onClose={() => setAttestOpen(false)} className="max-w-md">
            <h3 className="mb-2 text-base font-bold text-body">{meta.label} sign-off attestation</h3>
            {/* §3.2 — fixed legal boilerplate + REQUIRED confirmation checkbox (legacy
                PreJobSignoffModal pattern) + optional notes below; Sign off gated on the checkbox. */}
            <p data-testid="prejob-attestation-boilerplate"
              className="mb-3 rounded-md border border-line bg-surface-alt p-2 text-xs leading-relaxed text-body">
              {boilerplate}
            </p>
            <label className="mb-3 flex cursor-pointer items-start gap-2 text-sm text-body">
              <input type="checkbox" data-testid="prejob-attestation-checkbox" checked={confirmed}
                onChange={(e) => setConfirmed(e.target.checked)} className="mt-0.5 h-4 w-4 shrink-0" />
              <span>I confirm the statement above and authorise this sign-off to be recorded against my user account.</span>
            </label>
            <label className="block text-xs text-muted">Additional notes (optional)
              <textarea value={attestation} rows={2} data-testid="prejob-attestation"
                onChange={(e) => setAttestation(e.target.value)}
                className="mt-1 w-full rounded-md border border-line px-2 py-1.5 text-sm text-body" />
            </label>
            <div className="mt-3 flex justify-end gap-2">
              <button onClick={() => setAttestOpen(false)} className="rounded-md border border-line px-3 py-1.5 text-sm">Cancel</button>
              <button onClick={() => void doSignoff()} disabled={busy || !confirmed}
                data-testid="prejob-attestation-confirm"
                className="flex items-center gap-1 rounded-md bg-primary px-3 py-1.5 text-sm font-semibold text-white disabled:opacity-50">
                <Send size={13} /> Sign off
              </button>
            </div>
          </Modal>

          {/* Reject modal (§0.14) */}
          <Modal open={rejectOpen} onClose={() => setRejectOpen(false)} className="max-w-md">
            <h3 className="mb-2 text-base font-bold text-body">Reject — return to draft</h3>
            <textarea value={reason} rows={3} autoFocus data-testid="prejob-reject-reason"
              placeholder="What must Internal Sales fix before re-submitting?"
              onChange={(e) => setReason(e.target.value)}
              className="w-full rounded-md border border-line px-2 py-1.5 text-sm text-body" />
            <div className="mt-3 flex justify-end gap-2">
              <button onClick={() => setRejectOpen(false)} className="rounded-md border border-line px-3 py-1.5 text-sm">Cancel</button>
              <button onClick={() => void doReject()} disabled={busy || !reason.trim()}
                data-testid="prejob-reject-confirm"
                className="rounded-md bg-status-red px-3 py-1.5 text-sm font-semibold text-white disabled:opacity-50">
                Reject
              </button>
            </div>
          </Modal>
        </>
      )}
    </div>
  )
}
