// Pure helpers that turn backend schedule/sync results into honest user-facing messages.
// Rule: "Synced N" is only ever built from events Google really created (live_created).

const plural = (n, word) => `${n} ${word}${n === 1 ? '' : 's'}`

// The date input needs YYYY-MM-DD; the API may return a full ISO timestamp.
export function dueDateForInput(value) {
  return value ? String(value).slice(0, 10) : ''
}

// Send due_date only when the user actually changed it (so a slot timestamp is never sent back).
export function dueDatePatch(originalDueDate, editedValue) {
  const edited = editedValue || ''
  if (dueDateForInput(originalDueDate) === edited) return {}
  return { due_date: edited || null }
}

export const SIGN_IN_TO_SYNC = 'Sign in with Google to sync your calendar.'

// Banner for a failed (or skipped, when not signed in) calendar sync. Never leaks backend auth internals.
export function syncErrorBanner(err, signedIn = true) {
  const msg = String(err?.message || '')
  if (!signedIn || /compass_session|cookie|HTTP 40[13]|not authenticated|sign in/i.test(msg)) {
    return { type: 'info', text: SIGN_IN_TO_SYNC }
  }
  return { type: 'error', text: `Failed to sync: ${msg || 'unknown error'}` }
}

// Result of POST /api/calendar/sync-now
export function syncResultBanner(res, accountEmail) {
  const live = Number(res?.live_created ?? 0)
  const errors = Number(res?.error_count ?? 0)
  const simulated = Number(res?.simulated_count ?? 0)
  const where = accountEmail ? ` (${accountEmail})` : ''
  if (live > 0 && errors === 0) {
    return { type: 'success', text: `Synced ${plural(live, 'task')} to your Google Calendar${where}.` }
  }
  if (live > 0) {
    return {
      type: 'warning',
      text: `Synced ${plural(live, 'task')} to your Google Calendar${where}, but ${errors} could not be created. ${res.calendar_error || ''}`.trim(),
    }
  }
  if (errors > 0) {
    return { type: 'error', text: res.calendar_error || `Google Calendar did not create ${plural(errors, 'event')}.` }
  }
  if (simulated > 0) {
    return { type: 'info', text: `Simulated ${plural(simulated, 'task')} (demo mode). Nothing was sent to Google Calendar.` }
  }
  return { type: 'info', text: res?.message || 'Nothing to sync: no open scheduled tasks or deadlines.' }
}

// Result of POST /api/schedule/commit (the `data` object)
export function commitResultBanner(res) {
  const committed = Number(res?.committed_count ?? 0)
  const rejected = Array.isArray(res?.rejected_task_ids) ? res.rejected_task_ids : []
  const live = Number(res?.live_created ?? 0)
  const errors = Number(res?.error_count ?? 0)
  if (committed === 0) {
    const why = rejected.length ? ` ${plural(rejected.length, 'task')} could not be scheduled (not found or not yours).` : ''
    return { type: 'error', text: `No tasks were scheduled.${why}` }
  }
  const parts = [`Scheduled ${plural(committed, 'task')} in Compass.`]
  if (live > 0) parts.push(`Created ${plural(live, 'Google Calendar event')}.`)
  if (errors > 0 && res.calendar_error) parts.push(res.calendar_error)
  if (rejected.length) parts.push(`${plural(rejected.length, 'task')} could not be scheduled (ids: ${rejected.join(', ')}).`)
  const clean = errors === 0 && rejected.length === 0
  return { type: clean ? 'success' : 'warning', text: parts.join(' ') }
}

// Error body of a rejected commit: {detail, message, errors: [{index, task_id, error}]}
export function commitErrorText(body) {
  if (body && Array.isArray(body.errors) && body.errors.length) {
    const lines = body.errors.slice(0, 3).map((e) => `#${e.task_id ?? e.index}: ${e.error}`)
    return `Nothing was scheduled. ${lines.join(' ')}`
  }
  if (body && typeof body.message === 'string') return body.message
  return body && typeof body.detail === 'string' ? body.detail : ''
}

// Result of POST /api/schedule/reactive-check
export function reactiveResultBanner(res) {
  const slipped = Number(res?.slipped_count ?? 0)
  if (slipped === 0) {
    return { type: 'success', text: 'Schedule is currently on track: no uncompleted tasks have slipped past their end time.' }
  }
  if (res.run_id) {
    return {
      type: 'warning',
      text: `Detected ${plural(slipped, 'slipped task')} past scheduled end time. Reactive re-plan staged for your approval (Run ID: ${res.run_id}).`,
    }
  }
  return {
    type: 'warning',
    text: `Detected ${plural(slipped, 'slipped task')} past scheduled end time, but no free slots were found, so nothing was staged.`,
  }
}

// Can the proposed plan be committed, and why not / what was left out?
export function planCommitState(plan) {
  const scheduled = Array.isArray(plan?.scheduled) ? plan.scheduled : []
  const unassigned = Array.isArray(plan?.unassigned) ? plan.unassigned : []
  const conflicts = Array.isArray(plan?.conflicts) ? plan.conflicts : []
  const reasons = [
    ...unassigned.map((u) => `${u.title || `Task #${u.task_id}`}: ${u.reason || 'could not be placed'}`),
    ...conflicts.map((c) => `${c.title || `Task #${c.task_id}`}: ${c.issue || 'deadline conflict'}`),
  ]
  return { canCommit: scheduled.length > 0, reasons }
}

// Inline note when the live Google read failed
export function availabilityNote(data) {
  return data && data.calendar_error ? `Could not read your Google Calendar: ${data.calendar_error}` : null
}
