import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { freshnessLabels } from '../src/utils/radarFreshness.js'

const radarSrc = readFileSync(new URL('../src/components/InternshipRadar.jsx', import.meta.url), 'utf8')
const cardSrc = readFileSync(new URL('../src/components/radar/RadarOverviewCards.jsx', import.meta.url), 'utf8')

// .jsx cannot be imported by node, so lift the pure helper out of the source.
const start = radarSrc.indexOf('export function openNowSummary')
assert.ok(start >= 0, 'openNowSummary must be exported')
const endMatch = /\r?\n}\r?\n/.exec(radarSrc.slice(start))
const end = start + endMatch.index + endMatch[0].length
const body = radarSrc.slice(start, end).replace('export function', 'function')
const openNowSummary = new Function('freshnessLabels', `${body}\nreturn openNowSummary`)(freshnessLabels)

const NOW = new Date('2026-11-28T12:00:00Z')
const daysAgo = n => new Date(NOW.getTime() - n * 86400000).toISOString()
const open = (id, d) => ({ id, current_status: 'OPEN_CONFIRMED', last_verified_at: d == null ? null : daysAgo(d) })

test('fresh-only list says all verified', () => {
  const s = openNowSummary([open(1, 0), open(2, 5), open(3, 14)], NOW)
  assert.equal(s.text, 'Showing 3 open listings, all verified in the last 14 days')
  assert.equal(s.fresh, 3)
})

test('mixed list reports verified and re-check counts', () => {
  const s = openNowSummary([open(1, 1), open(2, 30), open(3, null), open(4, 2)], NOW)
  assert.equal(s.total, 4)
  assert.equal(s.fresh, 2)
  assert.equal(s.stale, 2)
  assert.equal(s.text, 'Showing 4 open listings: 2 verified in the last 14 days, 2 need a re-check')
})

test('empty list', () => {
  assert.equal(openNowSummary([], NOW).text, 'No open listings match your filters')
  assert.equal(openNowSummary(undefined, NOW).text, 'No open listings match your filters')
})

test('helper reuses freshnessLabels, not a hard-coded 14-day rule', () => {
  assert.match(body, /freshnessLabels\(/)
  assert.doesNotMatch(body, /\b14\s*\*|86400000|<=\s*14/)
})

test('card shows the 14-day hint under the number and the list renders the summary', () => {
  assert.match(cardSrc, /Checked in the last 14 days/)
  assert.match(radarSrc, /data-testid="open-now-summary"/)
  assert.match(radarSrc, /Load more/)
})
