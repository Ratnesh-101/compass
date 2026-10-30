/**
 * Request body builders for agent and scheduling endpoints.
 *
 * Ensures that demo data is scoped consistently across the dashboard, chat,
 * agent, and scheduling workflows: demo tasks are included only when the
 * Judge Persona demo is active.
 */

import { getChatIncludeDemo } from '../api/chatApi.js'

/**
 * Build POST body for /api/agent/run
 */
export function buildAgentRunBody(payload = {}, options = {}) {
  const body = { ...payload }
  const convId = options.conversationId !== undefined ? options.conversationId : payload.conversation_id
  if (convId && !body.conversation_id) {
    body.conversation_id = convId
  }
  const includeDemo = options.includeDemo !== undefined ? Boolean(options.includeDemo) : getChatIncludeDemo()
  if (includeDemo) {
    body.include_demo = true
  }
  return body
}

/**
 * Build POST body for /api/agent/feasibility
 */
export function buildFeasibilityBody(payload = {}, options = {}) {
  const goalStr = payload?.goal || ''
  const daysMatch = goalStr.match(/(\d+)\s*days?/i)
  const hoursMatch = goalStr.match(/(\d+(?:\.\d+)?)\s*hours?/i)

  const body = {
    days: payload.days !== undefined ? payload.days : (daysMatch ? parseInt(daysMatch[1], 10) : 5),
    hours_per_day: payload.hours_per_day !== undefined ? payload.hours_per_day : (hoursMatch ? parseFloat(hoursMatch[1]) : 4.0),
    domain: payload.domain !== undefined ? payload.domain : null,
  }

  const includeDemo = options.includeDemo !== undefined ? Boolean(options.includeDemo) : getChatIncludeDemo()
  if (includeDemo) {
    body.include_demo = true
  }
  return body
}

/**
 * Build POST body for /api/schedule/propose
 */
export function buildProposeScheduleBody(params = {}, options = {}) {
  const { targetDate, domain, taskIds } = params
  const payload = {}
  if (targetDate) payload.target_date = targetDate
  if (domain && domain !== 'all') payload.domain = domain
  if (taskIds && taskIds.length > 0) payload.task_ids = taskIds

  const includeDemo = options.includeDemo !== undefined ? Boolean(options.includeDemo) : getChatIncludeDemo()
  if (includeDemo) {
    payload.include_demo = true
  }
  return payload
}

/**
 * Build POST body for /api/schedule/commit
 */
export function buildCommitScheduleBody(assignments, rationale, options = {}) {
  const payload = {
    assignments,
    rationale: rationale || 'Committed via Schedule View',
  }

  const includeDemo = options.includeDemo !== undefined ? Boolean(options.includeDemo) : getChatIncludeDemo()
  if (includeDemo) {
    payload.include_demo = true
  }
  return payload
}

/**
 * Build POST body for /api/schedule/reactive-check
 */
export function buildReactiveCheckBody(currentTime = null, options = {}) {
  const body = currentTime ? { current_time: currentTime } : {}

  const includeDemo = options.includeDemo !== undefined ? Boolean(options.includeDemo) : getChatIncludeDemo()
  if (includeDemo) {
    body.include_demo = true
  }
  return body
}
