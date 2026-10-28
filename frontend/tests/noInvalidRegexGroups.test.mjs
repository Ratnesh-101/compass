import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

// JavaScript has no inline-flag groups such as (?i). A regex literal containing one is an early
// SyntaxError, which makes the whole module (and a lazily loaded chunk) fail to load, while the
// production build still succeeds. This scan keeps that from shipping again.
const srcDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../src')

function sourceFiles(dir) {
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const full = path.join(dir, entry.name)
    if (entry.isDirectory()) return sourceFiles(full)
    return /\.(jsx?|mjs)$/.test(entry.name) ? [full] : []
  })
}

test('no regex literal or RegExp string uses an unsupported inline flag group like (?i)', () => {
  const offenders = []
  for (const file of sourceFiles(srcDir)) {
    fs.readFileSync(file, 'utf8').split('\n').forEach((line, i) => {
      if (/\(\?[imsx-]+\)/.test(line)) offenders.push(`${path.relative(srcDir, file)}:${i + 1}`)
    })
  }
  assert.deepEqual(offenders, [])
})

test('the inline-flag detector flags a known-bad pattern (guards the guard)', () => {
  assert.throws(() => new RegExp('(?i)logo'), SyntaxError)
  assert.ok(/\(\?[imsx-]+\)/.test('t.replace(/(?i)\blogo\b/g, "")'))
})
