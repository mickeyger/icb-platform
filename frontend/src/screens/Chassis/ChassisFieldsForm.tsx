// ChassisFieldsForm.tsx — WO v4.36b. The ONE chassis-fields form, shared by the Chassis page Edit modal
// and the Planning-ack panel so both present the same chassis information identically over a single source
// of truth (chassis_records). Purely presentational: controlled inputs only (no fetch, no save) — each
// wrapper owns the seed, the submit, and the per-field lock flags. Reuses ChassisModelSelect + DealerSelect.
import type { ReactNode } from 'react'
import { Lock } from 'lucide-react'
import { ChassisModelSelect } from './ChassisModelSelect'
import { DealerSelect } from './DealerSelect'

export interface ChassisFieldValues {
  customer_name: string
  make: string                       // "Chassis type" (chassis_records.make, via the DDM)
  dealer_id: number | null
  dealer_name?: string | null
  chassis_eta: string                // YYYY-MM-DD (persists onto the linked job, not the chassis)
  contact_person: string
  telephone: string
  vin: string
  tail_lift_code: string
  description: string
  notes: string
}

// Per-field read-only flags. A locked field renders a read-only display chip (consistent across both screens).
export interface ChassisFieldLocks {
  customer?: boolean; chassisType?: boolean; dealer?: boolean; eta?: boolean
  contact?: boolean; telephone?: boolean; vin?: boolean; tailLift?: boolean
  description?: boolean; notes?: boolean
}

const INPUT = 'mt-1 w-full rounded-md border border-line px-2 py-1.5 text-sm'
const LOCKED = 'mt-1 w-full rounded-md border border-line bg-surface-alt px-2 py-1.5 text-sm text-body'

function Locked({ testid, value, mono }: { testid?: string; value: string; mono?: boolean }) {
  return <div data-testid={testid} className={`${LOCKED}${mono ? ' font-mono' : ''}`}>{value || '—'}</div>
}

export function ChassisFieldsForm({
  values, onChange, locks = {}, hidden = [], etaLabel = 'Delivery ETA', etaHint, etaDisabled,
  vinNote, vinPlaceholder = '(filled when the chassis physically arrives)', tailLifts, testidPrefix = 'chassis',
  editNotice,
}: {
  values: ChassisFieldValues
  onChange: (patch: Partial<ChassisFieldValues>) => void
  locks?: ChassisFieldLocks
  hidden?: (keyof ChassisFieldValues)[]
  etaLabel?: string
  etaHint?: ReactNode
  etaDisabled?: boolean
  vinNote?: ReactNode
  vinPlaceholder?: string
  tailLifts: { code: string; supplier: string; model: string }[]
  testidPrefix?: string
  editNotice?: ReactNode               // WO v4.36.5 §3.3 — centralized "edits happen on the Chassis page" banner
}) {
  const show = (k: keyof ChassisFieldValues) => !hidden.includes(k)
  const tid = (s: string) => `${testidPrefix}-${s}`

  return (
    <div className="space-y-3">
      {/* WO v4.36.5 §3.3 — centralized read-only affordance: a non-editor surface (e.g. the Planning-ack
          read-only view) passes editNotice, so every chassis-fields display carries the same "edit on the
          Chassis page" signal. The Chassis-page Edit modal — the sole editor — omits it. */}
      {editNotice && (
        <div data-testid={tid('edit-notice')}
             className="flex items-center gap-2 rounded-md border border-line bg-surface-alt px-3 py-2 text-[11px] text-muted">
          <Lock size={12} className="shrink-0" />
          <span>{editNotice}</span>
        </div>
      )}
      {show('customer_name') && (
        <label className="block text-xs"><span className="font-semibold text-muted">Customer</span>
          {locks.customer
            ? <Locked testid={tid('customer')} value={values.customer_name} />
            : <input data-testid={tid('customer')} value={values.customer_name}
                     onChange={(e) => onChange({ customer_name: e.target.value })} className={INPUT} />}
        </label>
      )}

      {show('make') && (
        <label className="block text-xs"><span className="font-semibold text-muted">Chassis type</span>
          {locks.chassisType
            ? <div data-testid={tid('make-locked')} className={`${LOCKED} flex items-center justify-between`}>
                <span>{values.make || '—'}</span>
                <span className="text-[10px] font-semibold uppercase tracking-wide text-muted">attested · locked</span>
              </div>
            : <ChassisModelSelect testid={tid('make')} value={values.make}
                                  onChange={(v) => onChange({ make: v })} />}
        </label>
      )}

      {show('dealer_id') && (
        <label className="block text-xs"><span className="font-semibold text-muted">Chassis dealer <span className="text-[10px]">(supplier)</span></span>
          {locks.dealer
            ? <Locked testid={tid('dealer-locked')} value={values.dealer_name || '—'} />
            : <DealerSelect testid={tid('dealer')} value={values.dealer_id} valueName={values.dealer_name ?? ''}
                            onChange={(id, name) => onChange({ dealer_id: id, dealer_name: name })} />}
        </label>
      )}

      {show('chassis_eta') && (
        <label className="block text-xs"><span className="font-semibold text-muted">{etaLabel}</span>
          <input type="date" data-testid={tid('eta')} value={values.chassis_eta}
                 disabled={locks.eta || etaDisabled}
                 onChange={(e) => onChange({ chassis_eta: e.target.value })}
                 className={`${INPUT} disabled:bg-surface-alt`} />
          {etaHint && <span className="mt-1 block text-[10px] text-muted">{etaHint}</span>}
        </label>
      )}

      {(show('contact_person') || show('telephone')) && (
        <div className="grid grid-cols-2 gap-3">
          {show('contact_person') && (
            <label className="block text-xs"><span className="font-semibold text-muted">Contact</span>
              {locks.contact
                ? <Locked value={values.contact_person} />
                : <input data-testid={tid('contact')} value={values.contact_person}
                         onChange={(e) => onChange({ contact_person: e.target.value })} className={INPUT} />}
            </label>
          )}
          {show('telephone') && (
            <label className="block text-xs"><span className="font-semibold text-muted">Telephone</span>
              {locks.telephone
                ? <Locked value={values.telephone} />
                : <input data-testid={tid('telephone')} value={values.telephone}
                         onChange={(e) => onChange({ telephone: e.target.value })} className={INPUT} />}
            </label>
          )}
        </div>
      )}

      {show('vin') && (
        <label className="block text-xs"><span className="font-semibold text-muted">Chassis VIN</span>
          {locks.vin
            ? <Locked testid={tid('vin-locked')} value={values.vin} mono />
            : <input type="text" data-testid={tid('vin')} value={values.vin}
                     onChange={(e) => onChange({ vin: e.target.value })} placeholder={vinPlaceholder}
                     className={`${INPUT} font-mono`} />}
          {vinNote && <span className="mt-1 block text-[10px] text-muted">{vinNote}</span>}
        </label>
      )}

      {show('tail_lift_code') && (
        <label className="block text-xs"><span className="font-semibold text-muted">Tail lift</span>
          {locks.tailLift
            ? <Locked value={(tailLifts.find((l) => l.code === values.tail_lift_code) || {} as { supplier?: string; model?: string }).supplier
                      ? `${tailLifts.find((l) => l.code === values.tail_lift_code)!.supplier} ${tailLifts.find((l) => l.code === values.tail_lift_code)!.model}`
                      : (values.tail_lift_code || '—')} />
            : <select data-testid={tid('tail-lift')} value={values.tail_lift_code}
                      onChange={(e) => onChange({ tail_lift_code: e.target.value })}
                      className={`${INPUT} bg-white`}>
                <option value="">— select —</option>
                {tailLifts.map((l) => <option key={l.code} value={l.code}>{l.supplier} {l.model}</option>)}
              </select>}
        </label>
      )}

      {show('description') && (
        <label className="block text-xs"><span className="font-semibold text-muted">Description</span>
          {locks.description
            ? <Locked value={values.description} />
            : <input data-testid={tid('description')} value={values.description}
                     onChange={(e) => onChange({ description: e.target.value })} className={INPUT} />}
        </label>
      )}

      {show('notes') && (
        <label className="block text-xs"><span className="font-semibold text-muted">Notes</span>
          {locks.notes
            ? <Locked value={values.notes} />
            : <textarea data-testid={tid('notes')} value={values.notes} rows={2}
                        onChange={(e) => onChange({ notes: e.target.value })} className={INPUT} />}
        </label>
      )}
    </div>
  )
}
