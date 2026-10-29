import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const modalPath = path.resolve(__dirname, '../src/components/career/GitHubIntelligenceModal.jsx')
const code = fs.readFileSync(modalPath, 'utf8')

test('modal renders intel.warnings in a prominent amber box above results', () => {
  assert.match(code, /intel\.warnings\.map/)
  assert.ok(code.includes('#fef3c7'), 'amber warning styling')
  assert.ok(code.indexOf('intel.warnings.map') < code.indexOf('Analyzed Repositories'), 'warnings come before results')
})

test('modal shows a clear error state when nothing could be analyzed', () => {
  assert.ok(code.includes('Nothing could be analyzed.'))
  assert.match(code, /analyzed_repos\?\.length === 0/)
})

test('modal uses honest wording instead of "verified"', () => {
  assert.ok(code.includes('Technologies detected in your own repositories'))
  assert.ok(code.includes('Detected from repository metadata'))
  assert.ok(code.includes('+ Add detected skills'))
  assert.ok(!/Verified (Technologies|Skills)/.test(code))
  assert.ok(!code.includes('or private repos'))
})

test('fork repos are labelled and cannot be imported', () => {
  assert.ok(code.includes('Fork - not your original work'))
  assert.match(code, /disabled=\{repo\.is_fork\}/)
  assert.match(code, /!repo\.is_fork && onImportRepoToMaster\(repo\)/)
})

test('unknown tests/CI (null) is not shown as missing or verified', () => {
  assert.match(code, /repo\.has_tests === null \|\| repo\.has_ci_cd === null/)
  assert.ok(code.includes('Tests/CI unknown'))
})
