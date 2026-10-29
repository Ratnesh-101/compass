/**
 * jobCardCleaner.js
 * Unified display helper for cleaning job / internship opportunity fields
 * across Radar cards, Radar detail modals, saved jobs, and Applications.
 */

export function cleanText(val) {
  if (val === null || val === undefined) return null
  const s = String(val).trim()
  const lower = s.toLowerCase()
  if (
    lower === '' ||
    lower === 'nan' ||
    lower === 'null' ||
    lower === 'undefined' ||
    lower === 'none' ||
    lower === 'n/a'
  ) {
    return null
  }
  return s
}

export function cleanSource(rawSource) {
  const clean = cleanText(rawSource)
  if (!clean) return null

  // Drop internal tool names like JobSpy and extract the user-facing source name
  // e.g. "JobSpy (Glassdoor)" -> "Glassdoor"
  const jobSpyMatch = clean.match(/jobspy\s*\(([^)]+)\)/i)
  if (jobSpyMatch && jobSpyMatch[1]) {
    return jobSpyMatch[1].trim()
  }

  // e.g. "jobspy_linkedin" -> "LinkedIn"
  if (/^jobspy_/i.test(clean)) {
    const site = clean.replace(/^jobspy_/i, '').trim()
    return site ? site.charAt(0).toUpperCase() + site.slice(1) : 'Job Board'
  }

  // Exact "JobSpy" -> "Job Board"
  if (clean.toLowerCase() === 'jobspy') {
    return 'Job Board'
  }

  return clean
}

export function formatJobLocation({
  workArrangement,
  location,
  country,
}) {
  const cleanMode = cleanText(workArrangement)
  const cleanLoc = cleanText(location)
  const cleanCtry = cleanText(country)

  const modeLower = (cleanMode || '').toLowerCase()
  const locLower = (cleanLoc || '').toLowerCase()
  const ctryLower = (cleanCtry || '').toLowerCase()

  const isRemote = modeLower === 'remote' || locLower === 'remote'
  const isHybrid = modeLower === 'hybrid' || locLower === 'hybrid'

  // Extract non-remote place from location string if mixed (e.g. "Remote, India" or "Pune")
  let place = null
  if (cleanLoc && locLower !== 'remote' && locLower !== 'flexible') {
    // If loc contains "Remote - India" or "Remote, India", clean it
    place = cleanLoc
      .replace(/remote\s*[-•·,]\s*/gi, '')
      .replace(/\s*[-•·,]\s*remote/gi, '')
      .trim()
  }

  if (!place && cleanCtry && ctryLower !== 'remote') {
    place = cleanCtry
  }

  if (isRemote) {
    if (place && place.toLowerCase() !== 'remote') {
      return `Remote, ${place}`
    }
    return 'Remote'
  }

  if (isHybrid) {
    if (place && place.toLowerCase() !== 'hybrid') {
      return `Hybrid, ${place}`
    }
    return 'Hybrid'
  }

  if (place) {
    return place
  }

  if (cleanMode) {
    return cleanMode.charAt(0).toUpperCase() + cleanMode.slice(1)
  }

  return 'Location unspecified'
}

const STALE_AFTER_DAYS = 3
const MS_PER_DAY = 86400000

// Date-only values ("2026-10-24") are calendar dates: parse them as UTC so they never shift a day
// in western timezones. Full timestamps go through the normal Date parser.
export function parseVerificationDate(value) {
  const clean = cleanText(value)
  if (!clean) return null
  const dateOnly = /^(\d{4})-(\d{2})-(\d{2})$/.exec(clean)
  const d = dateOnly
    ? new Date(Date.UTC(Number(dateOnly[1]), Number(dateOnly[2]) - 1, Number(dateOnly[3])))
    : new Date(clean)
  return Number.isNaN(d.getTime()) ? null : d
}

function utcDayNumber(d) {
  return Math.floor(Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate()) / MS_PER_DAY)
}

// Whole UTC calendar days between the verification date and now (never negative); null if unparsable.
export function daysSinceVerified(value, now = new Date()) {
  const d = parseVerificationDate(value)
  if (!d) return null
  return Math.max(0, utcDayNumber(now) - utcDayNumber(d))
}

export function isStaleVerification(value, now = new Date()) {
  const days = daysSinceVerified(value, now)
  return days !== null && days > STALE_AFTER_DAYS
}

export function lastCheckedText(value, now = new Date()) {
  const days = daysSinceVerified(value, now)
  if (days === null) return null
  if (days === 0) return 'Last checked today'
  if (days === 1) return 'Last checked 1 day ago'
  return `Last checked ${days} days ago`
}

const AMBER_BADGE = {
  bg: 'rgba(245, 166, 35, 0.1)',
  text: 'var(--brand-dark, #b47507)',
  border: 'rgba(245, 166, 35, 0.3)',
}

// A listing only earns the green "Verified open" chip while its last check is recent.
export function getVerificationBadge(status, lastVerifiedAt, now = new Date()) {
  if (status === 'OPEN_CONFIRMED') {
    if (isStaleVerification(lastVerifiedAt, now)) {
      return { label: 'Stale - re-verify before applying', ...AMBER_BADGE }
    }
    return {
      label: 'Verified open',
      bg: 'rgba(28, 138, 98, 0.08)',
      text: 'var(--domain-code, #1c8a62)',
      border: 'rgba(28, 138, 98, 0.25)',
    }
  }
  return null
}

export function getEligibilityBadge(classification) {
  switch (classification) {
    case 'ELIGIBLE':
      return {
        label: 'Eligible',
        bg: 'rgba(28, 138, 98, 0.08)',
        text: 'var(--domain-code, #1c8a62)',
        border: 'rgba(28, 138, 98, 0.25)',
      }
    case 'POTENTIAL_MATCH':
    case 'POTENTIALLY_ELIGIBLE':
      return { label: 'Possible match', ...AMBER_BADGE }
    case 'INELIGIBLE':
      return {
        label: 'Not eligible',
        bg: 'var(--danger-bg, #fdeaea)',
        text: 'var(--danger-text, #b91c1c)',
        border: 'rgba(185, 28, 28, 0.25)',
      }
    case 'INSUFFICIENT_INFORMATION':
    default:
      return {
        label: 'Eligibility unconfirmed',
        bg: 'var(--bg-card-soft)',
        text: 'var(--text-muted)',
        border: 'var(--border)',
      }
  }
}

export function cleanOpportunity(opportunity, now = new Date()) {
  if (!opportunity || typeof opportunity !== 'object') {
    return {
      company: 'Company',
      role: 'Internship Opportunity',
      locationLine: 'Location unspecified',
      salary: null,
      verificationBadge: { label: 'Needs verification', bg: 'var(--bg-card-soft)', text: 'var(--text-secondary)', border: 'var(--border)' },
      eligibilityBadge: { label: 'Eligibility unconfirmed', bg: 'var(--bg-card-soft)', text: 'var(--text-muted)', border: 'var(--border)' },
      footerLine: 'Posting date unrecorded',
      restrictions: [],
      isMissingProfile: false,
      cleanedExplanation: null,
    }
  }

  const company = cleanText(opportunity.company_name) || 'Company'
  const role = cleanText(opportunity.role_title) || 'Internship Opportunity'
  const salary = cleanText(opportunity.compensation)

  const locationLine = formatJobLocation({
    workArrangement: opportunity.work_arrangement,
    location: opportunity.location,
    country: opportunity.country,
  })

  // Verification Badge: exactly one verification chip
  let verificationBadge
  switch (opportunity.current_status) {
    case 'OPEN_CONFIRMED':
      verificationBadge = getVerificationBadge('OPEN_CONFIRMED', opportunity.last_verified_at, now)
      break
    case 'UPCOMING_CONFIRMED':
    case 'ANNOUNCED':
      verificationBadge = {
        label: 'Upcoming confirmed',
        bg: 'rgba(47, 100, 200, 0.08)',
        text: 'var(--domain-coursework, #2f64c8)',
        border: 'rgba(47, 100, 200, 0.25)',
      }
      break
    case 'CLOSED_CONFIRMED':
      verificationBadge = {
        label: 'Closed',
        bg: 'var(--bg-card-soft)',
        text: 'var(--text-muted)',
        border: 'var(--border)',
      }
      break
    default:
      verificationBadge = {
        label: 'Needs verification',
        bg: 'var(--bg-card-soft)',
        text: 'var(--text-secondary)',
        border: 'var(--border)',
      }
  }

  // Eligibility Badge: exactly one eligibility chip
  const eligibilityBadge = getEligibilityBadge(opportunity.eligibility_classification)

  // Restrictions (Drop separate "Location: India" tag per rule 4)
  const restrictions = []
  const req = opportunity.requirements
  if (req && typeof req === 'object') {
    if (req.eligible_graduation_years && req.eligible_graduation_years.length > 0) {
      restrictions.push(`Batch: ${req.eligible_graduation_years.join('/')}`)
    }
    if (req.eligible_academic_years && req.eligible_academic_years.length > 0) {
      restrictions.push(`Year: ${req.eligible_academic_years.join('/')}`)
    }
    if (req.eligible_degree_types && req.eligible_degree_types.length > 0) {
      restrictions.push(`Degree: ${req.eligible_degree_types.join('/')}`)
    }
    if (req.no_active_backlogs === true) {
      restrictions.push('0 Active Backlogs')
    }
    if (req.work_auth_required === true && opportunity.country && opportunity.country.toLowerCase() !== 'india') {
      restrictions.push(`Requires ${opportunity.country} Work Auth`)
    }
    // Drop separate "Location: India" or Location: <country> tag as locationLine handles it cleanly
  }

  // Missing profile check
  const rawExpl = cleanText(opportunity.eligibility_explanation)
  const isMissingProfile = Boolean(
    rawExpl &&
    (rawExpl.toLowerCase().includes('no candidate profile found') ||
     rawExpl.toLowerCase().includes('complete your profile in resume studio'))
  )
  const cleanedExplanation = isMissingProfile ? null : rawExpl

  // Dates & Footer
  const rawPosted = opportunity.posted_at || opportunity.confirmed_open_date
  let postedStr = null
  if (cleanText(rawPosted)) {
    try {
      const d = new Date(rawPosted)
      if (!isNaN(d.getTime())) {
        postedStr = d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
      }
    } catch {
      /* ignore */
    }
  }

  const rawVerified = opportunity.last_verified_at

  // Source name: clean, no JobSpy
  const rawSource =
    (opportunity.sources && opportunity.sources.length > 0 && opportunity.sources[0]?.source_name) ||
    opportunity.source_identifier ||
    (opportunity.official_source_confirmed ? 'Official Careers Site' : null)
  const sourceName = cleanSource(rawSource)

  // One line footer: e.g. "Posted Oct 23, Last checked 2 days ago via Glassdoor"
  const footerParts = []
  if (postedStr) {
    footerParts.push(`Posted ${postedStr}`)
  } else {
    footerParts.push('Posting date unrecorded')
  }

  const checkedText = lastCheckedText(rawVerified, now)
  if (checkedText) {
    footerParts.push(checkedText)
  }

  let footerLine = footerParts.join(', ')
  if (sourceName) {
    footerLine += ` via ${sourceName}`
  }

  return {
    company,
    role,
    locationLine,
    salary,
    verificationBadge,
    eligibilityBadge,
    footerLine,
    restrictions,
    isMissingProfile,
    cleanedExplanation,
  }
}
