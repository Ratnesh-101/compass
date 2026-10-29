import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { nextTabTarget, FOCUSABLE_SELECTOR, pushDialog, removeDialog, isTopDialog } from '../src/utils/dialogFocus.js'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const read = rel => fs.readFileSync(path.resolve(__dirname, '../src', rel), 'utf8')

test('nextTabTarget wraps forward from the last element to the first', () => {
  const items = ['a', 'b', 'c']
  assert.equal(nextTabTarget(items, 'c', false), 'a')
  assert.equal(nextTabTarget(items, 'a', false), null) // browser default moves inside
})

test('nextTabTarget wraps backward from the first element to the last', () => {
  const items = ['a', 'b', 'c']
  assert.equal(nextTabTarget(items, 'a', true), 'c')
  assert.equal(nextTabTarget(items, 'c', true), null)
})

test('nextTabTarget pulls focus back in when it escaped the dialog', () => {
  const items = ['a', 'b']
  assert.equal(nextTabTarget(items, 'outside', false), 'a')
  assert.equal(nextTabTarget(items, 'outside', true), 'b')
})

test('nextTabTarget with no focusable elements returns the sentinel to keep focus on the dialog', () => {
  assert.equal(nextTabTarget([], 'x', false), 'ROOT')
})

test('dialog stack only lets the most recently opened dialog react', () => {
  const first = {}
  const second = {}
  pushDialog(first)
  pushDialog(second)
  assert.equal(isTopDialog(first), false)
  assert.equal(isTopDialog(second), true)
  removeDialog(second)
  assert.equal(isTopDialog(first), true)
  removeDialog(first)
  assert.equal(isTopDialog(first), false)
})

test('FOCUSABLE_SELECTOR excludes disabled and negative-tabindex controls', () => {
  assert.match(FOCUSABLE_SELECTOR, /button:not\(\[disabled\]\)/)
  assert.match(FOCUSABLE_SELECTOR, /tabindex\]:not\(\[tabindex="-1"\]\)/)
})

test('Dialog component wires role, aria-modal, labelling, Escape, focus restore and inert background', () => {
  const src = read('components/Dialog.jsx')
  assert.match(src, /role="dialog"/)
  assert.match(src, /aria-modal="true"/)
  assert.match(src, /aria-labelledby/)
  assert.match(src, /key === 'Escape'/)
  assert.match(src, /'Tab'/)
  assert.match(src, /previouslyFocused/)
  assert.match(src, /\.focus\(/)
  assert.match(src, /inert/)
})

const MODALS = [
  'AuthModal.jsx',
  'MigrationModal.jsx',
  'NebiusTelemetryModal.jsx',
  'ShareModal.jsx',
  'calendar/CalendarModals.jsx',
  'career/ApplicationWorkspaceModal.jsx',
  'career/BatchApprovalModal.jsx',
  'career/CoverLetterModal.jsx',
  'career/ExternalProfileImportModal.jsx',
  'career/ExtractionReviewModal.jsx',
  'career/GitHubIntelligenceModal.jsx',
  'career/HandoffKitDrawer.jsx',
  'career/HandoffKitModal.jsx',
  'career/ResumeImportModal.jsx',
  'career/ReturnSubmissionPrompt.jsx',
  'chat/ChatHistoryDrawer.jsx',
  'radar/RadarDetailModal.jsx',
  'radar/RadarProfileModal.jsx',
  'timeline/AddDeadlineModal.jsx',
  'timeline/CreateDomainModal.jsx',
  'timeline/TaskDetailModal.jsx',
]

for (const rel of MODALS) {
  test(`${rel} renders its overlay through the shared Dialog`, () => {
    const src = read(`components/${rel}`)
    assert.match(src, /import Dialog from '[./]+\/(components\/)?Dialog'/)
    assert.match(src, /<Dialog[\s>]/)
    assert.equal((src.match(/<Dialog[\s>]/g) || []).length, (src.match(/<\/Dialog>/g) || []).length)
  })
}

test('CalendarModals wraps all three dialogs', () => {
  const src = read('components/calendar/CalendarModals.jsx')
  assert.equal((src.match(/<Dialog[\s>]/g) || []).length, 3)
})

test('modals no longer carry their own duplicate Escape listeners', () => {
  assert.doesNotMatch(read('components/radar/RadarProfileModal.jsx'), /e\.key === 'Escape'/)
  assert.doesNotMatch(read('components/MigrationModal.jsx'), /e\.key === 'Escape'/)
})
