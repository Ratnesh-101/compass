import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const read = (rel) => readFileSync(new URL(rel, import.meta.url), 'utf8')
const listSrc = read('../src/components/chat/ChatMessageList.jsx')
const timeSrc = read('../src/utils/localTime.js')

function headerRegion() {
  const start = listSrc.indexOf('chat-pending-action-card')
  const end = listSrc.indexOf('btn-pending-confirm', start)
  assert.ok(start >= 0 && end > start, 'pending card region not found')
  return listSrc.slice(start, end)
}

test('pending card header has wording for complete_task and reschedule_task', () => {
  const region = headerRegion()
  assert.match(region, /complete_task/, 'header does not branch on complete_task')
  assert.match(region, /reschedule_task/, 'header does not branch on reschedule_task')
})

test('complete_task and reschedule_task get their own headers', () => {
  const region = headerRegion()
  assert.match(region, /pendingKind === 'complete_task'\s*\?\s*'Confirm mark as done'/)
  assert.match(region, /pendingKind === 'reschedule_task'\s*\?\s*'Confirm new due date or time'/)
})

test('destructive wording still exists for delete', () => {
  assert.match(listSrc, /destructive|Confirm delete|delete/i)
  assert.match(listSrc, /destructive/i, 'no destructive wording left anywhere for delete')
})

test('Asia/Calcutta is shown as India Standard Time (IST)', async () => {
  assert.ok(timeSrc.includes('India Standard Time (IST)'), 'localTime.js has no "India Standard Time (IST)" label')
  const { friendlyTimeZone } = await import('../src/utils/localTime.js')
  assert.equal(friendlyTimeZone('Asia/Calcutta'), 'India Standard Time (IST)')
  assert.equal(friendlyTimeZone('Asia/Kolkata'), 'India Standard Time (IST)')
  assert.equal(friendlyTimeZone('Europe/Paris'), 'Europe/Paris')
})
