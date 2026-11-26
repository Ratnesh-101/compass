/**
 * Pure timezone and local-time formatting helpers for calendar views.
 * Scheduled timestamps arrive from the API in UTC (e.g. "2026-11-25T03:30:00" or with Z).
 */

/**
 * Parses an API instant into a Date object.
 * Strings without a timezone designator are treated as UTC by appending 'Z'.
 * Accepts Date instances, numbers (epoch ms), and ISO strings with offset or Z.
 *
 * @param {Date|string|number|null|undefined} value
 * @returns {Date|null}
 */
export function parseApiInstant(value) {
  if (value == null || value === '') return null
  if (value instanceof Date) {
    return Number.isNaN(value.getTime()) ? null : value
  }
  if (typeof value === 'number') {
    const d = new Date(value)
    return Number.isNaN(d.getTime()) ? null : d
  }
  if (typeof value !== 'string') return null

  let s = value.trim()
  if (!s) return null

  // Normalize space separator to 'T' (e.g. "2026-11-25 03:30:00")
  if (/^\d{4}-\d{2}-\d{2}\s\d{2}:\d{2}/.test(s)) {
    s = s.replace(' ', 'T')
  }

  // Date-only string "YYYY-MM-DD"
  if (/^\d{4}-\d{2}-\d{2}$/.test(s)) {
    const d = new Date(`${s}T00:00:00Z`)
    return Number.isNaN(d.getTime()) ? null : d
  }

  // Check if it already has a timezone indicator (Z or offset like +05:30 / -0500)
  // after the time component
  const hasTimezone = /(?:Z|[+-]\d{2}(?::?\d{2})?)$/i.test(s) && (s.includes('T') || s.includes(':'))

  const strToParse = hasTimezone ? s : `${s}Z`
  const d = new Date(strToParse)
  return Number.isNaN(d.getTime()) ? null : d
}

export const TIMEZONE_FRIENDLY_NAMES = {
  'Asia/Calcutta': 'India Standard Time (IST)',
  'Asia/Kolkata': 'India Standard Time (IST)',
}

/**
 * Returns a user-friendly label for an IANA time zone, falling back to the raw name.
 * Maps 'Asia/Calcutta' and 'Asia/Kolkata' to 'India Standard Time (IST)'.
 *
 * @param {string|null|undefined} tz
 * @returns {string}
 */
export function friendlyTimeZone(tz) {
  if (!tz || typeof tz !== 'string') return ''
  return TIMEZONE_FRIENDLY_NAMES[tz] || tz
}

export const friendly_timezone = friendlyTimeZone
export const formatTimeZone = friendlyTimeZone

/**
 * Returns the browser's resolved time zone identifier or friendly label.
 *
 * @returns {string}
 */
export function getLocalTimeZone() {
  try {
    const tz = Intl.DateTimeFormat().resolvedOptions().timeZone
    const raw = typeof tz === 'string' && tz ? tz : 'UTC'
    return friendlyTimeZone(raw)
  } catch {
    return 'UTC'
  }
}

/**
 * Formats an instant in "9:00 AM" style using Intl.DateTimeFormat(undefined, {hour:'numeric', minute:'2-digit'})
 * in the browser time zone.
 *
 * @param {Date|string|number} value
 * @param {Intl.DateTimeFormatOptions} [opts]
 * @returns {string}
 */
export function formatLocalTime(value, opts = {}) {
  const d = parseApiInstant(value)
  if (!d) return ''
  return new Intl.DateTimeFormat(undefined, {
    hour: 'numeric',
    minute: '2-digit',
    ...opts,
  }).format(d)
}

/**
 * Formats a start and end instant as a local time range, e.g. "9:00 AM - 12:00 PM".
 *
 * @param {Date|string|number} start
 * @param {Date|string|number} end
 * @returns {string}
 */
export function formatLocalTimeRange(start, end) {
  const s = formatLocalTime(start)
  const e = formatLocalTime(end)
  if (!s && !e) return ''
  if (!s) return e
  if (!e) return s
  return `${s} - ${e}`
}

/**
 * Formats an instant in "Wed, Nov 25, 9:00 AM" style.
 *
 * @param {Date|string|number} value
 * @returns {string}
 */
export function formatLocalDateTime(value) {
  const d = parseApiInstant(value)
  if (!d) return ''
  return new Intl.DateTimeFormat(undefined, {
    weekday: 'short',
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  }).format(d)
}

/**
 * Returns the "YYYY-MM-DD" date key of the instant in the browser time zone.
 *
 * @param {Date|string|number} value
 * @returns {string}
 */
export function localDateKey(value) {
  if (typeof value === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(value.trim())) {
    return value.trim()
  }
  const d = parseApiInstant(value)
  if (!d) return ''
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

/**
 * Returns the minutes since local midnight (0..1439) of the instant in the browser time zone.
 *
 * @param {Date|string|number} value
 * @returns {number}
 */
export function minutesSinceLocalMidnight(value) {
  const d = parseApiInstant(value)
  if (!d) return 0
  return d.getHours() * 60 + d.getMinutes()
}
