import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import { newestRefreshDate } from '../src/utils/radarRefresh.js'

test('newestRefreshDate uses stats.last_sync_at when newer than opportunities', () => {
  const opps = [
    { last_verified_at: '2026-10-24T10:00:00Z', last_checked_at: '2026-10-24T09:00:00Z' },
  ]
  const stats = { last_sync_at: '2026-11-12T04:00:00Z' }

  const d = newestRefreshDate(opps, stats)
  assert.ok(d instanceof Date)
  assert.equal(d.toISOString(), '2026-11-12T04:00:00.000Z')
})

test('newestRefreshDate falls back to opportunity timestamps when stats has no sync time', () => {
  const opps = [
    { last_verified_at: '2026-11-10T12:00:00Z' },
    { last_verified_at: '2026-11-11T08:00:00Z' },
  ]
  const stats = { last_sync_at: null }

  const d = newestRefreshDate(opps, stats)
  assert.ok(d instanceof Date)
  assert.equal(d.toISOString(), '2026-11-11T08:00:00.000Z')
})

test('newestRefreshDate handles empty or null data without crashing', () => {
  assert.equal(newestRefreshDate([], null), null)
  assert.equal(newestRefreshDate(null, null), null)
  assert.equal(newestRefreshDate(null, { last_sync_at: null }), null)
})

test('InternshipRadar component integrates stats into newestRefreshDate and passes recent_24h', () => {
  const source = fs.readFileSync(
    new URL('../src/components/InternshipRadar.jsx', import.meta.url),
    'utf8',
  )
  assert.ok(source.includes('newestRefreshDate(opportunities, stats)'))
  assert.ok(source.includes('recent_24h: true'))
  assert.ok(source.includes('fetchRecommendedOpportunities(30, selectedEmployerType, indiaOnly)'))
  assert.ok(source.includes('is_india_eligible !== false'))
})

test('radarApi correctly serializes recent_24h and ensures session on user actions', () => {
  const source = fs.readFileSync(
    new URL('../src/api/radarApi.js', import.meta.url),
    'utf8',
  ).replaceAll(String.fromCharCode(13), '')
  assert.ok(source.includes("params.set('recent_24h', 'true')"))
  assert.ok(source.includes("params.set('india_only', String(india_only))"))
  assert.ok(source.includes('export async function fetchWatchlist() {\n  await ensureSession()'))
  assert.ok(source.includes('export async function saveOpportunity(id) {\n  await ensureSession()'))
  assert.ok(source.includes('export async function unsaveOpportunity(id) {\n  await ensureSession()'))
  assert.ok(source.includes('export async function fetchApplications() {\n  await ensureSession()'))
})
