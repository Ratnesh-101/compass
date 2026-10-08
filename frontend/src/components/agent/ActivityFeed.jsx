import React from 'react'
import {
  RotateCcw,
  CheckCircle2,
  History,
  Plus,
  Trash2,
  Edit3,
  FileText,
  Calendar,
  Sparkles,
  RefreshCw,
} from 'lucide-react'

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

export function formatFriendlyTime(dateStr) {
  if (!dateStr) return ''
  try {
    const d = new Date(dateStr)
    if (isNaN(d.getTime())) return dateStr.slice(11, 16)
    return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
  } catch {
    return dateStr.slice(11, 16)
  }
}

function formatActivityItem(item) {
  try {
    const args = typeof item.args === 'string' ? JSON.parse(item.args) : (item.args || {})
    const newState = typeof item.new_state === 'string' ? JSON.parse(item.new_state) : (item.new_state || {})
    const prevState = typeof item.previous_state === 'string' ? JSON.parse(item.previous_state) : (item.previous_state || {})

    const title = args.title || newState.title || prevState.title || ''

    if (item.tool === 'add_task') {
      return title ? `Added task "${title}"` : 'Added a new task'
    }
    if (item.tool === 'delete_task') {
      return title ? `Removed task "${title}"` : 'Removed a task'
    }
    if (item.tool === 'edit_task') {
      return title ? `Updated task "${title}"` : 'Updated a task'
    }
    if (item.tool === 'update_task_status') {
      const status = args.status || newState.status || 'updated'
      const statusLabel = status === 'done' ? 'completed' : status
      return title ? `Marked "${title}" as ${statusLabel}` : `Marked task as ${statusLabel}`
    }
    if (item.tool === 'ingest_url') {
      const url = args.url || ''
      const host = url ? url.replace(/^https?:\/\/(www\.)?/, '').split('/')[0] : ''
      return host ? `Saved link from ${host}` : 'Saved web page'
    }
    if (item.tool === 'ingest_text') {
      return title ? `Saved note: "${title}"` : 'Saved note to memory'
    }
    if (item.tool === 'commit_schedule' || item.tool === 'schedule_event') {
      return title ? `Scheduled "${title}"` : 'Scheduled calendar event'
    }
    if (item.tool === 'apply_triage_plan') {
      return 'Adjusted task plan & schedule'
    }
  } catch {
    // fallback
  }
  return friendlyAction(item.tool)
}

function getActivityIcon(tool) {
  if (tool === 'add_task') return Plus
  if (tool === 'delete_task') return Trash2
  if (tool === 'edit_task' || tool === 'update_task_status') return Edit3
  if (tool === 'commit_schedule' || tool === 'schedule_event') return Calendar
  return FileText
}

export default function ActivityFeed({
  activityList = [],
  onRefresh,
  onRevertItem,
}) {
  return (
    <div
      id="agent-activity-feed"
      style={{
        marginTop: '24px',
        borderTop: '1px solid #e2e8f0',
        paddingTop: '18px',
      }}
    >
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          marginBottom: '12px',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <History size={16} color="#6366f1" />
          <span
            style={{
              fontSize: '13.5px',
              fontWeight: '700',
              color: '#0f172a',
            }}
          >
            Audit Log & Mutation History{activityList.length > 0 ? ` (${activityList.length})` : ''}
          </span>
        </div>
        <button
          onClick={onRefresh}
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '5px',
            fontSize: '12px',
            fontWeight: '600',
            background: 'var(--bg-card)',
            border: '1px solid var(--border)',
            borderRadius: '6px',
            padding: '4px 10px',
            color: 'var(--text-secondary)',
            cursor: 'pointer',
          }}
          onMouseEnter={e => (e.currentTarget.style.background = 'var(--bg-card-soft)')}
          onMouseLeave={e => (e.currentTarget.style.background = 'var(--bg-card)')}
        >
          <RefreshCw size={12} />
          <span>Refresh</span>
        </button>
      </div>

      {activityList.length === 0 ? (
        <div
          style={{
            fontSize: '12.5px',
            color: '#94a3b8',
            fontStyle: 'italic',
            padding: '12px 0',
            textAlign: 'center',
            background: 'var(--bg-card-soft)',
            borderRadius: '8px',
            border: '1px dashed var(--border)',
          }}
        >
          No automated state changes made by the assistant yet.
        </div>
      ) : (
        <div
          style={{
            display: 'flex',
            flexDirection: 'column',
            gap: '8px',
            maxHeight: '280px',
            overflowY: 'auto',
            overscrollBehavior: 'contain',
            paddingRight: '2px',
          }}
        >
          {activityList.map((item) => {
            const Icon = getActivityIcon(item.tool)
            return (
              <div
                key={item.id}
                className="agent-activity-item"
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  padding: '10px 14px',
                  background: item.is_reverted ? 'var(--bg-card-soft)' : 'var(--bg-card)',
                  border: `1px solid ${item.is_reverted ? 'var(--border-soft, var(--border))' : 'var(--border)'}`,
                  borderRadius: '10px',
                  fontSize: '12.5px',
                  opacity: item.is_reverted ? 0.6 : 1,
                  boxShadow: item.is_reverted ? 'none' : '0 1px 2px rgba(0,0,0,0.03)',
                  transition: 'all 0.15s ease',
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: '10px', flexWrap: 'wrap' }}>
                  <div
                    style={{
                      width: '26px',
                      height: '26px',
                      borderRadius: '6px',
                      background: item.is_reverted ? '#f1f5f9' : 'rgba(99, 102, 241, 0.1)',
                      color: item.is_reverted ? '#94a3b8' : '#6366f1',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      flexShrink: 0,
                    }}
                  >
                    <Icon size={14} />
                  </div>
                  <span style={{ color: 'var(--text-primary)', fontWeight: '600' }}>
                    {formatActivityItem(item)}
                  </span>
                  <span style={{ fontSize: '11px', color: '#94a3b8' }}>
                    {formatFriendlyTime(item.created_at)}
                  </span>
                  {item.is_reverted && (
                    <span
                      style={{
                        fontSize: '10.5px',
                        padding: '1px 8px',
                        borderRadius: '10px',
                        fontWeight: '700',
                        background: 'rgba(239, 68, 68, 0.1)',
                        color: '#dc2626',
                        border: '1px solid rgba(239, 68, 68, 0.25)',
                      }}
                    >
                      Reverted
                    </span>
                  )}
                </div>

                {!item.is_reverted && (
                  <button
                    className="agent-revert-btn"
                    onClick={() => onRevertItem(item.id)}
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: '5px',
                      padding: '5px 12px',
                      background: 'var(--bg-card)',
                      border: '1px solid var(--border)',
                      borderRadius: '6px',
                      color: 'var(--text-secondary)',
                      fontSize: '11.5px',
                      fontWeight: '600',
                      cursor: 'pointer',
                      whiteSpace: 'nowrap',
                      flexShrink: 0,
                      transition: 'all 0.15s ease',
                    }}
                    onMouseEnter={e => {
                      e.currentTarget.style.borderColor = '#ef4444'
                      e.currentTarget.style.color = '#ef4444'
                      e.currentTarget.style.background = 'rgba(239, 68, 68, 0.1)'
                    }}
                    onMouseLeave={e => {
                      e.currentTarget.style.borderColor = 'var(--border)'
                      e.currentTarget.style.color = 'var(--text-secondary)'
                      e.currentTarget.style.background = 'var(--bg-card)'
                    }}
                  >
                    <RotateCcw size={12} />
                    <span>Undo</span>
                  </button>
                )}
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
