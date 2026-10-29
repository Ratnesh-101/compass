import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import os from 'node:os'
import { fileURLToPath, pathToFileURL } from 'node:url'
import { rolldown } from 'rolldown'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const read = (rel) => fs.readFileSync(path.resolve(__dirname, rel), 'utf8')
const browserZone = Intl.DateTimeFormat().resolvedOptions().timeZone

function sseResponse(events, { failAfter = false } = {}) {
  const chunks = events.map((e) => new TextEncoder().encode(`data: ${JSON.stringify(e)}\n\n`))
  let i = 0
  return {
    ok: true,
    status: 200,
    body: {
      getReader: () => ({
        read: async () => {
          if (i < chunks.length) return { done: false, value: chunks[i++] }
          if (failAfter) throw new TypeError('network error')
          return { done: true, value: undefined }
        },
        releaseLock() {},
      }),
    },
  }
}

async function withFetch(stub, run) {
  const original = globalThis.fetch
  globalThis.fetch = stub
  try {
    return await run()
  } finally {
    globalThis.fetch = original
  }
}

test('the browser timezone and request id are sent with streamed chat requests', async () => {
  const bodies = []
  const stub = async (url, options) => {
    bodies.push(JSON.parse(options.body))
    return sseResponse([{ type: 'token', value: 'hi' }, { type: 'done', conversation_id: 'c1' }])
  }
  const { streamQueryFromAssistant } = await import('../src/api/chatApi.js')
  await withFetch(stub, async () => {
    await streamQueryFromAssistant('add task buy milk', null, { requestId: 'req-abc-12345678' })
    await streamQueryFromAssistant('hello', null)
  })
  assert.ok(browserZone && browserZone.length > 0)
  assert.equal(bodies[0].tz, browserZone)
  assert.equal(bodies[0].request_id, 'req-abc-12345678')
  assert.equal(bodies[1].tz, browserZone)
  assert.equal('request_id' in bodies[1], false, 'no id is invented when the caller gives none')
})

test('the non-streaming chat request also sends the timezone', async () => {
  const bodies = []
  const stub = async (url, options) => {
    bodies.push(JSON.parse(options.body))
    return { ok: true, status: 200, json: async () => ({ response: 'ok', conversation_id: 'c1' }) }
  }
  const { sendQueryToAssistant } = await import('../src/api/chatApi.js')
  await withFetch(stub, () => sendQueryToAssistant('hello', null))
  assert.equal(bodies[0].tz, browserZone)
})

test('a stream error after a committed change is reported as saved, without a Retry', async () => {
  const stub = async () =>
    sseResponse(
      [
        { type: 'committed', skill_used: 'add_task', count: 1 },
        { type: 'token', value: "Done! Added task 'Buy milk'" },
      ],
      { failAfter: true }
    )
  const { streamQueryFromAssistant } = await import('../src/api/chatApi.js')
  const { failureMessage } = await import('../src/utils/chatRequest.js')
  let caught = null
  await withFetch(stub, () =>
    streamQueryFromAssistant('add task buy milk', null, {
      requestId: 'req-saved-1234',
      onError: (err) => {
        caught = err
      },
    })
  )
  assert.equal(caught.message, 'network error')
  assert.deepEqual(caught.committed, { skill_used: 'add_task', count: 1 })

  const msg = failureMessage({
    err: caught,
    partialText: caught.partialResponse,
    prompt: 'add task buy milk',
    specialistId: null,
    requestId: 'req-saved-1234',
    thought: null,
    fallbackError: 'x',
  })
  assert.match(msg.savedNotice, /saved/)
  assert.equal(msg.error, undefined)
  assert.equal(msg.canRetry, undefined)
  assert.equal(msg.text, "Done! Added task 'Buy milk'")
})

test('a stream error before any commit keeps Retry and reuses the same request id', async () => {
  const stub = async () => sseResponse([{ type: 'token', value: 'partial' }], { failAfter: true })
  const { streamQueryFromAssistant } = await import('../src/api/chatApi.js')
  const { failureMessage } = await import('../src/utils/chatRequest.js')
  let caught = null
  await withFetch(stub, () =>
    streamQueryFromAssistant('add task x', null, {
      requestId: 'req-retry-9999',
      onError: (err) => {
        caught = err
      },
    })
  )
  assert.equal(caught.committed, undefined)
  const msg = failureMessage({
    err: caught,
    partialText: 'partial',
    prompt: 'add task x',
    specialistId: null,
    requestId: 'req-retry-9999',
    thought: null,
    fallbackError: 'x',
  })
  assert.equal(msg.canRetry, true)
  assert.equal(msg.retryRequestId, 'req-retry-9999')
  assert.equal(msg.retryPrompt, 'add task x')
  assert.equal(msg.retrySpecialistId, null)
  assert.equal(msg.error, 'network error')
})

test('ChatPanel keeps one request id per send, reuses it on Retry and refreshes tasks after a saved change', () => {
  const panel = read('../src/components/ChatPanel.jsx')
  assert.ok(panel.includes('extraMeta?.requestId || makeRequestId()'))
  assert.ok(panel.includes('requestId: clientRequestId'))
  assert.ok(panel.includes('{ requestId: retryRequestId }'))
  assert.ok(panel.includes('err?.committed && onChatComplete'))
  const list = read('../src/components/chat/ChatMessageList.jsx')
  assert.ok(list.includes('msg.retryRequestId'))
  assert.ok(list.includes('msg.savedNotice'))
})

test('makeRequestId returns distinct ids the server accepts', async () => {
  const { makeRequestId } = await import('../src/utils/chatRequest.js')
  const ids = new Set(Array.from({ length: 50 }, () => makeRequestId()))
  assert.equal(ids.size, 50)
  for (const id of ids) assert.match(id, /^[A-Za-z0-9_-]{8,64}$/)
})

async function loadRenderCard() {
  const bundle = await rolldown({
    input: path.resolve(__dirname, 'fixtures/intakeCardEntry.jsx'),
    platform: 'node',
    transform: { jsx: { runtime: 'automatic' } },
    logLevel: 'silent',
  })
  const { output } = await bundle.generate({ format: 'esm' })
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'compass-card-'))
  const file = path.join(dir, 'card.mjs')
  fs.writeFileSync(file, output[0].code)
  try {
    return (await import(pathToFileURL(file).href)).renderCard
  } finally {
    fs.rmSync(dir, { recursive: true, force: true })
  }
}

test('the preview card lists every task with its due time and offers Add all / Cancel', async () => {
  const renderCard = await loadRenderCard()
  const html = renderCard({
    action: 'add_tasks',
    count: 3,
    items: [
      {
        title: 'Record demo video',
        domain: 'hackathon',
        priority: 'high',
        duration_minutes: 240,
        due_label: 'Thu Oct 29, 9:00 PM (Asia/Calcutta)',
      },
      { title: 'DBMS assignment 3', domain: 'coursework', priority: 'medium', duration_minutes: 120, due_label: 'Fri Oct 30' },
      {
        title: 'Read paper',
        domain: 'general',
        priority: 'medium',
        duration_minutes: null,
        due_label: 'no due date',
        due_unparsed: 'whenever',
      },
    ],
  })
  assert.match(html, /3 tasks are ready to add/)
  assert.match(html, /Nothing is saved until you confirm/)
  for (const title of ['Record demo video', 'DBMS assignment 3', 'Read paper']) assert.ok(html.includes(title))
  assert.ok(html.includes('Thu Oct 29, 9:00 PM (Asia/Calcutta)'))
  assert.ok(html.includes('hackathon · high · 4h'))
  assert.ok(html.includes('could not read &quot;whenever&quot;'))
  assert.match(html, /id="btn-intake-confirm"[^>]*>Add all[^<]*3/)
  assert.match(html, /id="btn-intake-cancel"/)
})

test('ChatMessageList shows the preview card for add_tasks and not the destructive-action card', () => {
  const list = read('../src/components/chat/ChatMessageList.jsx')
  assert.ok(list.includes("pendingKind === 'add_tasks'"))
  assert.ok(list.includes("pendingKind !== 'add_tasks'"))
  assert.ok(list.includes('<IntakePreviewCard'))
})
