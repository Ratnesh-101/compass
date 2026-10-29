/**
 * Compass - Career Copilot API Client.
 * Communicates with /api/career/* endpoints for:
 * - Master & tailored resume management
 * - Factual validation reports & HTML export
 * - Applications pipeline & batch approvals
 * - Submission adapters & execution
 */

import { API_BASE as BASE_URL, getAuthHeaders, getGuestToken, initGuestSession, safeHref } from './baseClient.js'
import { extractErrorDetail, parseRetryAfter, buildJobAnalysisRequest } from '../utils/careerUiHelpers.js'

const API_BASE = `${BASE_URL}/api/career`

async function ensureSession() {
  if (!getGuestToken()) {
    try {
      await initGuestSession()
    } catch {
      /* ignore storage access error */
    }
  }
}

/** Build an Error from a failed response, preferring the backend `detail` over statusText. */
async function errorFromResponse(res, fallback) {
  const body = await res.json().catch(() => ({}))
  const err = new Error(extractErrorDetail(body, `${fallback}: ${res.statusText || `HTTP ${res.status}`}`))
  err.status = res.status
  const detail = body && typeof body === 'object' ? body.detail : null
  if (detail && typeof detail === 'object' && !Array.isArray(detail) && detail.code) err.code = detail.code
  err.retryAfter = parseRetryAfter(res.headers && typeof res.headers.get === 'function' ? res.headers.get('Retry-After') : null)
  return err
}

function getJsonHeaders() {
  return getAuthHeaders({ 'Content-Type': 'application/json' })
}

// ---------------------------------------------------------------------------
// Resume Studio API
// ---------------------------------------------------------------------------

export async function fetchMasterResume() {
  await ensureSession()
  const res = await fetch(`${API_BASE}/resumes/master`, {
    headers: getAuthHeaders(),
    credentials: 'include',
  })
  if (!res.ok) throw new Error(`Failed to fetch master resume: ${res.statusText}`)
  return res.json()
}

export async function updateMasterResume(content) {
  await ensureSession()
  const res = await fetch(`${API_BASE}/resumes/master`, {
    method: 'PUT',
    headers: getJsonHeaders(),
    credentials: 'include',
    body: JSON.stringify(content),
  })
  if (!res.ok) throw new Error(`Failed to update master resume: ${res.statusText}`)
  return res.json()
}

export async function fetchResumes() {
  await ensureSession()
  const res = await fetch(`${API_BASE}/resumes`, {
    headers: getAuthHeaders(),
    credentials: 'include',
  })
  if (!res.ok) throw new Error(`Failed to list resumes: ${res.statusText}`)
  return res.json()
}

export async function tailorResume(opportunityId, customTitle = null, targetSkills = null, applicationId = null) {
  await ensureSession()
  const res = await fetch(`${API_BASE}/resumes/tailor`, {
    method: 'POST',
    headers: getJsonHeaders(),
    credentials: 'include',
    body: JSON.stringify({
      opportunity_id: opportunityId,
      custom_title: customTitle,
      target_skills_emphasis: targetSkills,
      ...(applicationId !== null && applicationId !== undefined ? { application_id: applicationId } : {}),
    }),
  })
  if (!res.ok) throw new Error(`Failed to tailor resume: ${res.statusText}`)
  return res.json()
}

export async function fetchResume(resumeId) {
  await ensureSession()
  const res = await fetch(`${API_BASE}/resumes/${resumeId}`, {
    headers: getAuthHeaders(),
    credentials: 'include',
  })
  if (!res.ok) throw new Error(`Failed to fetch resume: ${res.statusText}`)
  return res.json()
}

export async function updateResume(resumeId, payload) {
  await ensureSession()
  const res = await fetch(`${API_BASE}/resumes/${resumeId}`, {
    method: 'PUT',
    headers: getJsonHeaders(),
    credentials: 'include',
    body: JSON.stringify(payload),
  })
  if (!res.ok) throw new Error(`Failed to update resume: ${res.statusText}`)
  return res.json()
}

export async function validateResume(resumeId) {
  await ensureSession()
  const res = await fetch(`${API_BASE}/resumes/${resumeId}/validate`, {
    method: 'POST',
    headers: getJsonHeaders(),
    credentials: 'include',
  })
  if (!res.ok) throw new Error(`Failed to validate resume: ${res.statusText}`)
  return res.json()
}

export function getResumeExportUrl(resumeId, template = null) {
  const params = new URLSearchParams()
  if (template) params.append('template', template)
  const qs = params.toString()
  return safeHref(qs ? `${API_BASE}/resumes/${encodeURIComponent(resumeId)}/export/html?${qs}` : `${API_BASE}/resumes/${encodeURIComponent(resumeId)}/export/html`)
}

export function getResumeExportDocxUrl(resumeId) {
  return safeHref(`${API_BASE}/resumes/${encodeURIComponent(resumeId)}/export/docx`)
}


export async function parseUploadResume(rawText) {
  await ensureSession()
  const res = await fetch(`${API_BASE}/resumes/parse-upload`, {
    method: 'POST',
    headers: getJsonHeaders(),
    credentials: 'include',
    body: JSON.stringify({ raw_text: rawText }),
  })
  if (!res.ok) throw new Error(`Failed to parse resume text: ${res.statusText}`)
  return res.json()
}

export async function parseResumeFile(file) {
  await ensureSession()
  const formData = new FormData()
  formData.append('file', file)
  const headers = getAuthHeaders()
  delete headers['Content-Type'] // Let the browser set multipart/form-data boundary automatically
  const res = await fetch(`${API_BASE}/resumes/parse-file`, {
    method: 'POST',
    headers,
    credentials: 'include',
    body: formData,
  })
  if (!res.ok) {
    const errData = await res.json().catch(() => ({}))
    throw new Error(errData.detail || `Failed to parse resume file: ${res.statusText}`)
  }
  return res.json()
}

export const uploadResumeFile = parseResumeFile

export async function commitExtractedResume(content, originalDocumentId = null, target = 'master') {
  await ensureSession()
  const res = await fetch(`${API_BASE}/resumes/commit-extracted`, {
    method: 'POST',
    headers: getJsonHeaders(),
    credentials: 'include',
    body: JSON.stringify({
      content,
      original_document_id: originalDocumentId,
      target,
    }),
  })
  if (!res.ok) throw await errorFromResponse(res, 'Failed to commit extracted resume')
  return res.json()
}

export async function fetchOriginalResumeDocuments() {
  await ensureSession()
  const res = await fetch(`${API_BASE}/resumes/original-documents`, {
    headers: getAuthHeaders(),
    credentials: 'include',
  })
  if (!res.ok) throw new Error(`Failed to fetch original documents: ${res.statusText}`)
  return res.json()
}

export async function analyzeGitHubProfile(usernameOrUrl, personalAccessToken = null, excludedRepos = []) {
  await ensureSession()
  const res = await fetch(`${API_BASE}/intelligence/github`, {
    method: 'POST',
    headers: getJsonHeaders(),
    credentials: 'include',
    body: JSON.stringify({
      username_or_url: usernameOrUrl,
      personal_access_token: personalAccessToken,
      excluded_repos: excludedRepos,
    }),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || `GitHub analysis failed: ${res.statusText}`)
  }
  return res.json()
}

export async function ingestExternalProfile(sourceType, rawContent, sourceUrl = null) {
  await ensureSession()
  const res = await fetch(`${API_BASE}/intelligence/external-profile`, {
    method: 'POST',
    headers: getJsonHeaders(),
    credentials: 'include',
    body: JSON.stringify({
      source_type: sourceType,
      raw_content: rawContent,
      source_url: sourceUrl,
    }),
  })
  if (!res.ok) throw await errorFromResponse(res, 'Failed to ingest external profile')
  return res.json()
}

export async function fetchJobAnalysis(opportunityId, customDesc = null) {
  await ensureSession()
  const req = buildJobAnalysisRequest(API_BASE, opportunityId, customDesc)
  const res = await fetch(req.url, {
    method: req.method,
    headers: req.method === 'POST' ? getJsonHeaders() : getAuthHeaders(),
    credentials: 'include',
    ...(req.body ? { body: req.body } : {}),
  })
  if (!res.ok) throw await errorFromResponse(res, 'Failed to fetch job requirement analysis')
  return res.json()
}

export async function draftCoverLetter(opportunityId, emphasisProjects = null) {
  await ensureSession()
  const res = await fetch(`${API_BASE}/cover-letters/draft`, {
    method: 'POST',
    headers: getJsonHeaders(),
    credentials: 'include',
    body: JSON.stringify({
      opportunity_id: opportunityId,
      emphasis_projects: emphasisProjects,
    }),
  })
  if (!res.ok) throw new Error(`Failed to draft cover letter: ${res.statusText}`)
  return res.json()
}

export async function setApplicationCoverLetter(appId, coverLetter) {
  await ensureSession()
  const res = await fetch(`${API_BASE}/applications/${appId}/cover-letter`, {
    method: 'POST',
    headers: getJsonHeaders(),
    credentials: 'include',
    body: JSON.stringify({ cover_letter: coverLetter }),
  })
  if (!res.ok) throw new Error(`Failed to attach cover letter: ${res.statusText}`)
  return res.json()
}

export async function fetchCompanyIntel(opportunityId, refresh = false) {
  await ensureSession()
  const url = refresh
    ? `${API_BASE}/opportunities/${opportunityId}/company-intel?refresh=true`
    : `${API_BASE}/opportunities/${opportunityId}/company-intel`
  const res = await fetch(url, {
    headers: getAuthHeaders(),
    credentials: 'include',
  })
  if (!res.ok) throw await errorFromResponse(res, 'Failed to fetch company intelligence')
  return res.json()
}

export async function refreshCompanyIntelJob(opportunityId) {
  await ensureSession()
  const res = await fetch(`${API_BASE}/opportunities/${opportunityId}/company-intel/refresh`, {
    method: 'POST',
    headers: getJsonHeaders(),
    credentials: 'include',
  })
  if (!res.ok) throw await errorFromResponse(res, 'Refresh failed')
  return res.json()
}

export async function getCompanyIntelJobStatus(opportunityId, jobId) {
  await ensureSession()
  const res = await fetch(`${API_BASE}/opportunities/${opportunityId}/company-intel/jobs/${jobId}`, {
    headers: getAuthHeaders(),
    credentials: 'include',
  })
  if (res.status === 404) {
    return {
      status: 'failed',
      reason: 'job_lost',
      error: 'Server restarted or research session expired. Please refresh intel again.',
    }
  }
  if (!res.ok) throw new Error(`Job status check failed: ${res.statusText}`)
  return res.json()
}

export async function fetchApplications(status = null) {
  await ensureSession()
  const url = status ? `${API_BASE}/applications?status=${encodeURIComponent(status)}` : `${API_BASE}/applications`
  const res = await fetch(url, {
    headers: getAuthHeaders(),
    credentials: 'include',
  })
  if (!res.ok) throw new Error(`Failed to list applications: ${res.statusText}`)
  return res.json()
}

export async function fetchPreparedApplication(opportunityId) {
  await ensureSession()
  const res = await fetch(`${API_BASE}/applications/prepare?opportunity_id=${opportunityId}`, {
    method: 'GET',
    headers: getAuthHeaders(),
    credentials: 'include',
  })
  if (!res.ok) {
    if (res.status === 404) return null
    throw new Error(`Failed to fetch prepared application: ${res.statusText}`)
  }
  return res.json()
}

export async function prepareApplication(opportunityId) {
  await ensureSession()
  const res = await fetch(`${API_BASE}/applications/prepare?opportunity_id=${opportunityId}`, {
    method: 'POST',
    headers: getJsonHeaders(),
    credentials: 'include',
  })
  if (!res.ok) throw new Error(`Failed to prepare application: ${res.statusText}`)
  return res.json()
}

export async function updateApplication(appId, updates) {
  await ensureSession()
  const res = await fetch(`${API_BASE}/applications/${appId}`, {
    method: 'PATCH',
    headers: getJsonHeaders(),
    credentials: 'include',
    body: JSON.stringify(updates),
  })
  if (!res.ok) throw await errorFromResponse(res, 'Failed to update application')
  return res.json()
}

export async function prepareBatch(opportunityIds) {
  await ensureSession()
  const res = await fetch(`${API_BASE}/applications/batch/prepare`, {
    method: 'POST',
    headers: getJsonHeaders(),
    credentials: 'include',
    body: JSON.stringify({ opportunity_ids: opportunityIds }),
  })
  if (!res.ok) throw new Error(`Failed to prepare batch: ${res.statusText}`)
  return res.json()
}

export async function fetchBatch(batchId) {
  await ensureSession()
  const res = await fetch(`${API_BASE}/applications/batch/${batchId}`, {
    headers: getAuthHeaders(),
    credentials: 'include',
  })
  if (!res.ok) throw new Error(`Failed to fetch batch: ${res.statusText}`)
  return res.json()
}

export async function approveBatch(batchId, attestations = {}) {
  await ensureSession()
  const res = await fetch(`${API_BASE}/applications/batch/${batchId}/approve`, {
    method: 'POST',
    headers: getJsonHeaders(),
    credentials: 'include',
    body: JSON.stringify({
      batch_id: batchId,
      attestation_confirmed: attestations.attestation_confirmed ?? true,
      work_auth_confirmed: attestations.work_auth_confirmed ?? true,
      legal_statements_accepted: attestations.legal_statements_accepted ?? true,
    }),
  })
  if (!res.ok) {
    const errData = await res.json().catch(() => ({}))
    throw new Error(errData.detail || `Failed to approve batch: ${res.statusText}`)
  }
  return res.json()
}

export async function submitBatch(batchId, preferredMethod = 'manual_handoff') {
  await ensureSession()
  const res = await fetch(`${API_BASE}/applications/batch/${batchId}/submit`, {
    method: 'POST',
    headers: getJsonHeaders(),
    credentials: 'include',
    body: JSON.stringify({
      batch_id: batchId,
      preferred_method: preferredMethod,
    }),
  })
  if (!res.ok) {
    const errData = await res.json().catch(() => ({}))
    throw new Error(errData.detail || `Failed to submit batch: ${res.statusText}`)
  }
  return res.json()
}

export async function trackExternalApplication(opportunityId, source = 'external_website') {
  await ensureSession()
  const res = await fetch(`${API_BASE}/track-external-application?opportunity_id=${opportunityId}&source=${encodeURIComponent(source)}`, {
    method: 'POST',
    headers: getAuthHeaders(),
    credentials: 'include',
  })
  if (!res.ok) throw new Error(`Failed to track external application: ${res.statusText}`)
  return res.json()
}

export async function fetchAdapters() {
  await ensureSession()
  const res = await fetch(`${API_BASE}/adapters`, {
    headers: getAuthHeaders(),
    credentials: 'include',
  })
  if (!res.ok) throw new Error(`Failed to fetch adapters: ${res.statusText}`)
  return res.json()
}

export async function markApplied(appId) {
  await ensureSession()
  const res = await fetch(`${API_BASE}/applications/${appId}/mark-applied`, {
    method: 'POST',
    headers: getJsonHeaders(),
    credentials: 'include',
  })
  if (!res.ok) throw await errorFromResponse(res, 'Failed to record submission confirmation')
  return res.json()
}

export async function fetchHandoffKit(appId) {
  await ensureSession()
  const res = await fetch(`${API_BASE}/applications/${appId}/handoff-kit`, {
    headers: getAuthHeaders({ Accept: 'application/json' }),
    credentials: 'include',
  })
  if (!res.ok) throw await errorFromResponse(res, 'Failed to load Handoff Kit')
  return res.json()
}
