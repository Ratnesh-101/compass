import React from 'react'
import { getDomainMeta } from './domainMeta'

export function formatHumanDate(ts) {
  if (!ts) return ''
  try {
    const d = new Date(ts)
    if (isNaN(d.getTime())) return String(ts)
    const now = new Date()
    const isToday = d.toDateString() === now.toDateString()
    const yesterday = new Date(now)
    yesterday.setDate(now.getDate() - 1)
    const isYesterday = d.toDateString() === yesterday.toDateString()

    const timeStr = d.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' }).toLowerCase()

    if (isToday) {
      return `Added today, ${timeStr}`
    }
    if (isYesterday) {
      return `Added yesterday, ${timeStr}`
    }
    const monthDay = d.toLocaleDateString([], { month: 'short', day: 'numeric' })
    if (d.getFullYear() === now.getFullYear()) {
      return `Added ${monthDay}, ${timeStr}`
    }
    return `Added ${d.toLocaleDateString([], { month: 'short', day: 'numeric', year: 'numeric' })}, ${timeStr}`
  } catch {
    return String(ts)
  }
}

export default function TaskCard({
  task,
  onSelectTask,
  onDeleteTask,
  onToggleStatus,
  isHighlighted = false,
}) {
  const isOverdue = (task.countdown || '').toLowerCase().includes('overdue')
  const isCompleted = task.status === 'completed' || task.status === 'done'
  const meta = getDomainMeta(task.domain)

  return (
    <div
      id={`task-card-${task.id}`}
      className={`timeline-card card-${task.domain} ${isHighlighted ? 'task-highlighted' : ''}`}
      onClick={() => onSelectTask(task)}
      role="button"
      tabIndex={0}
      style={{
        opacity: isCompleted ? 0.75 : 1,
        transition: 'all 0.25s ease',
        background: isHighlighted ? 'rgba(217, 119, 6, 0.08)' : 'var(--bg-card)',
        border: isHighlighted ? '2px solid #d97706' : '1px solid var(--border)',
        boxShadow: isHighlighted ? '0 0 0 3px rgba(217, 119, 6, 0.2), 0 4px 14px rgba(217, 119, 6, 0.15)' : 'none',
        borderRadius: 'var(--radius-card, 8px)',
        padding: '16px',
        marginBottom: '12px',
        cursor: 'pointer',
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
            borderRadius: 'var(--radius-btn, 6px)',
            background: 'var(--bg-card-soft)',
            border: '1px solid var(--border)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            fontSize: '15px',
            color: 'var(--text-primary)',
            flexShrink: 0
          }}>
            {meta.icon}
          </div>
          <div>
            <div style={{ fontSize: '14px', fontWeight: '600', color: 'var(--text-primary)' }}>{task.project}</div>
            <div style={{ fontSize: '13px', color: 'var(--text-secondary)' }}>{formatHumanDate(task.timestamp || task.created_at)}</div>
          </div>
        </div>

        {/* Badge with 8px domain swatch & Quick Delete Action */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <span style={{
            fontSize: '12px',
            padding: '4px 10px',
            borderRadius: 'var(--radius-btn, 6px)',
            fontWeight: '500',
            flexShrink: 0,
            background: 'var(--bg-card-soft)',
            color: 'var(--text-primary)',
            border: '1px solid var(--border)',
            display: 'inline-flex',
            alignItems: 'center',
            gap: '6px'
          }}>
            <span
              className="domain-swatch"
              style={{ background: meta.color }}
            />
            {meta.label}
          </span>
          <button
            className="btn-delete-deadline btn-touch-target"
            id={`btn-delete-task-${task.id}`}
            title="Delete deadline"
            aria-label={`Delete deadline "${task.title}"`}
            onClick={async (e) => {
              e.stopPropagation()
              if (window.confirm(`Delete deadline "${task.title}"?`)) {
                await onDeleteTask(task.id)
              }
            }}
            style={{
              background: 'transparent',
              border: '1px solid transparent',
              color: 'var(--text-secondary)',
              minWidth: '44px',
              minHeight: '44px',
              borderRadius: 'var(--radius-btn, 6px)',
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              lineHeight: 1,
              transition: 'all 0.15s ease'
            }}
            onMouseEnter={e => {
              e.currentTarget.style.color = '#ef4444'
              e.currentTarget.style.background = 'rgba(239, 68, 68, 0.1)'
              e.currentTarget.style.borderColor = 'rgba(239, 68, 68, 0.3)'
            }}
            onMouseLeave={e => {
              e.currentTarget.style.color = 'var(--text-secondary)'
              e.currentTarget.style.background = 'transparent'
              e.currentTarget.style.borderColor = 'transparent'
            }}
          >
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
              <polyline points="3 6 5 6 21 6" />
              <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
            </svg>
          </button>
        </div>
      </div>

      {/* Title with Quick Completion Checkbox */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '12px' }}>
        <button
          className="btn-toggle-task-status"
          id={`btn-toggle-status-${task.id}`}
          title={isCompleted ? 'Mark as open' : 'Mark as completed'}
          aria-label={isCompleted ? `Mark "${task.title}" as open` : `Mark "${task.title}" as completed`}
          onClick={async (e) => {
            e.stopPropagation()
            onToggleStatus(task.id, isCompleted)
          }}
          style={{
            width: '28px',
            height: '28px',
            minWidth: '28px',
            minHeight: '28px',
            borderRadius: 'var(--radius-btn, 6px)',
            border: isCompleted ? '1.5px solid var(--domain-code, #1c8a62)' : '1.5px solid var(--border)',
            background: isCompleted ? 'var(--domain-code, #1c8a62)' : 'var(--bg-card-soft)',
            color: isCompleted ? '#ffffff' : 'var(--text-secondary)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            cursor: 'pointer',
            fontSize: '13px',
            flexShrink: 0,
            transition: 'all 0.15s ease'
          }}
          onMouseEnter={e => {
            if (!isCompleted) {
              e.currentTarget.style.borderColor = 'var(--domain-code, #1c8a62)'
              e.currentTarget.style.color = 'var(--domain-code, #1c8a62)'
            }
          }}
          onMouseLeave={e => {
            if (!isCompleted) {
              e.currentTarget.style.borderColor = 'var(--border)'
              e.currentTarget.style.color = 'var(--text-secondary)'
            }
          }}
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <polyline points="20 6 9 17 4 12" />
          </svg>
        </button>
        <div style={{
          fontSize: '14px',
          fontWeight: '500',
          color: isCompleted ? 'var(--text-secondary)' : 'var(--text-primary)',
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
            <span key={tag} style={{ fontSize: '11px', background: 'var(--bg-card-soft)', color: 'var(--text-secondary)', padding: '3px 8px', borderRadius: 'var(--radius-btn, 6px)', border: '1px solid var(--border)' }}>
              #{tag}
            </span>
          ))}
        </div>
        <div style={{ display: 'flex', gap: '6px', alignItems: 'center', flexShrink: 0 }}>
          <div className={`countdown-badge ${isOverdue ? 'countdown-overdue' : ''}`} style={{ borderRadius: 'var(--radius-btn, 6px)', display: 'inline-flex', alignItems: 'center', gap: '4px' }}>
            {isOverdue && (
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
                <path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z" />
                <line x1="12" y1="9" x2="12" y2="13" />
                <line x1="12" y1="17" x2="12.01" y2="17" />
              </svg>
            )}
            {task.countdown}
          </div>
        </div>
      </div>
    </div>
  )
}
