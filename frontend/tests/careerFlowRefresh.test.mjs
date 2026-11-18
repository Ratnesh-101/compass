import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import { createRefreshGate } from '../src/utils/radarRefresh.js'
import {
  summarizeTopMatchesResult,
  summarizeResumeImport,
  missingContactDetails,
  readWhatChanged,
  jobLinkErrorMessage,
  looksLikeJobLink,
} from '../src/utils/careerFlowText.js'

test('refresh gate runs once per profile save, not once per re-render', () => {
  const gate = createRefreshGate(0)
  let calls = 0
  // 50 re-renders with the same counter value (callbacks changing identity must not matter)
  for (let i = 0; i < 50; i += 1) if (gate.check(0)) calls += 1
  assert.equal(calls, 0)
  // one save
  for (let i = 0; i < 50; i += 1) if (gate.check(1)) calls += 1
  assert.equal(calls, 1)
  // a second save
  for (let i = 0; i < 10; i += 1) if (gate.check(2)) calls += 1
  assert.equal(calls, 2)
})

test('a gate created after a save does not refresh on mount', () => {
  const gate = createRefreshGate(3)
  assert.equal(gate.check(3), false)
  assert.equal(gate.check(4), true)
})

test('radar refresh effect does not depend on the parent callbacks', () => {
  const src = fs.readFileSync(new URL('../src/components/InternshipRadar.jsx', import.meta.url), 'utf8')
  assert.match(src, /\}, \[loadMetadata, loadOpportunities\]\)/)
  assert.doesNotMatch(src, /\[loadMetadata, loadOpportunities, onRefreshComplete, onRefreshError\]/)
  assert.match(src, /refreshGate\.check\(refreshTrigger\)/)
  const copilot = fs.readFileSync(new URL('../src/components/CareerCopilot.jsx', import.meta.url), 'utf8')
  assert.match(copilot, /const handleRefreshComplete = useCallback/)
  assert.match(copilot, /const handleRefreshError = useCallback/)
})

test('top matches result is summarised in plain words', () => {
  const ok = summarizeTopMatchesResult({
    status: 'completed',
    drafts: [{ status: 'prepared', role_title: 'ML Intern', company_name: 'Acme', opportunity_id: 1 }, { status: 'failed', message: 'x', opportunity_id: 2 }],
  })
  assert.equal(ok.preparedCount, 1)
  assert.equal(ok.message, '1 application is ready to review.')
  assert.equal(ok.lines[0], 'ML Intern at Acme: ready to review')
  assert.equal(summarizeTopMatchesResult({ status: 'incomplete_profile', message: 'Upload your resume first.' }).needsResume, true)
  assert.equal(summarizeTopMatchesResult({ status: 'completed', drafts: [] }).tone, 'info')
})

test('resume import summary shows only what was read', () => {
  const lines = summarizeResumeImport({
    full_name: 'Priya Sharma',
    email: 'p@x.com',
    education: [{ institution: 'Pune Institute of Technology', degree: 'B.Tech', field_of_study: 'CS', start_year: 2024, end_year: 2028, cgpa_or_grade: '8.4/10' }],
    skills: ['Python'],
    projects: [],
  })
  assert.deepEqual(lines, ['Priya Sharma · p@x.com', 'B.Tech in CS, Pune Institute of Technology (2024-2028)', 'CGPA / grade: 8.4/10', '1 skills: Python'])
  assert.deepEqual(summarizeResumeImport(null), [])
  assert.deepEqual(missingContactDetails({ full_name: '', email: 'a' }), ['your name', 'your email'])
})

test('what-changed block is read from the tailored resume', () => {
  assert.equal(readWhatChanged({}), null)
  const w = readWhatChanged({ validation_report: { diff_summary: { what_changed: { changed: false, reason_if_unchanged: 'This posting lists no skills we could match.', preview: {} } } } })
  assert.equal(w.changed, false)
  assert.equal(w.reason, 'This posting lists no skills we could match.')
})

test('job link helpers', () => {
  assert.equal(looksLikeJobLink('https://acme.com/jobs/1'), true)
  assert.equal(looksLikeJobLink('acme.com/jobs/1'), true)
  assert.equal(looksLikeJobLink('hello world'), false)
  assert.equal(looksLikeJobLink(''), false)
  assert.match(jobLinkErrorMessage(new Error('HTTP 500')), /couldn't read that link/)
  assert.equal(jobLinkErrorMessage(new Error("We couldn't read that page.")), "We couldn't read that page.")
})
