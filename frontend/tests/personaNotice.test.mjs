import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { mapPersonaError } from '../src/utils/personaNotice.js'

const __dirname = path.dirname(fileURLToPath(import.meta.url))

test('mapPersonaError maps 503 db_unavailable, cold_start, rate_limiter_unavailable properly', () => {
  const err503 = { status: 503, code: 'db_unavailable', retryAfter: 8 }
  const res = mapPersonaError(err503)
  assert.equal(res.type, 'info')
  assert.equal(res.text, 'The server is waking up or temporarily unavailable. Retrying...')
  assert.equal(res.canRetry, true)
  assert.equal(res.is503, true)
  assert.equal(res.retryDelay, 8)

  // Cap retryAfter at 10s max
  const errHighDelay = { status: 503, code: 'cold_start', retryAfter: 60 }
  const resHigh = mapPersonaError(errHighDelay)
  assert.equal(resHigh.retryDelay, 10)

  // Rate limiter unavailable
  const errLimiter = { status: 503, code: 'rate_limiter_unavailable' }
  const resLimiter = mapPersonaError(errLimiter)
  assert.equal(resLimiter.is503, true)
  assert.equal(resLimiter.canRetry, true)
  assert.equal(resLimiter.retryDelay, 5)
})

test('mapPersonaError maps 403 seeding_disabled properly', () => {
  const err403 = { status: 403, code: 'seeding_disabled' }
  const res = mapPersonaError(err403)
  assert.equal(res.type, 'disabled')
  assert.equal(res.text, 'Demo loading is turned off on this server.')
  assert.equal(res.canRetry, false)
})

test('mapPersonaError maps 429 seeding_rate_limited properly', () => {
  const err429 = { status: 429, code: 'seeding_rate_limited', message: 'Seeding rate limit reached. Please wait before retrying.', retryAfter: 30 }
  const res = mapPersonaError(err429)
  assert.equal(res.type, 'error')
  assert.equal(res.text, 'Seeding rate limit reached. Please wait before retrying.')
  assert.equal(res.canRetry, false)
})


test('mapPersonaError maps 401 session expired properly', () => {
  const err401 = { status: 401, code: 'unauthorized' }
  const res = mapPersonaError(err401)
  assert.equal(res.type, 'error')
  assert.equal(res.text, 'Session expired. Please refresh.')
  assert.equal(res.canRetry, false)
})

test('mapPersonaError maps network error properly', () => {
  const errNet = new Error('Failed to fetch: network connection refused')
  const res = mapPersonaError(errNet)
  assert.equal(res.type, 'error')
  assert.equal(res.text, 'Network error. Check your connection.')
  assert.equal(res.canRetry, true)
})

test('Dashboard.jsx and Timeline.jsx no longer import the persona notice mapper (seeding UI removed)', () => {
  const dashSrc = fs.readFileSync(path.resolve(__dirname, '../src/components/Dashboard.jsx'), 'utf8')
  const timelineSrc = fs.readFileSync(path.resolve(__dirname, '../src/components/Timeline.jsx'), 'utf8')
  assert.equal(dashSrc.includes('personaNotice'), false)
  assert.equal(timelineSrc.includes('personaNotice'), false)
  assert.equal(dashSrc.includes('handleSeedJudgePersona'), false)
  assert.equal(timelineSrc.includes('handleSeedJudgePersona'), false)
})
