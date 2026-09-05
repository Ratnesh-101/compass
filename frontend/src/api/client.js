// Compass API Client
const API_BASE = (import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000').replace(/\/$/, '')

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

/**
 * Health check ping — dynamically reports Neon connection or fallback status.
 */
export async function checkBackendHealth() {
  try {
    const controller = new AbortController()
    const timeoutId = setTimeout(() => controller.abort(), 4000)

    const res = await fetch(`${API_BASE}/health`, {
      method: 'GET',
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
    return 'Backend Offline • Connection Refused'
  }
}

/**
 * Fetch synchronized task list from Neon PostgreSQL.
 * Returns empty array if database is empty; falls back to demo tasks only if server is unreachable.
 */
export async function fetchTasks() {
  try {
    const controller = new AbortController()
    const timeoutId = setTimeout(() => controller.abort(), 4000)

    const res = await fetch(`${API_BASE}/api/tasks`, {
      signal: controller.signal
    })
    clearTimeout(timeoutId)

    if (!res.ok) {
      return FALLBACK_TASKS
    }

    const data = await res.json()
    if (Array.isArray(data)) {
      return data
    }
    return FALLBACK_TASKS
  } catch {
    return FALLBACK_TASKS
  }
}

/**
 * Send a chat message to the Nebius-powered assistant.
 * Passes conversation_id for multi-turn memory.
 * Returns { response, conversation_id } on success.
 */
export async function sendQueryToAssistant(prompt, conversationId) {
  try {
    const controller = new AbortController()
    const timeoutId = setTimeout(() => controller.abort(), 12000)

    const body = { message: prompt }
    if (conversationId) {
      body.conversation_id = conversationId
    }

    const res = await fetch(`${API_BASE}/api/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
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
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })

    if (!res.ok) {
      throw new Error(`SSE endpoint returned HTTP ${res.status}`)
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
        try {
          const evt = JSON.parse(jsonStr)
          if (evt.type === 'token') {
            fullResponse += evt.value
            if (onToken) onToken(evt.value, fullResponse)
          } else if (evt.type === 'done') {
            if (evt.conversation_id) lastConvId = evt.conversation_id
            if (evt.skill_used) lastSkill = evt.skill_used
          } else if (evt.type === 'error') {
            throw new Error(evt.message || 'Stream error')
          }
        } catch (e) {
          console.warn('[Compass SSE Parse Error]', e, jsonStr)
        }
      }
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
