import { CostCalculator } from './calculator/CostCalculator'
import { CostingsDashboard } from './CostingsDashboard'

/**
 * WO v4.37 §3.2 — New Costing surface at /costings/new.
 *
 * Was an iframe to the `/mes/calculator` Jinja fork; now renders the NATIVE React
 * Cost Calculator (§0.12: route integration + component name preserved, internals
 * replaced). The CostingsDashboard stays embedded below (WO v4.31 §3.3). The now-
 * unused `/mes/calculator` Jinja route + the Vite `/mes` proxy are retired in §3.3.
 * (The /api/mes/autologin dev seam STAYS — it's the main-app session bootstrap used
 * by every context, not iframe-specific.)
 */
export function LiveCalculator() {
  return (
    <>
      <CostCalculator />
      <div className="border-t border-line">
        <CostingsDashboard embedded />
      </div>
    </>
  )
}
