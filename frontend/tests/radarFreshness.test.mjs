import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import {
  FRESH_DAYS,
  formatVerifiedAge,
  formatOpportunityVerifiedAge,
  needsRecheck,
  anyConfirmedDeadline,
  shouldShowNoDeadlineNote,
} from '../src/utils/radarFreshness.js'

const read = (rel) =>
  fs.readFileSync(new URL(rel, import.meta.url), 'utf8').replace(/\r\n/g, '\n')

test('FRESH_DAYS is 14', () => {
  assert.equal(FRESH_DAYS, 14)
})

test('formatVerifiedAge for recent checks', () => {
  assert.equal(formatVerifiedAge(0), 'Last verified today')
  assert.equal(formatVerifiedAge(1), 'Last verified 1 day ago')
  assert.equal(formatVerifiedAge(5), 'Last verified 5 days ago')
  assert.equal(formatVerifiedAge(14), 'Last verified 14 days ago')
})

test('formatVerifiedAge uses absolute date when older than 14 days', () => {
  const out = formatVerifiedAge(20, '2026-10-20T10:00:00Z')
  assert.match(out, /^Last verified /)
  assert.match(out, /2026/)
  assert.ok(!out.includes('days ago'))
})

test('formatVerifiedAge says not verified recently when age unknown or no date', () => {
  assert.equal(formatVerifiedAge(null), 'Not verified recently')
  assert.equal(formatVerifiedAge(undefined), 'Not verified recently')
  assert.equal(formatVerifiedAge(NaN), 'Not verified recently')
  assert.equal(formatVerifiedAge(-3), 'Not verified recently')
  assert.equal(formatVerifiedAge(30), 'Not verified recently')
  assert.equal(formatVerifiedAge(30, 'not-a-date'), 'Not verified recently')
})

test('formatOpportunityVerifiedAge reads the contract fields', () => {
  assert.equal(
    formatOpportunityVerifiedAge({ verification_age_days: 3 }),
    'Last verified 3 days ago',
  )
  assert.equal(formatOpportunityVerifiedAge({}), 'Not verified recently')
  assert.equal(formatOpportunityVerifiedAge(null), 'Not verified recently')
})

test('needsRecheck only true when backend says so', () => {
  assert.equal(needsRecheck({ needs_recheck: true }), true)
  assert.equal(needsRecheck({ needs_recheck: false }), false)
  assert.equal(needsRecheck({}), false)
  assert.equal(needsRecheck(null), false)
})

test('no-deadline note only for a loaded list without any confirmed close date', () => {
  assert.equal(anyConfirmedDeadline([{ confirmed_close_date: '2026-12-01' }]), true)
  assert.equal(anyConfirmedDeadline([{ confirmed_close_date: null }, {}]), false)
  assert.equal(shouldShowNoDeadlineNote(null), false)
  assert.equal(shouldShowNoDeadlineNote([]), false)
  assert.equal(shouldShowNoDeadlineNote([{ id: 1 }, { id: 2, confirmed_close_date: null }]), true)
  assert.equal(shouldShowNoDeadlineNote([{ id: 1 }, { id: 2, confirmed_close_date: '2026-12-01' }]), false)
})

test('overview cards carry the student wording', () => {
  const src = read('../src/components/radar/RadarOverviewCards.jsx')
  assert.ok(src.includes('Verified open'))
  assert.ok(src.includes('Checked in the last 14 days'))
  assert.ok(src.includes('stats?.verified_open_count'))
  assert.ok(src.includes('stale_open_count'))
  assert.ok(src.includes('listed as open, need re-check'))
  assert.ok(src.includes('Last checked more than 14 days ago. Confirm on the company site before applying.'))
  assert.ok(src.includes('No listing has a confirmed deadline. Apply early.'))
  assert.ok(src.includes('shouldShowNoDeadlineNote'))
})

test('opportunity card and detail modal show age and re-check chip', () => {
  const card = read('../src/components/radar/RadarOpportunityCard.jsx')
  const modal = read('../src/components/radar/RadarDetailModal.jsx')
  for (const src of [card, modal]) {
    assert.ok(src.includes('formatOpportunityVerifiedAge'))
    assert.ok(src.includes('needsRecheck'))
    assert.ok(src.includes('Needs re-check'))
  }
})

test('radar page passes loaded opportunities to the overview cards', () => {
  const src = read('../src/components/InternshipRadar.jsx')
  assert.match(src, /opportunities=\{loading \? null : opportunities\}/)
})
