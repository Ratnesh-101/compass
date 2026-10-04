import React from 'react'

function formatFriendlyTime(dateStr) {
  if (!dateStr) return ''
  try {
    const d = new Date(dateStr)
    if (isNaN(d.getTime())) return dateStr.slice(11, 16)
    return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
  } catch {
    return dateStr.slice(11, 16)
  }
}

export default function RunHistoryDrawer({
  isOpen,
  onClose,
  runsList = [],
  currentRunId,
  onLoadPastRun,
}) {
  if (!isOpen) return null

  return (
    <div style={{
      marginBottom: '16px',
      background: 'var(--bg-card)',
      border: '1px solid var(--border)',
      borderRadius: '8px',
      padding: '14px',
      boxShadow: 'var(--shadow-md)',
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '10px' }}>
        <span style={{ fontSize: '13px', fontWeight: '700', color: 'var(--text-primary)', letterSpacing: '0.02em' }}>
          📜 Past Plans & Answers ({runsList.length})
        </span>
        <button
          onClick={onClose}
          style={{ background: 'transparent', border: 'none', color: 'var(--text-secondary)', cursor: 'pointer', fontSize: '15px' }}
        >
          ✕
        </button>
      </div>
      {runsList.length === 0 ? (
        <div style={{ fontSize: '12px', color: 'var(--text-muted)', fontStyle: 'italic', padding: '12px 0', textAlign: 'center' }}>
          No past plans yet. Ask a question or run a plan above to see history here.
        </div>
      ) : (
        <div style={{
          display: 'flex',
          flexDirection: 'column',
          gap: '6px',
          maxHeight: '220px',
          overflowY: 'auto',
          overscrollBehavior: 'contain',
        }}>
          {runsList.map(r => (
            <div
              key={r.id}
              onClick={() => onLoadPastRun(r)}
              style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                padding: '9px 12px',
                background: currentRunId === r.id ? 'rgba(99, 102, 241, 0.08)' : 'var(--bg-card-soft)',
                border: `1px solid ${currentRunId === r.id ? 'var(--primary)' : 'var(--border)'}`,
                borderRadius: '6px',
                cursor: 'pointer',
                transition: 'all 0.15s',
              }}
            >
              <div style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: '70%' }}>
                <span style={{ fontSize: '13px', color: 'var(--text-primary)', fontWeight: '500' }}>{r.goal || 'Question'}</span>
                <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginTop: '2px' }}>
                  {formatFriendlyTime(r.created_at)}
                </div>
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <span style={{ fontSize: '11px', color: 'var(--text-secondary)' }}>{r.steps_count} steps</span>
                <span style={{
                  fontSize: '11px',
                  fontWeight: '600',
                  padding: '2px 8px',
                  borderRadius: '10px',
                  background: r.status === 'completed' ? 'rgba(16, 185, 129, 0.15)' : r.status === 'paused' ? 'rgba(245, 158, 11, 0.15)' : 'rgba(100, 116, 139, 0.15)',
                  color: r.status === 'completed' ? '#059669' : r.status === 'paused' ? '#b45309' : 'var(--text-muted)',
                }}>
                  {r.status === 'completed' ? 'Completed' : r.status === 'paused' ? 'Needs approval' : 'In progress'}
                </span>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
