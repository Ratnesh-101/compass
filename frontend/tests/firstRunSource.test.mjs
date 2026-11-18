import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'

const read = (p) => fs.readFileSync(new URL(`../src/${p}`, import.meta.url), 'utf8').split('\r\n').join('\n')
const app = read('App.jsx')
const dashboard = read('components/Dashboard.jsx')
const timeline = read('components/Timeline.jsx')
const authModal = read('components/AuthModal.jsx')
const migration = read('components/MigrationModal.jsx')
const migrationApi = read('api/migrationApi.js')
const calendarView = read('components/CalendarView.jsx')
const css = read('index.css')

function between(source, startMarker, endMarker) {
  const start = source.indexOf(startMarker)
  assert.ok(start > -1, `missing ${startMarker}`)
  const end = source.indexOf(endMarker, start + startMarker.length)
  assert.ok(end > -1, `missing ${endMarker}`)
  return source.slice(start, end)
}

test('seeding UI is gone from Dashboard, Timeline and the About modal (demo seeding is off in production)', () => {
  for (const [name, src] of [['Dashboard', dashboard], ['Timeline', timeline], ['AboutJudgesModal', read('components/AboutJudgesModal.jsx')]]) {
    assert.ok(!src.includes('handleSeedJudgePersona'), `${name} must not seed`)
    assert.ok(!src.includes('seedJudgeDemoPersona'), `${name} must not call the seed API`)
    assert.ok(!src.includes('ExamplePersonaModal'), `${name} must not open the example dialog`)
    assert.ok(!src.includes('See an example'), `${name} must not offer "See an example"`)
  }
  assert.ok(!read('api/chatApi.js').includes('/api/demo/seed-persona'))
  assert.ok(!app.includes('compass:demo-persona-loaded'))
})

test('health offline->online transition re-runs the one-shot user and demo checks', () => {
  const block = between(app, 'const applyBackendStatus', 'const handleRetryConnection')
  assert.ok(block.includes('!isBackendOnline(prev) && isBackendOnline(status)'))
  assert.ok(block.includes('runUserCheck()'))
  assert.ok(block.includes('checkDemoStatus()'))
  assert.ok(block.includes('checkMigration()'))
})

test('stored identity is only cleared on an explicit unauthenticated answer', () => {
  const block = between(app, 'const runUserCheck', 'const handleUserChanged')
  assert.ok(block.includes('identityActionFor(status)'))
  assert.ok(block.includes("action === 'clear'"))
  assert.ok(!app.includes("fetchCurrentUser()"), 'legacy null-means-signed-out call must be gone')
})

test('handleUserChanged resets per-identity state and re-checks demo status', () => {
  const block = between(app, 'const handleUserChanged', 'handleUserChangedRef')
  for (const needle of [
    'setMessages(INITIAL_MESSAGES)', 'setConversationId(null)', 'setPendingPrompt(null)',
    'setAllTasks([])', 'setIsDemoActive(false)', 'checkDemoStatus()', 'setCurrentUser(null)',
  ]) {
    assert.ok(block.includes(needle), needle)
  }
})

test('OAuth return is handled once in App, confirmed by the server, and the URL is cleaned', () => {
  assert.ok(app.includes('parseOAuthReturn(window.location.search)'))
  assert.ok(app.includes('stripOAuthParams('))
  assert.ok(app.includes('history.replaceState'))
  const block = between(app, 'parseOAuthReturn(window.location.search)', "}, [])")
  assert.ok(block.indexOf("handleUserChangedRef.current('oauth')") < block.indexOf('Signed in as'))
  assert.ok(!/get\(['"]email['"]\)/.test(app), 'email query param must never be read in App')
  assert.ok(!/get\(['"]email['"]\)/.test(calendarView), 'CalendarView must not trust ?email=')
})

test('mobile shell uses 100dvh with a 100vh fallback declared first', () => {
  assert.ok(app.includes('className="app-shell"'))
  assert.ok(!app.includes("height: '100vh'"))
  assert.match(css, /\.app-shell\s*\{\s*height: 100vh;\s*height: 100dvh;/)
  assert.match(css, /height: calc\(100vh - 58px - env\(safe-area-inset-bottom, 0px\)\) !important;\s*height: calc\(100dvh - 58px - env\(safe-area-inset-bottom, 0px\)\) !important;/)
  assert.match(css, /#root \{[^}]*height: 100vh;\s*height: 100dvh;/)
})

test('migration success view is reachable: import handlers no longer close it, Done completes', () => {
  const all = between(migration, 'const handleImportAll', 'const handleImportSelected')
  assert.ok(!all.includes('onMigrationComplete'))
  const sel = between(migration, 'const handleImportSelected', 'if (!isOpen) return null')
  assert.ok(!sel.includes('onMigrationComplete'))
  const done = between(migration, 'const handleDone', 'const handleSkip')
  assert.ok(done.includes('onMigrationComplete'))
  assert.ok(migration.includes('onClick={handleDone}'))
  assert.match(migration, />\s*Done\s*</)
  assert.ok(between(migration, 'const handleSkip', 'skipMigration()').includes("view === 'success'"))
})

test('network calls that used to spin forever now use a timeout', () => {
  assert.ok(migrationApi.includes('fetchWithTimeout('))
  assert.ok(read('api/calendarApi.js').includes('fetchWithTimeout('))
  assert.ok(read('api/baseClient.js').includes('export async function fetchWithTimeout'))
})

test('active tab and lazy CareerCopilot are wrapped in a resettable TabErrorBoundary', () => {
  const boundaries = app.match(/<TabErrorBoundary/g) || []
  assert.ok(boundaries.length >= 2)
  assert.ok(app.indexOf('<TabErrorBoundary') < app.indexOf("activeTab === 'dashboard' ? ("))
  assert.match(app, /<TabErrorBoundary resetKey=\{activeTab\} onRetry=[^\n]*\n\s*<React\.Suspense/)
  const tab = read('components/TabErrorBoundary.jsx')
  assert.ok(tab.includes('Try again'))
  assert.ok(tab.includes('handleRetry'))
  assert.ok(!tab.includes('error.message'))
  assert.ok(!tab.includes('state.error'))
})

test('email sign-in form is hidden unless enabled and Google leads', () => {
  assert.ok(authModal.includes('isEmailSignInEnabled(import.meta.env)'))
  const gate = authModal.indexOf('{emailSignInEnabled && (')
  assert.ok(gate > -1)
  assert.ok(gate < authModal.indexOf('Instant Sign-In (Select or Enter Email)'))
  assert.ok(gate < authModal.indexOf('Sign In →'))
  assert.ok(authModal.indexOf('Sign in with Google') < gate)
  assert.ok(!authModal.includes("{activeEmail ? 'Isolated Memory Active'"))
})
