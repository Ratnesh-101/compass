import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const read = (rel) => readFileSync(new URL(rel, import.meta.url), 'utf8')
const listSrc = read('../src/components/chat/ChatMessageList.jsx')

function headerRegion() {
  const start = listSrc.indexOf('chat-pending-action-card')
  const end = listSrc.indexOf('btn-pending-confirm', start)
  assert.ok(start >= 0 && end > start, 'pending card region not found')
  return listSrc.slice(start, end)
}

const headerFor = (region, kind, label) => {
  // The kind must be tested before its label appears (ternary chain), whatever the exact syntax.
  const k = region.indexOf(`'${kind}'`)
  const l = region.indexOf(label, k)
  assert.ok(k >= 0 && l > k, `no '${label}' header for ${kind}`)
}

test('each pending action kind has its own confirm header', () => {
  const region = headerRegion()
  headerFor(region, 'complete_task', 'Confirm mark as done')
  headerFor(region, 'reschedule_task', 'Confirm new due date or time')
  headerFor(region, 'update_preferences', 'Confirm new planning preferences')
  headerFor(region, 'add_to_watchlist', 'Confirm add to watchlist')
  headerFor(region, 'delete_chat', 'Confirm delete chat')
  headerFor(region, 'delete_task', 'Confirm delete task')
})

test('"Confirm destructive action" is only reachable for delete kinds, or absent', () => {
  const region = headerRegion()
  const idx = region.indexOf('Confirm destructive action')
  if (idx === -1) return
  const before = region.slice(0, idx)
  // Every non-delete kind must be matched by an earlier branch.
  for (const kind of ['complete_task', 'reschedule_task', 'update_preferences', 'add_to_watchlist']) {
    assert.ok(before.includes(`'${kind}'`), `${kind} would fall through to the destructive header`)
  }
  const tail = region.slice(Math.max(0, idx - 200), idx)
  assert.match(tail, /delete/, 'destructive wording is not tied to delete kinds')
})
