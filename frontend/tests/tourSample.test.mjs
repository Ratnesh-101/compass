import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import {
  DEMO_VIDEO_URL,
  SAMPLE_TABLE_HEADERS,
  SAMPLE_TASKS,
  TOUR_FEASIBILITY_TEXT,
  TOUR_INTERNSHIPS_TEXT,
  TOUR_STEP_FEASIBILITY_LABEL,
  TOUR_STEP_INTERNSHIPS_LABEL,
  TOUR_STEP_LOAD_LABEL,
  buildSampleWeekMessage,
  formatIsoDate,
  isTourRequested,
} from '../src/utils/tourSample.js'

const read = (p) => fs.readFileSync(new URL(`../src/${p}`, import.meta.url), 'utf8').split('\r\n').join('\n')

// Rules copied from backend/services/task_intake_parse.py and task_intent.title_problem. Keep in sync.
const HEADER_FIELDS = {
  title: 'title', task: 'title', name: 'title', item: 'title',
  domain: 'domain', category: 'domain', project: 'domain',
  due: 'due', deadline: 'due', 'due date': 'due', when: 'due', date: 'due',
  priority: 'priority', prio: 'priority',
  duration: 'duration', estimate: 'duration', est: 'duration', effort: 'duration',
}
const VALID_DOMAINS = ['hackathon', 'coursework', 'code', 'general']
const PRIORITY_WORDS = ['urgent', 'critical', 'p0', 'asap', 'high', 'p1', 'important', 'medium', 'normal', 'p2', 'moderate', 'low', 'p3', 'minor']
const MAX_ITEMS = 20
const MIN_ITEMS = 2

function splitRow(line) {
  if (line.includes('|')) return line.trim().replace(/^\|/, '').replace(/\|$/, '').split('|').map((c) => c.trim())
  if (line.includes('\t')) return line.split('\t').map((c) => c.trim())
  return []
}
const isSeparator = (cells) => cells.every((c) => !c || /^:?-{2,}:?$/.test(c))

// Pinned example: 17 Nov 2026 (local) -> offsets 1..9 days give 18..26 Nov.
const PINNED_NOW = new Date(2026, 10, 17, 9, 30)
const PINNED_MESSAGE = [
  'Add these 8 tasks to my deadlines:',
  '| Task | Domain | Priority | Duration | Due |',
  '| --- | --- | --- | --- | --- |',
  '| Operating Systems assignment | coursework | high | 4h | 2026-11-19 |',
  '| Computer Networks lab report | coursework | medium | 3h | 2026-11-21 |',
  '| Database Systems midterm revision | coursework | high | 5h | 2026-11-23 |',
  '| Hackathon project proposal | hackathon | high | 3h | 2026-11-20 |',
  '| Hackathon demo video | hackathon | medium | 4h | 2026-11-24 |',
  '| Hackathon final submission | hackathon | urgent | 3h | 2026-11-26 |',
  '| Fix login bug in portfolio site | code | medium | 2h | 2026-11-18 |',
  '| Write unit tests for the API | code | low | 2h | 2026-11-22 |',
].join('\n')

test('sample week message has the exact pinned format (same literal as tests/test_tour_sample_intake.py)', () => {
  assert.equal(buildSampleWeekMessage(PINNED_NOW), PINNED_MESSAGE)
})

test('sample week: 8 tasks, 3 coursework + 3 hackathon + 2 code, 26 hours', () => {
  assert.equal(SAMPLE_TASKS.length, 8)
  const count = (d) => SAMPLE_TASKS.filter((t) => t.domain === d).length
  assert.deepEqual([count('coursework'), count('hackathon'), count('code')], [3, 3, 2])
  assert.equal(SAMPLE_TASKS.reduce((s, t) => s + t.hours, 0), 26)
})

test('every header and row satisfies the backend parser rules', () => {
  const lines = buildSampleWeekMessage(PINNED_NOW).split('\n').filter((l) => l.trim())
  const rows = lines.map((l) => ({ l, cells: splitRow(l) })).filter((r) => r.cells.length && !isSeparator(r.cells))
  // the intro line has no pipe or tab, so it is not a table row
  assert.ok(!rows.some((r) => r.l.startsWith('Add these')))
  const header = rows[0].cells
  const mapping = {}
  header.forEach((c, i) => { if (HEADER_FIELDS[c.toLowerCase()]) mapping[i] = HEADER_FIELDS[c.toLowerCase()] })
  const fields = Object.values(mapping)
  assert.ok(fields.includes('title') && new Set(fields).size >= 2, 'header needs a title column plus one more')
  assert.deepEqual(fields, ['title', 'domain', 'priority', 'duration', 'due'])
  assert.deepEqual(SAMPLE_TABLE_HEADERS.map((h) => HEADER_FIELDS[h.toLowerCase()]), fields)
  const data = rows.slice(1)
  assert.ok(data.length >= MIN_ITEMS && data.length <= MAX_ITEMS)
  assert.equal(data.length, 8)
  for (const { cells } of data) {
    assert.equal(cells.length, header.length)
    const [title, domain, priority, duration, due] = cells
    assert.ok(title && !title.includes('?'), `title ok: ${title}`)
    assert.ok(/[A-Za-z]/.test(title) && title.length <= 200)
    assert.ok(VALID_DOMAINS.includes(domain), `valid domain: ${domain}`)
    assert.ok(PRIORITY_WORDS.includes(priority), `known priority: ${priority}`)
    assert.match(duration, /^\d+(?:\.\d+)?\s*(?:h|hr|hrs|hour|hours)$/i)
    assert.match(due, /^20\d{2}-\d{2}-\d{2}$/)
  }
})

test('due dates are computed at click time as today + 1..9 days, never hard-coded', () => {
  const offsets = SAMPLE_TASKS.map((t) => t.daysAhead)
  assert.equal(Math.min(...offsets), 1)
  assert.equal(Math.max(...offsets), 9)
  const later = new Date(2027, 0, 20)
  const msg = buildSampleWeekMessage(later)
  assert.ok(msg.includes('2027-01-21') && msg.includes('2027-01-29'))
  assert.ok(!msg.includes('2026-11'))
  assert.equal(formatIsoDate(new Date(2027, 0, 5)), '2027-01-05')
  const src = read('utils/tourSample.js')
  assert.ok(!/['"`]20\d{2}-\d{2}-\d{2}/.test(src), 'no literal dates in source')
})

test('steps 2 and 3 send exactly their button text', () => {
  assert.equal(TOUR_FEASIBILITY_TEXT, 'Can I finish all of this in 2 hours a day?')
  assert.equal(TOUR_INTERNSHIPS_TEXT, 'Find internships for a 3rd-year B.Tech student in India')
  assert.equal(TOUR_STEP_LOAD_LABEL, '1. Load a sample week')
  assert.equal(TOUR_STEP_FEASIBILITY_LABEL, `2. ${TOUR_FEASIBILITY_TEXT}`)
  assert.equal(TOUR_STEP_INTERNSHIPS_LABEL, `3. ${TOUR_INTERNSHIPS_TEXT}`)
})

test('?tour=1 detection', () => {
  assert.equal(isTourRequested('?tour=1'), true)
  assert.equal(isTourRequested('?a=b&tour=1'), true)
  assert.equal(isTourRequested('?tour=0'), false)
  assert.equal(isTourRequested(''), false)
  assert.equal(isTourRequested(undefined), false)
})

test('TourCard is on the Dashboard welcome card with the approved copy', () => {
  const card = read('components/TourCard.jsx')
  const util = read('utils/tourSample.js')
  assert.ok(util.includes('New here? Take the 60-second tour'))
  assert.ok(util.includes('Three clicks. Everything stays in your private guest workspace.'))
  assert.ok(card.includes('buildSampleWeekMessage(new Date())'))
  assert.ok(read('components/Dashboard.jsx').includes('<TourCard onRun='))
  assert.ok(read('components/TourStrip.jsx').includes('<TourButtons'))
  const app = read('App.jsx')
  assert.ok(app.includes('<TourStrip') && app.includes('isTourRequested(window.location.search)'))
})

test('welcome copy, sponsor line and wake screen wording (Decisions 6 and 9)', () => {
  const dash = read('components/Dashboard.jsx')
  for (const s of [
    'Compass keeps your deadlines, coursework and internship hunt in one place, and asks before it changes anything.',
    'You are in a private guest workspace. No signup. Nothing you add is shared.',
    'Runs on NVIDIA Nemotron models through Nebius Token Factory, with Tavily web search.',
    'How it works',
    'Starting the server. This takes about 30 seconds and only happens after a quiet period.',
    'watch the 3-minute demo',
  ]) assert.ok(dash.includes(s), s)
  assert.equal(DEMO_VIDEO_URL, 'https://youtu.be/TSO7xV_5ZHw')
  assert.ok(fs.readFileSync(new URL('../../README.md', import.meta.url), 'utf8').includes(DEMO_VIDEO_URL))
})

test('T-029 is gone from App.jsx: eager screens, no polling pause flag', () => {
  const app = read('App.jsx')
  assert.ok(!app.includes('__compass_chat_streaming'))
  assert.ok(!app.includes('isChatStreamingRef'))
  assert.ok(!app.includes('isTypingRef'))
  assert.ok(!/React\.lazy\(\(\) => import\('\.\/components\/(Timeline|CalendarView|CompassPanel)'\)\)/.test(app))
  for (const name of ['Timeline', 'CalendarView', 'CompassPanel']) {
    assert.ok(app.includes(`import ${name} from './components/${name}'`), name)
  }
})
