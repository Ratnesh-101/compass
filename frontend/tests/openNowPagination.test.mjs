import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const api = readFileSync(new URL('../src/api/radarApi.js', import.meta.url), 'utf8')
const comp = readFileSync(new URL('../src/components/InternshipRadar.jsx', import.meta.url), 'utf8')

test('open fetch sends offset and reads the total header', () => {
  const fn = api.slice(api.indexOf('export async function fetchOpenOpportunities'), api.indexOf('export async function fetchSourceInventory'))
  assert.match(fn, /params\.set\('offset'/)
  assert.match(fn, /X-Total-Count/)
})

test('Open Now passes offset when appending and dedupes by id', () => {
  assert.match(comp, /offset: isAppending \? options\.offset \|\| 0 : 0/)
  assert.match(comp, /offset: openLoadedRef\.current/)
  assert.match(comp, /new Set\(prev\.map\(o => o\.id\)\)/)
})

test('Load more is gated on total greater than loaded', () => {
  assert.match(comp, /openPage\.total \|\| statsRef\.current\?\.verified_open_count/)
  assert.match(comp, /openTotal > openLoadedRef\.current/)
  assert.match(comp, /'Load more'/)
  assert.match(comp, /\{hasMore && \(/)
})
