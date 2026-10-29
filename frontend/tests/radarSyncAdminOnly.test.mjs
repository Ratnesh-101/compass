import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const radar = readFileSync(new URL('../src/components/InternshipRadar.jsx', import.meta.url), 'utf8')
const filters = readFileSync(new URL('../src/components/radar/RadarFilters.jsx', import.meta.url), 'utf8')
const api = readFileSync(new URL('../src/api/radarApi.js', import.meta.url), 'utf8')

test('Sync Sources button (admin-only endpoint) is not shown to ordinary users', () => {
  assert.ok(!filters.includes('Sync Sources'))
  assert.ok(!radar.includes('Trigger Discovery Sync'))
  assert.ok(!radar.includes('triggerRadarSync'))
})

test('radar shows a muted "Listings last refreshed" line instead', () => {
  assert.ok(filters.includes('Listings last refreshed'))
  assert.ok(radar.includes('last_verified_at') && radar.includes('last_checked_at'))
})

test('a failed sync surfaces the server detail instead of only an HTTP code', () => {
  assert.ok(api.includes('detail'))
})
