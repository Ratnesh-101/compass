import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'

test('ChatMessageList contains delete_task_disambiguation, updated heading, and keeps default heading', () => {
  const fileUrl = new URL('../src/components/chat/ChatMessageList.jsx', import.meta.url)
  const source = fs.readFileSync(fileUrl, 'utf8')

  assert.ok(
    source.includes('delete_task_disambiguation'),
    'expected ChatMessageList.jsx to contain delete_task_disambiguation'
  )
  assert.ok(
    source.includes('Choose a task to delete:'),
    'expected ChatMessageList.jsx to contain Choose a task to delete:'
  )
  assert.ok(
    source.includes('Confirm destructive action:'),
    'expected ChatMessageList.jsx to still contain Confirm destructive action:'
  )
})

test('Confirm button in pending action card is conditional on kind', () => {
  const fileUrl = new URL('../src/components/chat/ChatMessageList.jsx', import.meta.url)
  const source = fs.readFileSync(fileUrl, 'utf8')

  const cardStart = source.indexOf('chat-pending-action-card')
  assert.ok(cardStart !== -1, 'expected to find chat-pending-action-card')

  const cardEnd = source.indexOf('btn-pending-cancel', cardStart)
  assert.ok(cardEnd !== -1, 'expected to find btn-pending-cancel after card start')

  const cardSlice = source.slice(cardStart, cardEnd)
  const confirmIndex = cardSlice.indexOf('Confirm')
  assert.ok(confirmIndex !== -1, 'expected to find Confirm button label in card slice')

  const sliceBeforeConfirm = cardSlice.slice(0, confirmIndex)
  assert.ok(
    sliceBeforeConfirm.includes('delete_task_disambiguation'),
    'expected card slice before Confirm button label to reference delete_task_disambiguation'
  )
})
