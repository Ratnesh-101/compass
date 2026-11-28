import { draftDiffersFromSaved, savedFieldsFromServer } from './careerLoadHonesty.js'
/**
 * Compass — Safe Workspace Draft Recovery Utility.
 *
 * Implements lightweight, namespaced, debounced local draft persistence
 * for unsaved tailored resume and cover-letter edits.
 *
 * Security & Isolation:
 * - Scoped strictly by opportunityId and authenticated/guest user identity.
 * - Never stores tokens, passwords, or unrelated profile state.
 * - Safely handles quota exhaustion, disabled storage, and corrupted JSON.
 */

export function getActiveSessionScope() {
  if (typeof window === 'undefined') return 'server_ssr'
  try {
    const user = localStorage.getItem('compass_user_email') || localStorage.getItem('compass_user_id')
    if (user && user.trim()) {
      return `user_${user.trim().toLowerCase().replace(/[^a-z0-9_-]/g, '_')}`
    }
    const guestId = localStorage.getItem('compass_guest_id')
    if (guestId && guestId.trim()) {
      return `guest_${guestId.trim().replace(/[^a-z0-9_-]/g, '_')}`
    }
  } catch {
    /* ignore storage access error */
  }
  return 'anonymous'
}

export function getWorkspaceDraftKey(opportunityId) {
  const scope = getActiveSessionScope()
  return `compass_draft_${scope}_opp_${opportunityId}`
}

/**
 * Reads a draft for a specific opportunity under the active user/guest scope.
 * Returns null if not found, malformed, or storage is inaccessible.
 */
export function loadWorkspaceDraft(opportunityId) {
  if (!opportunityId || typeof window === 'undefined') return null
  const key = getWorkspaceDraftKey(opportunityId)
  try {
    const raw = localStorage.getItem(key)
    if (!raw) return null
    const parsed = JSON.parse(raw)
    if (!parsed || typeof parsed !== 'object' || !parsed.draft) {
      localStorage.removeItem(key)
      return null
    }
    return parsed
  } catch {
    // Quota, SecurityError or malformed JSON
    try {
      localStorage.removeItem(key)
    } catch {
      /* ignore */
    }
    return null
  }
}

/**
 * Persists an unsaved draft to localStorage.
 * Only saves minimum editable fields.
 */
export function saveWorkspaceDraft(opportunityId, draftPayload) {
  if (!opportunityId || typeof window === 'undefined') return false
  const key = getWorkspaceDraftKey(opportunityId)
  const record = {
    opportunityId,
    scope: getActiveSessionScope(),
    updatedAt: new Date().toISOString(),
    baseResumeId: draftPayload.baseResumeId || null,
    baseResumeUpdatedAt: draftPayload.baseResumeUpdatedAt || null,
    baseAppUpdatedAt: draftPayload.baseAppUpdatedAt || null,
    draft: {
      fullName: draftPayload.fullName || '',
      email: draftPayload.email || '',
      phone: draftPayload.phone || '',
      location: draftPayload.location || '',
      summary: draftPayload.summary || '',
      skillsText: draftPayload.skillsText || '',
      resumeTemplate: draftPayload.resumeTemplate || 'ats_classic',
      coverLetterText: draftPayload.coverLetterText || '',
      privateNotes: draftPayload.privateNotes || '',
      targetDeadline: draftPayload.targetDeadline || '',
    },
  }

  try {
    localStorage.setItem(key, JSON.stringify(record))
    return true
  } catch {
    // Gracefully handle quota exhaustion without crashing the workspace
    return false
  }
}

/**
 * Removes the draft for this opportunity.
 */
export function clearWorkspaceDraft(opportunityId) {
  if (!opportunityId || typeof window === 'undefined') return
  const key = getWorkspaceDraftKey(opportunityId)
  try {
    localStorage.removeItem(key)
  } catch {
    /* ignore */
  }
}

/**
 * Checks whether current form state has material differences compared to server data.
 */
export function hasMaterialUnsavedChanges(formState, serverResume, serverApp) {
  if (!serverResume && !serverApp) return false

  const rc = serverResume?.content || {}
  const serverSkills = (rc.skills || []).join(', ')

  if (formState.fullName && formState.fullName !== (rc.full_name || '')) return true
  if (formState.email && formState.email !== (rc.email || '')) return true
  if (formState.phone && formState.phone !== (rc.phone || '')) return true
  if (formState.location && formState.location !== (rc.location || '')) return true
  if (formState.summary && formState.summary !== (rc.summary || '')) return true
  if (formState.skillsText && formState.skillsText !== serverSkills) return true

  if (serverApp) {
    if (formState.coverLetterText && formState.coverLetterText !== (serverApp.cover_letter || '')) return true
    if (formState.privateNotes && formState.privateNotes !== (serverApp.private_notes || '')) return true
    if (formState.targetDeadline && formState.targetDeadline !== (serverApp.target_deadline || '')) return true
  }

  return false
}

/**
 * Compares an existing stored draft against fresh server data.
 * Returns:
 * - { hasConflict: false } if draft is identical to server or empty
 * - { hasConflict: true, type: 'server_newer', draftRecord } if server updated after draft base
 * - { hasConflict: true, type: 'unsaved_draft', draftRecord } if draft has unsaved changes to restore
 */
export function inspectDraftConflict(draftRecord, serverResume, serverApp) {
  if (!draftRecord || !draftRecord.draft) {
    return { hasConflict: false }
  }

  const d = draftRecord.draft
  // Show the banner only when the draft really differs from what is saved (trimmed, deep compare).
  const isDifferent = draftDiffersFromSaved(d, savedFieldsFromServer(serverResume, serverApp))
  if (!isDifferent) {
    return { hasConflict: false }
  }

  // Check if server was updated after the draft was saved
  const draftTime = new Date(draftRecord.updatedAt).getTime()
  const serverResumeTime = serverResume?.updated_at ? new Date(serverResume.updated_at).getTime() : 0
  const serverAppTime = serverApp?.updated_at ? new Date(serverApp.updated_at).getTime() : 0

  if (serverResumeTime > draftTime || serverAppTime > draftTime) {
    return {
      hasConflict: true,
      type: 'server_newer',
      draftRecord,
      draftUpdatedAt: draftRecord.updatedAt,
    }
  }

  return {
    hasConflict: true,
    type: 'unsaved_draft',
    draftRecord,
    draftUpdatedAt: draftRecord.updatedAt,
  }
}
