import test from 'node:test'
import assert from 'node:assert/strict'
import { plainJobDescription } from '../src/utils/plainJobDescription.js'

test('returns empty string for null, undefined and blank input', () => {
  assert.equal(plainJobDescription(null), '')
  assert.equal(plainJobDescription(undefined), '')
  assert.equal(plainJobDescription('   \n  '), '')
})

test('strips heading hashes', () => {
  assert.equal(plainJobDescription('### About the role\nBuild things.'), 'About the role\nBuild things.')
  assert.equal(plainJobDescription('##### Minor heading'), 'Minor heading')
})

test('turns markdown links into their text, including titles', () => {
  const out = plainJobDescription('See [our careers page](https://example.com/jobs "Opens in a new window") now.')
  assert.equal(out, 'See our careers page now.')
})

test('drops bare URLs and image syntax', () => {
  const out = plainJobDescription('Apply at https://example.com/apply today. ![logo](https://x.com/a.png)')
  assert.ok(!out.includes('http'))
  assert.ok(!out.includes('!['))
  assert.ok(out.startsWith('Apply at'))
})

test('unescapes backslash-escaped characters', () => {
  assert.equal(plainJobDescription('my\\_var and 5\\. item'), 'my_var and 5. item')
})

test('converts * and - bullets to bullet lines', () => {
  const out = plainJobDescription('* Python\n- SQL\n* Docker')
  assert.equal(out, '• Python\n• SQL\n• Docker')
})

test('removes bold markers', () => {
  assert.equal(plainJobDescription('This is **important** text'), 'This is important text')
})

test('collapses whitespace but keeps paragraph breaks', () => {
  const out = plainJobDescription('One   two\t three\n\n\n\nSecond   paragraph')
  assert.equal(out, 'One two three\n\nSecond paragraph')
})

test('leaves short text untruncated', () => {
  const text = 'A short sentence. Another one.'
  assert.equal(plainJobDescription(text), text)
})

test('truncates long text at a sentence boundary with an ellipsis', () => {
  const sentence = 'This sentence is exactly fifty characters long ok. '
  const text = sentence.repeat(60)
  const out = plainJobDescription(text)
  assert.ok(out.length <= 1201)
  assert.ok(out.endsWith('.…'))
})

test('respects a custom max length and falls back to a word boundary', () => {
  const out = plainJobDescription('word '.repeat(100), 50)
  assert.ok(out.endsWith('…'))
  assert.ok(out.length <= 51)
  assert.ok(!out.includes('wor…'))
})

test('cleans flattened scrapes with mid-line markers and leaked icon names', () => {
  const raw = '### What is GSoC? A global program. * play\_circle\_outline Learn more [Watch video](https://example.com/v "Opens in a new window") * people\_alt Orgs are ready. ##### Why participate.'
  const out = plainJobDescription(raw)
  assert.ok(!/#|play_circle|people_alt|https?:|\]\(/.test(out), out)
  assert.ok(out.includes('• Learn more Watch video'), out)
  assert.ok(out.includes('\n\nWhy participate.'), out)
})
