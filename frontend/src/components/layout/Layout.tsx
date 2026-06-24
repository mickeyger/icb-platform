import type { ReactNode } from 'react'
import { TopNav } from './TopNav'
import { FeedbackWidget } from '../feedback/FeedbackWidget'

export function Layout({
  children,
  dark = false,
}: {
  children: ReactNode
  dark?: boolean
}) {
  // WO v4.32 §0.14: the "Phase 0 mockup · Snapshot …" footer banner is GONE — with the
  // dashboards wired to live data it was false on every page.
  return (
    <div className={`flex h-screen flex-col overflow-hidden ${dark ? 'bg-slate-900' : 'bg-surface-alt'}`}>
      <TopNav dark={dark} />
      {/* WO v4.29: app-shell — main is the scroll container (min-h-0 lets it shrink so screens that
          manage their own internal scroll, e.g. the Planning board, fit one viewport without a page scroll). */}
      <main className="flex-1 min-h-0 overflow-y-auto">{children}</main>
      {/* WO v4.38 — global Feedback Portal launcher. Mounted here so it renders on every
          /mes-app/* screen and NEVER on the /calculator Jinja pages (byte-identical). */}
      <FeedbackWidget />
    </div>
  )
}
