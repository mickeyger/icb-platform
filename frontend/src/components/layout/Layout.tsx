import type { ReactNode } from 'react'
import { TopNav } from './TopNav'
import { data } from '../../data/mockData'
import { dmy } from '../../lib/format'

export function Layout({
  children,
  dark = false,
}: {
  children: ReactNode
  dark?: boolean
}) {
  return (
    <div className={`flex h-screen flex-col overflow-hidden ${dark ? 'bg-slate-900' : 'bg-surface-alt'}`}>
      <TopNav dark={dark} />
      {/* WO v4.29: app-shell — main is the scroll container (min-h-0 lets it shrink so screens that
          manage their own internal scroll, e.g. the Planning board, fit one viewport without a page scroll). */}
      <main className="flex-1 min-h-0 overflow-y-auto">{children}</main>
      {!dark && (
        <footer className="border-t border-line bg-white px-4 py-2 text-center text-xs text-muted">
          Icecold Bodies MES — Phase 0 mockup · Snapshot {dmy(data._meta.snapshot_date)} ·
          Currency {data._meta.currency} · Illustrative data
        </footer>
      )}
    </div>
  )
}
