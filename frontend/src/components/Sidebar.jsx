import React from 'react'

export default function Sidebar({
  activeDomain,
  onSelectDomain,
  domainCounts = { hackathon: 0, coursework: 0, code: 0 },
  backendStatus = 'Checking...'
}) {
  return (
    <aside style={{
      width: '280px',
      borderRight: '1px solid #1e293b',
      background: '#0d131f',
      display: 'flex',
      flexDirection: 'column',
      padding: '24px 18px'
    }}>
      {/* Brand Header */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '28px' }}>
        <div style={{
          width: '32px',
          height: '32px',
          borderRadius: '8px',
          background: 'linear-gradient(135deg, #6366f1, #a855f7)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          fontWeight: 'bold',
          fontSize: '18px'
        }}>
          🧭
        </div>
        <div>
          <h1 style={{ fontSize: '18px', fontWeight: '700', letterSpacing: '-0.5px' }}>Compass</h1>
          <p style={{ fontSize: '11px', color: '#64748b' }}>Persistent AI Memory</p>
        </div>
      </div>

      {/* System Health Dot */}
      <div style={{
        padding: '8px 12px',
        borderRadius: '8px',
        background: 'rgba(16, 185, 129, 0.1)',
        border: '1px solid rgba(16, 185, 129, 0.2)',
        marginBottom: '24px',
        display: 'flex',
        alignItems: 'center',
        gap: '8px'
      }}>
        <div style={{
          width: '8px',
          height: '8px',
          borderRadius: '50%',
          background: '#10b981',
          boxShadow: '0 0 8px #10b981'
        }}></div>
        <span style={{ fontSize: '12px', color: '#34d399', fontWeight: '500' }}>{backendStatus}</span>
      </div>

      {/* Domain Navigation Counters */}
      <div style={{ marginBottom: 'auto' }}>
        <p style={{
          fontSize: '11px',
          textTransform: 'uppercase',
          letterSpacing: '0.05em',
          color: '#64748b',
          fontWeight: '600',
          marginBottom: '12px'
        }}>
          Active Domains
        </p>

        {/* 🚀 Hackathon */}
        <div
          onClick={() => onSelectDomain('hackathon')}
          style={{
            padding: '10px 14px',
            borderRadius: '8px',
            marginBottom: '8px',
            cursor: 'pointer',
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            background: activeDomain === 'hackathon' ? '#1e293b' : 'transparent',
            transition: 'background 0.2s'
          }}>
          <span style={{ fontSize: '14px', color: '#fbbf24', fontWeight: '500' }}>🚀 Hackathon</span>
          <span className="badge-hackathon" style={{ padding: '2px 8px', borderRadius: '12px', fontSize: '12px', fontWeight: '600' }}>
            {domainCounts.hackathon || 0}
          </span>
        </div>

        {/* 📚 Coursework */}
        <div
          onClick={() => onSelectDomain('coursework')}
          style={{
            padding: '10px 14px',
            borderRadius: '8px',
            marginBottom: '8px',
            cursor: 'pointer',
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            background: activeDomain === 'coursework' ? '#1e293b' : 'transparent',
            transition: 'background 0.2s'
          }}>
          <span style={{ fontSize: '14px', color: '#60a5fa', fontWeight: '500' }}>📚 Coursework</span>
          <span className="badge-coursework" style={{ padding: '2px 8px', borderRadius: '12px', fontSize: '12px', fontWeight: '600' }}>
            {domainCounts.coursework || 0}
          </span>
        </div>

        {/* 💻 Code */}
        <div
          onClick={() => onSelectDomain('code')}
          style={{
            padding: '10px 14px',
            borderRadius: '8px',
            marginBottom: '8px',
            cursor: 'pointer',
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            background: activeDomain === 'code' ? '#1e293b' : 'transparent',
            transition: 'background 0.2s'
          }}>
          <span style={{ fontSize: '14px', color: '#34d399', fontWeight: '500' }}>💻 Code</span>
          <span className="badge-code" style={{ padding: '2px 8px', borderRadius: '12px', fontSize: '12px', fontWeight: '600' }}>
            {domainCounts.code || 0}
          </span>
        </div>
      </div>

      {/* Architecture Specs Block */}
      <div style={{
        padding: '14px',
        borderRadius: '8px',
        background: '#131c2e',
        border: '1px solid #1e293b',
        fontSize: '11px',
        color: '#94a3b8',
        lineHeight: '1.6'
      }}>
        <div style={{ color: '#f1f5f9', fontWeight: '600', marginBottom: '6px' }}>Vector Engine Specs</div>
        <div>• Matryoshka: 768-dim</div>
        <div>• Router: Nemotron-3 Nano</div>
        <div>• Index: pgvector HNSW</div>
      </div>
    </aside>
  )
}
