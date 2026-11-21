import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { blockedMessage } from '../src/utils/applicationStages.js'

const read = rel => readFileSync(new URL(rel, import.meta.url), 'utf8')

test('blockedMessage turns the real backend sentences into plain field names', () => {
  const backend = [
    'Candidate Full Name is required.',
    'Valid contact email address is required.',
    'Education section cannot be empty.',
  ]
  const msg = blockedMessage({
    status: 'RESUME_VALIDATION_FAILED',
    missing_fields: backend,
    resume: { validation_report: { missing_fields: backend } },
  })
  assert.doesNotMatch(msg, /is required|cannot be empty/i)
  assert.equal(
    msg,
    'To move this forward, add your full name, your email address and your education in My resume. Then open the application again.',
  )
  for (const word of ['your full name', 'your email address', 'your education']) {
    assert.equal(msg.split(word).length - 1, 1, `${word} listed once`)
  }
})

test('blockedMessage strips a trailing period from unknown backend text', () => {
  const msg = blockedMessage({ status: 'NEEDS_INFORMATION', missing_fields: ['Work authorization unknown.'] })
  assert.match(msg, /add work authorization unknown in My resume/)
})

test('CareerStartPanel forwards the save target to commitExtractedResume', () => {
  const src = read('../src/components/career/CareerStartPanel.jsx')
  assert.match(src, /onCommit=\{\(content, docId, target\) => commit\(content, docId, target/)
  assert.match(src, /commitExtractedResume\(content, [^\n]*, target\)/)
  assert.doesNotMatch(src, /commitExtractedResume\([^\n]*'master'\)/)
})

test('JobLinkInput accepts links without a scheme', () => {
  const src = read('../src/components/career/JobLinkInput.jsx')
  assert.match(src, /inputMode="url"/)
  assert.doesNotMatch(src, /type="url"/)
})
