import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import { planStageMove } from '../src/utils/applicationStages.js'
import { hasSavedResume, hasSavedProfile } from '../src/utils/careerUiHelpers.js'

const read = p => fs.readFileSync(new URL(p, import.meta.url), 'utf8')

// ---- Task 1: top matches button ------------------------------------------------------------

test('hasSavedResume is true only when the master resume has real content', () => {
  assert.equal(hasSavedResume(null), false)
  assert.equal(hasSavedResume({ content: {} }), false)
  assert.equal(hasSavedResume({ content: { full_name: 'A', skills: [], education: [] } }), false)
  assert.equal(hasSavedResume({ content: { skills: ['Python'] } }), true)
  assert.equal(hasSavedResume({ content: { projects: [{ name: 'x' }] } }), true)
})

test('a saved resume without degree or graduation year still enables the button', () => {
  assert.equal(hasSavedProfile({}), false)
  assert.equal(hasSavedResume({ content: { skills: ['Python'] } }), true)
  const radar = read('../src/components/InternshipRadar.jsx')
  assert.match(radar, /hasProfile=\{hasCandidateProfile \|\| hasResume\}/)
  assert.match(radar, /hasResume = false/)
})

test('CareerCopilot reads the master resume inside the existing profile effect and passes hasResume down', () => {
  const src = read('../src/components/CareerCopilot.jsx')
  assert.match(src, /fetchMasterResume\(\)/)
  assert.match(src, /setHasResume\(hasSavedResume\(master\)\)/)
  assert.match(src, /hasResume=\{hasResume\}/)
  // the effect still depends only on the refresh counter (no new function dependency)
  assert.match(src, /\}, \[profileRefreshTrigger\]\)/)
})

test('the top matches bar shows the backend message, not a raw error', () => {
  const src = read('../src/components/career/TopMatchesBar.jsx')
  assert.match(src, /err\?\.message \|\| 'Could not prepare your top matches/)
  assert.match(src, /disabled=\{busy \|\| !hasProfile\}/)
})

// ---- Task 2: closing an application --------------------------------------------------------

const DIRECT_CLOSE = ['OFFER_RECEIVED', 'REJECTED', 'WITHDRAWN']
const TWO_STEP_CLOSE = [
  'SAVED', 'PREPARING', 'RESUME_VALIDATION_FAILED', 'READY_FOR_REVIEW', 'READY_FOR_APPROVAL',
  'APPROVED_FOR_SUBMISSION', 'SUBMITTING', 'SUBMISSION_OUTCOME_UNKNOWN', 'SUBMISSION_FAILED',
  'HANDOFF_KIT_READY', 'MANUAL_SUBMISSION_REQUIRED', 'SUBMITTED', 'ASSESSMENT_RECEIVED', 'INTERVIEW',
]

test('Closed is one step only where the backend allows CLOSED directly', () => {
  for (const status of DIRECT_CLOSE) {
    if (status === 'REJECTED' || status === 'WITHDRAWN' || status === 'OFFER_RECEIVED') {
      const plan = planStageMove(status, 'closed')
      // REJECTED and WITHDRAWN are already in the Closed stage, so nothing to do
      if (status === 'OFFER_RECEIVED') assert.deepEqual(plan.steps, [{ type: 'status', status: 'CLOSED' }])
      else assert.deepEqual(plan.steps, [])
    }
  }
})

test('every other status closes in two steps, withdrawn first (the backend has no direct CLOSED for them)', () => {
  for (const status of TWO_STEP_CLOSE) {
    const plan = planStageMove(status, 'closed')
    assert.equal(plan.ok, true, status)
    assert.deepEqual(plan.steps, [
      { type: 'status', status: 'WITHDRAWN' },
      { type: 'status', status: 'CLOSED' },
    ], status)
  }
})

test('callers report a half-finished close in plain words and keep the stored status', () => {
  const msg = 'The application was withdrawn but could not be closed. Try closing it again.'
  const center = read('../src/components/career/ApplicationCenter.jsx')
  const modal = read('../src/components/career/ApplicationWorkspaceModal.jsx')
  assert.ok(center.includes(msg))
  assert.ok(modal.includes(msg))
  // the list is updated from the last successful server reply even when a later step fails
  assert.match(center, /showLatest\(\)\s*\n\s*setError/)
})

// ---- Task 3: phone table -------------------------------------------------------------------

test('the Application Center table stacks on phones and its wrapper scrolls sideways', () => {
  const css = read('../src/index.css')
  const jsx = read('../src/components/career/ApplicationCenter.jsx')
  assert.match(jsx, /<table className="application-center-table"/)
  assert.match(jsx, /overflowX: 'auto'/)
  assert.match(css, /@media \(max-width: 640px\)[\s\S]*\.application-center-table/)
})
