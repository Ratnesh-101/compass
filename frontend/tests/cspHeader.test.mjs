import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'

const frontendConfig = JSON.parse(fs.readFileSync(new URL('../vercel.json', import.meta.url)))
const rootConfig = JSON.parse(fs.readFileSync(new URL('../../vercel.json', import.meta.url)))
const configs = [
  { name: 'frontend/vercel.json', config: frontendConfig },
  { name: 'vercel.json (root)', config: rootConfig },
]

const EXPECTED_CSP = [
  "default-src 'self'",
  "script-src 'self' 'unsafe-inline'",
  "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
  "font-src 'self' https://fonts.gstatic.com data:",
  "img-src 'self' data: blob: https:",
  "connect-src 'self'",
  "frame-ancestors 'none'",
  "object-src 'none'",
  "base-uri 'self'",
  "form-action 'self' https://accounts.google.com",
].join('; ')

function findCspHeader(config) {
  for (const entry of config.headers || []) {
    const csp = entry.headers?.find(
      (h) => h.key === 'Content-Security-Policy'
    )
    if (csp) return { entry, header: csp }
  }
  return null
}

test('both manifests contain Content-Security-Policy header with frame-ancestors none and default-src self', () => {
  for (const { name, config } of configs) {
    const found = findCspHeader(config)
    assert.ok(found, `Expected ${name} to contain a Content-Security-Policy header`)
    assert.match(
      found.header.value,
      /frame-ancestors 'none'/,
      `Expected ${name} CSP to contain "frame-ancestors 'none'"`
    )
    assert.match(
      found.header.value,
      /default-src 'self'/,
      `Expected ${name} CSP to contain "default-src 'self'"`
    )
    assert.equal(
      found.header.value.includes('report-uri'),
      false,
      `Expected ${name} CSP NOT to include report-uri`
    )
    assert.equal(
      found.header.value,
      EXPECTED_CSP,
      `Expected ${name} CSP to match the exact defined policy`
    )
  }
})

test('frontend/vercel.json and root vercel.json stay identical in Content-Security-Policy header and source route', () => {
  const frontendCsp = findCspHeader(frontendConfig)
  const rootCsp = findCspHeader(rootConfig)

  assert.ok(frontendCsp, 'frontend/vercel.json must have CSP header')
  assert.ok(rootCsp, 'root vercel.json must have CSP header')

  assert.equal(
    frontendCsp.header.value,
    rootCsp.header.value,
    'Expected frontend/vercel.json and vercel.json to have identical CSP values'
  )
  assert.equal(
    frontendCsp.entry.source,
    rootCsp.entry.source,
    'Expected frontend/vercel.json and vercel.json to configure CSP on the same source route'
  )
})
