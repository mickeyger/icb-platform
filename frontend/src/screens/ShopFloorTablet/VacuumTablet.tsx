import { useState } from 'react'
import {
  ClipboardList,
  CheckSquare,
  Camera,
  MessageSquare,
  ChevronRight,
  Clock,
  Check,
  X,
  AlertTriangle,
} from 'lucide-react'
import { data } from '../../data/mockData'
import { hoursToHm } from '../../lib/format'
import { Modal } from '../../components/ui/overlays'
import { Tooltip } from '../../components/ui/Tooltip'
import type { PickingSlipItem, SignoffItem } from '../../data/types'

type PickState = 'unchecked' | 'picked' | 'short'
type SignState = 'pending' | 'pass' | 'fail'

export function VacuumTablet() {
  const t = data.vacuum_bay_tablet
  const wo = t.current_work_order

  const [picks, setPicks] = useState<PickState[]>(
    wo.picking_slip.map((p) => (p.status === 'short' ? 'short' : 'unchecked')),
  )
  const [signs, setSigns] = useState<SignState[]>(wo.signoff_items.map(() => 'pending'))
  const [modal, setModal] = useState<null | 'photo' | 'comment' | 'time' | 'confirm' | 'done'>(null)
  const [comment, setComment] = useState('')

  const cyclePick = (i: number) =>
    setPicks((p) => p.map((s, j) => (j === i ? (s === 'unchecked' ? 'picked' : s === 'picked' ? 'short' : 'unchecked') : s)))
  const cycleSign = (i: number) =>
    setSigns((s) => s.map((v, j) => (j === i ? (v === 'pending' ? 'pass' : v === 'pass' ? 'fail' : 'pending') : v)))

  const allAnswered = signs.every((s) => s !== 'pending')
  const elapsedOver = wo.elapsed_hours > wo.planned_hours

  return (
    <div className="mx-auto max-w-5xl p-4 text-[17px]">
      {/* Header */}
      <Tooltip k="tablet_vacuum.header_bar">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2 rounded-lg bg-primary px-4 py-3 text-white">
        <div className="text-2xl font-bold">{t.bay_name}</div>
        <div className="text-base">Operator: <span className="font-semibold">{t.operator}</span></div>
        <div className="text-base">Shift: {t.shift_start}–</div>
      </div>
      </Tooltip>

      {/* Current WO */}
      <Tooltip k="tablet_vacuum.current_work_order_card">
      <div className="mb-3 rounded-lg border border-line bg-white p-4">
        <div className="flex items-start justify-between">
          <div>
            <div className="text-sm font-semibold uppercase tracking-wide text-muted">Current work order</div>
            <div className="text-xl font-bold text-body">{wo.wo_id} — {wo.customer_name}</div>
            <div className="text-base text-body">{wo.body_type} · {wo.panels_in_cycle}</div>
          </div>
          <Tooltip k="tablet_vacuum.elapsed_vs_planned_timer">
            <button
              onClick={() => setModal('time')}
              className={`flex items-center gap-2 rounded-lg px-3 py-2 text-base font-semibold ${
                elapsedOver ? 'bg-status-amber/15 text-status-amber' : 'bg-surface-alt text-body'
              }`}
            >
              <Clock size={18} />
              Elapsed {hoursToHm(wo.elapsed_hours)} / {wo.planned_hours}h
            </button>
          </Tooltip>
        </div>
      </div>
      </Tooltip>

      {/* Picking slip */}
      <Tooltip k="tablet_vacuum.picking_slip_section">
      <Section icon={<ClipboardList size={20} />} title="Picking slip">
        <ul className="divide-y divide-line">
          {wo.picking_slip.map((item: PickingSlipItem, i) => {
            const st = picks[i]
            return (
              <Tooltip key={item.sap_item_code} k="tablet_vacuum.picking_slip_tap_row">
              <li className="flex items-center gap-3 py-3">
                <button
                  onClick={() => cyclePick(i)}
                  className={`flex h-11 w-11 items-center justify-center rounded-lg ${
                    st === 'picked' ? 'bg-status-green text-white' : st === 'short' ? 'bg-status-amber text-white' : 'bg-surface-alt text-muted'
                  }`}
                >
                  {st === 'picked' ? <Check size={22} /> : st === 'short' ? <AlertTriangle size={20} /> : ''}
                </button>
                <div className="flex-1">
                  <span className="font-mono text-sm font-semibold">{item.sap_item_code}</span>
                  <div className="text-base text-body">{item.description}</div>
                </div>
                <div className="text-right text-base tabular-nums">
                  {st === 'short' ? `${item.qty_picked} of ${item.qty_required}` : `${item.qty_required} of ${item.qty_required}`}
                </div>
                {st === 'short' && (
                  <Tooltip k="tablet_vacuum.report_shortage_button">
                    <button onClick={() => setModal('confirm')} className="rounded-md bg-status-red px-3 py-2 text-sm font-semibold text-white">
                      Report
                    </button>
                  </Tooltip>
                )}
              </li>
              </Tooltip>
            )
          })}
        </ul>
      </Section>
      </Tooltip>

      {/* Sign-off */}
      <Tooltip k="tablet_vacuum.signoff_checklist">
      <Section icon={<CheckSquare size={20} />} title="Sign-off (this stage)">
        <ul className="space-y-2">
          {wo.signoff_items.map((item: SignoffItem, i) => {
            const st = signs[i]
            return (
              <Tooltip key={item.id} k="tablet_vacuum.signoff_item_toggle">
              <li className="flex items-center gap-3 rounded-lg border border-line p-3">
                <button
                  onClick={() => cycleSign(i)}
                  className={`flex h-11 w-11 items-center justify-center rounded-lg ${
                    st === 'pass' ? 'bg-status-green text-white' : st === 'fail' ? 'bg-status-red text-white' : 'bg-surface-alt text-muted'
                  }`}
                >
                  {st === 'pass' ? <Check size={22} /> : st === 'fail' ? <X size={22} /> : item.id}
                </button>
                <span className="flex-1 text-base">{item.text}</span>
                {st === 'fail' && (
                  <button onClick={() => setModal('photo')} className="rounded-md bg-surface-alt p-2.5 text-muted">
                    <Camera size={20} />
                  </button>
                )}
              </li>
              </Tooltip>
            )
          })}
        </ul>
      </Section>
      </Tooltip>

      {/* Action bar */}
      <div className="mt-3 flex items-center gap-2">
        <Tooltip k="tablet_vacuum.photo_button">
          <button onClick={() => setModal('photo')} className="flex items-center gap-2 rounded-lg border border-line bg-white px-4 py-3 text-base font-semibold">
            <Camera size={18} /> Photo
          </button>
        </Tooltip>
        <Tooltip k="tablet_vacuum.comment_button">
          <button onClick={() => setModal('comment')} className="flex items-center gap-2 rounded-lg border border-line bg-white px-4 py-3 text-base font-semibold">
            <MessageSquare size={18} /> Comment
          </button>
        </Tooltip>
        <Tooltip k="tablet_vacuum.signoff_and_move_on" placement="top">
          <button
            onClick={() => setModal('done')}
            disabled={!allAnswered}
            className="ml-auto flex items-center gap-2 rounded-lg bg-status-green px-8 py-4 text-lg font-bold text-white shadow disabled:opacity-40"
          >
            Sign off & move on <ChevronRight size={22} />
          </button>
        </Tooltip>
      </div>

      {/* Next queue */}
      <Tooltip k="tablet_vacuum.next_in_my_queue">
      <div className="mt-4 rounded-lg bg-surface-alt p-3 text-base">
        <span className="font-semibold text-muted">Next in my queue: </span>
        {t.next_work_orders.map((n) => `${n.job_number} ${n.customer_name}`).join(' · ')}
      </div>
      </Tooltip>

      {/* Modals */}
      <Modal open={modal === 'photo'} onClose={() => setModal(null)}>
        <h3 className="mb-3 text-lg font-bold">Capture photo</h3>
        <div className="flex h-48 items-center justify-center rounded-lg bg-slate-800 text-slate-400">
          <Camera size={40} />
        </div>
        <div className="mt-4 flex justify-end gap-2">
          <button onClick={() => setModal(null)} className="rounded-md border border-line px-4 py-2">Cancel</button>
          <button onClick={() => setModal(null)} className="rounded-md bg-primary px-4 py-2 font-semibold text-white">Capture</button>
        </div>
      </Modal>

      <Modal open={modal === 'comment'} onClose={() => setModal(null)}>
        <h3 className="mb-3 text-lg font-bold">Add comment</h3>
        <textarea value={comment} onChange={(e) => setComment(e.target.value)} rows={4} className="w-full rounded-md border border-line p-2 text-base" placeholder="Type a note…" />
        <div className="mt-4 flex justify-end gap-2">
          <button onClick={() => setModal(null)} className="rounded-md border border-line px-4 py-2">Cancel</button>
          <button onClick={() => setModal(null)} className="rounded-md bg-primary px-4 py-2 font-semibold text-white">Save</button>
        </div>
      </Modal>

      <Modal open={modal === 'time'} onClose={() => setModal(null)}>
        <h3 className="mb-3 text-lg font-bold">Request more time</h3>
        <textarea rows={3} className="w-full rounded-md border border-line p-2 text-base" placeholder="Reason for extension…" />
        <div className="mt-4 flex justify-end gap-2">
          <button onClick={() => setModal(null)} className="rounded-md border border-line px-4 py-2">Cancel</button>
          <button onClick={() => setModal(null)} className="rounded-md bg-primary px-4 py-2 font-semibold text-white">Request</button>
        </div>
      </Modal>

      <Modal open={modal === 'confirm'} onClose={() => setModal(null)}>
        <h3 className="mb-2 text-lg font-bold">Raise material shortage alert?</h3>
        <p className="text-base text-muted">This notifies the Materials Bridge for the short item.</p>
        <div className="mt-4 flex justify-end gap-2">
          <button onClick={() => setModal(null)} className="rounded-md border border-line px-4 py-2">Cancel</button>
          <button onClick={() => setModal(null)} className="rounded-md bg-status-red px-4 py-2 font-semibold text-white">Raise alert</button>
        </div>
      </Modal>

      <Modal open={modal === 'done'} onClose={() => setModal(null)}>
        <div className="text-center">
          <div className="mx-auto mb-3 flex h-14 w-14 items-center justify-center rounded-full bg-status-green text-white">
            <Check size={28} />
          </div>
          <h3 className="text-xl font-bold">Work order complete</h3>
          <p className="mt-1 text-base text-muted">{wo.wo_id} signed off. Moving to next: {t.next_work_orders[0]?.job_number} {t.next_work_orders[0]?.customer_name}.</p>
          <button onClick={() => { setSigns(wo.signoff_items.map(() => 'pending')); setModal(null) }} className="mt-4 w-full rounded-md bg-primary py-3 text-base font-semibold text-white">
            Start next work order
          </button>
        </div>
      </Modal>
    </div>
  )
}

function Section({ icon, title, children }: { icon: React.ReactNode; title: string; children: React.ReactNode }) {
  return (
    <div className="mb-3 rounded-lg border border-line bg-white p-4">
      <div className="mb-2 flex items-center gap-2 text-base font-semibold uppercase tracking-wide text-muted">
        {icon} {title}
      </div>
      {children}
    </div>
  )
}
