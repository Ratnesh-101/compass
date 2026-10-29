import test from 'node:test'
import assert from 'node:assert/strict'
import {
  classifyAuthMe,
  identityActionFor,
  shouldRemintGuest,
  computeMintBackoffMs,
  canAttemptMint,
  mapHealthPayload,
  isBackendOnline,
  parseOAuthReturn,
  stripOAuthParams,
  oauthErrorMessage,
  GENERIC_OAUTH_ERROR,
  isEmailSignInEnabled,
  MIN_MINT_BACKOFF_MS,
} from '../src/utils/firstRun.js'

test('classifyAuthMe: network error, timeout and 5xx are transient, never "signed out"', () => {
  for (const status of [0, null, undefined, 500, 502, 503, 504, 429, 404]) {
    assert.equal(classifyAuthMe(status, null), 'transient', `status ${status}`)
  }
})

test('classifyAuthMe: only 401 or authenticated:false is an explicit unauthenticated answer', () => {
  assert.equal(classifyAuthMe(401, null), 'unauthenticated')
  assert.equal(classifyAuthMe(200, { authenticated: false }), 'unauthenticated')
  assert.equal(classifyAuthMe(200, { authenticated: true, email: 'a@b.co' }), 'authenticated')
  assert.equal(classifyAuthMe(200, { email: 'a@b.co' }), 'authenticated')
})

test('identityActionFor: only an explicit unauthenticated answer clears stored identity', () => {
  assert.equal(identityActionFor('authenticated'), 'set')
  assert.equal(identityActionFor('unauthenticated'), 'clear')
  assert.equal(identityActionFor('transient'), 'keep')
})

test('shouldRemintGuest: only 401 proves the token is invalid', () => {
  assert.equal(shouldRemintGuest(401), true)
  for (const s of [200, 403, 429, 500, 502, 503, 504, 0]) assert.equal(shouldRemintGuest(s), false)
})

test('mint backoff: minimum 30 s, honours Retry-After, capped', () => {
  assert.equal(computeMintBackoffMs(null), MIN_MINT_BACKOFF_MS)
  assert.equal(computeMintBackoffMs('5'), MIN_MINT_BACKOFF_MS)
  assert.equal(computeMintBackoffMs('120'), 120000)
  assert.equal(computeMintBackoffMs('abc'), MIN_MINT_BACKOFF_MS)
  assert.ok(computeMintBackoffMs('999999') <= 5 * 60000)
  assert.equal(canAttemptMint(1000, 0), true)
  assert.equal(canAttemptMint(1000, 2000), false)
  assert.equal(canAttemptMint(2000, 2000), true)
})

test('health mapping: db_connected false is "Database waking up" and NOT online', () => {
  const waking = mapHealthPayload({ status: 'ok', db_connected: false })
  assert.match(waking, /waking up/i)
  assert.equal(isBackendOnline(waking), false)
  assert.equal(isBackendOnline(mapHealthPayload({ status: 'ok', db_connected: true })), true)
  assert.equal(isBackendOnline(mapHealthPayload({})), true)
  assert.equal(isBackendOnline('Waking up the server…'), false)
  assert.equal(isBackendOnline('Backend Error • HTTP 500'), false)
})

test('waking status passes none of the substring checks used by Dashboard/Sidebar/ChatPanel', () => {
  const s = mapHealthPayload({ db_connected: false }).toLowerCase()
  for (const word of ['neon', 'live', 'connected', 'ready']) assert.ok(!s.includes(word), word)
})

test('OAuth return: success is signalled without trusting the ?email= param', () => {
  const r = parseOAuthReturn('?calendar_connected=true&email=evil%40attacker.com')
  assert.deepEqual(r, { kind: 'connected' })
  assert.ok(!JSON.stringify(r).includes('attacker'))
})

test('OAuth return: known codes map to messages, unknown codes to a generic one', () => {
  assert.match(parseOAuthReturn('?calendar_error=access_denied').message, /cancelled|denied/i)
  assert.equal(parseOAuthReturn('?calendar_error=<script>alert(1)</script>').message, GENERIC_OAUTH_ERROR)
  assert.equal(parseOAuthReturn('?oauth_error=whatever').message, GENERIC_OAUTH_ERROR)
  assert.equal(oauthErrorMessage('__proto__'), GENERIC_OAUTH_ERROR)
  assert.equal(oauthErrorMessage('constructor'), GENERIC_OAUTH_ERROR)
  assert.equal(parseOAuthReturn('?select_account=1').kind, 'select_account')
  assert.equal(parseOAuthReturn('?foo=bar').kind, 'none')
  assert.equal(parseOAuthReturn('').kind, 'none')
})

test('stripOAuthParams removes only OAuth params and keeps the rest', () => {
  assert.equal(stripOAuthParams('?calendar_connected=true&email=a%40b.co'), '')
  assert.equal(stripOAuthParams('?oauth_error=x&share=abc'), '?share=abc')
  assert.equal(stripOAuthParams('?calendar_error=database_error'), '')
  assert.equal(stripOAuthParams('?email=keep%40me.co'), '?email=keep%40me.co')
  assert.equal(stripOAuthParams(''), '')
})

test('email sign-in is only enabled in development', () => {
  assert.equal(isEmailSignInEnabled({ DEV: true }), true)
  assert.equal(isEmailSignInEnabled({ DEV: false }), false)
  assert.equal(isEmailSignInEnabled(undefined), false)
})
