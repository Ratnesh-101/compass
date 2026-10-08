import React from 'react'
import { getDomainMeta } from './domainMeta'

export default function TaskCard({
  task,
  onSelectTask,
  onDeleteTask,
  onToggleStatus,
}) {
  const isOverdue = (task.countdown || '').toLowerCase().includes('overdue')
  const isCompleted = task.status === 'completed' || task.status === 'done'
  const meta = getDomainMeta(task.domain)

  return (
    <div
      className={`timeline-card card-${task.domain}`}
      onClick={() => onSelectTask(task)}
      role="button"
      tabIndex={0}
      style={{
        opacity: isCompleted ? 0.75 : 1,
        transition: 'all 0.15s ease'
      }}
      onKeyDown={e => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault()
          onSelectTask(task)
        }
      }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: '14px', marginBottom: '10px', flexWrap: 'wrap' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
          <div style={{
            width: '36px',
            height: '36px',
            borderRadius: '10px',
            background: 'var(--bg-card-soft)',
            border: '1px solid var(--border)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            fontSize: '17px',
            flexShrink: 0
          }}>
            {meta.icon}
          </div>
          <div>
            <div style={{ fontSize: '13.5px', fontWeight: '700', color: 'var(--text-primary)' }}>{task.project}</div>
            <div style={{ fontSize: '11.5px', color: 'var(--text-muted)' }}>{task.timestamp}</div>
          </div>
        </div>

        {/* Badge & Quick Delete Action */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <span className={`badge-${task.domain}`} style={{
            fontSize: '11px',
            padding: '3px 10px',
            borderRadius: '20px',
            fontWeight: '600',
            flexShrink: 0,
            background: 'rgba(255,255,255,0.06)',
            color: meta.color,
            border: '1px solid ' + (meta.border || 'rgba(255,255,255,0.1)')
          }}>
            {meta.label}
          </span>
          <button
            className="btn-delete-deadline"
            id={`btn-delete-task-${task.id}`}
            title="Delete deadline"
            onClick={async (e) => {
              e.stopPropagation()
              if (window.confirm(`Delete deadline "${task.title}"?`)) {
                await onDeleteTask(task.id)
              }
            }}
            style={{
              background: 'transparent',
              border: '1px solid transparent',
              color: '#64748b',
              width: '26px',
              height: '26px',
              borderRadius: '6px',
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              fontSize: '13px',
              lineHeight: 1,
              transition: 'all 0.15s ease'
            }}
            onMouseEnter={e => {
              e.currentTarget.style.color = '#ef4444'
              e.currentTarget.style.background = 'rgba(239, 68, 68, 0.15)'
              e.currentTarget.style.borderColor = 'rgba(239, 68, 68, 0.3)'
            }}
            onMouseLeave={e => {
              e.currentTarget.style.color = '#64748b'
              e.currentTarget.style.background = 'transparent'
              e.currentTarget.style.borderColor = 'transparent'
            }}
          >
            🗑️
          </button>
        </div>
      </div>

      {/* Title with Quick Completion Checkbox */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '12px' }}>
        <button
          className="btn-toggle-task-status"
          id={`btn-toggle-status-${task.id}`}
          title={isCompleted ? 'Mark as open' : 'Mark as completed'}
          onClick={async (e) => {
            e.stopPropagation()
            onToggleStatus(task.id, isCompleted)
          }}
          style={{
            width: '22px',
            height: '22px',
            borderRadius: '50%',
            border: isCompleted ? '1.5px solid #10b981' : '1.5px solid var(--border)',
            background: isCompleted ? '#10b981' : 'var(--bg-card-soft)',
            color: isCompleted ? '#ffffff' : 'var(--text-muted)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            cursor: 'pointer',
            fontSize: '12px',
            flexShrink: 0,
            transition: 'all 0.15s ease'
          }}
          onMouseEnter={e => {
            if (!isCompleted) {
              e.currentTarget.style.borderColor = '#10b981'
              e.currentTarget.style.color = '#10b981'
            }
          }}
          onMouseLeave={e => {
            if (!isCompleted) {
              e.currentTarget.style.borderColor = 'var(--border)'
              e.currentTarget.style.color = 'var(--text-muted)'
            }
          }}
        >
          ✓
        </button>
        <div style={{
          fontSize: '15px',
          fontWeight: '600',
          color: isCompleted ? 'var(--text-muted)' : 'var(--text-primary)',
          textDecoration: isCompleted ? 'line-through' : 'none',
          lineHeight: '1.4',
          flex: 1
        }}>
          {task.title}
        </div>
      </div>

      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '10px' }}>
        <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap' }}>
          {(task.tags || []).map(tag => (
            <span key={tag} style={{ fontSize: '10.5px', background: 'var(--bg-card-soft)', color: 'var(--text-secondary)', padding: '2px 8px', borderRadius: '20px', border: '1px solid var(--border)' }}>
              #{tag}
            </span>
          ))}
        </div>
        <div style={{ display: 'flex', gap: '6px', alignItems: 'center', flexShrink: 0 }}>
          <div className={`countdown-badge ${isOverdue ? 'countdown-overdue' : ''}`}>
            {isOverdue && '⚠️ '}
            {task.countdown}
          </div>
        </div>
      </div>
    </div>
  )
}
