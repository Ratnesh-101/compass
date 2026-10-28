import test from 'node:test'
import assert from 'node:assert/strict'

import {
  parseDeadlineDate,
  classifyDeadline,
  filterTasksByView,
  filterTasksByStatusAndDue,
  calculateFilterCounts,
  sortOverdueDeadlines,
  sortUpcomingDeadlines,
} from '../src/utils/deadlineClassifier.js'

test('parseDeadlineDate parses date-only YYYY-MM-DD strings to end of local day', () => {
  const res = parseDeadlineDate('2026-05-15')
  assert.equal(res.isDateOnly, true)
  assert.equal(res.year, 2026)
  assert.equal(res.month, 4)
  assert.equal(res.day, 15)
  assert.ok(res.date instanceof Date)
  assert.equal(res.date.getFullYear(), 2026)
  assert.equal(res.date.getMonth(), 4)
  assert.equal(res.date.getDate(), 15)
  assert.equal(res.date.getHours(), 23)
  assert.equal(res.date.getMinutes(), 59)
  assert.equal(res.date.getSeconds(), 59)
  assert.equal(res.date.getMilliseconds(), 999)
})

test('parseDeadlineDate parses ISO timestamp strings', () => {
  const isoStr = '2026-05-15T10:30:00.000Z'
  const res = parseDeadlineDate(isoStr)
  assert.equal(res.isDateOnly, false)
  assert.ok(res.date instanceof Date)
  assert.equal(res.date.getTime(), new Date(isoStr).getTime())
})

test('parseDeadlineDate handles empty, null, undefined, non-string, and malformed inputs', () => {
  assert.deepEqual(parseDeadlineDate(''), { date: null, isDateOnly: false })
  assert.deepEqual(parseDeadlineDate('   '), { date: null, isDateOnly: false })
  assert.deepEqual(parseDeadlineDate(null), { date: null, isDateOnly: false })
  assert.deepEqual(parseDeadlineDate(undefined), { date: null, isDateOnly: false })
  assert.deepEqual(parseDeadlineDate(12345), { date: null, isDateOnly: false })
  assert.deepEqual(parseDeadlineDate({}), { date: null, isDateOnly: false })
  assert.deepEqual(parseDeadlineDate('not-a-valid-date'), { date: null, isDateOnly: false })
})

test('classifyDeadline handles null, undefined, or non-object task', () => {
  const fallback = classifyDeadline(null)
  assert.equal(fallback.lifecycle, 'pending')
  assert.equal(fallback.timing, 'no_deadline')
  assert.equal(fallback.priority, 'medium')
  assert.equal(fallback.type, 'none')
  assert.equal(fallback.label, 'Active')
  assert.equal(fallback.isActiveDeadline, false)
  assert.equal(fallback.isUrgent, false)
  assert.equal(fallback.isOverdue, false)

  const nonObj = classifyDeadline('not-a-task-object')
  assert.equal(nonObj.timing, 'no_deadline')
  assert.equal(nonObj.isActiveDeadline, false)
})

test('classifyDeadline excludes completed and cancelled tasks from active deadlines', () => {
  const now = new Date(2026, 4, 15, 12, 0, 0)

  // Status completed with past due date
  const completedTask = { id: 't-comp', status: 'completed', due_date: '2026-05-10' }
  const cRes = classifyDeadline(completedTask, now)
  assert.equal(cRes.lifecycle, 'completed')
  assert.equal(cRes.timing, 'completed')
  assert.equal(cRes.isActiveDeadline, false)
  assert.equal(cRes.isOverdue, false)
  assert.equal(cRes.isUrgent, false)
  assert.equal(cRes.type, 'completed')
  assert.equal(cRes.label, 'Completed')

  // Status done
  const doneTask = { id: 't-done', status: 'done', due_date: '2026-05-10' }
  const doneRes = classifyDeadline(doneTask, now)
  assert.equal(doneRes.lifecycle, 'completed')
  assert.equal(doneRes.timing, 'completed')
  assert.equal(doneRes.isActiveDeadline, false)

  // Countdown completed
  const countdownCompleted = { id: 't-cd-comp', status: 'open', countdown: 'completed', due_date: '2026-05-10' }
  const cdRes = classifyDeadline(countdownCompleted, now)
  assert.equal(cdRes.lifecycle, 'completed')
  assert.equal(cdRes.timing, 'completed')
  assert.equal(cdRes.isActiveDeadline, false)

  // Status cancelled
  const cancelledTask = { id: 't-cancel', status: 'cancelled', due_date: '2026-05-10' }
  const cancelRes = classifyDeadline(cancelledTask, now)
  assert.equal(cancelRes.lifecycle, 'cancelled')
  assert.equal(cancelRes.timing, 'cancelled')
  assert.equal(cancelRes.isActiveDeadline, false)
  assert.equal(cancelRes.isOverdue, false)
  assert.equal(cancelRes.isUrgent, false)
  assert.equal(cancelRes.type, 'cancelled')
  assert.equal(cancelRes.label, 'Cancelled')

  // Status canceled (single l)
  const canceledTask = { id: 't-canceled-1l', status: 'canceled', due_date: '2026-05-10' }
  const canceled1lRes = classifyDeadline(canceledTask, now)
  assert.equal(canceled1lRes.lifecycle, 'cancelled')
  assert.equal(canceled1lRes.timing, 'cancelled')
  assert.equal(canceled1lRes.isActiveDeadline, false)
})

test('classifyDeadline classifies active tasks without deadline as no_deadline', () => {
  const now = new Date(2026, 4, 15, 12, 0, 0)

  const taskWithoutDue = { id: 't-no-due', status: 'open' }
  const res = classifyDeadline(taskWithoutDue, now)
  assert.equal(res.lifecycle, 'pending')
  assert.equal(res.timing, 'no_deadline')
  assert.equal(res.isActiveDeadline, false)
  assert.equal(res.isOverdue, false)
  assert.equal(res.isUrgent, false)
  assert.equal(res.type, 'none')
  assert.equal(res.label, 'No deadline')

  // In-progress task without deadline retains custom countdown label if provided
  const taskWithCountdown = { id: 't-cd', status: 'in_progress', countdown: 'Sprint 3' }
  const resCountdown = classifyDeadline(taskWithCountdown, now)
  assert.equal(resCountdown.lifecycle, 'in_progress')
  assert.equal(resCountdown.timing, 'no_deadline')
  assert.equal(resCountdown.label, 'Sprint 3')
  assert.equal(resCountdown.isActiveDeadline, false)
})

test('classifyDeadline classifies overdue tasks correctly for date-only and timestamp deadlines', () => {
  const now = new Date(2026, 4, 15, 12, 0, 0) // May 15, 12:00

  // Date-only deadline yesterday: May 14
  const dateOnlyPast = { id: 't-past-1d', status: 'open', due_date: '2026-05-14' }
  const resPast = classifyDeadline(dateOnlyPast, now)
  assert.equal(resPast.timing, 'overdue')
  assert.equal(resPast.isActiveDeadline, true)
  assert.equal(resPast.isOverdue, true)
  assert.equal(resPast.isUrgent, true)
  assert.equal(resPast.type, 'overdue')
  assert.equal(resPast.diffDays, -1)
  assert.equal(resPast.label, '⚠️ Overdue (1d ago)')

  // Date-only deadline 4 days ago: May 11
  const dateOnlyPast4d = { id: 't-past-4d', status: 'open', due_date: '2026-05-11' }
  const resPast4d = classifyDeadline(dateOnlyPast4d, now)
  assert.equal(resPast4d.timing, 'overdue')
  assert.equal(resPast4d.diffDays, -4)
  assert.equal(resPast4d.label, '⚠️ Overdue (4d ago)')

  // Timestamp deadline that passed earlier today (10:00 AM on May 15)
  const timestampPassed = {
    id: 't-ts-passed',
    status: 'in_progress',
    due_date: new Date(2026, 4, 15, 10, 0, 0).toISOString(),
  }
  const resTimestampPassed = classifyDeadline(timestampPassed, now)
  assert.equal(resTimestampPassed.timing, 'overdue')
  assert.equal(resTimestampPassed.isActiveDeadline, true)
  assert.equal(resTimestampPassed.isOverdue, true)
  assert.equal(resTimestampPassed.isUrgent, true)
  assert.equal(resTimestampPassed.type, 'overdue')
})

test('classifyDeadline keeps date-only deadline as due_today through its entire local calendar day', () => {
  const task = { id: 't-today', status: 'open', due_date: '2026-05-15' }

  // Early morning on the day
  const morning = new Date(2026, 4, 15, 1, 0, 0)
  const resMorning = classifyDeadline(task, morning)
  assert.equal(resMorning.timing, 'due_today')
  assert.equal(resMorning.isActiveDeadline, true)
  assert.equal(resMorning.isOverdue, false)
  assert.equal(resMorning.isUrgent, true)
  assert.equal(resMorning.diffDays, 0)
  assert.equal(resMorning.type, 'today')
  assert.equal(resMorning.label, '⚠️ Due today')

  // Afternoon on the day
  const afternoon = new Date(2026, 4, 15, 15, 30, 0)
  const resAfternoon = classifyDeadline(task, afternoon)
  assert.equal(resAfternoon.timing, 'due_today')
  assert.equal(resAfternoon.isOverdue, false)
  assert.equal(resAfternoon.isUrgent, true)

  // Late evening on the day (23:59:00)
  const lateEvening = new Date(2026, 4, 15, 23, 59, 0)
  const resLate = classifyDeadline(task, lateEvening)
  assert.equal(resLate.timing, 'due_today')
  assert.equal(resLate.isOverdue, false)
  assert.equal(resLate.isUrgent, true)

  // Immediately upon rolling over into next day -> becomes overdue
  const nextDay = new Date(2026, 4, 16, 0, 0, 1)
  const resNextDay = classifyDeadline(task, nextDay)
  assert.equal(resNextDay.timing, 'overdue')
  assert.equal(resNextDay.isOverdue, true)
})

test('classifyDeadline classifies future timestamp on current calendar day as due_today', () => {
  const now = new Date(2026, 4, 15, 12, 0, 0)
  const futureTimestampToday = {
    id: 't-ts-today',
    status: 'open',
    due_date: new Date(2026, 4, 15, 18, 0, 0).toISOString(),
  }
  const res = classifyDeadline(futureTimestampToday, now)
  assert.equal(res.timing, 'due_today')
  assert.equal(res.isActiveDeadline, true)
  assert.equal(res.isOverdue, false)
  assert.equal(res.isUrgent, true)
  assert.equal(res.label, '⚠️ Due today')
})

test('classifyDeadline classifies deadlines within 24 hours on next calendar day as urgent', () => {
  // Now is May 15 at 20:00 (8:00 PM)
  const now = new Date(2026, 4, 15, 20, 0, 0)
  // Deadline is tomorrow morning at 08:00 (8:00 AM) -> 12 hours away
  const tomorrowMorning = new Date(2026, 4, 16, 8, 0, 0)
  const task = {
    id: 't-urgent',
    status: 'open',
    due_date: tomorrowMorning.toISOString(),
  }
  const res = classifyDeadline(task, now)
  assert.equal(res.timing, 'urgent')
  assert.equal(res.isActiveDeadline, true)
  assert.equal(res.isUrgent, true)
  assert.equal(res.isOverdue, false)
  assert.equal(res.type, 'urgent')
  assert.equal(res.label, '🚨 Due in 12h')
})

test('classifyDeadline classifies remaining deadlines within next 7 days as due_soon', () => {
  const now = new Date(2026, 4, 15, 12, 0, 0) // Friday May 15

  // 3 calendar days away (Monday May 18, 12:00) -> diffHours = 72 > 24
  const monday = new Date(2026, 4, 18, 12, 0, 0)
  const task3d = { id: 't-soon-3d', status: 'open', due_date: monday.toISOString() }
  const res3d = classifyDeadline(task3d, now)
  assert.equal(res3d.timing, 'due_soon')
  assert.equal(res3d.isActiveDeadline, true)
  assert.equal(res3d.isUrgent, false)
  assert.equal(res3d.isOverdue, false)
  assert.equal(res3d.type, 'week')
  assert.equal(res3d.diffDays, 3)
  const expectedDayName = monday.toLocaleDateString('en-US', { weekday: 'short' })
  assert.equal(res3d.label, `3d left (${expectedDayName})`)

  // 7 calendar days away: May 22
  const task7d = { id: 't-soon-7d', status: 'open', due_date: '2026-05-22' }
  const res7d = classifyDeadline(task7d, now)
  assert.equal(res7d.timing, 'due_soon')
  assert.equal(res7d.diffDays, 7)
  assert.equal(res7d.isActiveDeadline, true)
  assert.equal(res7d.isUrgent, false)
})

test('classifyDeadline classifies deadlines more than 7 days away as upcoming', () => {
  const now = new Date(2026, 4, 15, 12, 0, 0)
  // 10 calendar days away: May 25
  const task10d = { id: 't-upcoming-10d', status: 'open', due_date: '2026-05-25' }
  const res10d = classifyDeadline(task10d, now)
  assert.equal(res10d.timing, 'upcoming')
  assert.equal(res10d.isActiveDeadline, true)
  assert.equal(res10d.isUrgent, false)
  assert.equal(res10d.isOverdue, false)
  assert.equal(res10d.type, 'future')
  assert.equal(res10d.diffDays, 10)
  assert.equal(res10d.label, '10d left')
})

test('classifyDeadline parses lifecycle statuses and priority normalization correctly', () => {
  const now = new Date(2026, 4, 15, 12, 0, 0)

  const inProgressTask = { id: 't-prog', status: 'in_progress', priority: 'HIGH' }
  const resProg = classifyDeadline(inProgressTask, now)
  assert.equal(resProg.lifecycle, 'in_progress')
  assert.equal(resProg.priority, 'high')

  const blockedTask = { id: 't-blk', status: 'blocked', priority: 'LOW' }
  const resBlocked = classifyDeadline(blockedTask, now)
  assert.equal(resBlocked.lifecycle, 'blocked')
  assert.equal(resBlocked.priority, 'low')

  const invalidPriorityTask = { id: 't-inv-prio', status: 'open', priority: 'critical' }
  const resInvalidPrio = classifyDeadline(invalidPriorityTask, now)
  assert.equal(resInvalidPrio.lifecycle, 'pending')
  assert.equal(resInvalidPrio.priority, 'medium')
})

test('filterTasksByView filters tasks accurately across views', () => {
  const now = new Date(2026, 4, 15, 12, 0, 0)
  const tomorrowMorning = new Date(2026, 4, 16, 8, 0, 0).toISOString()
  const monday = new Date(2026, 4, 18, 12, 0, 0).toISOString()

  const tasks = [
    { id: 't-overdue', status: 'open', due_date: '2026-05-10' },
    { id: 't-today', status: 'open', due_date: '2026-05-15' },
    { id: 't-urgent', status: 'open', due_date: tomorrowMorning },
    { id: 't-soon', status: 'open', due_date: monday },
    { id: 't-upcoming', status: 'open', due_date: '2026-05-30' },
    { id: 't-completed', status: 'completed', due_date: '2026-05-10' },
    { id: 't-blocked', status: 'blocked', due_date: '2026-05-20' },
    { id: 't-in-progress', status: 'in_progress', due_date: '2026-05-20' },
    { id: 't-cancelled', status: 'cancelled', due_date: '2026-05-10' },
  ]

  assert.deepEqual(filterTasksByView(null, 'all'), [])
  assert.equal(filterTasksByView(tasks, 'all', now).length, tasks.length)

  // 'overdue' view
  const overdue = filterTasksByView(tasks, 'overdue', now)
  assert.deepEqual(overdue.map(t => t.id), ['t-overdue'])

  // 'due_today' view
  const dueToday = filterTasksByView(tasks, 'due_today', now)
  assert.deepEqual(dueToday.map(t => t.id), ['t-today'])

  // 'urgent' view includes both 'urgent' and 'due_today'
  const urgent = filterTasksByView(tasks, 'urgent', now)
  assert.deepEqual(urgent.map(t => t.id), ['t-today', 't-urgent'])

  // 'due_soon' view
  const dueSoon = filterTasksByView(tasks, 'due_soon', now)
  assert.deepEqual(dueSoon.map(t => t.id), ['t-soon', 't-blocked', 't-in-progress'])

  // 'upcoming' view
  const upcoming = filterTasksByView(tasks, 'upcoming', now)
  assert.deepEqual(upcoming.map(t => t.id), ['t-upcoming'])

  // Lifecycle views
  assert.deepEqual(
    filterTasksByView(tasks, 'pending', now).map(t => t.id),
    ['t-overdue', 't-today', 't-urgent', 't-soon', 't-upcoming']
  )
  assert.deepEqual(
    filterTasksByView(tasks, 'pending_tasks', now).map(t => t.id),
    ['t-overdue', 't-today', 't-urgent', 't-soon', 't-upcoming']
  )
  assert.deepEqual(filterTasksByView(tasks, 'in_progress', now).map(t => t.id), ['t-in-progress'])
  assert.deepEqual(filterTasksByView(tasks, 'completed', now).map(t => t.id), ['t-completed'])
  assert.deepEqual(filterTasksByView(tasks, 'blocked', now).map(t => t.id), ['t-blocked'])
  assert.deepEqual(filterTasksByView(tasks, 'cancelled', now).map(t => t.id), ['t-cancelled'])
})

test('filterTasksByStatusAndDue filters tasks by combination of status and due filters', () => {
  const now = new Date(2026, 4, 15, 12, 0, 0)
  const tomorrowMorning = new Date(2026, 4, 16, 8, 0, 0).toISOString()

  const tasks = [
    { id: 't1', status: 'open', due_date: '2026-05-10' }, // pending, overdue
    { id: 't2', status: 'in_progress', due_date: '2026-05-10' }, // in_progress, overdue
    { id: 't3', status: 'open', due_date: '2026-05-15' }, // pending, due_today
    { id: 't4', status: 'in_progress', due_date: tomorrowMorning }, // in_progress, urgent
    { id: 't5', status: 'completed', due_date: '2026-05-10' }, // completed
  ]

  assert.deepEqual(filterTasksByStatusAndDue(null), [])
  assert.equal(filterTasksByStatusAndDue(tasks, 'all', 'all', now).length, 5)

  // Status = in_progress, Due = all
  const inProg = filterTasksByStatusAndDue(tasks, 'in_progress', 'all', now)
  assert.deepEqual(inProg.map(t => t.id), ['t2', 't4'])

  // Status = all, Due = overdue
  const overdueOnly = filterTasksByStatusAndDue(tasks, 'all', 'overdue', now)
  assert.deepEqual(overdueOnly.map(t => t.id), ['t1', 't2'])

  // Status = in_progress, Due = overdue
  const inProgOverdue = filterTasksByStatusAndDue(tasks, 'in_progress', 'overdue', now)
  assert.deepEqual(inProgOverdue.map(t => t.id), ['t2'])

  // Status = pending, Due = urgent (which includes due_today)
  const pendingUrgent = filterTasksByStatusAndDue(tasks, 'pending', 'urgent', now)
  assert.deepEqual(pendingUrgent.map(t => t.id), ['t3'])
})

test('calculateFilterCounts returns accurate counts across filters', () => {
  const now = new Date(2026, 4, 15, 12, 0, 0)
  const tomorrowMorning = new Date(2026, 4, 16, 8, 0, 0).toISOString()

  const tasks = [
    { id: 't1', status: 'open', due_date: '2026-05-10' }, // pending, overdue
    { id: 't2', status: 'in_progress', due_date: '2026-05-15' }, // in_progress, due_today
    { id: 't3', status: 'open', due_date: tomorrowMorning }, // pending, urgent
    { id: 't4', status: 'open', due_date: '2026-05-20' }, // pending, due_soon (5 days)
    { id: 't5', status: 'open', due_date: '2026-05-30' }, // pending, upcoming (15 days)
    { id: 't6', status: 'completed', due_date: '2026-05-10' }, // completed
  ]

  assert.deepEqual(calculateFilterCounts(null), {
    statusCounts: { all: 0, pending: 0, in_progress: 0, completed: 0 },
    dueCounts: { all: 0, overdue: 0, due_today: 0, urgent: 0, due_soon: 0, upcoming: 0 },
    baseOverdueCount: 0,
  })

  const countsAll = calculateFilterCounts(tasks, 'all', 'all', now)
  assert.equal(countsAll.baseOverdueCount, 1)
  assert.equal(countsAll.statusCounts.all, 6)
  assert.equal(countsAll.statusCounts.pending, 4)
  assert.equal(countsAll.statusCounts.in_progress, 1)
  assert.equal(countsAll.statusCounts.completed, 1)

  assert.equal(countsAll.dueCounts.all, 6)
  assert.equal(countsAll.dueCounts.overdue, 1)
  assert.equal(countsAll.dueCounts.due_today, 1)
  assert.equal(countsAll.dueCounts.urgent, 2) // due_today (t2) + urgent (t3)
  assert.equal(countsAll.dueCounts.due_soon, 1)
  assert.equal(countsAll.dueCounts.upcoming, 1)

  // When filtering by statusFilter = 'pending'
  const countsPending = calculateFilterCounts(tasks, 'pending', 'all', now)
  assert.equal(countsPending.dueCounts.all, 4)
  assert.equal(countsPending.dueCounts.overdue, 1)
  assert.equal(countsPending.dueCounts.due_today, 0)
  assert.equal(countsPending.dueCounts.urgent, 1) // t3 only
  assert.equal(countsPending.dueCounts.due_soon, 1)
  assert.equal(countsPending.dueCounts.upcoming, 1)
})

test('sortOverdueDeadlines sorts by priority first, then by most overdue first', () => {
  const now = new Date(2026, 4, 15, 12, 0, 0)

  const tasks = [
    { id: 'low-older', status: 'open', priority: 'low', due_date: '2026-05-01' },
    { id: 'urgent-newer', status: 'open', priority: 'urgent', due_date: '2026-05-14' },
    { id: 'urgent-older', status: 'open', priority: 'urgent', due_date: '2026-05-10' },
    { id: 'high-task', status: 'open', priority: 'high', due_date: '2026-05-12' },
    { id: 'completed-task', status: 'completed', priority: 'urgent', due_date: '2026-05-01' },
    { id: 'future-task', status: 'open', priority: 'urgent', due_date: '2026-05-20' },
  ]

  assert.deepEqual(sortOverdueDeadlines(null), [])

  const sorted = sortOverdueDeadlines(tasks, now)
  // Non-overdue (future) and inactive (completed) excluded
  assert.equal(sorted.length, 4)
  // urgent priority: urgent-older (lower diffHours, more overdue) before urgent-newer
  // then high priority: high-task
  // then low priority: low-older
  assert.deepEqual(sorted.map(t => t.id), ['urgent-older', 'urgent-newer', 'high-task', 'low-older'])
})

test('sortUpcomingDeadlines sorts active upcoming deadlines nearest future first', () => {
  const now = new Date(2026, 4, 15, 12, 0, 0)
  const tomorrowMorning = new Date(2026, 4, 16, 8, 0, 0).toISOString()

  const tasks = [
    { id: 'far-future', status: 'open', due_date: '2026-05-30' },
    { id: 'due-today-task', status: 'open', due_date: '2026-05-15' },
    { id: 'urgent-tomorrow', status: 'open', due_date: tomorrowMorning },
    { id: 'soon-task', status: 'open', due_date: '2026-05-18' },
    { id: 'overdue-task', status: 'open', due_date: '2026-05-10' },
    { id: 'completed-today', status: 'completed', due_date: '2026-05-15' },
    { id: 'cancelled-tomorrow', status: 'cancelled', due_date: tomorrowMorning },
  ]

  assert.deepEqual(sortUpcomingDeadlines(null), [])

  const sorted = sortUpcomingDeadlines(tasks, now)
  // Overdue, completed, and cancelled must be excluded
  assert.equal(sorted.length, 4)
  // Order: nearest future first (diffHours ascending)
  assert.deepEqual(sorted.map(t => t.id), ['due-today-task', 'urgent-tomorrow', 'soon-task', 'far-future'])
})
