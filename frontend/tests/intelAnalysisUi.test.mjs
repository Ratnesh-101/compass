import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const here = path.dirname(fileURLToPath(import.meta.url))
const srcDir = path.resolve(here, '../src')
const read = rel => fs.readFileSync(path.join(srcDir, rel), 'utf8')

// Env overrides let the tests run against pre-fix copies of the sources.
const fromEnv = (name, rel) => (process.env[name] ? fs.readFileSync(process.env[name], 'utf8') : read(rel))
const modal = fromEnv('CAREER_MODAL_FILE', 'components/career/ApplicationWorkspaceModal.jsx')
const radar = fromEnv('RADAR_FILE', 'components/InternshipRadar.jsx')
const api = fromEnv('CAREER_API_FILE', 'api/careerApi.js')

const helpers = await import('../src/utils/careerUiHelpers.js')
const {
  formatMatchScore,
  matchScoreColor,
  resolveSkillMatch,
  buildJobAnalysisRequest,
  parseRetryAfter,
  intelCooldownForError,
  cooldownSecondsLeft,
  intelErrorMessage,
  copyWithFeedback,
  extractErrorDetail,
} = helpers
const { getSafeHttpUrl } = await import('../src/utils/safeUrl.js')

// ---- score display -------------------------------------------------------

test('match score is rendered on the 0-100 scale, not multiplied by 100', () => {
  assert.equal(formatMatchScore({ match_score: 50, required_skills: ['a', 'b'] }).text, '50%')
  assert.equal(formatMatchScore({ match_score: 100, required_skills: ['a'] }).text, '100%')
  assert.equal(formatMatchScore({ match_score: 49.6, required_skills: ['a'] }).text, '50%')
})

test('score_available false renders N/A with a caption in a neutral colour', () => {
  const v = formatMatchScore({ match_score: 0, score_available: false, required_skills: [] })
  assert.equal(v.text, 'N/A')
  assert.equal(v.caption, 'No skills listed in this posting')
  assert.notEqual(v.color, '#dc2626')
})

test('missing score_available is treated as available (old servers)', () => {
  assert.equal(formatMatchScore({ match_score: 0, required_skills: ['python'] }).text, '0%')
  assert.equal(formatMatchScore({ match_score: 80 }).text, '80%')
})

test('colour thresholds are 75 and 50', () => {
  assert.equal(matchScoreColor(75), '#16a34a')
  assert.equal(matchScoreColor(74), '#d97706')
  assert.equal(matchScoreColor(50), '#d97706')
  assert.equal(matchScoreColor(49), '#dc2626')
  assert.equal(matchScoreColor(0.8), '#dc2626')
})

test('modal no longer multiplies the score by 100', () => {
  assert.doesNotMatch(modal, /match_score[^\n]*\*\s*100/)
  assert.match(modal, /formatMatchScore\(/)
})

// ---- skill match consistency ----------------------------------------------

test('skill match uses the analysis once loaded and never claims "none" while unavailable', () => {
  const ready = resolveSkillMatch({
    analysis: { matched_skills: ['a'], missing_skills: ['b'], required_skills: ['a', 'b'] },
    postingSkills: [],
  })
  assert.equal(ready.status, 'ready')
  assert.deepEqual(ready.matched, ['a'])
  assert.deepEqual(ready.missing, ['b'])
  assert.equal(resolveSkillMatch({ analysis: null, loading: true, postingSkills: [] }).status, 'loading')
  assert.equal(resolveSkillMatch({ analysis: null, loading: false, failed: true, postingSkills: [] }).status, 'unavailable')
  // a stale report kept after a failed re-analyze stays usable
  assert.equal(resolveSkillMatch({ analysis: { matched_skills: [] }, failed: true }).status, 'ready')
})

test('modal derives matched/missing from the shared resolver and has loading/unavailable text', () => {
  assert.match(modal, /resolveSkillMatch\(/)
  assert.doesNotMatch(modal, /userSkills\.some\(us =>/)
  assert.match(modal, /Requirements unavailable/)
})

// ---- analysis error / retry ------------------------------------------------

test('modal tracks analysisError and offers Retry plus the "Could not load the analysis" text', () => {
  assert.match(modal, /\[analysisError,\s*setAnalysisError\]/)
  assert.match(modal, /setAnalysisError\(err/)
  assert.match(modal, /Could not load the analysis/)
  assert.match(modal, /id="job-analysis-error"/)
})

test('failed workspace load shows an error with Retry that re-runs the whole load', () => {
  assert.match(modal, /\[workspaceError,\s*setWorkspaceError\]/)
  assert.match(modal, /id="workspace-load-error"/)
  assert.match(modal, /onClick=\{loadWorkspaceData\}/)
})

// ---- request builder -------------------------------------------------------

test('custom descriptions go in a POST JSON body, plain analysis stays a GET', () => {
  const base = 'https://x/api/career'
  const get = buildJobAnalysisRequest(base, 7, null)
  assert.equal(get.method, 'GET')
  assert.equal(get.url, 'https://x/api/career/opportunities/7/job-analysis')
  assert.equal(get.body, null)
  assert.equal(buildJobAnalysisRequest(base, 7, '   ').method, 'GET')
  const long = 'x'.repeat(20000)
  const post = buildJobAnalysisRequest(base, 7, long)
  assert.equal(post.method, 'POST')
  assert.ok(!post.url.includes('?'))
  assert.equal(JSON.parse(post.body).custom_description, long)
})

test('careerApi no longer puts the description in a query string and surfaces server detail', () => {
  assert.doesNotMatch(api, /custom_desc=/)
  assert.match(api, /buildJobAnalysisRequest\(/)
  assert.match(api, /errorFromResponse\(res, 'Failed to fetch job requirement analysis'\)/)
  assert.match(api, /errorFromResponse\(res, 'Failed to fetch company intelligence'\)/)
})

// ---- 429 handling ----------------------------------------------------------

test('structured 429 detail is extracted and Retry-After parsed', () => {
  const body = { detail: { code: 'intel_budget_exhausted', message: 'Daily intel budget used up.' } }
  assert.equal(extractErrorDetail(body, 'fallback'), 'Daily intel budget used up.')
  assert.equal(parseRetryAfter('45'), 45)
  assert.equal(parseRetryAfter('abc'), null)
  assert.equal(parseRetryAfter(null), null)
  assert.equal(parseRetryAfter('0'), null)
})

test('cooldown starts only for 429, uses Retry-After or 30 s default', () => {
  assert.equal(intelCooldownForError({ status: 429, retryAfter: 120 }), 120)
  assert.equal(intelCooldownForError({ status: 429 }), 30)
  assert.equal(intelCooldownForError({ status: 500 }), 0)
  assert.equal(intelCooldownForError(new TypeError('Failed to fetch')), 0)
})

test('countdown never goes negative and rounds up', () => {
  assert.equal(cooldownSecondsLeft(10_000, 1_000), 9)
  assert.equal(cooldownSecondsLeft(10_000, 9_500), 1)
  assert.equal(cooldownSecondsLeft(10_000, 20_000), 0)
  assert.equal(cooldownSecondsLeft(0, 5), 0)
})

test('intel error message prefers the server wording and falls back for network errors', () => {
  assert.equal(intelErrorMessage({ status: 429, message: 'Cooldown: try in 20s.' }), 'Cooldown: try in 20s.')
  assert.match(intelErrorMessage(new Error('network down')), /couldn't generate company intel/)
})

test('modal disables Refresh with a visible countdown and no longer pre-locks for 30 s', () => {
  assert.match(modal, /cooldownSeconds\s*>\s*0/)
  assert.match(modal, /Refresh available in \{cooldownSeconds\}s/)
  assert.doesNotMatch(modal, /lastIntelRefreshTimeRef/)
})

// ---- lazy intel ------------------------------------------------------------

test('company intel is fetched lazily on first tab activation, not on open', () => {
  const loadFn = modal.match(/const loadWorkspaceData = useCallback\([\s\S]*?\n {2}\}, \[/)[0]
  assert.doesNotMatch(loadFn, /loadCompanyIntelData\(/)
  assert.match(modal, /activeTab !== 'company_intel'[\s\S]{0,120}intelFetchStartedRef/)
})

// ---- submission tab --------------------------------------------------------

test('application link goes through getSafeHttpUrl and unsafe schemes yield no URL', () => {
  assert.match(modal, /getSafeHttpUrl\(opportunity\?\.official_application_url\)/)
  assert.doesNotMatch(modal, /href=\{opportunity\.official_application_url\}/)
  assert.equal(getSafeHttpUrl('javascript:alert(1)'), null)
  assert.equal(getSafeHttpUrl('https://jobs.example.com/a'), 'https://jobs.example.com/a')
})

test('submission wording is self-attested, not verified', () => {
  assert.match(modal, /You marked this as submitted/)
  assert.doesNotMatch(modal, /Confirmed: Marked as submitted on employer portal/)
  assert.doesNotMatch(modal, /requires submissions directly through their official career portal/)
})

// ---- clipboard -------------------------------------------------------------

test('copy failure and empty text are reported as failures', async () => {
  const rejecting = { writeText: async () => { throw new Error('denied') } }
  const ok = { writeText: async () => {} }
  assert.equal((await copyWithFeedback('Summary', 'hi', rejecting)).ok, false)
  assert.match((await copyWithFeedback('Summary', 'hi', rejecting)).message, /Copy failed/)
  assert.equal((await copyWithFeedback('Summary', '', ok)).ok, false)
  assert.equal((await copyWithFeedback('Summary', 'hi', ok)).ok, true)
})

test('modal has no bare navigator.clipboard.writeText calls', () => {
  assert.doesNotMatch(modal, /navigator\.clipboard\.writeText/)
  assert.match(modal, /copyWithFeedback\(/)
})

// ---- stale state -----------------------------------------------------------

test('workspace modal is keyed by opportunity id and customJobDesc starts from the opportunity', () => {
  assert.match(radar, /<ApplicationWorkspaceModal\s+key=\{activeWorkspaceOpp\.id\}/)
  assert.match(modal, /useState\(opportunity\?\.description \|\| ''\)/)
})

// ---- merged with the async refresh flow (#188) ------------------------------

test('detail.detail strings (async refresh 429 shape) are extracted', () => {
  assert.equal(extractErrorDetail({ detail: { code: 'x', detail: 'Search budget used up.' } }, 'f'), 'Search budget used up.')
})

test('async refresh: a 429 on job creation is surfaced, not retried through the sync path', () => {
  assert.match(modal, /postErr\?\.status === 429\) throw postErr/)
  assert.match(api, /errorFromResponse\(res, 'Refresh failed'\)/)
})

test('async refresh: cooldown starts only once the server accepted the job, and the button honours it', () => {
  assert.match(modal, /if \(job\) startCooldown\(DEFAULT_INTEL_COOLDOWN_SECONDS\)/)
  assert.match(modal, /startCooldown\(intelCooldownForError\(err\)\)/)
  assert.match(modal, /disabled=\{loadingIntel \|\| cooldownSeconds > 0\}/)
  assert.match(modal, /getCompanyIntelJobStatus/)
})
