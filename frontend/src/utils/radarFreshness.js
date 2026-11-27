// Pure helpers for Internship Radar freshness labels.
// Mirrors the backend contract: RECENCY_FRESH_DAYS = 14, `verification_age_days`
// (int or null) and `needs_recheck` (bool) on every opportunity.

import { daysSinceVerified } from './jobCardCleaner.js'

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

function relativeAge(days) {
  if (days === 0) return 'today'
  if (days === 1) return '1 day ago'
  return `${days} days ago`
}

/**
 * Single source of truth for the freshness labels on a radar card. Everything derives from
 * `last_verified_at` (the field backend is_fresh_open / needs_recheck use), never from
 * last_checked_at / updated_at, so the badges cannot contradict each other.
 *   fresh (<= FRESH_DAYS): 'Verified open' badge + 'Verified <age>'
 *   otherwise:             'Needs re-check' + 'Last verified <age>' / 'Never verified'
 */
export function freshnessLabels(opportunity, now = new Date()) {
  const opp = opportunity || {}
  const days = daysSinceVerified(opp.last_verified_at, now)
  const fresh = days !== null && days <= FRESH_DAYS
  const isOpen = opp.current_status === 'OPEN_CONFIRMED'
  const badgeEligible = isOpen || !opp.current_status
  let ageText
  if (days === null) ageText = 'Never verified'
  else ageText = `${fresh ? 'Verified' : 'Last verified'} ${relativeAge(days)}`
  return {
    fresh,
    showVerifiedBadge: badgeEligible && fresh,
    verifiedBadgeLabel: badgeEligible && fresh ? 'Verified open' : null,
    needsRecheck: isOpen ? !fresh : opp.needs_recheck === true,
    ageText,
  }
}

/** Age line for a card, derived from last_verified_at only. */
export function formatOpportunityVerifiedAge(opportunity, now = new Date()) {
  return freshnessLabels(opportunity, now).ageText
}

/** Re-check chip: derived from last_verified_at for open listings. */
export function needsRecheck(opportunity, now = new Date()) {
  return freshnessLabels(opportunity, now).needsRecheck
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
