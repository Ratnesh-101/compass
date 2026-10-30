import test from 'node:test'
import assert from 'node:assert/strict'
import { safeHref, sanitizeUrl } from '../src/utils/safeUrl.js'

test('SEC-08: sanitizeUrl rejects dangerous javascript:, data:, and vbscript: URIs', () => {
  const attacks = [
    'javascript:alert(1)',
    'JAVASCRIPT:alert(document.cookie)',
    '  javascript:alert(1)  ',
    'java\tscript:alert(1)',
    'java\nscript:alert(1)',
    'java\r\nscript:alert(1)',
    'javascript :alert(1)',
    'javascript://https://google.com/%0aalert(1)',
    'data:text/html,<script>alert(1)</script>',
    'DATA:text/html;base64,PHNjcmlwdD5hbGVydCgxKTwvc2NyaXB0Pg==',
    'vbscript:msgbox(1)',
    'VBSCRIPT:msgbox(1)',
    '//evil.com',
    '/\\evil.com',
    'file:///etc/passwd',
  ]

  for (const attack of attacks) {
    const sanitized = sanitizeUrl(attack)
    assert.equal(sanitized, null, `Expected null for attack: ${attack}`)
  }
})

test('SEC-08: sanitizeUrl allows valid https, http, and mailto URLs', () => {
  const valid = [
    'https://example.com',
    'https://compass.app/tasks?id=123',
    'http://localhost:8000/api',
    'mailto:support@compass.app',
  ]

  for (const url of valid) {
    assert.equal(sanitizeUrl(url), url)
  }
})

test('SEC-08: safeHref neutralizes dangerous schemes to # and allows safe paths', () => {
  const attacks = [
    'javascript:alert(1)',
    '  JaVaScRiPt:alert(1)  ',
    'data:text/html;base64,123',
    'vbscript:alert(1)',
    '//evil.com',
    '/\\evil.com',
    'http://',
    '',
    null,
    undefined,
  ]

  for (const attack of attacks) {
    assert.equal(safeHref(attack), '#', `Expected # for attack: ${attack}`)
  }

  assert.equal(safeHref('/dashboard'), '/dashboard')
  assert.equal(safeHref('/api/calendar/export.ics'), '/api/calendar/export.ics')
  assert.equal(safeHref('https://compass.app'), 'https://compass.app')
  assert.equal(safeHref('http://localhost:3000'), 'http://localhost:3000')
})
