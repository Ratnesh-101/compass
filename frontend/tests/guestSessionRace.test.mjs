import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'

const read = rel => fs.readFileSync(new URL(`../src/${rel}`, import.meta.url), 'utf8')

// ---- source-text wiring ----------------------------------------------------

test('baseClient.js exports ensureGuestSession and authedFetch', () => {
  const src = read('api/baseClient.js')
  assert.match(src, /export\s+(async\s+)?function\s+ensureGuestSession\b/)
  assert.match(src, /export\s+(async\s+)?function\s+authedFetch\b/)
})

test('chatApi.js imports ensureGuestSession/authedFetch from ./baseClient.js and has no local ensureSession', () => {
  const src = read('api/chatApi.js')
  const m = src.match(/import\s*\{([^}]*)\}\s*from\s*'\.\/baseClient\.js'/)
  assert.ok(m, 'no import from ./baseClient.js')
  assert.match(m[1], /\bauthedFetch\b/)
  assert.ok(!src.includes('async function ensureSession'))
})

test('careerApi.js imports the shared ensureGuestSession and has no local ensureSession', () => {
  const src = read('api/careerApi.js')
  const m = src.match(/import\s*\{([^}]*)\}\s*from\s*'\.\/baseClient\.js'/)
  assert.ok(m, 'no import from ./baseClient.js')
  assert.match(m[1], /\bensureGuestSession\b/)
  assert.ok(!src.includes('async function ensureSession'))
})

test('chatApi.js calls to parked, agent runs/activity and profile facts use authedFetch', () => {
  const lines = read('api/chatApi.js').split(/\r?\n/)
  const required = { '/api/parked': true, 'agent/runs': false, 'agent/activity': false, 'profile/facts': true }
  for (const [needle, mustExist] of Object.entries(required)) {
    const hits = lines.map((l, i) => (l.includes(needle) ? i : -1)).filter(i => i >= 0)
    if (mustExist) assert.ok(hits.length > 0, `no occurrence of ${needle}`)
    for (const i of hits) {
      const around = lines.slice(Math.max(0, i - 3), i + 4).join('\n')
      assert.ok(/authedFetch\(/.test(around), `${needle} (line ${i + 1}) is not using authedFetch`)
    }
  }
})

test('chatApi.js streaming and conversation calls use authedFetch', () => {
  const lines = read('api/chatApi.js').split(/\r?\n/)
  for (const needle of ['/api/chat/stream', '/api/conversations']) {
    const hits = lines.map((l, i) => (l.includes('`${API_BASE}' + needle) ? i : -1)).filter(i => i >= 0)
    assert.ok(hits.length > 0, `no occurrence of ${needle}`)
    for (const i of hits) {
      const around = lines.slice(Math.max(0, i - 3), i + 4).join('\n')
      assert.ok(/authedFetch\(/.test(around), `${needle} (line ${i + 1}) is not using authedFetch`)
    }
  }
})

test('chatApi.js shows the friendly session message, not the raw auth sentence', () => {
  const src = read('api/chatApi.js')
  assert.ok(src.includes('Your session is still starting. Please try again in a moment.'))
  assert.ok(!src.includes('Authentication required: active session or valid guest token required'))
})

// ---- behaviour -------------------------------------------------------------

function makeStorage(initial = {}) {
  const m = new Map(Object.entries(initial))
  return {
    getItem: k => (m.has(k) ? m.get(k) : null),
    setItem: (k, v) => { m.set(k, String(v)) },
    removeItem: k => { m.delete(k) },
  }
}

function jsonResponse(status, body) {
  return {
    ok: status >= 200 && status < 300,
    status,
    headers: { get: () => null },
    json: async () => body,
    text: async () => JSON.stringify(body),
  }
}

const GUEST_BODY = { guest_token: 'tok123', guest_id: 'g1', is_new: true }

// Fresh storage, fake fetch and module instance per test. `handler(url, init, calls)` returns a response.
async function setup(storage, handler) {
  const calls = []
  globalThis.localStorage = makeStorage(storage)
  globalThis.fetch = async (url, init = {}) => {
    calls.push({ url: String(url), init })
    return handler(String(url), init, calls)
  }
  const mod = await import(`../src/api/baseClient.js?${Math.random()}`)
  return { mod, calls }
}

const isGuestSession = c => c.url.includes('/api/guest/session')
const headerOf = (init, name) => {
  const h = init.headers
  if (!h) return undefined
  return typeof h.get === 'function' ? h.get(name) : h[name]
}

test('signed-in user: ensureGuestSession does not touch the guest endpoint', async () => {
  const { mod, calls } = await setup({ compass_user_email: 'a@b.co' }, () => jsonResponse(200, GUEST_BODY))
  await mod.ensureGuestSession()
  assert.equal(calls.filter(isGuestSession).length, 0)
})

test('guest without token: concurrent ensureGuestSession calls make exactly one POST', async () => {
  const { mod, calls } = await setup({}, async () => {
    await new Promise(r => setTimeout(r, 20))
    return jsonResponse(200, GUEST_BODY)
  })
  await Promise.all([mod.ensureGuestSession(), mod.ensureGuestSession(), mod.ensureGuestSession()])
  const posts = calls.filter(c => isGuestSession(c) && c.init.method === 'POST')
  assert.equal(posts.length, 1)
  assert.equal(calls.filter(isGuestSession).length, 1)
  assert.equal(globalThis.localStorage.getItem('compass_guest_token'), 'tok123')
})

test('authedFetch sends x-guest-token with the stored token', async () => {
  const { mod, calls } = await setup({ compass_guest_token: 'tok123', compass_guest_id: 'g1' }, () => jsonResponse(200, { ok: 1 }))
  const res = await mod.authedFetch('/api/target', { method: 'GET' })
  assert.equal(res.status, 200)
  const target = calls.filter(c => c.url.endsWith('/api/target'))
  assert.equal(target.length, 1)
  assert.equal(headerOf(target[0].init, 'x-guest-token'), 'tok123')
})

test('authedFetch mints the guest session first when none exists, then sends its token', async () => {
  const { mod, calls } = await setup({}, url => (url.includes('/api/guest/session') ? jsonResponse(200, GUEST_BODY) : jsonResponse(200, {})))
  await mod.authedFetch('/api/target')
  const target = calls.filter(c => c.url.endsWith('/api/target'))
  assert.equal(target.length, 1)
  assert.equal(headerOf(target[0].init, 'x-guest-token'), 'tok123')
  assert.ok(calls.indexOf(target[0]) > calls.findIndex(isGuestSession))
})

test('authedFetch retries a 401 once and returns the 200', async () => {
  let n = 0
  const { mod, calls } = await setup({ compass_guest_token: 'tok123', compass_guest_id: 'g1' }, url => {
    if (url.includes('/api/guest/session')) return jsonResponse(200, GUEST_BODY)
    n += 1
    return n === 1 ? jsonResponse(401, { detail: 'nope' }) : jsonResponse(200, { ok: 1 })
  })
  const res = await mod.authedFetch('/api/target', { method: 'GET' })
  assert.equal(res.status, 200)
  assert.equal(calls.filter(c => c.url.endsWith('/api/target')).length, 2)
})

test('authedFetch returns the 401 after exactly one retry when it persists', async () => {
  const { mod, calls } = await setup({ compass_guest_token: 'tok123', compass_guest_id: 'g1' }, url =>
    url.includes('/api/guest/session') ? jsonResponse(200, GUEST_BODY) : jsonResponse(401, { detail: 'nope' }))
  const res = await mod.authedFetch('/api/target', { method: 'GET' })
  assert.equal(res.status, 401)
  assert.equal(calls.filter(c => c.url.endsWith('/api/target')).length, 2)
})
