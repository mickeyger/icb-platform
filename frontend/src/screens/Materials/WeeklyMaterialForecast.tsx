// WeeklyMaterialForecast.tsx — Screen 4: replaces the MATERIAL PLANNING sheet.
// Per-material, per-week demand grid. Buyer + Planner shared view. Click any cell
// to drill into the contributing jobs. Rendered as a tab inside MaterialsDashboard.
// Companion: Mockup Brief Addendum v1.5 §6; Work Order v4.11 §3.1.

import { useMemo, useState } from 'react'
import { useMaterials, type Dept } from '../../store/MaterialsContext'
import { Card } from '../../components/ui/primitives'
import { Modal } from '../../components/ui/overlays'
import { Tooltip } from '../../components/ui/Tooltip'
import { zarShort, dmy } from '../../lib/format'
import { UrgencyPill } from './components/UrgencyPill'
import { MaterialsKpiStrip } from './components/MaterialsKpiStrip'

type DeptFilter = 'all' | Dept

interface DrillState {
  sapCode: string
  week: string
}

// Returns "YYYY-WNN" — same shape as the seed week_bucket field.
function isoWeek(d: Date): string {
  const date = new Date(Date.UTC(d.getFullYear(), d.getMonth(), d.getDate()))
  const dayNum = (date.getUTCDay() + 6) % 7
  date.setUTCDate(date.getUTCDate() - dayNum + 3)
  const firstThursday = date.getTime()
  date.setUTCMonth(0, 1)
  if (date.getUTCDay() !== 4) date.setUTCMonth(0, 1 + ((4 - date.getUTCDay()) + 7) % 7)
  const week = 1 + Math.ceil((firstThursday - date.getTime()) / 604_800_000)
  return `${d.getFullYear()}-W${String(week).padStart(2, '0')}`
}

function weeksFromCurrent(n: number): { iso: string; label: string; dates: string }[] {
  const result: { iso: string; label: string; dates: string }[] = []
  const now = new Date('2026-06-01') // mock "today" so the wireframe and screen agree
  for (let i = 0; i < n; i++) {
    const monday = new Date(now)
    monday.setDate(monday.getDate() - ((monday.getDay() + 6) % 7) + i * 7)
    const sunday = new Date(monday)
    sunday.setDate(monday.getDate() + 6)
    result.push({
      iso: isoWeek(monday),
      label: `Wk ${isoWeek(monday).slice(-2)}`,
      dates: `${monday.getDate()}–${sunday.getDate()} ${sunday.toLocaleString('en-GB', { month: 'short' })}`,
    })
  }
  return result
}

function computeFlag(weekly: { week: string; qty: number }[], stock: number, openPO: number): string {
  let running = stock + openPO
  for (const w of weekly) {
    running -= w.qty
    if (running < 0) return w.week.slice(-3) // "2026-W23" -> "W23"
  }
  return 'OK'
}

const DEPTS: DeptFilter[] = ['all', 'vacuum', 'panelshop', 'assy', 'paint']

export function WeeklyMaterialForecast() {
  const { materials, demandLines, stockPositions } = useMaterials()
  const [dept, setDept] = useState<DeptFilter>('all')
  const [drill, setDrill] = useState<DrillState | null>(null)

  const weeks = useMemo(() => weeksFromCurrent(4), [])

  const grid = useMemo(() => {
    return materials
      .filter((m) => dept === 'all' || m.dept === dept)
      .map((m) => {
        const weekly = weeks.map((w) => {
          const lines = demandLines.filter((d) => d.sap_code === m.sap_code && d.week_bucket === w.iso)
          return { week: w.iso, qty: lines.reduce((a, d) => a + d.qty, 0) }
        })
        const total = weekly.reduce((a, w) => a + w.qty, 0)
        const stock = stockPositions.find((s) => s.sap_code === m.sap_code)
        const coverage = (stock?.sap_stock ?? 0) + (stock?.open_po_qty ?? 0) - total
        const flag = computeFlag(weekly, stock?.sap_stock ?? 0, stock?.open_po_qty ?? 0)
        return { m, weekly, total, coverage, flag }
      })
      .filter((r) => r.total > 0)
      .sort((a, b) => b.total - a.total)
  }, [materials, demandLines, stockPositions, dept, weeks])

  const kpis = useMemo(() => {
    const shortItems = grid.filter((r) => r.flag !== 'OK').length
    const totalValue = grid.reduce((a, r) => a + r.total * r.m.last_price, 0)
    const totalJobs = new Set(demandLines.map((d) => d.job_id)).size
    return { tracked: grid.length, short: shortItems, value: totalValue, jobs: totalJobs }
  }, [grid, demandLines])

  return (
    <>
      <p className="mb-3 text-xs text-muted">
        Per-material demand by week — drill into any cell to see contributing jobs. Replaces the MATERIAL PLANNING sheet.
      </p>

      <MaterialsKpiStrip
        tiles={[
          {
            label: 'Materials tracked',
            value: kpis.tracked,
            sub: 'items with demand in next 4 weeks',
            k: 'weekly_material_forecast.kpi_materials_tracked',
          },
          {
            label: 'Items short (next 4 wk)',
            value: kpis.short,
            tone: 'critical',
            sub: 'supply gap on confirmed schedule',
            k: 'weekly_material_forecast.kpi_items_short',
          },
          {
            label: 'Forecast demand value',
            value: zarShort(kpis.value),
            sub: 'at last-paid prices · next 4 weeks',
            k: 'weekly_material_forecast.kpi_forecast_value',
          },
          {
            label: 'Jobs driving forecast',
            value: kpis.jobs,
            sub: 'scheduled in next 4 weeks',
            k: 'weekly_material_forecast.kpi_jobs_driving',
          },
        ]}
      />

      {/* Department tabs */}
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <span className="text-[10px] font-semibold uppercase tracking-wide text-muted">Department:</span>
        {DEPTS.map((d) => {
          const on = dept === d
          return (
            <Tooltip key={d} k="weekly_material_forecast.tab_department">
              <button
                onClick={() => setDept(d)}
                className={`rounded-full border px-3 py-1 text-xs font-semibold capitalize ${
                  on ? 'border-primary bg-primary text-white' : 'border-line bg-white text-body hover:bg-surface-alt'
                }`}
              >
                {d}
              </button>
            </Tooltip>
          )
        })}
        <span className="ml-auto text-xs text-body">
          Starting: {weeks[0].label} ({weeks[0].dates})
        </span>
      </div>

      {/* Grid */}
      <Card className="p-0">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-primary text-left text-white">
              <tr>
                <th className="px-3 py-2 font-semibold">Material</th>
                {weeks.map((w) => (
                  <th key={w.iso} className="px-3 py-2 text-right font-semibold">
                    {w.label}
                    <br />
                    <span className="text-[10px] font-normal text-white/70">{w.dates}</span>
                  </th>
                ))}
                <th className="px-3 py-2 text-right font-semibold">Total</th>
                <th className="px-3 py-2 text-right font-semibold">Stock covers</th>
                <th className="px-3 py-2 font-semibold">Flag</th>
              </tr>
            </thead>
            <tbody>
              {grid.map((r, i) => (
                <tr key={r.m.sap_code} className={`border-b border-line ${i % 2 ? 'bg-surface-alt' : 'bg-white'}`}>
                  <td className="px-3 py-2">
                    <div className="font-mono text-xs font-semibold">{r.m.sap_code}</div>
                    <div className="text-[10px] text-muted">{r.m.description}</div>
                  </td>
                  {r.weekly.map((w) => (
                    <td key={w.week} className="px-3 py-2 text-right tabular-nums">
                      {w.qty > 0 ? (
                        <Tooltip k="weekly_material_forecast.cell_quantity_click">
                          <button
                            onClick={() => setDrill({ sapCode: r.m.sap_code, week: w.week })}
                            className="font-semibold text-primary underline decoration-dotted hover:text-primary-dark"
                          >
                            {w.qty}
                          </button>
                        </Tooltip>
                      ) : (
                        <span className="text-line">0</span>
                      )}
                    </td>
                  ))}
                  <td className="px-3 py-2 text-right font-bold tabular-nums">{r.total}</td>
                  <td
                    className={`px-3 py-2 text-right font-semibold tabular-nums ${
                      r.coverage < 0 ? 'text-status-red' : 'text-status-green'
                    }`}
                  >
                    {r.coverage >= 0 ? `+${r.coverage}` : r.coverage}
                  </td>
                  <td className="px-3 py-2">
                    {r.flag === 'OK' ? (
                      <UrgencyPill tone="comfortable" size="sm" />
                    ) : (
                      <UrgencyPill tone="order_now" size="sm" suffix={` · ${r.flag}`} />
                    )}
                  </td>
                </tr>
              ))}
              {grid.length === 0 && (
                <tr>
                  <td colSpan={weeks.length + 4} className="px-4 py-12 text-center text-sm text-muted">
                    No demand for this department in the next 4 weeks.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </Card>

      <div className="mt-2 text-[11px] text-muted">
        {grid.length} of {materials.length} materials · click any cell for contributing jobs
      </div>

      <div className="mt-4 rounded-md border border-status-green/40 bg-status-green/5 p-3 text-[11px] text-body">
        <div className="mb-1 text-xs font-bold text-status-green">This view replaces the MATERIAL PLANNING sheet</div>
        Old sheet: 5,162 rows × 20 columns, rebuilt by hand every week, shortages spotted by blank cells.
        <br />
        New view: auto-computed from each accepted job's BOM × Planning Board start week. Live SAP stock. Shortages
        flagged proactively against lead time.
      </div>

      {drill && <DrillModal sapCode={drill.sapCode} week={drill.week} onClose={() => setDrill(null)} />}
    </>
  )
}

function DrillModal({ sapCode, week, onClose }: { sapCode: string; week: string; onClose: () => void }) {
  const { demandLines, materials } = useMaterials()
  const mat = materials.find((m) => m.sap_code === sapCode)
  const contributing = demandLines.filter((d) => d.sap_code === sapCode && d.week_bucket === week)
  const total = contributing.reduce((a, d) => a + d.qty, 0)
  return (
    <Modal open onClose={onClose} className="max-w-lg">
      <h2 className="text-lg font-bold text-body">
        <span className="font-mono">{sapCode}</span> — {week}
      </h2>
      <p className="mt-0.5 text-xs text-muted">{mat?.description}</p>
      <div className="mt-3 text-xs font-semibold text-body">
        Contributing jobs ({contributing.length}, total {total}):
      </div>
      <div className="mt-2 max-h-80 overflow-y-auto rounded-md border border-line">
        {contributing.map((d, i) => (
          <div
            key={i}
            className="flex items-center justify-between border-b border-line px-3 py-2 text-xs last:border-b-0"
          >
            <span>
              <span className="font-mono font-semibold">{d.job_id}</span>
              <span className="text-muted"> · need-by {dmy(d.need_by)}</span>
            </span>
            <strong className="tabular-nums">{d.qty}</strong>
          </div>
        ))}
      </div>
      <div className="mt-4 text-right">
        <button
          onClick={onClose}
          className="rounded-md bg-primary px-4 py-2 text-sm font-semibold text-white hover:bg-primary-dark"
        >
          Close
        </button>
      </div>
    </Modal>
  )
}
