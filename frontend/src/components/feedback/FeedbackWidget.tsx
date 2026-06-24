// FeedbackWidget — the global "Report issue" launcher (WO v4.38).
//
// Renders a floating button on every /mes-app/* screen (mounted in Layout, so it
// NEVER appears on the /calculator Jinja pages). Opening it captures a screenshot
// of the page behind it (html2canvas, best-effort — a capture failure just omits
// the image), takes a description, POSTs multipart to /api/feedback, then shows
// Claude-Haiku's clarifying questions for the user to answer. The whole feedback
// UI subtree is tagged data-feedback-ui so html2canvas excludes it from the shot.
//
// UX adapted from the in-repo Jinja help widget (app/static/js/help_chat.js):
// floating launcher + panel + a "thinking" state while the model works.
import { useCallback, useEffect, useState } from 'react'
import { CheckCircle2, Loader2, MessageSquarePlus, X } from 'lucide-react'
import { ApiError, apiPost, apiUpload } from '../../lib/api'

type Phase = 'form' | 'submitting' | 'clarify' | 'done' | 'error'

interface SubmitResult {
  ticket_id: number
  status: string
  issue_type: string | null
  severity: string | null
  summary: string | null
  clarifying_questions: string[]
  classified: boolean
}

const SEV_CLS: Record<string, string> = {
  blocker: 'bg-status-red text-white',
  major: 'bg-status-amber text-white',
  minor: 'bg-amber-100 text-amber-800',
  nice: 'bg-surface-alt text-muted',
}

export function FeedbackWidget() {
  const [open, setOpen] = useState(false)
  const [phase, setPhase] = useState<Phase>('form')
  const [text, setText] = useState('')
  const [shot, setShot] = useState<Blob | null>(null)
  const [shotUrl, setShotUrl] = useState<string | null>(null)
  const [capturing, setCapturing] = useState(false)
  const [result, setResult] = useState<SubmitResult | null>(null)
  const [answers, setAnswers] = useState<string[]>([])
  const [errMsg, setErrMsg] = useState('')

  const resetShot = useCallback(() => {
    setShotUrl((url) => {
      if (url) URL.revokeObjectURL(url)
      return null
    })
    setShot(null)
  }, [])

  const close = useCallback(() => {
    setOpen(false)
    resetShot()
  }, [resetShot])

  // Escape closes the widget.
  useEffect(() => {
    if (!open) return
    const h = (e: KeyboardEvent) => e.key === 'Escape' && close()
    window.addEventListener('keydown', h)
    return () => window.removeEventListener('keydown', h)
  }, [open, close])

  const openWidget = useCallback(async () => {
    setOpen(true)
    setPhase('form')
    setText('')
    setResult(null)
    setErrMsg('')
    setAnswers([])
    resetShot()
    // Capture the page behind the (data-feedback-ui-excluded) overlay. Best-effort:
    // the canvas-rendered Planning Board or a tainted image can make this fail — we
    // just proceed without a screenshot.
    setCapturing(true)
    try {
      const { default: html2canvas } = await import('html2canvas')
      const canvas = await html2canvas(document.body, {
        logging: false,
        useCORS: true,
        scale: 1,
        ignoreElements: (el) => el instanceof HTMLElement && el.dataset.feedbackUi !== undefined,
      })
      const blob = await new Promise<Blob | null>((res) => canvas.toBlob(res, 'image/png'))
      if (blob) {
        setShot(blob)
        setShotUrl(URL.createObjectURL(blob))
      }
    } catch {
      /* capture unavailable — report still works without an image */
    } finally {
      setCapturing(false)
    }
  }, [resetShot])

  const submit = useCallback(async () => {
    if (!text.trim()) return
    setPhase('submitting')
    try {
      const fd = new FormData()
      fd.append('user_text', text.trim())
      fd.append('page_url', window.location.href)
      if (shot) fd.append('screenshot', shot, 'screenshot.png')
      const r = await apiUpload<SubmitResult>('/api/feedback', fd)
      setResult(r)
      const qs = r.clarifying_questions || []
      setAnswers(qs.map(() => ''))
      setPhase(qs.length ? 'clarify' : 'done')
    } catch (e) {
      setErrMsg(e instanceof ApiError ? e.detail || `Error ${e.status}` : 'Could not submit — please try again.')
      setPhase('error')
    }
  }, [text, shot])

  const sendAnswers = useCallback(async () => {
    if (!result) return
    setPhase('submitting')
    try {
      const payload = (result.clarifying_questions || []).map((q, i) => ({ q, a: answers[i] || '' }))
      await apiPost(`/api/feedback/${result.ticket_id}/answer`, { answers: payload })
    } catch {
      /* answers are a bonus — never block the thank-you */
    }
    setPhase('done')
  }, [result, answers])

  return (
    <>
      <button
        data-feedback-ui="1"
        data-testid="feedback-launcher"
        onClick={openWidget}
        title="Report an issue"
        className="fixed bottom-5 right-5 z-30 flex items-center gap-2 rounded-full bg-primary px-4 py-3 text-white shadow-lg transition hover:bg-primary/90 focus:outline-none focus:ring-2 focus:ring-primary/40"
      >
        <MessageSquarePlus size={18} />
        <span className="hidden text-sm font-medium sm:inline">Report issue</span>
      </button>

      {open && (
        <div data-feedback-ui="1" className="fixed inset-0 z-50 flex items-center justify-center p-4">
          <div className="absolute inset-0 bg-black/40" onClick={close} />
          <div
            data-testid="feedback-modal"
            className="relative w-full max-w-md rounded-xl bg-white p-6 shadow-2xl"
          >
            <button
              onClick={close}
              aria-label="Close"
              className="absolute right-3 top-3 rounded p-1 text-muted hover:bg-surface-alt"
            >
              <X size={18} />
            </button>

            {phase === 'form' && (
              <div>
                <h2 className="mb-1 text-lg font-semibold text-body">Report an issue</h2>
                <p className="mb-3 text-sm text-muted">
                  Tell us what went wrong or what you need — we'll attach a screenshot of this page.
                </p>
                <textarea
                  data-testid="feedback-text"
                  value={text}
                  onChange={(e) => setText(e.target.value)}
                  rows={4}
                  autoFocus
                  placeholder="e.g. The planning board didn't update after I merged job 40400."
                  className="w-full resize-none rounded-lg border border-line p-3 text-sm focus:border-primary focus:outline-none"
                />
                <div className="mt-2 flex items-center gap-2 text-xs text-muted" data-testid="feedback-shot-status">
                  {capturing ? (
                    <>
                      <Loader2 size={14} className="animate-spin" /> Capturing screenshot…
                    </>
                  ) : shotUrl ? (
                    <>
                      <img src={shotUrl} alt="screenshot preview" className="h-10 w-16 rounded border border-line object-cover" />
                      Screenshot attached
                    </>
                  ) : (
                    <>No screenshot (optional)</>
                  )}
                </div>
                <div className="mt-4 flex justify-end gap-2">
                  <button onClick={close} className="rounded-lg px-4 py-2 text-sm text-muted hover:bg-surface-alt">
                    Cancel
                  </button>
                  <button
                    data-testid="feedback-submit"
                    onClick={submit}
                    disabled={!text.trim()}
                    className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-white hover:bg-primary/90 disabled:opacity-40"
                  >
                    Send report
                  </button>
                </div>
              </div>
            )}

            {phase === 'submitting' && (
              <div className="flex flex-col items-center gap-3 py-8 text-muted" data-testid="feedback-thinking">
                <Loader2 size={28} className="animate-spin text-primary" />
                <span className="text-sm">Analysing your report…</span>
              </div>
            )}

            {phase === 'clarify' && result && (
              <div data-testid="feedback-clarify">
                <div className="mb-2 flex items-center gap-2">
                  <CheckCircle2 size={18} className="text-status-green" />
                  <h2 className="text-lg font-semibold text-body">Ticket #{result.ticket_id} logged</h2>
                </div>
                <p className="mb-3 text-sm text-muted">A couple of quick questions to help us sort it out:</p>
                <div className="space-y-3">
                  {(result.clarifying_questions || []).map((q, i) => (
                    <div key={i}>
                      <label className="mb-1 block text-sm text-body">{q}</label>
                      <input
                        data-testid={`feedback-answer-${i}`}
                        value={answers[i] || ''}
                        onChange={(e) => setAnswers((a) => a.map((v, j) => (j === i ? e.target.value : v)))}
                        className="w-full rounded-lg border border-line p-2 text-sm focus:border-primary focus:outline-none"
                      />
                    </div>
                  ))}
                </div>
                <div className="mt-4 flex justify-end gap-2">
                  <button data-testid="feedback-skip" onClick={() => setPhase('done')} className="rounded-lg px-4 py-2 text-sm text-muted hover:bg-surface-alt">
                    Skip
                  </button>
                  <button
                    data-testid="feedback-send-answers"
                    onClick={sendAnswers}
                    className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-white hover:bg-primary/90"
                  >
                    Send answers
                  </button>
                </div>
              </div>
            )}

            {phase === 'done' && (
              <div className="flex flex-col items-center gap-3 py-6 text-center" data-testid="feedback-done">
                <CheckCircle2 size={36} className="text-status-green" />
                <h2 className="text-lg font-semibold text-body">Thanks — we're on it</h2>
                <p className="text-sm text-muted">
                  {result ? <>Ticket #{result.ticket_id} has been sent to the team.</> : 'Your report has been sent.'}
                </p>
                {result?.severity && (
                  <span className={`rounded-full px-3 py-1 text-xs font-medium ${SEV_CLS[result.severity] || 'bg-surface-alt text-muted'}`}>
                    {result.severity} · {result.issue_type}
                  </span>
                )}
                <button onClick={close} className="mt-2 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-white hover:bg-primary/90">
                  Close
                </button>
              </div>
            )}

            {phase === 'error' && (
              <div className="flex flex-col items-center gap-3 py-6 text-center" data-testid="feedback-error">
                <h2 className="text-lg font-semibold text-body">Couldn't send that</h2>
                <p className="text-sm text-muted">{errMsg}</p>
                <div className="flex gap-2">
                  <button onClick={() => setPhase('form')} className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-white hover:bg-primary/90">
                    Try again
                  </button>
                  <button onClick={close} className="rounded-lg px-4 py-2 text-sm text-muted hover:bg-surface-alt">
                    Close
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </>
  )
}
