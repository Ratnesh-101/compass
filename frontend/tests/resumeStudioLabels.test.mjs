import { test } from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'

const src = fs.readFileSync(new URL('../src/components/career/ResumeStudio.jsx', import.meta.url), 'utf8')

test('every input, textarea and select in ResumeStudio has an accessible name', () => {
  const re = /<(input|textarea|select)\b/g
  let m
  let count = 0
  const unlabeled = []
  while ((m = re.exec(src))) {
    count += 1
    // Attributes before style= (id / aria-label come first in this file).
    const rest = src.slice(m.index)
    const styleAt = rest.indexOf('style=')
    const head = rest.slice(0, styleAt > 0 ? styleAt : 400)
    const aria = /aria-label(ledby)?=/.test(head)
    const id = head.match(/\bid="([^"]+)"/)
    const labelled = id && new RegExp(`htmlFor="${id[1]}"`).test(src)
    if (!aria && !labelled) unlabeled.push(`${m[1]} at offset ${m.index}`)
  }
  assert.ok(count >= 8, `expected at least 8 form controls, found ${count}`)
  assert.deepEqual(unlabeled, [])
})
