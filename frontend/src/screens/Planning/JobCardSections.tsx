// JobCardSections.tsx — WO v4.31 §3.2. The job-card modal enrichment: three READ-ONLY sections
// rendered inside the Planning Board slot-detail panel (LiveSlotDetail) from the enriched
// GET /api/production-jobs/{id}: (1) chassis detail — latest VCL photos/checklist/condition notes,
// (2) current-BOM lines, (3) bay context. No write paths (§0.5).
//
// Per-role: the BOM PRICE columns (unit price / line total / grand total) are hidden for the
// `workshop` role at RENDER time — a deliberate display choice, NOT an auth gate. The fetch is
// identical for every role; only the column render is conditional (BA lock 2026-06-10). A null
// unit_price (unresolved BOM line) renders an em-dash, never "null"/"0.00".
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Camera, ClipboardList, MapPin, Package, Truck } from 'lucide-react'
import { apiGet, handleApiError } from '../../lib/api'
import { useToast } from '../../components/ui/toast'
import { useAppData } from '../../store/AppDataContext'
import { Skeleton } from '../../components/ui/feedback'
import { dmy, zar } from '../../lib/format'
import type { ChassisRecordDetail } from '../Chassis/types'

export interface JobCardBomLine {
  sap_code: string
  description?: string | null
  qty: number
  unit_price?: number | null
  line_total?: number | null
  section?: string | null
}

export interface JobCardBom {
  id: number
  version: number
  bom_status: string                       // complete | incomplete | manual
  grand_total?: number | null
  generated_at?: string | null
  lines: JobCardBomLine[]
}

interface JobCardDetail {
  current_bom: JobCardBom | null
  chassis: ChassisRecordDetail | null
  current_assembly_bay_code: string | null
  assembly_assigned_at: string | null
}

const money = (v?: number | null) => (v == null ? '—' : zar(v))

function SectionHead({ icon, label }: { icon: React.ReactNode; label: string }) {
  return (
    <div className="mb-2 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-muted">
      {icon} {label}
    </div>
  )
}

function Placeholder({ text }: { text: string }) {
  return (
    <div className="rounded-md border border-dashed border-line bg-surface-alt p-3 text-center text-xs text-muted">
      {text}
    </div>
  )
}

export function JobCardSections({ jobId }: { jobId: number }) {
  const toast = useToast()
  const { sessionRole } = useAppData()
  // Workshop sees the BOM lines but NOT pricing — render-time column omit, not an auth gate (§3.2).
  const hidePrices = sessionRole === 'workshop'
  const [detail, setDetail] = useState<JobCardDetail | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let live = true
    setLoading(true)
    setDetail(null)
    apiGet<JobCardDetail>(`/api/production-jobs/${jobId}`)
      .then((d) => { if (live) setDetail(d) })
      .catch((e) => handleApiError(e, toast.push))
      .finally(() => { if (live) setLoading(false) })
    return () => { live = false }
  }, [jobId, toast])

  if (loading) return <Skeleton rows={4} />
  if (!detail) return null

  const chassis = detail.chassis
  // Latest VCL = the highest-cycle VCL (events arrive ordered by cycle_number asc).
  const vcl = chassis ? ([...chassis.events].filter((e) => e.event_type === 'VCL').pop() ?? null) : null
  const bom = detail.current_bom

  return (
    <>
      {/* 1 — Chassis detail (latest VCL) */}
      <div className="rounded-md border border-line p-3" data-testid="jobcard-chassis">
        <SectionHead icon={<Truck size={13} />} label="Chassis" />
        {chassis ? (
          <div className="space-y-2 text-sm">
            {/* WO v4.36a §3.5d Patch 1 — jump to the full Chassis page (same-tab); only when linked */}
            <Link to={`/chassis/${chassis.id}`} data-testid="jobcard-open-chassis"
                  className="inline-flex items-center gap-1 text-xs font-semibold text-primary hover:underline">
              Open Chassis page →
            </Link>
            <div className="flex flex-wrap items-baseline justify-between gap-1">
              <span className="font-mono text-xs font-semibold">{chassis.vin}</span>
              <span className="text-xs text-muted">{[chassis.make, chassis.model].filter(Boolean).join(' ') || ''}</span>
            </div>
            {vcl ? (
              <>
                <div className="text-xs text-muted">
                  Booked in {vcl.event_date ? dmy(vcl.event_date) : '—'}
                  {vcl.created_by ? ` · by ${vcl.created_by}` : ''} (cycle {vcl.cycle_number})
                </div>
                {vcl.checklist_json && Object.keys(vcl.checklist_json).length > 0 && (
                  <div className="rounded-md bg-surface-alt p-2">
                    <div className="mb-1 flex items-center gap-1 text-[11px] font-semibold text-muted">
                      <ClipboardList size={12} /> VCL checklist
                    </div>
                    <div className="grid grid-cols-2 gap-x-3 gap-y-0.5 text-xs">
                      {Object.entries(vcl.checklist_json).map(([k, v]) => (
                        <div key={k} className="flex items-center justify-between gap-2">
                          <span className="truncate text-muted">{k.replace(/_/g, ' ')}</span>
                          {typeof v === 'boolean' ? (
                            <span className={v ? 'font-semibold text-status-green' : 'font-semibold text-status-red'}>
                              {v ? '✓' : '✗'}
                            </span>
                          ) : (
                            <span className="truncate font-medium">{String(v)}</span>
                          )}
                        </div>
                      ))}
                    </div>
                  </div>
                )}
                {vcl.notes && (
                  <div className="rounded-md border border-line bg-white p-2 text-xs">
                    <span className="font-semibold text-muted">Condition notes: </span>
                    {vcl.notes}
                  </div>
                )}
                {vcl.photos.length > 0 && (
                  <div>
                    <div className="mb-1 flex items-center gap-1 text-[11px] font-semibold text-muted">
                      <Camera size={12} /> Photos ({vcl.photos.length})
                    </div>
                    <div className="flex flex-wrap gap-1.5">
                      {vcl.photos.map((p) => (
                        <img
                          key={p.id}
                          src={p.url ?? ''}
                          alt={p.caption ?? p.original_filename ?? 'chassis photo'}
                          className="h-14 w-14 rounded-md border border-line object-cover"
                        />
                      ))}
                    </div>
                  </div>
                )}
              </>
            ) : (
              <div className="text-xs text-muted">No VCL captured yet for this chassis.</div>
            )}
          </div>
        ) : (
          <Placeholder text="Chassis pending — not yet received" />
        )}
      </div>

      {/* 2 — BOM lines (current generated_bom) */}
      <div className="rounded-md border border-line p-3" data-testid="jobcard-bom">
        <SectionHead icon={<Package size={13} />} label="Bill of materials" />
        {bom ? (
          <div className="space-y-2">
            <div className="flex items-center justify-between text-xs">
              <span className="text-muted">
                v{bom.version}
                {bom.generated_at ? ` · generated ${dmy(bom.generated_at)}` : ''}
              </span>
              <span
                className={`rounded-full px-2 py-0.5 text-[10px] font-bold uppercase ${
                  bom.bom_status === 'complete'
                    ? 'bg-status-green/15 text-status-green'
                    : 'bg-status-amber/15 text-status-amber'
                }`}
              >
                {bom.bom_status}
              </span>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b border-line text-left text-muted">
                    <th className="py-1 pr-2 font-semibold">SAP code</th>
                    <th className="py-1 pr-2 font-semibold">Description</th>
                    <th className="py-1 pr-2 text-right font-semibold">Qty</th>
                    {!hidePrices && <th className="py-1 pr-2 text-right font-semibold">Unit price</th>}
                    {!hidePrices && <th className="py-1 text-right font-semibold">Line total</th>}
                  </tr>
                </thead>
                <tbody>
                  {bom.lines.map((l, i) => (
                    <tr key={i} className="border-b border-line/60 align-top">
                      <td className="py-1 pr-2 font-mono">{l.sap_code}</td>
                      <td className="py-1 pr-2">
                        {l.description || '—'}
                        {l.section && <span className="block text-[10px] text-muted">{l.section}</span>}
                      </td>
                      <td className="py-1 pr-2 text-right tabular-nums">{l.qty}</td>
                      {!hidePrices && <td className="py-1 pr-2 text-right tabular-nums">{money(l.unit_price)}</td>}
                      {!hidePrices && <td className="py-1 text-right tabular-nums">{money(l.line_total)}</td>}
                    </tr>
                  ))}
                </tbody>
                {!hidePrices && (
                  <tfoot>
                    <tr>
                      <td colSpan={4} className="py-1 pr-2 text-right text-[11px] font-semibold text-muted">
                        Grand total
                      </td>
                      <td className="py-1 text-right font-semibold tabular-nums">{money(bom.grand_total)}</td>
                    </tr>
                  </tfoot>
                )}
              </table>
            </div>
          </div>
        ) : (
          <Placeholder text="BOM not yet generated" />
        )}
      </div>

      {/* 3 — Bay context (renders only when a chassis exists; §3.2 state mapping, BA 10 Jun) */}
      {chassis && (
        <div className="rounded-md border border-line p-3" data-testid="jobcard-bay">
          <SectionHead icon={<MapPin size={13} />} label="Bay" />
          <BayContext
            chassis={chassis}
            bayCode={detail.current_assembly_bay_code}
            assignedAt={detail.assembly_assigned_at}
          />
        </div>
      )}
    </>
  )
}

function BayContext({
  chassis,
  bayCode,
  assignedAt,
}: {
  chassis: ChassisRecordDetail
  bayCode: string | null
  assignedAt: string | null
}) {
  if (chassis.status === 'in_assembly' && bayCode) {
    return (
      <div className="text-sm">
        <span className="font-semibold text-status-green">{bayCode}</span>
        {assignedAt && <span className="text-xs text-muted"> · since {dmy(assignedAt)}</span>}
      </div>
    )
  }
  if (chassis.status === 'in_workshop') {
    return <div className="text-sm">Parking (yard) <span className="text-xs text-muted">· no bay assigned</span></div>
  }
  if (chassis.status === 'dispatched') {
    return <div className="text-sm text-muted">Dispatched — workshop cycle closed</div>
  }
  return <div className="text-sm text-muted">{chassis.status.replace(/_/g, ' ')}</div>
}
