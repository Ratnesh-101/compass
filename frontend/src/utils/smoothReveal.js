// Helpers for revealing streamed text smoothly instead of in network-sized bursts.

const MAX_DT_MS = 100
const MIN_RATE = 90 // chars per second: a trickle still moves smoothly
const CATCH_UP_FACTOR = 12 // backlog shrinks with a ~80ms time constant, so the text never trails the stream for long

function toCount(value) {
  return Number.isFinite(value) ? Math.max(0, Math.floor(value)) : 0
}

// New number of characters to show. `target` is the length of all text received
// so far, `shown` is how many characters are currently displayed.
export function nextRevealLength({ shown, target, dtMs, reduced = false } = {}) {
  const total = toCount(target)
  if (reduced) return total
  const current = toCount(shown)
  if (current >= total) return total

  const dt = Number.isFinite(dtMs) ? Math.min(MAX_DT_MS, Math.max(0, dtMs)) : 0
  const backlog = total - current
  const rate = Math.max(MIN_RATE, backlog * CATCH_UP_FACTOR)
  const step = Math.max(1, Math.round((rate * dt) / 1000))
  return Math.min(total, Math.max(current, current + step))
}

// text.slice(0, length) that never ends on the first half of a surrogate pair.
export function revealedPrefix(text, length) {
  const str = typeof text === 'string' ? text : ''
  const end = toCount(length)
  if (end >= str.length) return str
  if (end === 0) return ''
  const code = str.charCodeAt(end - 1)
  const cut = code >= 0xd800 && code <= 0xdbff ? end - 1 : end
  return str.slice(0, cut)
}

// True when the streamed text kept growing (next starts with prev) rather than being replaced.
export function isContinuation(prevTarget, nextTarget) {
  if (typeof prevTarget !== 'string' || typeof nextTarget !== 'string') return false
  return nextTarget.startsWith(prevTarget)
}
