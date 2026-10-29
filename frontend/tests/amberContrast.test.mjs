import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const css = fs.readFileSync(path.resolve(__dirname, '../src/index.css'), 'utf8')
const readSrc = rel => fs.readFileSync(path.resolve(__dirname, '../src', rel), 'utf8')

function luminance(hex) {
  const [r, g, b] = [1, 3, 5].map(i => parseInt(hex.slice(i, i + 2), 16) / 255)
    .map(v => (v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4))
  return 0.2126 * r + 0.7152 * g + 0.0722 * b
}

function contrast(a, b) {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x)
  return (hi + 0.05) / (lo + 0.05)
}

function token(block, name) {
  const m = block.match(new RegExp(`--${name}:\\s*(#[0-9a-fA-F]{6})`))
  assert.ok(m, `token --${name} missing`)
  return m[1]
}

// The first block defining --bg-app is light :root, the second is the dark theme.
const blocks = css.split(/\n(?=[^\s}][^{]*\{)/).filter(b => /--bg-app:/.test(b))
const light = blocks[0]
const dark = blocks[1]

test('light-mode amber text token reaches WCAG AA on every light surface', () => {
  const fg = token(light, 'amber-text')
  for (const bg of ['bg-card', 'bg-app', 'bg-card-soft']) {
    const ratio = contrast(fg, token(light, bg))
    assert.ok(ratio >= 4.5, `${fg} on ${bg} is ${ratio.toFixed(2)}`)
  }
  assert.ok(contrast(fg, '#fef3c7') >= 4.5, 'amber badge background')
})

test('dark-mode amber text token reaches WCAG AA on every dark surface', () => {
  const fg = token(dark, 'amber-text')
  for (const bg of ['bg-card', 'bg-app', 'bg-card-soft']) {
    const ratio = contrast(fg, token(dark, bg))
    assert.ok(ratio >= 4.5, `${fg} on ${bg} is ${ratio.toFixed(2)}`)
  }
})

test('the old low-contrast amber text colour is gone from text', () => {
  const offenders = []
  const walk = d => {
    for (const e of fs.readdirSync(d, { withFileTypes: true })) {
      const p = path.join(d, e.name)
      if (e.isDirectory()) walk(p)
      else if (/\.jsx$/.test(e.name) && /(?<![a-zA-Z])color: '#b45309'/.test(fs.readFileSync(p, 'utf8'))) offenders.push(p)
    }
  }
  walk(path.resolve(__dirname, '../src'))
  assert.deepEqual(offenders, [])
})

test('"Sources found" label and refresh cooldown use the amber text token, not the brand fill', () => {
  const src = readSrc('components/career/ApplicationWorkspaceModal.jsx')
  const i = src.indexOf('companyIntel.fallback_label}')
  assert.ok(i > 0)
  assert.match(src.slice(i - 500, i), /var\(--amber-text\)/)
  const j = src.indexOf('Refresh available in')
  assert.match(src.slice(j - 200, j), /var\(--amber-text\)/)
})

test('EvidenceCard STALE and PARTIALLY_VERIFIED badges no longer use the low-contrast orange', () => {
  assert.doesNotMatch(readSrc('components/chat/EvidenceCard.jsx'), /text: '#e65100'/)
})
