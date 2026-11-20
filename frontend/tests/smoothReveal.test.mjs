import test from 'node:test'
import assert from 'node:assert/strict'
import { nextRevealLength, revealedPrefix, isContinuation } from '../src/utils/smoothReveal.js'

test('reduced motion returns the full target immediately', () => {
  assert.equal(nextRevealLength({ shown: 0, target: 500, dtMs: 16, reduced: true }), 500)
  assert.equal(nextRevealLength({ shown: 10, target: 40, dtMs: 0, reduced: true }), 40)
})

test('returns target when everything is already shown', () => {
  assert.equal(nextRevealLength({ shown: 50, target: 50, dtMs: 16 }), 50)
  assert.equal(nextRevealLength({ shown: 80, target: 50, dtMs: 16 }), 50)
})

test('never exceeds target and never goes below shown', () => {
  for (const target of [1, 2, 7, 60, 300, 5000]) {
    for (const shown of [0, 1, 3, 59, 250]) {
      if (shown > target) continue
      for (const dtMs of [0, 1, 16, 33, 100, 5000]) {
        const next = nextRevealLength({ shown, target, dtMs })
        assert.ok(Number.isInteger(next))
        assert.ok(next >= shown, `next ${next} < shown ${shown}`)
        assert.ok(next <= target, `next ${next} > target ${target}`)
      }
    }
  }
})

test('a small backlog types out gently, one or two characters per frame', () => {
  const next = nextRevealLength({ shown: 90, target: 100, dtMs: 16 })
  assert.ok(next === 91 || next === 92, `step to ${next}`)
  assert.equal(nextRevealLength({ shown: 0, target: 5, dtMs: 16 }), 1)
})

test('a large backlog catches up fast', () => {
  const next = nextRevealLength({ shown: 0, target: 2000, dtMs: 16 })
  assert.ok(next - 0 > 20, `step ${next} should be well above 20`)
})

test('a large backlog is cleared in about a second and a half at most', () => {
  let shown = 0
  let ms = 0
  while (shown < 2000 && ms < 5000) {
    shown = nextRevealLength({ shown, target: 2000, dtMs: 16 })
    ms += 16
  }
  assert.equal(shown, 2000)
  assert.ok(ms <= 1500, `took ${ms}ms`)
})

test('dtMs is clamped between 0 and 100', () => {
  const huge = nextRevealLength({ shown: 0, target: 100000, dtMs: 60000 })
  const capped = nextRevealLength({ shown: 0, target: 100000, dtMs: 100 })
  assert.equal(huge, capped)
  const negative = nextRevealLength({ shown: 5, target: 100, dtMs: -50 })
  const zero = nextRevealLength({ shown: 5, target: 100, dtMs: 0 })
  assert.equal(negative, zero)
  assert.ok(negative >= 5 && negative <= 100)
})

test('non-finite inputs are treated as 0 and never produce NaN', () => {
  const a = nextRevealLength({ shown: 0, target: 100, dtMs: NaN })
  assert.ok(Number.isInteger(a) && a >= 0 && a <= 100)
  assert.equal(nextRevealLength({ shown: NaN, target: 100, dtMs: 16 }), nextRevealLength({ shown: 0, target: 100, dtMs: 16 }))
  assert.equal(nextRevealLength({ shown: 0, target: NaN, dtMs: 16 }), 0)
  assert.equal(nextRevealLength({ shown: Infinity, target: 10, dtMs: 16 }), nextRevealLength({ shown: 0, target: 10, dtMs: 16 }))
  assert.equal(nextRevealLength({ shown: 0, target: 100, dtMs: Infinity }), nextRevealLength({ shown: 0, target: 100, dtMs: 0 }))
  assert.equal(nextRevealLength({ shown: undefined, target: undefined, dtMs: undefined }), 0)
})

test('revealedPrefix slices plain text normally', () => {
  assert.equal(revealedPrefix('hello world', 5), 'hello')
  assert.equal(revealedPrefix('hello', 0), '')
  assert.equal(revealedPrefix('hello', 99), 'hello')
})

test('revealedPrefix never cuts a surrogate pair in half', () => {
  const text = 'a😀b'
  assert.equal(text.length, 4)
  assert.equal(revealedPrefix(text, 1), 'a')
  assert.equal(revealedPrefix(text, 2), 'a')
  assert.equal(revealedPrefix(text, 3), 'a😀')
  assert.equal(revealedPrefix(text, 4), text)
  assert.equal(revealedPrefix('😀', 1), '')
})

test('isContinuation is true when the text kept growing', () => {
  assert.equal(isContinuation('Hello', 'Hello world'), true)
  assert.equal(isContinuation('Hello', 'Hello'), true)
  assert.equal(isContinuation('', 'anything'), true)
})

test('isContinuation is false when the text was replaced', () => {
  assert.equal(isContinuation('Hello world', 'Hello'), false)
  assert.equal(isContinuation('Hello', 'Goodbye'), false)
  assert.equal(isContinuation('Hello', undefined), false)
})

function clearTime(total) {
  let shown = 0
  let ms = 0
  while (shown < total && ms < 20000) {
    shown = nextRevealLength({ shown, target: total, dtMs: 16 })
    ms += 16
  }
  return ms
}

test('a 500-character answer types out steadily, not in a flash', () => {
  const ms = clearTime(500)
  assert.ok(ms >= 700 && ms <= 1200, `took ${ms}ms`)
})

test('no answer length waits more than about a second and a half', () => {
  for (const n of [60, 400, 1000, 2000, 5000, 20000]) {
    assert.ok(clearTime(n) <= 1500, `${n} chars took ${clearTime(n)}ms`)
  }
})

test('the displayed text never trails the received text by more than 1000 characters', () => {
  let shown = 0
  for (let i = 0; i < 40; i++) {
    shown = nextRevealLength({ shown, target: 50000, dtMs: 16 })
    assert.ok(50000 - shown <= 1000 + 800, `backlog ${50000 - shown} at step ${i}`)
  }
})

test('the per-frame step respects the pace cap for a short backlog', () => {
  const next = nextRevealLength({ shown: 0, target: 200, dtMs: 16 })
  assert.ok(next <= 9, `step ${next} exceeds about 500 chars/second`)
})
