import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'

const read = rel => fs.readFileSync(new URL(`../src/${rel}`, import.meta.url), 'utf8')
const CARD = 'components/sidebar/SidebarStatusCard.jsx'

test('SidebarStatusCard has a default export', () => {
  const src = read(CARD)
  assert.match(src, /export default function SidebarStatusCard\s*\(|export default SidebarStatusCard/)
})

test('SidebarStatusCard keeps the stable ids', () => {
  const src = read(CARD)
  assert.ok(src.includes('sidebar-specs-card'))
  assert.ok(src.includes('sidebar-status-bolt'))
  assert.ok(src.includes('sidebar-retry-connection-button'))
})

test('SidebarStatusCard reuses the lightning bolt polygon', () => {
  assert.ok(read(CARD).includes('13 2 3 14 12 14 11 22 21 10 12 10 13 2'))
})

test('SidebarStatusCard is keyboard accessible', () => {
  const src = read(CARD)
  assert.match(src, /role=["'{]+\s*button/)
  assert.match(src, /tabIndex/)
  assert.match(src, /onKeyDown/)
  assert.match(src, /['"]Enter['"]/)
  assert.match(src, /['"] ['"]/)
  assert.ok(src.includes('stopPropagation'))
})

test('SidebarStatusCard animates safely with sbs- keyframes and reduced motion', () => {
  const src = read(CARD)
  assert.ok(src.includes('prefers-reduced-motion'))
  assert.match(src, /@keyframes sbs-[\w-]+/)
})

test('SidebarStatusCard renders collapsed and expanded branches', () => {
  const src = read(CARD)
  assert.match(src, /\bcollapsed\b/)
  assert.match(src, /if\s*\(\s*collapsed\s*\)|collapsed\s*\?|collapsed\s*&&|!collapsed/)
  assert.ok(src.includes('children'))
  for (const prop of ['isOnline', 'totalActive', 'backendStatus', 'onRetryConnection', 'onOpenTelemetry']) {
    assert.ok(src.includes(prop), `missing prop ${prop}`)
  }
})

test('Sidebar imports and renders SidebarStatusCard with the contract props', () => {
  const src = read('components/Sidebar.jsx')
  assert.match(src, /import\s+SidebarStatusCard\s+from\s+['"][^'"]*SidebarStatusCard(\.jsx)?['"]/)
  const m = src.match(/<SidebarStatusCard\b[\s\S]*?>/)
  assert.ok(m, 'Sidebar must render <SidebarStatusCard')
  for (const prop of ['collapsed', 'isOnline', 'totalActive', 'backendStatus', 'onRetryConnection', 'onOpenTelemetry']) {
    assert.match(m[0], new RegExp(`\\b${prop}=`), `missing prop ${prop}`)
  }
})
