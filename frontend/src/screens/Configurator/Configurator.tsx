import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Check, ChevronLeft, ChevronRight } from 'lucide-react'
import { data, demoJob, demoBom, demoBomTotal } from '../../data/mockData'
import { useAppData } from '../../store/AppDataContext'
import { zar, zarShort } from '../../lib/format'
import { Tooltip } from '../../components/ui/Tooltip'
import { AcceptedModal } from './AcceptedModal'
import { CustomerStep } from './CustomerStep'
import type { Customer, ChassisModel, BodyType, FridgeUnit, TailLift } from '../../data/types'

const STEPS = ['Customer', 'Chassis', 'Body Type', 'Fridge', 'Tail Lift', 'Extras', 'Review']
const STEP_KEYS = [
  'configurator.step_customer',
  'configurator.step_chassis',
  'configurator.step_body_type',
  'configurator.step_fridge',
  'configurator.step_tail_lift',
  'configurator.step_extras',
  'configurator.step_review',
]

const EXTRAS = [
  'Interior Lights x3',
  'Marker Lights x6',
  'Access Ladder',
  'Catwalk',
  'Evaporator Guard',
  'Escape Hatch',
  'Spare Wheel Carrier',
]

// Pre-filled selection state from the demo job 32891 so each demo starts ready.
export interface Selection {
  customer?: Customer
  chassis?: ChassisModel
  body?: BodyType
  fridge?: FridgeUnit
  lift?: TailLift
  extras: string[]
}

export function Configurator() {
  const nav = useNavigate()
  const { addAcceptedJob } = useAppData()
  const [step, setStep] = useState(0)
  const [accepted, setAccepted] = useState(false)

  const [sel, setSel] = useState<Selection>(() => ({
    customer: data.customers.find((c) => c.id === demoJob.customer_id),
    chassis: data.chassis_models.find((c) => c.code === demoJob.chassis_code),
    body: data.body_types.find((b) => b.code === demoJob.body_type),
    fridge: data.fridge_units.find((f) => f.code === demoJob.fridge_code),
    lift: data.tail_lifts.find((l) => l.code === demoJob.lift_code),
    extras: ['Interior Lights x3', 'Marker Lights x6'],
  }))

  // Running quote — uses the demo job's mock values.
  const cost = demoJob.cost_zar
  const sell = demoJob.selling_zar
  const markup = demoJob.markup_pct

  const canNext = (() => {
    switch (step) {
      case 0: return !!sel.customer
      case 1: return !!sel.chassis
      case 2: return !!sel.body
      case 3: return !!sel.fridge
      case 4: return !!sel.lift
      default: return true
    }
  })()

  const fridgeCategory = sel.chassis?.category === 'trailer' ? 'trailer' : 'truck'
  const fridges = data.fridge_units.filter(
    (f) => f.category === fridgeCategory || f.category === 'any',
  )

  function handleAccept() {
    addAcceptedJob({
      job_number: demoJob.job_number,
      customer_name: sel.customer?.name ?? '',
      description: demoJob.description,
      selling_zar: sell,
      accepted_at: new Date().toISOString(),
    })
    setAccepted(true)
  }

  return (
    <div className="flex min-h-[calc(100vh-96px)]">
      {/* Sidebar: steps + running quote */}
      <aside className="flex w-64 flex-col border-r border-line bg-white">
        <ol className="flex-1 p-4">
          {STEPS.map((label, i) => {
            const done = i < step
            const active = i === step
            return (
              <li
                key={label}
                onClick={() => i <= step && setStep(i)}
                className={`mb-1 flex items-center gap-2 rounded-md px-3 py-2 text-sm ${
                  active ? 'bg-primary-light font-semibold text-primary' : done ? 'cursor-pointer text-body' : 'text-muted'
                }`}
              >
                <span
                  className={`flex h-5 w-5 items-center justify-center rounded-full text-[11px] ${
                    done ? 'bg-status-green text-white' : active ? 'bg-primary text-white' : 'bg-surface-alt text-muted'
                  }`}
                >
                  {done ? <Check size={12} /> : i + 1}
                </span>
                {label}
              </li>
            )
          })}
        </ol>
        <Tooltip k="configurator.running_quote_sidebar" placement="top">
          <div className="border-t border-line bg-surface-alt p-4">
            <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted">Quote running</div>
            <div className="space-y-1 text-sm">
              <Line label="Cost" value={zarShort(cost)} />
              <Line label="Sell" value={zarShort(sell)} />
              <Line label="Markup" value={`${markup}%`} highlight />
            </div>
          </div>
        </Tooltip>
      </aside>

      {/* Main step area */}
      <section className="flex flex-1 flex-col p-6">
        <Tooltip k={STEP_KEYS[step]}>
          <h1 className="mb-1 inline-block text-lg font-bold text-body">
            Step {step + 1} of 7: {STEPS[step]}
          </h1>
        </Tooltip>
        <div className="mb-6 flex-1">
          {step === 0 && <CustomerStep sel={sel} setSel={setSel} />}
          {step === 1 && <ChassisStep sel={sel} setSel={setSel} />}
          {step === 2 && <BodyStep sel={sel} setSel={setSel} />}
          {step === 3 && <FridgeStep sel={sel} setSel={setSel} fridges={fridges} />}
          {step === 4 && <LiftStep sel={sel} setSel={setSel} />}
          {step === 5 && <ExtrasStep sel={sel} setSel={setSel} />}
          {step === 6 && <ReviewStep sel={sel} cost={cost} sell={sell} markup={markup} />}
        </div>

        <div className="flex items-center justify-between border-t border-line pt-4">
          <button
            onClick={() => setStep((s) => Math.max(0, s - 1))}
            disabled={step === 0}
            className="flex items-center gap-1 rounded-md px-4 py-2 text-sm font-medium text-primary disabled:opacity-30"
          >
            <ChevronLeft size={16} /> Back
          </button>
          {step < 6 ? (
            <button
              onClick={() => setStep((s) => s + 1)}
              disabled={!canNext}
              className="flex items-center gap-1 rounded-md bg-primary px-5 py-2 text-sm font-semibold text-white hover:bg-primary-dark disabled:opacity-40"
            >
              Next: {STEPS[step + 1]} <ChevronRight size={16} />
            </button>
          ) : (
            <Tooltip k="configurator.accepted_button" placement="top">
              <button
                onClick={handleAccept}
                className="flex items-center gap-2 rounded-md bg-status-green px-6 py-3 text-base font-bold text-white shadow hover:opacity-90"
              >
                <Check size={18} /> Accepted
              </button>
            </Tooltip>
          )}
        </div>
      </section>

      <AcceptedModal
        open={accepted}
        jobNumber={demoJob.job_number}
        onClose={() => {
          setAccepted(false)
          nav('/production')
        }}
      />
    </div>
  )
}

function Line({ label, value, highlight }: { label: string; value: string; highlight?: boolean }) {
  return (
    <div className="flex items-center justify-between">
      <span className="text-muted">{label}</span>
      <span className={`font-semibold tabular-nums ${highlight ? 'text-primary' : 'text-body'}`}>{value}</span>
    </div>
  )
}

// --- Card grid helpers ------------------------------------------------------
function Grid({ children }: { children: React.ReactNode }) {
  return <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">{children}</div>
}

function SelectCard({
  selected,
  onClick,
  children,
}: {
  selected: boolean
  onClick: () => void
  children: React.ReactNode
}) {
  return (
    <button
      onClick={onClick}
      className={`rounded-lg border p-3 text-left transition ${
        selected ? 'border-primary bg-primary-light ring-2 ring-primary/30' : 'border-line bg-white hover:border-primary/40'
      }`}
    >
      {children}
    </button>
  )
}

// --- Steps ------------------------------------------------------------------
type StepProps = { sel: Selection; setSel: React.Dispatch<React.SetStateAction<Selection>> }

function ChassisStep({ sel, setSel }: StepProps) {
  return (
    <Grid>
      {data.chassis_models.map((c) => (
        <SelectCard key={c.code} selected={sel.chassis?.code === c.code} onClick={() => setSel((s) => ({ ...s, chassis: c }))}>
          <div className="font-semibold text-body">{c.make}</div>
          <div className="text-sm text-body">{c.model}</div>
          <div className="mt-1 text-[11px] uppercase text-muted">{c.category} · {c.max_payload_kg.toLocaleString()}kg</div>
        </SelectCard>
      ))}
    </Grid>
  )
}

function BodyStep({ sel, setSel }: StepProps) {
  return (
    <Grid>
      {data.body_types.map((b) => (
        <SelectCard key={b.code} selected={sel.body?.code === b.code} onClick={() => setSel((s) => ({ ...s, body: b }))}>
          <div className="font-semibold text-body">{b.name}</div>
          <div className="mt-1 flex gap-1.5">
            <span className="rounded bg-surface-alt px-1.5 py-0.5 text-[10px] font-semibold uppercase text-muted">{b.complexity}</span>
            <span className="rounded bg-primary-light px-1.5 py-0.5 text-[10px] font-semibold uppercase text-primary">{b.panel_route}</span>
          </div>
        </SelectCard>
      ))}
    </Grid>
  )
}

function FridgeStep({ sel, setSel, fridges }: StepProps & { fridges: FridgeUnit[] }) {
  return (
    <div>
      <p className="mb-3 text-xs text-muted">Filtered for {sel.chassis?.category === 'trailer' ? 'trailer' : 'truck'} bodies.</p>
      <Grid>
        {fridges.map((f) => (
          <SelectCard key={f.code} selected={sel.fridge?.code === f.code} onClick={() => setSel((s) => ({ ...s, fridge: f }))}>
            <div className="font-semibold text-body">{f.supplier}</div>
            <div className="text-sm text-body">{f.model}</div>
            <div className="mt-1 text-[11px] uppercase text-muted">{f.approx_weight_kg ? `${f.approx_weight_kg}kg` : '—'}</div>
          </SelectCard>
        ))}
      </Grid>
    </div>
  )
}

function LiftStep({ sel, setSel }: StepProps) {
  return (
    <Grid>
      {data.tail_lifts.map((l) => (
        <SelectCard key={l.code} selected={sel.lift?.code === l.code} onClick={() => setSel((s) => ({ ...s, lift: l }))}>
          <div className="font-semibold text-body">{l.supplier}</div>
          <div className="text-sm text-body">{l.model}</div>
          <div className="mt-1 text-[11px] uppercase text-muted">{l.capacity_kg ? `${l.capacity_kg.toLocaleString()}kg` : '—'}</div>
        </SelectCard>
      ))}
    </Grid>
  )
}

function ExtrasStep({ sel, setSel }: StepProps) {
  const toggle = (x: string) =>
    setSel((s) => ({ ...s, extras: s.extras.includes(x) ? s.extras.filter((e) => e !== x) : [...s.extras, x] }))
  return (
    <div className="grid grid-cols-2 gap-2 lg:grid-cols-3">
      {EXTRAS.map((x) => {
        const on = sel.extras.includes(x)
        return (
          <button
            key={x}
            onClick={() => toggle(x)}
            className={`flex items-center gap-2 rounded-md border p-3 text-left text-sm ${
              on ? 'border-primary bg-primary-light' : 'border-line bg-white'
            }`}
          >
            <span className={`flex h-5 w-5 items-center justify-center rounded border ${on ? 'border-primary bg-primary text-white' : 'border-line'}`}>
              {on && <Check size={12} />}
            </span>
            {x}
          </button>
        )
      })}
    </div>
  )
}

function ReviewStep({ sel, cost, sell, markup }: { sel: Selection; cost: number; sell: number; markup: number }) {
  return (
    <div className="grid gap-4 lg:grid-cols-3">
      <div className="lg:col-span-2">
        <div className="overflow-hidden rounded-lg border border-line">
          <table className="w-full text-sm">
            <thead className="bg-primary text-left text-white">
              <tr>
                <th className="px-3 py-2 font-semibold">Item</th>
                <th className="px-3 py-2 font-semibold">Description</th>
                <th className="px-3 py-2 text-right font-semibold">Qty</th>
                <th className="px-3 py-2 text-right font-semibold">Cost</th>
              </tr>
            </thead>
            <tbody>
              {demoBom.map((l, i) => (
                <tr key={l.sap_item_code} className={i % 2 ? 'bg-surface-alt' : 'bg-white'}>
                  <td className="px-3 py-2 font-mono text-xs">{l.sap_item_code}</td>
                  <td className="px-3 py-2">{l.description}</td>
                  <td className="px-3 py-2 text-right tabular-nums">{l.qty}</td>
                  <td className="px-3 py-2 text-right tabular-nums">{zar(l.cost_zar)}</td>
                </tr>
              ))}
              <tr className="border-t border-line font-semibold">
                <td className="px-3 py-2" colSpan={3}>Total cost</td>
                <td className="px-3 py-2 text-right tabular-nums">{zar(demoBomTotal)}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
      <div className="space-y-3">
        <div className="rounded-lg border border-line bg-white p-4">
          <div className="text-sm font-semibold text-body">{sel.customer?.name}</div>
          <div className="text-xs text-muted">{demoJob.description}</div>
          <dl className="mt-3 space-y-1 text-sm">
            <Line label="Chassis" value={sel.chassis?.model ?? '—'} />
            <Line label="Body" value={sel.body?.name ?? '—'} />
            <Line label="Fridge" value={sel.fridge?.model ?? '—'} />
            <Line label="Tail lift" value={sel.lift?.model ?? '—'} />
            <Line label="Extras" value={String(sel.extras.length)} />
          </dl>
        </div>
        <div className="rounded-lg border border-primary bg-primary-light p-4">
          <Line label="Total cost" value={zar(cost)} />
          <Line label="Selling price" value={zar(sell)} highlight />
          <Line label="Markup" value={`${markup}%`} highlight />
        </div>
      </div>
    </div>
  )
}
