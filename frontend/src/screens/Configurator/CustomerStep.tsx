import { useMemo, useState } from 'react'
import { Plus, Search, Check } from 'lucide-react'
import { data } from '../../data/mockData'
import { Modal } from '../../components/ui/overlays'
import type { Customer } from '../../data/types'
import type { Selection } from './Configurator'

/**
 * Customer step (per addendum §4): customers grouped by their owning rep,
 * the logged-in rep's section pinned to the top with subtler styling for
 * the others. A global search filters across all groups.
 */
export function CustomerStep({
  sel,
  setSel,
}: {
  sel: Selection
  setSel: React.Dispatch<React.SetStateAction<Selection>>
}) {
  const [q, setQ] = useState('')
  const [showNew, setShowNew] = useState(false)
  const activeRep = data.user.rep_code

  // Group customers by default_rep, alphabetical within each group.
  const grouped = useMemo(() => {
    const byRep = new Map<string, Customer[]>()
    for (const c of data.customers) {
      if (!byRep.has(c.default_rep)) byRep.set(c.default_rep, [])
      byRep.get(c.default_rep)!.push(c)
    }
    for (const list of byRep.values()) list.sort((a, b) => a.name.localeCompare(b.name))
    return byRep
  }, [])

  // Active rep first, then other reps alphabetical by rep_code (as per addendum).
  const orderedReps = useMemo(() => {
    const codes = Array.from(grouped.keys())
    const others = codes.filter((c) => c !== activeRep).sort()
    return grouped.has(activeRep) ? [activeRep, ...others] : codes.sort()
  }, [grouped, activeRep])

  function repName(code: string): string {
    return data.sales_reps.find((r) => r.code === code)?.name ?? code
  }

  // Search filter: name, contact, or numeric id.
  const ql = q.trim().toLowerCase()
  function matches(c: Customer): boolean {
    if (!ql) return true
    return (
      c.name.toLowerCase().includes(ql) ||
      c.contact.toLowerCase().includes(ql) ||
      String(c.id).includes(ql)
    )
  }

  return (
    <div>
      <div className="sticky top-0 z-10 mb-3 flex items-center gap-2 rounded-md border border-line bg-white px-3 py-2 shadow-sm">
        <Search size={16} className="text-muted" />
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Search customers, contacts, IDs… filters across all reps"
          className="flex-1 text-sm outline-none"
        />
        {q && (
          <button onClick={() => setQ('')} className="text-xs text-muted hover:text-body">
            clear
          </button>
        )}
      </div>

      <div className="space-y-4">
        {orderedReps.map((code) => {
          const all = grouped.get(code) ?? []
          const visible = all.filter(matches)
          if (ql && visible.length === 0) return null
          const isActive = code === activeRep
          return (
            <section key={code} className={isActive ? '' : 'opacity-95'}>
              <RepHeader
                isActive={isActive}
                code={code}
                name={repName(code)}
                count={visible.length}
                onNewCustomer={isActive ? () => setShowNew(true) : undefined}
              />
              <div
                className={
                  isActive
                    ? 'grid grid-cols-2 gap-3 lg:grid-cols-4'
                    : 'grid grid-cols-2 gap-2 lg:grid-cols-5'
                }
              >
                {visible.map((c) => (
                  <CustomerCard
                    key={c.id}
                    customer={c}
                    compact={!isActive}
                    selected={sel.customer?.id === c.id}
                    onClick={() => setSel((s) => ({ ...s, customer: c }))}
                  />
                ))}
              </div>
            </section>
          )
        })}
      </div>

      <Modal open={showNew} onClose={() => setShowNew(false)}>
        <h3 className="mb-2 text-lg font-bold">New customer</h3>
        <p className="text-sm text-muted">
          In the production system this opens a customer-creation form; the new record will
          default to the logged-in rep ({activeRep}). For the demo it's a stub.
        </p>
        <div className="mt-4 flex justify-end">
          <button
            onClick={() => setShowNew(false)}
            className="rounded-md bg-primary px-4 py-2 text-sm font-semibold text-white"
          >
            OK
          </button>
        </div>
      </Modal>
    </div>
  )
}

function RepHeader({
  isActive,
  code,
  name,
  count,
  onNewCustomer,
}: {
  isActive: boolean
  code: string
  name: string
  count: number
  onNewCustomer?: () => void
}) {
  return (
    <div
      className={`sticky top-[44px] z-[5] mb-2 flex items-center gap-3 rounded-md px-3 py-2 ${
        isActive
          ? 'border-l-4 border-primary bg-primary-light text-primary'
          : 'border-l-4 border-line bg-surface-alt text-muted'
      }`}
    >
      <span className={`font-mono text-sm font-bold ${isActive ? 'text-primary' : 'text-muted'}`}>{code}</span>
      <span className={`text-sm ${isActive ? 'font-semibold text-body' : 'text-muted'}`}>{name}</span>
      <span
        className={`rounded-full px-2 py-0.5 text-[11px] font-semibold ${
          isActive ? 'bg-primary text-white' : 'bg-line text-muted'
        }`}
      >
        {count} {count === 1 ? 'customer' : 'customers'}
      </span>
      {onNewCustomer && (
        <button
          onClick={onNewCustomer}
          className="ml-auto flex items-center gap-1 rounded-md bg-primary px-2.5 py-1 text-xs font-semibold text-white hover:bg-primary-dark"
        >
          <Plus size={13} /> New customer
        </button>
      )}
    </div>
  )
}

function CustomerCard({
  customer,
  selected,
  onClick,
  compact,
}: {
  customer: Customer
  selected: boolean
  onClick: () => void
  compact: boolean
}) {
  return (
    <button
      onClick={onClick}
      className={`relative rounded-lg border p-3 text-left transition ${
        selected
          ? 'border-primary bg-primary-light ring-2 ring-primary/30'
          : compact
            ? 'border-line bg-white hover:border-primary/40'
            : 'border-line bg-white hover:border-primary/60'
      }`}
    >
      <div className={`font-semibold ${compact ? 'text-sm' : 'text-body'}`}>{customer.name}</div>
      <div className={`text-xs text-muted ${compact ? 'truncate' : ''}`}>{customer.contact}</div>
      <div className="mt-1 text-[11px] uppercase text-muted">{customer.site}</div>
      {selected && (
        <span className="absolute right-2 top-2 flex h-5 w-5 items-center justify-center rounded-full bg-primary text-white">
          <Check size={12} />
        </span>
      )}
    </button>
  )
}
