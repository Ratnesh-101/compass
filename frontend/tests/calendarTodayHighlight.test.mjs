import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'

const read = rel => fs.readFileSync(new URL(`../src/${rel}`, import.meta.url), 'utf8')

const SIDEBAR = 'components/calendar/CalendarSidebar.jsx'
const GRID = 'components/calendar/CalendarGrid.jsx'

test('mini calendar marks today with aria-current="date"', () => {
  const src = read(SIDEBAR)
  assert.match(src, /aria-current/)
  assert.match(src, /aria-current=\{[^}]*isToday[^}]*['"]date['"][^}]*\}/)
})

test('mini calendar day buttons announce "today" in aria-label', () => {
  const src = read(SIDEBAR)
  assert.ok(src.includes('aria-label={ariaLabel}'), 'aria-label={ariaLabel} missing')
  assert.ok(src.includes(', today'), "', today' text missing")
})

test('mini calendar uses isToday for accent border and soft card background', () => {
  const src = read(SIDEBAR)
  assert.match(src, /isToday[^\n]*var\(--accent\)/)
  assert.match(src, /isToday[^\n]*var\(--bg-card-soft\)/)
  assert.match(src, /1px solid var\(--accent\)/)
})

test('mini calendar keeps var(--accent-text) for the selected state', () => {
  const src = read(SIDEBAR)
  assert.match(src, /isSelected \? 'var\(--accent-text\)'/)
})

test('mini calendar has a box-shadow ring for selected-and-today', () => {
  const src = read(SIDEBAR)
  assert.match(src, /boxShadow/)
  assert.match(src, /isSelected && isToday/)
})

test('week view still highlights today with accent border (views stay aligned)', () => {
  const src = read(GRID)
  assert.match(src, /isCurrToday/)
  assert.match(src, /isCurrToday \? '1px solid var\(--accent\)'/)
  assert.match(src, /isCurrToday \? 'var\(--bg-card-soft\)'/)
})
