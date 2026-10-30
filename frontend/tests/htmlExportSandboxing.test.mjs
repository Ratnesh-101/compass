import { test } from 'node:test'
import assert from 'node:assert/strict'
import { openAuthedHtml } from '../src/api/baseClient.js'

test('SEC-09: openAuthedHtml injects strict Content-Security-Policy to block script execution', async () => {
  const originalFetch = globalThis.fetch
  const originalCreate = globalThis.URL.createObjectURL

  let capturedBlob = null

  globalThis.URL.createObjectURL = (blob) => {
    capturedBlob = blob
    return 'blob:mock-sandboxed-html'
  }

  globalThis.fetch = async () => {
    return new Response(
      '<!DOCTYPE html><html><head><title>Resume</title></head><body><script>alert(document.cookie)</script><h1>John Doe</h1></body></html>',
      { status: 200, headers: { 'content-type': 'text/html' } }
    )
  }

  try {
    const res = await openAuthedHtml('http://localhost:8000/api/career/resumes/1/export/html', {
      printOnLoad: false,
    })
    assert.equal(res.success, true)
    assert.ok(capturedBlob instanceof Blob)
    const blobText = await capturedBlob.text()

    // Must contain CSP meta tag
    assert.match(blobText, /<meta http-equiv="Content-Security-Policy"/i)
    // Must restrict script-src to 'none'
    assert.match(blobText, /script-src 'none'/i)
  } finally {
    globalThis.fetch = originalFetch
    globalThis.URL.createObjectURL = originalCreate
  }
})

test('SEC-09: renderInHiddenIframe does not include allow-same-origin or allow-scripts', async () => {
  const originalFetch = globalThis.fetch
  const originalCreate = globalThis.URL.createObjectURL

  let setAttributes = {}

  const originalDocument = globalThis.document
  globalThis.document = {
    createElement: (tag) => {
      if (tag === 'iframe') {
        return {
          style: {},
          setAttribute: (k, v) => {
            setAttributes[k] = v
          },
          onload: null,
          src: '',
          parentNode: null,
        }
      }
      return { style: {} }
    },
    body: {
      appendChild: () => {},
      removeChild: () => {},
    },
  }

  globalThis.URL.createObjectURL = () => 'blob:mock-iframe-html'

  globalThis.fetch = async () => {
    return new Response('<html><body><h1>Print</h1></body></html>', { status: 200 })
  }

  try {
    await openAuthedHtml('http://localhost:8000/api/career/resumes/1/export/html', {
      printOnLoad: false,
      popup: null,
    })

    const sandbox = setAttributes['sandbox'] || ''
    // Must NOT allow same-origin or scripts
    assert.ok(!sandbox.includes('allow-same-origin'), `sandbox must not include allow-same-origin, got: ${sandbox}`)
    assert.ok(!sandbox.includes('allow-scripts'), `sandbox must not include allow-scripts, got: ${sandbox}`)
  } finally {
    globalThis.fetch = originalFetch
    globalThis.URL.createObjectURL = originalCreate
    globalThis.document = originalDocument
  }
})
