import { test } from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'

const read = (p) => fs.readFileSync(new URL(p, import.meta.url), 'utf8')

test('Radar application card offers Open workspace wired to the workspace opener', () => {
  const src = read('../src/components/radar/RadarOpportunityCard.jsx')
  const m = src.match(/\{application_status && \(\s*<button[^>]*?onClick=\{\(\) => onApply\(opportunity\)\}[\s\S]{0,300}?Open workspace/)
  assert.ok(m, 'Open workspace button calls onApply(opportunity) for prepared applications')
  assert.match(src, /'View Progress'/)
})

test('Radar passes the workspace opener as onApply', () => {
  const src = read('../src/components/InternshipRadar.jsx')
  assert.match(src, /onApply=\{setActiveWorkspaceOpp\}/)
  assert.match(src, /<ApplicationWorkspaceModal/)
})

test('Application Center rows offer Open workspace and render the same modal', () => {
  const src = read('../src/components/career/ApplicationCenter.jsx')
  assert.match(src, /onClick=\{\(\) => setActiveWorkspaceOpp\(app\.opportunity\)\}[\s\S]{0,700}?Open workspace/)
  assert.match(src, /React\.lazy\(\(\) => import\('\.\/ApplicationWorkspaceModal'\)\)/)
  assert.match(src, /<ApplicationWorkspaceModal[\s\S]{0,200}opportunity=\{activeWorkspaceOpp\}/)
  assert.match(src, /Application pack/)
})
