import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const srcDir = path.resolve(__dirname, '../src')

const modalPath = process.env.CAREER_MODAL_FILE || path.join(srcDir, 'components/career/ApplicationWorkspaceModal.jsx')
const radarPath = process.env.INTERNSHIP_RADAR_FILE || path.join(srcDir, 'components/InternshipRadar.jsx')

const readModal = () => fs.readFileSync(modalPath, 'utf8')
const readRadar = () => fs.readFileSync(radarPath, 'utf8')

test('Item 1: loadCompanyIntelData avoids infinite re-fetch loop by omitting loadingIntel from deps and using loading ref guard', () => {
  const code = readModal()
  // 1. Ref to track loading state without causing re-render/deps invalidation
  assert.match(code, /const\s+loadingIntelRef\s*=\s*useRef\(\s*false\s*\)/, 'Must declare loadingIntelRef to guard concurrent requests')
  // 2. Guard using loadingIntelRef.current
  assert.match(code, /if\s*\(\s*loadingIntelRef\.current\s*\)\s*return/, 'Must guard concurrent intel loads using loadingIntelRef.current')
  // 3. Must not include loadingIntel in useCallback deps of loadCompanyIntelData
  const intelFnMatch = code.match(/const\s+loadCompanyIntelData\s*=\s*useCallback\([\s\S]*?\},\s*\[([\s\S]*?)\]\)/)
  assert.ok(intelFnMatch, 'loadCompanyIntelData must be defined with useCallback')
  const deps = intelFnMatch[1]
  assert.ok(!deps.includes('loadingIntel'), 'loadCompanyIntelData dependencies must NOT include loadingIntel (causes infinite re-fetch loop)')
})

test('Item 2: status case normalization, valid enum select options, and uppercase API updates', () => {
  const code = readModal()
  // 1. Must normalize status from backend to lowercase so it matches select option values
  assert.match(code, /setAppStatus\(\s*String\(\s*app\.status\s*\|\|\s*['"]preparing['"]\s*\)\.toLowerCase\(\)\s*\)/, 'Loaded application status must be normalized to lowercase')
  // 2. Status select options must not include invalid enums (interested, interviewing)
  assert.ok(!code.includes('value="interested"'), 'Select options must not include invalid enum "interested"')
  assert.ok(!code.includes('value="interviewing"'), 'Select options must not include invalid enum "interviewing"')
  // 3. Status select options must include valid enum "interview"
  assert.match(code, /buildStatusOptions\(appStatus,\s*\{\s*useLowerCase:\s*true\s*\}\)/, 'Select options must come from the shared backend-status list (includes "interview")')
  // 4. Outgoing update must send uppercase enum matching CareerApplicationStatus
  assert.match(code, /const\s+\w+\s*=\s*\w+\s*\?\s*String\(\s*\w+\s*\)\.toUpperCase\(\)\s*:\s*undefined|\.toUpperCase\(\)/, 'Outgoing status update must send uppercase enum to match CareerApplicationStatus')
})

test('Item 3: external submission confirmation guards success state and avoids false positive toast on failure', () => {
  const code = readModal()
  // 1. handleUpdateApplicationRecord returns boolean indicating success/failure
  const updateRecordFn = code.match(/const\s+handleUpdateApplicationRecord\s*=\s*async\s*[\s\S]*?finally\s*\{[\s\S]*?\}/)
  assert.ok(updateRecordFn, 'handleUpdateApplicationRecord must be defined')
  const fnBody = updateRecordFn[0]
  assert.match(fnBody, /return\s+true/, 'handleUpdateApplicationRecord must return true on success')
  assert.match(fnBody, /return\s+false/, 'handleUpdateApplicationRecord must return false on error or early return')
  // 2. handleConfirmExternalSubmission checks success before updating checklist or notifying
  const confirmFn = code.match(/const\s+handleConfirmExternalSubmission\s*=\s*async\s*\(\s*\)\s*=>\s*\{([\s\S]*?)\}/)
  assert.ok(confirmFn, 'handleConfirmExternalSubmission must be defined')
  const confirmBody = confirmFn[1]
  assert.match(confirmBody, /const\s+([$\w]+)\s*=\s*await\s+handleUpdateApplicationRecord\(\s*['"]submitted['"]\s*\)/, 'handleConfirmExternalSubmission must await handleUpdateApplicationRecord and store result')
  assert.match(confirmBody, /if\s*\(\s*!\s*[$\w]+\s*\)\s*return/, 'handleConfirmExternalSubmission must guard checklist and toast behind successful status update')
})

test('Item 4: Fix in profile button closes modal and invokes real Resume Studio navigation callback', () => {
  const code = readModal()
  const radarCode = readRadar()
  // 1. ApplicationWorkspaceModal accepts navigation props
  assert.match(code, /export\s+default\s+function\s+ApplicationWorkspaceModal\s*\(\s*\{[\s\S]*?onNavigateToResumeStudio[\s\S]*?\}\s*\)/, 'ApplicationWorkspaceModal must accept onNavigateToResumeStudio prop')
  // 2. Must not use unhandled custom event dispatch
  assert.ok(!code.includes("CustomEvent('navigate'"), 'Must not dispatch unhandled CustomEvent for navigation')
  // 3. Fix in profile click handler invokes onClose and navigation callback
  const handleFixFn = code.match(/const\s+handleFixInProfile\s*=\s*\(\s*\)\s*=>\s*\{([\s\S]*?)\}/)
  assert.ok(handleFixFn, 'handleFixInProfile handler must be defined')
  const handleFixBody = handleFixFn[1]
  assert.match(handleFixBody, /onClose\s*\(\s*\)/, 'handleFixInProfile must invoke onClose()')
  assert.match(handleFixBody, /onNavigateToResumeStudio/, 'handleFixInProfile must check/invoke onNavigateToResumeStudio')
  // 4. InternshipRadar passes real navigation callback to ApplicationWorkspaceModal
  assert.match(radarCode, /<ApplicationWorkspaceModal[\s\S]*?onNavigateToResumeStudio=\{\s*handleGoToResumeStudio\s*\}[\s\S]*?\/>/, 'InternshipRadar must pass onNavigateToResumeStudio={handleGoToResumeStudio} to ApplicationWorkspaceModal')
})

test('Item 5: company intel refresh error uses showNotification with error type instead of raw string', () => {
  const code = readModal()
  // 1. Error block in loadCompanyIntelData must call showNotification with error type
  assert.match(code, /showNotification\(\s*['"]Could not refresh intelligence report\. Please try again\.['"]\s*,\s*['"]error['"]\s*\)/, 'Must call showNotification with "error" type on intel refresh error')
  // 2. Must not call setNotification with raw string which causes missing notification.message
  assert.ok(!code.includes("setNotification('Could not refresh intelligence report. Please try again.')"), 'Must not call setNotification with raw string (causes undefined notification.message)')
})
