import test from 'node:test'
import assert from 'node:assert/strict'
import {
  STAGES,
  BACKEND_STATUSES,
  stageOfStatus,
  stageLabel,
  stageDetail,
  countApplications,
  filterByStage,
  blockedMessage,
  planStageMove,
} from '../src/utils/applicationStages.js'
import { APPLICATION_STATUS_LABELS } from '../src/utils/careerUiHelpers.js'

test('there are six stages in the order a student thinks about them', () => {
  assert.deepEqual(STAGES.map(s => s.label), ['Saved', 'Preparing', 'Applied', 'Interview', 'Offer', 'Closed'])
})

test('every one of the 23 backend statuses maps to a stage', () => {
  const backend = Object.keys(APPLICATION_STATUS_LABELS)
  assert.equal(backend.length, 23)
  for (const status of backend) {
    assert.ok(BACKEND_STATUSES.includes(status), `${status} has no stage`)
    assert.ok(STAGES.some(s => s.key === stageOfStatus(status)), `${status} maps to an unknown stage`)
  }
  assert.equal(BACKEND_STATUSES.length, backend.length)
})

test('status to stage mapping', () => {
  assert.equal(stageOfStatus('SAVED'), 'saved')
  assert.equal(stageOfStatus('RESUME_VALIDATION_FAILED'), 'preparing')
  assert.equal(stageOfStatus('READY_FOR_REVIEW'), 'preparing')
  assert.equal(stageOfStatus('HANDOFF_KIT_READY'), 'preparing')
  assert.equal(stageOfStatus('SUBMITTED'), 'applied')
  assert.equal(stageOfStatus('ASSESSMENT_RECEIVED'), 'interview')
  assert.equal(stageOfStatus('INTERVIEW'), 'interview')
  assert.equal(stageOfStatus('OFFER_RECEIVED'), 'offer')
  assert.equal(stageOfStatus('REJECTED'), 'closed')
  assert.equal(stageOfStatus('WITHDRAWN'), 'closed')
  assert.equal(stageOfStatus('closed'), 'closed')
  assert.equal(stageOfStatus('something_new'), 'preparing')
  assert.equal(stageOfStatus(undefined), 'preparing')
  assert.equal(stageLabel('applied'), 'Applied')
})

test('stage detail is plain words and empty when there is nothing to add', () => {
  assert.equal(stageDetail('RESUME_VALIDATION_FAILED'), 'Needs your details')
  assert.equal(stageDetail('SAVED'), '')
  assert.doesNotMatch(stageDetail('HANDOFF_KIT_READY'), /kit/i)
})

test('one counter: active excludes only Closed, total includes all', () => {
  const apps = [
    { status: 'SAVED' },
    { status: 'RESUME_VALIDATION_FAILED' },
    { status: 'SUBMITTED' },
    { status: 'REJECTED' },
    { status: 'CLOSED' },
  ]
  const c = countApplications(apps)
  assert.equal(c.total, 5)
  assert.equal(c.active, 3)
  assert.deepEqual(c.byStage, { saved: 1, preparing: 1, applied: 1, interview: 0, offer: 0, closed: 2 })
  assert.deepEqual(countApplications(null), { total: 0, active: 0, byStage: { saved: 0, preparing: 0, applied: 0, interview: 0, offer: 0, closed: 0 } })
})

test('a failed resume check shows under Preparing, not only under All', () => {
  const apps = [{ id: 1, status: 'RESUME_VALIDATION_FAILED' }, { id: 2, status: 'SUBMITTED' }]
  assert.deepEqual(filterByStage(apps, 'preparing').map(a => a.id), [1])
  assert.deepEqual(filterByStage(apps, 'all').map(a => a.id), [1, 2])
})

test('blocked message says what is missing in plain words', () => {
  const app = {
    status: 'RESUME_VALIDATION_FAILED',
    resume: { content: { full_name: '', email: '' }, validation_report: { missing_fields: ['Phone number'] } },
  }
  const msg = blockedMessage(app)
  assert.match(msg, /your full name/)
  assert.match(msg, /your email address/)
  assert.match(msg, /your phone number/)
  assert.match(msg, /My resume/)
  assert.doesNotMatch(msg, /VALIDATION|RESUME_/)
})

test('blocked message is null for applications that are not blocked', () => {
  assert.equal(blockedMessage({ status: 'READY_FOR_REVIEW' }), null)
  assert.equal(blockedMessage({ status: 'SUBMITTED' }), null)
  assert.ok(blockedMessage({ status: 'RESUME_VALIDATION_FAILED' }))
})

test('moving to Applied uses mark-applied and only when the application is ready', () => {
  assert.deepEqual(planStageMove('READY_FOR_REVIEW', 'applied'), { ok: true, steps: [{ type: 'mark_applied' }] })
  const blocked = planStageMove('RESUME_VALIDATION_FAILED', 'applied')
  assert.equal(blocked.ok, false)
  assert.match(blocked.reason, /Finish preparing/)
})

test('Interview and Offer need Applied first', () => {
  assert.equal(planStageMove('READY_FOR_REVIEW', 'interview').ok, false)
  assert.deepEqual(planStageMove('SUBMITTED', 'interview').steps, [{ type: 'status', status: 'INTERVIEW' }])
  assert.deepEqual(planStageMove('INTERVIEW', 'offer').steps, [{ type: 'status', status: 'OFFER_RECEIVED' }])
})

test('Closed withdraws first when the transition table needs it', () => {
  assert.deepEqual(planStageMove('SUBMITTED', 'closed').steps, [
    { type: 'status', status: 'WITHDRAWN' },
    { type: 'status', status: 'CLOSED' },
  ])
  assert.deepEqual(planStageMove('OFFER_RECEIVED', 'closed').steps, [{ type: 'status', status: 'CLOSED' }])
  assert.deepEqual(planStageMove('SUBMITTED', 'applied').steps, [])
})
