// Compass Base API Client
// Handles base URL resolution, guest identity, user session, and common headers.

export const RENDER_BACKEND_URL = 'https://compass-backend-qryu-vcfv.onrender.com'

function clearObsoleteCookie() {
  if (typeof document === 'undefined') return
  try {
    document.cookie = 'compass_user_id=; path=/; expires=Thu, 01 Jan 1970 00:00:00 GMT; SameSite=Lax; Secure;'
    if (typeof window !== 'undefined' && window.location?.hostname) {
      const host = window.location.hostname
      document.cookie = `compass_user_id=; path=/; expires=Thu, 01 Jan 1970 00:00:00 GMT; SameSite=Lax; Secure; domain=${host}`
      document.cookie = `compass_user_id=; path=/; expires=Thu, 01 Jan 1970 00:00:00 GMT; SameSite=Lax; Secure; domain=.${host}`
    }
  } catch {
    /* ignore cookie cleanup error */
  }
}

// Proactively clear obsolete compass_user_id cookie from browser on script initialization
clearObsoleteCookie()

const isLocalDevHost = typeof window !== 'undefined' &&
  (window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1')

if (typeof window !== 'undefined' && isLocalDevHost) {
  try {
    localStorage.removeItem('compass_active_api_base')
  } catch {
    /* ignore storage access error */
  }
}

function resolveInitialApiBase() {
  // If hosted on a public domain (Vercel, custom domain, anything other than localhost),
  // ALWAYS use '' (same-origin relative URL) so that:
  // 1. All requests go to /api and /health on the same domain (e.g. compass-farmlytics.vercel.app)
  // 2. Vercel server-side rewrites forward traffic to Render seamlessly
  // 3. Browser ad-blockers (uBlock Origin, Brave Shields, Privacy Badger) NEVER block same-origin requests (avoids net::ERR_BLOCKED_BY_CLIENT)
  if (typeof window !== 'undefined' && !isLocalDevHost) {
    try {
      localStorage.removeItem('compass_active_api_base')
    } catch {
      /* ignore storage access error */
    }
    return ''
  }

  if (isLocalDevHost) {
    if (import.meta?.env?.VITE_API_BASE_URL) {
      return import.meta.env.VITE_API_BASE_URL.replace(/\/$/, '')
    }
    return 'http://localhost:8000'
  }
  return ''
}

export let API_BASE = resolveInitialApiBase()

export function safeHref(url) {
  if (!url || typeof url !== 'string') return '#'
  const trimmed = url.trim()
  if (/^(?:javascript|vbscript|data):/i.test(trimmed)) {
    return '#'
  }
  if (trimmed.startsWith('https://') || trimmed.startsWith('http://') || (trimmed.startsWith('/') && !trimmed.startsWith('//'))) {
    return trimmed
  }
  return '#'
}

export function setApiBase(newBase) {
  // In production on Vercel, keep same-origin '' to avoid cross-domain ad-blocker triggers
  if (typeof window !== 'undefined' && !isLocalDevHost) {
    API_BASE = ''
    try {
      localStorage.removeItem('compass_active_api_base')
    } catch {
      /* ignore */
    }
    return
  }

  API_BASE = (newBase || '').replace(/\/$/, '')
  try {
    if (API_BASE && (!isLocalDevHost || API_BASE !== RENDER_BACKEND_URL)) {
      localStorage.setItem('compass_active_api_base', API_BASE)
    } else {
      localStorage.removeItem('compass_active_api_base')
    }
  } catch {
    /* ignore storage access error */
  }
}



export const FALLBACK_TASKS = []

const DEFAULT_ACCOUNTS = ['demo@compass.app', 'researcher@compass.app']

export function getKnownAccounts() {
  try {
    const raw = localStorage.getItem('compass_known_accounts')
    if (raw) {
      const parsed = JSON.parse(raw)
      if (Array.isArray(parsed) && parsed.length > 0) {
        const merged = [...parsed]
        for (const def of DEFAULT_ACCOUNTS) {
          if (!merged.includes(def)) merged.push(def)
        }
        return merged
      }
    }
  } catch {
    /* ignore storage access error */
  }
  return DEFAULT_ACCOUNTS
}

export function addKnownAccount(email) {
  if (!email || !email.includes('@')) return
  const clean = email.trim().toLowerCase()
  const list = getKnownAccounts()
  const filtered = list.filter(e => e !== clean)
  filtered.unshift(clean)
  try {
    localStorage.setItem('compass_known_accounts', JSON.stringify(filtered.slice(0, 6)))
  } catch {
    /* ignore storage access error */
  }
}

export function getGuestToken() {
  try {
    return localStorage.getItem('compass_guest_token') || null
  } catch {
    return null
  }
}

export function getGuestId() {
  try {
    return localStorage.getItem('compass_guest_id') || null
  } catch {
    return null
  }
}

export function setGuestSession(guestId, guestToken) {
  try {
    if (guestId && guestToken) {
      localStorage.setItem('compass_guest_id', guestId)
      localStorage.setItem('compass_guest_token', guestToken)
    } else {
      localStorage.removeItem('compass_guest_id')
      localStorage.removeItem('compass_guest_token')
    }
  } catch {
    /* ignore storage access error */
  }
}

let inflightGuestSession = null

export function initGuestSession() {
  if (!inflightGuestSession) {
    inflightGuestSession = runGuestSessionInit().finally(() => {
      inflightGuestSession = null
    })
  }
  return inflightGuestSession
}

async function runGuestSessionInit() {
  try {
    const existingToken = getGuestToken()
    const res = await fetch(`${API_BASE}/api/guest/session`, {
      method: existingToken ? 'GET' : 'POST',
      headers: existingToken ? { 'x-guest-token': existingToken } : {},
      credentials: 'include',
    })
    if (res.ok) {
      const data = await res.json()
      if (data.guest_id && data.guest_token) {
        setGuestSession(data.guest_id, data.guest_token)
        return data
      }
    }
    if (existingToken) {
      const freshRes = await fetch(`${API_BASE}/api/guest/session`, {
        method: 'POST',
        credentials: 'include',
      })
      if (freshRes.ok) {
        const data = await freshRes.json()
        if (data.guest_id && data.guest_token) {
          setGuestSession(data.guest_id, data.guest_token)
          return data
        }
      }
    }
  } catch (err) {
    console.warn('[Compass] Guest session init failed:', err)
  }
  return null
}

export function getCurrentUserId() {
  const uid = localStorage.getItem('compass_user_email') || localStorage.getItem('compass_user_id')
  if (uid && uid.trim() && uid.includes('@')) {
    return uid.trim().toLowerCase()
  }
  return null
}

export function setCurrentUserId(userId) {
  if (userId && userId.trim()) {
    const clean = userId.trim().toLowerCase()
    if (clean.includes('@')) {
      localStorage.setItem('compass_user_email', clean)
      addKnownAccount(clean)
    }
  } else {
    localStorage.removeItem('compass_user_email')
  }
  try {
    localStorage.removeItem('compass_user_id')
  } catch {
    /* ignore storage access error */
  }
  // Proactively clear obsolete compass_user_id cookie that triggers impersonation errors
  clearObsoleteCookie()
}

export function getAuthHeaders(extraHeaders = {}) {
  const headers = { ...extraHeaders }
  // Identity comes exclusively from verified guest token or authenticated session.
  // Never send raw x-user-id or x-guest-id headers.
  const guestToken = getGuestToken()
  if (guestToken) {
    headers['x-guest-token'] = guestToken
  }
  try {
    const token = typeof localStorage !== 'undefined' ? localStorage.getItem('compass_auth_token') : null
    if (token && !headers['Authorization']) {
      headers['Authorization'] = `Bearer ${token}`
    }
  } catch {
    /* ignore storage access error */
  }
  return headers
}

/**
 * Perform a fetch request with automatic guest token minting and 1-time retry on 401/403.
 * Strict rules:
 * - Retry only for guest identities, max 1 retry (_retried: true).
 * - NEVER replace or overwrite an authenticated user's identity. If authenticated, dispatch 'compass:session_expired'.
 * - NEVER retry if the body is a stream or options.isStreaming is true.
 */
export async function fetchWithGuestRetry(url, options = {}) {
  const mergedHeaders = getAuthHeaders(options.headers || {})
  const init = {
    ...options,
    headers: mergedHeaders,
    credentials: options.credentials || 'include',
  }
  let res = await fetch(url, init)
  if ((res.status === 401 || res.status === 403) && !options._retried) {
    const hasAuthToken = typeof localStorage !== 'undefined' && Boolean(localStorage.getItem('compass_auth_token'))
    const hasAuthEmail = typeof localStorage !== 'undefined' && Boolean(localStorage.getItem('compass_user_email'))
    const isAuthenticated = hasAuthToken || hasAuthEmail

    if (isAuthenticated) {
      if (typeof window !== 'undefined' && typeof window.dispatchEvent === 'function') {
        const CustomEventClass = typeof window.CustomEvent === 'function'
          ? window.CustomEvent
          : (typeof globalThis.CustomEvent === 'function' ? globalThis.CustomEvent : null)
        const event = CustomEventClass
          ? new CustomEventClass('compass:session_expired', {
              detail: { message: 'Session expired. Please sign in again.' }
            })
          : { type: 'compass:session_expired', detail: { message: 'Session expired. Please sign in again.' } }
        window.dispatchEvent(event)
      }
      return res
    }

    // Never retry if this is a streaming request or streaming body already started
    if (options.isStreaming || (typeof globalThis.ReadableStream !== 'undefined' && options.body instanceof globalThis.ReadableStream)) {
      return res
    }

    // Retry only for unauthenticated guest identities, exactly once
    const guestData = await initGuestSession()
    if (guestData && (guestData.guest_token || guestData.token)) {
      const retryHeaders = getAuthHeaders(options.headers || {})
      res = await fetch(url, {
        ...options,
        headers: retryHeaders,
        credentials: options.credentials || 'include',
        _retried: true,
      })
    }
  }
  return res
}

let inflightHealthCheck = null

export async function checkBackendHealth(force = false) {
  if (inflightHealthCheck && !force) {
    return inflightHealthCheck
  }

  inflightHealthCheck = (async () => {
    // Helper to probe an endpoint with a custom timeout
    const probe = async (url, timeoutMs) => {
      const controller = new AbortController()
      const timeoutId = setTimeout(() => controller.abort(), timeoutMs)
      try {
        const res = await fetch(url, {
          method: 'GET',
          headers: getAuthHeaders(),
          signal: controller.signal,
        })
        clearTimeout(timeoutId)
        return res
      } catch (err) {
        clearTimeout(timeoutId)
        throw err
      }
    }

    try {
      // 1. If currently configured for localhost, test localhost first with a quick 2.5s timeout
      const isLocal = isLocalDevHost || API_BASE.includes('localhost') || API_BASE.includes('127.0.0.1')
      let res = null

      if (isLocal) {
        try {
          res = await probe(`${API_BASE}/health`, 2500)
        } catch {
          if (!isLocalDevHost) {
            console.info(`[Compass] Local backend (${API_BASE}) unreachable. Attempting cloud backend: ${RENDER_BACKEND_URL}`)
            try {
              res = await probe(`${RENDER_BACKEND_URL}/health`, 35000)
              if (res && (res.ok || res.status === 200)) {
                setApiBase(RENDER_BACKEND_URL)
              }
            } catch {
              return 'Waking up the server…'
            }
          } else {
            return 'Local backend starting…'
          }
        }
      } else {
        // 2. Production (Vercel) — ALWAYS use same-origin /health.
        // Vercel rewrites forward to Render server-side.
        // Same-origin calls are NEVER blocked by ad-blockers (fixes net::ERR_BLOCKED_BY_CLIENT).
        API_BASE = ''
        res = await probe('/health', 35000)
      }

      if (!res) {
        return 'Waking up the server…'
      }

      if (!res.ok) {
        // If HTTP 502/503/504, Render or proxy is still booting up
        if ([502, 503, 504].includes(res.status)) {
          return 'Waking up the server…'
        }
        return 'Backend Error • HTTP ' + res.status
      }

      const data = await res.json()
      if (data.db_connected || data.status === 'ok' || data.database === 'connected') {
        return 'Live • Neon Connected'
      }
      return 'Live • Edge Connected'
    } catch {
      return 'Waking up the server…'
    } finally {
      inflightHealthCheck = null
    }
  })()

  return inflightHealthCheck
}

export function mapHttpErrorToUserMessage(status, fallbackMessage = 'An unexpected error occurred. Please try again.') {
  if (status === 401) {
    return 'Your session has expired. Please sign in or refresh the page.'
  }
  if (status === 403 || status === 404) {
    return 'The requested resource was not found or you do not have permission to access it.'
  }
  if (status >= 500) {
    return 'The server encountered an error generating the file. Please try again later.'
  }
  return fallbackMessage
}

export async function downloadAuthedFile(url, fallbackFilename = 'download') {
  let res
  try {
    res = await fetchWithGuestRetry(url)
  } catch {
    const error = new Error('Network error: Unable to connect to server. Please check your connection.')
    error.status = 0
    throw error
  }

  if (!res.ok) {
    const message = mapHttpErrorToUserMessage(res.status, `Failed to download file (HTTP ${res.status}).`)
    const error = new Error(message)
    error.status = res.status
    throw error
  }

  let filename = fallbackFilename
  const disposition = res.headers?.get?.('content-disposition') || res.headers?.get?.('Content-Disposition')
  if (disposition) {
    const match = disposition.match(/filename\*?=(?:UTF-8'')?"?([^";\r\n]+)"?/i)
    if (match && match[1]) {
      filename = decodeURIComponent(match[1].trim().replace(/^"+|"+$/g, ''))
    }
  }

  const blob = await res.blob()
  const urlHelper = (typeof window !== 'undefined' ? window.URL : null) || globalThis.URL || URL
  const doc = typeof document !== 'undefined' ? document : (typeof globalThis !== 'undefined' ? globalThis.document : null)
  if (doc && urlHelper && typeof urlHelper.createObjectURL === 'function') {
    const blobUrl = urlHelper.createObjectURL(blob)
    try {
      const a = doc.createElement('a')
      if (a) {
        if (a.style) a.style.display = 'none'
        a.href = blobUrl
        a.download = filename
        if (doc.body) doc.body.appendChild(a)
        if (typeof a.click === 'function') a.click()
        if (a.parentNode) a.parentNode.removeChild(a)
      }
    } finally {
      setTimeout(() => {
        try {
          urlHelper.revokeObjectURL(blobUrl)
        } catch { /* ignore */ }
      }, 1000)
    }
  }
  return { success: true, filename, blob }
}

export async function openAuthedHtml(url, { printOnLoad = true, popup = null } = {}) {
  let res
  try {
    res = await fetchWithGuestRetry(url)
  } catch {
    if (popup && typeof popup.close === 'function' && !popup.closed) {
      try { popup.close() } catch { /* ignore */ }
    }
    const error = new Error('Network error: Unable to connect to server. Please check your connection.')
    error.status = 0
    throw error
  }

  if (!res.ok) {
    if (popup && typeof popup.close === 'function' && !popup.closed) {
      try { popup.close() } catch { /* ignore */ }
    }
    const message = mapHttpErrorToUserMessage(res.status, `Failed to load document for printing (HTTP ${res.status}).`)
    const error = new Error(message)
    error.status = res.status
    throw error
  }

  const html = await res.text()
  const urlHelper = (typeof window !== 'undefined' ? window.URL : null) || globalThis.URL || URL
  const doc = typeof document !== 'undefined' ? document : (typeof globalThis !== 'undefined' ? globalThis.document : null)
  if (urlHelper && typeof urlHelper.createObjectURL === 'function') {
    const blob = new Blob([html], { type: 'text/html;charset=utf-8' })
    const blobUrl = urlHelper.createObjectURL(blob)

    if (popup && typeof popup.close === 'function' && !popup.closed) {
      try {
        try { popup.opener = null } catch { /* ignore */ }
        if (popup.location) {
          popup.location.href = blobUrl
        }
        if (printOnLoad) {
          popup.onload = () => {
            try {
              if (typeof popup.focus === 'function') popup.focus()
              if (typeof popup.print === 'function') popup.print()
            } catch { /* ignore */ }
          }
        }
      } catch {
        if (doc) renderInHiddenIframe(blobUrl, printOnLoad)
      }
      const revokeTimer = setTimeout(() => {
        try {
          urlHelper.revokeObjectURL(blobUrl)
        } catch { /* ignore */ }
      }, 60000)
      if (revokeTimer && typeof revokeTimer.unref === 'function') {
        revokeTimer.unref()
      }
    } else if (doc) {
      renderInHiddenIframe(blobUrl, printOnLoad)
    }
  }
  return { success: true, html }
}

function renderInHiddenIframe(blobUrl, printOnLoad) {
  if (typeof document === 'undefined') return
  const iframe = document.createElement('iframe')
  iframe.style.position = 'fixed'
  iframe.style.right = '0'
  iframe.style.bottom = '0'
  iframe.style.width = '0'
  iframe.style.height = '0'
  iframe.style.border = '0'
  iframe.style.visibility = 'hidden'
  try { iframe.setAttribute('sandbox', 'allow-modals allow-same-origin') } catch { /* ignore */ }
  document.body.appendChild(iframe)

  iframe.onload = () => {
    if (printOnLoad) {
      setTimeout(() => {
        try {
          iframe.contentWindow?.focus()
          iframe.contentWindow?.print()
        } catch { /* ignore */ }
        setTimeout(() => {
          if (iframe.parentNode) iframe.parentNode.removeChild(iframe)
          try { (window.URL || URL).revokeObjectURL(blobUrl) } catch { /* ignore */ }
        }, 3000)
      }, 300)
    } else {
      setTimeout(() => {
        if (iframe.parentNode) iframe.parentNode.removeChild(iframe)
        try { (window.URL || URL).revokeObjectURL(blobUrl) } catch { /* ignore */ }
      }, 5000)
    }
  }
  iframe.src = blobUrl
}
