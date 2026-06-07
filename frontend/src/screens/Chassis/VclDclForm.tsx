/** WO v4.28 §0.6/§0.7 — tablet-friendly VCL (book-in) / DCL (dispatch) capture form (modal).
 * Checklist items come from /api/chassis-records/checklists (data, not hard-coded). Large touch
 * targets (min py-3 / h-7 toggles) for shop-floor tablets; photo multi-upload; one POST to capture
 * the event then a multipart POST for the photos. */
import { useState } from 'react'
import { X, Camera, Check } from 'lucide-react'

import { apiPost, apiUpload, handleApiError } from '../../lib/api'
import { useToast } from '../../components/ui/toast'
import { Spinner } from '../../components/ui/feedback'

export interface ChecklistItem { key: string; label: string; type: 'bool' | 'text' }

export function VclDclForm({ recordId, eventType, items, onClose, onSaved }: {
  recordId: number
  eventType: 'VCL' | 'DCL'
  items: ChecklistItem[]
  onClose: () => void
  onSaved: () => void
}) {
  const toast = useToast()
  const today = new Date().toISOString().slice(0, 10)
  const [date, setDate] = useState(today)
  const [values, setValues] = useState<Record<string, boolean | string>>({})
  const [notes, setNotes] = useState('')
  const [files, setFiles] = useState<File[]>([])
  const [saving, setSaving] = useState(false)
  const isVcl = eventType === 'VCL'

  const setVal = (k: string, v: boolean | string) => setValues((p) => ({ ...p, [k]: v }))

  async function save() {
    setSaving(true)
    try {
      const ev = await apiPost<{ id: number }>(
        `/api/chassis-records/${recordId}/${eventType.toLowerCase()}`,
        { event_date: date, checklist_json: values, notes: notes || null })
      if (files.length) {
        const fd = new FormData()
        files.forEach((f) => fd.append('files', f))
        await apiUpload(`/api/chassis-records/${recordId}/events/${ev.id}/photos`, fd)
      }
      toast.push({ kind: 'ok', message: `${eventType} captured.` })
      onSaved()
    } catch (e) {
      handleApiError(e, toast.push)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-black/40 sm:items-center sm:p-4"
         onClick={onClose}>
      <div data-testid="chassis-capture-form" onClick={(e) => e.stopPropagation()}
           className="max-h-[92vh] w-full max-w-lg overflow-y-auto rounded-t-2xl bg-white p-5 shadow-xl sm:rounded-2xl">
        <div className="mb-3 flex items-center justify-between">
          <h3 className="text-lg font-bold text-body">{isVcl ? 'VCL — Book-in' : 'DCL — Dispatch'}</h3>
          <button data-testid="chassis-capture-cancel" onClick={onClose}
                  className="rounded p-2 hover:bg-surface-alt"><X size={20} /></button>
        </div>

        <label className="mb-3 block">
          <span className="text-xs font-semibold uppercase tracking-wide text-muted">
            {isVcl ? 'Received date' : 'Dispatch date'}
          </span>
          <input data-testid="chassis-capture-date" type="date" value={date}
                 onChange={(e) => setDate(e.target.value)}
                 className="mt-1 w-full rounded-md border border-line px-3 py-3 text-base" />
        </label>

        <div className="mb-3 space-y-2">
          {items.map((it) => it.type === 'bool' ? (
            <button key={it.key} type="button" data-testid={`chk-${it.key}`}
                    onClick={() => setVal(it.key, !values[it.key])}
                    className={`flex w-full items-center justify-between rounded-md border px-4 py-3 text-left text-base ${values[it.key] ? 'border-status-green bg-status-green/10' : 'border-line bg-white'}`}>
              <span>{it.label}</span>
              <span className={`flex h-7 w-7 items-center justify-center rounded-full ${values[it.key] ? 'bg-status-green text-white' : 'bg-surface-alt text-muted'}`}>
                {values[it.key] ? <Check size={16} /> : null}
              </span>
            </button>
          ) : (
            <label key={it.key} className="block">
              <span className="text-sm text-body">{it.label}</span>
              <input data-testid={`chk-${it.key}`} value={(values[it.key] as string) || ''}
                     onChange={(e) => setVal(it.key, e.target.value)}
                     className="mt-1 w-full rounded-md border border-line px-3 py-3 text-base" />
            </label>
          ))}
        </div>

        <label className="mb-3 flex cursor-pointer items-center gap-2 rounded-md border border-dashed border-line px-4 py-3 text-sm font-semibold text-primary">
          <Camera size={18} /> {files.length ? `${files.length} photo(s) selected` : 'Add photos'}
          <input data-testid="chassis-capture-photos" type="file" accept="image/*" multiple className="hidden"
                 onChange={(e) => setFiles(Array.from(e.target.files ?? []))} />
        </label>

        <textarea value={notes} onChange={(e) => setNotes(e.target.value)} rows={2}
                  placeholder="Notes (optional)"
                  className="mb-4 w-full rounded-md border border-line px-3 py-2 text-sm" />

        <div className="flex gap-2">
          <button onClick={onClose} className="flex-1 rounded-md border border-line py-3 text-base font-semibold">
            Cancel
          </button>
          <button data-testid="chassis-capture-save" onClick={save} disabled={saving}
                  className="flex flex-1 items-center justify-center gap-2 rounded-md bg-primary py-3 text-base font-semibold text-white disabled:opacity-50">
            {saving ? <Spinner size={16} /> : null} Save {eventType}
          </button>
        </div>
      </div>
    </div>
  )
}
