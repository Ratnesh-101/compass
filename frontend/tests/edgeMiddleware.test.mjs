import test from 'node:test'
import assert from 'node:assert/strict'
import crypto from 'node:crypto'
import fs from 'node:fs'
import { fileURLToPath } from 'node:url'
import path from 'node:path'
import { buildEdgeSignature } from '../middleware.js'

test('buildEdgeSignature returns three pipe-separated parts with correct format, determinism and secret dependency', async () => {
  const secret = 'test-edge-secret-abc-123'
  const ip = '198.51.100.10'
  const ts = 1712345678

  const signatureResult = await buildEdgeSignature(secret, ip, ts)

  // Returns three pipe-separated parts
  const parts = signatureResult.split('|')
  assert.equal(parts.length, 3, 'Signature header must contain exactly three pipe-separated parts')

  // The first is the IP
  assert.equal(parts[0], ip, 'The first part must be the client IP')

  // The second is the given timestamp
  assert.equal(parts[1], String(ts), 'The second part must be the given timestamp string')

  // The third is 64 lowercase hex chars
  assert.equal(parts[2].length, 64, 'The third part must be exactly 64 characters long')
  assert.match(parts[2], /^[0-9a-f]{64}$/, 'The third part must consist of 64 lowercase hex characters')

  // Same inputs give same output
  const signatureSame = await buildEdgeSignature(secret, ip, ts)
  assert.equal(signatureResult, signatureSame, 'Identical inputs must produce identical signature output')

  // A different secret gives a different signature
  const signatureDiff = await buildEdgeSignature('different-secret-xyz', ip, ts)
  assert.notEqual(signatureResult, signatureDiff, 'A different secret must produce a different signature')
})

test("verify against Node's crypto.createHmac", async () => {
  const secret = 'verified-secret-key-456'
  const ip = '203.0.113.55'
  const ts = 1720001122

  const expectedHmac = crypto.createHmac('sha256', secret).update(`${ip}|${ts}`).digest('hex')
  const expectedHeader = `${ip}|${ts}|${expectedHmac}`

  const actualHeader = await buildEdgeSignature(secret, ip, ts)
  assert.equal(actualHeader, expectedHeader)
})

test('source check: middleware.js fails closed and strips client edge sig header', () => {
  const middlewarePath = fileURLToPath(new URL('../middleware.js', import.meta.url))
  const source = fs.readFileSync(middlewarePath, 'utf8')

  assert.ok(
    !source.includes('compass_vercel_edge_hmac_secret_2026'),
    'frontend/middleware.js must not contain compass_vercel_edge_hmac_secret_2026'
  )
  assert.ok(
    source.includes("requestHeaders.delete('x-compass-edge-sig')"),
    "frontend/middleware.js must contain requestHeaders.delete('x-compass-edge-sig')"
  )
})
