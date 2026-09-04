import React from 'react'

export default function Timeline({ tasks = [], activeDomain = 'all', onSelectDomain }) {
  const filteredTasks = activeDomain === 'all'
    ? tasks
    : tasks.filter(t => t.domain === activeDomain)

  return (
    <div style={{ padding: '28px', overflowY: 'auto', flex: 1 }}>
      {/* Header Row */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '20px' }}>
        <div>
          <h2 style={{ fontSize: '18px', fontWeight: '600' }}>Synchronized Context Stream</h2>
          <p style={{ fontSize: '12px', color: '#64748b', marginTop: '2px' }}>
            Live CLI and multi-agent memory events
          </p>
        </div>
        <span style={{ fontSize: '13px', color: '#64748b' }}>
          Showing <strong style={{ color: '#f8fafc' }}>{filteredTasks.length}</strong> active chunk(s)
        </span>
      </div>

      {/* Filter Pill Bar */}
      <div style={{ display: 'flex', gap: '8px', marginBottom: '20px' }}>
        {['all', 'hackathon', 'coursework', 'code'].map(dom => (
          <button
            key={dom}
            onClick={() => onSelectDomain(dom)}
            style={{
              padding: '6px 14px',
              borderRadius: '20px',
              fontSize: '12px',
              fontWeight: '500',
              border: activeDomain === dom ? '1px solid #6366f1' : '1px solid #1e293b',
              background: activeDomain === dom ? 'rgba(99, 102, 241, 0.15)' : '#0d131f',
              color: activeDomain === dom ? '#a5b4fc' : '#94a3b8',
              cursor: 'pointer',
              textTransform: 'capitalize',
              transition: 'all 0.15s'
            }}>
            {dom === 'all' ? '🌐 All Domains' : dom}
          </button>
        ))}
      </div>

      {/* Task Card Layout */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
        {filteredTasks.length === 0 ? (
          <div style={{ padding: '40px', textAlign: 'center', color: '#64748b', background: '#0d131f', borderRadius: '8px' }}>
            No memories or tasks in this domain yet. Run <code>compass log</code> in terminal to capture.
          </div>
        ) : (
          filteredTasks.map(task => (
            <div
              key={task.id}
              className={`card-${task.domain}`}
              style={{
                background: '#111827',
                padding: '18px',
                borderRadius: '10px',
                border: '1px solid #1f2937',
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'flex-start',
                transition: 'transform 0.15s',
              }}>
              <div>
                {/* Top Row: Domain badge, project name, timestamp */}
                <div style={{ display: 'flex', gap: '8px', alignItems: 'center', marginBottom: '8px' }}>
                  <span
                    className={`badge-${task.domain}`}
                    style={{
                      fontSize: '11px',
                      padding: '2px 8px',
                      borderRadius: '6px',
                      textTransform: 'uppercase',
                      fontWeight: '600'
                    }}>
                    {task.domain}
                  </span>
                  <span style={{ fontSize: '12px', color: '#94a3b8' }}>• {task.project}</span>
                  <span style={{ fontSize: '12px', color: '#475569' }}>• {task.timestamp}</span>
                </div>

                {/* Middle: Title/log text */}
                <div style={{ fontSize: '15px', fontWeight: '500', color: '#f8fafc', marginBottom: '10px' }}>
                  {task.title}
                </div>

                {/* Bottom: Tag pills */}
                <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap' }}>
                  {task.tags && task.tags.map(tag => (
                    <span
                      key={tag}
                      style={{
                        fontSize: '11px',
                        background: '#1e293b',
                        color: '#94a3b8',
                        padding: '2px 8px',
                        borderRadius: '4px'
                      }}>
                      #{tag}
                    </span>
                  ))}
                </div>
              </div>

              {/* Right Flank: Countdown badge & vector indicator */}
              <div style={{ textAlign: 'right', minWidth: '150px' }}>
                <div style={{
                  fontSize: '13px',
                  fontWeight: '600',
                  color: '#fbbf24',
                  background: 'rgba(251, 191, 36, 0.1)',
                  padding: '4px 10px',
                  borderRadius: '6px',
                  border: '1px solid rgba(251, 191, 36, 0.2)',
                  marginBottom: '8px',
                  display: 'inline-block'
                }}>
                  {task.countdown}
                </div>
                <div className="mono" style={{ fontSize: '11px', color: '#475569' }}>
                  {task.vector_dim || 768}-dim embedded
                </div>
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  )
}
