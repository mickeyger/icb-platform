/**
 * WO v4.25 §3.7 — read-only BOM rules-engine inspection (admin only).
 * Lists icb_mes.bom_rules + bom_rule_lookups + material_price_overrides via the admin GET
 * endpoints. No CRUD (editing arrives in v4.26). Backend-gated by require_admin; the page also
 * gates on AppData.isAdmin so non-admins never see the nav item or hit the 403.
 */
import { useEffect, useState } from 'react'

import { Skeleton, EmptyState, LastUpdated } from '../../components/ui/feedback'
import { Card, SectionTitle } from '../../components/ui/primitives'
import { useToast } from '../../components/ui/toast'
import { apiGet, handleApiError } from '../../lib/api'
import { useAppData } from '../../store/AppDataContext'

interface BomRule {
  id: number; body_type: string; section: string; panel: string; output_field: string
  formula_expression: string; priority: number; notes?: string | null; updated_by?: string | null
}
interface BomRuleLookup {
  id: number; body_type: string; section: string; lookup_type: string
  lookup_key: string; lookup_value: string; notes?: string | null
}
interface PriceOverride {
  id: number; sap_code: string; override_price: number | string; reason?: string | null
  valid_from: string; valid_to?: string | null
}

const TH = 'px-3 py-2 font-semibold'
const TD = 'px-3 py-2'

export function AdminBomRules() {
  const { isAdmin, apiMode } = useAppData()
  const toast = useToast()
  const [rules, setRules] = useState<BomRule[]>([])
  const [lookups, setLookups] = useState<BomRuleLookup[]>([])
  const [overrides, setOverrides] = useState<PriceOverride[]>([])
  const [loading, setLoading] = useState(true)
  const [updated, setUpdated] = useState<Date | null>(null)

  useEffect(() => {
    if (apiMode === 'loading') return
    if (!isAdmin) { setLoading(false); return }
    let alive = true
    void (async () => {
      try {
        const [r, l, o] = await Promise.all([
          apiGet<BomRule[]>('/api/admin/bom-rules'),
          apiGet<BomRuleLookup[]>('/api/admin/bom-rule-lookups'),
          apiGet<PriceOverride[]>('/api/admin/material-price-overrides'),
        ])
        if (!alive) return
        setRules(r); setLookups(l); setOverrides(o); setUpdated(new Date())
      } catch (e) {
        handleApiError(e, toast.push)
      } finally {
        if (alive) setLoading(false)
      }
    })()
    return () => { alive = false }
  }, [isAdmin, apiMode, toast])

  if (apiMode !== 'loading' && !isAdmin) {
    return (
      <div className="p-4">
        <EmptyState title="Admin access required"
                    hint="The BOM rules inspector is restricted to admin users." />
      </div>
    )
  }
  if (loading) return <div className="p-4"><Skeleton rows={10} /></div>

  return (
    <div className="space-y-6 p-4">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-bold text-body">Admin &rsaquo; BOM Rules</h1>
        <LastUpdated at={updated} />
      </div>
      <p className="text-xs text-muted">
        Rules-engine inspection (WO v4.25, read-only). Formulas run against resolved job specs by the
        AST-safe evaluator; editing arrives in v4.26.
      </p>

      <section>
        <SectionTitle>Rules ({rules.length})</SectionTitle>
        <Card className="p-0"><div className="overflow-x-auto"><table className="w-full text-sm">
          <thead className="bg-primary text-left text-white"><tr>
            {['Body', 'Section', 'Panel', 'Output', 'Formula', 'Prio'].map((h) => <th key={h} className={TH}>{h}</th>)}
          </tr></thead>
          <tbody>{rules.length ? rules.map((r, i) => (
            <tr key={r.id} className={`border-b border-line ${i % 2 ? 'bg-surface-alt' : 'bg-white'}`}>
              <td className={TD}>{r.body_type}</td>
              <td className={TD}>{r.section}</td>
              <td className={TD}>{r.panel}</td>
              <td className={TD}>{r.output_field}</td>
              <td className={`${TD} font-mono text-xs`}>{r.formula_expression}</td>
              <td className={TD}>{r.priority}</td>
            </tr>
          )) : <tr><td colSpan={6} className="px-4 py-8 text-center text-muted">No rules.</td></tr>}</tbody>
        </table></div></Card>
      </section>

      <section>
        <SectionTitle>Lookups ({lookups.length})</SectionTitle>
        <Card className="p-0"><div className="overflow-x-auto"><table className="w-full text-sm">
          <thead className="bg-primary text-left text-white"><tr>
            {['Type', 'Key', 'SAP code', 'Description'].map((h) => <th key={h} className={TH}>{h}</th>)}
          </tr></thead>
          <tbody>{lookups.length ? lookups.map((l, i) => (
            <tr key={l.id} className={`border-b border-line ${i % 2 ? 'bg-surface-alt' : 'bg-white'}`}>
              <td className={TD}>{l.lookup_type}</td>
              <td className={`${TD} font-mono text-xs`}>{l.lookup_key}</td>
              <td className={`${TD} font-mono text-xs`}>{l.lookup_value}</td>
              <td className={TD}>{l.notes}</td>
            </tr>
          )) : <tr><td colSpan={4} className="px-4 py-8 text-center text-muted">No lookups.</td></tr>}</tbody>
        </table></div></Card>
      </section>

      <section>
        <SectionTitle>Price overrides ({overrides.length})</SectionTitle>
        <Card className="p-0"><div className="overflow-x-auto"><table className="w-full text-sm">
          <thead className="bg-primary text-left text-white"><tr>
            {['SAP code', 'Override', 'Reason', 'From', 'To'].map((h) => <th key={h} className={TH}>{h}</th>)}
          </tr></thead>
          <tbody>{overrides.length ? overrides.map((o, i) => (
            <tr key={o.id} className={`border-b border-line ${i % 2 ? 'bg-surface-alt' : 'bg-white'}`}>
              <td className={`${TD} font-mono text-xs`}>{o.sap_code}</td>
              <td className={TD}>{o.override_price}</td>
              <td className={TD}>{o.reason}</td>
              <td className={TD}>{o.valid_from}</td>
              <td className={TD}>{o.valid_to ?? '—'}</td>
            </tr>
          )) : (
            <tr><td colSpan={5} className="px-4 py-8 text-center text-muted">
              No overrides — live SAP (OITM) pricing in effect.
            </td></tr>
          )}</tbody>
        </table></div></Card>
      </section>
    </div>
  )
}
