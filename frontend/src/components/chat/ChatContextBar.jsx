import React from 'react'

export default function ChatContextBar({
  overdueCount = 0,
  taskCount = 0,
  isOnline = false,
  backendStatus = '',
}) {
  return (
    <div style={{
      display: 'flex', gap: '10px', padding: '12px 24px', borderBottom: '1px solid var(--border)',
      background: 'var(--bg-card)', flexShrink: 0, flexWrap: 'wrap'
    }}>
      <div style={{
        display: 'flex', alignItems: 'center', gap: '10px', padding: '8px 12px', borderRadius: '10px',
        background: overdueCount > 0 ? 'var(--danger-bg)' : 'var(--code-bg)', minWidth: '170px'
      }}>
        <span style={{ fontSize: '16px' }}>{overdueCount > 0 ? '⚠️' : '✅'}</span>
        <div>
          <div style={{ fontSize: '12px', fontWeight: '700', color: overdueCount > 0 ? '#b23b3b' : 'var(--code-text)' }}>
            {overdueCount > 0 ? `${overdueCount} overdue` : 'On schedule'}
          </div>
          <div style={{ fontSize: '10.5px', color: 'var(--text-muted)' }}>Across all domains</div>
        </div>
      </div>

      <div style={{
        display: 'flex', alignItems: 'center', gap: '10px', padding: '8px 12px', borderRadius: '10px',
        background: 'var(--coursework-bg)', minWidth: '170px'
      }}>
        <span style={{ fontSize: '16px' }}>📋</span>
        <div>
          <div style={{ fontSize: '12px', fontWeight: '700', color: 'var(--coursework-text)' }}>
            {taskCount} task{taskCount === 1 ? '' : 's'} tracked
          </div>
          <div style={{ fontSize: '10.5px', color: 'var(--text-muted)' }}>Live in Neon</div>
        </div>
      </div>

      <div style={{
        display: 'flex', alignItems: 'center', gap: '10px', padding: '8px 12px', borderRadius: '10px',
        background: isOnline ? 'var(--code-bg)' : 'var(--hackathon-bg)', minWidth: '170px'
      }}>
        <span style={{ fontSize: '16px' }}>{isOnline ? '🟢' : '🟡'}</span>
        <div>
          <div style={{ fontSize: '12px', fontWeight: '700', color: isOnline ? 'var(--code-text)' : 'var(--hackathon-text)' }}>
            {isOnline ? 'Backend live' : 'Backend offline'}
          </div>
          <div style={{ fontSize: '10.5px', color: 'var(--text-muted)' }}>{backendStatus}</div>
        </div>
      </div>
    </div>
  )
}
