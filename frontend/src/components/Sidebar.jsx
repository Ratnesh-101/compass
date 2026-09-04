import React from 'react'

export default function Sidebar({
  activeDomain,
  onSelectDomain,
  domainCounts,
  backendStatus,
  activeTab,
  onSelectTab
}) {
  return (
    <aside style={{ width: '280px', borderRight: '1px solid #1e293b', background: '#0d131f', display: 'flex', flexDirection: 'column', padding: '24px 18px', height: '100vh' }}>
      {/* Brand */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '24px' }}>
        <div style={{ width: '34px', height: '34px', borderRadius: '8px', background: 'linear-gradient(135deg, #6366f1, #a855f7)', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '18px' }}>
          🧭
        </div>
        <div>
          <h1 style={{ fontSize: '18px', fontWeight: '700', letterSpacing: '-0.5px', color: '#f8fafc' }}>Compass</h1>
          <p style={{ fontSize: '11px', color: '#64748b' }}>Persistent AI Memory</p>
        </div>
      </div>

      {/* Backend Health Pill */}
      <div style={{ padding: '8px 12px', borderRadius: '8px', background: 'rgba(16, 185, 129, 0.1)', border: '1px solid rgba(16, 185, 129, 0.2)', marginBottom: '24px', display: 'flex', alignItems: 'center', gap: '8px' }}>
        <div style={{ width: '8px', height: '8px', borderRadius: '50%', background: '#10b981', boxShadow: '0 0 8px #10b981' }} />
        <span style={{ fontSize: '12px', color: '#34d399', fontWeight: '500' }}>{backendStatus}</span>
      </div>

      {/* Navigation Tabs */}
      <div style={{ marginBottom: '24px' }}>
        <p style={{ fontSize: '11px', textTransform: 'uppercase', letterSpacing: '0.05em', color: '#64748b', fontWeight: '600', marginBottom: '8px' }}>Views</p>
        <button
          onClick={() => onSelectTab('timeline')}
          style={{ width: '100%', textAlign: 'left', padding: '10px 14px', borderRadius: '8px', border: 'none', background: activeTab === 'timeline' ? '#1e293b' : 'transparent', color: activeTab === 'timeline' ? '#fff' : '#94a3b8', cursor: 'pointer', fontWeight: '500', marginBottom: '4px' }}>
          📅 Timeline View
        </button>
        <button
          onClick={() => onSelectTab('chat')}
          style={{ width: '100%', textAlign: 'left', padding: '10px 14px', borderRadius: '8px', border: 'none', background: activeTab === 'chat' ? '#1e293b' : 'transparent', color: activeTab === 'chat' ? '#fff' : '#94a3b8', cursor: 'pointer', fontWeight: '500' }}>
          💬 Assistant Chat
        </button>
      </div>

      {/* Domain Isolation Metrics */}
      <div style={{ marginBottom: 'auto' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '10px' }}>
          <p style={{ fontSize: '11px', textTransform: 'uppercase', letterSpacing: '0.05em', color: '#64748b', fontWeight: '600' }}>Domain Isolation</p>
          {activeDomain !== 'all' && (
            <span onClick={() => onSelectDomain('all')} style={{ fontSize: '11px', color: '#6366f1', cursor: 'pointer' }}>Reset</span>
          )}
        </div>

        <div
          onClick={() => onSelectDomain('hackathon')}
          style={{ padding: '10px 14px', borderRadius: '8px', marginBottom: '8px', cursor: 'pointer', display: 'flex', justifyContent: 'space-between', alignItems: 'center', background: activeDomain === 'hackathon' ? '#1e293b' : 'transparent', border: activeDomain === 'hackathon' ? '1px solid rgba(245, 158, 11, 0.4)' : '1px solid transparent' }}>
          <span style={{ fontSize: '13px', color: '#fbbf24' }}>🚀 Hackathon</span>
          <span className="badge-hackathon" style={{ padding: '2px 8px', borderRadius: '12px', fontSize: '11px', fontWeight: '600' }}>{domainCounts.hackathon}</span>
        </div>

        <div
          onClick={() => onSelectDomain('coursework')}
          style={{ padding: '10px 14px', borderRadius: '8px', marginBottom: '8px', cursor: 'pointer', display: 'flex', justifyContent: 'space-between', alignItems: 'center', background: activeDomain === 'coursework' ? '#1e293b' : 'transparent', border: activeDomain === 'coursework' ? '1px solid rgba(59, 130, 246, 0.4)' : '1px solid transparent' }}>
          <span style={{ fontSize: '13px', color: '#60a5fa' }}>📚 Coursework</span>
          <span className="badge-coursework" style={{ padding: '2px 8px', borderRadius: '12px', fontSize: '11px', fontWeight: '600' }}>{domainCounts.coursework}</span>
        </div>

        <div
          onClick={() => onSelectDomain('code')}
          style={{ padding: '10px 14px', borderRadius: '8px', marginBottom: '8px', cursor: 'pointer', display: 'flex', justifyContent: 'space-between', alignItems: 'center', background: activeDomain === 'code' ? '#1e293b' : 'transparent', border: activeDomain === 'code' ? '1px solid rgba(16, 185, 129, 0.4)' : '1px solid transparent' }}>
          <span style={{ fontSize: '13px', color: '#34d399' }}>💻 Code</span>
          <span className="badge-code" style={{ padding: '2px 8px', borderRadius: '12px', fontSize: '11px', fontWeight: '600' }}>{domainCounts.code}</span>
        </div>
      </div>

      {/* Technical Footprint Card */}
      <div style={{ padding: '14px', borderRadius: '8px', background: '#131c2e', border: '1px solid #1e293b', fontSize: '11px', color: '#94a3b8' }}>
        <div style={{ color: '#f1f5f9', fontWeight: '600', marginBottom: '6px' }}>Vector Engine Specs</div>
        <div>• Embeddings: 768-dim (Qwen3)</div>
        <div>• Routing: Nemotron-3 Nano</div>
        <div>• Index: pgvector HNSW</div>
      </div>
    </aside>
  )
}
