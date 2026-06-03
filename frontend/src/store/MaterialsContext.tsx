// MaterialsContext.tsx — domain state + mutators for the Materials / Buying / Stores
// screens. WO v4.17 (Phase 2C-1): now a live/mock context. In LIVE mode it reads the
// v4.15 APIs and POSTs mutations (pessimistic → await → refetch); if the backend is
// unreachable it falls back to the bundled seed (MOCK mode) so the demo still works.
// Mirrors the live/mock pattern proven in CostingsContext, via the shared lib/api.

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react'
import seed from '../data/icb_materials_data.json'
import { apiGet, apiPost, handleApiError, mesAutoLogin } from '../lib/api'
import { useToast } from '../components/ui/toast'
import { useAppData } from './AppDataContext'

// ── Types ───────────────────────────────────────────────────────────────────
export type Urgency = 'critical' | 'order_now' | 'advisory' | 'comfortable'
export type SuggestionStatus = 'pending' | 'raised' | 'deferred'
export type CountStatus = 'pending' | 'confirmed' | 'discrepancy'
export type Dept = 'vacuum' | 'panelshop' | 'assy' | 'paint'
export type ApiMode = 'live' | 'mock' | 'loading'

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
export function classifyUrgency(needByISO: string, leadDays: number, today: Date = new Date()): Urgency {
  const days = Math.ceil((+new Date(needByISO) - +today) / 86_400_000)
  if (days <= 10) return 'critical'
  if (days <= leadDays + 3) return 'order_now'
  if (days <= leadDays + 10) return 'advisory'
  return 'comfortable'
}

// ── API response shapes (v4.15) + mappers to the interfaces above ─────────────
interface ApiStock {
  sap_code: string; sap_stock: number; allocated: number; free: number
  open_po_qty: number; open_po_eta: string | null; last_refreshed: string
}
interface ApiMaterial {
  sap_code: string; description: string; supplier: string; lead_days: number
  last_price: number; abc_class: 'A' | 'B' | 'C'; dept: Dept; stock: ApiStock | null
}
interface ApiStockCount {
  id: number; sap_code: string; bin: string | null; sap_stock_at_count: number | null
  physical_count: number | null; counted_by_name: string | null; counted_at: string | null; status: CountStatus
}
interface ApiDiscrepancy {
  id: number; stock_count_id: number; raised_at: string | null
  raised_to_buyer_name: string | null; notes: string | null; resolved_at: string | null
}
interface ApiPO {
  id: number; sap_code: string; qty: number; suggested_supplier: string; last_price: number
  total: number; need_by: string; jobs_impacted: string[] | null; urgency: Urgency
  status: SuggestionStatus; pr_number: string | null; deferred_until: string | null
  raised_at: string | null; raised_by_name: string | null; created_at: string
}
interface ApiDemandLine {
  sap_code: string; qty: number; need_by: string; job_ref: string | null; week_bucket: string
}
interface ApiSupplier { name: string; contact_person: string; payment_terms: string; phone?: string }
interface ApiBulkRaise { pr_numbers: string[]; raised: ApiPO[]; skipped: { id: number; reason: string }[] }

const toMaterial = (m: ApiMaterial): Material => ({
  sap_code: m.sap_code, description: m.description, supplier: m.supplier,
  lead_days: m.lead_days, last_price: m.last_price, abc_class: m.abc_class, dept: m.dept,
})
const toStockCount = (c: ApiStockCount): StockCount => ({
  id: c.id, sap_code: c.sap_code, bin: c.bin ?? '', sap_stock_at_count: c.sap_stock_at_count ?? 0,
  physical_count: c.physical_count, counted_by: c.counted_by_name ?? '', counted_at: c.counted_at, status: c.status,
})
const toDiscrepancy = (d: ApiDiscrepancy): DiscrepancyRecord => ({
  id: d.id, stock_count_id: d.stock_count_id, raised_at: d.raised_at ?? '',
  raised_to_buyer: d.raised_to_buyer_name ?? '', notes: d.notes, resolved_at: d.resolved_at,
})
const toPO = (p: ApiPO): POSuggestion => ({
  id: p.id, sap_code: p.sap_code, qty: p.qty, suggested_supplier: p.suggested_supplier,
  last_price: p.last_price, total: p.total, need_by: p.need_by, jobs_impacted: p.jobs_impacted ?? [],
  urgency: p.urgency, status: p.status, pr_number: p.pr_number ?? undefined,
  deferred_until: p.deferred_until ?? undefined, raised_at: p.raised_at ?? undefined,
  raised_by: p.raised_by_name ?? undefined, created_at: p.created_at,
})
const toDemandLine = (d: ApiDemandLine): DemandLine => ({
  sap_code: d.sap_code, qty: d.qty, need_by: d.need_by, job_id: d.job_ref ?? '', week_bucket: d.week_bucket,
})

// ── Context ─────────────────────────────────────────────────────────────────
interface MaterialsValue {
  mode: ApiMode
  lastUpdated: Date | null
  refresh: () => Promise<void>
  materials: Material[]
  stockPositions: StockPosition[]
  demandLines: DemandLine[]
  poSuggestions: POSuggestion[]
  stockCounts: StockCount[]
  discrepancies: DiscrepancyRecord[]
  suppliers: Supplier[]
  // Mutators — pessimistic in live mode (await API → refetch); in-memory in mock.
  raisePR: (suggestionIds: number[], raisedBy?: string) => Promise<{ prNumber: string; suppliersAffected: string[]; total: number }>
  deferSuggestion: (suggestionId: number, until: string) => Promise<void>
  overrideSupplier: (suggestionId: number, newSupplier: string, newPrice?: number) => Promise<void>
  recordCount: (sapCode: string, bin: string, physical: number, countedBy: string) => Promise<StockCount>
  notifyBuyerOfDiscrepancy: (stockCountId: number, buyerName: string) => Promise<DiscrepancyRecord>
  resolveDiscrepancy: (discrepancyId: number, notes: string) => Promise<void>
}

const MaterialsContext = createContext<MaterialsValue | null>(null)

export function MaterialsProvider({ children }: { children: ReactNode }) {
  const toast = useToast()
  const [mode, setMode] = useState<ApiMode>('loading')
  const [materials, setMaterials] = useState<Material[]>(seed.materials as Material[])
  const [stockPositions, setStockPositions] = useState<StockPosition[]>(seed.stock_positions as StockPosition[])
  const [demandLines, setDemandLines] = useState<DemandLine[]>(seed.demand_lines as DemandLine[])
  const [poSuggestions, setPoSuggestions] = useState<POSuggestion[]>(seed.po_suggestions as POSuggestion[])
  const [stockCounts, setStockCounts] = useState<StockCount[]>(seed.stock_counts as StockCount[])
  const [discrepancies, setDiscrepancies] = useState<DiscrepancyRecord[]>(seed.discrepancies as DiscrepancyRecord[])
  const [suppliers, setSuppliers] = useState<Supplier[]>(seed.suppliers as Supplier[])
  const [nextPrSeq, setNextPrSeq] = useState<number>(4500123456) // mock-only PR sequence
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null)

  // Granular live refetchers.
  const refetchPO = useCallback(async () => {
    setPoSuggestions((await apiGet<ApiPO[]>('/api/po-suggestions')).map(toPO))
  }, [])
  const refetchCounts = useCallback(async () => {
    setStockCounts((await apiGet<ApiStockCount[]>('/api/stock-counts')).map(toStockCount))
  }, [])
  const refetchDiscrepancies = useCallback(async () => {
    setDiscrepancies((await apiGet<ApiDiscrepancy[]>('/api/discrepancies')).map(toDiscrepancy))
  }, [])

  // refetch() = reads only (no autologin). Used by the Refresh button AND the
  // branch-switch signal (WO v4.18 §3.5/§4.6). bootstrap() adds the one-shot
  // autologin and runs once on mount.
  const refetch = useCallback(async () => {
    try {
      const [mats, counts, discs, pos, demand, sups] = await Promise.all([
        apiGet<ApiMaterial[]>('/api/mes-materials'),
        apiGet<ApiStockCount[]>('/api/stock-counts'),
        apiGet<ApiDiscrepancy[]>('/api/discrepancies'),
        apiGet<ApiPO[]>('/api/po-suggestions'),
        apiGet<ApiDemandLine[]>('/api/demand-lines'), // raw lines (drill needs per-job detail)
        apiGet<ApiSupplier[]>('/api/suppliers'),
      ])
      setMaterials(mats.map(toMaterial))
      setStockPositions(mats.filter((m) => m.stock).map((m) => m.stock as ApiStock))
      setStockCounts(counts.map(toStockCount))
      setDiscrepancies(discs.map(toDiscrepancy))
      setPoSuggestions(pos.map(toPO))
      setDemandLines(demand.map(toDemandLine))
      setSuppliers(sups as Supplier[])
      setMode('live')
    } catch {
      // Backend unreachable / unauthorised → keep the seed, run in mock mode.
      setMode('mock')
    }
    setLastUpdated(new Date())
  }, [])

  // Bootstrap once on mount: mint the session (deduped), then read.
  useEffect(() => {
    void (async () => {
      await mesAutoLogin()
      await refetch()
    })()
  }, [refetch])

  // Branch-changed signal (§4.4): re-scope on an actual active-branch switch.
  // Skip the initial null→branch resolution — bootstrap already loaded.
  const { activeBranch } = useAppData()
  const prevBranchId = useRef<number | null | undefined>(undefined)
  useEffect(() => {
    const id = activeBranch?.id ?? null
    const prev = prevBranchId.current
    prevBranchId.current = id
    // Refetch only on a real branch switch — skip mount + the initial
    // null→default-branch resolution (bootstrap already loaded that branch).
    if (prev === undefined || prev === null || id === null) return
    if (prev !== id) void refetch()
  }, [activeBranch?.id, refetch])

  // ── Mutators ────────────────────────────────────────────────────────────────
  const raisePR = useCallback(
    async (suggestionIds: number[], raisedBy = 'Buyer') => {
      if (mode === 'live') {
        try {
          const res = await apiPost<ApiBulkRaise>('/api/po-suggestions/raise', { ids: suggestionIds })
          await refetchPO()
          const suppliersAffected = Array.from(new Set(res.raised.map((r) => r.suggested_supplier)))
          const total = res.raised.reduce((a, r) => a + (r.total ?? 0), 0)
          return { prNumber: res.pr_numbers.join(', ') || '—', suppliersAffected, total }
        } catch (e) {
          handleApiError(e, toast.push)
          throw e
        }
      }
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
    [mode, nextPrSeq, refetchPO, toast],
  )

  const deferSuggestion = useCallback(
    async (suggestionId: number, until: string) => {
      if (mode === 'live') {
        try {
          await apiPost(`/api/po-suggestions/${suggestionId}/defer`, { deferred_until: until })
          await refetchPO()
        } catch (e) {
          handleApiError(e, toast.push)
        }
        return
      }
      setPoSuggestions((prev) =>
        prev.map((s) => (s.id === suggestionId ? { ...s, status: 'deferred' as const, deferred_until: until } : s)),
      )
    },
    [mode, refetchPO, toast],
  )

  const overrideSupplier = useCallback(
    async (suggestionId: number, newSupplier: string, newPrice?: number) => {
      if (mode === 'live') {
        try {
          await apiPost(`/api/po-suggestions/${suggestionId}/override-supplier`, {
            supplier_name: newSupplier,
            last_price: newPrice,
          })
          await refetchPO()
        } catch (e) {
          handleApiError(e, toast.push)
        }
        return
      }
      setPoSuggestions((prev) =>
        prev.map((s) => {
          if (s.id !== suggestionId) return s
          const price = newPrice ?? s.last_price
          return { ...s, suggested_supplier: newSupplier, last_price: price, total: price * s.qty }
        }),
      )
    },
    [mode, refetchPO, toast],
  )

  const recordCount = useCallback(
    async (sapCode: string, bin: string, physical: number, countedBy: string): Promise<StockCount> => {
      if (mode === 'live') {
        try {
          const created = await apiPost<ApiStockCount>('/api/stock-counts', {
            sap_code: sapCode,
            bin,
            physical_count: physical,
          })
          await refetchCounts()
          return toStockCount(created)
        } catch (e) {
          handleApiError(e, toast.push)
          throw e
        }
      }
      const sap = stockPositions.find((s) => s.sap_code === sapCode)?.sap_stock ?? 0
      const status: CountStatus = physical === sap ? 'confirmed' : 'discrepancy'
      const newCount: StockCount = {
        id: Math.max(0, ...stockCounts.map((c) => c.id)) + 1,
        sap_code: sapCode, bin, sap_stock_at_count: sap, physical_count: physical,
        counted_by: countedBy, counted_at: new Date().toISOString(), status,
      }
      setStockCounts((prev) => [...prev, newCount])
      return newCount
    },
    [mode, stockPositions, stockCounts, refetchCounts, toast],
  )

  const notifyBuyerOfDiscrepancy = useCallback(
    async (stockCountId: number, buyerName: string): Promise<DiscrepancyRecord> => {
      if (mode === 'live') {
        try {
          const created = await apiPost<ApiDiscrepancy>(`/api/stock-counts/${stockCountId}/raise-discrepancy`, {
            raised_to_buyer_name: buyerName,
          })
          await Promise.all([refetchDiscrepancies(), refetchCounts()])
          return toDiscrepancy(created)
        } catch (e) {
          handleApiError(e, toast.push)
          throw e
        }
      }
      const rec: DiscrepancyRecord = {
        id: Math.max(0, ...discrepancies.map((d) => d.id)) + 1,
        stock_count_id: stockCountId, raised_at: new Date().toISOString(),
        raised_to_buyer: buyerName, notes: null, resolved_at: null,
      }
      setDiscrepancies((prev) => [...prev, rec])
      return rec
    },
    [mode, discrepancies, refetchDiscrepancies, refetchCounts, toast],
  )

  const resolveDiscrepancy = useCallback(
    async (discrepancyId: number, notes: string) => {
      if (mode === 'live') {
        try {
          await apiPost(`/api/discrepancies/${discrepancyId}/resolve`, { resolution_notes: notes })
          await refetchDiscrepancies()
        } catch (e) {
          handleApiError(e, toast.push)
        }
        return
      }
      setDiscrepancies((prev) =>
        prev.map((d) => (d.id === discrepancyId ? { ...d, notes, resolved_at: new Date().toISOString() } : d)),
      )
    },
    [mode, refetchDiscrepancies, toast],
  )

  const value = useMemo<MaterialsValue>(
    () => ({
      mode, lastUpdated, refresh: refetch,
      materials, stockPositions, demandLines, poSuggestions, stockCounts, discrepancies, suppliers,
      raisePR, deferSuggestion, overrideSupplier, recordCount, notifyBuyerOfDiscrepancy, resolveDiscrepancy,
    }),
    [
      mode, lastUpdated, refetch, materials, stockPositions, demandLines, poSuggestions, stockCounts, discrepancies, suppliers,
      raisePR, deferSuggestion, overrideSupplier, recordCount, notifyBuyerOfDiscrepancy, resolveDiscrepancy,
    ],
  )

  return <MaterialsContext.Provider value={value}>{children}</MaterialsContext.Provider>
}

export function useMaterials(): MaterialsValue {
  const ctx = useContext(MaterialsContext)
  if (!ctx) throw new Error('useMaterials must be used within MaterialsProvider')
  return ctx
}
