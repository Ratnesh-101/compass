import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const src = readFileSync(join(here, '..', 'src', 'components', 'ChatPanel.jsx'), 'utf8')

function selectPastChatBody() {
  const start = src.indexOf('const handleSelectPastChat = async')
  assert.notEqual(start, -1, 'handleSelectPastChat not found')
  const end = src.indexOf('const showToast', start)
  assert.notEqual(end, -1, 'end of handleSelectPastChat not found')
  return src.slice(start, end)
}

test('handleSelectPastChat captures the request id it started with', () => {
  const body = selectPastChatBody()
  assert.match(body, /const loadRequestId = activeRequestIdRef\.current/)
})

test('a superseded past-chat load is dropped before it can overwrite messages', () => {
  const body = selectPastChatBody()
  const awaited = body.indexOf('await fetchConversationMessages')
  const stale = body.indexOf('loadRequestId !== activeRequestIdRef.current')
  const firstSet = body.indexOf('setMessages(', awaited)
  assert.ok(awaited !== -1 && stale !== -1 && firstSet !== -1)
  assert.ok(awaited < stale && stale < firstSet, 'staleness check must sit between the await and setMessages')
})

test('the captured id is defined before it is used', () => {
  const body = selectPastChatBody()
  assert.ok(body.indexOf('const loadRequestId') < body.indexOf('loadRequestId !== activeRequestIdRef.current'))
})
