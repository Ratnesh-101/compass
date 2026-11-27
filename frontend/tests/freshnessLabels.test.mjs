import test from 'node:test'
import assert from 'node:assert/strict'
import { freshnessLabels } from '../src/utils/radarFreshness.js'
import { cleanOpportunity } from '../src/utils/jobCardCleaner.js'

const NOW = new Date('2026-10-29T03:00:00Z')
const daysAgo = (n) => new Date(NOW.getTime() - n * 86400000).toISOString()
const open = (extra) => ({ current_status: 'OPEN_CONFIRMED', ...extra })

function allLabels(opp) {
  const f = freshnessLabels(opp, NOW)
  const c = cleanOpportunity(opp, NOW)
  return [
    f.verifiedBadgeLabel,
    f.needsRecheck ? 'Needs re-check' : null,
    f.ageText,
    c.verificationBadge.label,
    c.footerLine,
  ].filter(Boolean).join(' | ')
}

test('verified 1 day ago -> verified labels only', () => {
  const f = freshnessLabels(open({ last_verified_at: daysAgo(1) }), NOW)
  assert.equal(f.verifiedBadgeLabel, 'Verified open')
  assert.equal(f.showVerifiedBadge, true)
  assert.equal(f.needsRecheck, false)
  assert.equal(f.ageText, 'Verified 1 day ago')
})

test('verified today', () => {
  assert.equal(freshnessLabels(open({ last_verified_at: daysAgo(0) }), NOW).ageText, 'Verified today')
})

test('verified 20 days ago -> needs re-check, no verified badge', () => {
  const opp = open({ last_verified_at: daysAgo(20) })
  const f = freshnessLabels(opp, NOW)
  assert.equal(f.verifiedBadgeLabel, null)
  assert.equal(f.showVerifiedBadge, false)
  assert.equal(f.needsRecheck, true)
  assert.equal(f.ageText, 'Last verified 20 days ago')
  assert.notEqual(cleanOpportunity(opp, NOW).verificationBadge.label, 'Verified open')
})

test('window edge: 14 days fresh, 15 days stale', () => {
  assert.equal(freshnessLabels(open({ last_verified_at: daysAgo(14) }), NOW).fresh, true)
  assert.equal(freshnessLabels(open({ last_verified_at: daysAgo(15) }), NOW).fresh, false)
})

test('no last_verified_at -> Never verified, needs re-check, no verified badge', () => {
  const f = freshnessLabels(open({}), NOW)
  assert.equal(f.ageText, 'Never verified')
  assert.equal(f.needsRecheck, true)
  assert.equal(f.verifiedBadgeLabel, null)
  assert.notEqual(cleanOpportunity(open({}), NOW).verificationBadge.label, 'Verified open')
})

test('last_checked_at / updated_at / verification_age_days are ignored', () => {
  const opp = open({
    last_verified_at: daysAgo(20),
    last_checked_at: daysAgo(0),
    updated_at: daysAgo(0),
    verification_age_days: 0,
  })
  const f = freshnessLabels(opp, NOW)
  assert.equal(f.ageText, 'Last verified 20 days ago')
  assert.equal(f.needsRecheck, true)
})

test('contradictory phrases never co-occur', () => {
  const cases = [
    open({ last_verified_at: daysAgo(0) }),
    open({ last_verified_at: daysAgo(1) }),
    open({ last_verified_at: daysAgo(14) }),
    open({ last_verified_at: daysAgo(15) }),
    open({ last_verified_at: daysAgo(20), last_checked_at: daysAgo(0) }),
    open({ last_checked_at: daysAgo(0) }),
    open({}),
    {},
    null,
  ]
  for (const opp of cases) {
    const text = allLabels(opp)
    assert.doesNotMatch(text, /Not verified recently/, text)
    assert.doesNotMatch(text, /Last checked/, text)
    const hasVerifiedOpen = /Verified open/.test(text)
    assert.ok(!(hasVerifiedOpen && /Needs re-check|Never verified|Last verified/.test(text)), text)
  }
})
