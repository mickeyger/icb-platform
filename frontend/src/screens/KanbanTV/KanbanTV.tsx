import { useEffect, useState } from 'react'
import { Clock, AlertTriangle, Star, User } from 'lucide-react'
import { data } from '../../data/mockData'
import { hhmm } from '../../lib/format'
import { statusBg } from '../../lib/status'
import { Tooltip } from '../../components/ui/Tooltip'
import type { KanbanJobCard } from '../../data/types'

export function KanbanTV() {
  const k = data.pre_assy_kanban
  const [now, setNow] = useState(new Date())
  const [queue, setQueue] = useState<KanbanJobCard[]>(k.in_queue)
  const [progress, setProgress] = useState<KanbanJobCard[]>(k.in_progress)
  const [moving, setMoving] = useState<string | null>(null)

  useEffect(() => {
    const clock = setInterval(() => setNow(new Date()), 1000)
    return () => clearInterval(clock)
  }, [])

  // Simulated tick: every 8s slide the top queued job into "in progress".
  useEffect(() => {
    const tick = setInterval(() => {
      setQueue((q) => {
        if (q.length <= 1) return k.in_queue // loop the demo
        const [head, ...rest] = q
        setMoving(head.job_number)
        setProgress((p) => [{ ...head, hours_in_bay: 0.5, hours_planned: 12 }, ...p].slice(0, 3))
        setTimeout(() => setMoving(null), 400)
        return rest
      })
    }, 8000)
    return () => clearInterval(tick)
  }, [k.in_queue])

  return (
    <div className="min-h-[calc(100vh-48px)] bg-slate-900 p-6 text-slate-100">
      {/* Top banner */}
      <div className="flex items-center justify-between rounded-lg bg-slate-950 px-6 py-4">
        <div className="text-3xl font-bold">
          {k.bay_name.toUpperCase()} · {k.team}
        </div>
        <div className="flex items-center gap-3 text-2xl font-semibold tabular-nums">
          {hhmm(now)}
          <span className="flex items-center gap-2 text-base font-bold uppercase text-status-green">
            <span className="h-3 w-3 animate-pulseRed rounded-full bg-status-green" /> Live
          </span>
        </div>
      </div>

      {/* Status banner */}
      <Tooltip k="kanban_board.bay_status_colour">
      <div className={`mt-2 flex flex-wrap items-center justify-between gap-3 rounded-lg px-6 py-3 text-white ${statusBg[k.status]} ${k.status === 'RED' ? 'animate-pulseRed' : ''}`}>
        <div className="flex items-center gap-6 text-2xl font-bold">
          <Tooltip k="kanban_board.wip_indicator">
            <span>WIP {k.wip_count}/{k.wip_limit} {'▮'.repeat(k.wip_count)}</span>
          </Tooltip>
          <span>Today {k.throughput_today}/{k.target_today}</span>
          <span>WTD {k.throughput_wtd}/{k.target_wtd}</span>
          <span>STATUS: {k.status}</span>
        </div>
        <Tooltip k="kanban_board.factory_bottleneck">
          <div className="text-xl font-semibold">Factory bottleneck: {k.factory_bottleneck}</div>
        </Tooltip>
      </div>
      </Tooltip>

      {/* Columns */}
      <div className="mt-4 grid grid-cols-4 gap-4">
        <Tooltip k="kanban_board.in_queue_column" placement="bottom">
        <Column title={`In queue (${queue.length})`}>
          {queue.map((j) => (
            <QueueCard key={j.job_number} j={j} moving={moving === j.job_number} />
          ))}
        </Column>
        </Tooltip>

        <Tooltip k="kanban_board.in_progress_column" placement="bottom">
        <Column title={`In progress (${progress.length})`}>
          {progress.map((j) => (
            <ProgressCard key={j.job_number} j={j} />
          ))}
        </Column>
        </Tooltip>

        <Tooltip k="kanban_board.waiting_column" placement="bottom">
        <Column title={`Waiting (${k.waiting.length})`}>
          {k.waiting.map((j) => (
            <Tooltip key={j.job_number} k="kanban_board.waiting_reason_code">
            <div className="rounded-lg border-l-4 border-status-red bg-status-red/15 p-3">
              <div className="text-2xl font-bold">{j.job_number}</div>
              <div className="text-lg text-slate-300">{j.customer_name}</div>
              <div className="mt-1 flex items-center gap-1 text-base text-status-red">
                <AlertTriangle size={18} /> {j.reason}
              </div>
              <div className="mt-1 text-base text-slate-400">{j.hours_waiting}h ago</div>
            </div>
            </Tooltip>
          ))}
        </Column>
        </Tooltip>

        <Tooltip k="kanban_board.completed_today_column" placement="bottom">
        <Column title={`Done today (${k.completed_today.length})`}>
          {k.completed_today.map((j) => (
            <div key={j.job_number} className="rounded-lg bg-slate-800 p-2.5">
              <div className="text-xl font-bold text-status-green">{j.job_number}</div>
              <div className="text-base text-slate-300">{j.customer_name}</div>
              <div className="text-base text-slate-400">{j.completed_at}</div>
            </div>
          ))}
        </Column>
        </Tooltip>
      </div>

      <div className="mt-4 text-center text-base text-slate-500">View-only wall display · press Esc / use top nav to return</div>
    </div>
  )
}

function Column({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="mb-2 rounded-md bg-slate-950 px-3 py-2 text-xl font-bold uppercase tracking-wide">{title}</div>
      <div className="space-y-3">{children}</div>
    </div>
  )
}

function QueueCard({ j, moving }: { j: KanbanJobCard; moving: boolean }) {
  return (
    <div className={`rounded-lg bg-slate-800 p-3 transition-all duration-300 ${moving ? 'translate-x-4 opacity-0' : ''}`}>
      <div className="flex items-center gap-2">
        <span className="text-2xl font-bold">{j.job_number}</span>
        {j.priority === 'high' && <Star size={20} className="fill-status-amber text-status-amber" />}
      </div>
      <div className="text-lg text-slate-300">{j.customer_name}</div>
      <div className="text-base text-slate-400">{j.body_type}</div>
      {j.promised_date && <div className="mt-1 text-base text-slate-400">Due {j.promised_date}</div>}
      {j.priority === 'high' && <span className="mt-1 inline-block rounded bg-status-amber px-2 text-sm font-bold text-white">HIGH</span>}
    </div>
  )
}

function ProgressCard({ j }: { j: KanbanJobCard }) {
  const over = j.is_over
  return (
    <div className="rounded-lg bg-slate-800 p-3">
      <div className="text-2xl font-bold">{j.job_number}</div>
      <div className="text-lg text-slate-300">{j.customer_name}</div>
      <div className="text-base text-slate-400">{j.body_type}</div>
      <Tooltip k="kanban_board.in_progress_timer">
      <div className={`mt-1 flex items-center gap-1 text-lg font-semibold ${over ? 'text-status-red' : 'text-slate-200'}`}>
        <Clock size={18} /> {j.hours_in_bay}h / {j.hours_planned}h {over && '⚠'}
      </div>
      </Tooltip>
      {j.assigned_to && (
        <div className="mt-1 flex items-center gap-1 text-base text-slate-400">
          <User size={16} /> {j.assigned_to}
        </div>
      )}
    </div>
  )
}
