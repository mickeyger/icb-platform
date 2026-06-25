// WO v4.37 §3.2 — native React Cost Calculator (replaces the /mes/calculator
// iframe). Core flow: pick a body type → set dimensions + body options → live
// POST /api/calculate (debounced) → cost summary + BOM table. The backend is the
// already-native calc engine (calculator.py); this layer only assembles inputs
// and renders the result. Save / version / customer flow lands in the §3.2 save
// increment; insulation copy-on-switch + optional-extras + per-row overrides are
// follow-ups (the engine already gates server-side from body_option_selections).
import { useEffect, useMemo, useState } from 'react'
import { Calculator, Loader2, RadioTower, AlertCircle } from 'lucide-react'
import { useTrailers, useTrailerBom, useLiveCalc } from './useCalculator'
import type { BomRow, Dimensions, BodyOptionSelections, CalcRequest } from './types'

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
  const { result, calculating, error: calcError, calculate } = useLiveCalc()

  // Default to the first body type once the list loads.
  useEffect(() => {
    if (trailerId == null && trailers.length) setTrailerId(trailers[0].id)
  }, [trailers, trailerId])

  // Seed dimensions + body-option defaults when a trailer's BOM loads.
  useEffect(() => {
    if (!bom.length) return
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
  }, [bom, trailerId, trailers])

  const req = useMemo<CalcRequest | null>(() => {
    if (trailerId == null) return null
    return {
      trailer_type_id: trailerId,
      dimensions: dims,
      profit_margin: margin,
      body_option_selections: sel,
      chassis: { enabled: false },
      ratio_value: ratio ? Number(ratio) : null,
      ratio_label: ratio ? `${Math.round(Number(ratio) * 100)}%` : null,
      discount_kind: discKind || null,
      discount_input: discKind ? discInput : null,
    }
  }, [trailerId, dims, margin, sel, ratio, discKind, discInput])

  // Debounced live recalc on any input change.
  useEffect(() => { if (req) calculate(req) }, [req, calculate])

  const optGroups = useMemo(() => groupBodyOptions(bom), [bom])
  const dimsValid = dims.length > 0 && dims.width > 0 && dims.height > 0

  const setSelExclusive = (rows: BomRow[], picked: number) =>
    setSel((s) => {
      const next = { ...s }
      for (const r of rows) next[String(r.id)] = r.id === picked
      return next
    })

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
                {g.subgroups.map((sg) => (
                  <div key={sg.subgroup || g.group} className="mb-2 rounded-md border border-line p-2">
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
                              onChange={() => sg.radio ? setSelExclusive(sg.rows, row.id) : setSel((s) => ({ ...s, [String(row.id)]: !on }))}
                            />
                            <span>{row.material_name}</span>
                            {row.variable_value != null && row.variable_value > 0 && (
                              <span className="text-[11px] text-muted">({row.variable_value} m)</span>
                            )}
                          </label>
                        )
                      })}
                    </div>
                  </div>
                ))}
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
                  {result.items.map((it, i) => (
                    <tr
                      key={`${it.bom_id}-${i}`}
                      className={`border-b border-line/60 ${it.excluded ? 'text-muted line-through' : 'text-body'} ${it.section_is_optional ? 'bg-status-amber/5' : ''}`}
                    >
                      <td className="px-3 py-1">{it.material}</td>
                      <td className="px-3 py-1 text-right tabular-nums">{(it.quantity ?? 0).toFixed(2)}</td>
                      <td className="px-3 py-1 text-muted">{it.unit}</td>
                      <td className="px-3 py-1 text-right tabular-nums">{(it.unit_price ?? 0).toFixed(2)}</td>
                      <td className="px-3 py-1 text-right tabular-nums">{(it.line_cost ?? 0).toFixed(2)}</td>
                    </tr>
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
