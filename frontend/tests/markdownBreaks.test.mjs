import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import { performance } from 'node:perf_hooks'

import { splitOnLineBreaks } from '../src/utils/markdownBreaks.js'

test('splitOnLineBreaks splits text on HTML line-break tags (<br>, <br/>, <br />, any case)', () => {
  assert.deepEqual(splitOnLineBreaks('a<br>b<BR/>c<br />d'), ['a', 'b', 'c', 'd'])
})

test('splitOnLineBreaks returns original text when no breaks are present', () => {
  assert.deepEqual(splitOnLineBreaks('no breaks here'), ['no breaks here'])
})

test('splitOnLineBreaks returns single empty string array for empty string', () => {
  assert.deepEqual(splitOnLineBreaks(''), [''])
})

test('splitOnLineBreaks handles large stress input without catastrophic backtracking in under 1000 ms', () => {
  const stressInput = '<br' + ' '.repeat(300000) + 'x'
  const start = performance.now()
  const result = splitOnLineBreaks(stressInput)
  const duration = performance.now() - start
  assert.ok(duration < 1000, `Execution took ${duration}ms, expected under 1000ms`)
  assert.deepEqual(result, [stressInput])
})

test('MarkdownRenderer.jsx imports and uses splitOnLineBreaks and renderTextWithBreaks', () => {
  const source = fs.readFileSync(new URL('../src/components/chat/MarkdownRenderer.jsx', import.meta.url), 'utf8')
  assert.ok(source.includes('splitOnLineBreaks'))
  assert.ok(source.includes('renderTextWithBreaks'))
})
