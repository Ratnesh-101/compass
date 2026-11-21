// One tracker with six stages for the user, mapped from the 23 backend statuses (the database
// values never change; only what the screen shows). Pure functions, no React.

export const STAGES = [
  { key: 'saved', label: 'Saved' },
  { key: 'preparing', label: 'Preparing' },
  { key: 'applied', label: 'Applied' },
  { key: 'interview', label: 'Interview' },
  { key: 'offer', label: 'Offer' },
  { key: 'closed', label: 'Closed' },
]

const STAGE_BY_STATUS = {
  SAVED: 'saved',
  DISCOVERED: 'saved',
  ELIGIBILITY_CHECKED: 'saved',
  PREPARING: 'preparing',
  ELIGIBILITY_REVIEW: 'preparing',
  NEEDS_INFORMATION: 'preparing',
  RESUME_DRAFT: 'preparing',
  RESUME_VALIDATION_FAILED: 'preparing',
  READY_FOR_REVIEW: 'preparing',
  READY_FOR_APPROVAL: 'preparing',
  APPROVED_FOR_SUBMISSION: 'preparing',
  SUBMITTING: 'preparing',
  SUBMISSION_FAILED: 'preparing',
  SUBMISSION_OUTCOME_UNKNOWN: 'preparing',
  MANUAL_SUBMISSION_REQUIRED: 'preparing',
  HANDOFF_KIT_READY: 'preparing',
  SUBMITTED: 'applied',
  ASSESSMENT_RECEIVED: 'interview',
  INTERVIEW: 'interview',
  OFFER_RECEIVED: 'offer',
  REJECTED: 'closed',
  WITHDRAWN: 'closed',
  CLOSED: 'closed',
}

const DETAIL_BY_STATUS = {
  RESUME_VALIDATION_FAILED: 'Needs your details',
  NEEDS_INFORMATION: 'Needs your details',
  READY_FOR_REVIEW: 'Ready to review',
  READY_FOR_APPROVAL: 'Ready to review',
  APPROVED_FOR_SUBMISSION: 'Approved, ready to apply',
  HANDOFF_KIT_READY: 'Ready to apply on the company site',
  MANUAL_SUBMISSION_REQUIRED: 'Ready to apply on the company site',
  SUBMISSION_FAILED: 'Needs another try',
  SUBMITTING: 'Checking the result',
  SUBMISSION_OUTCOME_UNKNOWN: 'Checking the result',
  ASSESSMENT_RECEIVED: 'Assessment received',
  REJECTED: 'Not selected',
  WITHDRAWN: 'Withdrawn',
}

export const BACKEND_STATUSES = Object.keys(STAGE_BY_STATUS)

const normalize = status => String(status || '').trim().toUpperCase()

/** Stage key for a backend status. Unknown values count as "preparing" so nothing disappears. */
export function stageOfStatus(status) {
  return STAGE_BY_STATUS[normalize(status)] || 'preparing'
}

export function stageLabel(stageKey) {
  return STAGES.find(s => s.key === stageKey)?.label || 'Preparing'
}

/** Small grey line shown next to the stage, e.g. "Needs your details". Empty when there is nothing to add. */
export function stageDetail(status) {
  return DETAIL_BY_STATUS[normalize(status)] || ''
}

/**
 * One counter for everywhere: `active` is every application that is not Closed.
 * Used by the Radar overview card and the Application Center header, so they cannot disagree.
 */
export function countApplications(applications) {
  const list = Array.isArray(applications) ? applications : []
  const byStage = Object.fromEntries(STAGES.map(s => [s.key, 0]))
  for (const app of list) byStage[stageOfStatus(app?.status)] += 1
  return { total: list.length, active: list.length - byStage.closed, byStage }
}

/** Applications shown under a tab: 'all' or a stage key. */
export function filterByStage(applications, tab) {
  const list = Array.isArray(applications) ? applications : []
  if (!tab || tab === 'all') return list
  return list.filter(app => stageOfStatus(app?.status) === tab)
}

// ---------------------------------------------------------------------------
// Why an application is stuck, in plain words
// ---------------------------------------------------------------------------

const FIELD_WORDS = {
  'full name': 'your full name',
  'candidate full name': 'your full name',
  'email address': 'your email address',
  email: 'your email address',
  'verified email address': 'your email address',
  'phone number': 'your phone number',
  'education history': 'your education',
  'education section': 'your education',
  'technical skills': 'your skills',
  'technical projects': 'your projects',
}

// The backend sends whole sentences ("Education section cannot be empty."), so match by keyword too.
const FIELD_PATTERNS = [
  [/full name/i, 'your full name'],
  [/e-?mail/i, 'your email address'],
  [/phone/i, 'your phone number'],
  [/education/i, 'your education'],
  [/skills?\b/i, 'your skills'],
  [/projects?\b/i, 'your projects'],
]

function plainField(raw) {
  const text = String(raw || '').replace(/\(.*?\)/g, '').trim()
  const known = FIELD_WORDS[text.toLowerCase()]
  if (known) return known
  const hit = FIELD_PATTERNS.find(([pattern]) => pattern.test(text))
  if (hit) return hit[1]
  return text.replace(/\.+$/, '').toLowerCase()
}

function joinWords(items) {
  if (items.length <= 1) return items.join('')
  return `${items.slice(0, -1).join(', ')} and ${items[items.length - 1]}`
}

/**
 * Plain message for an application that cannot move on, or null when nothing is blocking it.
 * Only RESUME_VALIDATION_FAILED and NEEDS_INFORMATION are blocked states.
 */
export function blockedMessage(app) {
  const status = normalize(app?.status)
  if (status !== 'RESUME_VALIDATION_FAILED' && status !== 'NEEDS_INFORMATION') return null
  const items = []
  const add = value => {
    const word = plainField(value)
    if (word && !items.includes(word)) items.push(word)
  }
  const content = app?.resume?.content
  if (content) {
    if (!String(content.full_name || '').trim()) add('full name')
    if (!String(content.email || '').trim() || !String(content.email).includes('@')) add('email address')
  }
  ;(app?.missing_fields || []).forEach(add)
  ;(app?.resume?.validation_report?.missing_fields || []).forEach(add)
  const claims = app?.resume?.validation_report?.unsupported_claims || []
  if (items.length > 0) {
    return `To move this forward, add ${joinWords(items)} in My resume. Then open the application again.`
  }
  if (claims.length > 0) {
    return 'Some items in this resume are not in your saved resume. Open the application and remove them or add them to My resume.'
  }
  return 'This application needs a few more details from you. Open My resume, check your name, email and education, then open the application again.'
}

// ---------------------------------------------------------------------------
// Moving between stages (the backend still decides what is allowed)
// ---------------------------------------------------------------------------

const CAN_MARK_APPLIED = new Set([
  'READY_FOR_REVIEW', 'READY_FOR_APPROVAL', 'APPROVED_FOR_SUBMISSION', 'SUBMITTING',
  'SUBMISSION_OUTCOME_UNKNOWN', 'SUBMISSION_FAILED', 'HANDOFF_KIT_READY', 'MANUAL_SUBMISSION_REQUIRED',
])
const CAN_WITHDRAW_THEN_CLOSE = new Set([
  'SAVED', 'PREPARING', 'RESUME_VALIDATION_FAILED', 'READY_FOR_REVIEW', 'READY_FOR_APPROVAL',
  'APPROVED_FOR_SUBMISSION', 'SUBMITTING', 'SUBMISSION_OUTCOME_UNKNOWN', 'SUBMISSION_FAILED',
  'HANDOFF_KIT_READY', 'MANUAL_SUBMISSION_REQUIRED', 'SUBMITTED', 'ASSESSMENT_RECEIVED', 'INTERVIEW',
])

/**
 * Steps to move an application to a stage, or the reason it cannot move yet.
 * Returns { ok: true, steps: [{ type: 'mark_applied' } | { type: 'status', status }] } or { ok: false, reason }.
 */
export function planStageMove(currentStatus, targetStage) {
  const status = normalize(currentStatus)
  const current = stageOfStatus(status)
  if (current === targetStage) return { ok: true, steps: [] }
  const status_ = value => ({ ok: true, steps: [{ type: 'status', status: value }] })

  switch (targetStage) {
    case 'saved':
      return ['PREPARING', 'RESUME_VALIDATION_FAILED', 'WITHDRAWN'].includes(status)
        ? status_('SAVED')
        : { ok: false, reason: 'An application that is ready or sent cannot go back to Saved.' }
    case 'preparing':
      return ['SAVED', 'RESUME_VALIDATION_FAILED'].includes(status)
        ? status_('PREPARING')
        : { ok: false, reason: 'This application is already past the preparing stage.' }
    case 'applied':
      if (CAN_MARK_APPLIED.has(status)) return { ok: true, steps: [{ type: 'mark_applied' }] }
      return { ok: false, reason: 'Finish preparing first. The resume check has to pass before you can mark it as applied.' }
    case 'interview':
      return ['SUBMITTED', 'ASSESSMENT_RECEIVED'].includes(status)
        ? status_('INTERVIEW')
        : { ok: false, reason: 'Mark it as applied first.' }
    case 'offer':
      return ['SUBMITTED', 'ASSESSMENT_RECEIVED', 'INTERVIEW'].includes(status)
        ? status_('OFFER_RECEIVED')
        : { ok: false, reason: 'Mark it as applied first.' }
    case 'closed':
      if (['OFFER_RECEIVED', 'REJECTED', 'WITHDRAWN'].includes(status)) return status_('CLOSED')
      if (CAN_WITHDRAW_THEN_CLOSE.has(status)) {
        return { ok: true, steps: [{ type: 'status', status: 'WITHDRAWN' }, { type: 'status', status: 'CLOSED' }] }
      }
      return { ok: false, reason: 'This application cannot be closed from here.' }
    default:
      return { ok: false, reason: 'Unknown stage.' }
  }
}
