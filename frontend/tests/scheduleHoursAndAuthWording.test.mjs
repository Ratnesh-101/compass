import { test } from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import { PLANNING_HOURS_TEXT } from '../src/components/calendar/planningHours.js'

const read = (rel) => fs.readFileSync(new URL(`../src/${rel}`, import.meta.url), 'utf8')

test('N-028: Schedule shows fixed planning hours as plain text, no fake "Edit hours" control', () => {
  const view = read('components/CalendarView.jsx')
  assert.equal(PLANNING_HOURS_TEXT, 'Planning hours: 9:00 to 18:00, Monday to Friday')
  assert.ok(view.includes("import { PLANNING_HOURS_TEXT } from './calendar/planningHours'"))
  assert.ok(view.includes('{PLANNING_HOURS_TEXT}'))
  for (const gone of ['Edit hours', 'compass_working_hours', 'isEditingHours', 'handleSaveWorkingHours', 'calendar-hours-start', 'Set Working Hours', 'workingHours']) {
    assert.ok(!view.includes(gone), `CalendarView still contains: ${gone}`)
  }
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
