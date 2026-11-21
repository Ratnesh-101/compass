import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const read = (name) => readFileSync(new URL(`../src/${name}`, import.meta.url), 'utf8')

test('App.jsx wires the skeleton and tasksSettled state', () => {
  const src = read('App.jsx')
  assert.ok(src.includes("import { TabSkeleton } from './components/Skeleton'"))
  assert.ok(src.includes('<TabSkeleton variant="career" />'))
  assert.match(src, /tasksSettled[^\n]*useState\(false\)/)
  assert.ok(src.split('setTasksSettled(true)').length - 1 >= 3)
  assert.doesNotMatch(src, /setTasksSettled\(false\)/)
  assert.ok(src.includes('60000'))
  assert.ok(src.includes('20000'))
  assert.ok(src.includes('clearTimeout'))
  assert.equal(src.split('tasksLoading={!tasksSettled}').length - 1, 2)
  assert.ok(!src.includes('Loading Career Copilot'))
})

test('Dashboard.jsx shows the skeleton only while loading and keeps other states', () => {
  const src = read('components/Dashboard.jsx')
  assert.ok(src.includes("from './Skeleton'"))
  assert.ok(src.includes('tasksLoading = false'))
  assert.ok(src.includes('const showTasksSkeleton = isOnline && tasksLoading && cleanTasks.length === 0'))
  assert.ok(src.includes('{showTasksSkeleton && <DashboardSkeleton />}'))
  assert.ok(src.includes('{!isOnline && cleanTasks.length === 0 && ('))
  assert.ok(src.includes('No tasks or deadlines tracked yet'))
  assert.ok(src.includes('dashboard-waking-card'))
})

test('Timeline.jsx swaps only the no-data branch for the skeleton', () => {
  const src = read('components/Timeline.jsx')
  assert.ok(src.includes("from './Skeleton'"))
  assert.ok(src.includes('tasksLoading = false'))
  assert.ok(src.includes('<TimelineSkeleton />'))
  assert.ok(src.includes('No tasks yet'))
  assert.ok(src.includes('No tasks match the selected filters'))
})
