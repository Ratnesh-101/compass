import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const src = fs.readFileSync(path.resolve(__dirname, '../src/hooks/useSmoothedText.js'), 'utf8')

test('exports a default hook with an enabled flag defaulting to true', () => {
  assert.match(src, /export default function useSmoothedText\(targetText, enabled = true\)/)
})

test('imports the reveal helpers from utils/smoothReveal.js', () => {
  assert.match(src, /import\s*\{[^}]*nextRevealLength[^}]*\}\s*from '\.\.\/utils\/smoothReveal\.js'/)
  assert.match(src, /import\s*\{[^}]*revealedPrefix[^}]*\}\s*from '\.\.\/utils\/smoothReveal\.js'/)
  assert.match(src, /nextRevealLength\(\{/)
  assert.match(src, /revealedPrefix\(text,/)
})

test('animates with requestAnimationFrame and cancels it on cleanup', () => {
  assert.match(src, /requestAnimationFrame\(tick\)/)
  assert.match(src, /cancelAnimationFrame\(/)
  assert.match(src, /return cancel/)
})

test('respects prefers-reduced-motion and passes reduced through', () => {
  assert.match(src, /window\.matchMedia\('\(prefers-reduced-motion: reduce\)'\)/)
  assert.match(src, /typeof window === 'undefined'/)
  assert.match(src, /reduced,/)
})

test('resets when the text is not a continuation of the previous text', () => {
  assert.match(src, /isContinuation\(prev, text\)/)
  assert.match(src, /shownRef\.current = /)
})

test('enabled=false returns the target unchanged and runs no frames', () => {
  assert.match(src, /if \(!enabled\) return text/)
  assert.match(src, /if \(!enabled\) \{\s*cancel\(\)/)
})

test('throttles state updates to about 30fps and only on change', () => {
  assert.match(src, /COMMIT_INTERVAL_MS = 33/)
  assert.match(src, /len !== committedRef\.current/)
})

test('skips animation in background tabs and stops when caught up', () => {
  assert.match(src, /document\.hidden/)
  assert.match(src, /if \(!done\) rafRef\.current = requestAnimationFrame\(tick\)/)
})
