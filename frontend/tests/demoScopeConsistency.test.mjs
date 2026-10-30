import test from 'node:test'
import assert from 'node:assert/strict'
import {
  setChatIncludeDemo,
  getChatIncludeDemo,
} from '../src/api/chatApi.js'
import {
  proposeSchedule,
  commitSchedule,
  checkReactiveSchedule,
} from '../src/api/calendarApi.js'
import {
  buildAgentRunBody,
  buildFeasibilityBody,
  buildProposeScheduleBody,
  buildCommitScheduleBody,
  buildReactiveCheckBody,
} from '../src/utils/requestBodies.js'

test('getChatIncludeDemo returns the flag set by setChatIncludeDemo', () => {
  setChatIncludeDemo(false)
  assert.equal(getChatIncludeDemo(), false)

  setChatIncludeDemo(true)
  assert.equal(getChatIncludeDemo(), true)

  setChatIncludeDemo(false)
  assert.equal(getChatIncludeDemo(), false)
})

test('buildAgentRunBody contains include_demo true when flag is on and never true when off', () => {
  try {
    setChatIncludeDemo(false)
    const offBody = buildAgentRunBody({ goal: 'Organize backlog', max_steps: 8 })
    assert.equal(offBody.include_demo, undefined, 'include_demo must not be set on agent run when demo is inactive')
    assert.notEqual(offBody.include_demo, true)

    setChatIncludeDemo(true)
    const onBody = buildAgentRunBody({ goal: 'Organize backlog', max_steps: 8 })
    assert.equal(onBody.include_demo, true, 'include_demo must be true on agent run when demo is active')
  } finally {
    setChatIncludeDemo(false)
  }
})

test('buildFeasibilityBody contains include_demo true when flag is on and never true when off', () => {
  try {
    setChatIncludeDemo(false)
    const offBody = buildFeasibilityBody({ goal: 'feasibility: 3 days left working 6 hours' })
    assert.equal(offBody.days, 3)
    assert.equal(offBody.hours_per_day, 6.0)
    assert.equal(offBody.include_demo, undefined, 'include_demo must not be set on feasibility when demo is inactive')
    assert.notEqual(offBody.include_demo, true)

    setChatIncludeDemo(true)
    const onBody = buildFeasibilityBody({ goal: 'feasibility: 3 days left working 6 hours' })
    assert.equal(onBody.days, 3)
    assert.equal(onBody.hours_per_day, 6.0)
    assert.equal(onBody.include_demo, true, 'include_demo must be true on feasibility when demo is active')
  } finally {
    setChatIncludeDemo(false)
  }
})

test('buildProposeScheduleBody contains include_demo true when flag is on and never true when off', () => {
  try {
    setChatIncludeDemo(false)
    const offBody = buildProposeScheduleBody({ targetDate: '2026-11-01', domain: 'hackathon', taskIds: [1, 2] })
    assert.equal(offBody.target_date, '2026-11-01')
    assert.equal(offBody.domain, 'hackathon')
    assert.deepEqual(offBody.task_ids, [1, 2])
    assert.equal(offBody.include_demo, undefined)
    assert.notEqual(offBody.include_demo, true)

    setChatIncludeDemo(true)
    const onBody = buildProposeScheduleBody({ targetDate: '2026-11-01', domain: 'hackathon', taskIds: [1, 2] })
    assert.equal(onBody.include_demo, true)
  } finally {
    setChatIncludeDemo(false)
  }
})

test('buildCommitScheduleBody contains include_demo true when flag is on and never true when off', () => {
  try {
    const assignments = [{ task_id: 1, scheduled_start: '2026-11-01T09:00:00Z', scheduled_end: '2026-11-01T10:00:00Z' }]
    setChatIncludeDemo(false)
    const offBody = buildCommitScheduleBody(assignments, 'Test rationale')
    assert.deepEqual(offBody.assignments, assignments)
    assert.equal(offBody.rationale, 'Test rationale')
    assert.equal(offBody.include_demo, undefined)
    assert.notEqual(offBody.include_demo, true)

    setChatIncludeDemo(true)
    const onBody = buildCommitScheduleBody(assignments, 'Test rationale')
    assert.equal(onBody.include_demo, true)
  } finally {
    setChatIncludeDemo(false)
  }
})

test('buildReactiveCheckBody contains include_demo true when flag is on and never true when off', () => {
  try {
    setChatIncludeDemo(false)
    const offBody = buildReactiveCheckBody('2026-11-01T12:00:00Z')
    assert.equal(offBody.current_time, '2026-11-01T12:00:00Z')
    assert.equal(offBody.include_demo, undefined)
    assert.notEqual(offBody.include_demo, true)

    setChatIncludeDemo(true)
    const onBody = buildReactiveCheckBody('2026-11-01T12:00:00Z')
    assert.equal(onBody.current_time, '2026-11-01T12:00:00Z')
    assert.equal(onBody.include_demo, true)
  } finally {
    setChatIncludeDemo(false)
  }
})

test('calendarApi endpoints send include_demo in POST body only when flag is on', async () => {
  const originalFetch = globalThis.fetch
  const captured = []
  globalThis.fetch = async (url, options = {}) => {
    captured.push({
      url: String(url),
      method: options.method,
      body: options.body ? JSON.parse(options.body) : null,
    })
    return {
      ok: true,
      status: 200,
      json: async () => ({ status: 'ok', data: {} }),
    }
  }

  try {
    // When demo is OFF:
    setChatIncludeDemo(false)
    await proposeSchedule({ targetDate: '2026-11-01' })
    await commitSchedule([])
    await checkReactiveSchedule('2026-11-01T10:00:00Z')

    assert.equal(captured.length, 3)
    assert.equal('include_demo' in captured[0].body, false, 'proposeSchedule must omit include_demo when off')
    assert.notEqual(captured[0].body.include_demo, true)
    assert.equal('include_demo' in captured[1].body, false, 'commitSchedule must omit include_demo when off')
    assert.notEqual(captured[1].body.include_demo, true)
    assert.equal('include_demo' in captured[2].body, false, 'checkReactiveSchedule must omit include_demo when off')
    assert.notEqual(captured[2].body.include_demo, true)

    // When demo is ON:
    setChatIncludeDemo(true)
    await proposeSchedule({ targetDate: '2026-11-01' })
    await commitSchedule([])
    await checkReactiveSchedule('2026-11-01T10:00:00Z')

    assert.equal(captured.length, 6)
    assert.equal(captured[3].body.include_demo, true, 'proposeSchedule sends include_demo: true when on')
    assert.equal(captured[4].body.include_demo, true, 'commitSchedule sends include_demo: true when on')
    assert.equal(captured[5].body.include_demo, true, 'checkReactiveSchedule sends include_demo: true when on')
  } finally {
    setChatIncludeDemo(false)
    globalThis.fetch = originalFetch
  }
})
