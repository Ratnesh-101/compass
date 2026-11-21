import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const jsx = readFileSync(new URL('../src/components/Skeleton.jsx', import.meta.url), 'utf8')
const css = readFileSync(new URL('../src/components/skeleton.css', import.meta.url), 'utf8')

const EXPORTS = [
  'SkeletonBlock',
  'SkeletonText',
  'SkeletonRegion',
  'TaskListSkeleton',
  'DashboardSkeleton',
  'TimelineSkeleton',
  'RadarCardsSkeleton',
  'ChatHistorySkeleton',
  'TabSkeleton',
]

test('Skeleton.jsx imports its css and has only the 9 named exports', () => {
  assert.ok(jsx.includes("import './skeleton.css'"))
  for (const name of EXPORTS) {
    const re = new RegExp(`export (function|const) ${name}\\b`)
    assert.match(jsx, re, `missing export ${name}`)
  }
  assert.ok(!jsx.includes('export default'))
})

test('accessibility attributes: one status region, hidden visuals', () => {
  assert.equal(jsx.split('role="status"').length - 1, 1)
  assert.ok(jsx.includes('aria-busy="true"'))
  assert.ok(jsx.includes('className="sr-only"'))
  assert.ok(jsx.includes('aria-hidden="true"'))
})

test('nothing focusable', () => {
  for (const bad of ['tabIndex', '<button', '<a ', '<input']) {
    assert.ok(!jsx.includes(bad), `found ${bad}`)
  }
})

test('labels are present', () => {
  for (const label of [
    'Loading your dashboard',
    'Loading your timeline',
    'Loading opportunities',
    'Loading chat history',
    'Loading tasks',
    'Career Copilot',
  ]) {
    assert.ok(jsx.includes(label), `missing label ${label}`)
  }
})

test('Skeleton.jsx is at most 250 lines', () => {
  assert.ok(jsx.split('\n').length <= 250)
})

test('skeleton.css keyframes, reduced motion, breakpoint and tokens', () => {
  assert.ok(css.includes('@keyframes sk-shimmer'))
  assert.doesNotMatch(css, /@keyframes\s+shimmer\b/)
  const rm = css.indexOf('prefers-reduced-motion')
  assert.ok(rm >= 0)
  assert.ok(css.indexOf('animation: none', rm) > rm)
  assert.ok(css.includes('max-width: 767px'))
  const allowed = new Set(['bg-card', 'bg-card-soft', 'border', 'radius-card'])
  const used = [...css.matchAll(/var\(--([a-z-]+)/g)].map((m) => m[1])
  assert.ok(used.length > 0)
  for (const v of used) assert.ok(allowed.has(v), `unexpected variable --${v}`)
})

test('skeleton.css has no hex colors', () => {
  assert.doesNotMatch(css, /#[0-9a-fA-F]{3,6}\b/)
})
