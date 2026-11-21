import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const src = readFileSync(
  new URL('../src/components/career/ApplicationWorkspaceModal.jsx', import.meta.url),
  'utf8',
).replace(/\r\n/g, '\n')

function functionBody(name) {
  const start = src.search(new RegExp(`const\\s+${name}\\s*=\\s*async`))
  assert.ok(start >= 0, `${name} not found`)
  const next = src.slice(start + 10).search(/\n {2}(?:const|\/\/)\s/)
  return src.slice(start, next < 0 ? undefined : start + 10 + next)
}

test('mark-applied saves notes and deadline before calling markApplied', () => {
  const body = functionBody('handleMarkAppliedRecord')
  const patch = body.search(/updateApplication\(\s*application\.id/)
  const mark = body.search(/markApplied\(\s*application\.id/)
  assert.ok(patch >= 0, 'no notes/deadline update')
  assert.ok(mark > patch, 'markApplied must come after the update')
  const patchCall = body.slice(patch, mark)
  assert.match(patchCall, /private_notes:\s*privateNotes/)
  assert.match(patchCall, /buildDeadlinePayload\(\s*targetDeadline\s*\)/)
  assert.doesNotMatch(patchCall, /status\s*:/)
})

test('draft is cleared only after markApplied succeeds', () => {
  const body = functionBody('handleMarkAppliedRecord')
  assert.ok(body.search(/clearWorkspaceDraft/) > body.search(/markApplied\(\s*application\.id/))
})

test('state is re-synced from the returned application', () => {
  for (const name of ['handleMarkAppliedRecord', 'handleUpdateApplicationRecord']) {
    const body = functionBody(name)
    assert.match(body, /setPrivateNotes\(\s*updated\.private_notes/, `${name} notes`)
    assert.match(body, /setTargetDeadline\(\s*updated\.target_deadline/, `${name} deadline`)
  }
})

test('external submission uses the mark-applied path', () => {
  const body = functionBody('handleConfirmExternalSubmission')
  assert.match(body, /handleMarkAppliedRecord\(\s*\)/)
  assert.doesNotMatch(body, /handleUpdateApplicationRecord\(\s*['"]submitted['"]\s*\)/)
  assert.match(body, /submittedExternally:\s*true/)
})
