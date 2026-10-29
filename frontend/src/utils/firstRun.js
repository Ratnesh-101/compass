// Pure helpers for first-run resilience: a brand-new guest may hit a backend that is
// still asleep (free-tier cold start), so every decision here separates "the server
// said no" from "the server did not answer".

export const MIN_MINT_BACKOFF_MS = 30000
export const MAX_MINT_BACKOFF_MS = 5 * 60000
export const DB_WAKING_STATUS = 'Database waking up…'
export const SERVER_WAKING_STATUS = 'Waking up the server…'
export const REQUEST_TIMEOUT_MS = 30000
export const SEED_TIMEOUT_MS = 45000

/**
 * Classify a GET /api/auth/me outcome.
 * status 0 / null means the request never got an answer (network error, timeout).
 * Only an explicit "not signed in" answer is 'unauthenticated'; everything else
 * that is not a clean answer is 'transient' and must never clear stored identity.
 */
export function classifyAuthMe(status, data) {
  if (status === 401) return 'unauthenticated'
  if (typeof status === 'number' && status >= 200 && status < 300) {
    if (data && data.authenticated === false) return 'unauthenticated'
    if (data && (data.authenticated || (typeof data.email === 'string' && data.email.includes('@')))) {
      return 'authenticated'
    }
    return 'unauthenticated'
  }
  return 'transient'
}

/** What to do with the locally stored identity for a classification. */
export function identityActionFor(classification) {
  if (classification === 'authenticated') return 'set'
  if (classification === 'unauthenticated') return 'clear'
  return 'keep'
}

/** A guest token is only re-minted when the server says it is invalid (401). */
export function shouldRemintGuest(status) {
  return status === 401
}

/** Milliseconds to wait before the next guest-mint attempt (honours Retry-After, min 30 s). */
export function computeMintBackoffMs(retryAfterHeader) {
  const seconds = Number.parseInt(retryAfterHeader, 10)
  const requested = Number.isFinite(seconds) && seconds > 0 ? seconds * 1000 : 0
  return Math.min(Math.max(requested, MIN_MINT_BACKOFF_MS), MAX_MINT_BACKOFF_MS)
}

export function canAttemptMint(now, blockedUntil) {
  return !blockedUntil || now >= blockedUntil
}

/** Map a /health JSON payload to the status string shown in the UI. */
export function mapHealthPayload(data) {
  if (data && data.db_connected === false) return DB_WAKING_STATUS
  if (data && (data.db_connected || data.status === 'ok' || data.database === 'connected')) {
    return 'Live • Neon Connected'
  }
  return 'Live • Edge Connected'
}

/** True only when the backend (including its database) is ready. */
export function isBackendOnline(status) {
  const s = String(status || '').toLowerCase()
  if (s.includes('waking')) return false
  return s.includes('neon') || s.includes('live') || s.includes('connected') || s.includes('ready')
}

const OAUTH_ERROR_MESSAGES = {
  access_denied: 'Google sign-in was cancelled or access was denied.',
  not_configured: 'Google sign-in is not configured on this server.',
  missing_code: 'Google did not return an authorization code. Please try again.',
  missing_state: 'The sign-in security check failed. Please try again.',
  invalid_state: 'The sign-in security check failed. Please try again.',
  expired_state: 'The sign-in attempt timed out. Please try again.',
  replayed_state: 'That sign-in link was already used. Please try again.',
  token_exchange_failed: 'Google sign-in could not be completed. Please try again.',
  database_error: 'We could not save your sign-in right now. Please try again shortly.',
  invalid_userinfo: 'We could not read a verified email from Google.',
  temporarily_unavailable: 'Google sign-in is temporarily unavailable. Please try again shortly.',
  server_error: 'Google sign-in is temporarily unavailable. Please try again shortly.',
}
export const GENERIC_OAUTH_ERROR = 'Sign-in did not complete. Please try again.'

/** Human message for an OAuth error code; unknown codes map to a generic message. */
export function oauthErrorMessage(code) {
  const key = String(code || '').trim().toLowerCase()
  return Object.prototype.hasOwnProperty.call(OAUTH_ERROR_MESSAGES, key)
    ? OAUTH_ERROR_MESSAGES[key]
    : GENERIC_OAUTH_ERROR
}

const OAUTH_PARAMS = ['calendar_connected', 'calendar_error', 'oauth_error', 'select_account']

/**
 * Parse the OAuth return query string. The ?email= value is deliberately NOT returned:
 * success must be confirmed by the server, never taken from the URL.
 */
export function parseOAuthReturn(search) {
  const params = new URLSearchParams(search || '')
  if (params.get('calendar_connected') === 'true') return { kind: 'connected' }
  if (params.get('calendar_error')) {
    return { kind: 'error', message: oauthErrorMessage(params.get('calendar_error')) }
  }
  if (params.get('oauth_error')) {
    return { kind: 'error', message: oauthErrorMessage(params.get('oauth_error')) }
  }
  if (params.has('select_account')) return { kind: 'select_account' }
  return { kind: 'none' }
}

/** Return the query string (with leading ?, or '') without the OAuth-return params. */
export function stripOAuthParams(search) {
  const params = new URLSearchParams(search || '')
  const wasConnected = params.has('calendar_connected')
  for (const key of OAUTH_PARAMS) params.delete(key)
  if (wasConnected) params.delete('email')
  const rest = params.toString()
  return rest ? `?${rest}` : ''
}

/** Email sign-in (quick-connect) endpoint only exists in development. */
export function isEmailSignInEnabled(env) {
  return Boolean(env && env.DEV)
}
