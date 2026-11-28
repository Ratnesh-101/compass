import { test } from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import { parseCareerLocation, buildCareerUrl, showDevSetupNote, CAREER_SUB_TABS } from '../src/utils/careerRouting.js'
import { parseLocation } from '../src/router.js'

const read = (p) => fs.readFileSync(new URL(p, import.meta.url), 'utf8')

test('career URL round-trips for every sub-tab', () => {
  for (const sub of CAREER_SUB_TABS) {
    const url = buildCareerUrl('career', sub)
    assert.deepEqual(parseCareerLocation(url.slice(url.indexOf('?'))), { tab: 'career', sub })
  }
  assert.equal(buildCareerUrl('career', 'resume'), '/?tab=copilot&sub=resume')
})

test('unknown tab and sub values fall back to defaults', () => {
  assert.deepEqual(parseCareerLocation('?tab=nope&sub=zzz'), { tab: 'dashboard', sub: 'radar' })
  assert.deepEqual(parseCareerLocation('?tab=copilot&sub=zzz'), { tab: 'career', sub: 'radar' })
  assert.deepEqual(parseCareerLocation(''), { tab: 'dashboard', sub: 'radar' })
  assert.equal(buildCareerUrl('career', 'zzz'), '/?tab=copilot')
  assert.equal(buildCareerUrl('nope'), '/')
})

test('main tabs round-trip', () => {
  for (const tab of ['dashboard', 'compass', 'calendar', 'timeline', 'career']) {
    const url = buildCareerUrl(tab)
    assert.equal(parseCareerLocation(url.slice(url.indexOf('?') === -1 ? url.length : url.indexOf('?'))).tab, tab === 'dashboard' ? 'dashboard' : tab)
  }
})

test('/copilot and /career resolve to Career Copilot', () => {
  assert.equal(parseLocation('/copilot', '').tab, 'career')
  assert.equal(parseLocation('/career', '').tab, 'career')
  assert.equal(parseLocation('/', '?tab=copilot&sub=resume').tab, 'career')
})

test('Vercel keeps the SPA rewrite for /copilot', () => {
  const cfg = JSON.parse(read('../vercel.json'))
  const spa = cfg.rewrites.find((r) => r.destination === '/index.html')
  assert.ok(spa)
  assert.ok(new RegExp(`^${spa.source}$`).test('/copilot'))
})

test('Career Copilot keeps the sub-tab in the URL and listens for back/forward', () => {
  const src = read('../src/components/CareerCopilot.jsx')
  assert.match(src, /history\.pushState/)
  assert.match(src, /addEventListener\('popstate'/)
})

test('setup note shows only outside production', () => {
  assert.equal(showDevSetupNote(true, 'example.com'), true)
  assert.equal(showDevSetupNote(false, 'localhost'), true)
  assert.equal(showDevSetupNote(false, '127.0.0.1'), true)
  assert.equal(showDevSetupNote(false, 'compass.example.com'), false)
  const src = read('../src/components/AuthModal.jsx')
  assert.match(src, /showDevSetupNote\(import\.meta\.env\.DEV, window\.location\.hostname\) && \(/)
})
