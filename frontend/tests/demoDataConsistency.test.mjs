import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))

test('Static audit: App.jsx imports and integrates demo banner and status check', () => {
  const appPath = path.resolve(__dirname, '../src/App.jsx')
  const appSource = fs.readFileSync(appPath, 'utf8')

  assert.ok(
    appSource.includes('fetchDemoStatus'),
    "App.jsx must contain 'fetchDemoStatus'"
  )
  assert.ok(
    appSource.includes('DemoDataBanner'),
    "App.jsx must contain 'DemoDataBanner'"
  )
  assert.ok(
    appSource.includes('handleResetDemo'),
    "App.jsx must contain 'handleResetDemo'"
  )

  // Ensure App.jsx does NOT contain '/demo/clear' or '/demo/seed'
  assert.equal(
    appSource.includes('/demo/clear'),
    false,
    "App.jsx must not contain '/demo/clear'"
  )
  assert.equal(
    appSource.includes('/demo/seed'),
    false,
    "App.jsx must not contain '/demo/seed'"
  )
})

test('Static audit: DemoDataBanner.jsx contains expected text and button id', () => {
  const bannerPath = path.resolve(__dirname, '../src/components/DemoDataBanner.jsx')
  const bannerSource = fs.readFileSync(bannerPath, 'utf8')

  assert.ok(
    bannerSource.includes('Demo data'),
    "DemoDataBanner.jsx must contain 'Demo data'"
  )
  assert.ok(
    bannerSource.includes('demo-banner-reset'),
    "DemoDataBanner.jsx must contain 'demo-banner-reset'"
  )
})

test('Behavior test: fetchDemoStatus requests /api/demo/status, handles success, non-ok, and error', async () => {
  const originalFetch = globalThis.fetch
  try {
    let lastUrl = null
    let lastOptions = null

    // 1. Success case: returns parsed JSON
    globalThis.fetch = async (url, options = {}) => {
      lastUrl = String(url)
      lastOptions = options
      return {
        ok: true,
        status: 200,
        json: async () => ({ active: true, task_count: 21 }),
      }
    }

    const { fetchDemoStatus } = await import('../src/api/chatApi.js')
    const successResult = await fetchDemoStatus()

    assert.ok(
      lastUrl && lastUrl.endsWith('/api/demo/status'),
      `fetchDemoStatus must request a URL ending '/api/demo/status', got: ${lastUrl}`
    )
    assert.equal(
      lastOptions.credentials,
      'include',
      "fetchDemoStatus must include credentials: 'include'"
    )
    assert.deepEqual(
      successResult,
      { active: true, task_count: 21 },
      'fetchDemoStatus must return parsed JSON on ok'
    )

    // 2. Non-ok response: returns null
    globalThis.fetch = async (url, options = {}) => {
      lastUrl = String(url)
      lastOptions = options
      return {
        ok: false,
        status: 500,
        json: async () => ({ detail: 'Internal server error' }),
      }
    }

    const nonOkResult = await fetchDemoStatus()
    assert.equal(
      nonOkResult,
      null,
      'fetchDemoStatus must return null on non-ok response'
    )

    // 3. Thrown error: returns null (never throws)
    globalThis.fetch = async () => {
      throw new Error('Connection refused')
    }

    const errorResult = await fetchDemoStatus()
    assert.equal(
      errorResult,
      null,
      'fetchDemoStatus must return null on thrown error'
    )
  } finally {
    globalThis.fetch = originalFetch
  }
})
