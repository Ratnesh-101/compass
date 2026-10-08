// Compass Base API Client
// Handles base URL resolution, guest identity, user session, and common headers.

export const API_BASE = (
  import.meta.env.VITE_API_BASE_URL ||
  (typeof window !== 'undefined' && (window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1')
    ? 'http://localhost:8000'
    : '')
).replace(/\/$/, '')

export const FALLBACK_TASKS = [
  {
    id: '1',
    title: 'Submit Nebius Token Factory Benchmark',
    domain: 'hackathon',
    project: 'Compass',
    countdown: '2d left (Friday)',
    tags: ['nebius', 'vector', 'benchmark'],
    vector_dim: 768,
    timestamp: 'Just now'
  },
  {
    id: '2',
    title: 'Configured Matryoshka 768-dim embeddings with Nebius Token Factory',
    domain: 'code',
    project: 'Compass',
    countdown: 'Logged from CLI',
    tags: ['qwen3', 'pgvector', 'hnsw'],
    vector_dim: 768,
    timestamp: '2 mins ago'
  },
  {
    id: '3',
    title: 'CS 61C — RISC-V Pipeline Synthesis Report',
    domain: 'coursework',
    project: 'CS 61C',
    countdown: '1d left (Thursday)',
    tags: ['hardware', 'riscv', 'architecture'],
    vector_dim: 768,
    timestamp: '1 hour ago'
  },
  {
    id: '4',
    title: 'Implement Nemotron-3 Nano sub-400ms router function',
    domain: 'code',
    project: 'Compass Core',
    countdown: 'Completed',
    tags: ['nemotron', 'router', 'latency'],
    vector_dim: 768,
    timestamp: '3 hours ago'
  }
]

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
  } catch {}
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
  } catch {}
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
  } catch {}
}

export async function initGuestSession() {
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
  let uid = localStorage.getItem('compass_user_email') || localStorage.getItem('compass_user_id')
  if (uid && uid.trim() && uid.includes('@')) {
    return uid.trim().toLowerCase()
  }

  if (typeof document !== 'undefined') {
    const cookieMatch = document.cookie.match(/(?:^|;\s*)compass_user_id=([^;]+)/)
    if (cookieMatch && cookieMatch[1]) {
      uid = decodeURIComponent(cookieMatch[1]).trim().toLowerCase()
      if (uid && uid.includes('@')) {
        localStorage.setItem('compass_user_id', uid)
        localStorage.setItem('compass_user_email', uid)
        addKnownAccount(uid)
        return uid
      }
    }
  }

  return null
}

export function setCurrentUserId(userId) {
  const isHttps = typeof window !== 'undefined' && window.location.protocol === 'https:'
  if (userId && userId.trim()) {
    const clean = userId.trim().toLowerCase()
    localStorage.setItem('compass_user_id', clean)
    if (clean.includes('@')) {
      localStorage.setItem('compass_user_email', clean)
      addKnownAccount(clean)
    }
    if (isHttps) {
      try {
        document.cookie = `compass_user_id=${encodeURIComponent(clean)}; path=/; max-age=31536000; SameSite=Lax; Secure`
      } catch {}
    }
  } else {
    localStorage.removeItem('compass_user_id')
    localStorage.removeItem('compass_user_email')
    if (isHttps) {
      try {
        document.cookie = `compass_user_id=; path=/; expires=Thu, 01 Jan 1970 00:00:00 GMT; Secure`
      } catch {}
    }
  }
}

export function getAuthHeaders(extraHeaders = {}) {
  const headers = { ...extraHeaders }
  const uid = getCurrentUserId()
  if (uid) {
    headers['x-user-id'] = uid
  }
  const guestToken = getGuestToken()
  if (guestToken) {
    headers['x-guest-token'] = guestToken
  }
  const guestId = getGuestId()
  if (guestId) {
    headers['x-guest-id'] = guestId
  }
  const token = localStorage.getItem('compass_auth_token') || (typeof window !== 'undefined' && (window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1') ? 'dev-token' : '')
  if (token && !headers['Authorization']) {
    headers['Authorization'] = `Bearer ${token}`
  }
  return headers
}

export async function checkBackendHealth() {
  try {
    const controller = new AbortController()
    const timeoutId = setTimeout(() => controller.abort(), 8000)

    const res = await fetch(`${API_BASE}/health`, {
      method: 'GET',
      headers: getAuthHeaders(),
      signal: controller.signal
    })
    clearTimeout(timeoutId)

    if (!res.ok) {
      return 'Backend Error • HTTP ' + res.status
    }

    const data = await res.json()
    if (data.db_connected || data.status === 'ok') {
      return 'Live • Neon Connected'
    }
    return 'Edge Online • Syncing'
  } catch {
    return 'Waking up the server…'
  }
}
