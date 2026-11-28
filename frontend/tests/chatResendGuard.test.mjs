import test from 'node:test'
import assert from 'node:assert/strict'
import { shouldAutoResend } from '../src/utils/autoResend.js'

test('a plain transient failure may be re-sent once', () => {
  assert.equal(shouldAutoResend({}), true)
  assert.equal(shouldAutoResend(undefined), true)
})

test('no second automatic resend', () => {
  assert.equal(shouldAutoResend({ autoRetried: true }), false)
})

test('a committed change is never re-sent', () => {
  assert.equal(shouldAutoResend({ committed: true }), false)
})

test('skipped once a done event has been seen', () => {
  assert.equal(shouldAutoResend({ doneSeen: true }), false)
})

test('skipped once a pending_action card has been seen', () => {
  assert.equal(shouldAutoResend({ pendingActionSeen: true }), false)
  assert.equal(shouldAutoResend({ doneSeen: true, pendingActionSeen: true }), false)
})

test('an aborted request is not re-sent', () => {
  assert.equal(shouldAutoResend({ aborted: true }), false)
})
