// WO v4.37 §3.2 — native React Cost Calculator (replaces the /mes/calculator
// iframe). Core flow: pick a body type → set dimensions + body options → live
// POST /api/calculate (debounced) → cost summary + BOM table. The backend is the
// already-native calc engine (calculator.py); this layer only assembles inputs
// and renders the result. Save / version / customer flow lands in the §3.2 save
// increment; insulation copy-on-switch + optional-extras + per-row overrides are
// follow-ups (the engine already gates server-side from body_option_selections).
import { Fragment, useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Calculator, Loader2, RadioTower, AlertCircle } from 'lucide-react'
import { useToast } from '../../../components/ui/toast'
import { useTrailers, useTrailerBom, useLiveCalc, loadCalculation } from './useCalculator'
import { SaveBar } from './SaveBar'
import type { BomRow, CalcItem, Dimensions, BodyOptionSelections, CalcRequest, LoadedCalculation } from './types'

const DEFAULT_DIMS: Dimensions = {
  length: 13.6, width: 2.5, height: 2.7,
  floor_thickness: 0.028, panel_thickness: 0.063, insulation_thickness: 0.076,
  num_axles: 3, num_doors: 2,
}

const RATIO_OPTIONS: { label: string; value: string }[] = [
  { label: 'No ratio', value: '' },
  { label: '30%', value: '0.3' }, { label: '40%', value: '0.4' },
  { label: '50%', value: '0.5' }, { label: '60%', value: '0.6' },
  { label: '70%', value: '0.7' },
]

const R = (n: number | null | undefined): string =>
  'R ' + (n ?? 0).toLocaleString('en-ZA', { minimumFractionDigits: 2, maximumFractionDigits: 2 })

/** Group is_body_option rows by group → subgroup. A subgroup with >1 row renders
 *  as a radio set (mutually exclusive); otherwise independent checkboxes. */
interface OptGroup { group: string; subgroups: { subgroup: string; rows: BomRow[]; radio: boolean }[] }
function groupBodyOptions(bom: BomRow[]): OptGroup[] {
  const byGroup = new Map<string, Map<string, BomRow[]>>()
  for (const row of bom) {
    if (!row.is_body_option) continue
    const g = (row.body_option_group || 'OPTIONS').toUpperCase()
    const sg = (row.body_option_subgroup || '').toUpperCase()
    if (!byGroup.has(g)) byGroup.set(g, new Map())
    const subMap = byGroup.get(g)!
    if (!subMap.has(sg)) subMap.set(sg, [])
    subMap.get(sg)!.push(row)
  }
  return [...byGroup.entries()].map(([group, subMap]) => ({
    group,
    subgroups: [...subMap.entries()].map(([subgroup, rows]) => ({
      subgroup, rows, radio: rows.length > 1 && subgroup !== '',
    })),
  }))
}

const fieldCls = 'w-full rounded-md border border-line bg-white px-2 py-1.5 text-sm text-body focus:border-primary focus:outline-none'
const labelCls = 'mb-1 block text-[11px] font-semibold uppercase tracking-wide text-muted'

export function CostCalculator() {
  const { trailers, loading: trLoading, error: trError } = useTrailers()
  const [trailerId, setTrailerId] = useState<number | null>(null)
  const { bom, loading: bomLoading } = useTrailerBom(trailerId)
  const [dims, setDims] = useState<Dimensions>(DEFAULT_DIMS)
  const [sel, setSel] = useState<BodyOptionSelections>({})
  const [margin, setMargin] = useState(0)
  const [ratio, setRatio] = useState('')
  const [discKind, setDiscKind] = useState<'percent' | 'amount' | ''>('')
  const [discInput, setDiscInput] = useState(0)
  const [overrides, setOverrides] = useState<Record<string, number>>({})  // bom_id → quote-only unit price
  const [optionalEnabled, setOptionalEnabled] = useState<Set<number>>(new Set())  // enabled optional bom_section_ids
  const [insThickness, setInsThickness] = useState<Record<string, number>>({})  // bom_id → insulation thickness override (m)
  const { result, calculating, error: calcError, calculate } = useLiveCalc()
  // WO v4.37 §3.2 addendum — edit-reopen state.
  const [searchParams] = useSearchParams()
  const toast = useToast()
  const [editRecordId, setEditRecordId] = useState<number | null>(null)
  const [baseEtag, setBaseEtag] = useState<string | null>(null)
  const [loadedVersion, setLoadedVersion] = useState<number | null>(null)
  const [editCustomerId, setEditCustomerId] = useState<number | null>(null)
  const [pendingEdit, setPendingEdit] = useState<LoadedCalculation | null>(null)

  // Edit-reopen: ?edit=<id> loads the saved costing; the seed effect re-hydrates
  // the form once that trailer's BOM arrives.
  useEffect(() => {
    const editId = searchParams.get('edit')
    if (!editId) return
    let alive = true
    loadCalculation(Number(editId))
      .then((data) => {
        if (!alive) return
        setEditRecordId(data.id)
        setBaseEtag(data.etag ?? null)
        setLoadedVersion(data.version ?? null)
        setEditCustomerId(data.customer_id ?? null)
        setPendingEdit(data)
        setTrailerId(data.trailer_type_id)
      })
      .catch(() => { if (alive) toast.push({ kind: 'error', message: 'Could not load that costing to edit.' }) })
    return () => { alive = false }
  }, [searchParams, toast])

  // Default to the first body type once the list loads (skipped in edit-mode —
  // the edit-load picks the saved trailer).
  useEffect(() => {
    if (searchParams.get('edit')) return
    if (trailerId == null && trailers.length) setTrailerId(trailers[0].id)
  }, [trailers, trailerId, searchParams])

  // Seed defaults when a trailer's BOM loads — OR re-hydrate from a saved costing
  // when reopening for edit (WO v4.37 §3.2 addendum).
  useEffect(() => {
    if (!bom.length) return
    if (pendingEdit && pendingEdit.trailer_type_id === trailerId) {
      const e = pendingEdit
      if (e.dimensions) setDims((d) => ({ ...d, ...e.dimensions }))
      setSel(e.body_option_selections ?? {})
      setMargin(e.profit_margin ?? 0)
      setRatio(e.ratio_value != null ? String(e.ratio_value) : '')
      setDiscKind((e.discount_kind ?? '') as 'percent' | 'amount' | '')
      setDiscInput(e.discount_input ?? 0)
      setOverrides(e.overrides ?? {})
      setOptionalEnabled(new Set(e.optional_sections_enabled ?? []))
      // saved body_variable_overrides are keyed by material name → map back to bom_id
      const bv = e.body_variable_overrides ?? {}
      const ins: Record<string, number> = {}
      for (const row of bom) if (row.material_name in bv) ins[String(row.id)] = bv[row.material_name]
      setInsThickness(ins)
      setPendingEdit(null)  // one-shot re-hydration
      return
    }
    const tr = trailers.find((t) => t.id === trailerId)
    setDims((d) => ({
      ...d,
      length: tr?.default_length ?? d.length,
      width: tr?.default_width ?? d.width,
      height: tr?.default_height ?? d.height,
    }))
    const defaults: BodyOptionSelections = {}
    for (const row of bom) if (row.is_body_option) defaults[String(row.id)] = !!row.body_option_default
    setSel(defaults)
    setOverrides({})  // a new body template clears any prior quote-only price overrides
    setOptionalEnabled(new Set())  // optional sections default OFF
    setInsThickness({})  // thickness overrides reset to the template defaults
  }, [bom, trailerId, trailers, pendingEdit])

  // Insulation thickness → body_variable_overrides (keyed by material name; the
  // backend resolves them in _build_body_variables). Per-quote, NOT a template
  // PUT — avoids mutating the shared body template for every other estimator.
  const bodyVarOverrides = useMemo(() => {
    const out: Record<string, number> = {}
    for (const row of bom) {
      const t = insThickness[String(row.id)]
      if (t !== undefined && row.material_name) out[row.material_name] = t
    }
    return out
  }, [bom, insThickness])

  const req = useMemo<CalcRequest | null>(() => {
    if (trailerId == null) return null
    return {
      trailer_type_id: trailerId,
      dimensions: dims,
      profit_margin: margin,
      overrides,
      body_option_selections: sel,
      body_variable_overrides: bodyVarOverrides,
      optional_sections_enabled: [...optionalEnabled],
      chassis: { enabled: false },
      ratio_value: ratio ? Number(ratio) : null,
      ratio_label: ratio ? `${Math.round(Number(ratio) * 100)}%` : null,
      discount_kind: discKind || null,
      discount_input: discKind ? discInput : null,
    }
  }, [trailerId, dims, margin, sel, ratio, discKind, discInput, overrides, optionalEnabled, bodyVarOverrides])

  // Debounced live recalc on any input change.
  useEffect(() => { if (req) calculate(req) }, [req, calculate])

  const optGroups = useMemo(() => groupBodyOptions(bom), [bom])
  const dimsValid = dims.length > 0 && dims.width > 0 && dims.height > 0

  // BOM grouped by category for the table; optional categories carry an "include"
  // toggle (→ optional_sections_enabled). sectionId is the category's bom_section_id.
  const bomGroups = useMemo(() => {
    const order: string[] = []
    const map = new Map<string, CalcItem[]>()
    for (const it of result?.items ?? []) {
      if (!map.has(it.category)) { map.set(it.category, []); order.push(it.category) }
      map.get(it.category)!.push(it)
    }
    return order.map((cat) => {
      const items = map.get(cat)!
      return {
        cat, items,
        optional: items.some((i) => i.section_is_optional),
        sectionId: items.find((i) => i.bom_section_id != null)?.bom_section_id ?? null,
      }
    })
  }, [result])
  const toggleOptional = (sectionId: number) =>
    setOptionalEnabled((s) => { const n = new Set(s); n.has(sectionId) ? n.delete(sectionId) : n.add(sectionId); return n })

  // Both-zero guard (BA §3.2): block save when an insulation pair has no thickness
  // on either side — the silent operator error worth a hard stop.
  const insBlock = useMemo(() => {
    const eff = (row: BomRow) => insThickness[String(row.id)] ?? (row.variable_value ?? 0)
    for (const g of optGroups) for (const sg of g.subgroups) {
      if (sg.rows.length === 2 && sg.rows.some((r) => /EPS/i.test(r.material_name)) && sg.rows.some((r) => /PU/i.test(r.material_name))
          && sg.rows.every((r) => eff(r) <= 0)) return true
    }
    return false
  }, [optGroups, insThickness])

  const setSelExclusive = (rows: BomRow[], picked: number) =>
    setSel((s) => {
      const next = { ...s }
      for (const r of rows) next[String(r.id)] = r.id === picked
      return next
    })

  const effThick = (row: BomRow) => insThickness[String(row.id)] ?? (row.variable_value ?? 0)
  const isInsulationPair = (rows: BomRow[]) =>
    rows.length === 2 && rows.some((r) => /EPS/i.test(r.material_name)) && rows.some((r) => /PU/i.test(r.material_name))
  // Copy-on-switch: picking the other insulation type carries the sibling's
  // thickness onto the picked row and zeroes the sibling (EPS↔PU parity).
  const copyOnSwitch = (rows: BomRow[], pickedId: number) => {
    const sibling = rows.find((r) => r.id !== pickedId)
    if (!sibling) return
    const sibT = effThick(sibling)
    setInsThickness((t) => ({ ...t, [String(pickedId)]: sibT, [String(sibling.id)]: 0 }))
  }

  const headline = result?.net_total ?? result?.selling_price ?? result?.grand_total ?? 0

  return (
    <div className="flex h-[calc(100vh-96px)] flex-col">
      {/* header */}
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line bg-surface-alt px-4 py-2 text-sm">
        <div className="flex items-center gap-2">
          <Calculator size={15} className="text-primary" />
          <span className="font-semibold text-body">New Costing</span>
          <span className="rounded-full bg-status-green/15 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide text-status-green">
            Native
          </span>
          {calculating && (
            <span className="flex items-center gap-1 text-xs text-muted">
              <Loader2 size={12} className="animate-spin" /> recalculating…
            </span>
          )}
        </div>
        {result?.trailer_name && <span className="text-xs text-muted">{result.trailer_name}</span>}
      </div>

      <div className="grid flex-1 grid-cols-1 gap-0 overflow-hidden lg:grid-cols-[minmax(320px,420px)_1fr]">
        {/* ── LEFT: configuration ─────────────────────────────────────────── */}
        <div className="overflow-y-auto border-r border-line bg-white p-4">
          <div className="mb-4">
            <label className={labelCls}>Body type</label>
            {trLoading ? (
              <div className="flex items-center gap-2 text-sm text-muted"><Loader2 size={14} className="animate-spin" /> Loading…</div>
            ) : trError ? (
              <div className="text-sm text-status-red">{trError}</div>
            ) : (
              <select className={fieldCls} value={trailerId ?? ''} onChange={(e) => setTrailerId(Number(e.target.value))}>
                {trailers.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
              </select>
            )}
          </div>

          <div className="mb-4 grid grid-cols-3 gap-2">
            {(['length', 'width', 'height'] as const).map((k) => (
              <div key={k}>
                <label className={labelCls}>{k} (m)</label>
                <input
                  type="number" step="0.01" min="0" className={fieldCls}
                  value={dims[k]}
                  onChange={(e) => setDims((d) => ({ ...d, [k]: Number(e.target.value) }))}
                />
              </div>
            ))}
          </div>
          {!dimsValid && (
            <div className="mb-3 flex items-center gap-1.5 text-xs text-status-amber">
              <AlertCircle size={13} /> All three dimensions must be greater than zero.
            </div>
          )}

          {/* body options */}
          {bomLoading ? (
            <div className="flex items-center gap-2 py-4 text-sm text-muted"><Loader2 size={14} className="animate-spin" /> Loading body template…</div>
          ) : (
            optGroups.map((g) => (
              <div key={g.group} className="mb-4">
                <div className="mb-1.5 text-xs font-bold uppercase tracking-wide text-body">{g.group}</div>
                {g.subgroups.map((sg) => {
                  const isIns = isInsulationPair(sg.rows)
                  const bothZero = isIns && sg.rows.every((r) => effThick(r) <= 0)
                  return (
                    <div key={sg.subgroup || g.group} className={`mb-2 rounded-md border p-2 ${bothZero ? 'border-status-red bg-status-red/5' : 'border-line'}`}>
                      {sg.subgroup && <div className="mb-1 text-[10px] font-semibold uppercase text-muted">{sg.subgroup}</div>}
                      <div className="flex flex-col gap-1">
                        {sg.rows.map((row) => {
                          const on = !!sel[String(row.id)]
                          return (
                            <label key={row.id} className="flex cursor-pointer items-center gap-2 text-sm text-body">
                              <input
                                type={sg.radio ? 'radio' : 'checkbox'}
                                name={sg.radio ? `${g.group}-${sg.subgroup}` : undefined}
                                checked={on}
                                onChange={() => {
                                  if (sg.radio) { setSelExclusive(sg.rows, row.id); if (isIns) copyOnSwitch(sg.rows, row.id) }
                                  else setSel((s) => ({ ...s, [String(row.id)]: !on }))
                                }}
                              />
                              <span className="flex-1">{row.material_name}</span>
                              {isIns ? (
                                <input
                                  type="number" step="0.001" min="0" title="Insulation thickness (m)"
                                  className="w-16 rounded border border-line px-1 py-0.5 text-right text-xs tabular-nums focus:border-primary focus:outline-none"
                                  value={effThick(row)}
                                  onChange={(e) => setInsThickness((t) => ({ ...t, [String(row.id)]: Number(e.target.value) }))}
                                />
                              ) : (row.variable_value != null && row.variable_value > 0 ? (
                                <span className="text-[11px] text-muted">({row.variable_value} m)</span>
                              ) : null)}
                            </label>
                          )
                        })}
                      </div>
                      {bothZero && <div className="mt-1 text-[11px] font-semibold text-status-red">⚠ Set a thickness on EPS or PU — both are zero.</div>}
                    </div>
                  )
                })}
              </div>
            ))
          )}

          {/* margin / ratio / discount */}
          <div className="mb-3 grid grid-cols-2 gap-2 border-t border-line pt-3">
            <div>
              <label className={labelCls}>Margin %</label>
              <input type="number" step="0.5" min="0" className={fieldCls} value={margin} onChange={(e) => setMargin(Number(e.target.value))} />
            </div>
            <div>
              <label className={labelCls}>Ratio</label>
              <select className={fieldCls} value={ratio} onChange={(e) => setRatio(e.target.value)}>
                {RATIO_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
              </select>
            </div>
          </div>
          <div className="grid grid-cols-2 gap-2">
            <div>
              <label className={labelCls}>Discount</label>
              <select className={fieldCls} value={discKind} onChange={(e) => setDiscKind(e.target.value as 'percent' | 'amount' | '')}>
                <option value="">None</option>
                <option value="percent">Percent %</option>
                <option value="amount">Amount R</option>
              </select>
            </div>
            <div>
              <label className={labelCls}>{discKind === 'amount' ? 'Amount (R)' : 'Percent (%)'}</label>
              <input type="number" step="0.01" min="0" disabled={!discKind} className={fieldCls} value={discInput} onChange={(e) => setDiscInput(Number(e.target.value))} />
            </div>
          </div>
        </div>

        {/* ── RIGHT: summary + BOM ────────────────────────────────────────── */}
        <div className="overflow-y-auto bg-surface-alt p-4">
          {calcError && (
            <div className="mb-3 flex items-center gap-1.5 rounded-md bg-status-amber/10 px-3 py-2 text-sm text-status-amber">
              <AlertCircle size={14} /> {calcError}
            </div>
          )}

          {/* summary */}
          <div className="mb-4 rounded-lg border border-line bg-white p-4">
            <div className="mb-2 flex items-center gap-1.5 text-xs font-bold uppercase tracking-wide text-muted">
              <RadioTower size={13} className="text-primary" /> Cost summary
            </div>
            <SummaryRow label="Materials cost" value={R(result?.materials_total ?? result?.grand_total)} />
            {!!result?.profit_amount && <SummaryRow label={`Margin (${result.profit_margin ?? 0}%)`} value={R(result.profit_amount)} />}
            {!!result?.ratio_amount && <SummaryRow label={`Ratio (${result.ratio_label ?? ''})`} value={R(result.ratio_amount)} />}
            {!!result?.selling_price && <SummaryRow label="Selling price" value={R(result.selling_price)} />}
            {!!result?.discount_amount && result.discount_amount > 0 && (
              <SummaryRow label="Discount" value={`- ${R(result.discount_amount)}`} amber />
            )}
            <div className="mt-2 flex items-center justify-between border-t border-line pt-2">
              <span className="text-sm font-bold text-body">Total</span>
              <span className="text-lg font-bold text-primary">{R(headline)}</span>
            </div>
            {result?.cost_per_sqm != null && (
              <div className="mt-1 text-right text-[11px] text-muted">{R(result.cost_per_sqm)} / m²</div>
            )}
          </div>

          {insBlock && (
            <div className="mt-4 flex items-center gap-1.5 rounded-md bg-status-red/10 px-3 py-2 text-sm font-semibold text-status-red">
              <AlertCircle size={14} /> An insulation pair has no thickness on either side — set EPS or PU before saving.
            </div>
          )}
          <SaveBar
            req={req}
            disabled={insBlock}
            edit={editRecordId != null ? { recordId: editRecordId, baseEtag, version: loadedVersion, customerId: editCustomerId } : null}
          />

          {/* BOM table */}
          <div className="rounded-lg border border-line bg-white">
            <div className="border-b border-line px-3 py-2 text-xs font-bold uppercase tracking-wide text-muted">
              Bill of materials
            </div>
            {!result ? (
              <div className="p-4 text-sm text-muted">Configure a body type to see the breakdown.</div>
            ) : (
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-line text-left text-[11px] uppercase text-muted">
                    <th className="px-3 py-1.5 font-semibold">Material</th>
                    <th className="px-3 py-1.5 text-right font-semibold">Qty</th>
                    <th className="px-3 py-1.5 font-semibold">Unit</th>
                    <th className="px-3 py-1.5 text-right font-semibold">Unit&nbsp;R</th>
                    <th className="px-3 py-1.5 text-right font-semibold">Line&nbsp;R</th>
                  </tr>
                </thead>
                <tbody>
                  {bomGroups.map((g) => (
                    <Fragment key={g.cat}>
                      <tr className="bg-surface-alt/70">
                        <td colSpan={5} className="px-3 py-1">
                          <div className="flex items-center justify-between">
                            <span className={`text-[11px] font-bold uppercase tracking-wide ${g.optional ? 'text-status-amber' : 'text-body'}`}>{g.cat}</span>
                            {g.optional && g.sectionId != null && (
                              <label className="flex cursor-pointer items-center gap-1 text-[10px] font-semibold uppercase text-muted">
                                <input type="checkbox" checked={optionalEnabled.has(g.sectionId)} onChange={() => toggleOptional(g.sectionId!)} /> include
                              </label>
                            )}
                          </div>
                        </td>
                      </tr>
                      {g.items.map((it, i) => (
                        <tr
                          key={`${it.bom_id}-${i}`}
                          className={`border-b border-line/60 ${it.excluded ? 'text-muted line-through' : 'text-body'}`}
                        >
                          <td className="px-3 py-1 pl-5">{it.material}</td>
                          <td className="px-3 py-1 text-right tabular-nums">{(it.quantity ?? 0).toFixed(2)}</td>
                          <td className="px-3 py-1 text-muted">{it.unit}</td>
                          <td className="px-3 py-1 text-right">
                            <input
                              type="number" step="0.01" title="Quote-only unit-price override"
                              className="w-20 rounded border border-transparent bg-transparent px-1 py-0.5 text-right tabular-nums hover:border-line focus:border-primary focus:outline-none"
                              value={overrides[String(it.bom_id)] ?? Number((it.unit_price ?? 0).toFixed(2))}
                              onChange={(e) => setOverrides((o) => ({ ...o, [String(it.bom_id)]: Number(e.target.value) }))}
                            />
                          </td>
                          <td className="px-3 py-1 text-right tabular-nums">{(it.line_cost ?? 0).toFixed(2)}</td>
                        </tr>
                      ))}
                    </Fragment>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}

function SummaryRow({ label, value, amber }: { label: string; value: string; amber?: boolean }) {
  return (
    <div className="flex items-center justify-between py-0.5 text-sm">
      <span className="text-muted">{label}</span>
      <span className={`tabular-nums ${amber ? 'text-status-amber' : 'text-body'}`}>{value}</span>
    </div>
  )
}
