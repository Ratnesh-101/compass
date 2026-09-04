import React from 'react'

export default function Timeline({ tasks, activeDomain, onSelectDomain }) {
  const filtered = activeDomain === 'all' ? tasks : tasks.filter(t => t.domain === activeDomain)

  return (
    <div style={{ padding: '28px', overflowY: 'auto', flex: 1 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '20px' }}>
        <div>
          <h2 style={{ fontSize: '18px', fontWeight: '600', color: '#f8fafc' }}>Synchronized Context Stream</h2>
          <p style={{ fontSize: '13px', color: '#64748b' }}>Cross-domain vector memory logs synced from CLI and backend</p>
        </div>
        <div style={{ display: 'flex', gap: '8px' }}>
          {['all', 'hackathon', 'coursework', 'code'].map(dom => (
            <button
              key={dom}
              onClick={() => onSelectDomain(dom)}
              style={{ padding: '6px 12px', borderRadius: '6px', fontSize: '12px', background: activeDomain === dom ? '#334155' : '#1e293b', border: '1px solid #334155', color: '#f1f5f9', cursor: 'pointer', textTransform: 'capitalize' }}>
              {dom}
            </button>
          ))}
        </div>
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
        {filtered.map(task => (
          <div
            key={task.id}
            className={`card-${task.domain}`}
            style={{ background: '#111827', padding: '18px', borderRadius: '10px', border: '1px solid #1f2937', display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
            <div style={{ maxWidth: '75%' }}>
              <div style={{ display: 'flex', gap: '8px', alignItems: 'center', marginBottom: '8px' }}>
                <span className={`badge-${task.domain}`} style={{ fontSize: '11px', padding: '2px 8px', borderRadius: '6px', textTransform: 'uppercase', fontWeight: '600' }}>
                  {task.domain}
                </span>
                <span style={{ fontSize: '12px', color: '#94a3b8' }}>• {task.project}</span>
                <span style={{ fontSize: '12px', color: '#475569' }}>• {task.timestamp}</span>
              </div>
              <div style={{ fontSize: '15px', fontWeight: '500', color: '#f8fafc', marginBottom: '10px', lineHeight: '1.4' }}>
                {task.title}
              </div>
              <div style={{ display: 'flex', gap: '6px' }}>
                {task.tags.map(tag => (
                  <span key={tag} style={{ fontSize: '11px', background: '#1e293b', color: '#94a3b8', padding: '2px 8px', borderRadius: '4px' }}>
                    #{tag}
                  </span>
                ))}
              </div>
            </div>

            <div style={{ textAlign: 'right' }}>
              <div style={{ fontSize: '12px', fontWeight: '600', color: '#fbbf24', background: 'rgba(251, 191, 36, 0.1)', padding: '4px 10px', borderRadius: '6px', border: '1px solid rgba(251, 191, 36, 0.2)', marginBottom: '8px' }}>
                {task.countdown}
              </div>
              <div className="mono" style={{ fontSize: '11px', color: '#475569' }}>
                {task.vector_dim}-dim embedded
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
