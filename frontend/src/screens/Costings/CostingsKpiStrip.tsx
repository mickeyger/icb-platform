// CostingsKpiStrip.tsx — WO v4.31 §3.4 (§0.7): the 5 METRIC tiles lifted from the legacy
// server-rendered dashboard into the React Costings dashboard (action tiles deliberately NOT
// lifted). Values come from GET /api/dashboard/kpis, which shares compute_kpis() with the legacy
// Jinja page — parity by construction. Renders nothing in mock mode / on fetch failure.
//
// v1.39.4 — the strip used to fetch ONCE on mount (empty deps), so the Accepted totals + approval
// rate went stale after a costing was accepted/approved/signed-off until a full reload. It now
// refetches whenever a KPI-affecting input moves: it derives a compact signature from the shared
// costings context (count + per-row status:selling_zar — exactly what compute_kpis aggregates) and
// keys the fetch effect on it. CostingsContext replaces the array on each refetch(), so the sig
// changes on a real mutation but NOT on unrelated search/filter/selection churn.
import { useEffect, useMemo, useState } from 'react'
import { apiGet } from '../../lib/api'
import { KpiTile } from '../../components/ui/primitives'
import { zarShort } from '../../lib/format'
import { useCostings } from '../../store/CostingsContext'

interface ApprovalBucket {
  approved: number
  total: number
  pct: number
  label: string
}

interface Kpis {
  quotes_this_week: number
  total_value_quoted: number
  approved_value_quoted: number
  approved_count: number
  mat_count: number
  approval_rates: { week: ApprovalBucket; month: ApprovalBucket; prev: ApprovalBucket }
}

export function CostingsKpiStrip() {
  const { costings } = useCostings()
  const [kpis, setKpis] = useState<Kpis | null>(null)
  // Signature of exactly the inputs compute_kpis() aggregates (accepted count/value, approval rate,
  // total quoted). Changes only when a KPI-affecting field moves — so the effect below refetches
  // after an accept/approve/sign-off but not on pure reference churn (e.g. a branch-switch that
  // returns identical rows).
  const sig = useMemo(
    () => `${costings.length}|${costings.map((c) => `${c.status}:${c.selling_zar}`).join(',')}`,
    [costings],
  )
  useEffect(() => {
    let live = true
    apiGet<Kpis>('/api/dashboard/kpis')
      .then((k) => { if (live) setKpis(k) })
      .catch(() => { /* offline / mock mode — the strip simply doesn't render */ })
    return () => { live = false }
  }, [sig])
  if (!kpis) return null
  const r = kpis.approval_rates
  return (
    <div className="mb-3 grid grid-cols-2 gap-2 md:grid-cols-3 xl:grid-cols-5" data-testid="costings-kpis">
      <KpiTile label="Quotes this week" value={kpis.quotes_this_week} />
      <KpiTile label="Total quoted" value={zarShort(kpis.total_value_quoted)} sub="all quotations" />
      <KpiTile
        label="Accepted"
        value={zarShort(kpis.approved_value_quoted)}
        sub={`${kpis.approved_count} quote${kpis.approved_count === 1 ? '' : 's'}`}
      />
      <KpiTile label="Active materials" value={kpis.mat_count} />
      <KpiTile
        label="Approval rate"
        value={`${r.week.pct}%`}
        sub={`${r.week.label} · ${r.month.label}: ${r.month.pct}% · ${r.prev.label}: ${r.prev.pct}%`}
      />
    </div>
  )
}
