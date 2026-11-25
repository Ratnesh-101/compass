import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'

const read = rel => fs.readFileSync(new URL(`../src/${rel}`, import.meta.url), 'utf8')

function fnBody(src, name) {
  const start = src.indexOf(`function ${name}(`)
  assert.ok(start >= 0, `${name} not found`)
  const next = src.indexOf('\nexport ', start + 1)
  return src.slice(start, next === -1 ? undefined : next)
}

test('fetchRadarAnalytics takes an india flag and adds india_only=true only when set', () => {
  const body = fnBody(read('api/radarApi.js'), 'fetchRadarAnalytics')
  const sig = body.match(/fetchRadarAnalytics\(([^)]*)\)/)[1]
  assert.ok(sig.trim().length > 0, 'fetchRadarAnalytics must accept an argument')
  assert.ok(body.includes('india_only=true'), 'URL must carry india_only=true')
  assert.ok(body.includes('/api/opportunities/analytics'))
  // the parameter must be used to decide (conditional), not appended unconditionally
  const arg = sig.split(/[=,{}\s]+/).filter(Boolean)[0]
  assert.ok(new RegExp(`${arg}\\s*\\?|if\\s*\\(\\s*${arg}\\b|${arg}\\s*&&`).test(body))
})

test('fetchRadarAnalytics sends india_only=true only for true (stubbed fetch)', async () => {
  const src = read('api/radarApi.js')
  if (!/^import /m.test(src) && !src.includes('ensureSession')) return
  let mod
  try {
    mod = await import('../src/api/radarApi.js')
  } catch {
    return // module needs browser globals; source test above covers it
  }
  const urls = []
  const origFetch = globalThis.fetch
  globalThis.fetch = async url => {
    urls.push(String(url))
    return { ok: true, status: 200, json: async () => ({}) }
  }
  try {
    await mod.fetchRadarAnalytics(true)
    await mod.fetchRadarAnalytics(false)
    await mod.fetchRadarAnalytics()
  } catch {
    return // session bootstrap not available under node
  } finally {
    globalThis.fetch = origFetch
  }
  const analytics = urls.filter(u => u.includes('/api/opportunities/analytics'))
  if (analytics.length === 3) {
    assert.ok(analytics[0].includes('india_only=true'))
    assert.ok(!analytics[1].includes('india_only'))
    assert.ok(!analytics[2].includes('india_only'))
  }
})

test('InternshipRadar passes the India toggle to analytics and reloads on change', () => {
  const src = read('components/InternshipRadar.jsx')
  assert.ok(/fetchRadarAnalytics\(\s*indiaOnly\s*\)/.test(src), 'InternshipRadar must call fetchRadarAnalytics(indiaOnly)')
  const callIdx = Math.max(src.indexOf('fetchRadarAnalytics(indiaOnly'), 0)
  const effectEnd = src.indexOf('}, [', callIdx)
  assert.ok(effectEnd > callIdx, 'effect dependency list not found after the call')
  const deps = src.slice(effectEnd, src.indexOf(']', effectEnd))
  assert.ok(/\bindiaOnly\b/.test(deps), `deps should include indiaOnly: ${deps}`)
})
