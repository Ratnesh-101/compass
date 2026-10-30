import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))

async function withFetch(stub, run) {
  const original = globalThis.fetch
  globalThis.fetch = stub
  try {
    return await run()
  } finally {
    globalThis.fetch = original
  }
}

test('Bug: sendQueryToAssistant omits request_id, disabling idempotency for non-streaming chat', async () => {
  const bodies = []
  const stub = async (url, options) => {
    bodies.push(JSON.parse(options.body))
    return { ok: true, status: 200, json: async () => ({ response: 'ok', conversation_id: 'c1' }) }
  }
  const { sendQueryToAssistant } = await import('../src/api/chatApi.js')
  await withFetch(stub, () => sendQueryToAssistant('add task buy milk tomorrow', null))

  assert.ok(bodies.length > 0, 'Request body was sent')
  assert.ok(
    bodies[0].request_id && typeof bodies[0].request_id === 'string',
    'sendQueryToAssistant must send a request_id for mutating chat commands'
  )
})

test('Bug: IntakePreviewCard Confirm button lacks disabled state, permitting double-click races', () => {
  const cardSrc = fs.readFileSync(path.resolve(__dirname, '../src/components/chat/IntakePreviewCard.jsx'), 'utf8')
  assert.match(
    cardSrc,
    /disabled=\{/,
    'IntakePreviewCard buttons must support disabled state to prevent rapid double-click dispatch'
  )
})
