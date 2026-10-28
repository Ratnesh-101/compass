import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const dir = path.dirname(fileURLToPath(import.meta.url))
const root = process.env.CHAT_SAFETY_SRC_ROOT || path.resolve(dir, '../src/components')
const read = (p) => fs.readFileSync(path.resolve(root, p), 'utf8')

test('EvidenceCard sanitizes source URLs through getSafeHttpUrl', () => {
  const s = read('chat/EvidenceCard.jsx')
  assert.match(s, /import \{ getSafeHttpUrl \} from '..\/..\/utils\/safeUrl/)
  assert.match(s, /const sUrl = getSafeHttpUrl\(item\.source_url \|\| item\.url\)/)
})

test('ChatInputBar passes specialist id as the third onSend argument', () => {
  const s = read('chat/ChatInputBar.jsx')
  assert.match(s, /onSend\(input\.trim\(\), null, activeSpecialist \? activeSpecialist\.id : null\)/)
})

test('new chat and past chat selection invalidate the in-flight request', () => {
  const s = read('ChatPanel.jsx')
  for (const name of ['const handleNewChat', 'const handleSelectPastChat']) {
    const start = s.indexOf(name)
    assert.ok(start !== -1)
    assert.match(s.slice(start, start + 400), /activeRequestIdRef\.current \+= 1/, name)
  }
  assert.match(s, /onComplete: async \(doneData\) => \{\s*if \(requestId !== activeRequestIdRef\.current\) return/)
})

test('pending-action card renders only for the latest non-streaming message', () => {
  const s = read('chat/ChatMessageList.jsx')
  assert.match(s, /pending_action\) && isLatest && !isStreaming/)
})

test('retry keeps the specialist of the failed message', () => {
  const p = read('ChatPanel.jsx')
  assert.match(p, /retrySpecialistId: specialistIdToUse/)
  assert.match(p, /handleSend\(retryPrompt, null, retrySpecialistId, true\)/)
  assert.match(read('chat/ChatMessageList.jsx'), /onRetry\(idx, msg\.retryPrompt, msg\.retrySpecialistId\)/)
})
