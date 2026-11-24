import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import { execFileSync } from 'node:child_process'

const read = rel => fs.readFileSync(new URL(`../src/${rel}`, import.meta.url), 'utf8')
const MODULE_URL = new URL('../src/utils/localTime.js', import.meta.url).href

// Run a snippet in a child node process with a given TZ; the snippet sees `m` (the module)
// and must console.log a JSON value.
function inTz(tz, body) {
  const script = `import(process.env.LT_URL).then(m => { const out = (${body})(m); console.log(JSON.stringify(out)) })`
  const stdout = execFileSync(process.execPath, ['-e', script], {
    env: { ...process.env, TZ: tz, LT_URL: MODULE_URL },
    encoding: 'utf8',
  })
  return JSON.parse(stdout.trim().split('\n').pop())
}

// ---- parseApiInstant (timezone independent) --------------------------------

test('parseApiInstant treats a naive ISO string as UTC', async () => {
  const { parseApiInstant } = await import(MODULE_URL)
  assert.equal(parseApiInstant('2026-11-25T03:30:00').toISOString(), '2026-11-25T03:30:00.000Z')
})

test('parseApiInstant accepts Z, offsets and Date objects', async () => {
  const { parseApiInstant } = await import(MODULE_URL)
  assert.equal(parseApiInstant('2026-11-25T03:30:00Z').toISOString(), '2026-11-25T03:30:00.000Z')
  assert.equal(parseApiInstant('2026-11-25T09:00:00+05:30').toISOString(), '2026-11-25T03:30:00.000Z')
  assert.equal(parseApiInstant('2026-11-25T03:30:00-02:00').toISOString(), '2026-11-25T05:30:00.000Z')
  const d = new Date('2026-11-25T03:30:00Z')
  assert.equal(parseApiInstant(d).toISOString(), '2026-11-25T03:30:00.000Z')
})

test('parseApiInstant returns null for garbage, null and undefined', async () => {
  const { parseApiInstant } = await import(MODULE_URL)
  assert.equal(parseApiInstant('not a date'), null)
  assert.equal(parseApiInstant(''), null)
  assert.equal(parseApiInstant(null), null)
  assert.equal(parseApiInstant(undefined), null)
})

// ---- browser-time-zone formatting ------------------------------------------

test('Asia/Kolkata: formatters use the browser time zone', () => {
  const r = inTz('Asia/Kolkata', `m => ({
    time: m.formatLocalTime('2026-11-25T03:30:00'),
    range: m.formatLocalTimeRange('2026-11-25T03:30:00', '2026-11-25T06:30:00'),
    key: m.localDateKey('2026-11-25T20:30:00'),
    mins: m.minutesSinceLocalMidnight('2026-11-25T03:30:00'),
  })`)
  assert.ok(r.time.includes('9:00'), r.time)
  assert.ok(/AM/i.test(r.time), r.time)
  assert.ok(r.range.includes('9:00') && r.range.includes('12:00'), r.range)
  assert.equal(r.key, '2026-11-26')
  assert.equal(r.mins, 540)
})

test('Asia/Kolkata: formatLocalDateTime shows the local time', () => {
  const s = inTz('Asia/Kolkata', `m => m.formatLocalDateTime('2026-11-25T03:30:00')`)
  assert.ok(s.includes('9:00'), s)
})

test('UTC: same inputs give UTC values', () => {
  const r = inTz('UTC', `m => ({
    time: m.formatLocalTime('2026-11-25T03:30:00'),
    key: m.localDateKey('2026-11-25T03:30:00'),
    mins: m.minutesSinceLocalMidnight('2026-11-25T03:30:00'),
  })`)
  assert.ok(r.time.includes('3:30'), r.time)
  assert.equal(r.key, '2026-11-25')
  assert.equal(r.mins, 210)
})

// ---- calendar components use local time ------------------------------------

const CALENDAR_FILES = [
  'components/calendar/CalendarModals.jsx',
  'components/calendar/CalendarGrid.jsx',
  'components/calendar/CalendarSidebar.jsx',
]

test('calendar components import from utils/localTime', () => {
  for (const f of CALENDAR_FILES) {
    assert.match(read(f), /from\s+['"]\.\.\/\.\.\/utils\/localTime(\.js)?['"]/, `${f} does not import localTime`)
  }
})

test('calendar components no longer print a UTC suffix', () => {
  for (const f of CALENDAR_FILES) {
    assert.ok(!read(f).includes(' UTC'), `${f} still contains " UTC"`)
  }
})

test('calendar components no longer slice scheduled_start with slice(11, 16)', () => {
  for (const f of CALENDAR_FILES) {
    assert.ok(!/slice\(\s*11\s*,\s*16\s*\)/.test(read(f)), `${f} still uses slice(11, 16)`)
  }
})

test('CalendarModals tells the user times are local', () => {
  assert.ok(read('components/calendar/CalendarModals.jsx').includes('Times shown in your local time'))
})
