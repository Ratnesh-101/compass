import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'

const read = rel => fs.readFileSync(new URL(`../src/${rel}`, import.meta.url), 'utf8')
const loadIcs = () => import('../src/utils/icsExport.js')

// ---- summarizeIcsExport -----------------------------------------------------

test('summarizeIcsExport counts exportable and undated open tasks', async () => {
  const { summarizeIcsExport } = await loadIcs()
  const tasks = [
    { id: 1, status: 'open', scheduled_start: '2026-11-30T10:00:00Z' },
    { id: 2, status: 'open', due_date: '2026-12-01' },
    { id: 3, status: 'open', due_at: '2026-12-02T09:00:00Z' },
    { id: 4, status: 'open' },
    { id: 5, status: 'open', due_date: null, scheduled_start: null },
  ]
  assert.deepEqual(summarizeIcsExport(tasks, 'all'), { exportable: 3, undated: 2 })
})

test('summarizeIcsExport ignores done, completed and cancelled tasks', async () => {
  const { summarizeIcsExport } = await loadIcs()
  const tasks = [
    { status: 'done', due_date: '2026-12-01' },
    { status: 'completed', scheduled_start: '2026-12-01T10:00:00Z' },
    { status: 'cancelled' },
    { status: 'done' },
  ]
  assert.deepEqual(summarizeIcsExport(tasks, 'all'), { exportable: 0, undated: 0 })
})

test('summarizeIcsExport applies the domain filter; all and empty mean every domain', async () => {
  const { summarizeIcsExport } = await loadIcs()
  const tasks = [
    { domain: 'code', due_date: '2026-12-01' },
    { domain: 'code' },
    { domain: 'coursework', due_date: '2026-12-01' },
    { domain: 'coursework' },
  ]
  assert.deepEqual(summarizeIcsExport(tasks, 'code'), { exportable: 1, undated: 1 })
  assert.deepEqual(summarizeIcsExport(tasks, 'all'), { exportable: 2, undated: 2 })
  assert.deepEqual(summarizeIcsExport(tasks, ''), { exportable: 2, undated: 2 })
})

test('summarizeIcsExport treats a missing status as open', async () => {
  const { summarizeIcsExport } = await loadIcs()
  assert.deepEqual(
    summarizeIcsExport([{ due_date: '2026-12-01' }, {}], 'all'),
    { exportable: 1, undated: 1 },
  )
})

test('summarizeIcsExport on an empty list gives zeros', async () => {
  const { summarizeIcsExport } = await loadIcs()
  assert.deepEqual(summarizeIcsExport([], 'all'), { exportable: 0, undated: 0 })
})

// ---- CalendarView source ----------------------------------------------------

test('CalendarView renders separate No deadline and Due-needs-a-slot groups', () => {
  const src = read('components/CalendarView.jsx')
  assert.ok(src.includes('No deadline'))
  assert.ok(src.includes('Due, needs a time slot'))
})

test('CalendarView leaves completed and cancelled tasks out of the unscheduled list', () => {
  const src = read('components/CalendarView.jsx')
  assert.ok(src.includes("'completed'"))
  assert.ok(src.includes("'cancelled'"))
})

test('CalendarView export handler skips the download when nothing is exportable', () => {
  const src = read('components/CalendarView.jsx')
  const start = src.indexOf('const handleExportIcs')
  assert.ok(start >= 0, 'handleExportIcs not found')
  const body = src.slice(start, src.indexOf('const handleDisconnect', start))
  assert.ok(body.includes('Nothing to export yet'))
  assert.ok(/exportable\s*(===|==|<=)\s*0|!\s*\w*\.?exportable/.test(body), 'no exportable === 0 guard')
  const guard = body.search(/exportable\s*(===|==|<=)\s*0|!\s*\w*\.?exportable/)
  const download = body.indexOf('downloadAuthedFile(')
  assert.ok(download > guard, 'download must come after the exportable guard')
  const returned = body.slice(guard, download)
  assert.ok(/return/.test(returned), 'guard must return before the download')
})

test('CalendarView success message says how many tasks were left out', () => {
  assert.ok(read('components/CalendarView.jsx').includes('left out'))
})

// ---- ProposedPlanModal source -----------------------------------------------

test('ProposedPlanModal labels undated placements, gated on has_deadline === false', () => {
  const src = read('components/calendar/CalendarModals.jsx')
  assert.ok(src.includes('No deadline, placed in free time'))
  assert.ok(src.includes('has_deadline === false'))
  const gate = src.indexOf('has_deadline === false')
  const label = src.indexOf('No deadline, placed in free time')
  assert.ok(Math.abs(label - gate) < 400, 'label is not next to the has_deadline gate')
})
