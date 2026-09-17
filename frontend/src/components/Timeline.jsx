import React, { useState } from 'react'

const KNOWN_FIELDS = new Set([
  'id', 'domain', 'project', 'timestamp', 'title', 'tags',
  'countdown', 'vector_dim', 'description'
])

function formatFieldLabel(key) {
  return key
    .replace(/_/g, ' ')
    .replace(/\b\w/g, c => c.toUpperCase())
}

function formatFieldValue(value) {
  if (value === null || value === undefined || value === '') return '—'
  if (Array.isArray(value)) return value.join(', ')
  if (typeof value === 'object') return JSON.stringify(value, null, 2)
  return String(value)
}

function TaskDetailModal({ task, onClose }) {
  if (!task) return null

  const isOverdue = (task.countdown || '').toLowerCase().includes('overdue')
  const extraEntries = Object.entries(task).filter(([key, value]) => {
    if (KNOWN_FIELDS.has(key)) return false
    if (value === null || value === undefined || value === '') return false
    return true
  })

  return (
    <div
      onClick={onClose}
      style={{
        position: 'fixed',
        inset: 0,
        background: 'rgba(2, 6, 15, 0.72)',
        backdropFilter: 'blur(2px)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        zIndex: 1000,
        padding: '20px'
      }}
    >
      <div
        onClick={e => e.stopPropagation()}
        className={`card-${task.domain}`}
        style={{
          background: '#111827',
          borderRadius: '12px',
          border: '1px solid #1f2937',
          width: '100%',
          maxWidth: '560px',
          maxHeight: '85vh',
          overflowY: 'auto',
          padding: '24px',
          boxShadow: '0 20px 60px rgba(0,0,0,0.5)'
        }}
      >
        {/* Header */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '16px', gap: '12px' }}>
          <div style={{ display: 'flex', gap: '8px', alignItems: 'center', flexWrap: 'wrap' }}>
            <span className={`badge-${task.domain}`} style={{ fontSize: '10.5px', padding: '2px 7px', borderRadius: '5px', textTransform: 'uppercase', fontWeight: '700' }}>
              {task.domain}
            </span>
            <span style={{ fontSize: '12px', color: '#94a3b8', fontWeight: '500' }}>
              • {task.project}
            </span>
          </div>
          <button
            onClick={onClose}
            style={{
              background: '#1e293b',
              border: '1px solid #334155',
              color: '#94a3b8',
              width: '26px',
              height: '26px',
              borderRadius: '6px',
              cursor: 'pointer',
              fontSize: '14px',
              lineHeight: 1,
              flexShrink: 0
            }}
          >
            ✕
          </button>
        </div>

        {/* Title */}
        <div style={{ marginBottom: task.description ? '14px' : '18px' }}>
          <div style={{ fontSize: '10px', textTransform: 'uppercase', letterSpacing: '0.06em', color: '#64748b', fontWeight: '700', marginBottom: '4px' }}>
            Title
          </div>
          <div style={{ fontSize: '18px', fontWeight: '600', color: '#f8fafc', lineHeight: '1.4' }}>
            {task.title}
          </div>
        </div>

        {/* Description — only renders when the backend actually provides one */}
        {task.description && (
          <div style={{ marginBottom: '18px' }}>
            <div style={{ fontSize: '10px', textTransform: 'uppercase', letterSpacing: '0.06em', color: '#64748b', fontWeight: '700', marginBottom: '4px' }}>
              Description
            </div>
            <div style={{ fontSize: '13.5px', color: '#cbd5e1', lineHeight: '1.6', whiteSpace: 'pre-wrap' }}>
              {task.description}
            </div>
          </div>
        )}

        {/* Status Row */}
        <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap', marginBottom: '18px' }}>
          <div className={`countdown-badge ${isOverdue ? 'countdown-overdue' : ''}`}>
            {isOverdue && '⚠️ '}
            {task.countdown}
          </div>
          <div className="vector-tag">
            {task.vector_dim || 768}-dim embedded
          </div>
        </div>

        {/* Core details grid */}
        <div style={{
          display: 'grid',
          gridTemplateColumns: '110px 1fr',
          rowGap: '10px',
          columnGap: '12px',
          fontSize: '13px',
          marginBottom: extraEntries.length ? '18px' : 0,
          borderTop: '1px solid #1f2937',
          paddingTop: '16px'
        }}>
          <div style={{ color: '#64748b' }}>ID</div>
          <div style={{ color: '#e2e8f0', fontFamily: "'JetBrains Mono', monospace", fontSize: '12px' }}>{task.id}</div>

          <div style={{ color: '#64748b' }}>Logged</div>
          <div style={{ color: '#e2e8f0' }}>{task.timestamp}</div>

          <div style={{ color: '#64748b' }}>Tags</div>
          <div style={{ display: 'flex', gap: '5px', flexWrap: 'wrap' }}>
            {(task.tags || []).length > 0 ? task.tags.map(tag => (
              <span key={tag} style={{ fontSize: '10.5px', background: '#1e293b', color: '#94a3b8', padding: '2px 7px', borderRadius: '4px' }}>
                #{tag}
              </span>
            )) : <span style={{ color: '#64748b' }}>—</span>}
          </div>
        </div>

        {/* Any additional fields present on the task object */}
        {extraEntries.length > 0 && (
          <div style={{
            display: 'grid',
            gridTemplateColumns: '110px 1fr',
            rowGap: '10px',
            columnGap: '12px',
            fontSize: '13px',
            borderTop: '1px solid #1f2937',
            paddingTop: '16px'
          }}>
            {extraEntries.map(([key, value]) => (
              <React.Fragment key={key}>
                <div style={{ color: '#64748b' }}>{formatFieldLabel(key)}</div>
                <div style={{ color: '#e2e8f0', whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
                  {formatFieldValue(value)}
                </div>
              </React.Fragment>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

export default function Timeline({ tasks, activeDomain, onSelectDomain }) {
  const [selectedTask, setSelectedTask] = useState(null)
  const filtered = activeDomain === 'all' ? tasks : tasks.filter(t => t.domain === activeDomain)

  return (
    <div style={{ padding: '20px', overflowY: 'auto', flex: 1, minWidth: 0 }}>
      {/* Header & Filter Bar */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '18px', flexWrap: 'wrap', gap: '10px' }}>
        <div>
          <h2 style={{ fontSize: '17px', fontWeight: '600', color: '#f8fafc', letterSpacing: '-0.2px' }}>
            Synchronized Context Stream
          </h2>
          <p style={{ fontSize: '12px', color: '#64748b' }}>
            Multi-domain vector memory logs synced from CLI and backend
          </p>
        </div>
        <div style={{ display: 'flex', gap: '6px' }}>
          {['all', 'hackathon', 'coursework', 'code', 'general'].map(dom => (
            <button
              key={dom}
              onClick={() => onSelectDomain(dom)}
              style={{
                padding: '5px 11px',
                borderRadius: '6px',
                fontSize: '11.5px',
                background: activeDomain === dom ? '#334155' : '#1e293b',
                border: activeDomain === dom ? '1px solid #475569' : '1px solid #1e293b',
                color: activeDomain === dom ? '#fff' : '#94a3b8',
                cursor: 'pointer',
                textTransform: 'capitalize',
                fontWeight: '500',
                transition: 'all 0.15s ease'
              }}>
              {dom}
            </button>
          ))}
        </div>
      </div>

      {/* Task Stream Feed */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
        {filtered.length === 0 ? (
          <div style={{
            padding: '40px 20px',
            textAlign: 'center',
            background: '#111827',
            borderRadius: '10px',
            border: '1px dashed #334155',
            color: '#94a3b8',
            marginTop: '10px'
          }}>
            <div style={{ fontSize: '28px', marginBottom: '10px' }}>📭</div>
            <div style={{ fontSize: '15px', fontWeight: '600', color: '#f8fafc', marginBottom: '6px' }}>
              No tasks found
            </div>
            <div style={{ fontSize: '12px', color: '#64748b' }}>
              {activeDomain === 'all'
                ? "Your memory stream is clear. Add tasks via CLI ('compass add ...') or in the Chat tab."
                : `No active tasks found under ${activeDomain.toUpperCase()} domain.`}
            </div>
          </div>
        ) : filtered.map(task => {
          const isOverdue = (task.countdown || '').toLowerCase().includes('overdue')

          return (
            <div
              key={task.id}
              className={`card-${task.domain}`}
              onClick={() => setSelectedTask(task)}
              role="button"
              tabIndex={0}
              onKeyDown={e => {
                if (e.key === 'Enter' || e.key === ' ') {
                  e.preventDefault()
                  setSelectedTask(task)
                }
              }}
              style={{
                background: '#111827',
                padding: '16px',
                borderRadius: '10px',
                border: '1px solid #1f2937',
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'flex-start',
                gap: '14px',
                cursor: 'pointer'
              }}>
              {/* Left Column: Domain Badge, Project, Timestamp, Title, Tags */}
              <div style={{ flex: 1, minWidth: '180px' }}>
                <div style={{ display: 'flex', gap: '8px', alignItems: 'center', marginBottom: '8px', flexWrap: 'wrap' }}>
                  <span className={`badge-${task.domain}`} style={{ fontSize: '10.5px', padding: '2px 7px', borderRadius: '5px', textTransform: 'uppercase', fontWeight: '700' }}>
                    {task.domain}
                  </span>
                  <span style={{ fontSize: '12px', color: '#94a3b8', fontWeight: '500' }}>
                    • {task.project}
                  </span>
                  <span style={{ fontSize: '11px', color: '#64748b' }}>
                    • {task.timestamp}
                  </span>
                </div>

                <div style={{ fontSize: '14px', fontWeight: '500', color: '#f8fafc', marginBottom: '10px', lineHeight: '1.4' }}>
                  {task.title}
                </div>

                <div style={{ display: 'flex', gap: '5px', flexWrap: 'wrap' }}>
                  {(task.tags || []).map(tag => (
                    <span key={tag} style={{ fontSize: '10.5px', background: '#1e293b', color: '#94a3b8', padding: '2px 7px', borderRadius: '4px' }}>
                      #{tag}
                    </span>
                  ))}
                </div>
              </div>

              {/* Right Column: Countdown Badge & Dimension Tag (Guaranteed Right-Aligned, Non-Wrapping) */}
              <div style={{
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'flex-end',
                flexShrink: 0,
                whiteSpace: 'nowrap'
              }}>
                <div className={`countdown-badge ${isOverdue ? 'countdown-overdue' : ''}`} style={{ marginBottom: '6px', whiteSpace: 'nowrap' }}>
                  {isOverdue && '⚠️ '}
                  {task.countdown}
                </div>
                <div className="vector-tag" style={{ whiteSpace: 'nowrap' }}>
                  {task.vector_dim || 768}-dim embedded
                </div>
              </div>
            </div>
          )
        })}
      </div>

      <TaskDetailModal task={selectedTask} onClose={() => setSelectedTask(null)} />
    </div>
  )
}