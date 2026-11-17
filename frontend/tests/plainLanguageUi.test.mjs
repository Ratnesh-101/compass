import test from 'node:test'
import assert from 'node:assert/strict'

// ---------------------------------------------------------------------------
// 1. Human Date Formatting (TaskCard N-027)
// ---------------------------------------------------------------------------
function formatHumanDate(ts) {
  if (!ts) return null
  try {
    const d = new Date(ts)
    if (isNaN(d.getTime())) return String(ts)
    const now = new Date()
    const isToday = d.toDateString() === now.toDateString()
    const yesterday = new Date(now)
    yesterday.setDate(yesterday.getDate() - 1)
    const isYesterday = d.toDateString() === yesterday.toDateString()

    const timeStr = d.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' }).toLowerCase()
    if (isToday) {
      return `Added today, ${timeStr}`
    }
    if (isYesterday) {
      return `Added yesterday, ${timeStr}`
    }
    const dateStr = d.toLocaleDateString([], { month: 'short', day: 'numeric' })
    return `Added ${dateStr}, ${timeStr}`
  } catch {
    return String(ts)
  }
}

test('formatHumanDate handles today, yesterday, and past dates', () => {
  const now = new Date()
  const todayResult = formatHumanDate(now.toISOString())
  assert.ok(todayResult.startsWith('Added today,'), `Expected "Added today...", got "${todayResult}"`)

  const yesterday = new Date(now)
  yesterday.setDate(yesterday.getDate() - 1)
  const yesterdayResult = formatHumanDate(yesterday.toISOString())
  assert.ok(yesterdayResult.startsWith('Added yesterday,'), `Expected "Added yesterday...", got "${yesterdayResult}"`)

  const pastDate = new Date('2025-01-15T14:30:00Z')
  const pastResult = formatHumanDate(pastDate.toISOString())
  assert.ok(pastResult.includes('Jan 15'), `Expected past date to include Jan 15, got "${pastResult}"`)
})

test('formatHumanDate handles null, empty string, and malformed input gracefully', () => {
  assert.equal(formatHumanDate(null), null)
  assert.equal(formatHumanDate(''), null)
  assert.equal(formatHumanDate('invalid-date-string'), 'invalid-date-string')
})

// ---------------------------------------------------------------------------
// 2. Pluralization logic (Sidebar N-033)
// ---------------------------------------------------------------------------
function formatTaskCount(count) {
  return `${count} ${count === 1 ? 'task' : 'tasks'} synced`
}

test('formatTaskCount pluralizes accurately', () => {
  assert.equal(formatTaskCount(0), '0 tasks synced')
  assert.equal(formatTaskCount(1), '1 task synced')
  assert.equal(formatTaskCount(2), '2 tasks synced')
  assert.equal(formatTaskCount(21), '21 tasks synced')
})

// ---------------------------------------------------------------------------
// 3. Completed Today Metric (Dashboard N-029)
// ---------------------------------------------------------------------------
function calculateCompletedToday(tasks, completedInSession = new Set()) {
  const now = new Date()
  const todayStr = now.toDateString()
  const todayShort = now.toLocaleDateString('en-US', { month: 'short', day: 'numeric' }).toLowerCase()
  const todayIsoDate = now.toISOString().slice(0, 10)

  let completedCount = 0
  let completedTodayCount = 0

  tasks.forEach((t) => {
    const s = (t.status || '').toLowerCase()
    const c = (t.countdown || '').toLowerCase()
    const isCompleted = s === 'completed' || s === 'done' || c === 'completed'

    if (isCompleted) {
      completedCount++
      let isToday = false
      const candidateDate = t.completed_at || t.updated_at || t.timestamp
      if (candidateDate) {
        const d = new Date(candidateDate)
        if (!isNaN(d.getTime()) && d.toDateString() === todayStr) {
          isToday = true
        }
        const ts = String(candidateDate).toLowerCase()
        if (
          ts.includes('just now') ||
          ts.includes('min') ||
          ts.includes('hour') ||
          ts.includes('today') ||
          ts.includes(todayShort) ||
          ts.startsWith(todayIsoDate)
        ) {
          isToday = true
        }
      }
      if (completedInSession.has(t.id)) {
        isToday = true
      }
      if (isToday) {
        completedTodayCount++
      }
    }
  })

  // Safeguard: completedTodayCount cannot exceed total completedCount
  completedTodayCount = Math.min(completedTodayCount, completedCount)

  const completionRate = tasks.length > 0 ? Math.round((completedCount / tasks.length) * 100) : 0

  return {
    total: tasks.length,
    completedCount,
    completedTodayCount,
    completionRate,
  }
}

test('calculateCompletedToday agrees with completedCount and local day', () => {
  const today = new Date().toISOString()
  const sampleTasks = [
    { id: '1', title: 'Task 1', status: 'completed', timestamp: today },
    { id: '2', title: 'Task 2', status: 'completed', timestamp: '2025-01-01T00:00:00Z' },
    { id: '3', title: 'Task 3', status: 'open', timestamp: today },
  ]

  const metrics = calculateCompletedToday(sampleTasks)
  assert.equal(metrics.total, 3)
  assert.equal(metrics.completedCount, 2)
  assert.equal(metrics.completedTodayCount, 1)
  assert.equal(metrics.completionRate, 67)
})

test('calculateCompletedToday respects session checkoffs', () => {
  const sampleTasks = [
    { id: '10', title: 'Old Task', status: 'completed', timestamp: '2024-05-01T00:00:00Z' },
  ]
  const sessionCheckoffs = new Set(['10'])
  const metrics = calculateCompletedToday(sampleTasks, sessionCheckoffs)
  assert.equal(metrics.completedTodayCount, 1)
  assert.equal(metrics.completedCount, 1)
})

// ---------------------------------------------------------------------------
// 4. Working hours validation (CalendarView N-028)
// ---------------------------------------------------------------------------
function validateWorkingHours(start, end) {
  if (!start || !end) return { valid: false, reason: 'Start and end time required' }
  const [sh, sm] = start.split(':').map(Number)
  const [eh, em] = end.split(':').map(Number)
  if (isNaN(sh) || isNaN(sm) || isNaN(eh) || isNaN(em)) return { valid: false, reason: 'Invalid time format' }
  const startMin = sh * 60 + sm
  const endMin = eh * 60 + em
  if (endMin <= startMin) return { valid: false, reason: 'End time must be after start time' }
  return { valid: true, startMin, endMin }
}

test('validateWorkingHours accepts standard study windows', () => {
  assert.equal(validateWorkingHours('09:00', '18:00').valid, true)
  assert.equal(validateWorkingHours('08:30', '17:00').valid, true)
  assert.equal(validateWorkingHours('18:00', '09:00').valid, false)
})
