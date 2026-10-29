import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import {
  extractErrorDetail,
  APPLICATION_STATUS_LABELS,
  buildStatusOptions,
  summarizeBatchResults,
  buildDeadlinePayload,
  getValidationCardState,
  resolveOverallConfidence,
  computeMissingFields,
  getResumeKindLabel,
  copyTextSafely,
  displayKitValue,
  validateProfileForm,
  buildProfilePayload,
  hasSavedProfile,
} from '../src/utils/careerUiHelpers.js'

const read = p => fs.readFileSync(new URL(`../src/${p}`, import.meta.url), 'utf8')

// Backend CareerApplicationStatus enum (backend/models_career.py)
const BACKEND_STATUSES = [
  'SAVED', 'DISCOVERED', 'ELIGIBILITY_CHECKED', 'PREPARING', 'ELIGIBILITY_REVIEW', 'NEEDS_INFORMATION',
  'RESUME_DRAFT', 'RESUME_VALIDATION_FAILED', 'READY_FOR_REVIEW', 'READY_FOR_APPROVAL',
  'APPROVED_FOR_SUBMISSION', 'SUBMITTING', 'SUBMITTED', 'SUBMISSION_FAILED', 'SUBMISSION_OUTCOME_UNKNOWN',
  'MANUAL_SUBMISSION_REQUIRED', 'HANDOFF_KIT_READY', 'ASSESSMENT_RECEIVED', 'INTERVIEW', 'REJECTED',
  'OFFER_RECEIVED', 'WITHDRAWN', 'CLOSED',
]

// 1. Candidate profile entry point
test('CareerCopilot mounts RadarProfileModal from both entry points', () => {
  const src = read('components/CareerCopilot.jsx')
  assert.match(src, /import RadarProfileModal/)
  assert.match(src, /<RadarProfileModal/)
  assert.match(src, /onClick=\{handleOpenProfileModal\}/)
  assert.match(src, /onOpenProfile=\{handleOpenProfileModal\}/)
  assert.match(src, /setProfileRefreshTrigger\(prev => prev \+ 1\)/)
})

test('profile years are validated: academic 1-5, graduation 2024-2035', () => {
  assert.match(validateProfileForm({ degree: 'B.Tech', academicYear: 6, gradYear: 2027 }), /1 and 5/)
  assert.match(validateProfileForm({ degree: 'B.Tech', academicYear: 0, gradYear: 2027 }), /1 and 5/)
  assert.match(validateProfileForm({ degree: 'B.Tech', academicYear: 2, gradYear: 2036 }), /2024 and 2035/)
  assert.equal(validateProfileForm({ degree: 'B.Tech', academicYear: 2, gradYear: 2027 }), null)
})

test('radar profile save throws the server detail text', () => {
  const src = read('api/radarApi.js')
  assert.match(src, /extractErrorDetail\(body, `Failed to update profile/)
})

// A. No fabricated profile defaults
test('profile form has no invented defaults and requires year fields', () => {
  assert.match(validateProfileForm({}), /2024 and 2035/)
  assert.match(validateProfileForm({ degree: 'BS', academicYear: '', gradYear: 2027 }), /1 and 5/)
  const src = read('components/radar/RadarProfileModal.jsx')
  assert.doesNotMatch(src, /'8\.5'/)
  assert.doesNotMatch(src, /\|\| 2027/)
  assert.doesNotMatch(src, /'PyTorch'/)
  assert.doesNotMatch(src, /\|\| 2\)/)
})

test('CGPA must be within 0 and the chosen scale', () => {
  const base = { degree: 'BS', academicYear: 3, gradYear: 2027 }
  assert.match(validateProfileForm({ ...base, cgpa: '11', cgpaScale: 10 }), /between 0 and 10/)
  assert.match(validateProfileForm({ ...base, cgpa: '-1', cgpaScale: 10 }), /between 0 and 10/)
  assert.equal(validateProfileForm({ ...base, cgpa: '3.5', cgpaScale: 4 }), null)
  assert.match(validateProfileForm({ ...base, cgpa: '4.5', cgpaScale: 4 }), /between 0 and 4/)
})

test('profile payload contains only fields the user filled', () => {
  const payload = buildProfilePayload({
    degree: 'B.Tech', academicYear: 3, gradYear: 2027, cgpa: '', activeBacklogs: '', skillsStr: '',
    preferredArrangements: [], preferredRoles: [], countryOfStudy: '', gradMonth: '',
  })
  assert.deepEqual(payload, { degree: 'B.Tech', academic_year: 3, grad_year: 2027 })
  assert.ok(!('active_backlogs' in payload))
  const withBacklogs = buildProfilePayload({ degree: 'B.Tech', academicYear: 3, gradYear: 2027, activeBacklogs: '0' })
  assert.equal(withBacklogs.active_backlogs, 0)
})

test('has-profile is derived from real fields, not has_profile/degree_level', () => {
  assert.equal(hasSavedProfile(null), false)
  assert.equal(hasSavedProfile({ has_profile: true }), false)
  assert.equal(hasSavedProfile({ degree_level: 'ug' }), false)
  assert.equal(hasSavedProfile({ degree: 'B.Tech' }), true)
  assert.equal(hasSavedProfile({ academic_year: 2 }), true)
  const src = read('components/InternshipRadar.jsx')
  assert.doesNotMatch(src, /profile\.has_profile/)
  assert.doesNotMatch(src, /degree_level/)
})

// 2. Validation card
test('validation card shows Resume incomplete with missing fields and warnings', () => {
  const state = getValidationCardState({
    is_valid: false, status: 'CONSISTENT WITH MASTER',
    missing_fields: ['name', 'email'], warnings: ['No education'],
  })
  assert.equal(state.incompleteLabel, 'Resume incomplete')
  assert.match(state.hint, /name, email and education in Resume Studio/)
  assert.deepEqual(state.missingFields, ['name', 'email'])
  assert.deepEqual(state.warnings, ['No education'])
  assert.equal(getValidationCardState({ is_valid: true }).incompleteLabel, null)
  const src = read('components/career/ValidationReportCard.jsx')
  assert.match(src, /missingFields\.map/)
  assert.match(src, /warnings\.map/)
})

// 3. Re-tailor
test('tailorResume sends application_id and the workspace passes it', () => {
  const api = read('api/careerApi.js')
  assert.match(api, /application_id: applicationId/)
  assert.match(read('components/career/ApplicationWorkspaceModal.jsx'), /tailorResume\(opportunity\.id, null, null, application\?\.id/)
})

// 4. Batch banner honesty
test('batch banner counts submitted separately from prepared kits', () => {
  const r = summarizeBatchResults([
    { status: 'HANDOFF_KIT_READY' }, { status: 'MANUAL_SUBMISSION_REQUIRED' }, { status: 'SUBMISSION_FAILED' },
  ])
  assert.equal(r.submitted, 0)
  assert.equal(r.prepared, 2)
  assert.equal(r.message, "Application kits prepared (2 of 3). Submit each on the employer's portal.")
  assert.doesNotMatch(r.message, /submitted/i)
  assert.match(summarizeBatchResults([{ status: 'SUBMITTED' }, { status: 'HANDOFF_KIT_READY' }]).message, /1 of 2 submitted/)
  assert.doesNotMatch(read('components/career/ApplicationCenter.jsx'), /Batch Submission Executed/)
  const modal = read('components/career/BatchApprovalModal.jsx')
  assert.match(modal, /Approve & prepare kits/)
  assert.doesNotMatch(modal, /Authorize & Submit Batch/)
  assert.match(modal, /\{error\}/)
})

// 5. Status options and error detail
test('status options include every backend status and keep unknown current values', () => {
  const values = buildStatusOptions('SAVED').map(o => o.value)
  for (const s of BACKEND_STATUSES) assert.ok(values.includes(s), `missing ${s}`)
  assert.deepEqual(Object.keys(APPLICATION_STATUS_LABELS).sort(), [...BACKEND_STATUSES].sort())
  assert.ok(buildStatusOptions('FUTURE_STATUS').some(o => o.value === 'FUTURE_STATUS'))
  assert.ok(buildStatusOptions('handoff_kit_ready', { useLowerCase: true }).some(o => o.value === 'handoff_kit_ready'))
  assert.match(read('components/career/ApplicationCenter.jsx'), /buildStatusOptions\(app\.status\)/)
  assert.match(read('components/career/ApplicationWorkspaceModal.jsx'), /buildStatusOptions\(appStatus/)
})

test('extractErrorDetail handles strings, lists and fallbacks', () => {
  assert.equal(extractErrorDetail({ detail: 'Nope' }, 'fb'), 'Nope')
  assert.equal(extractErrorDetail({ detail: ['a', { msg: 'b' }] }, 'fb'), 'a; b')
  assert.equal(extractErrorDetail({ detail: [{ company_name: 'Acme', reason: 'no resume' }] }, 'fb'), 'Acme: no resume')
  assert.equal(extractErrorDetail({}, 'fb'), 'fb')
  assert.equal(extractErrorDetail(null, 'fb'), 'fb')
  const api = read('api/careerApi.js')
  for (const msg of ['Failed to update application', 'Failed to commit extracted resume', 'Failed to ingest external profile']) {
    assert.match(api, new RegExp(`errorFromResponse\\(res, '${msg}'\\)`))
  }
  assert.doesNotMatch(api, /Failed to update application: \$\{res\.statusText\}/)
})

// 6. Workspace save details
test('clearing a deadline sends clear_target_deadline', () => {
  assert.deepEqual(buildDeadlinePayload(''), { clear_target_deadline: true })
  assert.deepEqual(buildDeadlinePayload(null), { clear_target_deadline: true })
  assert.deepEqual(buildDeadlinePayload('2026-12-01'), { target_deadline: '2026-12-01' })
  const src = read('components/career/ApplicationWorkspaceModal.jsx')
  assert.match(src, /\.\.\.buildDeadlinePayload\(targetDeadline\)/)
  assert.match(src, /Local checklist \(not saved\)/)
  assert.match(src, /onClick=\{handleConfirmExternalSubmission\}\s+disabled=\{savingStatus\}/)
})

// 7. Handoff kit UI
test('handoff kit shows (not provided), no pre-ticked letter, safe clipboard and API base', async () => {
  assert.equal(displayKitValue(null), '(not provided)')
  assert.equal(displayKitValue('  '), '(not provided)')
  assert.equal(displayKitValue('x'), 'x')
  assert.equal(await copyTextSafely('t', { writeText: async () => { throw new Error('denied') } }), false)
  assert.equal(await copyTextSafely('t', { writeText: async () => {} }), true)
  assert.equal(await copyTextSafely('t', null), false)
  const drawer = read('components/career/HandoffKitDrawer.jsx')
  assert.doesNotMatch(drawer, /coverLetterReviewed: Boolean/)
  assert.doesNotMatch(drawer, /fetch\(`\/api/)
  assert.match(drawer, /API_BASE/)
  assert.match(drawer, /Copy failed/)
  assert.match(drawer, /kit\.missing_fields/)
  const modal = read('components/career/HandoffKitModal.jsx')
  assert.match(modal, /activeKit\.portal_url && \(/)
  assert.doesNotMatch(modal, /alert\(/)
  assert.doesNotMatch(modal, /Rolling recruitment/)
})

// 8. Return prompt
test('ReturnSubmissionPrompt uses markApplied and shows an inline error', () => {
  const src = read('components/career/ReturnSubmissionPrompt.jsx')
  assert.match(src, /import \{ markApplied \} from '..\/..\/api\/careerApi'/)
  assert.doesNotMatch(src, /fetch\(/)
  assert.match(src, /confirmError/)
  assert.match(read('api/careerApi.js'), /export async function markApplied/)
})

// 9. Resume Studio / extraction
test('confidence resolver returns null for unknown instead of a fake value', () => {
  assert.equal(resolveOverallConfidence({}), null)
  assert.equal(resolveOverallConfidence(null), null)
  assert.equal(resolveOverallConfidence({ field_confidence: {} }), null)
  assert.equal(resolveOverallConfidence({ overall_confidence: 0.4, field_confidence: { overall: 0.9 } }), 0.4)
  assert.equal(resolveOverallConfidence({ field_confidence: { overall: 0.7 } }), 0.7)
  assert.equal(resolveOverallConfidence({ overall_confidence: 0 }), 0)
  assert.doesNotMatch(read('components/career/ExtractionReviewModal.jsx'), /0\.85/)
  const studio = read('components/career/ResumeStudio.jsx')
  assert.doesNotMatch(studio, /overall: 0\.(85|9)/)
  assert.doesNotMatch(studio, /missing_fields: \[\]/)
})

test('missing fields are computed client-side from empty content', () => {
  assert.deepEqual(computeMissingFields({}), ['name', 'email', 'skills', 'education'])
  assert.deepEqual(computeMissingFields({ full_name: 'A', email: 'a@b.c', skills: ['x'], education: [{}] }), [])
})

test('imported drafts are not labelled v1 Tailored', () => {
  assert.equal(getResumeKindLabel({ is_master: true }), 'Master')
  assert.equal(getResumeKindLabel({ is_master: false, opportunity_id: null }), 'Imported draft')
  assert.equal(getResumeKindLabel({ is_master: false, opportunity_id: 4, company_name: 'Acme' }), 'Tailored for Acme')
  assert.doesNotMatch(read('components/career/ResumeStudio.jsx'), /Tailored`\}/)
})

test('external profile import defaults to separate draft; no blocking alert()', () => {
  const review = read('components/career/ExtractionReviewModal.jsx')
  assert.match(review, /preferDraft = diag\.file_type === 'profile_import'/)
  const studio = read('components/career/ResumeStudio.jsx')
  assert.doesNotMatch(studio, /\balert\(/)
  assert.match(studio, /is_fork \|\| repo\?\.fork/)
})
