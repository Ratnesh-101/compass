import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const chatPanelPath = path.resolve(__dirname, '../src/components/ChatPanel.jsx')

test('ChatPanel dead code cleanup: streamAssistantResponse removed, clearStreamTimer preserved, onSendMessage prop preserved on child', () => {
  const source = fs.readFileSync(chatPanelPath, 'utf8')

  // (a) the text streamAssistantResponse does not appear
  assert.equal(
    source.includes('streamAssistantResponse'),
    false,
    'streamAssistantResponse should not appear in ChatPanel.jsx'
  )

  // (b) clearStreamTimer still appears in both handleNewChat and handleSelectPastChat
  const handleNewChatIndex = source.indexOf('const handleNewChat')
  const handleSelectPastChatIndex = source.indexOf('const handleSelectPastChat')
  const showToastIndex = source.indexOf('const showToast')

  assert.ok(handleNewChatIndex !== -1, 'handleNewChat must exist')
  assert.ok(handleSelectPastChatIndex !== -1, 'handleSelectPastChat must exist')
  assert.ok(showToastIndex !== -1, 'showToast must exist')

  const handleNewChatBody = source.slice(handleNewChatIndex, handleSelectPastChatIndex)
  assert.ok(
    handleNewChatBody.includes('clearStreamTimer'),
    'clearStreamTimer must appear in handleNewChat'
  )

  const handleSelectPastChatBody = source.slice(handleSelectPastChatIndex, showToastIndex)
  assert.ok(
    handleSelectPastChatBody.includes('clearStreamTimer'),
    'clearStreamTimer must appear in handleSelectPastChat'
  )

  // (c) the child prop line onSendMessage={handleSend} is still present
  assert.ok(
    source.includes('onSendMessage={handleSend}'),
    'child prop line onSendMessage={handleSend} must still be present'
  )

  // onSendMessage prop is removed from component signature
  assert.equal(
    /export default function ChatPanel\([^)]*onSendMessage/.test(source),
    false,
    'onSendMessage must not be destructured in ChatPanel component signature'
  )
})
