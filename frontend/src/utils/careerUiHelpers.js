// Pure helpers for the Career Copilot UI (kept free of React so they are unit-testable).

// ---------------------------------------------------------------------------
// Backend error detail extraction
// ---------------------------------------------------------------------------

/**
 * Turn a FastAPI error body into a human message.
 * `detail` may be a string, a list of strings, or a list of {msg, loc} objects.
 */
export function extractErrorDetail(body, fallback) {
  const detail = body && typeof body === 'object' ? body.detail : null
  if (typeof detail === 'string' && detail.trim()) return detail.trim()
  if (Array.isArray(detail) && detail.length > 0) {
    const parts = detail
      .map(item => {
        if (typeof item === 'string') return item
        if (item && typeof item === 'object') {
          const text = item.msg || item.message || item.detail || item.reason || ''
          const who = item.company_name || item.role_title || item.application_id || item.id
          return who && text ? `${who}: ${text}` : text
        }
        return ''
      })
      .filter(Boolean)
    if (parts.length > 0) return parts.join('; ')
  }
  if (detail && typeof detail === 'object') {
    const inner = detail.message || detail.msg || detail.detail
    if (typeof inner === 'string' && inner) return inner
  }
  return fallback
}

// ---------------------------------------------------------------------------
// Application statuses (mirrors backend CareerApplicationStatus)
// ---------------------------------------------------------------------------

export const APPLICATION_STATUS_LABELS = {
  SAVED: 'Saved',
  DISCOVERED: 'Discovered',
  ELIGIBILITY_CHECKED: 'Eligibility Checked',
  PREPARING: 'Preparing',
  ELIGIBILITY_REVIEW: 'Eligibility Review',
  NEEDS_INFORMATION: 'Needs Information',
  RESUME_DRAFT: 'Resume Draft',
  RESUME_VALIDATION_FAILED: 'Resume Validation Failed',
  READY_FOR_REVIEW: 'Ready for Review',
  READY_FOR_APPROVAL: 'Ready for Approval',
  APPROVED_FOR_SUBMISSION: 'Approved for Submission',
  SUBMITTING: 'Submitting',
  SUBMITTED: 'Submitted',
  SUBMISSION_FAILED: 'Submission Failed',
  SUBMISSION_OUTCOME_UNKNOWN: 'Submission Outcome Unknown',
  MANUAL_SUBMISSION_REQUIRED: 'Manual Handoff',
  HANDOFF_KIT_READY: 'Handoff Kit Ready',
  ASSESSMENT_RECEIVED: 'Assessment Received',
  INTERVIEW: 'Interviewing',
  REJECTED: 'Rejected',
  OFFER_RECEIVED: 'Offer Received',
  WITHDRAWN: 'Withdrawn',
  CLOSED: 'Closed',
}

export function humanizeStatus(status) {
  if (!status) return ''
  const key = String(status).trim().toUpperCase()
  if (APPLICATION_STATUS_LABELS[key]) return APPLICATION_STATUS_LABELS[key]
  return key
    .toLowerCase()
    .split('_')
    .map(w => w.charAt(0).toUpperCase() + w.slice(1))
    .join(' ')
}

/**
 * Options for a controlled status <select>. Every backend status is present, and an
 * unknown current value is added so the select never silently displays another option.
 * `useLowerCase` keeps the workspace modal's lower-case value convention.
 */
export function buildStatusOptions(currentStatus, { useLowerCase = false } = {}) {
  const fmt = v => (useLowerCase ? v.toLowerCase() : v)
  const options = Object.keys(APPLICATION_STATUS_LABELS).map(value => ({
    value: fmt(value),
    label: APPLICATION_STATUS_LABELS[value],
  }))
  const current = currentStatus ? fmt(String(currentStatus).trim().toUpperCase()) : ''
  if (current && !options.some(o => o.value === current)) {
    options.unshift({ value: current, label: humanizeStatus(current) })
  }
  return options
}

// ---------------------------------------------------------------------------
// Batch banner honesty
// ---------------------------------------------------------------------------

/**
 * Summarise a batch submit/prepare result. Only SUBMITTED results count as submitted;
 * manual handoff kits are "prepared".
 */
export function summarizeBatchResults(results) {
  const list = Array.isArray(results) ? results : []
  const total = list.length
  const submitted = list.filter(r => String(r?.status || '').toUpperCase() === 'SUBMITTED').length
  const prepared = list.filter(r => {
    const s = String(r?.status || '').toUpperCase()
    return s === 'HANDOFF_KIT_READY' || s === 'MANUAL_SUBMISSION_REQUIRED' || (s !== 'SUBMITTED' && Boolean(r?.manual_package))
  }).length
  let message
  if (total === 0) {
    message = 'No applications were prepared.'
  } else if (submitted > 0) {
    message =
      `${submitted} of ${total} submitted.` +
      (prepared > 0 ? ` Application kits prepared (${prepared} of ${total}). Submit each on the employer's portal.` : '')
  } else {
    message = `Application kits prepared (${prepared} of ${total}). Submit each on the employer's portal.`
  }
  return { total, submitted, prepared, message }
}

// ---------------------------------------------------------------------------
// Workspace deadline payload
// ---------------------------------------------------------------------------

/** A cleared deadline must be sent as `clear_target_deadline: true`; null means "no change". */
export function buildDeadlinePayload(deadline) {
  const value = typeof deadline === 'string' ? deadline.trim() : deadline
  if (!value) return { clear_target_deadline: true }
  return { target_deadline: value }
}

// ---------------------------------------------------------------------------
// Resume validation card decision
// ---------------------------------------------------------------------------

export const RESUME_INCOMPLETE_HINT = 'Add your name, email and education in Resume Studio.'

export function getValidationCardState(report) {
  if (!report) return null
  const missingFields = Array.isArray(report.missing_fields) ? report.missing_fields.filter(Boolean) : []
  const warnings = Array.isArray(report.warnings) ? report.warnings.filter(Boolean) : []
  const isIncomplete = report.is_valid === false
  const rawStatus = report.validation_status || report.status || ''
  const status = rawStatus || (report.is_valid ? 'CONSISTENT WITH MASTER' : 'INCONSISTENT WITH MASTER')
  return {
    status,
    isIncomplete,
    incompleteLabel: isIncomplete ? 'Resume incomplete' : null,
    hint: isIncomplete ? RESUME_INCOMPLETE_HINT : null,
    missingFields,
    warnings,
    isNotEnoughData: status === 'NOT ENOUGH DATA',
    isConsistent: status === 'CONSISTENT WITH MASTER',
  }
}

// ---------------------------------------------------------------------------
// Extraction confidence and missing fields
// ---------------------------------------------------------------------------

/** Returns a 0..1 number, or null when the backend did not provide a confidence. */
export function resolveOverallConfidence(diagnostics) {
  if (!diagnostics || typeof diagnostics !== 'object') return null
  const candidate = diagnostics.overall_confidence ?? diagnostics.field_confidence?.overall
  if (candidate === null || candidate === undefined || candidate === '') return null
  const n = Number(candidate)
  return Number.isFinite(n) ? n : null
}

/** Client-side missing field detection for imports where the backend sends no list. */
export function computeMissingFields(content) {
  const c = content || {}
  const missing = []
  if (!String(c.full_name || c.name || '').trim()) missing.push('name')
  if (!String(c.email || '').trim()) missing.push('email')
  if (!Array.isArray(c.skills) || c.skills.filter(s => String(s || '').trim()).length === 0) missing.push('skills')
  if (!Array.isArray(c.education) || c.education.length === 0) missing.push('education')
  return missing
}

// ---------------------------------------------------------------------------
// Resume version labels
// ---------------------------------------------------------------------------

export function getResumeKindLabel(resume) {
  if (!resume) return ''
  const company = resume.company_name || resume.target_company || resume.opportunity_company
  const hasOpportunity = resume.opportunity_id !== null && resume.opportunity_id !== undefined
  if (resume.is_master || resume.kind === 'master' || resume.type === 'master') return 'Master'
  if (hasOpportunity || company || resume.kind === 'tailored') {
    return company ? `Tailored for ${company}` : 'Tailored'
  }
  return 'Imported draft'
}

// ---------------------------------------------------------------------------
// Clipboard
// ---------------------------------------------------------------------------

/** Resolves true when copied, false when the clipboard is unavailable or rejected. */
export async function copyTextSafely(text, clipboard) {
  const target = clipboard !== undefined ? clipboard : (typeof navigator !== 'undefined' ? navigator.clipboard : null)
  if (!target || typeof target.writeText !== 'function') return false
  try {
    await target.writeText(text)
    return true
  } catch {
    return false
  }
}

// ---------------------------------------------------------------------------
// Handoff kit display values
// ---------------------------------------------------------------------------

export const NOT_PROVIDED = '(not provided)'

export function displayKitValue(value) {
  if (value === null || value === undefined) return NOT_PROVIDED
  const s = String(value).trim()
  return s ? s : NOT_PROVIDED
}

// ---------------------------------------------------------------------------
// Profile validation (mirrors RadarProfileModal rules)
// ---------------------------------------------------------------------------

export function validateProfileYears({ academicYear, gradYear }) {
  const gy = Number(gradYear)
  if (!Number.isInteger(gy) || gy < 2024 || gy > 2035) return 'Graduation Year must be between 2024 and 2035.'
  const ay = Number(academicYear)
  if (!Number.isInteger(ay) || ay < 1 || ay > 5) return 'Academic Year must be between 1 and 5.'
  return null
}

// ---------------------------------------------------------------------------
// Candidate profile form (RadarProfileModal): no invented defaults
// ---------------------------------------------------------------------------

export function validateProfileForm({ degree = '', academicYear = '', gradYear = '', cgpa = '', cgpaScale = 10 }) {
  const years = validateProfileYears({ academicYear: academicYear === '' ? NaN : academicYear, gradYear: gradYear === '' ? NaN : gradYear })
  if (years) return years
  if (!String(degree).trim()) return 'Please specify your Current Degree (e.g. B.Tech, B.E., BS).'
  if (String(cgpa).trim() !== '') {
    const value = Number(cgpa)
    const scale = Number(cgpaScale) || 10
    if (!Number.isFinite(value) || value < 0 || value > scale) {
      return `CGPA must be between 0 and ${scale}.`
    }
  }
  return null
}

/** Build the PUT body from only the fields the user actually filled. */
export function buildProfilePayload(form) {
  const text = v => (v === null || v === undefined ? '' : String(v).trim())
  const payload = {
    degree: text(form.degree),
    academic_year: Number(form.academicYear),
    grad_year: Number(form.gradYear),
  }
  if (text(form.specialization)) payload.degree_specialization = text(form.specialization)
  if (text(form.university)) payload.university = text(form.university)
  if (text(form.gradMonth)) payload.grad_month = Number(form.gradMonth)
  if (text(form.cgpa)) {
    payload.cgpa = Number(form.cgpa)
    payload.cgpa_scale = Number(form.cgpaScale) || 10
  }
  if (text(form.activeBacklogs)) payload.active_backlogs = Number(form.activeBacklogs)
  if (text(form.countryOfStudy)) {
    payload.country_of_study = text(form.countryOfStudy)
    payload.country_of_residence = text(form.countryOfStudy)
  }
  if (Array.isArray(form.preferredArrangements) && form.preferredArrangements.length > 0) {
    payload.preferred_work_arrangements = form.preferredArrangements
  }
  if (Array.isArray(form.preferredRoles) && form.preferredRoles.length > 0) {
    payload.preferred_roles = form.preferredRoles
  }
  const skills = text(form.skillsStr).split(',').map(s => s.trim()).filter(Boolean)
  if (skills.length > 0) payload.skills = skills
  return payload
}

/** True only when the saved profile has real candidate data (backend never returns has_profile/degree_level). */
export function hasSavedProfile(profile) {
  if (!profile || typeof profile !== 'object') return false
  return Boolean(
    profile.degree ||
    profile.university ||
    profile.grad_year ||
    profile.academic_year ||
    (Array.isArray(profile.skills) && profile.skills.length > 0)
  )
}

// ---------------------------------------------------------------------------
// Job analysis: score display, skill match, request shape
// ---------------------------------------------------------------------------

export const NO_SKILLS_CAPTION = 'No skills listed in this posting'
export const SCORE_GREEN = '#16a34a'
export const SCORE_AMBER = '#d97706'
export const SCORE_RED = '#dc2626'
export const SCORE_NEUTRAL = 'var(--text-muted)'
const SCORE_GREEN_MIN = 75
const SCORE_AMBER_MIN = 50

/** Colour for a 0-100 match score. */
export function matchScoreColor(score) {
  const n = Number(score) || 0
  if (n >= SCORE_GREEN_MIN) return SCORE_GREEN
  if (n >= SCORE_AMBER_MIN) return SCORE_AMBER
  return SCORE_RED
}

/**
 * How to show a JobAnalysisReport match score. The backend sends 0-100 (not a fraction).
 * `score_available === false` (or an analysis with no recognisable skills) is "N/A", never a red 0%.
 * A missing `score_available` (old server) is treated as available.
 */
export function formatMatchScore(analysis) {
  if (!analysis) return { text: '…', color: SCORE_NEUTRAL, caption: '', available: false }
  const noSkills =
    analysis.score_available === false ||
    (analysis.score_available === undefined &&
      Array.isArray(analysis.required_skills) &&
      analysis.required_skills.length === 0 &&
      !(Number(analysis.match_score) > 0))
  if (noSkills) return { text: 'N/A', color: SCORE_NEUTRAL, caption: NO_SKILLS_CAPTION, available: false }
  const score = Math.max(0, Math.min(100, Math.round(Number(analysis.match_score) || 0)))
  return { text: `${score}%`, color: matchScoreColor(score), caption: '', available: true }
}

/**
 * One source of truth for matched/missing skills, shared by the overview and the analysis tab.
 * status: 'loading' (not loaded yet), 'unavailable' (load failed, nothing to show), 'ready'.
 * A stale report kept after a failed re-analyze stays 'ready'.
 */
export function resolveSkillMatch({ analysis, loading, failed, postingSkills }) {
  const posting = Array.isArray(postingSkills) ? postingSkills : []
  if (analysis) {
    const matched = Array.isArray(analysis.matched_skills) ? analysis.matched_skills : []
    const missing = Array.isArray(analysis.missing_skills) ? analysis.missing_skills : []
    const listed = Array.isArray(analysis.required_skills) ? analysis.required_skills : []
    const required = listed.length > 0 ? listed : [...matched, ...missing]
    return { status: 'ready', required, matched, missing }
  }
  const status = failed && !loading ? 'unavailable' : 'loading'
  return { status, required: posting, matched: [], missing: [] }
}

/** GET when there is no custom description; POST with a JSON body otherwise (avoids huge query strings). */
export function buildJobAnalysisRequest(apiBase, opportunityId, customDesc) {
  const url = `${apiBase}/opportunities/${opportunityId}/job-analysis`
  const text = typeof customDesc === 'string' ? customDesc.trim() : ''
  if (!text) return { url, method: 'GET', body: null }
  return { url, method: 'POST', body: JSON.stringify({ custom_description: customDesc }) }
}

// ---------------------------------------------------------------------------
// Company intel: rate limiting
// ---------------------------------------------------------------------------

export const DEFAULT_INTEL_COOLDOWN_SECONDS = 30
export const MAX_INTEL_COOLDOWN_SECONDS = 3600

/** Parse a Retry-After header (delta-seconds). Returns a positive integer or null. */
export function parseRetryAfter(value) {
  if (value === null || value === undefined || value === '') return null
  const n = Number(value)
  if (!Number.isFinite(n) || n <= 0) return null
  return Math.min(Math.ceil(n), MAX_INTEL_COOLDOWN_SECONDS)
}

/**
 * Cooldown (seconds) to apply after a failed intel request.
 * Only a 429 starts one; any other failure never reached the budget so does not lock the user out.
 */
export function intelCooldownForError(err) {
  if (!err || err.status !== 429) return 0
  return parseRetryAfter(err.retryAfter) || DEFAULT_INTEL_COOLDOWN_SECONDS
}

/** Whole seconds left until `untilMs`, never negative. */
export function cooldownSecondsLeft(untilMs, nowMs) {
  if (!untilMs) return 0
  return Math.max(0, Math.ceil((untilMs - nowMs) / 1000))
}

/** User-facing message for a failed intel request, preferring the server's own wording. */
export function intelErrorMessage(err) {
  const msg = err && typeof err.message === 'string' ? err.message.trim() : ''
  if (err && err.status === 429) return msg || 'Company intel is rate limited right now. Please try again shortly.'
  if (err && err.status && msg) return msg
  return "We couldn't generate company intel right now. Please try again."
}

// ---------------------------------------------------------------------------
// Links and clipboard feedback
// ---------------------------------------------------------------------------

export const NO_APPLICATION_URL_TEXT = 'No direct application URL verified for this opportunity yet.'

/** Copy `text` and describe the outcome. Empty text or a rejected write is a failure. */
export async function copyWithFeedback(label, text, clipboard) {
  if (typeof text !== 'string' || !text.trim()) {
    return { ok: false, message: `Copy failed: there is no ${label.toLowerCase()} to copy.` }
  }
  const ok = await copyTextSafely(text, clipboard)
  return ok
    ? { ok: true, message: `${label} copied to clipboard!` }
    : { ok: false, message: `Copy failed: could not access the clipboard.` }
}
