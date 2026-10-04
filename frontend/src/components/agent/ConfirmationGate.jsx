import React from 'react'

function friendlyAction(tool) {
  const map = {
    add_task: 'Added a task',
    edit_task: 'Updated a task',
    delete_task: 'Deleted a task',
    update_task_status: 'Changed task status',
    ingest_url: 'Saved web page',
    ingest_text: 'Saved note',
    apply_triage_plan: 'Adjusted schedule',
    schedule_event: 'Scheduled event',
    commit_schedule: 'Scheduled tasks',
  }
  return map[tool] || (tool || '').replace(/_/g, ' ')
}

export function formatActionDescription(action) {
  if (!action) return 'Update data'
  if (action.summary) return action.summary
  const tool = action.tool
  const args = action.args || {}
  if (tool === 'add_task') {
    return `Add task: "${args.title || 'New Task'}"`
  }
  if (tool === 'edit_task') {
    return `Update task: "${args.title || `Task #${args.task_id || ''}`}"`
  }
  if (tool === 'delete_task') {
    return `Delete task #${args.task_id || ''}`
  }
  if (tool === 'update_task_status') {
    const status = args.status || 'done'
    return `Mark task #${args.task_id || ''} as ${status === 'done' ? 'completed' : status}`
  }
  if (tool === 'schedule_event' || tool === 'commit_schedule') {
    return `Schedule "${args.title || 'event'}" on calendar`
  }
  if (tool === 'apply_triage_plan') {
    return 'Adjust task plan to balance workload'
  }
  return friendlyAction(tool)
}

export default function ConfirmationGate({
  pendingActions,
  rejectFeedback,
  setRejectFeedback,
  onApprove,
  onReject,
}) {
  if (!pendingActions || pendingActions.length === 0) return null

  return (
    <div style={{
      background: 'rgba(99, 102, 241, 0.05)',
      border: '1px solid rgba(99, 102, 241, 0.25)',
      borderRadius: '10px',
      padding: '16px',
      marginTop: '8px',
    }}>
      <div style={{ fontSize: '15px', fontWeight: '700', color: 'var(--text-primary)', marginBottom: '6px' }}>
        🙋 Ready to make {pendingActions.length} change{pendingActions.length !== 1 ? 's' : ''} — is that ok?
      </div>
      <div style={{ fontSize: '13px', color: 'var(--text-secondary)', marginBottom: '14px' }}>
        Nothing has been saved yet. Review below, then say yes or no. You can always undo changes.
      </div>
      {pendingActions.map((action, i) => (
        <div key={i} style={{
          background: 'var(--bg-card)',
          borderRadius: '8px',
          padding: '10px 14px',
          marginBottom: '6px',
          fontSize: '13px',
          color: 'var(--text-primary)',
          display: 'flex',
          alignItems: 'center',
          gap: '10px',
          border: '1px solid var(--border)',
        }}>
          <span style={{ fontSize: '16px' }}>📝</span>
          <span style={{ fontWeight: '500' }}>{formatActionDescription(action)}</span>
        </div>
      ))}
      <div style={{ marginTop: '12px' }}>
        <input
          id="agent-reject-input"
          type="text"
          value={rejectFeedback}
          onChange={e => setRejectFeedback(e.target.value)}
          placeholder="Optional: tell me what NOT to change (e.g. 'don't touch my exam date')…"
          style={{
            width: '100%',
            padding: '9px 12px',
            background: 'var(--bg-card)',
            border: '1px solid var(--border)',
            borderRadius: '8px',
            color: 'var(--text-primary)',
            fontSize: '13px',
            marginBottom: '10px',
            outline: 'none',
            boxSizing: 'border-box',
            fontFamily: 'Inter, system-ui, sans-serif',
          }}
        />
      </div>
      <div style={{ display: 'flex', gap: '8px', marginTop: '4px' }}>
        <button
          id="agent-approve-btn"
          onClick={onApprove}
          style={{
            padding: '9px 20px',
            background: '#16a34a',
            border: 'none',
            borderRadius: '8px',
            color: '#fff',
            fontSize: '14px',
            fontWeight: '600',
            cursor: 'pointer',
          }}
        >
          ✅ Yes, go ahead
        </button>
        <button
          id="agent-reject-btn"
          onClick={onReject}
          style={{
            padding: '9px 20px',
            background: 'transparent',
            border: '1px solid #ef4444',
            borderRadius: '8px',
            color: '#dc2626',
            fontSize: '14px',
            fontWeight: '600',
            cursor: 'pointer',
          }}
        >
          ❌ No, try a different way
        </button>
      </div>
    </div>
  )
}
