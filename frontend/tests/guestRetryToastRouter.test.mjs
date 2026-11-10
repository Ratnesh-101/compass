import test, { beforeEach } from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import * as base from '../src/api/baseClient.js'
import * as tasksApi from '../src/api/tasksApi.js'
import { buildUrl } from '../src/router.js'

const __dirname = path.dirname(fileURLToPath(import.meta.url))

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
    calls.push({ url: String(url), method: init.method || 'GET', headers: init.headers, body: init.body })
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

function setupGuestRetryMock(taskUrlFragment, successPayload) {
  let taskAttempts = 0
  mockFetch((url) => {
    if (url.includes('/api/guest/session')) {
      return json(200, { guest_id: 'guest-new', guest_token: 'token-new' })
    }
    if (url.includes(taskUrlFragment)) {
      taskAttempts++
      if (taskAttempts === 1) {
        return json(401, { detail: 'Guest session expired' })
      }
      return json(200, successPayload)
    }
    return json(404, { detail: 'Not found' })
  })
}

// ---------------------------------------------------------------------------
// a) tasksApi mutation functions: re-mint expired guest session and retry
// ---------------------------------------------------------------------------

test('tasksApi.createTask: guest token re-mints on 401 and retries', async () => {
  base.setGuestSession('guest-old', 'token-old')
  assert.equal(globalThis.localStorage.getItem('compass_auth_token'), null)
  assert.equal(globalThis.localStorage.getItem('compass_user_email'), null)

  const payload = { id: 'task-new-1', title: 'Buy milk' }
  setupGuestRetryMock('/api/tasks', payload)

  const res = await tasksApi.createTask({ title: 'Buy milk' })

  const taskCalls = calls.filter((c) => c.url.includes('/api/tasks') && !c.url.includes('/api/guest/session'))
  assert.equal(taskCalls.length, 2, 'task URL must be requested twice')
  assert.deepEqual(res, payload, 'must resolve with success value from retry')
  assert.equal(base.getGuestToken(), 'token-new')
})

test('tasksApi.deleteTask: guest token re-mints on 401 and retries', async () => {
  base.setGuestSession('guest-old', 'token-old')
  assert.equal(globalThis.localStorage.getItem('compass_auth_token'), null)
  assert.equal(globalThis.localStorage.getItem('compass_user_email'), null)

  const payload = { success: true, id: 'task-del-1' }
  setupGuestRetryMock('/api/tasks/task-del-1', payload)

  const res = await tasksApi.deleteTask('task-del-1')

  const taskCalls = calls.filter((c) => c.url.includes('/api/tasks/task-del-1'))
  assert.equal(taskCalls.length, 2, 'task URL must be requested twice')
  assert.deepEqual(res, payload, 'must resolve with success value from retry')
  assert.equal(base.getGuestToken(), 'token-new')
})

test('tasksApi.updateTask: guest token re-mints on 401 and retries', async () => {
  base.setGuestSession('guest-old', 'token-old')
  assert.equal(globalThis.localStorage.getItem('compass_auth_token'), null)
  assert.equal(globalThis.localStorage.getItem('compass_user_email'), null)

  const payload = { id: 'task-upd-1', status: 'completed' }
  setupGuestRetryMock('/api/tasks/task-upd-1', payload)

  const res = await tasksApi.updateTask('task-upd-1', { status: 'completed' })

  const taskCalls = calls.filter((c) => c.url.includes('/api/tasks/task-upd-1'))
  assert.equal(taskCalls.length, 2, 'task URL must be requested twice')
  assert.deepEqual(res, payload, 'must resolve with success value from retry')
  assert.equal(base.getGuestToken(), 'token-new')
})

test('tasksApi.verifyTaskDeadline: guest token re-mints on 401 and retries', async () => {
  base.setGuestSession('guest-old', 'token-old')
  assert.equal(globalThis.localStorage.getItem('compass_auth_token'), null)
  assert.equal(globalThis.localStorage.getItem('compass_user_email'), null)

  const payload = { verified: true, task_id: 'task-ver-1' }
  setupGuestRetryMock('/api/tasks/task-ver-1/verify', payload)

  const res = await tasksApi.verifyTaskDeadline('task-ver-1')

  const taskCalls = calls.filter((c) => c.url.includes('/api/tasks/task-ver-1/verify'))
  assert.equal(taskCalls.length, 2, 'task URL must be requested twice')
  assert.deepEqual(res, payload, 'must resolve with success value from retry')
  assert.equal(base.getGuestToken(), 'token-new')
})

test('tasksApi.verifyAllDeadlines: guest token re-mints on 401 and retries', async () => {
  base.setGuestSession('guest-old', 'token-old')
  assert.equal(globalThis.localStorage.getItem('compass_auth_token'), null)
  assert.equal(globalThis.localStorage.getItem('compass_user_email'), null)

  const payload = { verified_count: 4 }
  setupGuestRetryMock('/api/tasks/verify-deadlines', payload)

  const res = await tasksApi.verifyAllDeadlines()

  const taskCalls = calls.filter((c) => c.url.includes('/api/tasks/verify-deadlines'))
  assert.equal(taskCalls.length, 2, 'task URL must be requested twice')
  assert.deepEqual(res, payload, 'must resolve with success value from retry')
  assert.equal(base.getGuestToken(), 'token-new')
})

// ---------------------------------------------------------------------------
// b) Source-level test for ChatPanel.jsx
// ---------------------------------------------------------------------------

test('ChatPanel.jsx source contains toastTimerRef, clears timeout before setTimeout, and assigns timer id', () => {
  const chatPanelPath = path.resolve(__dirname, '../src/components/ChatPanel.jsx')
  const content = fs.readFileSync(chatPanelPath, 'utf8')

  assert.ok(content.includes('toastTimerRef'), 'ChatPanel.jsx must contain toastTimerRef')

  const showToastIndex = content.indexOf('const showToast')
  assert.ok(showToastIndex !== -1, 'ChatPanel.jsx must define showToast')

  const showToastSlice = content.slice(showToastIndex, showToastIndex + 400)
  const clearTimeoutPos = showToastSlice.indexOf('clearTimeout')
  const setTimeoutPos = showToastSlice.indexOf('setTimeout')

  assert.ok(clearTimeoutPos !== -1, 'showToast must call clearTimeout')
  assert.ok(setTimeoutPos !== -1, 'showToast must call setTimeout')
  assert.ok(clearTimeoutPos < setTimeoutPos, 'showToast must call clearTimeout before setTimeout')

  assert.ok(
    content.includes('toastTimerRef.current = setTimeout(() => setToast(null), 2500)'),
    'toastTimerRef.current must be assigned setTimeout(() => setToast(null), 2500)'
  )

  assert.ok(
    content.includes('clearTimeout(toastTimerRef.current)'),
    'unmount cleanup effect must clear toastTimerRef.current'
  )
})

// ---------------------------------------------------------------------------
// c) buildUrl aliases and dashboard mapping
// ---------------------------------------------------------------------------

test('buildUrl correctly maps aliases and dashboard', () => {
  // compass / assistant / planner / northstar -> '/compass'
  assert.equal(buildUrl('compass'), '/compass')
  assert.equal(buildUrl('assistant'), '/compass')
  assert.equal(buildUrl('planner'), '/compass')
  assert.equal(buildUrl('northstar'), '/compass')

  // calendar / schedule -> '/schedule'
  assert.equal(buildUrl('calendar'), '/schedule')
  assert.equal(buildUrl('schedule'), '/schedule')

  // career / radar / copilot / internships -> '/career'
  assert.equal(buildUrl('career'), '/career')
  assert.equal(buildUrl('radar'), '/career')
  assert.equal(buildUrl('copilot'), '/career')
  assert.equal(buildUrl('internships'), '/career')

  // dashboard -> '/'
  assert.equal(buildUrl('dashboard'), '/')
})
