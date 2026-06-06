/** WO v4.26 §3.6 — generic admin CRUD table (list + create/edit modal + delete-confirm).
 * Driven by a ResourceConfig. Formula fields get a live parse-check; SAP-code fields get an
 * OITM typeahead. All writes go through lib/api (CSRF + error toast). */
import { useCallback, useEffect, useState } from 'react'

import { Skeleton } from '../../components/ui/feedback'
import { Card } from '../../components/ui/primitives'
import { useToast } from '../../components/ui/toast'
import { apiDelete, apiGet, apiPatch, apiPost, handleApiError } from '../../lib/api'
import type { FieldDef, ResourceConfig } from './adminResources'

type Row = Record<string, unknown>

function defaults(cfg: ResourceConfig): Row {
  const o: Row = {}
  cfg.fields.forEach((f) => { o[f.name] = f.default ?? (f.type === 'bool' ? false : '') })
  return o
}

function FieldInput({ field, value, onChange }: {
  field: FieldDef; value: unknown; onChange: (v: unknown) => void
}) {
  const [opts, setOpts] = useState<string[]>([])
  const base = 'w-full rounded border border-line px-2 py-1 text-sm'
  const testId = `field-${field.name}`
  if (field.type === 'bool') {
    return <input type="checkbox" data-testid={testId} checked={!!value} onChange={(e) => onChange(e.target.checked)} />
  }
  if (field.type === 'textarea') {
    return <textarea className={`${base} font-mono`} data-testid={testId} rows={2} value={String(value ?? '')}
                     onChange={(e) => onChange(e.target.value)} />
  }
  if (field.type === 'number') {
    return <input type="number" step="any" data-testid={testId} className={base} value={value as number ?? ''}
                  onChange={(e) => onChange(e.target.value === '' ? null : Number(e.target.value))} />
  }
  if (field.type === 'date') {
    return <input type="date" data-testid={testId} className={base} value={String(value ?? '')}
                  onChange={(e) => onChange(e.target.value || null)} />
  }
  // text — with optional OITM autocomplete
  const listId = field.oitmAutocomplete ? `dl-${field.name}` : undefined
  return (
    <>
      <input className={base} data-testid={testId} value={String(value ?? '')} list={listId}
             onChange={async (e) => {
               const v = e.target.value
               onChange(v)
               if (field.oitmAutocomplete && v.length >= 2) {
                 try {
                   const hits = await apiGet<{ sap_code: string }[]>(`/api/admin/oitm-search?q=${encodeURIComponent(v)}`)
                   setOpts(hits.map((h) => h.sap_code))
                 } catch { /* ignore typeahead errors */ }
               }
             }} />
      {listId && <datalist id={listId}>{opts.map((o) => <option key={o} value={o} />)}</datalist>}
    </>
  )
}

export function AdminCrudTable({ config }: { config: ResourceConfig }) {
  const toast = useToast()
  const [rows, setRows] = useState<Row[]>([])
  const [loading, setLoading] = useState(true)
  const [editing, setEditing] = useState<Row | null>(null)   // null = closed; {} -> new
  const [form, setForm] = useState<Row>({})
  const [formulaCheck, setFormulaCheck] = useState<string>('')

  const refetch = useCallback(async () => {
    setLoading(true)
    try {
      setRows(await apiGet<Row[]>(config.basePath))
    } catch (e) { handleApiError(e, toast.push) } finally { setLoading(false) }
  }, [config.basePath, toast])

  useEffect(() => { void refetch() }, [refetch])

  const openNew = () => { setForm(defaults(config)); setEditing({}); setFormulaCheck('') }
  const openEdit = (r: Row) => { setForm({ ...r }); setEditing(r); setFormulaCheck('') }

  const save = async () => {
    try {
      const id = (editing as Row)?.id
      if (id) await apiPatch(`${config.basePath}/${id}`, form)
      else await apiPost(config.basePath, form)
      setEditing(null)
      await refetch()
      toast.push({ kind: 'ok', message: id ? 'Updated.' : 'Created.' })
    } catch (e) { handleApiError(e, toast.push) }
  }

  const remove = async (r: Row) => {
    if (!window.confirm(`Delete this ${config.title} row (id ${r.id})?`)) return
    try { await apiDelete(`${config.basePath}/${r.id}`); await refetch() }
    catch (e) { handleApiError(e, toast.push) }
  }

  const checkFormula = async () => {
    try {
      const res = await apiPost<{ valid: boolean; error?: string }>(
        '/api/admin/bom-rules/validate-formula', { formula_expression: form.formula_expression })
      setFormulaCheck(res.valid ? '✓ valid' : `✗ ${res.error}`)
    } catch (e) { handleApiError(e, toast.push) }
  }

  if (loading) return <Skeleton rows={8} />

  return (
    <div data-testid="admin-crud">
      <div className="mb-3 flex items-center justify-between">
        <h2 data-testid="admin-title" className="text-lg font-bold text-body">{config.title} <span className="text-sm text-muted">({rows.length})</span></h2>
        <button data-testid="admin-new" onClick={openNew} className="rounded bg-primary px-3 py-1.5 text-sm font-semibold text-white">+ New</button>
      </div>
      <Card className="p-0"><div className="overflow-x-auto"><table data-testid="admin-table" className="w-full text-sm">
        <thead className="bg-primary text-left text-white"><tr>
          {config.columns.map((c) => <th key={c.key} className="px-3 py-2 font-semibold">{c.label}</th>)}
          <th className="px-3 py-2" />
        </tr></thead>
        <tbody>
          {rows.length ? rows.map((r, i) => (
            <tr key={String(r.id)} data-testid="admin-row" data-row-id={String(r.id)} className={`border-b border-line ${i % 2 ? 'bg-surface-alt' : 'bg-white'}`}>
              {config.columns.map((c) => (
                <td key={c.key} className={`px-3 py-2 ${c.key === 'formula_expression' ? 'font-mono text-xs' : ''}`}>
                  {typeof r[c.key] === 'boolean' ? (r[c.key] ? 'Yes' : 'No') : String(r[c.key] ?? '—')}
                </td>
              ))}
              <td className="whitespace-nowrap px-3 py-2 text-right">
                <button data-testid="admin-edit" onClick={() => openEdit(r)} className="mr-2 text-primary hover:underline">Edit</button>
                <button data-testid="admin-delete" onClick={() => remove(r)} className="text-red-600 hover:underline">Delete</button>
              </td>
            </tr>
          )) : <tr><td colSpan={config.columns.length + 1} className="px-4 py-8 text-center text-muted">No rows.</td></tr>}
        </tbody>
      </table></div></Card>

      {editing && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4" onClick={() => setEditing(null)}>
          <div data-testid="admin-form" className="max-h-[90vh] w-full max-w-lg overflow-y-auto rounded-lg bg-white p-5 shadow-xl" onClick={(e) => e.stopPropagation()}>
            <h3 className="mb-3 text-base font-bold text-body">{(editing as Row).id ? 'Edit' : 'New'} — {config.title}</h3>
            <div className="space-y-3">
              {config.fields.map((f) => (
                <div key={f.name}>
                  <label className="mb-1 block text-xs font-semibold text-body">
                    {f.label}{f.required && <span className="text-red-600"> *</span>}
                  </label>
                  <FieldInput field={f} value={form[f.name]} onChange={(v) => setForm((p) => ({ ...p, [f.name]: v }))} />
                  {f.validateFormula && (
                    <div className="mt-1 flex items-center gap-2">
                      <button data-testid="admin-validate-formula" onClick={checkFormula} className="rounded border border-line px-2 py-0.5 text-xs">Validate</button>
                      <span data-testid="admin-formula-check" className={`text-xs ${formulaCheck.startsWith('✓') ? 'text-green-600' : 'text-red-600'}`}>{formulaCheck}</span>
                    </div>
                  )}
                </div>
              ))}
            </div>
            <div className="mt-5 flex justify-end gap-2">
              <button data-testid="admin-cancel" onClick={() => setEditing(null)} className="rounded border border-line px-3 py-1.5 text-sm">Cancel</button>
              <button data-testid="admin-save" onClick={save} className="rounded bg-primary px-3 py-1.5 text-sm font-semibold text-white">Save</button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
