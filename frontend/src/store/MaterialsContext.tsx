// MaterialsContext.tsx — domain state + mutators for the four Materials / Buying /
// Stores screens (Work Order v4.11). Mock implementation: holds the seed data in
// React state and fabricates PR numbers on raisePR. Real SAP integration
// (BAPI_PR_CREATE, OData stock/PO reads) lives behind the same surface — see
// WO v4.11 §3.7 and Proposal §11.10 Q8. Follows the CostingsContext pattern:
// state + useCallback mutators + a useMaterials() hook.

import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
  type ReactNode,
} from 'react'
import seed from '../data/icb_materials_data.json'

// ── Types ───────────────────────────────────────────────────────────────────

export type Urgency = 'critical' | 'order_now' | 'advisory' | 'comfortable'
export type SuggestionStatus = 'pending' | 'raised' | 'deferred'
export type CountStatus = 'pending' | 'confirmed' | 'discrepancy'
export type Dept = 'vacuum' | 'panelshop' | 'assy' | 'paint'

export interface Material {
  sap_code: string
  description: string
  supplier: string
  lead_days: number
  last_price: number
  abc_class: 'A' | 'B' | 'C'
  dept: Dept
}

export interface StockPosition {
  sap_code: string
  sap_stock: number
  allocated: number
  free: number
  open_po_qty: number
  open_po_eta: string | null
  last_refreshed: string
}

export interface DemandLine {
  sap_code: string
  qty: number
  need_by: string
  job_id: string
  week_bucket: string
}

export interface POSuggestion {
  id: number
  sap_code: string
  qty: number
  suggested_supplier: string
  last_price: number
  total: number
  need_by: string
  jobs_impacted: string[]
  urgency: Urgency
  status: SuggestionStatus
  pr_number?: string
  deferred_until?: string
  raised_at?: string
  raised_by?: string
  created_at: string
}

export interface StockCount {
  id: number
  sap_code: string
  bin: string
  sap_stock_at_count: number
  physical_count: number | null
  counted_by: string
  counted_at: string | null
  status: CountStatus
}

export interface DiscrepancyRecord {
  id: number
  stock_count_id: number
  raised_at: string
  raised_to_buyer: string
  notes: string | null
  resolved_at: string | null
}

export interface Supplier {
  name: string
  contact_person: string
  payment_terms: string
  phone?: string
}

// ── Derived helpers ─────────────────────────────────────────────────────────

/** Urgency classification by need-by vs today + supplier lead time. */
export function classifyUrgency(
  needByISO: string,
  leadDays: number,
  today: Date = new Date(),
): Urgency {
  const days = Math.ceil((+new Date(needByISO) - +today) / 86_400_000)
  if (days <= 10) return 'critical'
  if (days <= leadDays + 3) return 'order_now'
  if (days <= leadDays + 10) return 'advisory'
  return 'comfortable'
}

// ── Context ─────────────────────────────────────────────────────────────────

interface MaterialsValue {
  materials: Material[]
  stockPositions: StockPosition[]
  demandLines: DemandLine[]
  poSuggestions: POSuggestion[]
  stockCounts: StockCount[]
  discrepancies: DiscrepancyRecord[]
  suppliers: Supplier[]

  // Mutators (mock — in-memory optimistic updates)
  raisePR: (
    suggestionIds: number[],
    raisedBy?: string,
  ) => Promise<{ prNumber: string; suppliersAffected: string[]; total: number }>
  deferSuggestion: (suggestionId: number, until: string) => void
  overrideSupplier: (suggestionId: number, newSupplier: string, newPrice?: number) => void
  recordCount: (sapCode: string, bin: string, physical: number, countedBy: string) => StockCount
  notifyBuyerOfDiscrepancy: (stockCountId: number, buyerName: string) => DiscrepancyRecord
  resolveDiscrepancy: (discrepancyId: number, notes: string) => void
}

const MaterialsContext = createContext<MaterialsValue | null>(null)

export function MaterialsProvider({ children }: { children: ReactNode }) {
  const [materials] = useState<Material[]>(seed.materials as Material[])
  const [stockPositions] = useState<StockPosition[]>(seed.stock_positions as StockPosition[])
  const [demandLines] = useState<DemandLine[]>(seed.demand_lines as DemandLine[])
  const [poSuggestions, setPoSuggestions] = useState<POSuggestion[]>(
    seed.po_suggestions as POSuggestion[],
  )
  const [stockCounts, setStockCounts] = useState<StockCount[]>(seed.stock_counts as StockCount[])
  const [discrepancies, setDiscrepancies] = useState<DiscrepancyRecord[]>(
    seed.discrepancies as DiscrepancyRecord[],
  )
  const [suppliers] = useState<Supplier[]>(seed.suppliers as Supplier[])

  // Fabricated PR-number sequence (mock SAP BAPI_PR_CREATE).
  const [nextPrSeq, setNextPrSeq] = useState<number>(4500123456)

  const raisePR = useCallback(
    async (suggestionIds: number[], raisedBy = 'Buyer') => {
      // Simulate the SAP round-trip latency.
      await new Promise((r) => setTimeout(r, 150))
      const prNumber = String(nextPrSeq)
      setNextPrSeq((n) => n + 1)
      const nowISO = new Date().toISOString()
      let total = 0
      const suppliersAffected = new Set<string>()
      setPoSuggestions((prev) =>
        prev.map((s) => {
          if (!suggestionIds.includes(s.id)) return s
          total += s.total
          suppliersAffected.add(s.suggested_supplier)
          return { ...s, status: 'raised' as const, pr_number: prNumber, raised_at: nowISO, raised_by: raisedBy }
        }),
      )
      return { prNumber, suppliersAffected: Array.from(suppliersAffected), total }
    },
    [nextPrSeq],
  )

  const deferSuggestion = useCallback((suggestionId: number, until: string) => {
    setPoSuggestions((prev) =>
      prev.map((s) =>
        s.id === suggestionId ? { ...s, status: 'deferred' as const, deferred_until: until } : s,
      ),
    )
  }, [])

  const overrideSupplier = useCallback(
    (suggestionId: number, newSupplier: string, newPrice?: number) => {
      setPoSuggestions((prev) =>
        prev.map((s) => {
          if (s.id !== suggestionId) return s
          const price = newPrice ?? s.last_price
          return { ...s, suggested_supplier: newSupplier, last_price: price, total: price * s.qty }
        }),
      )
    },
    [],
  )

  const recordCount = useCallback(
    (sapCode: string, bin: string, physical: number, countedBy: string): StockCount => {
      const sap = stockPositions.find((s) => s.sap_code === sapCode)?.sap_stock ?? 0
      const status: CountStatus = physical === sap ? 'confirmed' : 'discrepancy'
      const newCount: StockCount = {
        id: Math.max(0, ...stockCounts.map((c) => c.id)) + 1,
        sap_code: sapCode,
        bin,
        sap_stock_at_count: sap,
        physical_count: physical,
        counted_by: countedBy,
        counted_at: new Date().toISOString(),
        status,
      }
      setStockCounts((prev) => [...prev, newCount])
      return newCount
    },
    [stockPositions, stockCounts],
  )

  const notifyBuyerOfDiscrepancy = useCallback(
    (stockCountId: number, buyerName: string): DiscrepancyRecord => {
      const rec: DiscrepancyRecord = {
        id: Math.max(0, ...discrepancies.map((d) => d.id)) + 1,
        stock_count_id: stockCountId,
        raised_at: new Date().toISOString(),
        raised_to_buyer: buyerName,
        notes: null,
        resolved_at: null,
      }
      setDiscrepancies((prev) => [...prev, rec])
      return rec
    },
    [discrepancies],
  )

  const resolveDiscrepancy = useCallback((discrepancyId: number, notes: string) => {
    setDiscrepancies((prev) =>
      prev.map((d) =>
        d.id === discrepancyId ? { ...d, notes, resolved_at: new Date().toISOString() } : d,
      ),
    )
  }, [])

  const value = useMemo<MaterialsValue>(
    () => ({
      materials,
      stockPositions,
      demandLines,
      poSuggestions,
      stockCounts,
      discrepancies,
      suppliers,
      raisePR,
      deferSuggestion,
      overrideSupplier,
      recordCount,
      notifyBuyerOfDiscrepancy,
      resolveDiscrepancy,
    }),
    [
      materials,
      stockPositions,
      demandLines,
      poSuggestions,
      stockCounts,
      discrepancies,
      suppliers,
      raisePR,
      deferSuggestion,
      overrideSupplier,
      recordCount,
      notifyBuyerOfDiscrepancy,
      resolveDiscrepancy,
    ],
  )

  return <MaterialsContext.Provider value={value}>{children}</MaterialsContext.Provider>
}

export function useMaterials(): MaterialsValue {
  const ctx = useContext(MaterialsContext)
  if (!ctx) throw new Error('useMaterials must be used within MaterialsProvider')
  return ctx
}
