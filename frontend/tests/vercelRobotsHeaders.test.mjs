import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'

const frontendConfig = JSON.parse(fs.readFileSync(new URL('../vercel.json', import.meta.url)))
const rootConfig = JSON.parse(fs.readFileSync(new URL('../../vercel.json', import.meta.url)))
const configs = [frontendConfig, rootConfig]

function getNoindexRule(config) {
  const noindexRule = config.headers.find(
    (entry) =>
      entry.source?.startsWith('/((?!') &&
      entry.headers?.some((h) => h.key === 'X-Robots-Tag' && h.value?.startsWith('noindex'))
  )
  assert.ok(noindexRule, "Expected negative-lookahead noindex header rule starting with '/((?!'")
  return noindexRule
}

test("root '/' rule sets 'index, follow'", () => {
  for (const config of configs) {
    const rootRule = config.headers.find((entry) => entry.source === '/')
    assert.ok(rootRule, "Expected rule for source '/'")
    const robotsHeader = rootRule.headers.find((h) => h.key === 'X-Robots-Tag')
    assert.ok(robotsHeader, "Expected 'X-Robots-Tag' header on '/' rule")
    assert.equal(robotsHeader.value, 'index, follow')
  }
})

test('both manifests contain the same noindex-rule source string', () => {
  assert.equal(
    getNoindexRule(frontendConfig).source,
    getNoindexRule(rootConfig).source,
    'Expected frontend/vercel.json and vercel.json to have identical noindex-rule source strings'
  )
})

test('negative-lookahead noindex rule matches paths that must be noindexed', () => {
  for (const config of configs) {
    const noindexRule = getNoindexRule(config)
    const regex = new RegExp('^' + noindexRule.source + '$')

    const mustMatch = [
      '/compass',
      '/career',
      '/terms',
      '/api/tasks',
      '/assets/index.js',
    ]
    for (const path of mustMatch) {
      assert.equal(regex.test(path), true, `Expected ${path} to match noindex rule`)
    }
  }
})

test('negative-lookahead noindex rule does not match paths that must stay indexable', () => {
  for (const config of configs) {
    const noindexRule = getNoindexRule(config)
    const regex = new RegExp('^' + noindexRule.source + '$')

    const mustNotMatch = [
      '/',
      '/robots.txt',
      '/sitemap.xml',
      '/google7f439d867e743102.html',
      '/og-image.png',
      '/logo.png',
      '/favicon.ico',
      '/favicon-32x32.png',
      '/favicon-16x16.png',
      '/apple-touch-icon.png',
    ]
    for (const path of mustNotMatch) {
      assert.equal(regex.test(path), false, `Expected ${path} NOT to match noindex rule (stay indexable)`)
    }
  }
})
