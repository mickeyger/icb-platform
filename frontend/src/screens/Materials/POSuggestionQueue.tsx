// POSuggestionQueue.tsx — Screen 2: Buyer's action queue. Click-to-raise PRs,
// per-supplier bulk raise, defer, and (senior buyer) supplier override.
// Companion: Mockup Brief Addendum v1.5 §4; Work Order v4.11 §3.1.

import { useMemo, useState } from 'react'
import { useMaterials, type Urgency } from '../../store/MaterialsContext'
import { useAppData } from '../../store/AppDataContext'
import { Card } from '../../components/ui/primitives'
import { Toast } from '../../components/ui/overlays'
import { Tooltip } from '../../components/ui/Tooltip'
import { zar, zarShort, dmy } from '../../lib/format'
import { UrgencyPill } from './components/UrgencyPill'
import { MaterialsKpiStrip } from './components/MaterialsKpiStrip'
import { RaisePRModal } from './RaisePRModal'
import { LastUpdated } from '../../components/ui/feedback'

type UrgencyFilter = 'all' | Urgency

export function POSuggestionQueue() {
  const { poSuggestions, materials, suppliers, raisePR, deferSuggestion, overrideSupplier, lastUpdated, refresh } =
    useMaterials()
  const { profile, hasPermission } = useAppData()
  const [filter, setFilter] = useState<UrgencyFilter>('all')
  const [supplierFilter, setSupplierFilter] = useState('all')
  const [selected, setSelected] = useState<Set<number>>(new Set())
  const [modalIds, setModalIds] = useState<number[] | null>(null)
  const [toast, setToast] = useState<string | null>(null)

  const canOverride = hasPermission('materials.override_supplier')
  const canBulk = hasPermission('materials.bulk_raise')

  const pending = useMemo(
    () => poSuggestions.filter((s) => s.status === 'pending'),
    [poSuggestions],
  )
  const filtered = useMemo(
    () =>
      pending.filter((s) => {
        if (filter !== 'all' && s.urgency !== filter) return false
        if (supplierFilter !== 'all' && s.suggested_supplier !== supplierFilter) return false
        return true
      }),
    [pending, filter, supplierFilter],
  )

  const today = new Date().toDateString()
  const counts = useMemo(
    () => ({
      pending: pending.length,
      suggested_value: pending.reduce((a, s) => a + s.total, 0),
      critical: pending.filter((s) => s.urgency === 'critical').length,
      order_now: pending.filter((s) => s.urgency === 'order_now').length,
      advisory: pending.filter((s) => s.urgency === 'advisory').length,
      oldest_days: pending.length
        ? Math.max(...pending.map((s) => Math.ceil((Date.now() - +new Date(s.created_at)) / 86_400_000)))
        : 0,
      raised_today: poSuggestions.filter(
        (s) => s.status === 'raised' && s.raised_at && new Date(s.raised_at).toDateString() === today,
      ).length,
      raised_today_value: poSuggestions
        .filter(
          (s) => s.status === 'raised' && s.raised_at && new Date(s.raised_at).toDateString() === today,
        )
        .reduce((a, s) => a + s.total, 0),
    }),
    [pending, poSuggestions, today],
  )

  function toggleSelected(id: number) {
    setSelected((prev) => {
      const n = new Set(prev)
      n.has(id) ? n.delete(id) : n.add(id)
      return n
    })
  }

  function openRaiseModal(ids: number[]) {
    if (ids.length) setModalIds(ids)
  }

  async function handleConfirmRaise(ids: number[]) {
    const result = await raisePR(ids, profile.name)
    setToast(
      `${result.prNumber} raised against ${result.suppliersAffected.join(', ')} · ${ids.length} item(s), ${zar(result.total)}.`,
    )
    setSelected(new Set())
    setModalIds(null)
    setTimeout(() => setToast(null), 5000)
  }

  const selectedTotal = Array.from(selected).reduce(
    (a, id) => a + (pending.find((p) => p.id === id)?.total ?? 0),
    0,
  )

  const FILTERS: { key: UrgencyFilter; label: string; count: number }[] = [
    { key: 'all', label: 'All', count: counts.pending },
    { key: 'critical', label: 'Critical', count: counts.critical },
    { key: 'order_now', label: 'Order Now', count: counts.order_now },
    { key: 'advisory', label: 'Advisory', count: counts.advisory },
  ]

  return (
    <div className="p-4">
      <div className="mb-1 text-[11px] text-muted">MES › Materials &amp; Buying › PO Suggestions</div>
      <h1 className="text-xl font-bold text-body">Purchase Order Suggestions</h1>
      <p className="mb-3 text-xs text-muted">
        System-generated draft PRs. Review, adjust, raise to SAP via BAPI_PR_CREATE.
      </p>

      <MaterialsKpiStrip
        tiles={[
          {
            label: 'Pending suggestions',
            value: counts.pending,
            sub: `${counts.critical} critical · ${counts.order_now} order-now · ${counts.advisory} advisory`,
            k: 'po_suggestion_queue.kpi_pending',
          },
          {
            label: 'Suggested value',
            value: zarShort(counts.suggested_value),
            sub: 'at last-paid prices',
            k: 'po_suggestion_queue.kpi_suggested_value',
          },
          {
            label: 'Oldest suggestion',
            value: `${counts.oldest_days}d`,
            tone: counts.oldest_days >= 5 ? 'critical' : 'neutral',
            sub: 'since first generated',
            k: 'po_suggestion_queue.kpi_oldest_age',
          },
          {
            label: 'Raised today · value',
            value: `${counts.raised_today} · ${zarShort(counts.raised_today_value)}`,
            tone: 'ok',
            sub: 'confirmed by SAP (PR numbers assigned)',
            k: 'po_suggestion_queue.kpi_raised_today',
          },
        ]}
      />

      {/* Filter + bulk-action row */}
      <div className="mb-3 flex flex-wrap items-center gap-2">
        {FILTERS.map((f) => {
          const on = filter === f.key
          return (
            <button
              key={f.key}
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
          )
        })}
        <Tooltip k="po_suggestion_queue.kpi_pending">
          <select
            value={supplierFilter}
            onChange={(e) => setSupplierFilter(e.target.value)}
            className="rounded-md border border-line bg-white px-2 py-1.5 text-xs outline-none"
          >
            <option value="all">All suppliers</option>
            {suppliers.map((s) => (
              <option key={s.name} value={s.name}>
                {s.name}
              </option>
            ))}
          </select>
        </Tooltip>

        <div className="ml-auto flex flex-wrap items-center gap-2">
          <button
            onClick={() => openRaiseModal(Array.from(selected))}
            disabled={selected.size === 0}
            className="rounded-md border border-status-green bg-white px-3 py-1.5 text-xs font-semibold text-status-green hover:bg-status-green/10 disabled:opacity-40"
          >
            Raise Selected ({selected.size})
          </button>
          <Tooltip k="po_suggestion_queue.defer_button">
            <button
              onClick={() => {
                const until = new Date(Date.now() + 7 * 86_400_000).toISOString().slice(0, 10)
                for (const id of selected) deferSuggestion(id, until)
                setSelected(new Set())
              }}
              disabled={selected.size === 0}
              className="rounded-md border border-line bg-white px-3 py-1.5 text-xs font-semibold text-body hover:bg-surface-alt disabled:opacity-40"
            >
              Defer Selected
            </button>
          </Tooltip>
          {canBulk && (
            <Tooltip k="po_suggestion_queue.bulk_raise_button">
              <button
                onClick={() => openRaiseModal(pending.filter((s) => s.urgency === 'critical').map((s) => s.id))}
                disabled={counts.critical === 0}
                className="rounded-md bg-primary px-3 py-1.5 text-xs font-semibold text-white hover:bg-primary-dark disabled:opacity-40"
              >
                Bulk Raise Critical ({counts.critical})
              </button>
            </Tooltip>
          )}
        </div>
      </div>

      {/* Table */}
      <Card className="p-0">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-primary text-left text-white">
              <tr>
                <th className="px-2 py-2">
                  <input
                    type="checkbox"
                    aria-label="Select all"
                    checked={selected.size === filtered.length && filtered.length > 0}
                    onChange={(e) =>
                      e.target.checked
                        ? setSelected(new Set(filtered.map((s) => s.id)))
                        : setSelected(new Set())
                    }
                    className="h-4 w-4 cursor-pointer"
                  />
                </th>
                <th className="px-3 py-2 font-semibold">Item</th>
                <th className="px-3 py-2 text-right font-semibold">Qty</th>
                <th className="px-3 py-2 font-semibold">Supplier</th>
                <th className="px-3 py-2 text-right font-semibold">Last price</th>
                <th className="px-3 py-2 text-right font-semibold">Total</th>
                <th className="px-3 py-2 font-semibold">Need-by</th>
                <th className="px-3 py-2 font-semibold">Job(s)</th>
                <th className="px-3 py-2 font-semibold">Urgency</th>
                <th className="px-3 py-2 font-semibold">Action</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((s, i) => {
                const mat = materials.find((m) => m.sap_code === s.sap_code)
                const supplier = suppliers.find((sup) => sup.name === s.suggested_supplier)
                const daysToNeed = Math.ceil((+new Date(s.need_by) - Date.now()) / 86_400_000)
                return (
                  <tr
                    key={s.id}
                    className={`border-b border-line align-top ${i % 2 ? 'bg-surface-alt' : 'bg-white'}`}
                  >
                    <td className="px-2 py-2">
                      <input
                        type="checkbox"
                        checked={selected.has(s.id)}
                        onChange={() => toggleSelected(s.id)}
                        className="h-4 w-4 cursor-pointer"
                      />
                    </td>
                    <td className="px-3 py-2">
                      <div className="font-mono text-xs font-semibold">{s.sap_code}</div>
                      <div className="text-xs text-muted">{mat?.description}</div>
                    </td>
                    <td className="px-3 py-2 text-right tabular-nums">{s.qty}</td>
                    <td className="px-3 py-2">
                      {canOverride ? (
                        <Tooltip k="po_suggestion_queue.override_supplier_dropdown">
                          <select
                            value={s.suggested_supplier}
                            onChange={(e) => overrideSupplier(s.id, e.target.value)}
                            className="rounded border border-line bg-white px-1.5 py-1 text-xs outline-none"
                          >
                            {suppliers.map((sup) => (
                              <option key={sup.name} value={sup.name}>
                                {sup.name}
                              </option>
                            ))}
                          </select>
                        </Tooltip>
                      ) : (
                        <div className="font-semibold">{s.suggested_supplier}</div>
                      )}
                      <div className="mt-0.5 text-xs text-muted">
                        contact: {supplier?.contact_person ?? '—'}
                      </div>
                    </td>
                    <td className="px-3 py-2 text-right tabular-nums">{zar(s.last_price)}</td>
                    <td className="px-3 py-2 text-right font-semibold tabular-nums">{zar(s.total)}</td>
                    <td className="px-3 py-2 text-xs">{dmy(s.need_by)}</td>
                    <td className="px-3 py-2 text-xs">
                      {s.jobs_impacted.slice(0, 2).join(' · ')}
                      {s.jobs_impacted.length > 2 ? ` +${s.jobs_impacted.length - 2}` : ''}
                    </td>
                    <td className="px-3 py-2">
                      <UrgencyPill tone={s.urgency} suffix={` · T-${daysToNeed}`} />
                    </td>
                    <td className="px-3 py-2">
                      <Tooltip k="po_suggestion_queue.raise_pr_button">
                        <button
                          onClick={() => openRaiseModal([s.id])}
                          className="rounded-md bg-primary px-2.5 py-1 text-xs font-semibold text-white hover:bg-primary-dark"
                        >
                          Raise PR ›
                        </button>
                      </Tooltip>
                    </td>
                  </tr>
                )
              })}
              {filtered.length === 0 && (
                <tr>
                  <td colSpan={10} className="px-4 py-12 text-center text-sm text-muted">
                    No pending suggestions match the current filters.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </Card>

      <div className="mt-2 flex justify-between text-xs text-body">
        <span>
          {filtered.length} of {counts.pending} pending · {selected.size} selected
        </span>
        {selected.size > 0 && <strong className="tabular-nums">Selected total: {zar(selectedTotal)}</strong>}
      </div>
      <LastUpdated at={lastUpdated} onRefresh={refresh} />

      {modalIds && (
        <RaisePRModal
          suggestionIds={modalIds}
          onConfirm={handleConfirmRaise}
          onClose={() => setModalIds(null)}
        />
      )}

      <Toast message={toast ? `✓ ${toast}` : ''} show={!!toast} />
    </div>
  )
}
