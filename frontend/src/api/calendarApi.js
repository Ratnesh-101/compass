// Calendar & Dynamic Scheduling API

import { API_BASE, getAuthHeaders, getCurrentUserId, setCurrentUserId, safeHref, fetchWithTimeout } from './baseClient.js'
import { classifyAuthMe } from '../utils/firstRun.js'
import { commitErrorText } from '../utils/scheduleHonesty.js'

export async function fetchCalendarStatus() {
  try {
    const res = await fetch(`${API_BASE}/api/calendar/status`, {
      headers: getAuthHeaders(),
    })
    if (!res.ok) return { connected: false, mode: 'demo', account_email: null, is_simulated: false }
    const data = await res.json()
    return data.calendar || { connected: false, mode: 'demo', is_simulated: false }
  } catch {
    return { connected: false, mode: 'demo', account_email: null, is_simulated: false }
  }
}

/**
 * Ask the server who we are and say how sure it is.
 * status: 'authenticated' | 'unauthenticated' (explicit 401 / authenticated:false) |
 * 'transient' (network error, timeout, 5xx - the caller must keep stored identity).
 */
export async function fetchCurrentUserResult() {
  try {
    const res = await fetchWithTimeout(`${API_BASE}/api/auth/me`, {
      headers: getAuthHeaders(),
    })
    let data = null
    if (res.ok) {
      try {
        data = await res.json()
      } catch {
        return { status: 'transient', user: null }
      }
    }
    const status = classifyAuthMe(res.status, data)
    if (status === 'authenticated' && data.user_id) {
      setCurrentUserId(data.user_id)
    }
    return { status, user: status === 'authenticated' ? data : (res.ok ? data : null) }
  } catch {
    return { status: 'transient', user: null }
  }
}

export async function fetchCurrentUser() {
  const result = await fetchCurrentUserResult()
  return result.user
}

export async function logoutUser() {
  setCurrentUserId('')
  try {
    await fetch(`${API_BASE}/api/auth/logout`, { method: 'POST', headers: getAuthHeaders() })
  } catch {
    /* ignore logout network failure */
  }
  return { status: 'ok' }
}

export async function checkGoogleOAuthStatus() {
  try {
    const res = await fetch(`${API_BASE}/api/calendar/connect?redirect=false`, {
      headers: getAuthHeaders(),
    })
    if (!res.ok) return { configured: false, status: 'error' }
    const data = await res.json()
    return {
      configured: Boolean(data.configured),
      status: data.status || (data.configured ? 'ok' : 'not_configured'),
      url: data.url,
      message: data.message,
    }
  } catch {
    return { configured: false, status: 'error' }
  }
}

export async function quickConnectUser(email) {
  const clean = email.trim().toLowerCase()
  const res = await fetch(`${API_BASE}/api/auth/quick-connect`, {
    method: 'POST',
    headers: getAuthHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({ email: clean }),
  })
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  const data = await res.json()
  setCurrentUserId(clean)
  return data
}

export async function syncCalendarNow() {
  const res = await fetch(`${API_BASE}/api/calendar/sync-now`, {
    method: 'POST',
    headers: getAuthHeaders({ 'Content-Type': 'application/json' }),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || err.message || `HTTP ${res.status}`)
  }
  return await res.json()
}

export function getGoogleOAuthConnectUrl(loginHint = null) {
  let url = `${API_BASE}/api/calendar/connect?redirect=true`
  const hint = (typeof loginHint === 'string' && loginHint) || getCurrentUserId()
  if (typeof hint === 'string' && hint.includes('@')) url += `&login_hint=${encodeURIComponent(hint)}`
  return safeHref(url)
}


export async function disconnectCalendar() {
  try {
    const res = await fetch(`${API_BASE}/api/calendar/disconnect`, {
      method: 'POST',
      headers: getAuthHeaders(),
    })
    return await res.json()
  } catch {
    return { status: 'ok' }
  }
}

export async function fetchCalendarAvailability(startDate, endDate) {
  try {
    let url = `${API_BASE}/api/calendar/availability`
    const params = new URLSearchParams()
    if (startDate) params.append('start_date', startDate)
    if (endDate) params.append('end_date', endDate)
    if (params.toString()) url += `?${params.toString()}`

    const res = await fetch(url, { headers: getAuthHeaders() })
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    const json = await res.json()
    return json.data || json
  } catch (err) {
    // Surface the failure instead of pretending the week is empty; callers keep their previous data.
    console.warn('[Compass Calendar Availability]', err)
    return { calendar_error: err?.message || 'Request failed' }
  }
}

export async function proposeSchedule({ targetDate, domain, taskIds } = {}) {
  const payload = {}
  if (targetDate) payload.target_date = targetDate
  if (domain && domain !== 'all') payload.domain = domain
  if (taskIds && taskIds.length > 0) payload.task_ids = taskIds

  const res = await fetch(`${API_BASE}/api/schedule/propose`, {
    method: 'POST',
    headers: getAuthHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify(payload),
  })
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  const json = await res.json()
  return json.data || json
}

export async function commitSchedule(assignments, rationale = 'Committed via Schedule View') {
  const res = await fetch(`${API_BASE}/api/schedule/commit`, {
    method: 'POST',
    headers: getAuthHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({ assignments, rationale }),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(commitErrorText(err) || `HTTP ${res.status}`)
  }
  const json = await res.json()
  return json.data || json
}

export async function fetchSchedulingPreferences() {
  try {
    const res = await fetch(`${API_BASE}/api/calendar/preferences`, { headers: getAuthHeaders() })
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    return await res.json()
  } catch {
    return {
      work_start_time: '09:00:00',
      work_end_time: '18:00:00',
      work_days: [1, 2, 3, 4, 5],
      buffer_minutes: 15,
      preferred_focus: 'morning',
    }
  }
}

export function getCalendarExportUrl(domain) {
  const params = new URLSearchParams()
  if (domain && domain !== 'all') params.append('domain', domain)
  const qs = params.toString()
  return safeHref(qs ? `${API_BASE}/api/calendar/export.ics?${qs}` : `${API_BASE}/api/calendar/export.ics`)
}


export async function checkReactiveSchedule(currentTime = null) {
  const body = currentTime ? { current_time: currentTime } : {}
  const res = await fetch(`${API_BASE}/api/schedule/reactive-check`, {
    method: 'POST',
    headers: getAuthHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify(body),
  })
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return await res.json()
}

export async function fetchScheduleConflicts() {
  const res = await fetch(`${API_BASE}/api/schedule/conflicts`, { headers: getAuthHeaders() })
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return await res.json()
}
