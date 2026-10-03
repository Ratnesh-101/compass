import React from 'react'
import {
  Check,
  Trash2,
  Clock,
  Calendar,
  AlertTriangle,
  Flame,
  BookOpen,
  Code2,
  Globe,
  Tag,
  Sparkles,
} from 'lucide-react'
import { getDomainMeta } from './domainMeta'

const DOMAIN_ICONS = {
  hackathon: Flame,
  coursework: BookOpen,
  code: Code2,
  general: Globe,
  other: Tag,
}

export default function TaskCard({
  task,
  onSelectTask,
  onDeleteTask,
  onToggleStatus,
}) {
  const isOverdue = (task.countdown || '').toLowerCase().includes('overdue')
  const isCompleted = task.status === 'completed' || task.status === 'done'
  const meta = getDomainMeta(task.domain)
  const DomainIcon = DOMAIN_ICONS[String(task.domain).toLowerCase()] || Tag

  const priority = String(task.priority || 'medium').toLowerCase()
  const priorityColors = {
    urgent: { bg: 'rgba(239, 68, 68, 0.12)', text: '#ef4444', border: 'rgba(239, 68, 68, 0.3)' },
    high: { bg: 'rgba(245, 158, 11, 0.12)', text: '#f59e0b', border: 'rgba(245, 158, 11, 0.3)' },
    medium: { bg: 'rgba(59, 130, 246, 0.12)', text: '#3b82f6', border: 'rgba(59, 130, 246, 0.3)' },
    low: { bg: 'rgba(100, 116, 139, 0.12)', text: '#64748b', border: 'rgba(100, 116, 139, 0.3)' },
  }
  const pStyle = priorityColors[priority] || priorityColors.medium

  return (
    <div
      className={`timeline-card card-${task.domain}`}
      onClick={() => onSelectTask(task)}
      role="button"
      tabIndex={0}
      style={{
        background: '#ffffff',
        border: '1px solid #e2e8f0',
        borderRadius: '12px',
        padding: '16px 20px',
        marginBottom: '12px',
        boxShadow: '0 1px 3px rgba(0, 0, 0, 0.05), 0 1px 2px rgba(0, 0, 0, 0.04)',
        opacity: isCompleted ? 0.7 : 1,
        transition: 'all 0.2s cubic-bezier(0.16, 1, 0.3, 1)',
        cursor: 'pointer',
      }}
      onMouseEnter={e => {
        e.currentTarget.style.transform = 'translateY(-2px)'
        e.currentTarget.style.boxShadow = '0 6px 16px -2px rgba(0, 0, 0, 0.08), 0 2px 6px -1px rgba(0, 0, 0, 0.04)'
        e.currentTarget.style.borderColor = '#cbd5e1'
      }}
      onMouseLeave={e => {
        e.currentTarget.style.transform = 'translateY(0)'
        e.currentTarget.style.boxShadow = '0 1px 3px rgba(0, 0, 0, 0.05), 0 1px 2px rgba(0, 0, 0, 0.04)'
        e.currentTarget.style.borderColor = '#e2e8f0'
      }}
      onKeyDown={e => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault()
          onSelectTask(task)
        }
      }}
    >
      {/* Top Metadata Row */}
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          gap: '12px',
          marginBottom: '12px',
          flexWrap: 'wrap',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
          <div
            style={{
              width: '32px',
              height: '32px',
              borderRadius: '8px',
              background: 'rgba(15, 23, 42, 0.04)',
              border: '1px solid #e2e8f0',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              color: meta.color,
              flexShrink: 0,
            }}
          >
            <DomainIcon size={16} />
          </div>
          <div>
            <div style={{ fontSize: '13px', fontWeight: '700', color: '#0f172a' }}>
              {task.project || 'General'}
            </div>
            <div style={{ fontSize: '11px', color: '#64748b' }}>
              {task.timestamp || 'Active task'}
            </div>
          </div>
        </div>

        {/* Badges: Priority, Domain, and Delete */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          {task.priority && (
            <span
              style={{
                fontSize: '10.5px',
                fontWeight: '700',
                padding: '2px 8px',
                borderRadius: '6px',
                background: pStyle.bg,
                color: pStyle.text,
                border: `1px solid ${pStyle.border}`,
                textTransform: 'uppercase',
                letterSpacing: '0.04em',
              }}
            >
              {task.priority}
            </span>
          )}

          <span
            style={{
              fontSize: '11px',
              padding: '3px 10px',
              borderRadius: '20px',
              fontWeight: '700',
              background: 'rgba(15, 23, 42, 0.04)',
              color: meta.color,
              border: `1px solid ${meta.border || 'rgba(0,0,0,0.1)'}`,
              display: 'inline-flex',
              alignItems: 'center',
              gap: '4px',
            }}
          >
            {meta.label}
          </span>

          <button
            className="btn-delete-deadline"
            id={`btn-delete-task-${task.id}`}
            title="Delete task"
            onClick={async e => {
              e.stopPropagation()
              if (window.confirm(`Delete deadline "${task.title}"?`)) {
                await onDeleteTask(task.id)
              }
            }}
            style={{
              background: 'transparent',
              border: 'none',
              color: '#94a3b8',
              width: '28px',
              height: '28px',
              borderRadius: '6px',
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              transition: 'all 0.15s ease',
            }}
            onMouseEnter={e => {
              e.currentTarget.style.color = '#ef4444'
              e.currentTarget.style.background = 'rgba(239, 68, 68, 0.1)'
            }}
            onMouseLeave={e => {
              e.currentTarget.style.color = '#94a3b8'
              e.currentTarget.style.background = 'transparent'
            }}
          >
            <Trash2 size={14} />
          </button>
        </div>
      </div>

      {/* Task Title & Checkbox */}
      <div style={{ display: 'flex', alignItems: 'flex-start', gap: '12px', marginBottom: '12px' }}>
        <button
          className="btn-toggle-task-status"
          id={`btn-toggle-status-${task.id}`}
          title={isCompleted ? 'Mark as open' : 'Mark as completed'}
          onClick={async e => {
            e.stopPropagation()
            onToggleStatus(task.id, isCompleted)
          }}
          style={{
            width: '22px',
            height: '22px',
            borderRadius: '6px',
            border: isCompleted ? '1.5px solid #10b981' : '1.5px solid #cbd5e1',
            background: isCompleted ? '#10b981' : '#ffffff',
            color: isCompleted ? '#ffffff' : 'transparent',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            cursor: 'pointer',
            flexShrink: 0,
            marginTop: '2px',
            transition: 'all 0.15s ease',
          }}
          onMouseEnter={e => {
            if (!isCompleted) {
              e.currentTarget.style.borderColor = '#10b981'
              e.currentTarget.style.background = 'rgba(16, 185, 129, 0.08)'
            }
          }}
          onMouseLeave={e => {
            if (!isCompleted) {
              e.currentTarget.style.borderColor = '#cbd5e1'
              e.currentTarget.style.background = '#ffffff'
            }
          }}
        >
          <Check size={14} strokeWidth={3} />
        </button>

        <div style={{ flex: 1, minWidth: 0 }}>
          <div
            style={{
              fontSize: '15px',
              fontWeight: '600',
              color: isCompleted ? '#94a3b8' : '#0f172a',
              textDecoration: isCompleted ? 'line-through' : 'none',
              lineHeight: '1.4',
            }}
          >
            {task.title}
          </div>
          {task.description && (
            <div
              style={{
                fontSize: '12.5px',
                color: '#64748b',
                marginTop: '4px',
                overflow: 'hidden',
                textOverflow: 'ellipsis',
                display: '-webkit-box',
                WebkitLineClamp: 2,
                WebkitBoxOrient: 'vertical',
                lineHeight: '1.45',
              }}
            >
              {task.description}
            </div>
          )}
        </div>
      </div>

      {/* Footer Details: Tags, Countdown, Effort, Vector Memory */}
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          flexWrap: 'wrap',
          gap: '8px',
          paddingTop: '10px',
          borderTop: '1px solid #f1f5f9',
        }}
      >
        <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap', alignItems: 'center' }}>
          {(task.tags || []).map(tag => (
            <span
              key={tag}
              style={{
                fontSize: '11px',
                background: '#f8fafc',
                color: '#475569',
                padding: '2px 8px',
                borderRadius: '4px',
                border: '1px solid #e2e8f0',
                fontWeight: '500',
              }}
            >
              #{tag}
            </span>
          ))}

          {task.duration_minutes && (
            <span
              style={{
                fontSize: '11px',
                color: '#64748b',
                display: 'inline-flex',
                alignItems: 'center',
                gap: '4px',
                background: '#f1f5f9',
                padding: '2px 8px',
                borderRadius: '4px',
                fontWeight: '500',
              }}
            >
              <Clock size={11} />
              {task.duration_minutes}m focus
            </span>
          )}
        </div>

        <div style={{ display: 'flex', gap: '8px', alignItems: 'center', flexShrink: 0 }}>
          {task.countdown && (
            <div
              style={{
                fontSize: '11px',
                fontWeight: '600',
                color: isOverdue ? '#ef4444' : '#b45309',
                background: isOverdue ? 'rgba(239, 68, 68, 0.1)' : 'rgba(245, 158, 11, 0.12)',
                border: `1px solid ${isOverdue ? 'rgba(239, 68, 68, 0.3)' : 'rgba(245, 158, 11, 0.3)'}`,
                padding: '3px 8px',
                borderRadius: '6px',
                display: 'inline-flex',
                alignItems: 'center',
                gap: '4px',
              }}
            >
              {isOverdue ? <AlertTriangle size={12} /> : <Calendar size={12} />}
              <span>{task.countdown}</span>
            </div>
          )}

          <div
            style={{
              fontFamily: "'JetBrains Mono', monospace",
              fontSize: '10.5px',
              color: '#64748b',
              background: '#f8fafc',
              padding: '2px 7px',
              borderRadius: '4px',
              border: '1px solid #e2e8f0',
              display: 'inline-flex',
              alignItems: 'center',
              gap: '4px',
            }}
          >
            <Sparkles size={10} color="#6366f1" />
            {task.vector_dim || 768}-dim
          </div>
        </div>
      </div>
    </div>
  )
}
