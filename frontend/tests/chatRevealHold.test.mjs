import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'

const read = rel => fs.readFileSync(new URL(rel, import.meta.url), 'utf8')
const panel = read('../src/components/ChatPanel.jsx')
const list = read('../src/components/chat/ChatMessageList.jsx')
const hook = read('../src/hooks/useRevealHold.js')
const messages = read('../src/utils/chatMessages.js')

test('ChatPanel holds the streaming bubble briefly after the answer arrives', () => {
  assert.ok(panel.includes('useRevealHold(activeRequestIdRef)'))
  assert.ok(panel.includes('holdFinal(requestId, finish)'))
  assert.ok(panel.includes('streamDone={streamDone}'))
  assert.ok(panel.includes('onRevealDone={flushPendingFinal}'))
})

test('the hold is bounded and drops a finish for a request that is no longer active', () => {
  const ms = Number(hook.match(/REVEAL_HOLD_MAX_MS = (\d+)/)[1])
  assert.ok(ms <= 2500)
  assert.match(hook, /setTimeout\(flushPendingFinal, REVEAL_HOLD_MAX_MS\)/)
  assert.match(hook, /pending\.requestId === activeRequestIdRef\.current/)
})

test('the hold is cancelled by new chat, switching chat and unmount', () => {
  const newChat = panel.slice(panel.indexOf('const handleNewChat'), panel.indexOf('const handleSelectPastChat'))
  assert.ok(newChat.includes('cancelRevealHold()'))
  const selectChat = panel.slice(panel.indexOf('const handleSelectPastChat'))
  assert.ok(selectChat.slice(0, 900).includes('cancelRevealHold()'))
  assert.match(hook, /useEffect\(\(\) => \(\) => \{\s*clearTimer\(\)/)
})

test('conversation id and parent refresh stay outside the deferred finish', () => {
  const complete = panel.slice(panel.indexOf('onComplete: async'), panel.indexOf('onError: async'))
  const finishStart = complete.indexOf('const finish = () => {')
  const finishEnd = complete.indexOf('// Keep the conversation id')
  const finishBody = complete.slice(finishStart, finishEnd)
  assert.ok(!finishBody.includes('setConversationId'))
  assert.ok(!finishBody.includes('onChatComplete'))
  assert.ok(complete.indexOf('setConversationId(doneData.conversation_id)') > finishEnd)
})

test('error and abort paths still end streaming immediately and never hold', () => {
  const rest = panel.slice(panel.indexOf('onError: async'))
  const hits = rest.match(/setIsStreaming\(false\)/g) || []
  assert.ok(hits.length >= 3, `only ${hits.length} direct setIsStreaming(false) calls remain`)
  assert.ok(!rest.slice(0, 3000).includes('holdFinal'))
})

test('ChatMessageList reports when the eased-in text has caught up and follows the tail', () => {
  assert.ok(list.includes('smoothStreamingText.length >= (streamingText'))
  assert.ok(list.includes('onRevealDoneRef.current?.()'))
  assert.match(list, /isStreaming && streamDone && revealCaughtUp/)
  assert.ok(list.includes("scrollIntoView({ block: 'end' })"))
})

test('message helpers: continue extends the same bubble, new answers carry their data', async () => {
  const { mergeContinuation, buildAssistantMessage } = await import('../src/utils/chatMessages.js')
  const prev = [{ id: 7, role: 'assistant', text: 'Hello' }]
  const merged = mergeContinuation(prev, 7, 'Hello world', { is_truncated: false })
  assert.equal(merged.length, 1)
  assert.equal(merged[0].text, 'Hello world')
  const appended = mergeContinuation(prev, 7, 'more', {})
  assert.equal(appended[0].text, 'Hello\nmore')
  const msg = buildAssistantMessage('Hi', 'thinking', { is_truncated: true, tasks: [1] })
  assert.equal(msg.role, 'assistant')
  assert.equal(msg.text, 'Hi')
  assert.equal(msg.thought, 'thinking')
  assert.equal(msg.isTruncated, true)
  assert.deepEqual(msg.tasks, [1])
  assert.ok(messages.includes('export function mergeContinuation'))
})
