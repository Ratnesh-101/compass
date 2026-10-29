import { API_BASE, getAuthHeaders, getGuestToken, initGuestSession } from './baseClient.js'
import { extractErrorDetail } from '../utils/careerUiHelpers.js'

async function ensureSession() {
  if (!getGuestToken()) {
    try {
      await initGuestSession()
    } catch {
      /* ignore */
    }
  }
}

export async function fetchOpportunities({
  status,
  category,
  employer_type,
  work_arrangement,
  country,
  search,
  india_only = false,
  verified_only = false,
  page = 1,
  pageSize = 20,
} = {}) {
  await ensureSession()
  const params = new URLSearchParams()
  if (status) params.set('status', status)
  if (category) params.set('category', category)
  if (employer_type) params.set('employer_type', employer_type)
  if (work_arrangement) params.set('work_arrangement', work_arrangement)
  if (country) params.set('country', country)
  if (search) params.set('search', search)
  if (india_only) params.set('india_only', 'true')
  if (verified_only) params.set('verified_only', 'true')
  params.set('page', String(page))
  params.set('page_size', String(pageSize))

  const res = await fetch(`${API_BASE}/api/opportunities?${params.toString()}`, {
    headers: getAuthHeaders(),
    credentials: 'include',
  })
  if (!res.ok) throw new Error(`Failed to fetch opportunities: HTTP ${res.status}`)
  return res.json()
}

export async function fetchRecommendedOpportunities(limit = 20, employer_type = '') {
  await ensureSession()
  const params = new URLSearchParams()
  params.set('limit', String(limit))
  if (employer_type) params.set('employer_type', employer_type)

  const res = await fetch(`${API_BASE}/api/opportunities/recommended?${params.toString()}`, {
    headers: getAuthHeaders(),
    credentials: 'include',
  })
  if (!res.ok) throw new Error(`Failed to fetch recommendations: HTTP ${res.status}`)
  return res.json()
}

export async function fetchOpenOpportunities(filters = {}) {
  await ensureSession()
  const params = new URLSearchParams()
  if (filters.category) params.set('category', filters.category)
  if (filters.employer_type) params.set('employer_type', filters.employer_type)
  if (filters.work_arrangement) params.set('work_arrangement', filters.work_arrangement)
  if (filters.india_only !== undefined) params.set('india_only', String(filters.india_only))

  const res = await fetch(`${API_BASE}/api/opportunities/open?${params.toString()}`, {
    headers: getAuthHeaders(),
    credentials: 'include',
  })
  if (!res.ok) throw new Error(`Failed to fetch open opportunities: HTTP ${res.status}`)
  return res.json()
}

export async function fetchSourceInventory() {
  const res = await fetch(`${API_BASE}/api/opportunities/sources`, {
    headers: getAuthHeaders(),
    credentials: 'include',
  })
  if (!res.ok) throw new Error(`Failed to fetch source inventory: HTTP ${res.status}`)
  return res.json()
}

export async function fetchUpcomingOpportunities() {
  const res = await fetch(`${API_BASE}/api/opportunities/upcoming`, {
    headers: getAuthHeaders(),
    credentials: 'include',
  })
  if (!res.ok) throw new Error(`Failed to fetch upcoming opportunities: HTTP ${res.status}`)
  return res.json()
}

export async function fetchRadarAnalytics() {
  const res = await fetch(`${API_BASE}/api/opportunities/analytics`, {
    headers: getAuthHeaders(),
    credentials: 'include',
  })
  if (!res.ok) throw new Error(`Failed to fetch radar analytics: HTTP ${res.status}`)
  return res.json()
}

export async function fetchWatchlist() {
  const res = await fetch(`${API_BASE}/api/opportunities/watchlist`, {
    headers: getAuthHeaders(),
    credentials: 'include',
  })
  if (!res.ok) throw new Error(`Failed to fetch watchlist: HTTP ${res.status}`)
  return res.json()
}

export async function saveOpportunity(id) {
  const res = await fetch(`${API_BASE}/api/opportunities/${id}/save`, {
    method: 'POST',
    headers: getAuthHeaders(),
    credentials: 'include',
  })
  if (!res.ok) throw new Error(`Failed to save opportunity: HTTP ${res.status}`)
  return res.json()
}

export async function unsaveOpportunity(id) {
  const res = await fetch(`${API_BASE}/api/opportunities/${id}/save`, {
    method: 'DELETE',
    headers: getAuthHeaders(),
    credentials: 'include',
  })
  if (!res.ok) throw new Error(`Failed to unsave opportunity: HTTP ${res.status}`)
  return res.json()
}

export async function fetchApplications() {
  const res = await fetch(`${API_BASE}/api/opportunities/applications`, {
    headers: getAuthHeaders(),
    credentials: 'include',
  })
  if (!res.ok) throw new Error(`Failed to fetch applications: HTTP ${res.status}`)
  return res.json()
}

export async function fetchOpportunityDetail(id) {
  await ensureSession()
  const res = await fetch(`${API_BASE}/api/opportunities/${id}`, {
    headers: getAuthHeaders(),
    credentials: 'include',
  })
  if (!res.ok) throw new Error(`Failed to fetch opportunity details: HTTP ${res.status}`)
  return res.json()
}

export async function updateApplication(id, payload) {
  const res = await fetch(`${API_BASE}/api/opportunities/${id}/application`, {
    method: 'POST',
    headers: getAuthHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify(payload),
    credentials: 'include',
  })
  if (!res.ok) throw new Error(`Failed to update application: HTTP ${res.status}`)
  return res.json()
}

export async function fetchRadarProfile() {
  const res = await fetch(`${API_BASE}/api/opportunities/profile`, {
    headers: getAuthHeaders(),
    credentials: 'include',
  })
  if (!res.ok) throw new Error(`Failed to fetch profile: HTTP ${res.status}`)
  return res.json()
}

export async function updateRadarProfile(profile) {
  const res = await fetch(`${API_BASE}/api/opportunities/profile`, {
    method: 'PUT',
    headers: getAuthHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify(profile),
    credentials: 'include',
  })
  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error(extractErrorDetail(body, `Failed to update profile: HTTP ${res.status}`))
  }
  return res.json()
}

export async function triggerRadarSync(source = 'all') {
  const res = await fetch(`${API_BASE}/api/opportunities/sync?source=${encodeURIComponent(source)}`, {
    method: 'POST',
    headers: getAuthHeaders(),
    credentials: 'include',
  })
  if (!res.ok) {
    let detail = ''
    try { detail = (await res.json())?.detail || '' } catch { /* non-JSON body */ }
    throw new Error(detail || `Sync trigger failed: HTTP ${res.status}`)
  }
  return res.json()
}

export async function verifyOpportunity(id) {
  const res = await fetch(`${API_BASE}/api/opportunities/${id}/verify`, {
    method: 'POST',
    headers: getAuthHeaders(),
    credentials: 'include',
  })
  if (!res.ok) throw new Error(`Verification failed: HTTP ${res.status}`)
  return res.json()
}
