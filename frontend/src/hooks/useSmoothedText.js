import { useEffect, useRef, useState } from 'react'
import { nextRevealLength, revealedPrefix, isContinuation } from '../utils/smoothReveal.js'

const COMMIT_INTERVAL_MS = 33 // about 30fps: the displayed string is re-parsed as markdown
const FIRST_FRAME_DT_MS = 16

function prefersReducedMotion() {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return false
  try {
    return window.matchMedia('(prefers-reduced-motion: reduce)').matches
  } catch {
    return false
  }
}

function tabHidden() {
  return typeof document !== 'undefined' && document.hidden === true
}

/**
 * Eases the displayed text toward targetText (streaming "typewriter" smoothing).
 * Returns the string to display. With enabled=false it returns targetText unchanged
 * and runs no animation frames.
 */
export default function useSmoothedText(targetText, enabled = true) {
  const text = typeof targetText === 'string' ? targetText : ''
  const [shownLen, setShownLen] = useState(0)
  const shownRef = useRef(0) // authoritative revealed length
  const committedRef = useRef(0) // last length pushed to state
  const prevTextRef = useRef('')
  const rafRef = useRef(null)

  useEffect(() => {
    const cancel = () => {
      if (rafRef.current !== null && typeof cancelAnimationFrame === 'function') {
        cancelAnimationFrame(rafRef.current)
      }
      rafRef.current = null
    }
    const commit = (len) => {
      if (len !== committedRef.current) {
        committedRef.current = len
        setShownLen(len)
      }
    }

    const prev = prevTextRef.current
    prevTextRef.current = text

    // Disabled: show everything, keep refs in sync so re-enabling does not restart.
    if (!enabled) {
      cancel()
      shownRef.current = text.length
      commit(text.length)
      return undefined
    }

    // Replaced or reset text (new answer, or empty): start over.
    if (!isContinuation(prev, text)) {
      shownRef.current = 0 // empty text: 0 is also its full length
      commit(shownRef.current)
    }
    if (shownRef.current > text.length) shownRef.current = text.length

    // Background tab: rAF is throttled, so just show the target.
    if (tabHidden() || typeof requestAnimationFrame !== 'function') {
      shownRef.current = text.length
      commit(text.length)
      return undefined
    }

    // Nothing to animate: no idle loop.
    if (shownRef.current >= text.length) {
      commit(shownRef.current)
      return undefined
    }

    const reduced = prefersReducedMotion()
    let lastTs = null
    let lastCommitTs = null

    const tick = (ts) => {
      rafRef.current = null
      if (tabHidden()) {
        shownRef.current = text.length
        commit(text.length)
        return
      }
      const dtMs = lastTs === null ? FIRST_FRAME_DT_MS : Math.max(0, ts - lastTs)
      lastTs = ts
      const next = nextRevealLength({
        shown: shownRef.current,
        target: text.length,
        dtMs,
        reduced,
      })
      shownRef.current = next
      const done = next >= text.length
      if (lastCommitTs === null || done || ts - lastCommitTs >= COMMIT_INTERVAL_MS) {
        lastCommitTs = ts
        commit(next)
      }
      if (!done) rafRef.current = requestAnimationFrame(tick)
    }

    rafRef.current = requestAnimationFrame(tick)
    return cancel
  }, [text, enabled])

  if (!enabled) return text
  return revealedPrefix(text, Math.min(shownLen, text.length))
}
