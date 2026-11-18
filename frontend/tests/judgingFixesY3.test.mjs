import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import { APPLICATION_STATUS_LABELS, RESUME_INCOMPLETE_HINT } from '../src/utils/careerUiHelpers.js'

const read = rel => fs.readFileSync(new URL(`../src/${rel}`, import.meta.url), 'utf8')

// ---- N-017 plain wording ---------------------------------------------------

test('Internship Radar header badge no longer says "Live Intel"', () => {
  const src = read('components/InternshipRadar.jsx')
  assert.ok(!src.includes('Live Intel'))
  assert.ok(src.includes('Updated daily'))
})

test('Career tabs use plain names and descriptions', () => {
  const src = read('components/CareerCopilot.jsx')
  assert.ok(src.includes("label: 'My resume'"))
  assert.ok(src.includes('Your resume, tailored for each job'))
  assert.ok(src.includes('Where each application stands'))
  assert.ok(!src.includes("label: 'Resume Studio'"))
  assert.ok(!src.includes('Factual tailoring'))
  assert.ok(!src.includes('batch approvals'))
})

test('"Manual Handoff" label became "Apply on company site"', () => {
  assert.equal(APPLICATION_STATUS_LABELS.MANUAL_SUBMISSION_REQUIRED, 'Apply on company site')
  assert.ok(!Object.values(APPLICATION_STATUS_LABELS).includes('Manual Handoff'))
})

test('the incomplete-resume hint names My resume', () => {
  assert.match(RESUME_INCOMPLETE_HINT, /My resume/)
  assert.ok(!/Resume Studio/.test(RESUME_INCOMPLETE_HINT))
})

test('engineer wording "deterministic" is gone from the profile and workspace pop-ups', () => {
  for (const file of ['components/radar/RadarProfileModal.jsx', 'components/career/ApplicationWorkspaceModal.jsx']) {
    assert.ok(!/deterministic/i.test(read(file)), `${file} still says deterministic`)
  }
})

test('visible "Resume Studio" is gone from the radar screens', () => {
  for (const file of ['components/InternshipRadar.jsx', 'components/radar/RadarDetailModal.jsx']) {
    const visible = read(file)
      .split('\n')
      .filter(line => !line.trim().startsWith('//') && !line.includes('{/*'))
      .filter(line => !/ResumeStudio|resume_studio/i.test(line))
    assert.ok(!visible.some(line => line.includes('Resume Studio')), `${file} shows Resume Studio`)
  }
})

// ---- N-030 small text ------------------------------------------------------

test('Dashboard has no 9px or 10px font sizes', () => {
  const src = read('components/Dashboard.jsx')
  assert.ok(!/fontSize:\s*['"]?(9|10)(\.\d+)?(px)?['"]?\s*[,}]/.test(src))
})

test('Sidebar, Dashboard and the application pop-up have no body text under 12px except tiny count badges', () => {
  for (const file of ['components/Dashboard.jsx', 'components/Sidebar.jsx', 'components/career/ApplicationWorkspaceModal.jsx']) {
    const src = read(file)
    assert.ok(!/fontSize:\s*['"]11(\.5)?px['"]/.test(src), `${file} has 11px text`)
    assert.ok(!/fontSize:\s*['"]10\.5px['"]/.test(src), `${file} has 10.5px text`)
  }
})

test('index.css no longer sets 11px text', () => {
  assert.ok(!/font-size:\s*11px/.test(read('index.css')))
})

// ---- N-018 one tracker -----------------------------------------------------

test('radar detail pop-up has no second 10-option tracker', () => {
  const src = read('components/radar/RadarDetailModal.jsx')
  assert.ok(!src.includes('PIPELINE_STATUSES'))
  assert.ok(!src.includes('Application Pipeline Status'))
  assert.ok(!src.includes('Closed Without Applying'))
  assert.ok(!src.includes('<select'))
  assert.ok(!src.includes('onUpdateApp'))
})

test('radar detail pop-up points to the Application Center, wired through CareerCopilot', () => {
  const modal = read('components/radar/RadarDetailModal.jsx')
  assert.ok(modal.includes('Application Center'))
  assert.ok(modal.includes('onNavigateToApplications'))
  const radar = read('components/InternshipRadar.jsx')
  assert.ok(radar.includes('onNavigateToApplications={onNavigateToApplications}'))
  const career = read('components/CareerCopilot.jsx')
  assert.match(career, /handleNavigateToApplications = useCallback\(\(\) => \{\s*setActiveSubTab\('applications'\)/)
  assert.ok(career.includes('onNavigateToApplications={handleNavigateToApplications}'))
})

test('the sidebar section is called "My areas", not "Context Domains"', () => {
  const src = read('components/Sidebar.jsx')
  assert.ok(src.includes('My areas'))
  assert.ok(!src.includes('Context Domains'))
})
