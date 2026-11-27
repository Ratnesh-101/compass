import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const api = readFileSync(new URL('../src/api/radarApi.js', import.meta.url), 'utf8')
const comp = readFileSync(new URL('../src/components/InternshipRadar.jsx', import.meta.url), 'utf8')

test('Open Now fetch requests limit 500', () => {
  const fn = api.slice(api.indexOf('export async function fetchOpenOpportunities'))
  const body = fn.slice(0, fn.indexOf('\n}\n'))
  assert.match(body, /params\.set\('limit', '500'\)/)
  assert.doesNotMatch(body, /'300'/)
  assert.match(comp, /fetchOpenOpportunities\(\{/)
})
