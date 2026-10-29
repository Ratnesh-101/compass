import React, { useEffect, useId, useRef } from 'react'
import {
  FOCUSABLE_SELECTOR,
  ROOT_SENTINEL,
  nextTabTarget,
  pushDialog,
  removeDialog,
  isTopDialog,
} from '../utils/dialogFocus'

const inertCounts = new WeakMap()

// React's autoFocus can move focus into a dialog before our effect runs, so track the
// element that was focused just before the current one to restore focus to the trigger.
const focusHistory = { previous: null, current: null }
if (typeof document !== 'undefined') {
  document.addEventListener(
    'focusin',
    event => {
      if (event.target === focusHistory.current) return
      focusHistory.previous = focusHistory.current
      focusHistory.current = event.target
    },
    true,
  )
}

// Marks everything outside the dialog (siblings along the path to <body>) inert so
// background content is neither tabbable nor exposed to assistive tech. Ref-counted so
// stacked dialogs release the background in the right order.
function makeBackgroundInert(root) {
  const touched = []
  let node = root
  while (node && node !== document.body) {
    const parent = node.parentElement
    if (!parent) break
    for (const sibling of parent.children) {
      if (sibling === node || sibling.tagName === 'SCRIPT') continue
      const count = inertCounts.get(sibling) || 0
      if (count === 0) sibling.setAttribute('inert', '')
      inertCounts.set(sibling, count + 1)
      touched.push(sibling)
    }
    node = parent
  }
  return () => {
    for (const el of touched) {
      const count = (inertCounts.get(el) || 1) - 1
      inertCounts.set(el, count)
      if (count === 0) el.removeAttribute('inert')
    }
  }
}

const listFocusables = root =>
  Array.from(root.querySelectorAll(FOCUSABLE_SELECTOR)).filter(el => el.getClientRects().length > 0)

/**
 * Accessible modal root. Drop-in replacement for the fixed overlay <div>:
 * role="dialog", aria-modal, aria-labelledby (first heading), focus trap, Escape to close,
 * focus moved in on open and restored on close, background made inert.
 * Pass closeOnEscape={false} to block Escape (e.g. while an import is running).
 */
export default function Dialog({ onClose, closeOnEscape = true, children, ...divProps }) {
  const rootRef = useRef(null)
  const onCloseRef = useRef(onClose)
  const escapeRef = useRef(closeOnEscape)
  onCloseRef.current = onClose
  escapeRef.current = closeOnEscape
  const generatedId = useId()

  useEffect(() => {
    const root = rootRef.current
    if (!root) return undefined
    const token = {}
    const previouslyFocused = root.contains(document.activeElement) ? focusHistory.previous : document.activeElement
    pushDialog(token)
    const releaseBackground = makeBackgroundInert(root)

    if (!divProps['aria-labelledby'] && !divProps['aria-label']) {
      const heading = root.querySelector('h1, h2, h3, [data-dialog-title]')
      if (heading) {
        if (!heading.id) heading.id = `${generatedId}-title`
        root.setAttribute('aria-labelledby', heading.id)
      } else {
        root.setAttribute('aria-label', 'Dialog')
      }
    }

    if (!root.contains(document.activeElement)) {
      const preferred = root.querySelector('[data-autofocus]') || listFocusables(root)[0]
      ;(preferred || root).focus({ preventScroll: true })
    }

    const handleKeyDown = event => {
      if (!isTopDialog(token) || event.defaultPrevented) return
      if (event.key === 'Escape') {
        if (escapeRef.current && onCloseRef.current) {
          event.stopPropagation()
          onCloseRef.current()
        }
        return
      }
      if (event.key !== 'Tab') return
      const target = nextTabTarget(listFocusables(root), document.activeElement, event.shiftKey)
      if (target === null) return
      event.preventDefault()
      ;(target === ROOT_SENTINEL ? root : target).focus()
    }
    document.addEventListener('keydown', handleKeyDown, true)

    return () => {
      document.removeEventListener('keydown', handleKeyDown, true)
      removeDialog(token)
      releaseBackground()
      if (previouslyFocused && previouslyFocused.isConnected && typeof previouslyFocused.focus === 'function') {
        previouslyFocused.focus({ preventScroll: true })
      }
    }
    // Runs once per mount: dialogs are mounted only while open.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return (
    <div ref={rootRef} role="dialog" aria-modal="true" tabIndex={-1} {...divProps}>
      {children}
    </div>
  )
}
