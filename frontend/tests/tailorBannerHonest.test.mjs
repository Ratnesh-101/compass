import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'

test('handleTriggerTailor checks verification status before claiming validation', () => {
  const fileUrl = new URL('../src/components/career/ApplicationWorkspaceModal.jsx', import.meta.url)
  const source = fs.readFileSync(fileUrl, 'utf8')

  const startIndex = source.indexOf('const handleTriggerTailor')
  assert.ok(startIndex !== -1, 'expected to find const handleTriggerTailor in source')

  const endIndex = source.indexOf('const handleSaveResumeEdits', startIndex)
  assert.ok(endIndex !== -1, 'expected to find const handleSaveResumeEdits after handleTriggerTailor')

  const slice = source.slice(startIndex, endIndex)

  assert.ok(
    slice.includes('NOT ENOUGH DATA'),
    "expected handleTriggerTailor slice to contain 'NOT ENOUGH DATA'"
  )
  assert.ok(
    slice.includes('Add more details to your master profile to enable verification'),
    "expected handleTriggerTailor slice to contain 'Add more details to your master profile to enable verification'"
  )
  assert.ok(
    slice.includes('validated against your master profile'),
    "expected handleTriggerTailor slice to contain 'validated against your master profile'"
  )
})
