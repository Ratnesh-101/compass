import React from 'react'

export default function Sidebar({
  activeDomain,
  onSelectDomain,
  domainCounts,
  backendStatus,
  activeTab,
  onSelectTab
}) {
  const isOnline = backendStatus.toLowerCase().includes('neon') || backendStatus.toLowerCase().includes('live')

  return (
    <aside style={{
      width: '240px',
      minWidth: '220px',
      flexShrink: 0,
      borderRight: '1px solid #1e293b',
      background: '#0d131f',
      display: 'flex',
      flexDirection: 'column',
      padding: '20px 14px',
      height: '100vh',
      overflowY: 'auto'
    }}>
      {/* Brand */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '20px' }}>
        <div style={{
          width: '32px',
          height: '32px',
          borderRadius: '8px',
          background: 'linear-gradient(135deg, #6366f1, #a855f7)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          fontSize: '16px',
          boxShadow: '0 0 12px rgba(99, 102, 241, 0.4)'
        }}>
          🧭
        </div>
        <div>
          <h1 style={{ fontSize: '16px', fontWeight: '700', letterSpacing: '-0.3px', color: '#f8fafc' }}>Compass</h1>
          <p style={{ fontSize: '10.5px', color: '#64748b' }}>Persistent AI Memory</p>
        </div>
      </div>

      {/* Backend Health Pill */}
      <div style={{
        padding: '7px 10px',
        borderRadius: '8px',
        background: isOnline ? 'rgba(16, 185, 129, 0.1)' : 'rgba(245, 158, 11, 0.1)',
        border: isOnline ? '1px solid rgba(16, 185, 129, 0.25)' : '1px solid rgba(245, 158, 11, 0.25)',
        marginBottom: '20px',
        display: 'flex',
        alignItems: 'center',
        gap: '8px'
      }}>
        <div style={{
          width: '7px',
          height: '7px',
          borderRadius: '50%',
          background: isOnline ? '#10b981' : '#f59e0b',
          boxShadow: isOnline ? '0 0 8px #10b981' : '0 0 8px #f59e0b'
        }} />
        <span style={{ fontSize: '11px', color: isOnline ? '#34d399' : '#fbbf24', fontWeight: '500' }}>
          {backendStatus}
        </span>
      </div>

      {/* Navigation Tabs */}
      <div style={{ marginBottom: '22px' }}>
        <p style={{ fontSize: '10px', textTransform: 'uppercase', letterSpacing: '0.06em', color: '#64748b', fontWeight: '700', marginBottom: '8px' }}>
          Views
        </p>
        <button
          onClick={() => onSelectTab('timeline')}
          style={{
            width: '100%',
            textAlign: 'left',
            padding: '8px 12px',
            borderRadius: '6px',
            border: 'none',
            background: activeTab === 'timeline' ? '#1e293b' : 'transparent',
            color: activeTab === 'timeline' ? '#fff' : '#94a3b8',
            cursor: 'pointer',
            fontWeight: '500',
            fontSize: '12.5px',
            marginBottom: '4px'
          }}>
          📅 Timeline View
        </button>
        <button
          onClick={() => onSelectTab('chat')}
          style={{
            width: '100%',
            textAlign: 'left',
            padding: '8px 12px',
            borderRadius: '6px',
            border: 'none',
            background: activeTab === 'chat' ? '#1e293b' : 'transparent',
            color: activeTab === 'chat' ? '#fff' : '#94a3b8',
            cursor: 'pointer',
            fontWeight: '500',
            fontSize: '12.5px'
          }}>
          💬 Assistant Chat
        </button>
      </div>

      {/* Domain Isolation Metrics */}
      <div style={{ marginBottom: 'auto' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '10px' }}>
          <p style={{ fontSize: '10px', textTransform: 'uppercase', letterSpacing: '0.06em', color: '#64748b', fontWeight: '700' }}>
            Domain Isolation
          </p>
          {activeDomain !== 'all' && (
            <span onClick={() => onSelectDomain('all')} style={{ fontSize: '10px', color: '#818cf8', cursor: 'pointer', fontWeight: '600' }}>
              Reset
            </span>
          )}
        </div>

        <div
          onClick={() => onSelectDomain('hackathon')}
          style={{
            padding: '8px 12px',
            borderRadius: '8px',
            marginBottom: '6px',
            cursor: 'pointer',
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            background: activeDomain === 'hackathon' ? 'rgba(245, 158, 11, 0.15)' : 'transparent',
            border: activeDomain === 'hackathon' ? '1px solid rgba(245, 158, 11, 0.4)' : '1px solid transparent'
          }}>
          <span style={{ fontSize: '12.5px', color: '#fbbf24', fontWeight: '500' }}>🚀 Hackathon</span>
          <span className="badge-hackathon" style={{ padding: '2px 7px', borderRadius: '10px', fontSize: '10.5px', fontWeight: '700' }}>
            {domainCounts.hackathon}
          </span>
        </div>

        <div
          onClick={() => onSelectDomain('coursework')}
          style={{
            padding: '8px 12px',
            borderRadius: '8px',
            marginBottom: '6px',
            cursor: 'pointer',
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            background: activeDomain === 'coursework' ? 'rgba(59, 130, 246, 0.15)' : 'transparent',
            border: activeDomain === 'coursework' ? '1px solid rgba(59, 130, 246, 0.4)' : '1px solid transparent'
          }}>
          <span style={{ fontSize: '12.5px', color: '#60a5fa', fontWeight: '500' }}>📚 Coursework</span>
          <span className="badge-coursework" style={{ padding: '2px 7px', borderRadius: '10px', fontSize: '10.5px', fontWeight: '700' }}>
            {domainCounts.coursework}
          </span>
        </div>

        <div
          onClick={() => onSelectDomain('code')}
          style={{
            padding: '8px 12px',
            borderRadius: '8px',
            marginBottom: '6px',
            cursor: 'pointer',
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            background: activeDomain === 'code' ? 'rgba(16, 185, 129, 0.15)' : 'transparent',
            border: activeDomain === 'code' ? '1px solid rgba(16, 185, 129, 0.4)' : '1px solid transparent'
          }}>
          <span style={{ fontSize: '12.5px', color: '#34d399', fontWeight: '500' }}>💻 Code</span>
          <span className="badge-code" style={{ padding: '2px 7px', borderRadius: '10px', fontSize: '10.5px', fontWeight: '700' }}>
            {domainCounts.code}
          </span>
        </div>
      </div>

      {/* Technical Specs Card */}
      <div style={{
        padding: '12px',
        borderRadius: '8px',
        background: '#131c2e',
        border: '1px solid #1e293b',
        fontSize: '10.5px',
        color: '#94a3b8',
        marginTop: '16px'
      }}>
        <div style={{ color: '#f1f5f9', fontWeight: '600', marginBottom: '6px', fontSize: '11px' }}>
          Vector Engine Specs
        </div>
        <div>• Embeddings: 768-dim (Qwen3)</div>
        <div>• Routing: Nemotron-3 Nano</div>
        <div>• Index: pgvector HNSW</div>
      </div>
    </aside>
  )
}
