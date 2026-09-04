import React from 'react'

export default function Timeline({ tasks, activeDomain, onSelectDomain }) {
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
          {['all', 'hackathon', 'coursework', 'code'].map(dom => (
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
        {filtered.map(task => {
          const isOverdue = (task.countdown || '').toLowerCase().includes('overdue')

          return (
            <div
              key={task.id}
              className={`card-${task.domain}`}
              style={{
                background: '#111827',
                padding: '16px',
                borderRadius: '10px',
                border: '1px solid #1f2937',
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'flex-start',
                gap: '14px'
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
    </div>
  )
}
