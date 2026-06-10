// CostingsKpiStrip.tsx — WO v4.31 §3.4 (§0.7): the 5 METRIC tiles lifted from the legacy
// server-rendered dashboard into the React Costings dashboard (action tiles deliberately NOT
// lifted). Values come from GET /api/dashboard/kpis, which shares compute_kpis() with the legacy
// Jinja page — parity by construction. Fetched ONCE on page load (§0.11 — no polling/websocket;
// fresher numbers = reload; tile-refresh is a v4.34 conversation). Renders nothing in mock mode /
// on fetch failure.
import { useEffect, useState } from 'react'
import { apiGet } from '../../lib/api'
import { KpiTile } from '../../components/ui/primitives'
import { zarShort } from '../../lib/format'

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
  const [kpis, setKpis] = useState<Kpis | null>(null)
  useEffect(() => {
    let live = true
    apiGet<Kpis>('/api/dashboard/kpis')
      .then((k) => { if (live) setKpis(k) })
      .catch(() => { /* offline / mock mode — the strip simply doesn't render */ })
    return () => { live = false }
  }, [])
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
