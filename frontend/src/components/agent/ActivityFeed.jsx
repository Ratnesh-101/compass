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

export default function ActivityFeed({
  activityList = [],
  onRefresh,
  onRevertItem,
}) {
  return (
    <div id="agent-activity-feed" style={{
      marginTop: '24px',
      borderTop: '1px solid var(--border)',
      paddingTop: '16px',
    }}>
      <div style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        marginBottom: '10px',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <span style={{
            fontSize: '13px',
            fontWeight: '700',
            color: 'var(--text-primary)',
          }}>
            📋 Recent changes{activityList.length > 0 ? ` (${activityList.length})` : ''}
          </span>
        </div>
        <button
          onClick={onRefresh}
          style={{
            fontSize: '11px',
            background: 'transparent',
            border: 'none',
            color: 'var(--primary)',
            cursor: 'pointer',
          }}
        >
          ↻ Refresh
        </button>
      </div>

      {activityList.length === 0 ? (
        <div style={{ fontSize: '12px', color: 'var(--text-muted)', fontStyle: 'italic', padding: '8px 0' }}>
          No changes made by the assistant yet.
        </div>
      ) : (
        <div style={{
          display: 'flex',
          flexDirection: 'column',
          gap: '6px',
          maxHeight: '260px',
          overflowY: 'auto',
          overscrollBehavior: 'contain',
          paddingRight: '2px',
        }}>
          {activityList.map((item) => (
            <div
              key={item.id}
              className="agent-activity-item"
              style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                padding: '9px 12px',
                background: item.is_reverted ? 'var(--bg-card)' : 'var(--bg-card-soft)',
                border: `1px solid var(--border)`,
                borderRadius: '8px',
                fontSize: '12px',
                opacity: item.is_reverted ? 0.55 : 1,
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: '10px', flexWrap: 'wrap' }}>
                <span style={{ fontSize: '14px' }}>
                  {item.tool === 'add_task' ? '➕' : item.tool === 'delete_task' ? '🗑️' : item.tool?.includes('ingest') ? '📥' : '✏️'}
                </span>
                <span style={{ color: 'var(--text-primary)', fontWeight: '600', fontSize: '12.5px' }}>
                  {formatActivityItem(item)}
                </span>
                <span style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
                  {formatFriendlyTime(item.created_at)}
                </span>
                {item.is_reverted && (
                  <span style={{
                    fontSize: '10px',
                    padding: '1px 7px',
                    borderRadius: '10px',
                    fontWeight: '700',
                    background: 'rgba(239, 68, 68, 0.1)',
                    color: '#dc2626',
                    border: '1px solid rgba(239, 68, 68, 0.25)',
                  }}>
                    Undone
                  </span>
                )}
              </div>

              {!item.is_reverted && (
                <button
                  className="agent-revert-btn"
                  onClick={() => onRevertItem(item.id)}
                  style={{
                    padding: '4px 10px',
                    background: 'var(--bg-card)',
                    border: '1px solid var(--border)',
                    borderRadius: '6px',
                    color: 'var(--text-secondary)',
                    fontSize: '11px',
                    fontWeight: '600',
                    cursor: 'pointer',
                    whiteSpace: 'nowrap',
                    flexShrink: 0,
                  }}
                >
                  ↩️ Undo
                </button>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
