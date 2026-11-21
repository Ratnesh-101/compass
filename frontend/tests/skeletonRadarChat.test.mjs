import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const read = (rel) => readFileSync(new URL(rel, import.meta.url), 'utf8')

test('InternshipRadar uses the card skeleton while loading', () => {
  const src = read('../src/components/InternshipRadar.jsx')
  assert.ok(src.includes("import { RadarCardsSkeleton } from './Skeleton'"))
  assert.ok(src.includes('<RadarCardsSkeleton count={4} />'))
  assert.ok(!src.includes('Loading verified opportunities'))
  assert.ok(src.includes(') : error ? ('))
  assert.ok(src.includes('Loader2'))
})

test('ChatPanel passes loadingHistory to the drawer and stays small', () => {
  const src = read('../src/components/ChatPanel.jsx')
  assert.ok(src.includes('const [loadingHistory, setLoadingHistory] = useState(false)'))
  assert.ok(src.includes('loadingHistory={loadingHistory}'))
  assert.ok(!src.includes('_loadingHistory'))
  assert.ok(src.split('\n').length <= 700)
})

test('ChatHistoryDrawer shows the history skeleton only while loading', () => {
  const src = read('../src/components/chat/ChatHistoryDrawer.jsx')
  assert.ok(src.includes("import { ChatHistorySkeleton } from '../Skeleton'"))
  assert.ok(src.includes('loadingHistory = false'))
  assert.ok(src.includes('loadingHistory && !showArchived && visibleConversations.length === 0'))
  assert.ok(src.includes('<ChatHistorySkeleton rows={6} />'))
  assert.ok(src.includes('No previous chats yet.'))
  assert.ok(src.includes('No archived chats.'))
})
