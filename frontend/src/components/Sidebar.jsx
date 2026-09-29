import React from 'react'

const NAV_ITEMS = [
  { key: 'timeline', icon: '▦', label: 'Timeline', sub: 'Tasks & deadlines' },
  { key: 'northstar', icon: '🧭', label: 'Northstar AI', sub: 'Copilot, planner & agents' },
  { key: 'calendar', icon: '🗓️', label: 'Schedule', sub: 'Calendar & Google sync' },
]

export default function Sidebar({
  activeDomain,
  onSelectDomain,
  domainCounts,
  backendStatus,
  activeTab,
  onSelectTab,
  usageBadge,
  currentUser,
  onOpenAuth,
}) {
  const isOnline = backendStatus.toLowerCase().includes('neon') || backendStatus.toLowerCase().includes('live')
  const totalActive = Object.values(domainCounts || {}).reduce((sum, n) => sum + (typeof n === 'number' ? n : 0), 0)

  const baseDomains = [
    { key: 'hackathon', label: 'Hackathon', icon: '🚀', color: '#fbbf24' },
    { key: 'coursework', label: 'Coursework', icon: '📚', color: '#60a5fa' },
    { key: 'code', label: 'Code', icon: '💻', color: '#34d399' },
    { key: 'general', label: 'General', icon: '🌐', color: '#94a3b8' },
    { key: 'other', label: 'Other', icon: '🏷️', color: '#a78bfa' },
  ]

  // Show any user-defined custom domains present in active tasks
  const extraDomains = Object.keys(domainCounts || {})
    .filter(k => !baseDomains.some(b => b.key === k) && ((domainCounts[k] || 0) > 0 || activeDomain === k))
    .map(k => ({
      key: k,
      label: k.charAt(0).toUpperCase() + k.slice(1),
      icon: '🏷️',
      color: '#c084fc'
    }))

  const displayDomains = [...baseDomains, ...extraDomains]

  return (
    <aside style={{
      width: '260px',
      minWidth: '240px',
      maxWidth: '280px',
      flexShrink: 0,
      borderRight: '1px solid var(--border)',
      background: 'var(--bg-sidebar)',
      display: 'flex',
      flexDirection: 'column',
      padding: '22px 16px',
      height: '100vh',
      overflowY: 'auto'
    }}>
      {/* Brand Header — clickable to return to default page (Timeline) */}
      <div
        id="sidebar-brand-header"
        onClick={() => {
          onSelectTab('timeline')
          if (onSelectDomain) onSelectDomain('all')
        }}
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: '12px',
          marginBottom: '24px',
          padding: '0 4px',
          cursor: 'pointer',
          userSelect: 'none',
          transition: 'opacity 0.15s ease',
        }}
        onMouseEnter={e => e.currentTarget.style.opacity = '0.85'}
        onMouseLeave={e => e.currentTarget.style.opacity = '1'}
        title="Compass Workspace — Click to return to default Timeline Feed"
      >
        <div style={{
          width: '38px',
          height: '38px',
          borderRadius: '10px',
          background: 'var(--brand)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          fontSize: '18px',
          flexShrink: 0,
          boxShadow: '0 4px 12px rgba(245, 166, 35, 0.25)'
        }}>
          🧭
        </div>
        <div>
          <h1 style={{ fontSize: '16px', fontWeight: '800', letterSpacing: '-0.3px', color: 'var(--text-on-dark)', margin: 0 }}>Compass</h1>
          <p style={{ fontSize: '10.5px', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.08em', fontWeight: '600', margin: 0 }}>Workspace</p>
        </div>
      </div>

      {/* Navigation */}
      <div style={{ marginBottom: '24px' }}>
        <p style={{ fontSize: '10px', textTransform: 'uppercase', letterSpacing: '0.08em', color: 'var(--text-muted)', fontWeight: '700', marginBottom: '10px', padding: '0 4px' }}>
          Navigation
        </p>
        {NAV_ITEMS.map(item => (
          <button
            key={item.key}
            id={`sidebar-tab-${item.key}`}
            onClick={() => onSelectTab(item.key)}
            className={`nav-item ${activeTab === item.key ? 'active' : ''}`}
          >
            <span className="nav-icon">{item.icon}</span>
            <span>
              <div style={{ fontSize: '13.5px', fontWeight: '700', color: activeTab === item.key ? 'var(--text-on-dark)' : 'inherit' }}>
                {item.label}
              </div>
              <div style={{ fontSize: '11px', opacity: 0.75 }}>{item.sub}</div>
            </span>
          </button>
        ))}
      </div>

      {/* Domain Isolation Metrics */}
      <div style={{ marginBottom: 'auto' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '10px', padding: '0 4px' }}>
          <p style={{ fontSize: '10px', textTransform: 'uppercase', letterSpacing: '0.08em', color: 'var(--text-muted)', fontWeight: '700' }}>
            Domains
          </p>
          {activeDomain !== 'all' && (
            <span onClick={() => onSelectDomain('all')} style={{ fontSize: '10px', color: 'var(--brand)', cursor: 'pointer', fontWeight: '700' }}>
              Reset
            </span>
          )}
        </div>

        {displayDomains.map(dom => (
          <div
            key={dom.key}
            onClick={() => onSelectDomain(dom.key)}
            style={{
              padding: '9px 12px',
              borderRadius: '10px',
              marginBottom: '4px',
              cursor: 'pointer',
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
              background: activeDomain === dom.key ? 'var(--bg-sidebar-active)' : 'transparent',
              transition: 'background 0.15s ease'
            }}>
            <span style={{ fontSize: '13px', color: activeDomain === dom.key ? 'var(--text-on-dark)' : 'var(--text-secondary)', fontWeight: '600', display: 'flex', alignItems: 'center', gap: '8px' }}>
              <span>{dom.icon}</span> {dom.label}
            </span>
            <span style={{
              padding: '2px 8px',
              borderRadius: '20px',
              fontSize: '10.5px',
              fontWeight: '700',
              background: 'rgba(255,255,255,0.08)',
              color: dom.color
            }}>
              {domainCounts[dom.key] ?? 0}
            </span>
          </div>
        ))}
      </div>

      {/* Live status card — replaces fake mock with real backend status */}
      <div style={{
        padding: '13px 14px',
        borderRadius: '12px',
        background: 'rgba(255,255,255,0.04)',
        border: '1px solid rgba(255,255,255,0.06)',
        marginTop: '16px'
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '4px' }}>
          <div style={{
            width: '7px',
            height: '7px',
            borderRadius: '50%',
            background: isOnline ? '#34d399' : '#f5a623',
            flexShrink: 0
          }} />
          <span style={{ fontSize: '12.5px', fontWeight: '700', color: 'var(--text-on-dark)' }}>
            {isOnline ? `${totalActive} tasks synced` : 'Reconnecting'}
          </span>
        </div>
        <div style={{ fontSize: '10.5px', color: 'var(--text-muted)', paddingLeft: '15px' }}>
          {backendStatus}
        </div>
        {usageBadge && (
          <div id="sidebar-usage-badge" className="mono" style={{
            fontSize: '10px', color: 'var(--text-muted)', paddingLeft: '15px',
            marginTop: '6px', paddingTop: '6px', borderTop: '1px solid rgba(255,255,255,0.06)'
          }}>
            {usageBadge}
          </div>
        )}
      </div>

      {/* Account / Workspace Switcher */}
      <div
        id="sidebar-account-btn"
        onClick={() => onOpenAuth && onOpenAuth()}
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '10px 12px',
          borderRadius: '10px',
          background: 'rgba(255, 255, 255, 0.04)',
          border: '1px solid rgba(255, 255, 255, 0.08)',
          cursor: 'pointer',
          marginTop: '12px',
          transition: 'all 0.15s ease'
        }}
        onMouseEnter={e => e.currentTarget.style.background = 'rgba(255, 255, 255, 0.08)'}
        onMouseLeave={e => e.currentTarget.style.background = 'rgba(255, 255, 255, 0.04)'}
        title="Manage Account & Google Calendar"
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', minWidth: 0 }}>
          <span style={{ fontSize: '13px' }}>👤</span>
          <div style={{ minWidth: 0 }}>
            <div style={{
              fontSize: '12px',
              color: 'var(--text-on-dark)',
              fontWeight: '600',
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              whiteSpace: 'nowrap'
            }}>
              {currentUser?.authenticated ? currentUser.email : 'Sign in / Account'}
            </div>
            <div style={{ fontSize: '10px', color: 'var(--text-muted)' }}>
              {currentUser?.calendar?.connected ? 'Google Calendar ✓' : 'Isolated Workspace'}
            </div>
          </div>
        </div>
        <span style={{ fontSize: '11px', color: 'var(--brand)', fontWeight: '700', flexShrink: 0, paddingLeft: '6px' }}>
          {currentUser?.authenticated ? 'Switch ▾' : 'Login ▾'}
        </span>
      </div>
    </aside>
  )
}
