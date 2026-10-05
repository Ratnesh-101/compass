// Chat & Memory History API

import { API_BASE, getAuthHeaders } from './baseClient'

/**
 * Send a chat message to the Nebius-powered assistant.
 * Passes conversation_id for multi-turn memory.
 * Returns { response, conversation_id } on success.
 */
export async function sendQueryToAssistant(prompt, conversationId) {
  try {
    const controller = new AbortController()
    const timeoutId = setTimeout(() => controller.abort(), 45000)

    const body = { message: prompt }
    if (conversationId) {
      body.conversation_id = conversationId
    }

    const res = await fetch(`${API_BASE}/api/chat`, {
      method: 'POST',
      headers: getAuthHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify(body),
      signal: controller.signal
    })
    clearTimeout(timeoutId)

    if (res.ok) {
      const data = await res.json()
      const text = data.response || data.message || ''
      if (text) {
        return {
          response: text,
          conversation_id: data.conversation_id || conversationId || null
        }
      }
    }
  } catch (err) {
    console.warn('[Compass Chat] Backend unreachable or timeout.', err)
  }

  // Friendly fallback when backend is offline
  return {
    response: "I'm having trouble connecting right now. Please make sure the backend is running and try again!",
    conversation_id: conversationId || null
  }
}

/**
 * Stream chat tokens via Server-Sent Events (SSE) from /api/chat/stream.
 * Dispatches incremental tokens via onToken, completion metadata via onComplete,
 * and errors via onError.
 */
export async function streamQueryFromAssistant(prompt, conversationId, { onToken, onComplete, onError } = {}) {
  try {
    const body = { message: prompt }
    if (conversationId) {
      body.conversation_id = conversationId
    }

    const res = await fetch(`${API_BASE}/api/chat/stream`, {
      method: 'POST',
      headers: getAuthHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify(body),
    })

    if (!res.ok) {
      let errText = ''
      try {
        const errJson = await res.json()
        errText = errJson.detail || errJson.message || `HTTP ${res.status}`
      } catch {
        errText = `HTTP ${res.status}`
      }
      throw new Error(`SSE endpoint returned ${errText}`)
    }

    const reader = res.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    let fullResponse = ''
    let lastConvId = conversationId || null
    let lastSkill = null

    while (true) {
      const { done, value } = await reader.read()
      if (done) break

      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n')
      buffer = lines.pop() || ''

      for (const line of lines) {
        const trimmed = line.trim()
        if (!trimmed || !trimmed.startsWith('data:')) continue
        const jsonStr = trimmed.slice(5).trim()
        if (!jsonStr) continue

        let evt = null
        try {
          evt = JSON.parse(jsonStr)
        } catch (e) {
          console.warn('[Compass SSE Parse Error]', e, jsonStr)
          continue
        }

        if (evt.type === 'token') {
          fullResponse += evt.value
          if (onToken) onToken(evt.value, fullResponse)
        } else if (evt.type === 'replace') {
          // Server detected a tool call after partial streaming —
          // discard any leaked markup and replace with the clean response.
          fullResponse = evt.value || ''
          if (onToken) onToken(fullResponse, fullResponse)
        } else if (evt.type === 'done') {
          if (evt.conversation_id) lastConvId = evt.conversation_id
          if (evt.skill_used) lastSkill = evt.skill_used
        } else if (evt.type === 'error') {
          const errMsg = evt.detail || evt.message || 'Stream error'
          throw new Error(errMsg)
        }
      }
    }

    if (!fullResponse.trim()) {
      throw new Error('Empty stream response from assistant')
    }

    if (onComplete) {
      onComplete({
        response: fullResponse,
        conversation_id: lastConvId,
        skill_used: lastSkill,
      })
    }
    return {
      response: fullResponse,
      conversation_id: lastConvId,
      skill_used: lastSkill,
    }
  } catch (err) {
    if (onError) {
      onError(err)
    } else {
      throw err
    }
  }
}


/**
 * Fetch previous chat conversations list.
 */
export async function fetchConversations(limit = 30, includeArchived = false) {
  try {
    const res = await fetch(`${API_BASE}/api/conversations?limit=${limit}&include_archived=${includeArchived}`, {
      headers: getAuthHeaders(),
    })
    if (!res.ok) return []
    const data = await res.json()
    return data.conversations || []
  } catch {
    return []
  }
}

/**
 * Fetch all messages from a specific previous conversation.
 */
export async function fetchConversationMessages(conversationId) {
  if (!conversationId) return []
  try {
    const res = await fetch(`${API_BASE}/api/conversations/${conversationId}/messages`, {
      headers: getAuthHeaders(),
    })
    if (!res.ok) return []
    const data = await res.json()
    return (data.messages || []).map(m => ({
      role: m.role,
      text: m.content,
      created_at: m.created_at,
    }))
  } catch {
    return []
  }
}

/**
 * Update conversation metadata (title, is_pinned, is_archived).
 */
export async function updateConversation(conversationId, updates) {
  if (!conversationId) return false
  try {
    const res = await fetch(`${API_BASE}/api/conversations/${conversationId}`, {
      method: 'PATCH',
      headers: {
        'Content-Type': 'application/json',
        ...getAuthHeaders(),
      },
      body: JSON.stringify(updates),
    })
    return res.ok
  } catch {
    return false
  }
}

/**
 * Delete a past conversation.
 */
export async function deleteConversation(conversationId) {
  if (!conversationId) return false
  try {
    const res = await fetch(`${API_BASE}/api/conversations/${conversationId}`, {
      method: 'DELETE',
      headers: getAuthHeaders(),
    })
    return res.ok
  } catch {
    return false
  }
}

/**
 * Fetch complete memory overview (previous chats, past plans, active tasks).
 */
export async function fetchMemoryOverview() {
  try {
    const res = await fetch(`${API_BASE}/api/memory/overview`, {
      headers: getAuthHeaders(),
    })
    if (!res.ok) return null
    return await res.json()
  } catch {
    return null
  }
}


/**
 * Seed or refresh the Dual-Degree Hackathon Competitor demo persona for judges.
 */
export async function seedJudgeDemoPersona() {
  try {
    const res = await fetch(`${API_BASE}/api/demo/seed`, {
      method: 'POST',
      headers: getAuthHeaders({ 'Content-Type': 'application/json' }),
    })
    if (!res.ok) {
      const err = await res.json().catch(() => ({}))
      throw new Error(err.detail || `Failed to seed demo persona (HTTP ${res.status})`)
    }
    return await res.json()
  } catch (err) {
    console.warn('Demo persona seed error:', err)
    throw err
  }
}

/**
 * Fetch persistent user profile facts (name, goals, preferences).
 */
export async function fetchProfileFacts() {
  try {
    const res = await fetch(`${API_BASE}/api/profile/facts`, {
      headers: getAuthHeaders(),
    })
    if (!res.ok) return {}
    const data = await res.json()
    return data.facts || {}
  } catch {
    return {}
  }
}

/**
 * Delete a persistent profile fact by key.
 */
export async function deleteProfileFact(key) {
  if (!key) return false
  try {
    const res = await fetch(`${API_BASE}/api/profile/facts/${encodeURIComponent(key)}`, {
      method: 'DELETE',
      headers: getAuthHeaders(),
    })
    return res.ok
  } catch {
    return false
  }
}

