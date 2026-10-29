import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { zonedDateKey, zonedMinutes, workingWindowLabel, getUserTimeZone } from '../src/utils/userTimezone.js'

test('zonedDateKey rolls over the date for Asia/Kolkata', () => {
  assert.equal(zonedDateKey('2026-09-21T20:00:00+00:00', 'Asia/Kolkata'), '2026-09-22')
  assert.equal(zonedDateKey('2026-09-21T20:00:00+00:00', 'UTC'), '2026-09-21')
})

test('zonedMinutes honours half-hour zones and DST', () => {
  assert.equal(zonedMinutes('2026-09-21T03:30:00+00:00', 'Asia/Kolkata'), 9 * 60)
  assert.equal(zonedMinutes('2026-10-30T13:00:00+00:00', 'America/New_York'), 9 * 60)
  assert.equal(zonedMinutes('2026-11-02T14:00:00+00:00', 'America/New_York'), 9 * 60)
  assert.equal(zonedMinutes('2027-01-03T20:00:00+00:00', 'Pacific/Auckland'), 9 * 60)
})

test('label shows the actual zone and defaults to UTC', () => {
  assert.equal(workingWindowLabel('Asia/Kolkata'), '09:00 - 18:00 Asia/Kolkata')
  assert.equal(workingWindowLabel(), '09:00 - 18:00 UTC')
  assert.ok(getUserTimeZone().length > 0)
})

test('calendar requests send tz and the UI no longer hardcodes UTC', () => {
  const api = readFileSync(new URL('../src/api/calendarApi.js', import.meta.url), 'utf8')
  const view = readFileSync(new URL('../src/components/CalendarView.jsx', import.meta.url), 'utf8')
  const tasks = readFileSync(new URL('../src/api/tasksApi.js', import.meta.url), 'utf8')
  assert.match(api, /params\.append\('tz'/)
  assert.match(api, /schedule\/propose\?\$\{/)
  assert.match(api, /reactive-check\?\$\{/)
  assert.match(tasks, /params\.set\('tz'/)
  assert.ok(!view.includes('18:00 UTC'))
  assert.ok(!view.includes('getUTCHours'))
})
