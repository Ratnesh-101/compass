import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const appSource = readFileSync(new URL('../src/App.jsx', import.meta.url), 'utf8')

test('task polling interval is throttled to at least 5 seconds', () => {
  const match = appSource.match(/const TASK_POLL_INTERVAL_MS = (\d+)/)
  assert.ok(match, 'TASK_POLL_INTERVAL_MS must be defined')
  assert.ok(Number(match[1]) >= 5000)
  assert.match(appSource, /setInterval\(pollTasks, TASK_POLL_INTERVAL_MS\)/)
  assert.doesNotMatch(appSource, /setInterval\(pollTasks, 3000\)/)
})

test('pollTasks skips hidden tabs and overlapping requests', () => {
  const start = appSource.indexOf('const pollTasks = () =>')
  assert.ok(start > -1, 'pollTasks must exist')
  const body = appSource.slice(start, start + 600)
  assert.match(body, /document\.hidden/)
  assert.match(body, /pollInFlightRef\.current/)
  assert.match(appSource, /const pollInFlightRef = useRef\(false\)/)
})

test('visibilitychange listener is added and removed', () => {
  assert.match(appSource, /addEventListener\('visibilitychange', handleVisibilityChange\)/)
  assert.match(appSource, /removeEventListener\('visibilitychange', handleVisibilityChange\)/)
})
