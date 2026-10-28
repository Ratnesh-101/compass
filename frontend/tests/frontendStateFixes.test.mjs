import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

// Polyfill browser globals for Node test environment
if (!globalThis.localStorage) {
  const store = new Map()
  globalThis.localStorage = {
    getItem: (key) => store.get(key) ?? null,
    setItem: (key, val) => store.set(key, String(val)),
    removeItem: (key) => store.delete(key),
    clear: () => store.clear(),
  }
}
if (!globalThis.window) {
  globalThis.window = { location: { hostname: 'localhost' } }
}

const { fetchTasks } = await import('../src/api/tasksApi.js')
const { haveTasksChanged } = await import('../src/utils/taskDiff.js')
const { isDemoTask } = await import('../src/utils/demoConstants.js')
const { getSafeHttpUrl } = await import('../src/utils/safeUrl.js')
const { initGuestSession } = await import('../src/api/baseClient.js')
const { streamQueryFromAssistant } = await import('../src/api/chatApi.js')

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const read = (rel) => fs.readFileSync(path.resolve(__dirname, '../src', rel), 'utf8')

function withFetch(impl, fn) {
  const original = globalThis.fetch
  globalThis.fetch = impl
  return Promise.resolve(fn()).finally(() => {
    globalThis.fetch = original
  })
}

function sseResponse(events) {
  const body = events.map((e) => `data: ${JSON.stringify(e)}\n\n`).join('')
  return new Response(body, { status: 200, headers: { 'Content-Type': 'text/event-stream' } })
}

test('Item 1/5: App polls with the latest domain ref and ignores stale loadTasks responses', () => {
  const code = read('App.jsx')
  assert.ok(code.includes('selectedDomainRef.current = selectedDomain'))
  assert.ok(code.includes('loadTasks(selectedDomainRef.current)'), 'pollers must read the domain ref')
  assert.ok(code.includes('++loadSeqRef.current'))
  assert.ok(code.includes('requestSeq !== loadSeqRef.current'), 'stale responses must be dropped')
})

test('Item 2: fetchTasks distinguishes failure (null) from a genuinely empty list ([])', async () => {
  await withFetch(async () => new Response('[]', { status: 200 }), async () => {
    assert.deepEqual(await fetchTasks('all'), [])
  })
  await withFetch(async () => new Response('boom', { status: 500 }), async () => {
    assert.equal(await fetchTasks('all'), null)
  })
  await withFetch(async () => { throw new TypeError('network down') }, async () => {
    assert.equal(await fetchTasks('all'), null)
  })
  await withFetch(async () => new Response('{"x":1}', { status: 200 }), async () => {
    assert.equal(await fetchTasks('all'), null)
  })
})

test('Item 3: haveTasksChanged detects changes in every user-visible field', () => {
  const base = { id: 1, title: 'T', countdown: '2d', status: 'open', domain: 'code', priority: 'low', notes: 'n', due_date: '2026-01-01', completed: false }
  assert.equal(haveTasksChanged([base], [{ ...base }]), false)
  for (const [field, value] of [
    ['status', 'completed'], ['domain', 'career'], ['priority', 'high'], ['notes', 'changed'],
    ['due_date', '2026-02-02'], ['deadline', '2026-03-03'], ['completed', true], ['tags', ['x']],
  ]) {
    assert.equal(haveTasksChanged([base], [{ ...base, [field]: value }]), true, `${field} change must be detected`)
  }
  assert.equal(haveTasksChanged([base], []), true)
})

test('Item 4: Dashboard clears optimistic override after a successful updateTask', () => {
  const code = read('components/Dashboard.jsx')
  const start = code.indexOf("await updateTask(taskId, { status: newStatus })")
  const catchIdx = code.indexOf('} catch (err) {', start)
  const successBlock = code.slice(start, catchIdx)
  assert.ok(successBlock.includes('delete next[taskId]'), 'override must be removed on the success path')
})

test('Item 6: ChatPanel clears the typewriter timer in handleNewChat and handleSelectPastChat', () => {
  const code = read('components/ChatPanel.jsx')
  for (const name of ['handleNewChat = () =>', 'handleSelectPastChat = async']) {
    const i = code.indexOf(name)
    assert.ok(i > 0)
    assert.ok(code.slice(i, i + 400).includes('clearStreamTimer()'), `${name} must clear the stream timer`)
  }
})

test('Item 7: done event with zero tokens completes normally; onComplete errors are not stream failures', async () => {
  let completeCalls = 0
  let errorCalls = 0
  await withFetch(async () => sseResponse([{ type: 'done', conversation_id: 'c1' }]), async () => {
    const result = await streamQueryFromAssistant('hi', null, {
      onComplete: async () => { completeCalls++ },
      onError: async () => { errorCalls++ },
    })
    assert.equal(result.conversation_id, 'c1')
  })
  assert.equal(completeCalls, 1)
  assert.equal(errorCalls, 0)

  const origError = console.error
  console.error = () => {}
  try {
    await withFetch(async () => sseResponse([{ type: 'token', value: 'ok' }, { type: 'done' }]), async () => {
      await streamQueryFromAssistant('hi', null, {
        onComplete: async () => { throw new Error('handler bug') },
        onError: async () => { errorCalls++ },
      })
    })
  } finally {
    console.error = origError
  }
  assert.equal(errorCalls, 0, 'onComplete failure must not reach onError')

  assert.ok(!read('components/ChatPanel.jsx').includes('await onSendMessage(text, tone, specialistIdToUse)'), 'no prompt re-send fallback')
})

test('Item 8: isDemoTask only matches seeded demo markers, not real URLs or tags', () => {
  assert.equal(isDemoTask({ id: '1', title: 'Real', trusted_event_url: 'https://demoday.example.com/e' }), false)
  assert.equal(isDemoTask({ id: '2', title: 'Real', tags: ['demo'] }), false)
  assert.equal(isDemoTask({ id: '3', title: 'Real', trusted_event_url: 'compass://demo-persona/x' }), true)
  assert.equal(isDemoTask({ id: 'demo-4', title: 'Real' }), true)
  assert.equal(isDemoTask({ id: '5', title: 'Real', is_demo: true }), true)
  assert.equal(isDemoTask({ id: '6', title: 'CS 61C Lab 4: RISC-V Pipeline Synthesis' }), true)
})

test('Item 9: concurrent initGuestSession calls share one POST', async () => {
  globalThis.localStorage.clear()
  let calls = 0
  await withFetch(async () => {
    calls++
    await new Promise((r) => setTimeout(r, 10))
    return new Response(JSON.stringify({ guest_id: 'g1', guest_token: 't1' }), { status: 200 })
  }, async () => {
    const [a, b, c] = await Promise.all([initGuestSession(), initGuestSession(), initGuestSession()])
    assert.equal(a.guest_id, 'g1')
    assert.equal(b, a)
    assert.equal(c, a)
  })
  assert.equal(calls, 1)
})

test('Item 10: getSafeHttpUrl allows only http(s) and the modal uses it for citation links', () => {
  assert.equal(getSafeHttpUrl('https://example.com/a'), 'https://example.com/a')
  assert.equal(getSafeHttpUrl('http://example.com'), 'http://example.com/')
  const bad = ['javascript:alert(1)', 'data:text/html,x', 'ftp://x.com', '/relative', 'not a url', '', null, undefined, 42]
  for (const value of bad) {
    assert.equal(getSafeHttpUrl(value), null, String(value))
  }
  const code = read('components/career/ApplicationWorkspaceModal.jsx')
  assert.ok(code.includes('getSafeHttpUrl(src.url)'))
  assert.ok(!code.includes('href={src.url}'))
})
