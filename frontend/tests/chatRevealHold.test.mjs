import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'

const panel = fs.readFileSync(new URL('../src/components/ChatPanel.jsx', import.meta.url), 'utf8')
const list = fs.readFileSync(new URL('../src/components/chat/ChatMessageList.jsx', import.meta.url), 'utf8')

test('ChatPanel holds the streaming bubble briefly after the answer arrives', () => {
  assert.match(panel, /const REVEAL_HOLD_MAX_MS = \d+/)
  assert.ok(panel.includes('pendingFinalRef'))
  assert.ok(panel.includes('flushPendingFinal'))
  assert.ok(panel.includes('setTimeout(flushPendingFinal, REVEAL_HOLD_MAX_MS)'))
  assert.ok(panel.includes('streamDone={streamDone}'))
  assert.ok(panel.includes('onRevealDone={flushPendingFinal}'))
})

test('the hold is bounded and cancelled by new chat, switching chat and unmount', () => {
  const ms = Number(panel.match(/const REVEAL_HOLD_MAX_MS = (\d+)/)[1])
  assert.ok(ms <= 2500)
  assert.ok(panel.includes('const cancelRevealHold'))
  const newChat = panel.slice(panel.indexOf('const handleNewChat'), panel.indexOf('const handleSelectPastChat'))
  assert.ok(newChat.includes('cancelRevealHold()'))
  const selectChat = panel.slice(panel.indexOf('const handleSelectPastChat'))
  assert.ok(selectChat.slice(0, 900).includes('cancelRevealHold()'))
  assert.match(panel, /clearTimeout\(holdTimerRef\.current\)/)
})

test('the finished message is dropped when its request is no longer the active one', () => {
  assert.match(panel, /pending\.requestId === activeRequestIdRef\.current/)
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

test('error and abort paths still end streaming immediately', () => {
  const rest = panel.slice(panel.indexOf('onError: async'))
  const hits = rest.match(/setIsStreaming\(false\)/g) || []
  assert.ok(hits.length >= 3, `only ${hits.length} direct setIsStreaming(false) calls remain`)
  assert.ok(!rest.slice(0, 3000).includes('setStreamDone(true)'))
})

test('ChatMessageList reports when the eased-in text has caught up and follows the tail', () => {
  assert.ok(list.includes('smoothStreamingText.length >= (streamingText'))
  assert.ok(list.includes('onRevealDoneRef.current?.()'))
  assert.match(list, /isStreaming && streamDone && revealCaughtUp/)
  assert.ok(list.includes("scrollIntoView({ block: 'end' })"))
})
