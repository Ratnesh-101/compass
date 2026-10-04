// Tasks & Verification API

import { API_BASE, FALLBACK_TASKS, getAuthHeaders } from './baseClient'

/**
 * Fetch synchronized task list from Neon PostgreSQL with per-account isolation.
 * Accepts an optional domain string to issue a genuine server-side filtered request.
 * Returns empty array if database is empty; falls back to demo tasks only if server is unreachable.
 */
export async function fetchTasks(domain) {
  try {
    const controller = new AbortController()
    const timeoutId = setTimeout(() => controller.abort(), 4000)

    const url = domain && domain !== 'all'
      ? `${API_BASE}/api/tasks?domain=${encodeURIComponent(domain)}`
      : `${API_BASE}/api/tasks`

    const res = await fetch(url, {
      headers: getAuthHeaders(),
      signal: controller.signal
    })
    clearTimeout(timeoutId)

    if (!res.ok) {
      return FALLBACK_TASKS.map(t => ({ ...t, is_fallback: true }))
    }

    const data = await res.json()
    if (Array.isArray(data)) {
      return data
    }
    return FALLBACK_TASKS.map(t => ({ ...t, is_fallback: true }))
  } catch {
    return FALLBACK_TASKS.map(t => ({ ...t, is_fallback: true }))
  }
}

/**
 * Fetch live usage summary (total calls, tokens, cost) from /api/usage/summary.
 * Public endpoint — no auth required. Returns null on failure.
 */
export async function fetchUsageSummary() {
  try {
    const controller = new AbortController()
    const timeoutId = setTimeout(() => controller.abort(), 3000)
    const res = await fetch(`${API_BASE}/api/usage/summary`, { signal: controller.signal })
    clearTimeout(timeoutId)
    if (!res.ok) return null
    return await res.json()
  } catch {
    return null
  }
}

/**
 * Create a task or deadline directly without relying on AI chat.
 */
export async function createTask(taskData) {
  const res = await fetch(`${API_BASE}/api/tasks`, {
    method: 'POST',
    headers: getAuthHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify(taskData)
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || `Failed to create task (HTTP ${res.status})`)
  }
  return await res.json()
}

/**
 * Delete a task or deadline directly by ID without relying on AI chat.
 */
export async function deleteTask(taskId) {
  const res = await fetch(`${API_BASE}/api/tasks/${taskId}`, {
    method: 'DELETE',
    headers: getAuthHeaders(),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || `Failed to delete task (HTTP ${res.status})`)
  }
  return await res.json()
}

/**
 * Update/edit any property of a task or deadline directly.
 */
export async function updateTask(taskId, updateData) {
  const res = await fetch(`${API_BASE}/api/tasks/${taskId}`, {
    method: 'PATCH',
    headers: getAuthHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify(updateData),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || `Failed to update deadline (HTTP ${res.status})`)
  }
  return await res.json()
}

/**
 * Verify a single task's deadline against live web sources via Tavily.
 */
export async function verifyTaskDeadline(taskId) {
  try {
    const res = await fetch(`${API_BASE}/api/tasks/${taskId}/verify`, {
      method: 'POST',
      headers: getAuthHeaders({ 'Content-Type': 'application/json' }),
    })
    if (!res.ok) {
      const err = await res.json().catch(() => ({}))
      throw new Error(err.detail || `Failed to verify deadline (HTTP ${res.status})`)
    }
    return await res.json()
  } catch (err) {
    console.warn('Deadline verification error:', err)
    throw err
  }
}

/**
 * Batch verify open deadlines across active tasks via Tavily web search.
 */
export async function verifyAllDeadlines() {
  try {
    const res = await fetch(`${API_BASE}/api/tasks/verify-deadlines`, {
      method: 'POST',
      headers: getAuthHeaders({ 'Content-Type': 'application/json' }),
    })
    if (!res.ok) {
      const err = await res.json().catch(() => ({}))
      throw new Error(err.detail || `Failed to verify deadlines (HTTP ${res.status})`)
    }
    return await res.json()
  } catch (err) {
    console.warn('Batch verification error:', err)
    throw err
  }
}
