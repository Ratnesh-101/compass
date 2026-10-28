import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import { performance } from 'node:perf_hooks'

import { isHorizontalRule } from '../src/utils/markdownRules.js'

test('isHorizontalRule returns true for markdown horizontal rules', () => {
  assert.equal(isHorizontalRule('---'), true)
  assert.equal(isHorizontalRule('-----'), true)
  assert.equal(isHorizontalRule('***'), true)
  assert.equal(isHorizontalRule('___'), true)
})

test('isHorizontalRule returns false for non-rule strings', () => {
  assert.equal(isHorizontalRule('--'), false)
  assert.equal(isHorizontalRule('- item'), false)
  assert.equal(isHorizontalRule('-- flag'), false)
  assert.equal(isHorizontalRule('--- text'), false)
  assert.equal(isHorizontalRule('• bullet'), false)
  assert.equal(isHorizontalRule(''), false)
  assert.equal(isHorizontalRule('a---b'), false)
})

test('isHorizontalRule returns false without throwing for non-strings', () => {
  assert.doesNotThrow(() => {
    assert.equal(isHorizontalRule(undefined), false)
    assert.equal(isHorizontalRule(null), false)
    assert.equal(isHorizontalRule(42), false)
  })
})

test('isHorizontalRule handles large stress input without catastrophic backtracking in under 1000 ms', () => {
  const stressInput = '-'.repeat(300000) + 'x'
  const start = performance.now()
  const result = isHorizontalRule(stressInput)
  const duration = performance.now() - start
  assert.equal(result, false)
  assert.ok(duration < 1000, `Execution took ${duration}ms, expected under 1000ms`)
})

test('MarkdownRenderer.jsx imports isHorizontalRule and evaluates it before bullet lists', () => {
  const source = fs.readFileSync(new URL('../src/components/chat/MarkdownRenderer.jsx', import.meta.url), 'utf8')
  assert.ok(source.includes('isHorizontalRule'))
  const ruleIndex = source.indexOf('isHorizontalRule(trimmed)')
  const bulletIndex = source.indexOf('// 8. Bullet Lists')
  assert.ok(ruleIndex !== -1, 'isHorizontalRule(trimmed) should be in source')
  assert.ok(bulletIndex !== -1, '// 8. Bullet Lists should be in source')
  assert.ok(ruleIndex < bulletIndex, 'isHorizontalRule(trimmed) must come before // 8. Bullet Lists')
})
