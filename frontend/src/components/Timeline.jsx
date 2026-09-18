import React, { useState } from 'react'

const KNOWN_FIELDS = new Set([
  'id', 'domain', 'project', 'timestamp', 'title', 'tags',
  'countdown', 'vector_dim', 'description', 'notes'
])

const DOMAIN_META = {
  hackathon: { icon: '🚀', label: 'Hackathon' },
  coursework: { icon: '📚', label: 'Coursework' },
  code: { icon: '💻', label: 'Code' },
  general: { icon: '🌐', label: 'General' },
}

function formatFieldLabel(key) {
  return key.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())
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
  const notesOrDescription = task.notes || task.description
  const extraEntries = Object.entries(task).filter(([key, value]) => {
    if (KNOWN_FIELDS.has(key)) return false
    if (value === null || value === undefined || value === '') return false
    return true
  })

  return (
    <div
      onClick={onClose}
      style={{
        position: 'fixed', inset: 0, background: 'rgba(31, 27, 46, 0.35)',
        backdropFilter: 'blur(2px)', display: 'flex', alignItems: 'center',
        justifyContent: 'center', zIndex: 1000, padding: '20px'
      }}
    >
      <div
        onClick={e => e.stopPropagation()}
        className={`card-${task.domain}`}
        style={{
          background: 'var(--bg-card)', borderRadius: '16px', border: '1px solid var(--border)',
          width: '100%', maxWidth: '560px', maxHeight: '85vh', overflowY: 'auto',
          padding: '26px', boxShadow: 'var(--shadow-lg)'
        }}
      >
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '18px', gap: '12px' }}>
          <div style={{ display: 'flex', gap: '8px', alignItems: 'center', flexWrap: 'wrap' }}>
            <span className={`badge-${task.domain}`} style={{ fontSize: '10.5px', padding: '3px 10px', borderRadius: '20px', textTransform: 'uppercase', fontWeight: '700' }}>
              {task.domain}
            </span>
            <span style={{ fontSize: '12.5px', color: 'var(--text-secondary)', fontWeight: '500' }}>
              • {task.project}
            </span>
          </div>
          <button
            onClick={onClose}
            style={{
              background: 'var(--bg-card-soft)', border: '1px solid var(--border)', color: 'var(--text-secondary)',
              width: '28px', height: '28px', borderRadius: '50%', cursor: 'pointer',
              fontSize: '14px', lineHeight: 1, flexShrink: 0
            }}
          >
            ✕
          </button>
        </div>

        <div style={{ marginBottom: notesOrDescription ? '14px' : '18px' }}>
          <div style={{ fontSize: '10px', textTransform: 'uppercase', letterSpacing: '0.06em', color: 'var(--text-muted)', fontWeight: '700', marginBottom: '5px' }}>
            Title
          </div>
          <div style={{ fontSize: '19px', fontWeight: '700', color: 'var(--text-primary)', lineHeight: '1.4' }}>
            {task.title}
          </div>
        </div>

        {notesOrDescription && (
          <div style={{ marginBottom: '18px' }}>
            <div style={{ fontSize: '10px', textTransform: 'uppercase', letterSpacing: '0.06em', color: 'var(--text-muted)', fontWeight: '700', marginBottom: '5px' }}>
              Notes
            </div>
            <div style={{ fontSize: '14px', color: 'var(--text-secondary)', lineHeight: '1.6', whiteSpace: 'pre-wrap' }}>
              {notesOrDescription}
            </div>
          </div>
        )}

        <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap', marginBottom: '18px' }}>
          <div className={`countdown-badge ${isOverdue ? 'countdown-overdue' : ''}`}>
            {isOverdue && '⚠️ '}{task.countdown}
          </div>
          <div className="vector-tag">{task.vector_dim || 768}-dim embedded</div>
        </div>

        <div style={{
          display: 'grid', gridTemplateColumns: '110px 1fr', rowGap: '10px', columnGap: '12px',
          fontSize: '13px', marginBottom: extraEntries.length ? '18px' : 0,
          borderTop: '1px solid var(--border-soft)', paddingTop: '16px'
        }}>
          <div style={{ color: 'var(--text-muted)' }}>ID</div>
          <div style={{ color: 'var(--text-primary)', fontFamily: "'JetBrains Mono', monospace", fontSize: '12px' }}>{task.id}</div>

          <div style={{ color: 'var(--text-muted)' }}>Logged</div>
          <div style={{ color: 'var(--text-primary)' }}>{task.timestamp}</div>

          <div style={{ color: 'var(--text-muted)' }}>Tags</div>
          <div style={{ display: 'flex', gap: '5px', flexWrap: 'wrap' }}>
            {(task.tags || []).length > 0 ? task.tags.map(tag => (
              <span key={tag} style={{ fontSize: '10.5px', background: 'var(--bg-card-soft)', color: 'var(--text-secondary)', padding: '2px 9px', borderRadius: '20px', border: '1px solid var(--border)' }}>
                #{tag}
              </span>
            )) : <span style={{ color: 'var(--text-muted)' }}>—</span>}
          </div>
        </div>

        {extraEntries.length > 0 && (
          <div style={{
            display: 'grid', gridTemplateColumns: '110px 1fr', rowGap: '10px', columnGap: '12px',
            fontSize: '13px', borderTop: '1px solid var(--border-soft)', paddingTop: '16px'
          }}>
            {extraEntries.map(([key, value]) => (
              <React.Fragment key={key}>
                <div style={{ color: 'var(--text-muted)' }}>{formatFieldLabel(key)}</div>
                <div style={{ color: 'var(--text-primary)', whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
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
  const today = new Date().toLocaleDateString('en-US', { weekday: 'long' })

  return (
    <div style={{ padding: '32px 36px', overflowY: 'auto', flex: 1, minWidth: 0, background: 'var(--bg-app)' }}>
      {/* Header */}
      <div style={{ marginBottom: '26px' }}>
        <h2 style={{ fontSize: '30px', fontWeight: '800', color: 'var(--text-primary)', letterSpacing: '-0.5px' }}>
          Timeline Feed <span className="serif-accent" style={{ color: 'var(--text-secondary)', fontWeight: '600' }}>— {today}</span>
        </h2>
        <p style={{ fontSize: '14px', color: 'var(--text-secondary)', marginTop: '4px' }}>
          What's happening across your workspace today
        </p>
      </div>

      {/* Filter pills */}
      <div style={{ display: 'flex', gap: '8px', marginBottom: '24px', flexWrap: 'wrap' }}>
        {['all', 'hackathon', 'coursework', 'code', 'general'].map(dom => (
          <button
            key={dom}
            onClick={() => onSelectDomain(dom)}
            className={`filter-pill ${activeDomain === dom ? 'active' : ''}`}
          >
            {dom}
          </button>
        ))}
      </div>

      {/* Task Stream Feed */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: '14px', maxWidth: '760px' }}>
        {filtered.length === 0 ? (
          <div style={{
            padding: '48px 20px', textAlign: 'center', background: 'var(--bg-card)',
            borderRadius: '16px', border: '1px dashed var(--border)', color: 'var(--text-secondary)'
          }}>
            <div style={{ fontSize: '30px', marginBottom: '10px' }}>📭</div>
            <div style={{ fontSize: '16px', fontWeight: '700', color: 'var(--text-primary)', marginBottom: '6px' }}>
              No tasks found
            </div>
            <div style={{ fontSize: '13px', color: 'var(--text-muted)' }}>
              {activeDomain === 'all'
                ? "Your workspace is clear. Add tasks via CLI ('compass add ...') or in the Chat tab."
                : `No active tasks found under ${activeDomain.toUpperCase()} domain.`}
            </div>
          </div>
        ) : filtered.map(task => {
          const isOverdue = (task.countdown || '').toLowerCase().includes('overdue')
          const meta = DOMAIN_META[task.domain] || DOMAIN_META.general

          return (
            <div
              key={task.id}
              className={`card-${task.domain}`}
              onClick={() => setSelectedTask(task)}
              role="button"
              tabIndex={0}
              onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setSelectedTask(task) } }}
              style={{
                background: 'var(--bg-card)', padding: '20px', borderRadius: '16px',
                border: '1px solid var(--border)', boxShadow: 'var(--shadow-sm)',
                cursor: 'pointer'
              }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: '14px', marginBottom: '12px' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                  <div style={{
                    width: '38px', height: '38px', borderRadius: '10px',
                    background: 'var(--bg-card-soft)', border: '1px solid var(--border)',
                    display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '17px', flexShrink: 0
                  }}>
                    {meta.icon}
                  </div>
                  <div>
                    <div style={{ fontSize: '13.5px', fontWeight: '700', color: 'var(--text-primary)' }}>{task.project}</div>
                    <div style={{ fontSize: '11.5px', color: 'var(--text-muted)' }}>{task.timestamp}</div>
                  </div>
                </div>
                <span className={`badge-${task.domain}`} style={{ fontSize: '10.5px', padding: '3px 10px', borderRadius: '20px', textTransform: 'uppercase', fontWeight: '700', flexShrink: 0 }}>
                  {meta.label}
                </span>
              </div>

              <div style={{ fontSize: '15px', fontWeight: '600', color: 'var(--text-primary)', marginBottom: '14px', lineHeight: '1.5' }}>
                {task.title}
              </div>

              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '10px' }}>
                <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap' }}>
                  {(task.tags || []).map(tag => (
                    <span key={tag} style={{ fontSize: '10.5px', background: 'var(--bg-card-soft)', color: 'var(--text-secondary)', padding: '3px 9px', borderRadius: '20px', border: '1px solid var(--border)' }}>
                      #{tag}
                    </span>
                  ))}
                </div>
                <div style={{ display: 'flex', gap: '6px', alignItems: 'center', flexShrink: 0 }}>
                  <div className={`countdown-badge ${isOverdue ? 'countdown-overdue' : ''}`}>
                    {isOverdue && '⚠️ '}{task.countdown}
                  </div>
                  <div className="vector-tag">{task.vector_dim || 768}-dim</div>
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