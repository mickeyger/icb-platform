/** WO v4.26 §0.9/§3.6 — admin module: sidebar + the active master-data CRUD sub-screen.
 * Routes: /admin/{spec-options,rules,lookups,price-overrides}. Admin-gated (AppData.isAdmin). */
import { NavLink, Navigate, useParams } from 'react-router-dom'

import { EmptyState } from '../../components/ui/feedback'
import { useAppData } from '../../store/AppDataContext'
import { AdminCrudTable } from './AdminCrudTable'
import { PrejobTemplatesAdmin } from './PrejobTemplatesAdmin'
import { ADMIN_ORDER, ADMIN_RESOURCES } from './adminResources'

export function AdminModule() {
  const { isAdmin, apiMode } = useAppData()
  const { resource } = useParams<{ resource: string }>()

  if (apiMode !== 'loading' && !isAdmin) {
    return (
      <div className="p-4">
        <EmptyState title="Admin access required"
                    hint="Master-data administration is restricted to admin users." />
      </div>
    )
  }
  if (!resource || !(resource in ADMIN_RESOURCES)) {
    return <Navigate to="/admin/spec-options" replace />
  }
  const cfg = ADMIN_RESOURCES[resource]

  return (
    <div className="flex gap-4 p-4">
      <aside className="w-52 shrink-0">
        <h1 className="mb-2 text-sm font-bold uppercase tracking-wide text-muted">Master data</h1>
        <nav className="space-y-1">
          {ADMIN_ORDER.map((k) => (
            <NavLink key={k} to={`/admin/${k}`} data-testid={`admin-nav-${k}`}
              className={({ isActive }) =>
                `block rounded px-3 py-2 text-sm ${isActive ? 'bg-primary text-white' : 'text-body hover:bg-surface-alt'}`}>
              {ADMIN_RESOURCES[k].title}
            </NavLink>
          ))}
        </nav>
        <p className="mt-3 px-1 text-xs text-muted">WO v4.26 — full CRUD, admin only. Formulas run
          against resolved specs by the AST-safe evaluator.</p>
      </aside>
      <main className="min-w-0 flex-1">
        {cfg.custom
          ? <PrejobTemplatesAdmin key={resource} />
          : <AdminCrudTable key={resource} config={cfg} />}
      </main>
    </div>
  )
}
