import test, { beforeEach } from 'node:test'
import assert from 'node:assert/strict'
import * as base from '../src/api/baseClient.js'
import * as calendarApi from '../src/api/calendarApi.js'
import * as chatApi from '../src/api/chatApi.js'

const store = new Map()
globalThis.localStorage = {
  getItem: (k) => (store.has(k) ? store.get(k) : null),
  setItem: (k, v) => store.set(k, String(v)),
  removeItem: (k) => store.delete(k),
  clear: () => store.clear(),
}
const events = []
globalThis.window = {
  localStorage: globalThis.localStorage,
  CustomEvent: globalThis.CustomEvent,
  dispatchEvent: (e) => { events.push(e); return true },
}

const realFetch = globalThis.fetch
const calls = []
function mockFetch(handler) {
  globalThis.fetch = async (url, init = {}) => {
    calls.push({ url: String(url), method: init.method || 'GET' })
    return handler(String(url), init)
  }
}
const json = (status, body, headers = {}) => ({
  ok: status >= 200 && status < 300,
  status,
  headers: { get: (k) => headers[k.toLowerCase()] ?? null },
  json: async () => body,
})

beforeEach(() => {
  store.clear()
  calls.length = 0
  events.length = 0
  if (typeof base.resetGuestMintBackoff === 'function') base.resetGuestMintBackoff()
  globalThis.fetch = realFetch
})

const sessionCalls = () => calls.filter((c) => c.url.endsWith('/api/guest/session'))

test('existing token + GET 503 keeps the guest: no POST, token untouched', async () => {
  base.setGuestSession('g-old', 't-old')
  mockFetch(() => json(503, {}))
  const res = await base.initGuestSession()
  assert.equal(res, null)
  assert.deepEqual(sessionCalls().map((c) => c.method), ['GET'])
  assert.equal(base.getGuestToken(), 't-old')
  assert.equal(base.getGuestId(), 'g-old')
})

test('existing token + GET 429 keeps the guest', async () => {
  base.setGuestSession('g-old', 't-old')
  mockFetch(() => json(429, {}, { 'retry-after': '60' }))
  await base.initGuestSession()
  assert.deepEqual(sessionCalls().map((c) => c.method), ['GET'])
  assert.equal(base.getGuestToken(), 't-old')
})

test('existing token + network error keeps the guest', async () => {
  base.setGuestSession('g-old', 't-old')
  mockFetch(() => { throw new TypeError('Failed to fetch') })
  await base.initGuestSession()
  assert.deepEqual(sessionCalls().map((c) => c.method), ['GET'])
  assert.equal(base.getGuestToken(), 't-old')
})

test('existing token + GET 401 mints a replacement guest', async () => {
  base.setGuestSession('g-old', 't-old')
  mockFetch((url, init) => (init.method === 'POST'
    ? json(200, { guest_id: 'g-new', guest_token: 't-new' })
    : json(401, {})))
  const res = await base.initGuestSession()
  assert.equal(res.guest_token, 't-new')
  assert.deepEqual(sessionCalls().map((c) => c.method), ['GET', 'POST'])
  assert.equal(base.getGuestToken(), 't-new')
})

test('cross-tab: a token stored by another tab while minting is used, not overwritten', async () => {
  mockFetch(() => {
    base.setGuestSession('g-other-tab', 't-other-tab')
    return json(200, { guest_id: 'g-mine', guest_token: 't-mine' })
  })
  const res = await base.initGuestSession()
  assert.equal(base.getGuestToken(), 't-other-tab')
  assert.equal(res.guest_token, 't-other-tab')
})

test('mint failure backs off >= 30 s, does not re-mint on the next call, and announces busy state', async () => {
  mockFetch(() => json(503, {}, { 'retry-after': '2' }))
  assert.equal(await base.initGuestSession(), null)
  assert.equal(await base.initGuestSession(), null)
  assert.equal(await base.initGuestSession(), null)
  assert.equal(sessionCalls().length, 1, 'only one mint attempt inside the backoff window')
  const busy = events.find((e) => e.type === 'compass:service-busy')
  assert.ok(busy, 'a visible busy event is dispatched')
  assert.ok(busy.detail.waitMs >= 30000)
})

test('fetchCurrentUserResult separates transient failures from an explicit sign-out', async () => {
  mockFetch(() => json(503, {}))
  assert.equal((await calendarApi.fetchCurrentUserResult()).status, 'transient')
  mockFetch(() => { throw new TypeError('Failed to fetch') })
  assert.equal((await calendarApi.fetchCurrentUserResult()).status, 'transient')
  mockFetch(() => json(401, {}))
  assert.equal((await calendarApi.fetchCurrentUserResult()).status, 'unauthenticated')
  mockFetch(() => json(200, { authenticated: false }))
  assert.equal((await calendarApi.fetchCurrentUserResult()).status, 'unauthenticated')
  mockFetch(() => json(200, { authenticated: true, user_id: 'a@b.co', email: 'a@b.co' }))
  const ok = await calendarApi.fetchCurrentUserResult()
  assert.equal(ok.status, 'authenticated')
  assert.equal(base.getCurrentUserId(), 'a@b.co')
})

test('fetchCurrentUser keeps its legacy shape (data or null)', async () => {
  mockFetch(() => json(503, {}))
  assert.equal(await calendarApi.fetchCurrentUser(), null)
  mockFetch(() => json(200, { authenticated: false }))
  assert.deepEqual(await calendarApi.fetchCurrentUser(), { authenticated: false })
})

test('a transient /auth/me failure does not touch the stored identity', async () => {
  store.set('compass_user_email', 'keep@me.co')
  mockFetch(() => json(502, {}))
  await calendarApi.fetchCurrentUserResult()
  assert.equal(store.get('compass_user_email'), 'keep@me.co')
})

test('fetchDemoStatusResult flags 5xx and network errors as transient; fetchDemoStatus stays null', async () => {
  mockFetch(() => json(502, {}))
  assert.deepEqual(await chatApi.fetchDemoStatusResult(), { ok: false, transient: true, data: null })
  assert.equal(await chatApi.fetchDemoStatus(), null)
  mockFetch(() => json(200, { active: true, task_count: 3 }))
  const ok = await chatApi.fetchDemoStatusResult()
  assert.equal(ok.ok, true)
  assert.equal(ok.data.active, true)
})

test('health: db_connected false is NOT reported as Live', async () => {
  mockFetch(() => json(200, { status: 'degraded', db_connected: false }))
  const status = await base.checkBackendHealth(true)
  assert.match(status, /database waking up/i)
  assert.doesNotMatch(status.toLowerCase(), /live|neon|connected/)
  mockFetch(() => json(200, { status: 'ok', db_connected: true }))
  assert.match(await base.checkBackendHealth(true), /Live/)
})

test('fetchWithTimeout aborts a hanging request with a user-safe timeout error', async () => {
  globalThis.fetch = (url, init) => new Promise((resolve, reject) => {
    init.signal.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')))
  })
  await assert.rejects(
    () => base.fetchWithTimeout('/x', {}, 20),
    (err) => err.code === 'timeout' && /too long/i.test(err.message),
  )
})
