import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

// Polyfill browser globals for the Node test environment
if (!globalThis.localStorage) {
  const store = new Map()
  globalThis.localStorage = {
    getItem: (key) => store.get(key) ?? null,
    setItem: (key, val) => store.set(key, String(val)),
    removeItem: (key) => store.delete(key),
    clear: () => store.clear(),
  }
}
if (!globalThis.window) {
  globalThis.window = { location: { hostname: 'localhost' } }
}

const here = path.dirname(fileURLToPath(import.meta.url))
const read = (rel) => fs.readFileSync(path.join(here, '..', 'src', rel), 'utf8')

const { haveTasksChanged } = await import('../src/utils/taskDiff.js')
const { fetchTasks } = await import('../src/api/tasksApi.js')
// Missing on the pre-fix code; each test then fails on a clear "not a function".
let H = {}
try {
  H = await import('../src/utils/scheduleHonesty.js')
} catch {
  H = {}
}

// ---- 1. sync / commit banners come from what Google really created --------------------------

test('sync banner never says Synced when Google created nothing', () => {
  const res = { live_created: 0, error_count: 3, calendar_error: 'Compass is connected read-only: Google refused to create events (missing write permission). Reconnect after enabling calendar write access.', count: 3, live_count: 0, is_live: true }
  const banner = H.syncResultBanner(res, 'me@example.com')
  assert.equal(banner.type, 'error')
  assert.match(banner.text, /read-only/)
  assert.doesNotMatch(banner.text, /Synced/)
})

test('sync banner says Synced N only for real creations and reports partial failures', () => {
  assert.equal(H.syncResultBanner({ live_created: 2, error_count: 0 }, 'me@example.com').text, 'Synced 2 tasks to your Google Calendar (me@example.com).')
  const partial = H.syncResultBanner({ live_created: 1, error_count: 2, calendar_error: 'Boom.' }, null)
  assert.equal(partial.type, 'warning')
  assert.match(partial.text, /^Synced 1 task to your Google Calendar, but 2 could not be created\. Boom\./)
})

test('simulated sync is labelled Simulated', () => {
  const banner = H.syncResultBanner({ live_created: 0, error_count: 0, simulated_count: 4 }, null)
  assert.match(banner.text, /^Simulated 4 tasks/)
  assert.doesNotMatch(banner.text, /Synced/)
})

test('commit banner counts what the backend committed, not what was requested', () => {
  const banner = H.commitResultBanner({ committed_count: 1, rejected_task_ids: [8, 9], live_created: 0, error_count: 0 })
  assert.equal(banner.type, 'warning')
  assert.match(banner.text, /^Scheduled 1 task in Compass\./)
  assert.match(banner.text, /2 tasks could not be scheduled \(ids: 8, 9\)/)
  assert.doesNotMatch(banner.text, /Google Calendar/)
  assert.equal(H.commitResultBanner({ committed_count: 0, rejected_task_ids: [1] }).type, 'error')
})

test('commit banner shows the calendar error instead of claiming a Google sync', () => {
  const banner = H.commitResultBanner({ committed_count: 2, live_created: 0, error_count: 2, calendar_error: 'Google refused.' })
  assert.match(banner.text, /Google refused\./)
  assert.doesNotMatch(banner.text, /synced to Google/i)
  assert.equal(H.commitResultBanner({ committed_count: 2, live_created: 2 }).text, 'Scheduled 2 tasks in Compass. Created 2 Google Calendar events.')
})

test('commit validation errors are turned into readable text', () => {
  const text = H.commitErrorText({ detail: 'x', errors: [{ index: 1, task_id: 5, error: 'This slot starts in the past. Propose a new schedule.' }] })
  assert.match(text, /^Nothing was scheduled\. #5: This slot starts in the past/)
})

test('commitSchedule surfaces the validation errors from a 422', () => {
  const api = read('api/calendarApi.js')
  assert.match(api, /commitErrorText\(err\)/)
})

// ---- 9. plan state and reactive banner -------------------------------------------------------

test('an empty proposed plan cannot be committed and explains why', () => {
  const state = H.planCommitState({
    scheduled: [],
    unassigned: [{ task_id: 3, title: 'Essay', reason: 'Insufficient free time windows within working hours or before deadline.' }],
    conflicts: [{ task_id: 4, title: 'Report', issue: 'Cannot be scheduled before deadline with current calendar load.' }],
  })
  assert.equal(state.canCommit, false)
  assert.equal(state.reasons.length, 2)
  assert.match(state.reasons[0], /^Essay: Insufficient free time/)
  assert.equal(H.planCommitState({ scheduled: [{ task_id: 1 }] }).canCommit, true)
})

test('the commit button is disabled for an empty plan and no longer promises a Google sync', () => {
  const modals = read('components/calendar/CalendarModals.jsx')
  assert.match(modals, /disabled=\{committing \|\| !canCommit\}/)
  assert.doesNotMatch(modals, /Approve & Commit to Google Calendar/)
})

test('reactive banner only claims staging when a run id exists', () => {
  const none = H.reactiveResultBanner({ slipped_count: 2, run_id: null })
  assert.doesNotMatch(none.text, /Run ID/)
  assert.doesNotMatch(none.text, /re-plan staged/)
  assert.match(none.text, /nothing was staged/)
  const staged = H.reactiveResultBanner({ slipped_count: 1, run_id: 'reactive_replan_1' })
  assert.match(staged.text, /re-plan staged for your approval \(Run ID: reactive_replan_1\)/)
  const view = read('components/CalendarView.jsx')
  assert.doesNotMatch(view, /run_id \|\| 'staged'/)
})

// ---- 10. availability errors are surfaced ----------------------------------------------------

test('availability error text is built from calendar_error', () => {
  assert.equal(H.availabilityNote({ busy_intervals: [] }), null)
  assert.equal(H.availabilityNote({ calendar_error: 'Reconnect.' }), 'Could not read your Google Calendar: Reconnect.')
})

test('calendarApi no longer converts availability errors into an empty busy list', () => {
  const api = read('api/calendarApi.js')
  const start = api.indexOf('export async function fetchCalendarAvailability')
  const body = api.slice(start, api.indexOf('export async function proposeSchedule'))
  assert.doesNotMatch(body, /busy_intervals: \[\]/)
  assert.match(body, /calendar_error/)
})

// ---- 2. due date handling --------------------------------------------------------------------

test('due date is sent only when the user changed it', () => {
  assert.deepEqual(H.dueDatePatch('2031-06-30', '2031-06-30'), {})
  assert.deepEqual(H.dueDatePatch('2031-06-02T10:00:00+00:00', '2031-06-02'), {})
  assert.deepEqual(H.dueDatePatch('2031-06-30', '2031-07-01'), { due_date: '2031-07-01' })
  assert.deepEqual(H.dueDatePatch('2031-06-30', ''), { due_date: null })
  assert.deepEqual(H.dueDatePatch(null, ''), {})
  assert.equal(H.dueDateForInput('2031-06-02T10:00:00+00:00'), '2031-06-02')
})

test('TaskDetailModal uses the changed-only due date patch', () => {
  const modal = read('components/timeline/TaskDetailModal.jsx')
  assert.match(modal, /\.\.\.dueDatePatch\(task\.due_date, editDueDate\)/)
  assert.doesNotMatch(modal, /due_date: editDueDate \|\| null/)
})

// ---- 4. failed task fetch keeps the current view ---------------------------------------------

test('fetchTasks returns null (not an empty list) on a 503', async () => {
  const original = globalThis.fetch
  globalThis.fetch = async () => ({ ok: false, status: 503, json: async () => ({ detail: 'down' }), headers: new Map() })
  try {
    assert.equal(await fetchTasks('all'), null)
  } finally {
    globalThis.fetch = original
  }
})

// ---- 6. no non-working subscription option ---------------------------------------------------

test('the sync guide no longer offers the unauthenticated subscription URL', () => {
  const modals = read('components/calendar/CalendarModals.jsx')
  assert.doesNotMatch(modals, /Calendar Subscription URL/)
  assert.doesNotMatch(modals, /From URL/)
  assert.match(modals, /Download compass_schedule\.ics/)
})

// ---- 8. task diff covers edited fields ------------------------------------------------------

test('taskDiff notices description, duration, project and slot changes', () => {
  const base = { id: '1', title: 'T', description: 'a', duration_minutes: 60, project: 'General', scheduled_start: null, scheduled_end: null }
  assert.equal(haveTasksChanged([base], [{ ...base }]), false)
  for (const patch of [
    { description: 'b' },
    { duration_minutes: 90 },
    { project: 'Thesis' },
    { scheduled_start: '2031-01-01T09:00:00+00:00' },
    { scheduled_end: '2031-01-01T10:00:00+00:00' },
  ]) {
    assert.equal(haveTasksChanged([base], [{ ...base, ...patch }]), true, JSON.stringify(patch))
  }
})

// ---- wiring ---------------------------------------------------------------------------------

test('CalendarView builds its banners from the honest helpers', () => {
  const view = read('components/CalendarView.jsx')
  assert.match(view, /syncResultBanner\(res/)
  assert.match(view, /commitResultBanner\(result\)/)
  assert.match(view, /reactiveResultBanner\(res\)/)
  assert.doesNotMatch(view, /synced to Google Calendar!/)
  assert.doesNotMatch(view, /directly to your Google Calendar/)
  assert.match(view, /Could not read|availabilityNote/)
})
