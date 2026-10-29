import test from 'node:test'
import assert from 'node:assert/strict'
import {
  cleanOpportunity,
  daysSinceVerified,
  getEligibilityBadge,
  getVerificationBadge,
  isStaleVerification,
  lastCheckedText,
  parseVerificationDate,
} from '../src/utils/jobCardCleaner.js'

const NOW = new Date('2026-10-29T03:00:00Z')

test('POTENTIAL_MATCH is labelled Possible match, never Eligible', () => {
  assert.equal(getEligibilityBadge('POTENTIAL_MATCH').label, 'Possible match')
  assert.equal(getEligibilityBadge('POTENTIALLY_ELIGIBLE').label, 'Possible match')
  assert.match(getEligibilityBadge('POTENTIAL_MATCH').text, /brand-dark/)
})

test('only ELIGIBLE says Eligible; unknown classifications are unconfirmed', () => {
  assert.equal(getEligibilityBadge('ELIGIBLE').label, 'Eligible')
  assert.equal(getEligibilityBadge('INSUFFICIENT_INFORMATION').label, 'Eligibility unconfirmed')
  assert.equal(getEligibilityBadge(undefined).label, 'Eligibility unconfirmed')
  assert.equal(getEligibilityBadge('INELIGIBLE').label, 'Not eligible')
})

test('cleanOpportunity uses the shared eligibility badge', () => {
  const c = cleanOpportunity({ eligibility_classification: 'POTENTIAL_MATCH', current_status: 'OPEN_CONFIRMED' }, NOW)
  assert.equal(c.eligibilityBadge.label, 'Possible match')
})

test('date-only values parse as UTC dates', () => {
  const d = parseVerificationDate('2026-10-28')
  assert.equal(d.toISOString(), '2026-10-28T00:00:00.000Z')
  assert.equal(parseVerificationDate('garbage'), null)
  assert.equal(parseVerificationDate(null), null)
})

test('day counting is UTC calendar based', () => {
  assert.equal(daysSinceVerified('2026-10-29', NOW), 0)
  assert.equal(daysSinceVerified('2026-10-28', NOW), 1)
  assert.equal(daysSinceVerified('2026-10-25', NOW), 4)
  assert.equal(daysSinceVerified('2026-10-28T23:59:00Z', NOW), 1)
  assert.equal(daysSinceVerified('2027-01-01', NOW), 0)
  assert.equal(daysSinceVerified('', NOW), null)
})

test('lastCheckedText wording', () => {
  assert.equal(lastCheckedText('2026-10-29', NOW), 'Last checked today')
  assert.equal(lastCheckedText('2026-10-28', NOW), 'Last checked 1 day ago')
  assert.equal(lastCheckedText('2026-10-24', NOW), 'Last checked 5 days ago')
  assert.equal(lastCheckedText(null, NOW), null)
})

test('stale after more than 3 days', () => {
  assert.equal(isStaleVerification('2026-10-26', NOW), false) // 3 days
  assert.equal(isStaleVerification('2026-10-25', NOW), true) // 4 days
  assert.equal(isStaleVerification(null, NOW), false)
})

test('stale open listing gets amber re-verify badge, fresh gets green', () => {
  const stale = getVerificationBadge('OPEN_CONFIRMED', '2026-10-20', NOW)
  assert.equal(stale.label, 'Stale - re-verify before applying')
  assert.match(stale.text, /brand-dark/)
  const fresh = getVerificationBadge('OPEN_CONFIRMED', '2026-10-28', NOW)
  assert.equal(fresh.label, 'Verified open')
  assert.match(fresh.text, /domain-code/)
})

test('footer shows last checked N days ago and stale chip', () => {
  const c = cleanOpportunity({
    current_status: 'OPEN_CONFIRMED',
    last_verified_at: '2026-10-20',
    confirmed_open_date: '2026-10-01',
  }, NOW)
  assert.match(c.footerLine, /Last checked 9 days ago/)
  assert.equal(c.verificationBadge.label, 'Stale - re-verify before applying')
})
