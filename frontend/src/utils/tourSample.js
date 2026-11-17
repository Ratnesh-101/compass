// Content and helpers for the "60-second tour" (Decision 1). No backend call and no seeding endpoint:
// step 1 is an ordinary chat message holding a pasted table, so the user still confirms before anything is saved.

export const DEMO_VIDEO_URL = 'https://youtu.be/TSO7xV_5ZHw'

export const TOUR_HEADING = 'New here? Take the 60-second tour'
export const TOUR_SUBLINE = 'Three clicks. Everything stays in your private guest workspace.'

export const TOUR_STEP_LOAD_LABEL = '1. Load a sample week'
export const TOUR_STEP_FEASIBILITY_LABEL = '2. Can I finish all of this in 2 hours a day?'
export const TOUR_STEP_INTERNSHIPS_LABEL = '3. Find internships for a 3rd-year B.Tech student in India'

// Steps 2 and 3 send exactly their button text.
export const TOUR_FEASIBILITY_TEXT = 'Can I finish all of this in 2 hours a day?'
export const TOUR_INTERNSHIPS_TEXT = 'Find internships for a 3rd-year B.Tech student in India'

// Column names the backend's deterministic table parser maps to fields
// (backend/services/task_intake_parse.py `_HEADER_FIELDS`): task->title, domain, priority, duration, due.
export const SAMPLE_TABLE_HEADERS = ['Task', 'Domain', 'Priority', 'Duration', 'Due']

// 3 coursework + 3 hackathon + 2 code = 26 hours. `daysAhead` is added to today at click time.
export const SAMPLE_TASKS = [
  { title: 'Operating Systems assignment', domain: 'coursework', priority: 'high', hours: 4, daysAhead: 2 },
  { title: 'Computer Networks lab report', domain: 'coursework', priority: 'medium', hours: 3, daysAhead: 4 },
  { title: 'Database Systems midterm revision', domain: 'coursework', priority: 'high', hours: 5, daysAhead: 6 },
  { title: 'Hackathon project proposal', domain: 'hackathon', priority: 'high', hours: 3, daysAhead: 3 },
  { title: 'Hackathon demo video', domain: 'hackathon', priority: 'medium', hours: 4, daysAhead: 7 },
  { title: 'Hackathon final submission', domain: 'hackathon', priority: 'urgent', hours: 3, daysAhead: 9 },
  { title: 'Fix login bug in portfolio site', domain: 'code', priority: 'medium', hours: 2, daysAhead: 1 },
  { title: 'Write unit tests for the API', domain: 'code', priority: 'low', hours: 2, daysAhead: 5 },
]

// Local calendar date as YYYY-MM-DD (never toISOString: that is UTC and can be the wrong day).
export function formatIsoDate(date) {
  const y = date.getFullYear()
  const m = String(date.getMonth() + 1).padStart(2, '0')
  const d = String(date.getDate()).padStart(2, '0')
  return `${y}-${m}-${d}`
}

export function addDays(date, days) {
  const next = new Date(date.getFullYear(), date.getMonth(), date.getDate())
  next.setDate(next.getDate() + days)
  return next
}

// One chat message: an intro line (no pipe or tab, so the parser ignores it) then a markdown table.
export function buildSampleWeekMessage(now = new Date()) {
  const row = (cells) => `| ${cells.join(' | ')} |`
  const lines = [
    'Add these 8 tasks to my deadlines:',
    row(SAMPLE_TABLE_HEADERS),
    row(SAMPLE_TABLE_HEADERS.map(() => '---')),
    ...SAMPLE_TASKS.map((t) => row([t.title, t.domain, t.priority, `${t.hours}h`, formatIsoDate(addDays(now, t.daysAhead))])),
  ]
  return lines.join('\n')
}

export function isTourRequested(search) {
  try {
    return new URLSearchParams(search || '').get('tour') === '1'
  } catch {
    return false
  }
}
