import React from 'react'
import CreateDomainModal from './timeline/CreateDomainModal'

const NAV_ITEMS = [
  { key: 'timeline', icon: '▦', label: 'Timeline', sub: 'Tasks & deadlines' },
  { key: 'compass', icon: '🧭', label: 'Compass', sub: 'Assistant & planner' },
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
  onOpenTelemetry,
  customDomains = [],
  onDomainCreated,
  onDomainDeleted,
  theme = 'light',
  onToggleTheme,
  mobileOpen = false,
  onCloseMobile,
}) {
  const [showCreateDomainModal, setShowCreateDomainModal] = React.useState(false)
  const [confirmDeleteKey, setConfirmDeleteKey] = React.useState(null)
  const [isCollapsed, setIsCollapsed] = React.useState(() => {
    try {
      return localStorage.getItem('compass.sidebar.collapsed') === 'true'
    } catch {
      /* ignore storage access error */
      return false
    }
  })

  const toggleCollapsed = () => {
    setIsCollapsed(prev => {
      const next = !prev
      try {
        localStorage.setItem('compass.sidebar.collapsed', String(next))
      } catch {
        /* ignore storage access error */
      }
      return next
    })
  }

  const isOnline = backendStatus.toLowerCase().includes('neon') || backendStatus.toLowerCase().includes('live')
  const totalActive = Object.values(domainCounts || {}).reduce((sum, n) => sum + (typeof n === 'number' ? n : 0), 0)

  const baseDomains = [
    { key: 'hackathon', label: 'Hackathon', icon: '🚀', color: '#fbbf24' },
    { key: 'coursework', label: 'Coursework', icon: '📚', color: '#60a5fa' },
    { key: 'code', label: 'Code', icon: '💻', color: '#34d399' },
    { key: 'general', label: 'General', icon: '🌐', color: '#94a3b8' },
    { key: 'other', label: 'Other', icon: '🏷️', color: '#a78bfa' },
  ]

  // Combine user-created custom domains with any discovered domains in active tasks
  const allCustom = [...customDomains]
  Object.keys(domainCounts || {}).forEach(k => {
    if (!baseDomains.some(b => b.key === k) && !allCustom.some(c => c.key === k)) {
      if ((domainCounts[k] || 0) > 0 || activeDomain === k) {
        allCustom.push({
          key: k,
          label: k.charAt(0).toUpperCase() + k.slice(1),
          icon: '🏷️',
          color: '#c084fc'
        })
      }
    }
  })

  const displayDomains = [...baseDomains, ...allCustom]

  return (
    <aside
      className={`compass-sidebar ${isCollapsed ? 'sidebar-collapsed' : 'sidebar-expanded'} ${mobileOpen ? 'mobile-open' : ''}`}
      style={{
        width: isCollapsed ? '68px' : '260px',
        minWidth: isCollapsed ? '68px' : '240px',
        maxWidth: isCollapsed ? '68px' : '280px',
        flexShrink: 0,
        borderRight: '1px solid var(--border)',
        background: 'var(--bg-sidebar)',
        display: 'flex',
        flexDirection: 'column',
        padding: isCollapsed ? '20px 8px' : '22px 16px',
        height: '100vh',
        overflowY: 'auto',
        overflowX: 'hidden',
        boxSizing: 'border-box',
      }}
    >
      {/* Brand Header */}
      {isCollapsed ? (
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '8px', marginBottom: '20px', userSelect: 'none' }}>
          <div
            id="sidebar-brand-header"
            onClick={() => { onSelectTab('timeline'); if (onSelectDomain) onSelectDomain('all') }}
            title="Compass Workspace — Click to return to default Timeline Feed"
            style={{ width: '38px', height: '38px', borderRadius: '10px', background: 'var(--brand)', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '18px', cursor: 'pointer', boxShadow: '0 4px 12px rgba(245, 166, 35, 0.25)', flexShrink: 0, transition: 'opacity 0.15s ease' }}
            onMouseEnter={e => (e.currentTarget.style.opacity = '0.85')}
            onMouseLeave={e => (e.currentTarget.style.opacity = '1')}
          >
            🧭
          </div>
          <button
            id="sidebar-collapse-toggle"
            onClick={toggleCollapsed}
            title="Expand sidebar"
            aria-label="Expand sidebar"
            style={{ background: 'rgba(255, 255, 255, 0.04)', border: '1px solid rgba(255, 255, 255, 0.08)', borderRadius: '6px', color: 'var(--text-muted)', cursor: 'pointer', width: '28px', height: '24px', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '15px', lineHeight: 1, padding: 0, transition: 'all 0.15s ease' }}
            onMouseEnter={e => { e.currentTarget.style.color = 'var(--text-on-dark)'; e.currentTarget.style.background = 'rgba(255, 255, 255, 0.08)'; e.currentTarget.style.borderColor = 'rgba(255, 255, 255, 0.2)' }}
            onMouseLeave={e => { e.currentTarget.style.color = 'var(--text-muted)'; e.currentTarget.style.background = 'rgba(255, 255, 255, 0.04)'; e.currentTarget.style.borderColor = 'rgba(255, 255, 255, 0.08)' }}
          >
            ›
          </button>
        </div>
      ) : (
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '24px', padding: '0 4px', userSelect: 'none' }}>
          <div
            id="sidebar-brand-header"
            onClick={() => {
              onSelectTab('timeline')
              if (onSelectDomain) onSelectDomain('all')
              if (onCloseMobile) onCloseMobile()
            }}
            style={{ display: 'flex', alignItems: 'center', gap: '12px', cursor: 'pointer', transition: 'opacity 0.15s ease', minWidth: 0 }}
            onMouseEnter={e => (e.currentTarget.style.opacity = '0.85')}
            onMouseLeave={e => (e.currentTarget.style.opacity = '1')}
            title="Compass Workspace — Click to return to default Timeline Feed"
          >
            <div style={{ width: '38px', height: '38px', borderRadius: '10px', background: 'var(--brand)', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '18px', flexShrink: 0, boxShadow: '0 4px 12px rgba(245, 166, 35, 0.25)' }}>
              🧭
            </div>
            <div>
              <h1 style={{ fontSize: '16px', fontWeight: '800', letterSpacing: '-0.3px', color: 'var(--text-on-dark)', margin: 0 }}>Compass</h1>
              <p style={{ fontSize: '10.5px', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.08em', fontWeight: '600', margin: 0 }}>Workspace</p>
            </div>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            {onCloseMobile && (
              <button
                id="mobile-drawer-close"
                className="mobile-close-btn"
                onClick={onCloseMobile}
                title="Close sidebar"
                aria-label="Close navigation drawer"
                style={{
                  background: 'rgba(255, 255, 255, 0.08)',
                  border: 'none',
                  borderRadius: '8px',
                  color: 'var(--text-on-dark)',
                  cursor: 'pointer',
                  width: '30px',
                  height: '30px',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  fontSize: '15px',
                  lineHeight: 1,
                  flexShrink: 0,
                }}
              >
                ✕
              </button>
            )}
            <button
              id="sidebar-collapse-toggle"
              onClick={toggleCollapsed}
              title="Collapse sidebar"
              aria-label="Collapse sidebar"
              style={{ background: 'transparent', border: '1px solid rgba(255, 255, 255, 0.08)', borderRadius: '6px', color: 'var(--text-muted)', cursor: 'pointer', width: '26px', height: '26px', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '15px', lineHeight: 1, padding: 0, transition: 'all 0.15s ease', flexShrink: 0 }}
              onMouseEnter={e => { e.currentTarget.style.color = 'var(--text-on-dark)'; e.currentTarget.style.background = 'rgba(255, 255, 255, 0.08)'; e.currentTarget.style.borderColor = 'rgba(255, 255, 255, 0.2)' }}
              onMouseLeave={e => { e.currentTarget.style.color = 'var(--text-muted)'; e.currentTarget.style.background = 'transparent'; e.currentTarget.style.borderColor = 'rgba(255, 255, 255, 0.08)' }}
            >
              ‹
            </button>
          </div>
        </div>
      )}

      {/* Navigation */}
      <div style={{ marginBottom: isCollapsed ? '16px' : '24px' }}>
        {!isCollapsed && (
          <p style={{ fontSize: '10px', textTransform: 'uppercase', letterSpacing: '0.08em', color: 'var(--text-muted)', fontWeight: '700', marginBottom: '10px', padding: '0 4px' }}>
            Navigation
          </p>
        )}
        {NAV_ITEMS.map(item => {
          const isActive =
            item.key === 'timeline'
              ? activeTab === 'timeline' && activeDomain === 'all'
              : item.key === 'compass'
              ? activeTab === 'compass' || activeTab === 'assistant' || activeTab === 'planner' || activeTab === 'agent'
              : activeTab === item.key
          return (
            <button
              key={item.key}
              id={`sidebar-tab-${item.key}`}
              onClick={() => {
                onSelectTab(item.key)
                if (onCloseMobile) onCloseMobile()
              }}
              className={`nav-item ${isActive ? 'active' : ''}`}
              title={item.label}
              style={isCollapsed ? { justifyContent: 'center', padding: '8px 0', width: '100%', gap: 0 } : undefined}
            >
              <span className="nav-icon">{item.icon}</span>
              {!isCollapsed && (
                <span>
                  <div style={{ fontSize: '13.5px', fontWeight: '700', color: isActive ? 'var(--text-on-dark)' : 'inherit' }}>
                    {item.label}
                  </div>
                  <div style={{ fontSize: '11px', opacity: 0.75 }}>{item.sub}</div>
                </span>
              )}
            </button>
          )
        })}
      </div>

      {/* Domain Isolation Metrics */}
      <div style={{ marginBottom: 'auto' }}>
        {!isCollapsed && (
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '10px', padding: '0 4px' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
              <p style={{ fontSize: '10px', textTransform: 'uppercase', letterSpacing: '0.08em', color: 'var(--text-muted)', fontWeight: '700', margin: 0 }}>
                Context Domains
              </p>
              <button
                id="btn-add-domain"
                onClick={() => setShowCreateDomainModal(true)}
                title="Add domain"
                aria-label="Add domain"
                style={{
                  background: 'transparent',
                  border: 'none',
                  color: 'var(--text-muted)',
                  cursor: 'pointer',
                  fontSize: '14px',
                  lineHeight: 1,
                  padding: '4px 6px',
                  borderRadius: '4px',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  transition: 'all 0.15s ease',
                  minWidth: '28px',
                  minHeight: '28px',
                }}
                onMouseEnter={e => {
                  e.currentTarget.style.color = 'var(--text-on-dark)'
                  e.currentTarget.style.background = 'rgba(255, 255, 255, 0.08)'
                }}
                onMouseLeave={e => {
                  e.currentTarget.style.color = 'var(--text-muted)'
                  e.currentTarget.style.background = 'transparent'
                }}
              >
                +
              </button>
            </div>
            {activeDomain !== 'all' && (
              <span
                onClick={() => {
                  onSelectDomain('all')
                  if (onCloseMobile) onCloseMobile()
                }}
                style={{ fontSize: '10px', color: 'var(--brand)', cursor: 'pointer', fontWeight: '700', padding: '2px 4px' }}
              >
                Reset
              </span>
            )}
          </div>
        )}

        {displayDomains.map(dom => {
          const isCustom = !baseDomains.some(b => b.key === dom.key)
          const isSelected = activeTab === 'timeline' && activeDomain === dom.key
          return (
            <div
              key={dom.key}
              id={`sidebar-domain-${dom.key}`}
              onClick={() => {
                onSelectDomain(dom.key)
                if (onCloseMobile) onCloseMobile()
              }}
              title={isCollapsed ? `${dom.label} (${domainCounts[dom.key] ?? 0})` : dom.label}
              style={{
                padding: isCollapsed ? '6px 0' : '8px 10px',
                borderRadius: '10px',
                marginBottom: '4px',
                cursor: 'pointer',
                display: 'flex',
                justifyContent: isCollapsed ? 'center' : 'space-between',
                alignItems: 'center',
                background: isSelected ? 'var(--bg-sidebar-active)' : 'transparent',
                transition: 'background 0.15s ease',
                width: '100%',
                boxSizing: 'border-box',
                minHeight: '38px',
              }}
              onMouseEnter={e => {
                if (!isSelected) e.currentTarget.style.background = 'rgba(255, 255, 255, 0.05)'
              }}
              onMouseLeave={e => {
                if (!isSelected) e.currentTarget.style.background = 'transparent'
              }}
            >
              {isCollapsed ? (
                <span style={{ fontSize: '16px', width: '32px', height: '32px', display: 'flex', alignItems: 'center', justifyContent: 'center', borderRadius: '8px', background: isSelected ? 'rgba(255, 255, 255, 0.08)' : 'transparent' }}>
                  {dom.icon}
                </span>
              ) : (
                <>
                  <span style={{ fontSize: '13px', color: isSelected ? 'var(--text-on-dark)' : 'var(--text-secondary)', fontWeight: '600', display: 'flex', alignItems: 'center', gap: '8px', minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    <span>{dom.icon}</span>
                    <span style={{ overflow: 'hidden', textOverflow: 'ellipsis' }}>{dom.label}</span>
                  </span>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '4px', flexShrink: 0 }}>
                    {isCustom && confirmDeleteKey === dom.key ? (
                      <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }} onClick={e => e.stopPropagation()}>
                        <span style={{ fontSize: '10px', color: '#f87171', fontWeight: '700' }}>Del?</span>
                        <button
                          id={`btn-confirm-delete-domain-${dom.key}`}
                          onClick={(e) => {
                            e.stopPropagation()
                            if (onDomainDeleted) onDomainDeleted(dom.key)
                            setConfirmDeleteKey(null)
                          }}
                          style={{ background: '#ef4444', border: 'none', color: '#fff', borderRadius: '4px', padding: '2px 5px', fontSize: '10px', cursor: 'pointer', fontWeight: '700' }}
                        >
                          Yes
                        </button>
                        <button
                          onClick={(e) => {
                            e.stopPropagation()
                            setConfirmDeleteKey(null)
                          }}
                          style={{ background: 'transparent', border: '1px solid rgba(255,255,255,0.2)', color: 'var(--text-muted)', borderRadius: '4px', padding: '2px 4px', fontSize: '10px', cursor: 'pointer' }}
                        >
                          No
                        </button>
                      </div>
                    ) : (
                      <>
                        <span style={{ padding: '2px 7px', borderRadius: '20px', fontSize: '10.5px', fontWeight: '700', background: 'rgba(255, 255, 255, 0.08)', color: dom.color }}>
                          {domainCounts[dom.key] ?? 0}
                        </span>
                        {isCustom && (
                          <button
                            id={`btn-remove-domain-${dom.key}`}
                            onClick={(e) => {
                              e.stopPropagation()
                              setConfirmDeleteKey(dom.key)
                            }}
                            title={`Remove ${dom.label} domain`}
                            aria-label={`Remove ${dom.label} domain`}
                            style={{ background: 'transparent', border: 'none', color: 'var(--text-muted)', cursor: 'pointer', fontSize: '12px', lineHeight: 1, padding: '2px 4px', borderRadius: '4px', display: 'inline-flex', alignItems: 'center', justifyContent: 'center', opacity: 0.6, transition: 'all 0.15s ease' }}
                            onMouseEnter={e => {
                              e.currentTarget.style.color = '#f87171'
                              e.currentTarget.style.opacity = '1'
                            }}
                            onMouseLeave={e => {
                              e.currentTarget.style.color = 'var(--text-muted)'
                              e.currentTarget.style.opacity = '0.6'
                            }}
                          >
                            ✕
                          </button>
                        )}
                      </>
                    )}
                  </div>
                </>
              )}
            </div>
          )
        })}

        {isCollapsed && (
          <div style={{ display: 'flex', justifyContent: 'center', margin: '4px 0 6px' }}>
            <button
              id="btn-add-domain-collapsed"
              onClick={() => setShowCreateDomainModal(true)}
              title="Add domain"
              aria-label="Add domain"
              style={{
                background: 'transparent',
                border: '1px dashed rgba(255, 255, 255, 0.18)',
                borderRadius: '8px',
                color: 'var(--text-muted)',
                cursor: 'pointer',
                width: '32px',
                height: '32px',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                fontSize: '15px',
                lineHeight: 1,
                transition: 'all 0.15s ease',
              }}
              onMouseEnter={e => {
                e.currentTarget.style.color = 'var(--text-on-dark)'
                e.currentTarget.style.borderColor = 'rgba(255, 255, 255, 0.35)'
                e.currentTarget.style.background = 'rgba(255, 255, 255, 0.06)'
              }}
              onMouseLeave={e => {
                e.currentTarget.style.color = 'var(--text-muted)'
                e.currentTarget.style.borderColor = 'rgba(255, 255, 255, 0.18)'
                e.currentTarget.style.background = 'transparent'
              }}
            >
              +
            </button>
          </div>
        )}
      </div>

      {/* Live status card — replaces fake mock with real backend status */}
      {isCollapsed ? (
        <div
          id="sidebar-specs-card"
          onClick={() => onOpenTelemetry && onOpenTelemetry()}
          title={isOnline ? `${totalActive} tasks synced — ${backendStatus}` : `Reconnecting — ${backendStatus}`}
          style={{
            padding: '10px 0',
            borderRadius: '10px',
            background: 'rgba(255, 255, 255, 0.04)',
            border: '1px solid rgba(255, 255, 255, 0.06)',
            marginTop: '16px',
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            justifyContent: 'center',
            cursor: onOpenTelemetry ? 'pointer' : 'default',
            gap: '6px',
            transition: 'background 0.15s ease',
            width: '100%',
            boxSizing: 'border-box',
          }}
          onMouseEnter={e => e.currentTarget.style.background = 'rgba(255, 255, 255, 0.08)'}
          onMouseLeave={e => e.currentTarget.style.background = 'rgba(255, 255, 255, 0.04)'}
        >
          <div style={{
            width: '8px',
            height: '8px',
            borderRadius: '50%',
            background: isOnline ? '#34d399' : '#f5a623',
            boxShadow: isOnline ? '0 0 8px rgba(52, 211, 153, 0.4)' : '0 0 8px rgba(245, 166, 35, 0.4)',
            flexShrink: 0,
          }} />
          {usageBadge && (
            <span style={{ fontSize: '11px', opacity: 0.85 }}>📊</span>
          )}
        </div>
      ) : (
        <div style={{
          padding: '13px 14px',
          borderRadius: '12px',
          background: 'rgba(255, 255, 255, 0.04)',
          border: '1px solid rgba(255, 255, 255, 0.06)',
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
            <div
              id="sidebar-usage-badge"
              className="mono"
              onClick={() => onOpenTelemetry && onOpenTelemetry()}
              style={{
                fontSize: '10.5px',
                color: 'var(--brand, #fbbf24)',
                padding: '6px 10px',
                marginTop: '8px',
                borderRadius: '7px',
                background: 'rgba(245, 166, 35, 0.08)',
                border: '1px solid rgba(245, 166, 35, 0.22)',
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                transition: 'all 0.15s ease',
              }}
              onMouseEnter={e => e.currentTarget.style.background = 'rgba(245, 166, 35, 0.16)'}
              onMouseLeave={e => e.currentTarget.style.background = 'rgba(245, 166, 35, 0.08)'}
              title="Click to inspect live Nebius Token Factory & NVIDIA telemetry"
            >
              <span>{usageBadge}</span>
              <span style={{ fontSize: '10px', opacity: 0.85 }}>📊</span>
            </div>
          )}
        </div>
      )}

      {/* Theme Toggle Control */}
      {onToggleTheme && (
        isCollapsed ? (
          <button
            id="sidebar-theme-toggle"
            type="button"
            role="switch"
            aria-checked={theme === 'dark'}
            aria-label={`Switch to ${theme === 'dark' ? 'Light' : 'Dark'} Mode`}
            title={`Switch to ${theme === 'dark' ? 'Light' : 'Dark'} Mode`}
            onClick={onToggleTheme}
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              padding: '10px 0',
              borderRadius: '10px',
              background: theme === 'dark' ? 'rgba(245, 166, 35, 0.12)' : 'rgba(255, 255, 255, 0.04)',
              border: `1px solid ${theme === 'dark' ? 'rgba(245, 166, 35, 0.3)' : 'rgba(255, 255, 255, 0.08)'}`,
              cursor: 'pointer',
              marginTop: '12px',
              transition: 'all 0.15s ease',
              width: '100%',
              boxSizing: 'border-box',
              fontSize: '15px',
              color: 'var(--text-on-dark)',
            }}
            onMouseEnter={e => {
              e.currentTarget.style.background = theme === 'dark' ? 'rgba(245, 166, 35, 0.22)' : 'rgba(255, 255, 255, 0.08)'
              e.currentTarget.style.borderColor = theme === 'dark' ? 'rgba(245, 166, 35, 0.45)' : 'rgba(255, 255, 255, 0.18)'
            }}
            onMouseLeave={e => {
              e.currentTarget.style.background = theme === 'dark' ? 'rgba(245, 166, 35, 0.12)' : 'rgba(255, 255, 255, 0.04)'
              e.currentTarget.style.borderColor = theme === 'dark' ? 'rgba(245, 166, 35, 0.3)' : 'rgba(255, 255, 255, 0.08)'
            }}
          >
            <span>{theme === 'dark' ? '🌙' : '☀️'}</span>
          </button>
        ) : (
          <button
            id="sidebar-theme-toggle"
            type="button"
            role="switch"
            aria-checked={theme === 'dark'}
            aria-label={`Switch to ${theme === 'dark' ? 'Light' : 'Dark'} Mode`}
            onClick={onToggleTheme}
            style={{
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              padding: '9px 12px',
              borderRadius: '10px',
              background: theme === 'dark' ? 'rgba(245, 166, 35, 0.12)' : 'rgba(255, 255, 255, 0.04)',
              border: `1px solid ${theme === 'dark' ? 'rgba(245, 166, 35, 0.3)' : 'rgba(255, 255, 255, 0.08)'}`,
              cursor: 'pointer',
              marginTop: '12px',
              transition: 'all 0.15s ease',
              color: 'var(--text-on-dark)',
              fontSize: '12.5px',
              fontWeight: '600',
              width: '100%',
              boxSizing: 'border-box',
            }}
            onMouseEnter={e => {
              e.currentTarget.style.background = theme === 'dark' ? 'rgba(245, 166, 35, 0.22)' : 'rgba(255, 255, 255, 0.08)'
              e.currentTarget.style.borderColor = theme === 'dark' ? 'rgba(245, 166, 35, 0.45)' : 'rgba(255, 255, 255, 0.18)'
            }}
            onMouseLeave={e => {
              e.currentTarget.style.background = theme === 'dark' ? 'rgba(245, 166, 35, 0.12)' : 'rgba(255, 255, 255, 0.04)'
              e.currentTarget.style.borderColor = theme === 'dark' ? 'rgba(245, 166, 35, 0.3)' : 'rgba(255, 255, 255, 0.08)'
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <span style={{ fontSize: '14px', lineHeight: 1 }}>{theme === 'dark' ? '🌙' : '☀️'}</span>
              <span>{theme === 'dark' ? 'Dark Mode' : 'Light Mode'}</span>
            </div>
            <span style={{
              fontSize: '10px',
              padding: '2px 8px',
              borderRadius: '12px',
              background: theme === 'dark' ? 'rgba(245, 166, 35, 0.2)' : 'rgba(255, 255, 255, 0.08)',
              color: theme === 'dark' ? '#fbbf24' : 'var(--text-on-dark-muted)',
              fontWeight: '700',
              textTransform: 'uppercase',
              letterSpacing: '0.04em'
            }}>
              {theme === 'dark' ? 'Dark' : 'Light'}
            </span>
          </button>
        )
      )}

      {/* Account / Workspace Switcher */}
      {isCollapsed ? (
        <div
          id="sidebar-account-btn"
          onClick={() => onOpenAuth && onOpenAuth()}
          title={currentUser?.authenticated ? `Signed in as ${currentUser.email} — Click to switch` : 'Sign in / Account'}
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            padding: '10px 0',
            borderRadius: '10px',
            background: 'rgba(255, 255, 255, 0.04)',
            border: '1px solid rgba(255, 255, 255, 0.08)',
            cursor: 'pointer',
            marginTop: '10px',
            transition: 'all 0.15s ease',
            width: '100%',
            boxSizing: 'border-box',
          }}
          onMouseEnter={e => e.currentTarget.style.background = 'rgba(255, 255, 255, 0.08)'}
          onMouseLeave={e => e.currentTarget.style.background = 'rgba(255, 255, 255, 0.04)'}
        >
          <span style={{ fontSize: '15px' }}>👤</span>
        </div>
      ) : (
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
            marginTop: '10px',
            transition: 'all 0.15s ease'
          }}
          onMouseEnter={e => e.currentTarget.style.background = 'rgba(255, 255, 255, 0.08)'}
          onMouseLeave={e => e.currentTarget.style.background = 'rgba(255, 255, 255, 0.04)'}
          title="Manage Account & Google Calendar"
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', minWidth: 0 }}>
            <span style={{ fontSize: '13px' }}>👤</span>
            <div style={{ minWidth: 0 }}>
              <div style={{ fontSize: '12px', color: 'var(--text-on-dark)', fontWeight: '600', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
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
      )}

      <CreateDomainModal
        isOpen={showCreateDomainModal}
        onClose={() => setShowCreateDomainModal(false)}
        onCreated={(newDomain) => {
          if (onDomainCreated) onDomainCreated(newDomain)
          if (onSelectDomain) onSelectDomain(newDomain.key)
        }}
        onDeleted={onDomainDeleted}
        customDomains={customDomains}
        existingDomains={displayDomains}
      />
    </aside>
  )
}
