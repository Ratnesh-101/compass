// Change detection for polled task lists. Compares every user-visible field so
// status, domain, priority, notes, deadline and completion changes reach the UI.

export const TASK_DIFF_FIELDS = [
  'id',
  'title',
  'countdown',
  'status',
  'domain',
  'priority',
  'notes',
  'description',
  'duration_minutes',
  'project',
  'scheduled_start',
  'scheduled_end',
  'due_date',
  'deadline',
  'completed',
  'completed_at',
  'is_demo',
  'tags',
]

function isSameTaskValue(a, b) {
  if (a === b) return true
  if (a == null && b == null) return true
  if (typeof a === 'object' && typeof b === 'object' && a !== null && b !== null) {
    return JSON.stringify(a) === JSON.stringify(b)
  }
  return false
}

export function haveTasksChanged(currentTasks, nextTasks) {
  if (currentTasks.length !== nextTasks.length) return true
  return nextTasks.some((task, i) => {
    const cur = currentTasks[i]
    return !cur || TASK_DIFF_FIELDS.some((field) => !isSameTaskValue(cur[field], task[field]))
  })
}
