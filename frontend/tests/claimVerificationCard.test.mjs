import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'

const read = rel => fs.readFileSync(new URL(`../src/${rel}`, import.meta.url), 'utf8')

test('careerApi exports verifyResumeClaims posting to /verify-claims', () => {
  const src = read('api/careerApi.js')
  assert.match(src, /export\s+(async\s+)?(function\s+verifyResumeClaims|const\s+verifyResumeClaims)/)
  assert.ok(src.includes('/verify-claims'))
  const idx = src.indexOf('verifyResumeClaims')
  const body = src.slice(idx, idx + 400)
  assert.ok(body.includes('/verify-claims'))
  assert.match(body, /POST/i)
})

test('ClaimVerificationCard shows plain status groups and accessible markup', () => {
  const src = read('components/career/ClaimVerificationCard.jsx')
  for (const label of ['Found online', 'Not found', 'Could not be checked']) {
    assert.ok(src.includes(label), `missing label: ${label}`)
  }
  assert.ok(src.includes('noopener noreferrer'))
  assert.match(src, /rel=['"]noopener noreferrer['"]/)
  assert.match(src, /role=['"]status['"]/)
  assert.ok(src.includes('aria-live'))
  assert.match(src, /<button[\s\S]*?>\s*Dismiss\s*<\/button>/)
})

test('ClaimVerificationCard copy never calls a claim fake or false', () => {
  const src = read('components/career/ClaimVerificationCard.jsx')
  // Strip the allowed explanatory phrase, then check no accusing words remain in UI text.
  const stripped = src.replace(/does not mean[^\n'"`]*/gi, '')
  assert.ok(
    src.includes('does not mean') || /note/i.test(src),
    'card should show the explanatory phrase or the server note',
  )
  assert.ok(!/\bfake\b/i.test(stripped), 'UI copy must not say "fake"')
  const jsxText = [...stripped.matchAll(/>([^<>{}]+)</g)].map(m => m[1]).join(' ')
  assert.ok(!/\bfalse\b/i.test(jsxText), 'JSX text must not say "false"')
})

test('ResumeStudio wires the claim verification card', () => {
  const src = read('components/career/ResumeStudio.jsx')
  assert.match(src, /import\s+ClaimVerificationCard\s+from/)
  assert.ok(src.includes('verifyResumeClaims'))
  assert.ok(src.includes('Checking claims online'))
  assert.ok(src.includes('Verify factual claims'))
})
