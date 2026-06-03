// StoresReconciliation.tsx — Screen 3: Stores' home, physical vs SAP.
// Stores cycle-counts items, confirms or flags discrepancies, and notifies Buying.
// Companion: Mockup Brief Addendum v1.5 §5; Work Order v4.11 §3.1.

import { useMemo, useState } from 'react'
import { ScanLine, Download } from 'lucide-react'
import { useMaterials, type StockCount, type CountStatus } from '../../store/MaterialsContext'
import { Card } from '../../components/ui/primitives'
import { Toast } from '../../components/ui/overlays'
import { Tooltip } from '../../components/ui/Tooltip'
import { dmy, hhmm } from '../../lib/format'
import { UrgencyPill } from './components/UrgencyPill'
import { MaterialsKpiStrip } from './components/MaterialsKpiStrip'
import { CountEntryModal } from './CountEntryModal'

type Filter = 'all' | CountStatus

// The buyer assigned to these items (from SAP item master in production).
const ASSIGNED_BUYER = 'M. Nkomo'

export function StoresReconciliation() {
  const { stockCounts, materials, notifyBuyerOfDiscrepancy } = useMaterials()
  const [filter, setFilter] = useState<Filter>('all')
  const [countTarget, setCountTarget] = useState<{ sapCode: string; bin: string } | null>(null)
  const [toast, setToast] = useState<{ msg: string; bad?: boolean } | null>(null)

  const today = new Date().toDateString()
  const counts = useMemo(
    () => ({
      confirmed_today: stockCounts.filter(
        (c) => c.status === 'confirmed' && c.counted_at && new Date(c.counted_at).toDateString() === today,
      ).length,
      discrepancies: stockCounts.filter((c) => c.status === 'discrepancy').length,
      pending: stockCounts.filter((c) => c.status === 'pending').length,
      cycle_coverage: 87, // mocked
    }),
    [stockCounts, today],
  )

  const filtered = useMemo(
    () => stockCounts.filter((c) => filter === 'all' || c.status === filter),
    [stockCounts, filter],
  )

  function flash(msg: string, bad = false) {
    setToast({ msg, bad })
    setTimeout(() => setToast(null), 4500)
  }

  async function handleNotifyBuyer(c: StockCount) {
    try {
      const rec = await notifyBuyerOfDiscrepancy(c.id, ASSIGNED_BUYER)
      flash(
        `Buyer notified — discrepancy #${rec.id} for ${c.sap_code} (bin ${c.bin}). ${ASSIGNED_BUYER} will investigate.`,
      )
    } catch {
      /* error toast surfaced by the context */
    }
  }

  const FILTERS: { key: Filter; label: string; count: number }[] = [
    { key: 'all', label: 'All', count: stockCounts.length },
    { key: 'discrepancy', label: 'Discrepancies', count: counts.discrepancies },
    { key: 'pending', label: 'Pending', count: counts.pending },
    { key: 'confirmed', label: 'Confirmed today', count: counts.confirmed_today },
  ]

  return (
    <div className="p-4">
      <div className="mb-1 text-[11px] text-muted">MES › Stores › Reconciliation</div>
      <h1 className="text-xl font-bold text-body">Stores Reconciliation — physical vs SAP</h1>
      <p className="mb-3 text-xs text-muted">
        Stores confirms or flags discrepancies; flagged items route to Buying for investigation.
      </p>

      <MaterialsKpiStrip
        tiles={[
          {
            label: 'Confirmed today',
            value: counts.confirmed_today,
            tone: 'ok',
            sub: 'items matched SAP stock',
            k: 'stores_reconciliation.kpi_confirmed_today',
          },
          {
            label: 'Discrepancies flagged',
            value: counts.discrepancies,
            tone: 'critical',
            sub: 'SAP differs from physical · awaiting Buyer',
            k: 'stores_reconciliation.kpi_discrepancies_open',
          },
          {
            label: 'Pending this week',
            value: counts.pending,
            tone: 'warn',
            sub: 'items to count by Friday · cycle plan',
            k: 'stores_reconciliation.kpi_pending_this_week',
          },
          {
            label: 'Cycle coverage',
            value: `${counts.cycle_coverage}%`,
            sub: 'of A-class items reconciled in last 14 days',
            k: 'stores_reconciliation.kpi_cycle_coverage',
          },
        ]}
      />

      {/* Filter row */}
      <div className="mb-3 flex flex-wrap items-center gap-2">
        {FILTERS.map((f) => {
          const on = filter === f.key
          return (
            <Tooltip key={f.key} k="stores_reconciliation.filter_chip_view">
              <button
                onClick={() => setFilter(f.key)}
                className={`flex items-center gap-1 rounded-full border px-3 py-1 text-xs font-semibold ${
                  on ? 'border-primary bg-primary text-white' : 'border-line bg-white text-body hover:bg-surface-alt'
                }`}
              >
                {f.label}
                <span
                  className={`rounded-full px-1.5 py-0.5 text-[10px] ${on ? 'bg-white/20' : 'bg-surface-alt text-muted'}`}
                >
                  {f.count}
                </span>
              </button>
            </Tooltip>
          )
        })}
        <div className="ml-auto flex items-center gap-2">
          <Tooltip k="stores_reconciliation.scan_barcode_button">
            <button className="flex items-center gap-1.5 rounded-md border border-line bg-white px-3 py-1.5 text-xs font-semibold text-body hover:bg-surface-alt">
              <ScanLine size={14} /> Scan barcode
            </button>
          </Tooltip>
          <button className="flex items-center gap-1.5 rounded-md border border-line bg-white px-3 py-1.5 text-xs font-semibold text-body hover:bg-surface-alt">
            <Download size={14} /> Export CSV
          </button>
        </div>
      </div>

      {/* Table */}
      <Card className="p-0">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-primary text-left text-white">
              <tr>
                <th className="px-3 py-2 font-semibold">SAP code</th>
                <th className="px-3 py-2 font-semibold">Description</th>
                <th className="px-3 py-2 font-semibold">Bin</th>
                <th className="px-3 py-2 text-right font-semibold">SAP stock</th>
                <th className="px-3 py-2 text-right font-semibold">Physical</th>
                <th className="px-3 py-2 text-right font-semibold">Diff</th>
                <th className="px-3 py-2 font-semibold">Last counted</th>
                <th className="px-3 py-2 font-semibold">Counted by</th>
                <th className="px-3 py-2 font-semibold">Status</th>
                <th className="px-3 py-2 font-semibold">Action</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((c, i) => {
                const mat = materials.find((m) => m.sap_code === c.sap_code)
                const diff = (c.physical_count ?? 0) - c.sap_stock_at_count
                const rowBg =
                  c.status === 'discrepancy' ? 'bg-status-red/5' : i % 2 ? 'bg-surface-alt' : 'bg-white'
                return (
                  <tr key={c.id} className={`border-b border-line ${rowBg}`}>
                    <td className="px-3 py-2 font-mono text-xs font-semibold">{c.sap_code}</td>
                    <td className="px-3 py-2">{mat?.description}</td>
                    <td className="px-3 py-2 text-xs">{c.bin}</td>
                    <td className="px-3 py-2 text-right tabular-nums">{c.sap_stock_at_count}</td>
                    <td
                      className={`px-3 py-2 text-right tabular-nums ${
                        c.status === 'discrepancy' ? 'font-semibold text-status-red' : ''
                      }`}
                    >
                      {c.physical_count ?? '—'}
                    </td>
                    <td
                      className={`px-3 py-2 text-right tabular-nums ${
                        c.physical_count == null
                          ? 'text-muted'
                          : diff < 0
                            ? 'font-semibold text-status-red'
                            : diff > 0
                              ? 'font-semibold text-status-green'
                              : 'text-status-green'
                      }`}
                    >
                      {c.physical_count == null ? '—' : diff === 0 ? '0' : diff > 0 ? `+${diff}` : diff}
                    </td>
                    <td className="px-3 py-2 text-xs text-muted">
                      {c.counted_at ? `${dmy(c.counted_at)} ${hhmm(c.counted_at)}` : '—'}
                    </td>
                    <td className="px-3 py-2 text-xs">{c.counted_by}</td>
                    <td className="px-3 py-2">
                      <UrgencyPill
                        tone={c.status}
                        suffix={c.status === 'discrepancy' ? ' · OPEN' : c.status === 'pending' ? ' COUNT' : ''}
                      />
                    </td>
                    <td className="px-3 py-2">
                      {c.status === 'discrepancy' && (
                        <Tooltip k="stores_reconciliation.notify_buyer_button">
                          <button
                            onClick={() => handleNotifyBuyer(c)}
                            className="rounded-md bg-primary px-2.5 py-1 text-xs font-semibold text-white hover:bg-primary-dark"
                          >
                            Notify Buyer ›
                          </button>
                        </Tooltip>
                      )}
                      {c.status === 'pending' && (
                        <Tooltip k="stores_reconciliation.count_now_button">
                          <button
                            onClick={() => setCountTarget({ sapCode: c.sap_code, bin: c.bin })}
                            className="rounded-md border border-primary bg-white px-2.5 py-1 text-xs font-semibold text-primary hover:bg-primary-light"
                          >
                            Count now ›
                          </button>
                        </Tooltip>
                      )}
                      {c.status === 'confirmed' && <span className="text-muted">—</span>}
                    </td>
                  </tr>
                )
              })}
              {filtered.length === 0 && (
                <tr>
                  <td colSpan={10} className="px-4 py-12 text-center text-sm text-muted">
                    No items match the current view.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </Card>

      <div className="mt-2 text-[11px] text-muted">
        {filtered.length} of {stockCounts.length} items · {counts.discrepancies} discrepancies open
      </div>

      <div className="mt-4 rounded-md border border-primary/30 bg-primary-light/50 p-3 text-[11px] text-primary-dark">
        <div className="mb-1 text-xs font-bold text-primary">Cycle-count workflow</div>
        Stores cycle-counts items on a rolling basis. Today's plan is generated from ABC analysis + last-count date.
        <br />
        When physical ≠ SAP, the item is flagged DISCREPANCY and Buying is notified to investigate (incoming POs not
        yet received, mis-issue, theft, damage).
      </div>

      {countTarget && (
        <CountEntryModal
          sapCode={countTarget.sapCode}
          bin={countTarget.bin}
          onClose={() => setCountTarget(null)}
          onCounted={(result) => {
            setCountTarget(null)
            if (result.status === 'confirmed') {
              flash(`✓ ${result.sap_code} confirmed at ${result.physical_count}`)
            } else {
              flash(
                `⚠ Discrepancy: ${result.sap_code} — SAP ${result.sap_stock_at_count}, physical ${result.physical_count}. Notify Buyer to investigate.`,
                true,
              )
            }
          }}
        />
      )}

      <Toast message={toast?.msg ?? ''} show={!!toast} />
    </div>
  )
}
