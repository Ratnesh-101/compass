// Decides whether a failed chat stream may be re-sent once automatically.
// Never re-send after the server already answered ('done' event) or showed a confirmation card
// (pending_action) for this request: a second run would repeat routing and replace that card.
export function shouldAutoResend(state) {
  const s = state || {}
  if (s.autoRetried || s.committed || s.aborted) return false
  if (s.doneSeen || s.pendingActionSeen) return false
  return true
}
