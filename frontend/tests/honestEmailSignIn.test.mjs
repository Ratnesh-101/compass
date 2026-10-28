import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'

const authModal = fs.readFileSync(new URL('../src/components/AuthModal.jsx', import.meta.url), 'utf8')
const app = fs.readFileSync(new URL('../src/App.jsx', import.meta.url), 'utf8')

test('quick-connect failure shows an error and does not fake a sign-in', () => {
  const start = authModal.indexOf('await quickConnectUser')
  assert.ok(start > -1, 'handleQuickLogin must call quickConnectUser')
  const afterCall = authModal.slice(start)
  const catchBlock = afterCall.slice(afterCall.indexOf('catch'), afterCall.indexOf('finally'))
  assert.ok(catchBlock.length > 0)
  assert.ok(catchBlock.includes('Email sign-in is not available on this server. Please sign in with Google instead.'))
  assert.ok(!catchBlock.includes('setCurrentUserId'))
  assert.ok(!catchBlock.includes('onUserChanged'))
  assert.ok(!catchBlock.includes('Switched local identity'))
})

test('App never fabricates an authenticated user from a saved local email', () => {
  assert.ok(!app.includes('savedEmail'))
  assert.ok(!app.includes("localStorage.getItem('compass_user_email')"))
  assert.ok(app.includes('useState(null)'))
})

test('handleUserChanged never fabricates a signed-in user', () => {
  assert.ok(!app.includes('is_simulated: true'))
  const start = app.indexOf('const handleUserChanged')
  assert.ok(start > -1, 'handleUserChanged must exist in App.jsx')
  const nextConst = app.indexOf('\n  const ', start + 1)
  assert.ok(nextConst > -1, 'next const declaration after handleUserChanged must exist')
  const slice = app.slice(start, nextConst)
  assert.ok(slice.includes('setCurrentUser(null)'))
})
