import { jobByNumber, customerById } from '../data/mockData'
import { SidePanel } from './ui/overlays'
import { StatusPill, Money } from './ui/primitives'
import { dmy } from '../lib/format'

// Graceful job-detail panel. Many bay/kanban job numbers are not present in
// jobs[] — for those we show a clearly-labelled stub instead of breaking.
export function JobDetailStub({
  jobNumber,
  fallbackName,
  onClose,
}: {
  jobNumber: string | null
  fallbackName?: string
  onClose: () => void
}) {
  const job = jobNumber ? jobByNumber(jobNumber) : undefined
  const customer = job ? customerById(job.customer_id) : undefined

  return (
    <SidePanel title={jobNumber ? `Job #${jobNumber}` : ''} open={!!jobNumber} onClose={onClose}>
      {!job ? (
        <div className="space-y-3">
          <p className="text-sm text-body">{fallbackName ?? 'Job'}</p>
          <div className="rounded-lg border border-dashed border-line bg-surface-alt p-4 text-sm text-muted">
            Full job detail is not part of this mock data set. In the production
            system this opens the job's complete record (BOM, routing, history).
          </div>
        </div>
      ) : (
        <div className="space-y-4">
          <div>
            <div className="text-lg font-semibold text-body">{job.description}</div>
            <div className="text-sm text-muted">{customer?.name}</div>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <StatusPill status={job.is_late ? 'RED' : 'GREEN'} label={job.status.replace(/_/g, ' ')} />
            {job.priority !== 'normal' && (
              <span className="rounded-full bg-surface-alt px-2 py-0.5 text-[11px] font-semibold uppercase text-muted">
                {job.priority} priority
              </span>
            )}
            <span className="rounded-full bg-surface-alt px-2 py-0.5 text-[11px] font-semibold uppercase text-muted">
              {job.complexity}
            </span>
          </div>
          <dl className="grid grid-cols-2 gap-3 text-sm">
            <Row label="Rep" value={job.rep} />
            <Row label="Site" value={job.site} />
            <Row label="Promised" value={dmy(job.promised_date)} />
            <Row label="Chassis received" value={dmy(job.chassis_received)} />
            <Row label="Current phase" value={job.current_phase.replace(/_/g, ' ')} />
            <Row label="Bay" value={job.current_bay ?? '—'} />
            <Row label="Progress" value={`${job.progress_pct}%`} />
            {job.is_late && <Row label="Days late" value={String(job.days_late ?? '—')} />}
          </dl>
          <div className="rounded-lg border border-line bg-surface-alt p-3">
            <div className="grid grid-cols-3 gap-2 text-center text-sm">
              <div>
                <div className="text-xs text-muted">Cost</div>
                <Money value={job.cost_zar} className="font-semibold" />
              </div>
              <div>
                <div className="text-xs text-muted">Selling</div>
                <Money value={job.selling_zar} className="font-semibold" />
              </div>
              <div>
                <div className="text-xs text-muted">Markup</div>
                <div className="font-semibold">{job.markup_pct}%</div>
              </div>
            </div>
          </div>
        </div>
      )}
    </SidePanel>
  )
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-xs uppercase tracking-wide text-muted">{label}</dt>
      <dd className="text-body">{value}</dd>
    </div>
  )
}
