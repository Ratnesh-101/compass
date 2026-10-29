// Chat request helpers: the browser timezone and a client request id travel with every chat call,
// so the server resolves "today 9pm" in the user's zone and a Retry never repeats a saved change.
import { getUserTimeZone } from './userTimezone.js'

export function makeRequestId() {
  try {
    if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID()
  } catch {
    /* fall through to the random id below */
  }
  return `req-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 12)}`
}

export function chatRequestFields(requestId) {
  const fields = { tz: getUserTimeZone() }
  if (requestId) fields.request_id = requestId
  return fields
}

export function describeIntakeItem(item) {
  const minutes = item?.duration_minutes
  const duration = minutes ? (minutes % 30 === 0 ? `${minutes / 60}h` : `${minutes}m`) : ''
  const due = item?.due_unparsed ? `no due date (could not read "${item.due_unparsed}")` : item?.due_label || 'no due date'
  return [item?.domain, item?.priority, duration, due].filter(Boolean).join(' · ')
}

export function savedChangeNotice(committed) {
  const count = Number(committed?.count) || 1
  const what = count === 1 ? '1 change was' : `${count} changes were`
  return `${what} saved before the connection dropped, so there is nothing to retry. Refresh the task list to see it.`
}

// The assistant message shown when a stream ends early. A committed change is reported as saved
// (no error, no Retry); anything else keeps the retry affordance and reuses the same request id.
export function failureMessage({ err, partialText, prompt, specialistId, requestId, thought, fallbackError }) {
  if (err?.committed) {
    return { role: 'assistant', text: partialText, savedNotice: savedChangeNotice(err.committed), thought: thought || null }
  }
  return {
    role: 'assistant',
    text: partialText,
    error: err?.message || fallbackError,
    canRetry: true,
    retryPrompt: prompt,
    retrySpecialistId: specialistId,
    retryRequestId: requestId,
    thought: thought || null,
  }
}
