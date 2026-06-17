// PreJobCardModal.tsx — WO v4.33 §3.4: the Pre-Job Card PREVIEW modal (replaces the v4.19-era
// send-confirm dialog with its hardcoded mock recipients). The §4-analysis 7-step flow in one
// scrollable modal: template auto-select (§0.6 Rhinorange-2.0-ranked, ACTIVE templates only —
// the §0.15 structural gate) → header/VIN → editable sections (inline text + add/delete row;
// notes + sub-items render per §0.5) → fridge mode → customer notes → Sales Rep + Planner
// dropdowns (§0.13 default from the costing; planner list = planner+admin per Q4) → Save Draft
// / Submit for Check (§0.8: gated on Body Gap populated unless explicitly waived). Submit
// drives the legacy production_jobs pre_job_sent transition server-side (§0.21) — the parents'
// onConfirm just refreshes. Sections editor is deliberately LIGHTER than the admin one (no
// section add/reorder — §3.4 step 3 scope); per-card mutations, not template mutations.
import { useCallback, useEffect, useMemo, useState } from 'react'
import { AlertTriangle, Check, FileText, Plus, Send, Trash2 } from 'lucide-react'
import { Modal } from '../../components/ui/overlays'
import { Spinner } from '../../components/ui/feedback'
import { useToast } from '../../components/ui/toast'
import { useAppData } from '../../store/AppDataContext'
import { apiGet, apiPatch, apiPost, handleApiError } from '../../lib/api'
import { dmy } from '../../lib/format'
import { compareTemplatesBySize } from '../../lib/templateSort'
import { ChassisModelSelect } from '../Chassis/ChassisModelSelect'
import type { Costing } from '../../data/costingsData'

interface SectionItem { text: string; note?: string | null; sub_items?: string[] | null; sap_item_code?: string | null }
interface Section { name: string; items: SectionItem[] }
interface TemplateOption { id: number; name: string; body_type: string; size_category: string | null; product_line: string; suggested: boolean }
interface UserOption { id: number; username: string; role: string }
interface FridgeOption {
  id: number; manufacturer: string; model: string; display_name: string
  mounting_drawing: string | null; cutout_width_mm: number | null; cutout_height_mm: number | null
}
interface PrejobCard {
  id: number; calculation_id: number; template_id: number | null
  body_description: string | null; chassis_make_model: string | null; vin_number: string | null
  body_gap_mm: number | null; body_gap_pending: boolean
  sections: Section[]
  fridge_ordering_mode: string | null; fridge_model: string | null; customer_notes: string | null
  sales_rep_user_id: number | null; sales_rep_signoff_at: string | null
  planner_user_id: number | null; planner_signoff_at: string | null
  status: string; sent_for_check_at: string | null; reject_reason: string | null
  cc_recipients: string | null
  quote_number: string | null; customer_name: string | null; template_name: string | null
  sales_rep_username: string | null; planner_username: string | null
}

const BODY_CLASSES = ['icecream', 'chiller', 'freezer', 'meathanger', 'bakery', 'explosive', 'trailer']

function bodyClassOf(costing: Costing): string | undefined {
  const low = (costing.body_type || '').toLowerCase()
  if (low.includes('trailer') || low.includes('body only')) return 'trailer'
  if (low.includes('dry freight')) return 'dry_freight'
  return BODY_CLASSES.find((c) => low.includes(c))
}

// WO v4.33.1 §3.5 — soft over-size warning. Derive the template's nominal length (mm) from its NAME
// ("13.8m Reefer Body" → 13800) — the BA's derive-from-name (no column, no migration). Returns null
// when the name has no parseable leading metre value (e.g. "Big …") → the caller skips silently.
function nominalLengthMm(name: string | null | undefined): number | null {
  const m = (name ?? '').match(/(\d+(?:\.\d+)?)\s*m\b/i)
  return m ? Math.round(parseFloat(m[1]) * 1000) : null
}

// Parse a baked "{N}mm o/a (l|w|h)" dimension out of the card's sections (the §0.5 dims line); the
// numbers are space-thousands ("5 400"). Returns null when no dims were baked (no calc dimensions).
function bakedDimMm(sections: Section[], axis: 'l' | 'w' | 'h'): number | null {
  const re = new RegExp(`(\\d[\\d\\s]*?)\\s*mm\\s*o/a\\s*\\(${axis}\\)`, 'i')
  for (const sec of sections ?? []) {
    for (const item of sec.items ?? []) {
      const m = (item.text ?? '').match(re)
      if (m) return parseInt(m[1].replace(/\s/g, ''), 10)
    }
  }
  return null
}

export function PreJobCardModal({
  costing,
  onClose,
  onConfirm,
}: {
  costing: Costing | null
  onClose: () => void
  onConfirm: (c: Costing) => void | Promise<void>
}) {
  const toast = useToast()
  const { hasPermission, isAdmin } = useAppData()
  const canCreate = isAdmin || hasPermission('prejob.create')

  const [loading, setLoading] = useState(false)
  const [busy, setBusy] = useState(false)
  const [card, setCard] = useState<PrejobCard | null>(null)
  const [templates, setTemplates] = useState<TemplateOption[]>([])
  const [templateId, setTemplateId] = useState<number | ''>('')
  const [salesReps, setSalesReps] = useState<UserOption[]>([])
  const [planners, setPlanners] = useState<UserOption[]>([])
  const [fridges, setFridges] = useState<FridgeOption[]>([])
  const [waiveGap, setWaiveGap] = useState(false)

  const liveCalcId = costing?.calculation_id ?? null

  const load = useCallback(async (c: Costing) => {
    setLoading(true)
    setWaiveGap(false)
    try {
      const cls = bodyClassOf(c)
      const [existing, tpls, reps, plns, frs] = await Promise.all([
        liveCalcId != null
          ? apiGet<PrejobCard | null>(`/api/prejob-cards/by-calculation/${liveCalcId}`)
          : Promise.resolve(null),
        apiGet<TemplateOption[]>(
          `/api/prejob-cards/templates?${cls ? `body_type=${cls}&` : ''}size_hint=${encodeURIComponent(c.body_type ?? '')}`),
        apiGet<UserOption[]>('/api/prejob-cards/user-options?kind=sales'),
        apiGet<UserOption[]>('/api/prejob-cards/user-options?kind=planner'),
        apiGet<FridgeOption[]>('/api/prejob-cards/fridge-options'),
      ])
      setCard(existing)
      setTemplates(tpls)
      setSalesReps(reps)
      setPlanners(plns)
      setFridges(frs)
      setTemplateId(tpls.find((t) => t.suggested)?.id ?? '')
    } catch (e) {
      handleApiError(e, toast.push)
    } finally {
      setLoading(false)
    }
  }, [liveCalcId, toast.push])

  useEffect(() => {
    if (costing) void load(costing)
    else { setCard(null); setTemplates([]) }
  }, [costing, load])

  // WO v4.33.1 §3.5 — over-size soft warning: costing length > 2× the selected template's nominal.
  // Non-blocking; skips silently (logs a one-liner) when either value isn't parseable.
  const sizeWarning = useMemo(() => {
    if (!card) return null
    const nominal = nominalLengthMm(card.template_name)
    if (nominal == null) {
      if (card.template_name) console.info(
        `[prejob-size] template "${card.template_name}" has no parseable nominal length — over-size warning skipped`)
      return null
    }
    const costL = bakedDimMm(card.sections, 'l')
    if (costL == null || costL <= 2 * nominal) return null   // no baked dims, or within range
    const w = bakedDimMm(card.sections, 'w')
    const h = bakedDimMm(card.sections, 'h')
    return `Costing dimensions (${costL}×${w ?? '—'}×${h ?? '—'}mm) appear larger than `
      + `"${card.template_name}" typical size — consider selecting a larger template?`
  }, [card])

  // WO v4.33.1 §3.6 — the suggested template stays on top; the rest sort human-numeric (size
  // buckets: 2.3m < 3.2m < mid < big < 15.5m), fixing the lexical "15.5m before 2.3m" order.
  const sortedTemplates = useMemo(() => {
    const suggested = templates.filter((t) => t.suggested)
    const rest = templates.filter((t) => !t.suggested).sort(compareTemplatesBySize)
    return [...suggested, ...rest]
  }, [templates])

  const patchCard = (p: Partial<PrejobCard>) => setCard((c) => (c ? { ...c, ...p } : c))
  const patchSections = (fn: (s: Section[]) => Section[]) =>
    setCard((c) => (c ? { ...c, sections: fn(structuredClone(c.sections)) } : c))

  // Scope addition — live fridge substitution. Mirrors the backend engine's exact semantics
  // for the 4 fridge tokens; a SWITCH (token already consumed) rewrites the previous
  // display_name occurrences so the "Provision for X fridge" line follows the dropdown.
  const fmtMm = (n: number | null) => (n == null ? '' : String(n).replace(/\B(?=(\d{3})+(?!\d))/g, ' '))
  const selectFridge = (f: FridgeOption | null) => {
    if (!card) return
    const prev = card.fridge_model
    const next = f?.display_name ?? null
    const replaceAll = (text: string): string => {
      let t = text
      if (next) {
        t = t.split('{{fridge_make}}').join(next)
        if (f?.mounting_drawing) t = t.split('{{fridge_drawing}}').join(f.mounting_drawing)
        if (f?.cutout_width_mm != null) t = t.split('{{fridge_cutout_width}}').join(fmtMm(f.cutout_width_mm))
        if (f?.cutout_height_mm != null) t = t.split('{{fridge_cutout_height}}').join(fmtMm(f.cutout_height_mm))
        if (prev && prev !== next) t = t.split(prev).join(next)   // switch: rewrite consumed token
      }
      return t
    }
    setCard((c) => c ? {
      ...c,
      fridge_model: next,
      sections: structuredClone(c.sections).map((s) => ({
        ...s,
        items: s.items.map((i) => ({
          ...i,
          text: replaceAll(i.text),
          note: i.note != null ? replaceAll(i.note) : i.note,
          sub_items: i.sub_items ? i.sub_items.map(replaceAll) : i.sub_items,
        })),
      })),
    } : c)
  }

  const fridgesByMaker = useMemo(() => {
    const g = new Map<string, FridgeOption[]>()
    for (const f of fridges) {
      const arr = g.get(f.manufacturer) ?? []
      arr.push(f)
      g.set(f.manufacturer, arr)
    }
    return [...g.entries()]
  }, [fridges])

  const createDraft = async () => {
    if (!costing || liveCalcId == null || templateId === '') return
    setBusy(true)
    try {
      setCard(await apiPost<PrejobCard>('/api/prejob-cards', {
        calculation_id: liveCalcId, template_id: templateId,
      }))
    } catch (e) { handleApiError(e, toast.push) } finally { setBusy(false) }
  }

  const saveDraft = async (silent = false): Promise<PrejobCard | null> => {
    if (!card) return null
    setBusy(true)
    try {
      const saved = await apiPatch<PrejobCard>(`/api/prejob-cards/${card.id}`, {
        body_description: card.body_description,
        chassis_make_model: card.chassis_make_model,
        vin_number: card.vin_number,
        body_gap_mm: card.body_gap_mm,
        sections: card.sections,
        fridge_ordering_mode: card.fridge_ordering_mode,
        fridge_model: card.fridge_model,
        customer_notes: card.customer_notes,
        sales_rep_user_id: card.sales_rep_user_id,
        planner_user_id: card.planner_user_id,
        cc_recipients: card.cc_recipients,
      })
      setCard(saved)
      if (!silent) toast.push({ kind: 'ok', message: 'Draft saved' })
      return saved
    } catch (e) {
      handleApiError(e, toast.push)
      return null
    } finally { setBusy(false) }
  }

  const openPdf = () => {
    if (card) window.open(`/api/prejob-cards/${card.id}/pdf`, '_blank')
  }

  const openEmail = async () => {
    if (!card) return
    try {
      const e = await apiGet<{ mailto: string }>(`/api/prejob-cards/${card.id}/email`)
      window.location.href = e.mailto                   // §0.11 — opens the user's mail client
    } catch (e) { handleApiError(e, toast.push) }
  }

  const submit = async () => {
    if (!card || !costing) return
    const saved = await saveDraft(true)                 // submit what's on screen
    if (!saved) return
    setBusy(true)
    try {
      const sent = await apiPost<PrejobCard>(
        `/api/prejob-cards/${saved.id}/submit-for-check`, { waive_body_gap: waiveGap })
      setCard(sent)
      toast.push({ kind: 'ok', message: 'Sent for check — opening your email client (§0.11)' })
      void openEmail()                                  // auto-open the prefilled mail draft
      await onConfirm(costing)
    } catch (e) { handleApiError(e, toast.push) } finally { setBusy(false) }
  }

  const editable = card?.status === 'draft' && canCreate
  const statusBanner = useMemo(() => {
    if (!card) return null
    if (card.status === 'draft' && card.reject_reason) {
      return { tone: 'amber', icon: AlertTriangle,
               text: `Rejected — back to draft. Reason: ${card.reject_reason}` }
    }
    if (card.status === 'sent_for_check') {
      return { tone: 'blue', icon: Send,
               text: 'Sent for check — awaiting Sales Rep + Planner sign-off (§3.5 pages).' }
    }
    if (card.status === 'pre_job_confirmed') {
      return { tone: 'green', icon: Check, text: 'Pre-Job CONFIRMED — both sign-offs captured.' }
    }
    return null
  }, [card])

  return (
    <Modal open={!!costing} onClose={onClose} className="max-w-3xl">
      {costing && (
        <div data-testid="prejob-card-modal" className="max-h-[80vh] overflow-y-auto pr-1">
          <div className="mb-3 flex items-center gap-2">
            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full bg-status-amber/15 text-status-amber">
              <FileText size={20} />
            </div>
            <div className="min-w-0">
              <h3 className="text-lg font-bold text-body">Pre-Job Card</h3>
              <p className="truncate text-xs text-muted">
                <span className="font-mono font-semibold">{card?.quote_number ?? costing.quote_number}</span>
                {' · '}{card?.customer_name ?? costing.customer_name} · internal sign-off (§0.2 — the customer never sees this)
              </p>
            </div>
          </div>

          {statusBanner && (
            <div className={`mb-3 flex items-start gap-2 rounded-md p-3 text-sm ${
              statusBanner.tone === 'amber' ? 'bg-status-amber/15 text-status-amber'
              : statusBanner.tone === 'green' ? 'bg-status-green/15 text-status-green'
              : 'bg-primary-light/50 text-primary'}`}>
              <statusBanner.icon size={16} className="mt-0.5 shrink-0" />
              <span data-testid="prejob-status-banner">{statusBanner.text}</span>
            </div>
          )}

          {sizeWarning && (
            <div data-testid="prejob-size-warning"
              className="mb-3 flex items-start gap-2 rounded-md bg-status-amber/15 p-3 text-sm text-status-amber">
              <AlertTriangle size={16} className="mt-0.5 shrink-0" />
              <span>{sizeWarning}</span>
            </div>
          )}

          {loading ? <Spinner /> : !card ? (
            /* ── Step 1: no card yet — template selection ── */
            liveCalcId == null ? (
              <p className="text-sm text-muted">
                This costing isn't linked to a live calculation — Pre-Job Cards need the live API.
              </p>
            ) : (
              <div data-testid="prejob-template-pick">
                <label className="text-xs font-semibold uppercase tracking-wide text-muted">
                  Template (suggested from the costing's body type — §0.6 prefers Rhinorange 2.0)
                </label>
                <select value={templateId}
                  onChange={(e) => setTemplateId(e.target.value ? Number(e.target.value) : '')}
                  className="mt-1 w-full rounded-md border border-line px-2 py-2 text-sm text-body"
                  data-testid="prejob-template-select">
                  <option value="">— choose a template —</option>
                  {sortedTemplates.map((t) => (
                    <option key={t.id} value={t.id}>
                      {t.suggested ? '★ ' : ''}{t.name}
                      {t.product_line !== 'standard' ? ` (${t.product_line === 'rhinorange_2_0' ? 'Rhinorange 2.0' : 'Rhinorange legacy'})` : ''}
                    </option>
                  ))}
                </select>
                {templates.length === 0 && (
                  <p className="mt-2 text-xs text-status-amber">
                    No APPROVED templates yet — approve some under Admin → Pre-Job templates first (§0.15).
                  </p>
                )}
                <div className="mt-4 flex justify-end gap-2">
                  <button onClick={onClose} className="rounded-md border border-line px-4 py-2 text-sm">Cancel</button>
                  <button onClick={() => void createDraft()} data-testid="prejob-create-draft"
                    disabled={!canCreate || busy || templateId === ''}
                    className="rounded-md bg-primary px-4 py-2 text-sm font-semibold text-white hover:bg-primary-dark disabled:opacity-50">
                    Create draft
                  </button>
                </div>
                {!canCreate && (
                  <p className="mt-2 text-right text-xs text-muted">Creating Pre-Job Cards needs the sales role (§0.3).</p>
                )}
              </div>
            )
          ) : (
            <div className="space-y-4">
              {/* ── Step 2: header ── */}
              <div className="grid gap-2 rounded-md border border-line p-3 md:grid-cols-2">
                <label className="text-xs text-muted md:col-span-2">Body description
                  <input value={card.body_description ?? ''} disabled={!editable}
                    onChange={(e) => patchCard({ body_description: e.target.value })}
                    className="mt-1 w-full rounded-md border border-line px-2 py-1.5 font-mono text-sm text-body disabled:bg-surface-alt" />
                </label>
                <label className="text-xs text-muted">Chassis (make / model)
                  {/* WO v4.34 §3.7 — DDM dropdown (was free-text); stops "Isuzu NPR 400" variants
                      fragmenting chassis_records + token substitution. */}
                  <ChassisModelSelect testid="prejob-chassis-make" value={card.chassis_make_model}
                    disabled={!editable} onChange={(v) => patchCard({ chassis_make_model: v })} />
                </label>
                <label className="text-xs text-muted">VIN Nr
                  <input value={card.vin_number ?? ''} disabled={!editable}
                    placeholder="17 characters, no I/O/Q (or leave blank until receive)"
                    onChange={(e) => patchCard({ vin_number: e.target.value || null })}
                    className="mt-1 w-full rounded-md border border-line px-2 py-1.5 font-mono text-sm text-body disabled:bg-surface-alt" />
                </label>
                <label className="text-xs text-muted">Body gap (mm) — §0.8
                  <div className="mt-1 flex items-center gap-2">
                    <input type="number" value={card.body_gap_mm ?? ''} disabled={!editable}
                      onChange={(e) => patchCard({ body_gap_mm: e.target.value === '' ? null : Number(e.target.value) })}
                      className="w-28 rounded-md border border-line px-2 py-1.5 text-sm text-body disabled:bg-surface-alt"
                      data-testid="prejob-body-gap" />
                    {card.body_gap_mm == null && (
                      <span className="rounded-full bg-status-amber/15 px-2 py-0.5 text-[11px] font-semibold text-status-amber">
                        Pending — awaiting chassis VCL
                      </span>
                    )}
                  </div>
                </label>
                <div className="text-xs text-muted">Template
                  <div className="mt-1 rounded-md bg-surface-alt px-2 py-1.5 text-sm text-body">{card.template_name ?? '—'}</div>
                </div>
              </div>

              {/* ── Step 3: sections (§0.5 — notes + sub-items render; inline edit + add/delete row) ── */}
              {card.sections.map((section, si) => (
                <div key={si} className="rounded-md border border-line p-3" data-testid="prejob-modal-section">
                  <div className="mb-2 text-sm font-bold uppercase tracking-wide text-body">{section.name}</div>
                  <ol className="space-y-1.5">
                    {section.items.map((item, ii) => (
                      <li key={ii} className="flex items-start gap-2">
                        <span className="mt-1.5 w-5 shrink-0 text-right font-mono text-xs text-muted">{ii + 1}</span>
                        <div className="min-w-0 flex-1">
                          <input value={item.text} disabled={!editable}
                            onChange={(e) => patchSections((s) => { s[si].items[ii].text = e.target.value; return s })}
                            className="w-full rounded-md border border-line px-2 py-1 text-sm text-body disabled:border-transparent disabled:bg-transparent" />
                          {item.note != null && (
                            <input value={item.note} disabled={!editable}
                              onChange={(e) => patchSections((s) => { s[si].items[ii].note = e.target.value; return s })}
                              className="mt-0.5 w-full rounded-md border border-dashed border-line px-2 py-0.5 text-xs italic text-muted disabled:border-transparent" />
                          )}
                          {(item.sub_items?.length ?? 0) > 0 && (
                            <ul className="ml-4 mt-0.5 list-disc space-y-0.5">
                              {item.sub_items!.map((s2, s2i) => (
                                <li key={s2i} className="text-xs text-body">
                                  {editable ? (
                                    <input value={s2}
                                      onChange={(e) => patchSections((s) => { s[si].items[ii].sub_items![s2i] = e.target.value; return s })}
                                      className="w-full rounded border border-dotted border-line px-1.5 py-0.5 text-xs" />
                                  ) : s2}
                                </li>
                              ))}
                            </ul>
                          )}
                        </div>
                        {editable && (
                          <button title="Delete row" className="mt-1 shrink-0 text-muted hover:text-status-red"
                            onClick={() => patchSections((s) => { s[si].items.splice(ii, 1); return s })}>
                            <Trash2 size={13} />
                          </button>
                        )}
                      </li>
                    ))}
                  </ol>
                  {editable && (
                    <button onClick={() => patchSections((s) => { s[si].items.push({ text: '' }); return s })}
                      className="mt-2 flex items-center gap-1 rounded-md border border-dashed border-line px-2 py-1 text-xs text-muted hover:text-body">
                      <Plus size={12} /> Add row
                    </button>
                  )}
                </div>
              ))}

              {/* ── Step 4: fridge ordering ── */}
              <div className="rounded-md border border-line p-3 text-sm">
                <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted">Fridge unit</div>
                {(['icb_orders', 'customer_supplies', 'none'] as const).map((m) => (
                  <label key={m} className="mr-4 inline-flex items-center gap-1.5 text-sm text-body">
                    <input type="radio" name="fridge" checked={card.fridge_ordering_mode === m} disabled={!editable}
                      onChange={() => patchCard({ fridge_ordering_mode: m })} />
                    {m === 'icb_orders' ? 'ICB orders' : m === 'customer_supplies' ? 'Customer supplies' : 'No fridge (cut-out only)'}
                  </label>
                ))}
                {card.fridge_ordering_mode === 'icb_orders' && (
                  /* Scope addition — fridge DDM dropdown (grouped by manufacturer); selecting
                     live-substitutes the {{fridge_*}} tokens in the sections above. */
                  <select value={card.fridge_model ?? ''} disabled={!editable} data-testid="prejob-fridge-select"
                    onChange={(e) => {
                      const f = fridges.find((x) => x.display_name === e.target.value) ?? null
                      selectFridge(f)
                    }}
                    className="mt-2 w-full rounded-md border border-line px-2 py-1.5 text-sm text-body disabled:bg-surface-alt">
                    <option value="">— select fridge unit —</option>
                    {fridgesByMaker.map(([maker, units]) => (
                      <optgroup key={maker} label={maker}>
                        {units.map((f) => (
                          <option key={f.id} value={f.display_name}>
                            {f.display_name}{f.cutout_width_mm ? ` · cutout ${f.cutout_width_mm}×${f.cutout_height_mm ?? '—'}` : ''}
                          </option>
                        ))}
                      </optgroup>
                    ))}
                  </select>
                )}
              </div>

              {/* ── Step 5: customer notes ── */}
              <label className="block text-xs text-muted">Customer-specific notes
                <textarea value={card.customer_notes ?? ''} rows={2} disabled={!editable}
                  onChange={(e) => patchCard({ customer_notes: e.target.value || null })}
                  className="mt-1 w-full rounded-md border border-line px-2 py-1.5 text-sm text-body disabled:bg-surface-alt" />
              </label>

              {/* ── Step 6: check signers (§0.3 / §0.13 / Q4) ── */}
              <div className="grid gap-2 md:grid-cols-2">
                <label className="text-xs text-muted">Sales Rep (check signer)
                  <select value={card.sales_rep_user_id ?? ''} disabled={!editable} data-testid="prejob-sales-rep"
                    onChange={(e) => patchCard({ sales_rep_user_id: e.target.value ? Number(e.target.value) : null })}
                    className="mt-1 w-full rounded-md border border-line px-2 py-1.5 text-sm text-body disabled:bg-surface-alt">
                    <option value="">— select —</option>
                    {salesReps.map((u) => <option key={u.id} value={u.id}>{u.username}</option>)}
                  </select>
                  {card.sales_rep_signoff_at && (
                    <span className="text-[11px] text-status-green">✓ signed {dmy(card.sales_rep_signoff_at)}</span>
                  )}
                </label>
                <label className="text-xs text-muted">Planner (check signer — planner or admin)
                  <select value={card.planner_user_id ?? ''} disabled={!editable} data-testid="prejob-planner"
                    onChange={(e) => patchCard({ planner_user_id: e.target.value ? Number(e.target.value) : null })}
                    className="mt-1 w-full rounded-md border border-line px-2 py-1.5 text-sm text-body disabled:bg-surface-alt">
                    <option value="">— select —</option>
                    {planners.map((u) => <option key={u.id} value={u.id}>{u.username} ({u.role})</option>)}
                  </select>
                  {card.planner_signoff_at && (
                    <span className="text-[11px] text-status-green">✓ signed {dmy(card.planner_signoff_at)}</span>
                  )}
                </label>
              </div>

              {/* ── CC recipients (Michael-approved addition) — lands in the mailto &cc= ── */}
              <label className="block text-xs text-muted">
                CC on the check email (comma-separated addresses — optional)
                <input value={card.cc_recipients ?? ''} disabled={!editable}
                  placeholder="e.g. burt@icecoldbodies.co.za, nadie@icecoldbodies.co.za"
                  data-testid="prejob-cc"
                  onChange={(e) => patchCard({ cc_recipients: e.target.value || null })}
                  className="mt-1 w-full rounded-md border border-line px-2 py-1.5 text-sm text-body disabled:bg-surface-alt" />
              </label>

              {/* ── Step 7: actions ── */}
              {editable && (
                <div className="flex flex-wrap items-center justify-end gap-3 border-t border-line pt-3">
                  {card.body_gap_mm == null && (
                    <label className="mr-auto inline-flex items-center gap-1.5 text-xs text-status-amber">
                      <input type="checkbox" checked={waiveGap} onChange={(e) => setWaiveGap(e.target.checked)}
                        data-testid="prejob-waive-gap" />
                      Submit without Body Gap (chassis not yet arrived — §0.8 waiver)
                    </label>
                  )}
                  <button onClick={onClose} className="rounded-md border border-line px-4 py-2 text-sm">Close</button>
                  <button onClick={openPdf} disabled={busy} data-testid="prejob-preview-pdf"
                    className="flex items-center gap-1 rounded-md border border-line px-4 py-2 text-sm font-semibold hover:bg-surface-alt disabled:opacity-50">
                    <FileText size={14} /> Preview PDF
                  </button>
                  <button onClick={() => void saveDraft()} disabled={busy} data-testid="prejob-save-draft"
                    className="rounded-md border border-line px-4 py-2 text-sm font-semibold hover:bg-surface-alt disabled:opacity-50">
                    Save Draft
                  </button>
                  <button onClick={() => void submit()} disabled={busy} data-testid="prejob-submit-check"
                    className="flex items-center gap-1 rounded-md bg-status-amber px-4 py-2 text-sm font-semibold text-white hover:opacity-90 disabled:opacity-50">
                    <Send size={14} /> Submit for Check
                  </button>
                </div>
              )}
              {!editable && (
                <div className="flex flex-wrap items-center justify-end gap-2 border-t border-line pt-3">
                  {/* §0.11 post-submit helpers: re-open the prefilled mail draft + grab the PDF
                      for manual attach (mailto cannot carry attachments — BA-corrected §0.11). */}
                  {(card.status === 'sent_for_check' || card.status === 'pre_job_confirmed') && (
                    <>
                      <button onClick={() => void openEmail()} data-testid="prejob-open-email"
                        className="flex items-center gap-1 rounded-md border border-line px-4 py-2 text-sm font-semibold hover:bg-surface-alt">
                        <Send size={14} /> Open email draft
                      </button>
                      <button onClick={openPdf} data-testid="prejob-download-pdf"
                        className="flex items-center gap-1 rounded-md border border-line px-4 py-2 text-sm font-semibold hover:bg-surface-alt">
                        <FileText size={14} /> Download PDF
                      </button>
                    </>
                  )}
                  <button onClick={onClose} className="rounded-md border border-line px-4 py-2 text-sm">Close</button>
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </Modal>
  )
}
