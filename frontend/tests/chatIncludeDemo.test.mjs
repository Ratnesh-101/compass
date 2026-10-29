import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))

function stubChatFetch(captured) {
  return async (url, options = {}) => {
    if (String(url).includes('/api/chat')) captured.push(JSON.parse(options.body))
    return { ok: true, status: 200, json: async () => ({ response: 'ok', conversation_id: 'c1' }), body: null }
  }
}

test('chat requests omit include_demo until the demo workspace is visible', async () => {
  const originalFetch = globalThis.fetch
  const captured = []
  globalThis.fetch = stubChatFetch(captured)
  try {
    const { sendQueryToAssistant, setChatIncludeDemo } = await import('../src/api/chatApi.js')

    setChatIncludeDemo(false)
    await sendQueryToAssistant('how many tasks do I have?', null)
    assert.equal('include_demo' in captured[0], false, 'default chat request must not ask for demo rows')

    setChatIncludeDemo(true)
    await sendQueryToAssistant('how many tasks do I have?', null)
    assert.equal(captured[1].include_demo, true, 'visible demo workspace must be sent with chat requests')

    setChatIncludeDemo(false)
    await sendQueryToAssistant('how many tasks do I have?', null)
    assert.equal('include_demo' in captured[2], false, 'after Reset demo the flag goes away again')
  } finally {
    globalThis.fetch = originalFetch
  }
})

test('App.jsx keeps the chat flag in sync with isDemoActive', () => {
  const source = fs.readFileSync(path.resolve(__dirname, '../src/App.jsx'), 'utf8')
  assert.ok(source.includes('setChatIncludeDemo(isDemoActive)'))
  assert.ok(source.includes('setChatIncludeDemo }') || source.includes('setChatIncludeDemo,'))
})
