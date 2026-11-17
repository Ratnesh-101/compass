// Plain-language text for the automatic Career flow. Pure functions so they can be unit tested.

export const SAVED_RESUME_MESSAGE = 'Saved. Your resume is now your profile, so matches use it right away.'
export const SAVED_PROFILE_MESSAGE = 'Saved. Your internship matches are being updated.'
export const SAVED_DETAILS_MESSAGE = 'Saved. Your name and contact details are now on your resume.'

/** What the Career page shows after "Prepare my top 3 matches". */
export function summarizeTopMatchesResult(result) {
  const status = result?.status
  const drafts = Array.isArray(result?.drafts) ? result.drafts : []
  const prepared = drafts.filter(d => d?.status === 'prepared')
  const lines = drafts.map(d => {
    const label = [d.role_title, d.company_name].filter(Boolean).join(' at ') || `Listing ${d.opportunity_id}`
    return d.status === 'prepared' ? `${label}: ready to review` : `${label}: ${d.message || 'not prepared'}`
  })

  if (status === 'incomplete_profile') {
    return { tone: 'info', message: result?.message || 'Upload your resume first.', lines: [], preparedCount: 0, needsResume: true }
  }
  if (status === 'no_eligible_opportunities' || status === 'no_saved_opportunities') {
    return { tone: 'info', message: result?.message || 'No open internships fit your profile right now.', lines: [], preparedCount: 0, needsResume: false }
  }
  if (status === 'completed') {
    if (prepared.length === 0) {
      const alreadyDone = drafts.length === 0
      return {
        tone: alreadyDone ? 'info' : 'error',
        message: alreadyDone
          ? 'Your top matches are already prepared. Open My applications to review them.'
          : "We couldn't prepare any of them right now. Try again in a moment.",
        lines,
        preparedCount: 0,
        needsResume: false,
      }
    }
    return {
      tone: 'success',
      message: prepared.length === 1 ? '1 application is ready to review.' : `${prepared.length} applications are ready to review.`,
      lines,
      preparedCount: prepared.length,
      needsResume: false,
    }
  }
  return { tone: 'info', message: result?.message || 'Nothing was prepared.', lines, preparedCount: 0, needsResume: false }
}

/** Short "what we read" lines for the resume the student just uploaded. Nothing is invented. */
export function summarizeResumeImport(content) {
  const c = content || {}
  const lines = []
  const name = String(c.full_name || '').trim()
  const email = String(c.email || '').trim()
  if (name || email) lines.push([name, email].filter(Boolean).join(' · '))
  const edu = Array.isArray(c.education) ? c.education[0] : null
  if (edu) {
    const years = edu.start_year || edu.end_year ? ` (${[edu.start_year, edu.end_year].filter(Boolean).join('-')})` : ''
    const study = [edu.degree, edu.field_of_study].filter(Boolean).join(' in ')
    const text = [study, edu.institution].filter(Boolean).join(', ')
    if (text) lines.push(`${text}${years}`)
    if (edu.cgpa_or_grade) lines.push(`CGPA / grade: ${edu.cgpa_or_grade}`)
  }
  const skills = Array.isArray(c.skills) ? c.skills.filter(Boolean) : []
  if (skills.length) lines.push(`${skills.length} skills: ${skills.slice(0, 6).join(', ')}${skills.length > 6 ? '…' : ''}`)
  const projects = Array.isArray(c.projects) ? c.projects.length : 0
  if (projects) lines.push(projects === 1 ? '1 project' : `${projects} projects`)
  return lines
}

/** Contact details missing from a resume, in the words used on screen. */
export function missingContactDetails(content) {
  const c = content || {}
  const missing = []
  if (!String(c.full_name || '').trim()) missing.push('your name')
  if (!String(c.email || '').includes('@')) missing.push('your email')
  return missing
}

/** The "What changed" block saved on a tailored resume, normalised for display, or null for old resumes. */
export function readWhatChanged(resume) {
  const w = resume?.validation_report?.diff_summary?.what_changed
  if (!w || typeof w !== 'object') return null
  return {
    changed: Boolean(w.changed),
    lines: Array.isArray(w.lines) ? w.lines : [],
    reason: w.reason_if_unchanged || null,
    note: w.note || null,
    preview: {
      skills: Array.isArray(w.preview?.skills) ? w.preview.skills : [],
      projects: Array.isArray(w.preview?.projects) ? w.preview.projects : [],
      summary: w.preview?.summary || '',
    },
  }
}

/** Plain message for a failed "Paste a job link". Server wording wins when it is already plain. */
export function jobLinkErrorMessage(err) {
  const msg = typeof err?.message === 'string' ? err.message.trim() : ''
  if (msg && !/^HTTP \d+|Failed to fetch|NetworkError|<|\{/.test(msg) && msg.length < 240) return msg
  return "We couldn't read that link. Check it opens in your browser, or choose a job from the list below."
}

/** True when `text` looks like a link the user pasted (so the field can enable its button). */
export function looksLikeJobLink(text) {
  const t = String(text || '').trim()
  if (!t || /\s/.test(t) || t.length < 8) return false
  return /^https?:\/\/[^\s/]+\.[^\s/]+/i.test(t) || /^[a-z0-9-]+(\.[a-z0-9-]+)+\/\S+/i.test(t)
}
