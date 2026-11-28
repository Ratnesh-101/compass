import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import {
  friendlyLoadError,
  needsReplaceConfirm,
  draftDiffersFromSaved,
  OFFLINE_TEXT,
  SLOW_LOAD_MS,
  SLOW_LOAD_TEXT,
} from '../src/utils/careerLoadHonesty.js'
import { inspectDraftConflict } from '../src/utils/workspaceDraft.js'
import { planStageMove, CLOSED_REOPEN_MESSAGE } from '../src/utils/applicationStages.js'

const read = rel => readFileSync(new URL(rel, import.meta.url), 'utf8').replace(/\r\n/g, '\n')
const studio = read('../src/components/career/ResumeStudio.jsx')
const center = read('../src/components/career/ApplicationCenter.jsx')
const modal = read('../src/components/career/ApplicationWorkspaceModal.jsx')
const panel = read('../src/components/career/LoadErrorPanel.jsx')
const api = read('../src/api/careerApi.js')

test('api helpers throw on a non-ok response, and the save handler sets success only after the awaited request', () => {
  assert.match(api, /export async function updateResume[\s\S]*?if \(!res\.ok\) throw/)
  assert.match(api, /export async function updateMasterResume[\s\S]*?if \(!res\.ok\) throw/)
  const handler = studio.slice(studio.indexOf('const handleSaveResume'), studio.indexOf('const handleVerifyClaims') > 0 ? studio.indexOf('const handleVerifyClaims') : undefined)
  assert.ok(handler.indexOf('await updateResume(') !== -1)
  assert.ok(handler.indexOf('setSaveSuccess(true)') > handler.indexOf('await updateResume('))
  assert.ok(handler.indexOf('setSaveSuccess(true)') > handler.indexOf('await updateMasterResume('))
  assert.match(handler, /if \(!selectedResume\) return/)
})

test('Save is disabled when no resume is loaded, and a failed load shows the error panel instead of the editor', () => {
  assert.match(studio, /disabled=\{saving \|\| !selectedResume\}/)
  assert.match(studio, /if \(!loading && loadError && !selectedResume\)[\s\S]*?<LoadErrorPanel[^>]*onRetry=\{loadData\}/)
  assert.ok(studio.indexOf('<LoadErrorPanel') < studio.indexOf('Save Tailored Resume'))
})

test('error panel maps statuses and offline to friendly text, never raw statuses', () => {
  assert.equal(friendlyLoadError({ status: 500, message: 'Failed to fetch master resume: Internal Server Error' }, true), "Something went wrong on our side. Try again in a moment.")
  assert.equal(friendlyLoadError(new Error('Failed to fetch'), true), "We couldn't load your resume. Check your connection and try again.")
  assert.equal(friendlyLoadError(new Error('Failed to fetch'), false), OFFLINE_TEXT)
  assert.equal(OFFLINE_TEXT, 'You seem to be offline.')
  assert.match(friendlyLoadError({ status: 401 }, true), /session/i)
  for (const e of [{ status: 500 }, { status: 404 }, new Error('Failed to fetch')]) {
    assert.doesNotMatch(friendlyLoadError(e, true), /Internal Server Error|Failed to fetch|\b500\b/)
  }
  assert.match(panel, /navigator\.onLine/)
  assert.match(panel, /<button[\s\S]*?onClick=\{onRetry\}[\s\S]*?Retry/)
  assert.match(studio, /<LoadErrorPanel/)
  assert.match(center, /<LoadErrorPanel/)
})

test('Application Center shows a slow-load hint after 8 seconds and a retry panel on failure', () => {
  assert.equal(SLOW_LOAD_MS, 8000)
  assert.match(SLOW_LOAD_TEXT, /Still loading\.\.\. this can take a moment on the first visit/)
  assert.match(center, /setTimeout\(\(\) => setSlowLoad\(true\), SLOW_LOAD_MS\)/)
  assert.match(center, /if \(loadError\)[\s\S]*?onRetry=\{loadData\}/)
})

test('needsReplaceConfirm asks only when the editor text differs from the last saved text', () => {
  assert.equal(needsReplaceConfirm('my edit', 'saved'), true)
  assert.equal(needsReplaceConfirm('saved', 'saved'), false)
  assert.equal(needsReplaceConfirm('  saved ', 'saved'), false)
  assert.equal(needsReplaceConfirm('', 'saved'), false)
  assert.equal(needsReplaceConfirm('typed', ''), true)
})

test('Generate with AI confirms, does not auto-save, and offers Undo for 15 seconds', () => {
  const gen = modal.slice(modal.indexOf('const handleGenerateCoverLetter'), modal.indexOf('// Handle Saving Cover Letter'))
  assert.match(gen, /needsReplaceConfirm\(coverLetterText, savedLetterText\)/)
  assert.doesNotMatch(gen, /setApplicationCoverLetter/)
  assert.match(gen, /15000/)
  assert.match(modal, /Replace your edited letter with a new draft\?/)
  assert.match(modal, />Replace<\/button>/)
  assert.match(modal, />Keep mine<\/button>/)
  assert.match(modal, />\s*Undo\s*</)
})

test('draft banner helper is false for equal drafts and true for different ones', () => {
  const saved = { fullName: 'Asha', email: 'a@x.dev', skillsText: 'Python, SQL', coverLetterText: 'Hi', targetDeadline: '2026-01-05' }
  assert.equal(draftDiffersFromSaved({ ...saved }, saved), false)
  assert.equal(draftDiffersFromSaved({ fullName: ' Asha ', skillsText: 'Python,SQL', targetDeadline: '2026-01-05T00:00:00Z' }, saved), false)
  assert.equal(draftDiffersFromSaved({ ...saved, summary: undefined }, { ...saved }), false)
  assert.equal(draftDiffersFromSaved({ ...saved, coverLetterText: 'Hi there' }, saved), true)
  assert.equal(draftDiffersFromSaved({ ...saved, skillsText: 'Python' }, saved), true)

  const resume = { content: { full_name: 'Asha', email: 'a@x.dev', skills: ['Python', 'SQL'] } }
  const app = { cover_letter: 'Hi', updated_at: '2026-01-01T00:00:00Z' }
  const same = { updatedAt: '2025-12-31T00:00:00Z', draft: { fullName: 'Asha', email: 'a@x.dev', skillsText: 'Python, SQL', coverLetterText: 'Hi' } }
  assert.equal(inspectDraftConflict(same, resume, app).hasConflict, false)
  const diff = { ...same, draft: { ...same.draft, coverLetterText: 'Edited' } }
  assert.equal(inspectDraftConflict(diff, resume, app).hasConflict, true)
})

test('a closed application gets the reopen message', () => {
  const plan = planStageMove('WITHDRAWN', 'preparing')
  assert.equal(plan.ok, false)
  assert.equal(plan.reason, CLOSED_REOPEN_MESSAGE)
  assert.equal(CLOSED_REOPEN_MESSAGE, "Closed applications can't be reopened here. Prepare it again from the Radar.")
  assert.equal(planStageMove('SUBMITTED', 'preparing').ok, false)
  assert.doesNotMatch(planStageMove('SUBMITTED', 'preparing').reason, /Closed applications/)
})
