import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'

const readRoot = rel => fs.readFileSync(new URL(`../${rel}`, import.meta.url), 'utf8')

// ---- vercel.json SPA fallback ---------------------------------------------

test('SPA fallback rewrite excludes assets/ and file extensions', () => {
  const cfg = JSON.parse(readRoot('vercel.json'))
  const fallback = cfg.rewrites.find(r => r.destination === '/index.html')
  assert.ok(fallback, 'no rewrite with destination /index.html')
  assert.ok(fallback.source.includes('(?!'), 'source has no negative lookahead')
  assert.ok(fallback.source.includes('assets/'), 'lookahead does not mention assets/')
  assert.ok(
    fallback.source.includes('.*\\.[a-zA-Z0-9]+$'),
    'lookahead does not exclude file extensions',
  )
})

test('security header blocks are still present', () => {
  const cfg = JSON.parse(readRoot('vercel.json'))
  const keys = new Set(cfg.headers.flatMap(h => h.headers.map(x => x.key)))
  for (const k of ['Content-Security-Policy', 'X-Frame-Options', 'X-Content-Type-Options']) {
    assert.ok(keys.has(k), `${k} missing`)
  }
})

// ---- chunkReload.js --------------------------------------------------------

const { isStaleChunkError, shouldReloadForStaleChunk } = await import('../src/utils/chunkReload.js')

test('isStaleChunkError recognises stale-chunk failures', () => {
  assert.equal(isStaleChunkError(new Error('Failed to fetch dynamically imported module: https://x/assets/a.js')), true)
  assert.equal(isStaleChunkError(new Error('error loading dynamically imported module')), true)
  assert.equal(isStaleChunkError(new Error('Importing a module script failed.')), true)
  assert.equal(
    isStaleChunkError(new TypeError('Failed to load module script: Expected a JavaScript module script but the server responded with a MIME type of "text/html".')),
    true,
  )
})

test('isStaleChunkError rejects unrelated values', () => {
  assert.equal(isStaleChunkError(new Error('Network request failed')), false)
  assert.equal(isStaleChunkError(null), false)
  assert.equal(isStaleChunkError(undefined), false)
  assert.equal(isStaleChunkError('oops'), false)
})

function fakeStorage() {
  const data = new Map()
  const calls = { get: 0, set: 0 }
  return {
    data,
    calls,
    getItem(k) { calls.get++; return data.has(k) ? data.get(k) : null },
    setItem(k, v) { calls.set++; data.set(k, String(v)) },
  }
}

const chunkErr = () => new Error('Failed to fetch dynamically imported module: https://x/assets/a.js')

test('shouldReloadForStaleChunk reloads once, then throttles for 60s', () => {
  const s = fakeStorage()
  const t0 = 1_000_000
  assert.equal(shouldReloadForStaleChunk(chunkErr(), s, t0), true)
  assert.equal(s.data.get('compass.chunkReload'), String(t0))
  assert.equal(shouldReloadForStaleChunk(chunkErr(), s, t0 + 1000), false)
  assert.equal(shouldReloadForStaleChunk(chunkErr(), s, t0 + 59_999), false)
  assert.equal(shouldReloadForStaleChunk(chunkErr(), s, t0 + 61_000), true)
})

test('shouldReloadForStaleChunk ignores non-chunk errors without touching storage', () => {
  const s = fakeStorage()
  assert.equal(shouldReloadForStaleChunk(new Error('Network request failed'), s, 5), false)
  assert.equal(s.calls.get, 0)
  assert.equal(s.calls.set, 0)
})

test('shouldReloadForStaleChunk survives storage failures', () => {
  const badGet = {
    getItem() { throw new Error('denied') },
    setItem() {},
  }
  assert.equal(shouldReloadForStaleChunk(chunkErr(), badGet, 1), false)
  const badSet = {
    getItem() { return null },
    setItem() { throw new Error('quota') },
  }
  assert.equal(shouldReloadForStaleChunk(chunkErr(), badSet, 1), true)
})
