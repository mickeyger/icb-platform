// PrejobTemplatesAdmin.tsx — WO v4.33 §3.3: the §0.15 review-and-approve surface for Nadie's
// Pre-Job Card template library. Renders inside AdminModule's sidebar layout (admin-gated
// there). List → editor: header metadata + the nested §0.5 sections editor (items with note +
// sub_items, add/delete/reorder) → Save / Approve (is_active=true — only active templates
// appear in the §3.4 modal selector) / Deactivate / Delete (drafts only, backend-enforced).
import { useCallback, useEffect, useMemo, useState } from 'react'
import { ArrowDown, ArrowUp, Check, ChevronLeft, Plus, Trash2 } from 'lucide-react'
import { Card, StatusPill } from '../../components/ui/primitives'
import { Spinner } from '../../components/ui/feedback'
import { useToast } from '../../components/ui/toast'
import { apiDelete, apiGet, apiPatch, apiPost, handleApiError } from '../../lib/api'

interface SectionItem { text: string; note?: string | null; sub_items?: string[] | null; sap_item_code?: string | null }
interface Section { name: string; items: SectionItem[] }
interface TemplateRow {
  id: number; name: string; body_type: string; size_category: string | null
  product_line: string; is_active: boolean; version: number
  updated_at: string | null; updated_by: string | null
  section_names: string[]; item_count: number
}
interface TemplateDetail extends TemplateRow {
  header_format: string | null; default_fridge_note: string | null; sections: Section[]
}

const BASE = '/api/admin/prejob-templates'
const LINE_LABEL: Record<string, string> = {
  standard: 'Standard', rhinorange_legacy: 'Rhinorange (legacy)', rhinorange_2_0: 'Rhinorange 2.0',
}
type SortKey = 'name' | 'body_type' | 'size_category' | 'product_line' | 'item_count' | 'is_active'

export function PrejobTemplatesAdmin() {
  const toast = useToast()
  const [rows, setRows] = useState<TemplateRow[]>([])
  const [loading, setLoading] = useState(true)
  const [bodyType, setBodyType] = useState('')
  const [line, setLine] = useState('')
  const [status, setStatus] = useState('')                 // '' | 'draft' | 'active'
  const [editing, setEditing] = useState<TemplateDetail | null>(null)
  const [busy, setBusy] = useState(false)
  const [sort, setSort] = useState<{ key: SortKey; dir: 1 | -1 }>({ key: 'name', dir: 1 })  // default A→Z by name

  const refresh = useCallback(async () => {
    setLoading(true)
    try {
      setRows(await apiGet<TemplateRow[]>(BASE))
    } catch (e) {
      handleApiError(e, toast.push)
    } finally {
      setLoading(false)
    }
  }, [toast.push])

  useEffect(() => { void refresh() }, [refresh])

  const bodyTypes = useMemo(() => [...new Set(rows.map((r) => r.body_type))].sort(), [rows])
  const filtered = rows.filter((r) =>
    (!bodyType || r.body_type === bodyType) &&
    (!line || r.product_line === line) &&
    (!status || (status === 'active' ? r.is_active : !r.is_active)))
  const sorted = [...filtered].sort((a, b) => {                 // client-side: header click re-sorts
    const av = a[sort.key]; const bv = b[sort.key]
    if (av == null && bv == null) return 0
    if (av == null) return 1                                    // nulls (e.g. blank size) sort last
    if (bv == null) return -1
    if (typeof av === 'number' && typeof bv === 'number') return (av - bv) * sort.dir
    if (typeof av === 'boolean' && typeof bv === 'boolean') return (Number(bv) - Number(av)) * sort.dir
    return String(av).localeCompare(String(bv)) * sort.dir
  })
  const th = (label: string, key: SortKey | null, align: 'left' | 'right' = 'left') => (
    <th
      onClick={key ? () => setSort((s) => ({ key, dir: (s.key === key ? -s.dir : 1) as 1 | -1 })) : undefined}
      className={`py-2 ${align === 'right' ? 'text-right' : ''} ${key ? 'cursor-pointer select-none hover:text-body' : ''}`}>
      {label}{key && sort.key === key ? (sort.dir === 1 ? ' ▲' : ' ▼') : ''}
    </th>
  )

  const open = async (id: number) => {
    try { setEditing(await apiGet<TemplateDetail>(`${BASE}/${id}`)) }
    catch (e) { handleApiError(e, toast.push) }
  }

  const save = async (): Promise<TemplateDetail | null> => {
    if (!editing) return null
    setBusy(true)
    try {
      const updated = await apiPatch<TemplateDetail>(`${BASE}/${editing.id}`, {
        name: editing.name, body_type: editing.body_type,
        size_category: editing.size_category, product_line: editing.product_line,
        header_format: editing.header_format, default_fridge_note: editing.default_fridge_note,
        sections: editing.sections,
      })
      setEditing(updated)
      toast.push({ kind: 'ok', message: 'Template saved' })
      void refresh()
      return updated
    } catch (e) {
      handleApiError(e, toast.push)
      return null
    } finally { setBusy(false) }
  }

  const approve = async () => {
    if (!editing) return
    const saved = await save()                            // approve what's on screen, not a stale copy
    if (!saved) return
    setBusy(true)
    try {
      setEditing(await apiPost<TemplateDetail>(`${BASE}/${saved.id}/approve`))
      toast.push({ kind: 'ok', message: `“${saved.name}” is now ACTIVE` })
      void refresh()
    } catch (e) { handleApiError(e, toast.push) } finally { setBusy(false) }
  }

  const deactivate = async () => {
    if (!editing) return
    setBusy(true)
    try {
      setEditing(await apiPost<TemplateDetail>(`${BASE}/${editing.id}/deactivate`))
      void refresh()
    } catch (e) { handleApiError(e, toast.push) } finally { setBusy(false) }
  }

  const remove = async () => {
    if (!editing || !window.confirm(`Delete draft “${editing.name}”?`)) return
    setBusy(true)
    try {
      await apiDelete(`${BASE}/${editing.id}`)
      toast.push({ kind: 'ok', message: 'Draft deleted' })
      setEditing(null)
      void refresh()
    } catch (e) { handleApiError(e, toast.push) } finally { setBusy(false) }
  }

  // ── editor mutators (immutably rebuild sections) ──────────────────────────
  const patchSections = (fn: (s: Section[]) => Section[]) =>
    setEditing((cur) => (cur ? { ...cur, sections: fn(structuredClone(cur.sections)) } : cur))

  if (editing) {
    const t = editing
    return (
      <div data-testid="prejob-template-editor">
        <div className="mb-3 flex flex-wrap items-center gap-2">
          <button onClick={() => setEditing(null)}
            className="flex items-center gap-1 rounded-md border border-line px-3 py-1.5 text-sm hover:bg-surface-alt">
            <ChevronLeft size={14} /> All templates
          </button>
          <StatusPill status={t.is_active ? 'GREEN' : 'AMBER'} label={t.is_active ? 'ACTIVE' : 'DRAFT'} />
          <span className="text-xs text-muted">v{t.version} · {t.updated_by ?? '—'}</span>
          <div className="ml-auto flex gap-2">
            {!t.is_active && (
              <button onClick={() => void remove()} disabled={busy}
                className="rounded-md border border-status-red px-3 py-1.5 text-sm text-status-red hover:bg-status-red/10">
                Delete draft
              </button>
            )}
            <button data-testid="prejob-template-save" onClick={() => void save()} disabled={busy}
              className="rounded-md border border-line px-3 py-1.5 text-sm font-semibold hover:bg-surface-alt">
              Save
            </button>
            {t.is_active ? (
              <button onClick={() => void deactivate()} disabled={busy}
                className="rounded-md border border-line px-3 py-1.5 text-sm hover:bg-surface-alt">
                Deactivate
              </button>
            ) : (
              <button data-testid="prejob-template-approve" onClick={() => void approve()} disabled={busy}
                className="flex items-center gap-1 rounded-md bg-primary px-3 py-1.5 text-sm font-semibold text-white hover:bg-primary-dark">
                <Check size={14} /> Approve (go live)
              </button>
            )}
          </div>
        </div>

        {/* Header metadata */}
        <Card className="mb-3">
          <div className="grid gap-3 md:grid-cols-3">
            <label className="text-xs text-muted">Name
              <input value={t.name} onChange={(e) => setEditing({ ...t, name: e.target.value })}
                className="mt-1 w-full rounded-md border border-line px-2 py-1.5 text-sm text-body" />
            </label>
            <label className="text-xs text-muted">Body type
              <input value={t.body_type} onChange={(e) => setEditing({ ...t, body_type: e.target.value })}
                className="mt-1 w-full rounded-md border border-line px-2 py-1.5 text-sm text-body" />
            </label>
            <label className="text-xs text-muted">Size category
              <input value={t.size_category ?? ''} onChange={(e) => setEditing({ ...t, size_category: e.target.value || null })}
                className="mt-1 w-full rounded-md border border-line px-2 py-1.5 text-sm text-body" />
            </label>
            <label className="text-xs text-muted">Product line
              <select value={t.product_line} onChange={(e) => setEditing({ ...t, product_line: e.target.value })}
                className="mt-1 w-full rounded-md border border-line px-2 py-1.5 text-sm text-body">
                {Object.entries(LINE_LABEL).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
              </select>
            </label>
            <label className="text-xs text-muted md:col-span-2">Header line
              <input value={t.header_format ?? ''} onChange={(e) => setEditing({ ...t, header_format: e.target.value || null })}
                className="mt-1 w-full rounded-md border border-line px-2 py-1.5 font-mono text-sm text-body" />
            </label>
          </div>
        </Card>

        {/* §0.5 sections editor */}
        {t.sections.map((section, si) => (
          <Card key={si} className="mb-3" data-testid="prejob-section">
            <div className="mb-2 flex items-center gap-2">
              <input value={section.name}
                onChange={(e) => patchSections((s) => { s[si].name = e.target.value; return s })}
                className="w-72 rounded-md border border-line px-2 py-1 text-sm font-bold uppercase tracking-wide text-body" />
              <span className="text-[11px] text-muted">{section.items.length} items</span>
              <div className="ml-auto flex gap-1">
                <IconBtn title="Move section up" disabled={si === 0}
                  onClick={() => patchSections((s) => { [s[si - 1], s[si]] = [s[si], s[si - 1]]; return s })}><ArrowUp size={13} /></IconBtn>
                <IconBtn title="Move section down" disabled={si === t.sections.length - 1}
                  onClick={() => patchSections((s) => { [s[si + 1], s[si]] = [s[si], s[si + 1]]; return s })}><ArrowDown size={13} /></IconBtn>
                <IconBtn title="Delete section"
                  onClick={() => patchSections((s) => { s.splice(si, 1); return s })}><Trash2 size={13} /></IconBtn>
              </div>
            </div>
            <ol className="space-y-2">
              {section.items.map((item, ii) => (
                <li key={ii} className="flex items-start gap-2 rounded-md bg-surface-alt/50 p-2">
                  <span className="mt-1.5 w-5 shrink-0 text-right font-mono text-xs text-muted">{ii + 1}</span>
                  <div className="min-w-0 flex-1 space-y-1">
                    <textarea value={item.text} rows={Math.min(3, Math.ceil(item.text.length / 90)) || 1}
                      onChange={(e) => patchSections((s) => { s[si].items[ii].text = e.target.value; return s })}
                      className="w-full resize-y rounded-md border border-line px-2 py-1 text-sm text-body" />
                    <input value={item.note ?? ''} placeholder="Note (optional — renders italic under the item)"
                      onChange={(e) => patchSections((s) => { s[si].items[ii].note = e.target.value || null; return s })}
                      className="w-full rounded-md border border-dashed border-line px-2 py-1 text-xs italic text-body" />
                    <textarea
                      value={(item.sub_items ?? []).join('\n')} rows={item.sub_items?.length ? Math.min(6, item.sub_items.length) : 1}
                      placeholder="Sub-items (optional — one per line, e.g. the HazChem pack)"
                      onChange={(e) => patchSections((s) => {
                        const v = e.target.value.split('\n').filter((x) => x.trim() !== '')
                        s[si].items[ii].sub_items = v.length ? v : null
                        return s
                      })}
                      className="w-full resize-y rounded-md border border-dotted border-line px-2 py-1 text-xs text-body" />
                  </div>
                  <div className="flex shrink-0 flex-col gap-1">
                    <IconBtn title="Move up" disabled={ii === 0}
                      onClick={() => patchSections((s) => { const a = s[si].items; [a[ii - 1], a[ii]] = [a[ii], a[ii - 1]]; return s })}><ArrowUp size={12} /></IconBtn>
                    <IconBtn title="Move down" disabled={ii === section.items.length - 1}
                      onClick={() => patchSections((s) => { const a = s[si].items; [a[ii + 1], a[ii]] = [a[ii], a[ii + 1]]; return s })}><ArrowDown size={12} /></IconBtn>
                    <IconBtn title="Delete item"
                      onClick={() => patchSections((s) => { s[si].items.splice(ii, 1); return s })}><Trash2 size={12} /></IconBtn>
                  </div>
                </li>
              ))}
            </ol>
            <button onClick={() => patchSections((s) => { s[si].items.push({ text: '' }); return s })}
              className="mt-2 flex items-center gap-1 rounded-md border border-dashed border-line px-2 py-1 text-xs text-muted hover:text-body">
              <Plus size={12} /> Add item
            </button>
          </Card>
        ))}
        <button
          onClick={() => patchSections((s) => { s.push({ name: 'NEW SECTION', items: [] }); return s })}
          className="flex items-center gap-1 rounded-md border border-dashed border-line px-3 py-2 text-sm text-muted hover:text-body">
          <Plus size={14} /> Add section
        </button>
      </div>
    )
  }

  // ── list view ───────────────────────────────────────────────────────────────
  return (
    <div data-testid="prejob-templates-admin">
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <h2 className="text-lg font-bold text-body">Pre-Job templates</h2>
        <span className="text-xs text-muted">
          {rows.filter((r) => r.is_active).length} active · {rows.filter((r) => !r.is_active).length} drafts
        </span>
        <div className="ml-auto flex gap-2">
          <select value={bodyType} onChange={(e) => setBodyType(e.target.value)}
            className="rounded-md border border-line px-2 py-1.5 text-sm text-body">
            <option value="">All body types</option>
            {bodyTypes.map((b) => <option key={b} value={b}>{b.replace(/_/g, ' ')}</option>)}
          </select>
          <select value={line} onChange={(e) => setLine(e.target.value)}
            className="rounded-md border border-line px-2 py-1.5 text-sm text-body">
            <option value="">All product lines</option>
            {Object.entries(LINE_LABEL).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select>
          <select value={status} onChange={(e) => setStatus(e.target.value)}
            className="rounded-md border border-line px-2 py-1.5 text-sm text-body">
            <option value="">All statuses</option>
            <option value="draft">Drafts</option>
            <option value="active">Active</option>
          </select>
        </div>
      </div>
      {loading ? <Spinner /> : (
        <Card>
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-line text-left text-xs uppercase tracking-wide text-muted">
                {th('Name', 'name')}{th('Body', 'body_type')}{th('Size', 'size_category')}
                {th('Line', 'product_line')}{th('Sections', null)}{th('Items', 'item_count', 'right')}
                {th('Status', 'is_active')}
              </tr>
            </thead>
            <tbody>
              {sorted.map((r) => (
                <tr key={r.id} data-testid="prejob-template-row" onClick={() => void open(r.id)}
                  className="cursor-pointer border-b border-line/60 last:border-0 hover:bg-surface-alt">
                  <td className="py-2 font-semibold text-body">{r.name}</td>
                  <td className="text-muted">{r.body_type.replace(/_/g, ' ')}</td>
                  <td className="text-muted">{r.size_category ?? '—'}</td>
                  <td className="text-muted">{LINE_LABEL[r.product_line] ?? r.product_line}</td>
                  <td className="font-mono text-[11px] text-muted">
                    {r.section_names.map((s) => s.split(' ')[0]).join(' + ')}
                  </td>
                  <td className="text-right text-muted">{r.item_count}</td>
                  <td><StatusPill status={r.is_active ? 'GREEN' : 'AMBER'} label={r.is_active ? 'Active' : 'Draft'} /></td>
                </tr>
              ))}
              {filtered.length === 0 && (
                <tr><td colSpan={7} className="py-6 text-center text-muted">No templates match the filters.</td></tr>
              )}
            </tbody>
          </table>
        </Card>
      )}
    </div>
  )
}

function IconBtn({ children, onClick, title, disabled = false }: {
  children: React.ReactNode; onClick: () => void; title: string; disabled?: boolean
}) {
  return (
    <button type="button" title={title} onClick={onClick} disabled={disabled}
      className="rounded border border-line p-1 text-muted hover:text-body disabled:opacity-30">
      {children}
    </button>
  )
}
