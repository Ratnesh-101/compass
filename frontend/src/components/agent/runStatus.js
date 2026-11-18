// Header text for the Planner run card.
export function runStatusLabel(isRunning, pendingActions) {
  if (isRunning) return 'Working on it…'
  if (pendingActions && pendingActions.length > 0) return 'Waiting for your approval'
  return 'All done'
}
