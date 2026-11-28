// Pure helpers for the My resume editor sections (education, projects, experience, links).
// Kept free of React so they are unit-testable.
import { getSafeHttpUrl } from '../../utils/safeUrl.js'

export const MIN_YEAR = 1950
export const MAX_YEAR = 2100
export const WORK_AUTH_PLACEHOLDER = 'e.g. Authorised to work in India'

export const SECTION_IDS = {
  education: 'resume-section-education',
  projects: 'resume-section-projects',
  experience: 'resume-section-experience',
  links: 'resume-section-links',
}

const MISSING_FIELD_SECTION = {
  degree: 'education',
  graduation_year: 'education',
  education: 'education',
  projects: 'projects',
  experience: 'experience',
  linkedin_url: 'links',
  github_url: 'links',
  portfolio_url: 'links',
  work_authorization: 'links',
  notice_or_availability: 'links',
}

/** Which editor section a missing application field belongs to (null when unknown). */
export function sectionForMissingField(key) {
  return Object.prototype.hasOwnProperty.call(MISSING_FIELD_SECTION, key) ? MISSING_FIELD_SECTION[key] : null
}

export const emptyEducation = () => ({ institution: '', degree: '', field_of_study: '', start_year: '', end_year: '', cgpa_or_grade: '' })
export const emptyProject = () => ({ title: '', description: '', technologies: '', link: '' })
export const emptyExperience = () => ({ company: '', role_title: '', start_date: '', end_date: '', is_current: false, highlights: '' })

const factories = { education: emptyEducation, projects: emptyProject, experience: emptyExperience }

/** Reducer for the list sections. Actions: add, remove, update, set. Never mutates. */
export function sectionsReducer(state, action) {
  if (action.type === 'setAll') return action.sections
  if (action.type === 'setLinks') return { ...state, links: action.links }
  if (action.type === 'setLink') return { ...state, links: { ...(state.links || {}), [action.key]: action.value } }
  const factory = factories[action.section]
  if (!factory) return state
  const list = state[action.section] || []
  switch (action.type) {
    case 'add':
      return { ...state, [action.section]: [...list, factory()] }
    case 'remove':
      return { ...state, [action.section]: list.filter((_, i) => i !== action.index) }
    case 'update':
      if (action.index < 0 || action.index >= list.length) return state
      return {
        ...state,
        [action.section]: list.map((item, i) => (i === action.index ? { ...item, [action.field]: action.value } : item)),
      }
    case 'set':
      return { ...state, [action.section]: Array.isArray(action.items) ? action.items : [] }
    default:
      return state
  }
}

const blank = (v) => v === undefined || v === null || String(v).trim() === ''

function checkYear(value, label, errors, key) {
  if (blank(value)) return null
  const s = String(value).trim()
  const n = Number(s)
  if (!/^\d{4}$/.test(s) || !Number.isInteger(n) || n < MIN_YEAR || n > MAX_YEAR) {
    errors[key] = `${label} must be a year between ${MIN_YEAR} and ${MAX_YEAR}.`
    return null
  }
  return n
}

/** CGPA: a number 0-10, or free text on a 0-4 scale such as "3.6/4.0" (accepted as given). */
export function validateGrade(value) {
  if (blank(value)) return null
  const s = String(value).trim()
  const scaled = /^(\d+(?:\.\d+)?)\s*\/\s*(\d+(?:\.\d+)?)$/.exec(s)
  if (scaled) {
    const got = Number(scaled[1])
    const max = Number(scaled[2])
    if (max > 0 && max <= 10 && got >= 0 && got <= max) return null
    return 'Grade must be between 0 and the scale given (scale up to 10).'
  }
  if (/^\d+(?:\.\d+)?$/.test(s)) {
    const n = Number(s)
    return n >= 0 && n <= 10 ? null : 'CGPA must be between 0 and 10.'
  }
  return 'Enter a CGPA from 0 to 10, or a grade like 3.6/4.0.'
}

/** Returns { errors, value }. errors is keyed by field name; empty when valid. */
export function validateEducation(item) {
  const errors = {}
  if (blank(item.institution)) errors.institution = 'Institution is required.'
  if (blank(item.degree)) errors.degree = 'Degree is required.'
  const start = checkYear(item.start_year, 'Start year', errors, 'start_year')
  const end = checkYear(item.end_year, 'End year', errors, 'end_year')
  if (start && end && end < start) errors.end_year = 'End year cannot be before start year.'
  const gradeError = validateGrade(item.cgpa_or_grade)
  if (gradeError) errors.cgpa_or_grade = gradeError
  const value = {
    institution: String(item.institution || '').trim(),
    degree: String(item.degree || '').trim(),
    field_of_study: blank(item.field_of_study) ? null : String(item.field_of_study).trim(),
    start_year: start,
    end_year: end,
    cgpa_or_grade: blank(item.cgpa_or_grade) ? null : String(item.cgpa_or_grade).trim(),
  }
  return { errors, value }
}

export function splitList(text) {
  return String(text || '').split(',').map((s) => s.trim()).filter(Boolean)
}

export function validateProject(item) {
  const errors = {}
  if (blank(item.title)) errors.title = 'Project title is required.'
  if (!blank(item.link) && !getSafeHttpUrl(item.link)) errors.link = 'Link must start with http:// or https://.'
  const value = {
    title: String(item.title || '').trim(),
    description: String(item.description || '').trim(),
    technologies: splitList(item.technologies),
    project_url: blank(item.link) ? null : getSafeHttpUrl(item.link),
  }
  return { errors, value }
}

export function validateExperience(item) {
  const errors = {}
  if (blank(item.company)) errors.company = 'Company is required.'
  if (blank(item.role_title)) errors.role_title = 'Role is required.'
  const value = {
    company: String(item.company || '').trim(),
    role_title: String(item.role_title || '').trim(),
    start_date: blank(item.start_date) ? null : String(item.start_date).trim(),
    end_date: item.is_current || blank(item.end_date) ? null : String(item.end_date).trim(),
    is_current: Boolean(item.is_current),
    highlights: String(item.highlights || '').split('\n').map((s) => s.trim()).filter(Boolean),
  }
  return { errors, value }
}

/**
 * links: { linkedin_url, github_url, portfolio_url, work_authorization, notice_period }.
 * Only the three URLs are validated (http/https); the other two are free text.
 */
export function validateLinks(links) {
  const errors = {}
  const value = {}
  for (const key of ['linkedin_url', 'github_url', 'portfolio_url']) {
    if (blank(links[key])) {
      value[key] = null
    } else {
      const safe = getSafeHttpUrl(links[key])
      if (!safe) errors[key] = 'Enter a link starting with http:// or https://.'
      value[key] = safe
    }
  }
  value.work_authorization = blank(links.work_authorization) ? null : String(links.work_authorization).trim()
  value.notice_period = blank(links.notice_period) ? null : String(links.notice_period).trim()
  return { errors, value }
}

/** Convert saved content into editor state. */
export function contentToSections(c = {}) {
  const notes = c.evidence_notes || {}
  const links = Array.isArray(c.relevant_links) ? c.relevant_links : []
  return {
    education: (c.education || []).map((e) => ({
      institution: e.institution || '', degree: e.degree || '', field_of_study: e.field_of_study || '',
      start_year: e.start_year ?? '', end_year: e.end_year ?? '', cgpa_or_grade: e.cgpa_or_grade || '',
    })),
    projects: (c.projects || []).map((p) => ({
      title: p.title || '', description: p.description || '',
      technologies: (p.technologies || []).join(', '), link: p.project_url || p.repo_url || '',
    })),
    experience: (c.experience || []).map((x) => ({
      company: x.company || '', role_title: x.role_title || '', start_date: x.start_date || '',
      end_date: x.end_date || '', is_current: Boolean(x.is_current), highlights: (x.highlights || []).join('\n'),
    })),
    links: {
      linkedin_url: c.linkedin_url || '',
      github_url: c.github_or_portfolio || '',
      portfolio_url: links[0] || '',
      work_authorization: notes.work_authorization || '',
      notice_period: notes.notice_period || '',
    },
  }
}

/**
 * Validate all sections. Returns { ok, errors, content } where errors is
 * { education: [{field: msg}], projects: [...], experience: [...], links: {...} } and content holds the
 * fields to merge into the saved ResumeContent. Fully blank list rows are dropped.
 */
export function buildSectionsContent(sections, existing = {}) {
  const errors = { education: [], projects: [], experience: [], links: {} }
  let ok = true
  const run = (name, validate, isEmpty) => {
    const out = []
    ;(sections[name] || []).forEach((item, i) => {
      if (isEmpty(item)) { errors[name][i] = {}; return }
      const r = validate(item)
      errors[name][i] = r.errors
      if (Object.keys(r.errors).length) ok = false
      else out.push(r.value)
    })
    return out
  }
  const rowEmpty = (item) => Object.values(item).every((v) => v === false || blank(v))
  const education = run('education', validateEducation, rowEmpty)
  const projects = run('projects', validateProject, rowEmpty)
  const experience = run('experience', validateExperience, rowEmpty)
  const l = validateLinks(sections.links || {})
  errors.links = l.errors
  if (Object.keys(l.errors).length) ok = false

  const notes = { ...(existing.evidence_notes || {}) }
  for (const [k, v] of [['work_authorization', l.value.work_authorization], ['notice_period', l.value.notice_period]]) {
    if (v) notes[k] = v
    else delete notes[k]
  }
  const oldLinks = Array.isArray(existing.relevant_links) ? existing.relevant_links : []
  const relevant = [l.value.portfolio_url, ...oldLinks.slice(1)].filter(Boolean)
  const oldProjects = existing.projects || []
  const content = {
    education,
    projects: projects.map((p) => {
      const prev = oldProjects.find((o) => o.title === p.title) || {}
      return { ...prev, ...p, repo_url: prev.repo_url || null }
    }),
    experience,
    linkedin_url: l.value.linkedin_url,
    github_or_portfolio: l.value.github_url,
    relevant_links: relevant,
    evidence_notes: notes,
  }
  return { ok, errors, content }
}
