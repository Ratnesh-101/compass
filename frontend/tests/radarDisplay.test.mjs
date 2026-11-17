import test from 'node:test'
import assert from 'node:assert/strict'
import {
  descriptionBlocks,
  friendlySourceAuthority,
  friendlySourceType,
  isStubDescription,
  lastCheckedLabel,
  parseInline,
  safeVerificationBasis,
} from '../src/components/radar/radarDisplay.js'

const NOW = new Date('2026-11-17T10:00:00Z').getTime()
const daysAgo = n => new Date(NOW - n * 24 * 60 * 60 * 1000).toISOString()

test('lastCheckedLabel uses plain wording', () => {
  assert.equal(lastCheckedLabel(daysAgo(3), { now: NOW }), 'Last checked 3 days ago')
  assert.equal(lastCheckedLabel(daysAgo(1), { now: NOW }), 'Last checked 1 day ago')
  assert.equal(lastCheckedLabel(daysAgo(0), { now: NOW }), 'Last checked today')
  assert.equal(lastCheckedLabel(null, { now: NOW }), 'Not checked yet')
  assert.equal(lastCheckedLabel(daysAgo(3), { checkFailed: true, now: NOW }), 'Could not re-check today')
})

test('safeVerificationBasis hides internal labels and raw errors', () => {
  assert.equal(safeVerificationBasis('HTTP 200 via tavily_extract'), null)
  assert.equal(safeVerificationBasis('Discovered via JobSpy (Glassdoor). Precision: DATE_ONLY'), null)
  assert.equal(safeVerificationBasis('Verification connection timed out or failed: SNI bytes. Retaining current status.'), null)
  assert.equal(safeVerificationBasis('Source authority tier_1'), null)
  assert.equal(safeVerificationBasis('Checked on the employer careers page.'), 'Checked on the employer careers page.')
  assert.equal(safeVerificationBasis(''), null)
})

test('source labels are friendly and internal ids are never returned', () => {
  assert.equal(friendlySourceType('jobspy_glassdoor'), 'Glassdoor')
  assert.equal(friendlySourceType('ats_greenhouse_api'), 'Employer careers page (Greenhouse)')
  assert.equal(friendlySourceType('something_odd'), null)
  assert.equal(friendlySourceAuthority('tier_1'), 'Employer source')
  assert.equal(friendlySourceAuthority('tier_9'), null)
})

test('descriptionBlocks removes markdown symbols, rules and empty headings', () => {
  const md = [
    '## About the role',
    'You will **build** models.',
    '----',
    '## Benefits',
    '## Requirements',
    '- Python',
    '- SQL',
    '**Nice to have**',
  ].join('\n')
  const blocks = descriptionBlocks(md)
  const text = JSON.stringify(blocks)
  assert.ok(!text.includes('**'))
  assert.ok(!text.includes('----'))
  assert.ok(!text.includes('##'))
  const headings = blocks.filter(b => b.type === 'heading').map(b => b.segments[0].text)
  assert.deepEqual(headings, ['About the role', 'Requirements'])
  assert.equal(blocks.filter(b => b.type === 'bullet').length, 2)
})

test('parseInline marks bold and strips stray symbols', () => {
  assert.deepEqual(parseInline('a **b** c'), [
    { text: 'a ', bold: false },
    { text: 'b', bold: true },
    { text: ' c', bold: false },
  ])
})

test('isStubDescription flags generated placeholder text', () => {
  assert.equal(isStubDescription('Data Intern at Acme. Discovered on Glassdoor.'), true)
  assert.equal(isStubDescription(''), true)
  assert.equal(isStubDescription('x'.repeat(500)), false)
})
