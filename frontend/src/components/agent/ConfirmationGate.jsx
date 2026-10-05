import React from 'react'
import {
  CheckCircle2,
  XCircle,
  AlertTriangle,
  FileEdit,
  ShieldAlert,
  Calendar,
  Trash2,
  PlusCircle,
  Undo2,
} from 'lucide-react'

function friendlyAction(tool) {
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

export function formatActionDescription(action) {
  if (!action) return 'Update data'
  if (action.summary) return action.summary
  const tool = action.tool
  const args = action.args || {}
  if (tool === 'add_task') {
    return `Create task: "${args.title || 'New Task'}" (${args.domain || 'general'})`
  }
  if (tool === 'edit_task') {
    return `Update task: "${args.title || `Task #${args.task_id || ''}`}"`
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

function getActionIcon(tool) {
  if (tool === 'add_task') return PlusCircle
  if (tool === 'delete_task') return Trash2
  if (tool === 'schedule_event' || tool === 'commit_schedule') return Calendar
  return FileEdit
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
    <div
      style={{
        background: 'var(--bg-card)',
        border: '1.5px solid #818cf8',
        borderRadius: '12px',
        padding: '20px',
        marginTop: '12px',
        marginBottom: '16px',
        boxShadow: '0 4px 20px rgba(99, 102, 241, 0.12)',
      }}
    >
      {/* Header with Safety Shield */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '8px' }}>
        <div
          style={{
            width: '32px',
            height: '32px',
            borderRadius: '8px',
            background: 'rgba(99, 102, 241, 0.12)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            color: '#6366f1',
          }}
        >
          <ShieldAlert size={18} />
        </div>
        <div>
          <div style={{ fontSize: '15px', fontWeight: '800', color: '#0f172a', letterSpacing: '-0.3px' }}>
            Action Confirmation Gate — {pendingActions.length} Pending Action{pendingActions.length !== 1 ? 's' : ''}
          </div>
          <div style={{ fontSize: '12.5px', color: '#64748b' }}>
            Zero-mutation safety protocol: AI proposed changes require your explicit authorization.
          </div>
        </div>
      </div>

      {/* Action List */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', margin: '14px 0' }}>
        {pendingActions.map((action, i) => {
          const ActionIcon = getActionIcon(action.tool)
          const isDestructive = action.tool === 'delete_task'
          return (
            <div
              key={i}
              style={{
                background: isDestructive ? '#fef2f2' : '#f8fafc',
                border: `1px solid ${isDestructive ? '#fecaca' : '#e2e8f0'}`,
                borderRadius: '8px',
                padding: '10px 14px',
                display: 'flex',
                alignItems: 'center',
                gap: '12px',
              }}
            >
              <ActionIcon size={16} color={isDestructive ? '#ef4444' : '#6366f1'} />
              <div style={{ flex: 1, fontSize: '13px', color: isDestructive ? '#991b1b' : '#0f172a', fontWeight: '500' }}>
                {formatActionDescription(action)}
              </div>
              <span
                style={{
                  fontSize: '11px',
                  fontWeight: '700',
                  padding: '2px 8px',
                  borderRadius: '4px',
                  background: isDestructive ? 'rgba(239, 68, 68, 0.1)' : 'rgba(99, 102, 241, 0.1)',
                  color: isDestructive ? '#dc2626' : '#4f46e5',
                  textTransform: 'uppercase',
                  letterSpacing: '0.04em',
                }}
              >
                {friendlyAction(action.tool)}
              </span>
            </div>
          )
        })}
      </div>

      {/* Rejection / Modification Guidance Input */}
      <div style={{ marginBottom: '14px' }}>
        <input
          id="agent-reject-input"
          type="text"
          value={rejectFeedback}
          onChange={e => setRejectFeedback(e.target.value)}
          placeholder="Optional revision guidance (e.g. 'Keep current due date, just reduce duration')..."
          style={{
            width: '100%',
            padding: '10px 14px',
            background: 'var(--bg-card-soft)',
            border: '1px solid var(--border)',
            borderRadius: '8px',
            color: 'var(--text-primary)',
            fontSize: '13px',
            outline: 'none',
            boxSizing: 'border-box',
          }}
          onFocus={e => (e.target.style.borderColor = '#6366f1')}
          onBlur={e => (e.target.style.borderColor = '#cbd5e1')}
        />
      </div>

      {/* Executive Decision Buttons */}
      <div style={{ display: 'flex', gap: '10px' }}>
        <button
          id="agent-approve-btn"
          onClick={onApprove}
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '7px',
            padding: '9px 20px',
            background: 'linear-gradient(135deg, #16a34a 0%, #15803d 100%)',
            border: 'none',
            borderRadius: '8px',
            color: '#ffffff',
            fontSize: '13.5px',
            fontWeight: '700',
            cursor: 'pointer',
            boxShadow: '0 2px 8px rgba(22, 163, 74, 0.3)',
            transition: 'all 0.15s ease',
          }}
          onMouseEnter={e => (e.currentTarget.style.transform = 'translateY(-1px)')}
          onMouseLeave={e => (e.currentTarget.style.transform = 'translateY(0)')}
        >
          <CheckCircle2 size={16} />
          <span>Authorize Changes</span>
        </button>

        <button
          id="agent-reject-btn"
          onClick={onReject}
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '7px',
            padding: '9px 18px',
            background: 'var(--bg-card)',
            border: '1px solid #ef4444',
            borderRadius: '8px',
            color: '#dc2626',
            fontSize: '13.5px',
            fontWeight: '600',
            cursor: 'pointer',
            transition: 'all 0.15s ease',
          }}
          onMouseEnter={e => (e.currentTarget.style.background = 'rgba(239, 68, 68, 0.12)')}
          onMouseLeave={e => (e.currentTarget.style.background = 'var(--bg-card)')}
        >
          <XCircle size={16} />
          <span>Reject / Re-plan</span>
        </button>
      </div>
    </div>
  )
}
