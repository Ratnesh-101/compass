import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'

const read = rel => fs.readFileSync(new URL(`../src/${rel}`, import.meta.url), 'utf8')
const REVIEW = 'components/career/ExtractionReviewModal.jsx'

test('Education review has a "Field of study" input bound to field_of_study', () => {
  const src = read(REVIEW)
  assert.match(src, /Field of study/)
  assert.match(src, /value=\{[^}]*field_of_study[^}]*\}/)
  assert.match(src, /\.field_of_study\s*=|field_of_study\s*:/)
})

test('Education review has a graduation month control or a read-only parsed month', () => {
  const src = read(REVIEW)
  const control = /type=["']month["']|graduation[_ ]?month|end_month|Graduation month/i
  assert.match(src, control)
})

test('Experience review has an is_current checkbox labelled "Currently working here"', () => {
  const src = read(REVIEW)
  assert.match(src, /type=["']checkbox["']/)
  assert.match(src, /checked=\{[^}]*is_current[^}]*\}/)
  assert.match(src, /Currently working here/)
})
