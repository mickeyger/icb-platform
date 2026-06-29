// useCockpitLayout.ts — WO Cockpit (Concept 6). Layout state for the additive Planning Cockpit:
// collapsible left rail / right inspector / bottom dock + native-fullscreen Focus Mode. Collapse
// state persists to localStorage; fullscreen is session-only (never persisted). No app-wide state —
// this is scoped to the cockpit page and touches nothing the existing /planning board relies on.
import { useCallback, useEffect, useRef, useState } from 'react'

export interface CockpitLayout {
  leftCollapsed: boolean
  rightCollapsed: boolean
  dockOpen: boolean
  isFullscreen: boolean
  toggleLeft: () => void
  toggleRight: () => void
  toggleDock: () => void
  setDockOpen: (v: boolean) => void
  /** Collapse both rails + close the dock — the one-click "max hero" timeline preset. */
  maxHero: () => void
  /** Native Fullscreen API toggle. Pass the cockpit root so only it goes fullscreen. */
  toggleFullscreen: (el?: HTMLElement | null) => void
}

const LS_KEY = 'icb:cockpit:layout'

interface Persisted {
  leftCollapsed: boolean
  rightCollapsed: boolean
  dockOpen: boolean
}

function readPersisted(): Persisted {
  const fallback: Persisted = { leftCollapsed: false, rightCollapsed: false, dockOpen: false }
  try {
    const raw = localStorage.getItem(LS_KEY)
    if (!raw) return fallback
    const p = JSON.parse(raw) as Partial<Persisted>
    return {
      leftCollapsed: !!p.leftCollapsed,
      rightCollapsed: !!p.rightCollapsed,
      dockOpen: !!p.dockOpen,
    }
  } catch {
    return fallback
  }
}

export function useCockpitLayout(): CockpitLayout {
  const initial = useRef(readPersisted())
  const [leftCollapsed, setLeftCollapsed] = useState(initial.current.leftCollapsed)
  const [rightCollapsed, setRightCollapsed] = useState(initial.current.rightCollapsed)
  const [dockOpen, setDockOpen] = useState(initial.current.dockOpen)
  const [isFullscreen, setIsFullscreen] = useState(false)

  // Persist collapse state (not fullscreen — that resets each visit).
  useEffect(() => {
    try {
      localStorage.setItem(LS_KEY, JSON.stringify({ leftCollapsed, rightCollapsed, dockOpen }))
    } catch {
      /* private mode / quota — non-fatal */
    }
  }, [leftCollapsed, rightCollapsed, dockOpen])

  // Mirror the real fullscreen state so Esc / F11 keep the button label honest.
  useEffect(() => {
    const onFs = () => setIsFullscreen(!!document.fullscreenElement)
    document.addEventListener('fullscreenchange', onFs)
    return () => document.removeEventListener('fullscreenchange', onFs)
  }, [])

  const toggleFullscreen = useCallback((el?: HTMLElement | null) => {
    // Only ever called from a click handler, which satisfies the user-gesture requirement.
    if (document.fullscreenElement) {
      void document.exitFullscreen?.()
    } else {
      const target = el ?? document.documentElement
      void target.requestFullscreen?.().catch(() => {})
    }
  }, [])

  const maxHero = useCallback(() => {
    setLeftCollapsed(true)
    setRightCollapsed(true)
    setDockOpen(false)
  }, [])

  return {
    leftCollapsed,
    rightCollapsed,
    dockOpen,
    isFullscreen,
    toggleLeft: () => setLeftCollapsed((v) => !v),
    toggleRight: () => setRightCollapsed((v) => !v),
    toggleDock: () => setDockOpen((v) => !v),
    setDockOpen,
    maxHero,
    toggleFullscreen,
  }
}
