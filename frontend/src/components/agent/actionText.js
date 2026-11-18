// Pure text helpers for the Planner approval card and trace (no JSX, importable from node tests).

export function friendlyAction(tool) {
  const map = {
    add_task: 'Create Task',
    edit_task: 'Update Task',
    delete_task: 'Delete Task',
    update_task_status: 'Update Task Status',
    ingest_url: 'Index Web Resource',
    ingest_text: 'Store Context Memory',
    apply_triage_plan: 'Execute Schedule Adjustment',
    schedule_event: 'Book Calendar Slot',
    commit_schedule: 'Commit Batch Schedule',
  }
  return map[tool] || (tool || '').replace(/_/g, ' ')
}

// " due Fri 2026-11-20" for an ISO date or datetime; empty when no date.
export function formatDue(raw) {
  if (!raw || typeof raw !== 'string') return ''
  const m = raw.match(/^(\d{4})-(\d{2})-(\d{2})/)
  if (!m) return ` due ${raw}`
  const d = new Date(Date.UTC(+m[1], +m[2] - 1, +m[3]))
  const weekday = Number.isNaN(d.getTime())
    ? ''
    : `${['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'][d.getUTCDay()]} `
  return ` due ${weekday}${m[0]}`
}

export function formatActionDescription(action) {
  if (!action) return 'Update data'
  if (action.summary) return action.summary
  const tool = action.tool
  const args = action.args || {}
  if (tool === 'add_task') {
    return `Create task: "${args.title || 'New Task'}" (${args.domain || 'general'})${formatDue(args.due_date)}`
  }
  if (tool === 'edit_task') {
    return `Update task: "${args.title || `Task #${args.task_id || ''}`}"${formatDue(args.due_date)}`
  }
  if (tool === 'delete_task') {
    return `Permanently remove task #${args.task_id || ''}`
  }
  if (tool === 'update_task_status') {
    const status = args.status || 'done'
    return `Mark task #${args.task_id || ''} as ${status === 'done' ? 'completed' : status}`
  }
  if (tool === 'schedule_event' || tool === 'commit_schedule') {
    return `Reserve calendar time slot for "${args.title || 'event'}"`
  }
  if (tool === 'apply_triage_plan') {
    return 'Rebalance task deadlines to prevent cognitive burnout'
  }
  return friendlyAction(tool)
}
