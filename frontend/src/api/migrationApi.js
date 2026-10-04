// Anonymous Guest Migration & Data Privacy API

import { API_BASE, getAuthHeaders, setGuestSession } from './baseClient'

/**
 * Fetch migration status to check if unauthenticated guest data exists.
 */
export async function fetchMigrationStatus() {
  try {
    const res = await fetch(`${API_BASE}/api/migration/status`, {
      headers: getAuthHeaders(),
      credentials: 'include',
    })
    if (!res.ok) return { has_guest_data: false, guest_conversations_count: 0 }
    return await res.json()
  } catch {
    return { has_guest_data: false, guest_conversations_count: 0 }
  }
}

/**
 * List all guest conversations for selective migration.
 */
export async function fetchMigrationConversations() {
  try {
    const res = await fetch(`${API_BASE}/api/migration/conversations`, {
      headers: getAuthHeaders(),
      credentials: 'include',
    })
    if (!res.ok) return { guest_id: null, conversations: [], total: 0 }
    return await res.json()
  } catch {
    return { guest_id: null, conversations: [], total: 0 }
  }
}

/**
 * Import all eligible guest conversations & memory into the authenticated account.
 */
export async function importAllGuestData() {
  const res = await fetch(`${API_BASE}/api/migration/import-all`, {
    method: 'POST',
    headers: getAuthHeaders({ 'Content-Type': 'application/json' }),
    credentials: 'include',
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || `Failed to import guest data (HTTP ${res.status})`)
  }
  return await res.json()
}

/**
 * Import selected guest conversations into the authenticated account.
 */
export async function importSelectedGuestConversations(conversationIds, importMemory = true) {
  const res = await fetch(`${API_BASE}/api/migration/import-selected`, {
    method: 'POST',
    headers: getAuthHeaders({ 'Content-Type': 'application/json' }),
    credentials: 'include',
    body: JSON.stringify({
      conversation_ids: conversationIds,
      import_memory: importMemory,
    }),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || `Failed to import selected conversations (HTTP ${res.status})`)
  }
  return await res.json()
}

/**
 * Skip migration for now, recording user preference while preserving guest data.
 */
export async function skipMigration() {
  try {
    const res = await fetch(`${API_BASE}/api/migration/skip`, {
      method: 'POST',
      headers: getAuthHeaders({ 'Content-Type': 'application/json' }),
      credentials: 'include',
    })
    if (!res.ok) return false
    return true
  } catch {
    return false
  }
}

/**
 * Delete all data associated with current guest session (GDPR / privacy control).
 */
export async function deleteGuestData() {
  const res = await fetch(`${API_BASE}/api/guest/data`, {
    method: 'DELETE',
    headers: getAuthHeaders(),
    credentials: 'include',
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || `Failed to delete guest data (HTTP ${res.status})`)
  }
  setGuestSession(null, null)
  return await res.json()
}
