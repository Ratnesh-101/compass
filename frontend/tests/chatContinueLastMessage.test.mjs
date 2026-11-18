import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const read = (p) => readFileSync(new URL(p, import.meta.url), 'utf8')

test('Continue on a message without a database id asks the server to continue the latest answer', () => {
  const panel = read('../src/components/ChatPanel.jsx')
  const list = read('../src/components/chat/ChatMessageList.jsx')
  // A freshly streamed message has no id yet; without a fallback Continue would send a brand new question.
  assert.match(panel, /const targetId = msg\?\.id \|\| 'last'/)
  assert.match(panel, /continue_message_id: targetId/)
  assert.match(list, /continue_message_id: msg\.id \|\| 'last'/)
  assert.ok(!/continue_message_id: msg\?\.id,/.test(panel), 'the undefined id must not be sent')
})

test('the panel merges a continuation into the newest id-less assistant bubble', () => {
  const panel = read('../src/components/ChatPanel.jsx')
  assert.ok(panel.includes("(!m.id && m.role === 'assistant' && m === prev[prev.length - 1])"))
})

test('moving an application to Applied uses the confirmation endpoint, not a plain status update', () => {
  const center = read('../src/components/career/ApplicationCenter.jsx')
  const modal = read('../src/components/career/ApplicationWorkspaceModal.jsx')
  assert.ok(center.includes('markApplied'), 'Application Center imports and calls markApplied')
  assert.match(center, /step\.type === 'mark_applied'\s*\?\s*await markApplied\(app\.id\)/)
  assert.match(modal, /step\.type === 'mark_applied'\s*\?\s*await handleMarkAppliedRecord\(\)/)
  assert.ok(!center.includes("'SUBMITTED' : step.status"), 'the status shortcut is gone')
})

test('the radar overview grid has the class the phone CSS targets', () => {
  const cards = read('../src/components/radar/RadarOverviewCards.jsx')
  assert.ok(cards.includes('className="radar-overview-grid"'))
})
