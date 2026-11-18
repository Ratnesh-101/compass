import { test } from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import { runStatusLabel } from '../src/components/agent/runStatus.js'
import { formatActionDescription } from '../src/components/agent/actionText.js'
import { formatObserveContent } from '../src/components/agent/observeText.js'

const read = (p) => fs.readFileSync(new URL(p, import.meta.url), 'utf8')

test('header says waiting, not all done, while approvals are pending', () => {
  assert.equal(runStatusLabel(false, [{ tool: 'add_task' }]), 'Waiting for your approval')
  assert.equal(runStatusLabel(false, []), 'All done')
  assert.equal(runStatusLabel(true, [{ tool: 'add_task' }]), 'Working on it…')
})

test('AgentPanel header uses runStatusLabel and has no hard-coded All done', () => {
  const src = read('../src/components/AgentPanel.jsx')
  assert.match(src, /runStatusLabel\(isRunning, pendingActions\)/)
  assert.doesNotMatch(src, /All done/)
})

test('add_task and edit_task descriptions include the due date and weekday', () => {
  const add = formatActionDescription({ tool: 'add_task', args: { title: 'x', domain: 'code', due_date: '2026-11-20' } })
  assert.match(add, /due Fri 2026-11-20/)
  const edit = formatActionDescription({ tool: 'edit_task', args: { title: 'x', due_date: '2026-11-20T10:00:00' } })
  assert.match(edit, /2026-11-20/)
  assert.doesNotMatch(formatActionDescription({ tool: 'add_task', args: { title: 'x' } }), /due/)
})

test('ConfirmationGate still exports formatActionDescription from the shared helper', () => {
  const src = read('../src/components/agent/ConfirmationGate.jsx')
  assert.match(src, /export \{ formatActionDescription \}/)
})

test('observe step with raw JSON shows one plain line and never user_id', () => {
  const raw = JSON.stringify({ count: 2, user_id: 'guest_abc123', owner: 'guest_abc123', include_demo: false })
  const out = formatObserveContent(raw)
  assert.doesNotMatch(out, /[{}"]/)
  assert.doesNotMatch(out, /user_id|guest_abc123|include_demo|owner/)
  const withResponse = formatObserveContent(JSON.stringify({ response: 'Found 3 deadlines', user_id: 'u1' }))
  assert.equal(withResponse, 'Found 3 deadlines')
  assert.equal(formatObserveContent('Deadline is Friday.'), 'Deadline is Friday.')
})

test('StepCard routes observe content through formatObserveContent', () => {
  assert.match(read('../src/components/agent/StepCard.jsx'), /formatObserveContent\(step\.content\)/)
})
