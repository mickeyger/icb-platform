import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Check, X, Camera, ChevronLeft, ChevronRight, Circle, CheckCircle2 } from 'lucide-react'
import { data } from '../../data/mockData'
import { useAppData } from '../../store/AppDataContext'
import { Modal } from '../../components/ui/overlays'
import { Tooltip } from '../../components/ui/Tooltip'
import type { QcItem } from '../../data/types'

// Sections beyond the elaborated 3 are exposed as collapsed stubs.
const STUB_SECTIONS = ['Floor', 'Roof', 'Refrigeration', 'Electrical', 'External fittings', 'Compliance']

// Rough routing for failed items → responsible bay.
const ROUTE: Record<string, string> = {
  'Cab & external': 'PS-1',
  'Doors & locking': 'DR-1',
  'Interior & panel finish': 'GRP-2',
}

type Result = 'pass' | 'fail' | 'pending'

export function QcFinalCheck() {
  const nav = useNavigate()
  const { addReworkTicket } = useAppData()
  const qc = data.qc_checklist_sample

  // Seed item results from the sample data; stub sections have no items.
  const [results, setResults] = useState<Record<string, Result>>(() => {
    const r: Record<string, Result> = {}
    qc.sections.forEach((s) => s.items.forEach((it) => { r[`${s.name}#${it.id}`] = it.result }))
    return r
  })
  const [active, setActive] = useState(0)
  const [reworkPrompt, setReworkPrompt] = useState<{ section: string; item: QcItem } | null>(null)
  const [photoModal, setPhotoModal] = useState(false)
  const [done, setDone] = useState(false)

  const sectionNames = [...qc.sections.map((s) => s.name), ...STUB_SECTIONS]
  const elaborated = active < qc.sections.length
  const section = elaborated ? qc.sections[active] : null

  const counts = useMemo(() => {
    const vals = Object.values(results)
    return {
      pass: vals.filter((v) => v === 'pass').length,
      fail: vals.filter((v) => v === 'fail').length,
      pending: qc.summary.total - vals.filter((v) => v !== 'pending').length,
    }
  }, [results, qc.summary.total])

  const answered = qc.sections.every((s) => s.items.every((it) => results[`${s.name}#${it.id}`] !== 'pending'))

  function cycle(sectionName: string, item: QcItem) {
    const key = `${sectionName}#${item.id}`
    setResults((r) => {
      const cur = r[key]
      const next: Result = cur === 'pending' ? 'pass' : cur === 'pass' ? 'fail' : 'pending'
      if (next === 'fail') setReworkPrompt({ section: sectionName, item })
      return { ...r, [key]: next }
    })
  }

  function createRework() {
    if (!reworkPrompt) return
    const toBay = ROUTE[reworkPrompt.section] ?? 'GRP-2'
    addReworkTicket({
      ticket: `RW-${2100 + Math.floor(Math.random() * 900)}`,
      job_number: qc.job_number,
      from_bay: 'QC-1',
      to_bay: toBay,
      reason: reworkPrompt.item.text,
      severity: reworkPrompt.item.severity ?? 'minor',
      opened_at: new Date().toISOString(),
      status: 'open',
    })
    setReworkPrompt(null)
  }

  const sectionDone = (name: string, i: number) => {
    if (i >= qc.sections.length) return 'none'
    const s = qc.sections[i]
    const states = s.items.map((it) => results[`${name}#${it.id}`])
    if (states.every((v) => v !== 'pending')) return 'all'
    if (states.some((v) => v !== 'pending')) return 'some'
    return 'none'
  }

  return (
    <div className="flex min-h-[calc(100vh-96px)] text-[16px]">
      {/* Sidebar */}
      <Tooltip k="qc_screen.section_navigator">
      <aside className="flex w-72 flex-col border-r border-line bg-white">
        <div className="border-b border-line bg-primary px-4 py-3 text-white">
          <div className="text-sm opacity-90">{qc.wo_id}</div>
          <div className="font-bold">J{qc.job_number} {qc.customer_name}</div>
          <div className="text-sm opacity-90">{qc.body_type}</div>
        </div>
        <ol className="flex-1 overflow-y-auto p-3">
          {sectionNames.map((name, i) => {
            const st = sectionDone(name, i)
            const stub = i >= qc.sections.length
            return (
              <li
                key={name}
                onClick={() => !stub && setActive(i)}
                className={`mb-1 flex items-center gap-2 rounded-md px-3 py-2 text-sm ${
                  active === i ? 'bg-primary-light font-semibold text-primary' : stub ? 'text-muted/60' : 'cursor-pointer text-body hover:bg-surface-alt'
                }`}
              >
                {st === 'all' ? <CheckCircle2 size={16} className="text-status-green" /> : st === 'some' ? <Circle size={16} className="fill-primary/30 text-primary" /> : <Circle size={16} className="text-muted/40" />}
                <span className="flex-1">{name}</span>
                {!stub && <span className="text-xs text-muted">{qc.sections[i].items.length}</span>}
                {stub && <span className="text-[10px] uppercase text-muted/60">stub</span>}
              </li>
            )
          })}
        </ol>
        <div className="grid grid-cols-3 gap-2 border-t border-line p-3 text-center text-sm">
          <Summary label="Pass" value={counts.pass} tone="text-status-green" />
          <Summary label="Fail" value={counts.fail} tone="text-status-red" />
          <Summary label="Pending" value={counts.pending} tone="text-muted" />
        </div>
      </aside>
      </Tooltip>

      {/* Main */}
      <section className="flex flex-1 flex-col p-6">
        <div className="mb-1 flex items-center justify-between">
          <h1 className="text-lg font-bold text-body">Final QC · {qc.inspector} · Progress {counts.pass + counts.fail}/{qc.summary.total}</h1>
        </div>

        <div className="mb-4 h-2 overflow-hidden rounded-full bg-surface-alt">
          <div className="h-full bg-status-green" style={{ width: `${((counts.pass + counts.fail) / qc.summary.total) * 100}%` }} />
        </div>

        <div className="flex-1">
          {elaborated && section ? (
            <>
              <h2 className="mb-3 text-base font-semibold text-body">Section: {section.name}</h2>
              <ul className="space-y-2">
                {section.items.map((item) => {
                  const st = results[`${section.name}#${item.id}`]
                  return (
                    <Tooltip key={item.id} k="qc_screen.checklist_item">
                    <li className="rounded-lg border border-line p-3">
                      <div className="flex items-center gap-3">
                        <Tooltip k={st === 'fail' ? 'qc_screen.item_fail_toggle' : 'qc_screen.item_pass_toggle'}>
                          <button
                            onClick={() => cycle(section.name, item)}
                            className={`flex h-10 w-10 items-center justify-center rounded-lg ${
                              st === 'pass' ? 'bg-status-green text-white' : st === 'fail' ? 'bg-status-red text-white' : 'bg-surface-alt text-muted'
                            }`}
                          >
                            {st === 'pass' ? <Check size={20} /> : st === 'fail' ? <X size={20} /> : item.id}
                          </button>
                        </Tooltip>
                        <span className="flex-1">{item.text}</span>
                      </div>
                      {st === 'fail' && (
                        <div className="mt-2 space-y-2 rounded-md bg-status-red/5 p-3">
                          <div className="flex items-center gap-2 text-sm">
                            <span className="text-muted">Severity:</span>
                            <Tooltip k="qc_screen.severity_dropdown">
                              <select defaultValue={item.severity ?? 'minor'} className="rounded-md border border-line px-2 py-1">
                                <option value="minor">Minor (cosmetic)</option>
                                <option value="major">Major (functional)</option>
                                <option value="critical">Critical (safety)</option>
                              </select>
                            </Tooltip>
                            <Tooltip k="qc_screen.photo_attached">
                              <button onClick={() => setPhotoModal(true)} className="ml-auto flex items-center gap-1 rounded-md border border-line px-2 py-1 text-sm">
                                <Camera size={15} /> {item.photo ? 'Photo attached' : 'Add photo'}
                              </button>
                            </Tooltip>
                          </div>
                          <input defaultValue={item.comment} placeholder="Comment…" className="w-full rounded-md border border-line px-2 py-1 text-sm" />
                          <div className="text-xs text-muted">Routes rework to <span className="font-semibold">{ROUTE[section.name] ?? 'GRP-2'}</span></div>
                        </div>
                      )}
                    </li>
                    </Tooltip>
                  )
                })}
              </ul>
            </>
          ) : (
            <div className="flex h-full items-center justify-center rounded-lg border border-dashed border-line bg-surface-alt text-muted">
              This section is a stub in the mock data (0 items).
            </div>
          )}
        </div>

        <div className="mt-4 flex items-center justify-between border-t border-line pt-4">
          <button onClick={() => setActive((a) => Math.max(0, a - 1))} disabled={active === 0} className="flex items-center gap-1 rounded-md px-4 py-2 text-sm font-medium text-primary disabled:opacity-30">
            <ChevronLeft size={16} /> Previous section
          </button>
          {answered ? (
            <Tooltip k="qc_screen.sign_off_and_invoice" placement="top">
              <button onClick={() => setDone(true)} className="rounded-md bg-status-green px-6 py-3 text-base font-bold text-white shadow hover:opacity-90">
                Sign off & Invoice
              </button>
            </Tooltip>
          ) : (
            <button onClick={() => setActive((a) => Math.min(sectionNames.length - 1, a + 1))} className="flex items-center gap-1 rounded-md bg-primary px-5 py-2 text-sm font-semibold text-white hover:bg-primary-dark">
              Next section <ChevronRight size={16} />
            </button>
          )}
        </div>
      </section>

      {/* Rework confirm */}
      <Modal open={!!reworkPrompt} onClose={() => setReworkPrompt(null)}>
        <h3 className="mb-2 text-lg font-bold">Create rework ticket?</h3>
        {reworkPrompt && (
          <p className="text-sm text-muted">
            Item “{reworkPrompt.item.text}” failed — route to{' '}
            <span className="font-semibold text-body">{ROUTE[reworkPrompt.section] ?? 'GRP-2'}</span>?
          </p>
        )}
        <div className="mt-4 flex justify-end gap-2">
          <button onClick={() => setReworkPrompt(null)} className="rounded-md border border-line px-4 py-2 text-sm">No, just record</button>
          <Tooltip k="qc_screen.create_rework_ticket">
            <button onClick={createRework} className="rounded-md bg-primary px-4 py-2 text-sm font-semibold text-white">Yes, create</button>
          </Tooltip>
        </div>
      </Modal>

      {/* Photo */}
      <Modal open={photoModal} onClose={() => setPhotoModal(false)}>
        <h3 className="mb-3 text-lg font-bold">Capture photo</h3>
        <div className="flex h-48 items-center justify-center rounded-lg bg-slate-800 text-slate-400"><Camera size={40} /></div>
        <div className="mt-4 flex justify-end gap-2">
          <button onClick={() => setPhotoModal(false)} className="rounded-md border border-line px-4 py-2">Cancel</button>
          <button onClick={() => setPhotoModal(false)} className="rounded-md bg-primary px-4 py-2 font-semibold text-white">Capture</button>
        </div>
      </Modal>

      {/* Done splash */}
      <Modal open={done}>
        <div className="text-center">
          <div className="mx-auto mb-3 flex h-14 w-14 items-center justify-center rounded-full bg-status-green text-white"><Check size={28} /></div>
          <h3 className="text-xl font-bold">QC complete</h3>
          <p className="mt-1 text-sm text-muted">Invoice enabled, finance notified for J{qc.job_number}.</p>
          <button onClick={() => { setDone(false); nav('/production') }} className="mt-4 w-full rounded-md bg-primary py-3 text-sm font-semibold text-white">
            Back to Production Dashboard
          </button>
        </div>
      </Modal>
    </div>
  )
}

function Summary({ label, value, tone }: { label: string; value: number; tone: string }) {
  return (
    <div>
      <div className={`text-2xl font-bold tabular-nums ${tone}`}>{value}</div>
      <div className="text-xs text-muted">{label}</div>
    </div>
  )
}
