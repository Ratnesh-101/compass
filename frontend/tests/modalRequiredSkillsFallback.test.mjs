import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
const src = readFileSync(
  join(here, '..', 'src', 'components', 'career', 'ApplicationWorkspaceModal.jsx'),
  'utf8',
)

test('required skills fall back to jobAnalysis.required_skills when the opportunity has none', () => {
  assert.match(src, /rawRequiredSkills\s*=\s*opportunity\?\.requirements\?\.required_skills\s*\|\|\s*\[\]/)
  assert.match(src, /rawRequiredSkills\.length\s*>\s*0\s*\?\s*rawRequiredSkills\s*:\s*\(jobAnalysis\?\.required_skills\s*\|\|\s*\[\]\)/)
})

test('an empty requirements list renders the general-qualification state instead of an empty grid', () => {
  assert.match(src, /id="factual-match-general-role"/)
  assert.match(src, /requiredSkills\.length\s*===\s*0/)
})

test('no leftover debug markers in the modal', () => {
  assert.doesNotMatch(src, /TEMP_\d+|INTEL_SRC_BRANCH/)
})
