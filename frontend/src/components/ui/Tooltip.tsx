import {
  useEffect,
  useId,
  useRef,
  useState,
  type ReactNode,
} from 'react'
import { createPortal } from 'react-dom'
import { useAppData } from '../../store/AppDataContext'
import { lookupTooltip, LONG_TOOLTIP_THRESHOLD } from '../../data/tooltips'

// Prefix highlighting helps the eye scan a wall of tooltips in the demo.
// Four prefixes per icb_tooltips.json: "Replaces:", "Replaces & augments:",
// "New:", and "Already exists:" (system kept in place / integrates with).
function splitPrefix(text: string): { prefix: string | null; rest: string } {
  const m = text.match(/^(Replaces & augments:|Replaces:|New:|Already exists:)\s*/)
  if (!m) return { prefix: null, rest: text }
  return { prefix: m[1].replace(/:$/, ''), rest: text.slice(m[0].length) }
}

function prefixClasses(prefix: string | null): string {
  if (prefix === 'New') return 'bg-status-green/20 text-status-green'
  if (prefix === 'Replaces & augments') return 'bg-status-amber/20 text-status-amber'
  if (prefix === 'Replaces') return 'bg-primary-light text-primary'
  if (prefix === 'Already exists') return 'bg-slate-200/90 text-slate-700'
  return ''
}

interface TooltipProps {
  /** i18n key into icb_tooltips.json. Optional when `text` is supplied directly. */
  k?: string
  /** Free text — v1.39.1: lets callers convert native dark `title=` attributes to the light custom tooltip. */
  text?: string
  children: ReactNode
  /** Override placement (default: auto below, flips above near bottom edge). */
  placement?: 'auto' | 'top' | 'bottom'
}

/**
 * Generic tooltip used across every screen. Text is looked up by `k`
 * (e.g. "nav.planning") from icb_tooltips.json — never hard-coded here.
 *
 * Implementation note: wraps children in a `display:contents` span so the
 * wrapper has a DOM ref without affecting layout (works for any child,
 * including function components without forwardRef). We measure the first
 * element child's bounding box for positioning, and attach
 * aria-describedby to it imperatively when the tooltip opens.
 *
 * Behaviour (per addendum §2):
 *  - hover (300ms) on pointer devices; long-press (500ms) on touch.
 *  - 200ms persistence after pointer leaves.
 *  - >200-char tooltips render as click-to-dismiss popovers.
 *  - role="tooltip" + aria-describedby; surfaces on keyboard focus.
 *  - global tooltipsEnabled flag silently disables all tooltips.
 *  - missing key → wrapped element with no tooltip (no error).
 */
export function Tooltip({ k, text: textProp, children, placement = 'auto' }: TooltipProps) {
  const { tooltipsEnabled } = useAppData()
  const text = textProp ?? (k ? lookupTooltip(k) : undefined)
  const id = useId()
  const wrapperRef = useRef<HTMLSpanElement>(null)
  const showTimer = useRef<number | null>(null)
  const hideTimer = useRef<number | null>(null)
  const longPressTimer = useRef<number | null>(null)
  const [open, setOpen] = useState(false)
  const [pos, setPos] = useState({ top: 0, left: 0 })
  const [pinned, setPinned] = useState(false)

  const isLong = !!text && text.length > LONG_TOOLTIP_THRESHOLD

  function targetEl(): Element | null {
    return wrapperRef.current?.firstElementChild ?? null
  }

  function compute() {
    const el = targetEl()
    if (!el) return
    const r = el.getBoundingClientRect()
    const margin = 8
    const tipWidth = 360
    const tipHeightEstimate = isLong ? 200 : 80
    let top = r.bottom + 6
    if (placement === 'top' || (placement === 'auto' && top + tipHeightEstimate > window.innerHeight - margin)) {
      top = r.top - 6 - tipHeightEstimate
    }
    let left = r.left + r.width / 2 - tipWidth / 2
    left = Math.max(margin, Math.min(left, window.innerWidth - tipWidth - margin))
    setPos({ top, left })
  }

  function show() {
    if (!tooltipsEnabled || !text) return
    if (hideTimer.current) {
      window.clearTimeout(hideTimer.current)
      hideTimer.current = null
    }
    if (showTimer.current) return
    showTimer.current = window.setTimeout(() => {
      compute()
      setOpen(true)
      targetEl()?.setAttribute('aria-describedby', id)
      showTimer.current = null
    }, 300)
  }

  function hide(immediate = false) {
    if (showTimer.current) {
      window.clearTimeout(showTimer.current)
      showTimer.current = null
    }
    if (pinned) return
    const doHide = () => {
      setOpen(false)
      targetEl()?.removeAttribute('aria-describedby')
    }
    if (immediate) {
      doHide()
      return
    }
    hideTimer.current = window.setTimeout(() => {
      doHide()
      hideTimer.current = null
    }, 200)
  }

  // Attach passive handlers to the actual child element so layout isn't
  // affected and existing handlers on children continue to work.
  useEffect(() => {
    const el = targetEl()
    if (!el || !text || !tooltipsEnabled) return
    const onEnter = () => show()
    const onLeave = () => hide()
    const onFocus = () => show()
    const onBlur = () => hide(true)
    const onTouchStart = () => {
      longPressTimer.current = window.setTimeout(() => {
        compute()
        setOpen(true)
        if (isLong) setPinned(true)
        longPressTimer.current = null
      }, 500)
    }
    const onTouchEnd = () => {
      if (longPressTimer.current) {
        window.clearTimeout(longPressTimer.current)
        longPressTimer.current = null
      }
    }
    const onClickPin = () => {
      if (isLong && open) setPinned(true)
    }
    el.addEventListener('mouseenter', onEnter)
    el.addEventListener('mouseleave', onLeave)
    el.addEventListener('focusin', onFocus)
    el.addEventListener('focusout', onBlur)
    el.addEventListener('touchstart', onTouchStart, { passive: true })
    el.addEventListener('touchend', onTouchEnd)
    el.addEventListener('click', onClickPin)
    return () => {
      el.removeEventListener('mouseenter', onEnter)
      el.removeEventListener('mouseleave', onLeave)
      el.removeEventListener('focusin', onFocus)
      el.removeEventListener('focusout', onBlur)
      el.removeEventListener('touchstart', onTouchStart)
      el.removeEventListener('touchend', onTouchEnd)
      el.removeEventListener('click', onClickPin)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [text, tooltipsEnabled, isLong, open])

  // Dismiss pinned long popover on outside click / Esc.
  useEffect(() => {
    if (!pinned) return
    const onClick = (e: MouseEvent) => {
      const t = e.target as Node
      if (wrapperRef.current?.contains(t)) return
      const tip = document.getElementById(id)
      if (tip?.contains(t)) return
      setPinned(false)
      setOpen(false)
    }
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setPinned(false)
        setOpen(false)
      }
    }
    window.addEventListener('mousedown', onClick)
    window.addEventListener('keydown', onKey)
    return () => {
      window.removeEventListener('mousedown', onClick)
      window.removeEventListener('keydown', onKey)
    }
  }, [pinned, id])

  // Clear timers on unmount.
  useEffect(
    () => () => {
      if (showTimer.current) window.clearTimeout(showTimer.current)
      if (hideTimer.current) window.clearTimeout(hideTimer.current)
      if (longPressTimer.current) window.clearTimeout(longPressTimer.current)
    },
    [],
  )

  if (!tooltipsEnabled || !text) {
    return <>{children}</>
  }

  const { prefix, rest } = splitPrefix(text)

  const tip =
    open &&
    createPortal(
      <div
        id={id}
        role="tooltip"
        onMouseEnter={() => {
          if (hideTimer.current) {
            window.clearTimeout(hideTimer.current)
            hideTimer.current = null
          }
        }}
        onMouseLeave={() => hide()}
        style={{ top: pos.top, left: pos.left, width: 360 }}
        // v1.39.1 backport (Item 3): surface-matched LIGHT tooltip (BA override of the dark convention) —
        // bg-white + dark text, with a border + shadow so it stays visually distinct from the page surface.
        className={`pointer-events-auto fixed z-[100] rounded-md border border-slate-200 bg-white px-3 py-2 text-[13px] leading-snug text-slate-900 shadow-lg ${
          isLong ? '' : 'animate-fadeIn'
        }`}
      >
        {prefix && (
          <span className={`mb-1 mr-1 inline-block rounded px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wide ${prefixClasses(prefix)}`}>
            {prefix}
          </span>
        )}
        <span>{rest}</span>
        {isLong && (
          <div className="mt-2 text-right text-[11px] uppercase tracking-wide text-slate-500">
            Click outside or press Esc to close
          </div>
        )}
      </div>,
      document.body,
    )

  return (
    <>
      <span ref={wrapperRef} style={{ display: 'contents' }}>
        {children}
      </span>
      {tip}
    </>
  )
}
