// Pure helpers for Internship Radar freshness labels.
// Mirrors the backend contract: RECENCY_FRESH_DAYS = 14, `verification_age_days`
// (int or null) and `needs_recheck` (bool) on every opportunity.

export const FRESH_DAYS = 14
export const NOT_VERIFIED_RECENTLY = 'Not verified recently'

function parseDate(value) {
  if (!value) return null
  const d = new Date(value)
  return Number.isNaN(d.getTime()) ? null : d
}

function formatAbsolute(date) {
  return date.toLocaleDateString('en-GB', {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
    timeZone: 'UTC',
  })
}

/**
 * "Last verified N days ago" for recent checks. When the age is unknown, or
 * older than FRESH_DAYS, show the absolute date if we have one, otherwise
 * "Not verified recently". Never invents a date.
 */
export function formatVerifiedAge(ageDays, absoluteDate = null) {
  const isInt = typeof ageDays === 'number' && Number.isFinite(ageDays) && ageDays >= 0
  if (isInt && ageDays <= FRESH_DAYS) {
    const n = Math.floor(ageDays)
    if (n === 0) return 'Last verified today'
    if (n === 1) return 'Last verified 1 day ago'
    return `Last verified ${n} days ago`
  }
  const date = parseDate(absoluteDate)
  if (isInt && date) return `Last verified ${formatAbsolute(date)}`
  return NOT_VERIFIED_RECENTLY
}

/** Convenience wrapper taking an opportunity object. */
export function formatOpportunityVerifiedAge(opportunity) {
  const opp = opportunity || {}
  return formatVerifiedAge(
    opp.verification_age_days ?? null,
    opp.last_verified_at || opp.last_checked_at || null,
  )
}

/** True only when the backend flagged the listing as needing a re-check. */
export function needsRecheck(opportunity) {
  return opportunity?.needs_recheck === true
}

/**
 * True when at least one loaded listing carries a confirmed close date.
 * Empty / not-yet-loaded lists return null-ish false via hasLoaded in caller.
 */
export function anyConfirmedDeadline(opportunities) {
  if (!Array.isArray(opportunities)) return false
  return opportunities.some((o) => Boolean(o && o.confirmed_close_date))
}

/** Show the "no confirmed deadline" note only for a loaded, non-empty list with none. */
export function shouldShowNoDeadlineNote(opportunities) {
  return Array.isArray(opportunities) && opportunities.length > 0 && !anyConfirmedDeadline(opportunities)
}
