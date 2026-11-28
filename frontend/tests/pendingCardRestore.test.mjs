import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const src = readFileSync(new URL('../src/api/chatApi.js', import.meta.url), 'utf8')
const list = readFileSync(new URL('../src/components/chat/ChatMessageList.jsx', import.meta.url), 'utf8')

function loadHelper() {
  const m = src.match(/export function attachPendingAction[\s\S]*?\n}\n/)
  assert.ok(m, 'attachPendingAction exported')
  return new Function(`${m[0].replace('export ', '')}; return attachPendingAction`)()
}

test('loader applies pending_action from the response', () => {
  assert.match(src, /attachPendingAction\(mapped, data\.pending_action\)/)
})

test('card reads pending_action from the message and confirm sends Confirm', () => {
  assert.match(list, /msg\.data\?\.pending_action \|\| msg\.pending_action/)
  assert.match(list, /onSendMessage\("Confirm"\)/)
  assert.match(list, /onSendMessage\("Cancel"\)/)
})

test('attaches to the last assistant message only', () => {
  const attach = loadHelper()
  const pa = { id: 1, action: 'add_tasks', items: [{ title: 'x' }] }
  const msgs = [{ role: 'assistant', text: 'a' }, { role: 'user', text: 'u' }, { role: 'assistant', text: 'b' }]
  const out = attach(msgs, pa)
  assert.equal(out[2].pending_action, pa)
  assert.equal(out[2].data.pending_action, pa)
  assert.equal(out[0].pending_action, undefined)
})

test('no pending action leaves messages unchanged', () => {
  const attach = loadHelper()
  const msgs = [{ role: 'assistant', text: 'a' }]
  assert.equal(attach(msgs, null), msgs)
  assert.equal(attach(msgs, undefined), msgs)
  assert.deepEqual(attach([{ role: 'user', text: 'u' }], { id: 1 }), [{ role: 'user', text: 'u' }])
})
