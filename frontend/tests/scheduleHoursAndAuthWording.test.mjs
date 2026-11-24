import { test } from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import {
  PLANNING_HOURS_TEXT,
  formatPlanningHours,
  formatBreak,
} from '../src/components/calendar/planningHours.js'

const read = (rel) => fs.readFileSync(new URL(`../src/${rel}`, import.meta.url), 'utf8')

test('Schedule uses real SchedulePreferencesCard reaching backend preferences API', () => {
  const view = read('components/CalendarView.jsx')
  const card = read('components/calendar/SchedulePreferencesCard.jsx')
  const api = read('api/calendarApi.js')

  // Planning hours text and formatting helpers
  assert.equal(PLANNING_HOURS_TEXT, 'Planning hours: 9:00 to 18:00, Monday to Friday')
  assert.equal(formatPlanningHours(), 'Planning hours: 9:00 to 18:00, Monday to Friday')
  assert.equal(
    formatPlanningHours({ work_start_time: '09:00:00', work_end_time: '18:00:00', work_days: [1, 2, 3, 4, 5] }),
    'Planning hours: 9:00 to 18:00, Monday to Friday'
  )
  assert.equal(
    formatPlanningHours({ work_start_time: '09:00:00', work_end_time: '18:00:00', work_days: [1, 2, 3, 4, 5, 6, 7] }),
    'Planning hours: 9:00 to 18:00, every day'
  )
  assert.equal(
    formatPlanningHours({ work_start_time: '09:00:00', work_end_time: '18:00:00', work_days: [1, 3, 5] }),
    'Planning hours: 9:00 to 18:00, Monday, Wednesday and Friday'
  )
  assert.equal(
    formatPlanningHours({ work_start_time: '09:00:00', work_end_time: '18:00:00', work_days: [6, 7] }),
    'Planning hours: 9:00 to 18:00, Saturday and Sunday'
  )

  assert.equal(formatBreak(15), 'Break between tasks: 15 minutes')
  assert.equal(formatBreak(0), 'Break between tasks: no break')
  assert.equal(formatBreak(60), 'Break between tasks: 1 hour')

  // CalendarView mounts SchedulePreferencesCard and formats hours dynamically
  assert.ok(view.includes('SchedulePreferencesCard'))
  assert.ok(view.includes('formatPlanningHours'))

  // Assert old fake-control strings are absent from both CalendarView and SchedulePreferencesCard
  const oldFakeStrings = [
    'Edit hours',
    'compass_working_hours',
    'isEditingHours',
    'handleSaveWorkingHours',
    'calendar-hours-start',
    'Set Working Hours',
    'workingHours',
  ]
  for (const gone of oldFakeStrings) {
    assert.ok(!view.includes(gone), `CalendarView still contains: ${gone}`)
    assert.ok(!card.includes(gone), `SchedulePreferencesCard contains: ${gone}`)
  }

  // Assert any localStorage use for hours is absent
  assert.ok(!card.includes('localStorage'), 'SchedulePreferencesCard must not use localStorage for hours')
  assert.ok(!view.includes('localStorage'), 'CalendarView must not use localStorage for hours')

  // Assert SchedulePreferencesCard calls updateSchedulingPreferences
  assert.ok(card.includes('updateSchedulingPreferences'), 'SchedulePreferencesCard must call updateSchedulingPreferences')

  // Assert calendarApi.js PUTs to /api/calendar/preferences
  assert.ok(api.includes('updateSchedulingPreferences'), 'calendarApi must export updateSchedulingPreferences')
  assert.ok(api.includes('/api/calendar/preferences'), 'calendarApi must use /api/calendar/preferences')
  assert.match(api, /method:\s*['"]PUT['"]/, 'calendarApi must perform a PUT request to /api/calendar/preferences')
})

test('AuthModal uses plain wording instead of OAuth and memory isolation jargon', () => {
  const modal = read('components/AuthModal.jsx')
  assert.ok(modal.includes('<span>Sign in with Google</span>'))
  assert.ok(!modal.includes('Sign in with Google OAuth'))
  assert.ok(!modal.includes('memory isolation'))
  assert.ok(!modal.includes('Isolated Memory Active'))
  assert.ok(!modal.includes('isolated memory'))
  assert.ok(!modal.includes('Connect with Google OAuth'))
  assert.ok(!modal.includes('Zero OAuth setup'))
  assert.ok(modal.includes('Private to your account'))
})
