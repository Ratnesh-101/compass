// Pure helpers for honest load/save behavior in My resume, Application Center and the workspace.

export const LOAD_ERROR_TEXT = "We couldn't load your resume. Check your connection and try again."
export const OFFLINE_TEXT = 'You seem to be offline.'
export const SESSION_TEXT = 'Your session has expired. Sign in again, then try again.'
export const SERVER_TEXT = "Something went wrong on our side. Try again in a moment."

/**
 * Friendly text for a failed load. Never returns a raw status or "Failed to fetch".
 * `err` may carry `.status`; `online` is navigator.onLine.
 */
export function friendlyLoadError(err, online = true, what = 'resume') {
  if (online === false) return OFFLINE_TEXT
  const status = Number(err && err.status)
  if (status === 401 || status === 403) return SESSION_TEXT
  if (status >= 500) return SERVER_TEXT
  return `We couldn't load your ${what}. Check your connection and try again.`
}

export const SLOW_LOAD_MS = 8000
export const SLOW_LOAD_TEXT = 'Still loading... this can take a moment on the first visit'

/** True when the editor holds text that a new generated draft would overwrite. */
export function needsReplaceConfirm(editorText, lastSavedText) {
  const current = String(editorText || '').trim()
  if (!current) return false
  return current !== String(lastSavedText || '').trim()
}

const EDITABLE = ['fullName', 'email', 'phone', 'location', 'summary', 'skillsText', 'coverLetterText', 'privateNotes', 'targetDeadline']

function norm(key, value) {
  let text = String(value == null ? '' : value).trim()
  if (key === 'skillsText') text = text.split(',').map(s => s.trim()).filter(Boolean).join(', ')
  if (key === 'targetDeadline') text = text.slice(0, 10)
  return text
}

/**
 * The banner is shown only when a local draft differs from the saved/server values.
 * Compares every editable field the draft has; fields missing from the draft are ignored.
 */
export function draftDiffersFromSaved(draft, saved) {
  if (!draft || !saved) return false
  return EDITABLE.some(key => draft[key] !== undefined && norm(key, draft[key]) !== norm(key, saved[key]))
}

/** Editable fields as they are stored on the server (resume content + application). */
export function savedFieldsFromServer(serverResume, serverApp) {
  const c = (serverResume && serverResume.content) || {}
  return {
    fullName: c.full_name,
    email: c.email,
    phone: c.phone,
    location: c.location,
    summary: c.summary,
    skillsText: (c.skills || []).join(', '),
    coverLetterText: serverApp && serverApp.cover_letter,
    privateNotes: serverApp && serverApp.private_notes,
    targetDeadline: serverApp && serverApp.target_deadline,
  }
}
