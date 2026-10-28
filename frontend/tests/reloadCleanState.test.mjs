import test from 'node:test'
import assert from 'node:assert/strict'
import { fetchTasks } from '../src/api/tasksApi.js'
import { isDemoTask } from '../src/utils/demoConstants.js'

test('isDemoTask correctly distinguishes dummy demo tasks from genuine user tasks', () => {
  const dummyTask1 = {
    id: '1',
    title: '36-hour Hackathon Sprint: Final Demo Build',
    is_demo: true,
    tags: ['hackathon', 'demo'],
  }
  const dummyTask2 = {
    id: '2',
    title: 'CS 61C Lab 4: RISC-V Pipeline Synthesis',
    trusted_event_url: 'compass://demo-persona/cs_61c_lab_4',
  }
  const dummyTask3 = {
    id: '3',
    title: 'Fallback Task',
    is_fallback: true,
  }
  // Legacy untagged demo tasks with trusted_event_url null and is_demo undefined
  const legacyUntaggedDemoTask = {
    id: '453',
    title: 'CS 61C Midterm Review: Cache Hierarchies & Virtual Memory',
    trusted_event_url: null,
    domain: 'coursework',
  }

  const userTask1 = {
    id: '10',
    title: 'Complete Math 54 Homework 4',
    domain: 'coursework',
    due_date: '2026-10-24',
    tags: ['coursework', 'math'],
    trusted_event_url: null,
  }
  const userTask2 = {
    id: '11',
    title: 'Submit job application to Nebius',
    domain: 'career',
    tags: ['career'],
  }

  assert.equal(isDemoTask(dummyTask1), true)
  assert.equal(isDemoTask(dummyTask2), true)
  assert.equal(isDemoTask(dummyTask3), true)
  assert.equal(isDemoTask(legacyUntaggedDemoTask), true, 'Legacy untagged demo task must be identified as demo')

  assert.equal(isDemoTask(userTask1), false)
  assert.equal(isDemoTask(userTask2), false)
})

test('Site reload filter: dummy demo data is purged, preserving only genuine user tasks', () => {
  const mixedTasksFromStorageOrDB = [
    {
      id: '1',
      title: '36-hour Hackathon Sprint: Final Demo Build',
      is_demo: true,
      tags: ['hackathon', 'demo'],
    },
    {
      id: '2',
      title: 'CS 61C Lab 4: RISC-V Pipeline Synthesis',
      trusted_event_url: 'compass://demo-persona/cs_61c_lab_4',
    },
    {
      id: '3',
      title: 'Nebius Buildathon Phase 2 Submission',
      tags: ['hackathon', 'demo'],
    },
    {
      id: '101',
      title: 'My Custom User Task: Prepare slide deck',
      domain: 'code',
      is_demo: false,
      tags: ['code'],
    },
  ]

  // On reload, demoActive is false
  const demoActiveOnReload = false
  const activeTasks = demoActiveOnReload
    ? mixedTasksFromStorageOrDB
    : mixedTasksFromStorageOrDB.filter((t) => !isDemoTask(t))

  assert.equal(activeTasks.length, 1)
  assert.equal(activeTasks[0].id, '101')
  assert.equal(activeTasks[0].title, 'My Custom User Task: Prepare slide deck')
})

test('fetchTasks on network failure returns null (not an empty list), never dummy fallback tasks', async () => {
  // Global fetch rejection mock
  const originalFetch = globalThis.fetch
  globalThis.fetch = async () => {
    throw new Error('Connection refused')
  }

  try {
    const tasks = await fetchTasks('all')
    assert.equal(tasks, null, 'Must signal failure with null so callers keep the current view, never dummy fallback tasks')
  } finally {
    globalThis.fetch = originalFetch
  }
})
