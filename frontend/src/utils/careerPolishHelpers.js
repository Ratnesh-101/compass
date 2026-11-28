// Small pure helpers for career UI polish: friendly status labels, resume hint,
// diff skill capitalisation, copy guard and version labels.

const FRIENDLY_STATUS = {
  READY_FOR_REVIEW: 'Ready for review',
  VALIDATION_FAILED: 'Needs fixes before sending',
  RESUME_VALIDATION_FAILED: 'Needs fixes before sending',
}

/** Friendly label for raw status codes shown to students. Unknown codes are title-cased. */
export function friendlyStatusLabel(code) {
  const key = String(code ?? '').trim().toUpperCase().replace(/[\s-]+/g, '_')
  if (!key) return ''
  if (FRIENDLY_STATUS[key]) return FRIENDLY_STATUS[key]
  return key.toLowerCase().split('_').map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(' ')
}

const DEFAULT_HINT = 'Add your name, email and education in My resume.'

/** Hint naming only the resume fields that are actually missing. */
export function buildResumeIncompleteHint(missingFields) {
  const list = (Array.isArray(missingFields) ? missingFields : [])
    .map(f => String(f || '').trim())
    .filter(Boolean)
  if (list.length === 0) return DEFAULT_HINT
  const names = list.map(f => f.replace(/_/g, ' ').toLowerCase())
  const joined = names.length === 1
    ? names[0]
    : `${names.slice(0, -1).join(', ')} and ${names[names.length - 1]}`
  return `Add your ${joined} in My resume.`
}

export const COPY_EMPTY_MESSAGE = 'Nothing to copy yet.'

export function hasCopyableText(text) {
  return typeof text === 'string' && text.trim().length > 0
}

/** Restore the saved capitalisation of a skill the backend returned lower-cased. */
export function restoreSkillCase(skill, knownSkills) {
  const s = String(skill ?? '')
  const match = (Array.isArray(knownSkills) ? knownSkills : [])
    .find(k => typeof k === 'string' && k.trim().toLowerCase() === s.trim().toLowerCase())
  return match ? match.trim() : s
}

/** Flatten a resume `skills` value (array, object of arrays, or comma string) into names. */
export function collectSkillNames(skills) {
  if (!skills) return []
  if (typeof skills === 'string') return skills.split(',').map(x => x.trim()).filter(Boolean)
  if (Array.isArray(skills)) return skills.flatMap(collectSkillNames)
  if (typeof skills === 'object') return Object.values(skills).flatMap(collectSkillNames)
  return []
}

/** Name plus created date/time so two versions with the same name can be told apart. */
export function resumeVersionLabel(resume) {
  const title = resume?.title || 'Resume'
  const d = resume?.created_at ? new Date(resume.created_at) : null
  if (!d || Number.isNaN(d.getTime())) return title
  const date = d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' })
  const time = d.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' })
  return `${title} · ${date} ${time}`
}
