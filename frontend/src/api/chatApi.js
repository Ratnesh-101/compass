// Chat & Memory History API

import {
  API_BASE,
  getAuthHeaders,
  fetchWithGuestRetry,
  getGuestToken,
  setGuestSession,
  initGuestSession,
  fetchWithTimeout,
} from './baseClient.js'
import { SEED_TIMEOUT_MS } from '../utils/firstRun.js'

// When the Judge Persona workspace is visible, chat must see the same demo data the dashboard shows.
let includeDemoInChat = false

export function setChatIncludeDemo(active) {
  includeDemoInChat = Boolean(active)
}

/**
 * Send a chat message to the Nebius-powered assistant.
 * Passes conversation_id for multi-turn memory.
 * Returns { response, conversation_id } on success.
 */
export async function sendQueryToAssistant(prompt, conversationId, tone = null, mode = null, specialistId = null) {
  try {
    const controller = new AbortController()
    const timeoutId = setTimeout(() => controller.abort(), 45000)

    const body = { message: prompt }
    if (includeDemoInChat) {
      body.include_demo = true
    }
    if (conversationId) {
      body.conversation_id = conversationId
    }
    if (tone) {
      body.tone = tone
    }
    if (mode) {
      body.mode = mode
    }
    if (specialistId) {
      body.specialist_id = specialistId
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
          conversation_id: data.conversation_id || conversationId || null,
          skill_used: data.skill_used || null,
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
 * Strips completed [[modes]] marker and suppresses incomplete trailing marker prefixes
 * (e.g. '[', '[[', '[[m', '[[modes', etc.) from flashing in the streaming UI.
 */
export function sanitizeModesMarker(text) {
  if (!text) return ''
  // Remove all complete occurrences of [[modes]], [modes], [[mode]], [[modes: ...]] etc.
  let clean = text.replace(/\[{1,2}\s*modes?(?::[^\]]*)?\s*\]{1,2}/gi, '')
  // Strip trailing partial prefix of [[modes]]
  clean = clean.replace(/\[(?:\[(?:m(?:o(?:d(?:e(?:s\]?)?)?)?)?)?)?$/i, '')
  return clean
}

/**
 * Stream chat tokens via Server-Sent Events (SSE) from /api/chat/stream.
 * Dispatches incremental tokens via onToken, completion metadata via onComplete,
 * and errors via onError.
 */
export async function streamQueryFromAssistant(prompt, conversationId, { onToken, onThought, onStatus, onComplete, onError, tone = null, mode = null, specialistId = null, targetMessageId = null, targetMessageContent = null, signal = null } = {}) {
  let fullResponse = ''
  let reader = null
  let streamResult = null
  try {
    const body = { message: prompt }
    if (includeDemoInChat) {
      body.include_demo = true
    }
    if (conversationId) {
      body.conversation_id = conversationId
    }
    if (tone) {
      body.tone = tone
    }
    if (mode) {
      body.mode = mode
    }
    if (specialistId) {
      body.specialist_id = specialistId
    }
    if (targetMessageId) {
      body.target_message_id = targetMessageId
    }
    if (targetMessageContent) {
      body.target_message_content = targetMessageContent
    }

    const res = await fetch(`${API_BASE}/api/chat/stream`, {
      method: 'POST',
      headers: getAuthHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify(body),
      signal,
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

    reader = res.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    let lastConvId = conversationId || null
    let lastSkill = null
    let lastTasks = null
    let lastEvidence = null
    let lastIsTruncated = false
    let lastVerifiable = false
    let lastPendingAction = null
    let lastCanUndo = false
    let lastData = null
    let sawDoneEvent = false

    const processLine = (line) => {
      const trimmed = line.trim()
      if (!trimmed || !trimmed.startsWith('data:')) return
      const jsonStr = trimmed.slice(5).trim()
      if (!jsonStr) return

      let evt
      try {
        evt = JSON.parse(jsonStr)
      } catch (e) {
        console.warn('[Compass SSE Parse Error]', e, jsonStr)
        return
      }

      if (evt.type === 'status' || evt.type === 'activity') {
        if (onStatus) onStatus(evt)
      } else if (evt.type === 'thought') {
        if (onThought) onThought(evt.value)
      } else if (evt.type === 'token') {
        if (typeof evt.value === 'string') {
          fullResponse += evt.value
          if (onToken) onToken(evt.value, sanitizeModesMarker(fullResponse))
        }
      } else if (evt.type === 'replace') {
        // Server detected a tool call or need to replace streamed markup with clean response
        if (typeof evt.value === 'string' && evt.value.trim().length > 0) {
          fullResponse = evt.value
          if (onToken) onToken(fullResponse, sanitizeModesMarker(fullResponse))
        }
      } else if (evt.type === 'done') {
        sawDoneEvent = true
        if (evt.conversation_id) lastConvId = evt.conversation_id
        if (evt.skill_used) lastSkill = evt.skill_used
        if (evt.tasks) lastTasks = evt.tasks
        if (evt.evidence) lastEvidence = evt.evidence
        if (evt.is_truncated) lastIsTruncated = true
        if (evt.verifiable !== undefined) lastVerifiable = evt.verifiable
        if (evt.pending_action) lastPendingAction = evt.pending_action
        if (evt.can_undo !== undefined) lastCanUndo = evt.can_undo
        if (evt.data) lastData = evt.data
      } else if (evt.type === 'error') {
        const errMsg = evt.detail || evt.message || 'Stream error'
        const errObj = new Error(errMsg)
        if (evt.can_retry !== undefined) errObj.can_retry = evt.can_retry
        errObj.partialResponse = fullResponse
        throw errObj
      }
    }

    while (true) {
      const { done, value } = await reader.read()
      if (done) {
        // Process any residual data in buffer when stream ends
        if (buffer && buffer.trim()) {
          const remainingLines = buffer.split(/\r?\n/)
          for (const line of remainingLines) {
            processLine(line)
          }
          buffer = ''
        }
        break
      }

      buffer += decoder.decode(value, { stream: true })
      // Handle both CRLF and LF line breaks
      const lines = buffer.split(/\r?\n/)
      // The last element is an incomplete line or empty string
      buffer = lines.pop() ?? ''

      for (const line of lines) {
        processLine(line)
      }
    }

    const cleanResponse = sanitizeModesMarker(fullResponse).trim()
    if (!cleanResponse && !sawDoneEvent) {
      const emptyErr = new Error('Connection closed before assistant response was received.')
      emptyErr.partialResponse = ''
      throw emptyErr
    }

    streamResult = {
      response: fullResponse,
      conversation_id: lastConvId,
      skill_used: lastSkill,
      tasks: lastTasks,
      evidence: lastEvidence,
      is_truncated: lastIsTruncated,
      verifiable: lastVerifiable,
      pending_action: lastPendingAction,
      can_undo: lastCanUndo,
      data: lastData,
    }
  } catch (err) {
    if (err && typeof err === 'object') {
      err.partialResponse = fullResponse
    }
    if (onError) {
      await onError(err)
    } else {
      throw err
    }
  } finally {
    if (reader) {
      try {
        reader.releaseLock()
      } catch {
        /* ignore */
      }
    }
  }

  // Run onComplete outside the stream try/catch: a handler failure after a successful
  // stream must not be reported to onError as a stream failure.
  if (streamResult && onComplete) {
    try {
      await onComplete(streamResult)
    } catch (completeErr) {
      console.error('[Compass] onComplete handler failed after successful stream:', completeErr)
    }
  }
  return streamResult
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
      id: m.id,
      role: m.role,
      text: m.content,
      skill_called: m.skill_called,
      evidence: m.evidence,
      created_at: m.created_at,
    }))
  } catch {
    return []
  }
}

/**
 * Update conversation metadata (title, is_pinned, is_archived, is_shared).
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
    if (!res.ok) return false
    const data = await res.json().catch(() => ({}))
    return { ok: true, ...data }
  } catch {
    return false
  }
}

/**
 * Fetch a publicly shared conversation and its messages by secure share token.
 */
export async function fetchSharedConversation(shareToken) {
  if (!shareToken || typeof shareToken !== 'string') return null
  const cleanToken = shareToken.trim()
  if (!cleanToken) return null

  try {
    const res = await fetch(`${API_BASE}/api/chat/shared/${encodeURIComponent(cleanToken)}`, {
      method: 'GET',
      headers: {
        'Accept': 'application/json',
      },
    })
    if (!res.ok) {
      return null
    }
    const data = await res.json()
    if (!data || !Array.isArray(data.messages)) {
      return null
    }
    return data
  } catch (err) {
    console.warn('[Compass API] Failed to fetch shared conversation:', err)
    return null
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
    let tz = 'UTC'
    try {
      tz = Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC'
    } catch {
      /* fallback to UTC */
    }

    let guestToken = getGuestToken()
    if (!guestToken) {
      const initData = await initGuestSession()
      if (initData) {
        guestToken = initData.guest_token || initData.token
      }
    }

    const res = await fetchWithGuestRetry(`${API_BASE}/api/demo/seed-persona`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(guestToken ? { 'x-guest-token': guestToken } : {})
      },
      body: JSON.stringify({ tz }),
      timeoutMs: SEED_TIMEOUT_MS,
    })
    if (!res.ok) {
      let errPayload = {}
      try {
        errPayload = await res.json()
      } catch {
        /* non-JSON response e.g. 503 HTML from proxy */
      }
      const retryHeader = res.headers.get('retry-after')
      const retryAfterSec = retryHeader ? parseInt(retryHeader, 10) : null
      const detailObj = typeof errPayload.detail === 'object' && errPayload.detail ? errPayload.detail : {}
      const detailText = detailObj.detail || (typeof errPayload.detail === 'string' ? errPayload.detail : '') || errPayload.message || `HTTP ${res.status}`
      const isExplicitlyDisabled = errPayload.code === 'seeding_disabled' || detailObj.code === 'seeding_disabled' || detailText.toLowerCase().includes('disabled')
      const code = errPayload.code || detailObj.code || (
        isExplicitlyDisabled ? 'seeding_disabled' :
        res.status === 429 ? 'seeding_rate_limited' :
        res.status === 403 ? 'auth_forbidden' :
        res.status === 503 ? 'db_unavailable' :
        res.status === 401 ? 'auth_required' : 'unknown_error'
      )
      const error = new Error(detailText)
      error.status = res.status
      error.code = code
      error.retryAfter = retryAfterSec
      throw error
    }
    const data = await res.json()
    if (data.guest_id && data.guest_token) {
      setGuestSession(data.guest_id, data.guest_token)
    }
    if (typeof window !== 'undefined' && typeof window.CustomEvent === 'function') {
      window.dispatchEvent(new window.CustomEvent('compass:demo-persona-loaded'))
    }
    return data
  } catch (err) {
    console.warn('Demo persona seed error:', err)
    throw err
  }
}

/**
 * Check if the current account/session has Judge Persona demo data active.
 * Returns { active: boolean, task_count: number } or null on non-ok/error.
 */
export async function fetchDemoStatusResult() {
  try {
    const res = await fetchWithTimeout(`${API_BASE}/api/demo/status`, {
      method: 'GET',
      headers: getAuthHeaders(),
      credentials: 'include',
    })
    if (!res.ok) return { ok: false, transient: true, data: null }
    return { ok: true, transient: false, data: await res.json() }
  } catch (err) {
    console.warn('Fetch demo status error:', err)
    return { ok: false, transient: true, data: null }
  }
}

export async function fetchDemoStatus() {
  const result = await fetchDemoStatusResult()
  return result.ok ? result.data : null
}

/**
 * Remove all demo persona dummy tasks for the current identity.
 * Genuine user tasks are strictly preserved.
 */
export async function clearDemoPersona() {
  try {
    const res = await fetch(`${API_BASE}/api/demo/clear`, {
      method: 'POST',
      headers: getAuthHeaders({ 'Content-Type': 'application/json' }),
      credentials: 'include',
    })
    if (!res.ok) return null
    return await res.json()
  } catch (err) {
    console.warn('Clear demo persona error:', err)
    return null
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

/**
 * Delete all persistent profile facts ('forget all').
 */
export async function deleteAllProfileFacts() {
  try {
    const res = await fetch(`${API_BASE}/api/profile/facts`, {
      method: 'DELETE',
      headers: getAuthHeaders(),
    })
    return res.ok
  } catch {
    return false
  }
}


/**
 * Fetch canonical persona signature phrase pools from backend.
 */
export async function fetchPersonaPhrases() {
  try {
    const res = await fetch(`${API_BASE}/api/persona/phrases`, {
      headers: getAuthHeaders(),
    })
    if (!res.ok) return null
    return await res.json()
  } catch {
    return null
  }
}

/**
 * Fetch open parked thoughts on the shelf.
 */
export async function fetchParkedThoughts() {
  try {
    const res = await fetch(`${API_BASE}/api/parked`, {
      headers: getAuthHeaders(),
    })
    if (!res.ok) return []
    const data = await res.json()
    return data.parked || []
  } catch {
    return []
  }
}

/**
 * Mark a parked thought as done.
 */
export async function resolveParkedThought(id) {
  if (!id) return false
  try {
    const res = await fetch(`${API_BASE}/api/parked/${id}`, {
      method: 'PATCH',
      headers: getAuthHeaders(),
    })
    return res.ok
  } catch {
    return false
  }
}

/**
 * Summarize decisions made, open questions, and next steps for a conversation.
 */
export async function fetchChatRecap(conversationId) {
  try {
    const res = await fetch(`${API_BASE}/api/chat/recap`, {
      method: 'POST',
      headers: getAuthHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({ conversation_id: conversationId || null }),
    })
    if (!res.ok) {
      return { recap: "I wasn't able to generate a recap right now. Please try again in a moment." }
    }
    return await res.json()
  } catch (err) {
    console.warn('[Compass Recap Error]', err)
    return { recap: "I wasn't able to generate a recap right now. Please try again in a moment." }
  }
}



