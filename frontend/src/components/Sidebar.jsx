import React from 'react'
import { X, Zap } from 'lucide-react'
import CreateDomainModal from './timeline/CreateDomainModal'
import Logo from './Logo'
import { parseUsageBadge } from '../utils/usageBadgeParser'

// Re-export for convenience
export { parseUsageBadge } from '../utils/usageBadgeParser'

// Simple line icons (1.8 stroke, currentColor)
function NavIcon({ type }) {
  if (type === 'dashboard') {
    return (
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <rect width="7" height="9" x="3" y="3" rx="1" />
        <rect width="7" height="5" x="14" y="3" rx="1" />
        <rect width="7" height="9" x="14" y="12" rx="1" />
        <rect width="7" height="5" x="3" y="16" rx="1" />
      </svg>
    )
  }
  if (type === 'timeline') {
    return (
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <path d="M6 3v18" />
        <path d="M18 3v18" />
        <rect width="6" height="7" x="3" y="5" rx="1" />
        <rect width="6" height="5" x="15" y="5" rx="1" />
        <rect width="6" height="7" x="15" y="14" rx="1" />
      </svg>
    )
  }
  if (type === 'compass') {
    return <Logo size={18} alt="" />
  }
  if (type === 'calendar') {
    return (
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <rect width="18" height="18" x="3" y="4" rx="2" />
        <path d="M3 10h18" />
        <path d="M8 2v4" />
        <path d="M16 2v4" />
      </svg>
    )
  }
  if (type === 'career') {
    return (
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <circle cx="12" cy="12" r="10" />
        <circle cx="12" cy="12" r="6" />
        <circle cx="12" cy="12" r="2" />
      </svg>
    )
  }
  return null
}

const NAV_ITEMS = [
  { key: 'dashboard', type: 'dashboard', label: 'Dashboard', sub: 'Overview & metrics' },
  { key: 'timeline', type: 'timeline', label: 'Timeline', sub: 'Tasks & deadlines' },
  { key: 'compass', type: 'compass', label: 'Compass', sub: 'Assistant & planner' },
  { key: 'calendar', type: 'calendar', label: 'Schedule', sub: 'Calendar & Google sync' },
  { key: 'career', type: 'career', label: 'Career Copilot', sub: 'Radar, Resumes & Apps' },
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
  mobileOpen = false,
  onCloseMobile,
  onRetryConnection,
}) {
  const [showCreateDomainModal, setShowCreateDomainModal] = React.useState(false)
  const [confirmDeleteKey, setConfirmDeleteKey] = React.useState(null)
  const [isCollapsed, setIsCollapsed] = React.useState(() => {
    try {
      return localStorage.getItem('compass.sidebar.collapsed') === 'true'
    } catch {
      return false
    }
  })

  // Never collapse when opened as a mobile drawer
  const effectivelyCollapsed = isCollapsed && !mobileOpen

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

  const isOnline = backendStatus.toLowerCase().includes('neon') ||
    backendStatus.toLowerCase().includes('live') ||
    backendStatus.toLowerCase().includes('connected') ||
    backendStatus.toLowerCase().includes('ready')
  const totalActive = Object.values(domainCounts || {}).reduce((sum, n) => sum + (typeof n === 'number' ? n : 0), 0)

  // Step 3 Theme Domain Colors: hackathon #f5a623, coursework #2f64c8, code #1c8a62, general #6b7a86
  const baseDomains = [
    { key: 'hackathon', label: 'Hackathon', color: '#f5a623' },
    { key: 'coursework', label: 'Coursework', color: '#2f64c8' },
    { key: 'code', label: 'Code', color: '#1c8a62' },
    { key: 'general', label: 'General', color: '#6b7a86' },
    { key: 'other', label: 'Other', color: '#7e68b5' },
  ]

  // Combine user-created custom domains with any discovered domains in active tasks
  const allCustom = [...customDomains]
  Object.keys(domainCounts || {}).forEach(k => {
    if (!baseDomains.some(b => b.key === k) && !allCustom.some(c => c.key === k)) {
      if ((domainCounts[k] || 0) > 0 || activeDomain === k) {
        allCustom.push({
          key: k,
          label: k.charAt(0).toUpperCase() + k.slice(1),
          color: '#8b5cf6'
        })
      }
    }
  })

  const displayDomains = [...baseDomains, ...allCustom]

  return (
    <aside
      className={`compass-sidebar ${effectivelyCollapsed ? 'sidebar-collapsed' : 'sidebar-expanded'} ${mobileOpen ? 'mobile-open' : ''}`}
      style={{
        width: effectivelyCollapsed ? '68px' : '260px',
        minWidth: effectivelyCollapsed ? '68px' : '240px',
        maxWidth: effectivelyCollapsed ? '68px' : '280px',
        flexShrink: 0,
        borderRight: '1px solid var(--sidebar-divider)',
        background: 'var(--bg-sidebar)',
        display: 'flex',
        flexDirection: 'column',
        padding: effectivelyCollapsed ? '18px 8px' : '18px 14px',
        height: '100vh',
        overflowY: 'auto',
        overflowX: 'hidden',
        boxSizing: 'border-box',
        transition: 'width 0.2s cubic-bezier(0.16, 1, 0.3, 1), min-width 0.2s cubic-bezier(0.16, 1, 0.3, 1), padding 0.2s ease',
      }}
    >
      {/* Brand Header & Toggle Row */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: effectivelyCollapsed ? 'center' : 'space-between',
          minHeight: '40px',
          height: '40px',
          marginBottom: '20px',
          padding: 0,
          userSelect: 'none',
          position: 'relative',
          width: '100%',
        }}
      >
        {effectivelyCollapsed ? (
          <button
            id="sidebar-collapse-toggle"
            onClick={toggleCollapsed}
            title="Expand sidebar"
            aria-label="Expand sidebar"
            style={{
              background: 'transparent',
              border: '1px solid var(--sidebar-divider)',
              borderRadius: '6px',
              color: 'var(--sidebar-text)',
              cursor: 'pointer',
              width: '28px',
              height: '28px',
              minWidth: '28px',
              minHeight: '28px',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              padding: 0,
              transition: 'all 0.15s ease',
              flexShrink: 0,
            }}
            onMouseEnter={e => {
              e.currentTarget.style.color = '#ffffff'
              e.currentTarget.style.background = 'var(--sidebar-hover)'
            }}
            onMouseLeave={e => {
              e.currentTarget.style.color = 'var(--sidebar-text)'
              e.currentTarget.style.background = 'transparent'
            }}
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <polyline points="9 18 15 12 9 6" />
            </svg>
          </button>
        ) : (
          <>
            <div
              id="sidebar-brand-header"
              onClick={() => {
                onSelectTab('dashboard')
                if (onCloseMobile) onCloseMobile()
              }}
              style={{ display: 'flex', alignItems: 'center', gap: '12px', cursor: 'pointer', transition: 'opacity 0.15s ease', minWidth: 0 }}
              onMouseEnter={e => (e.currentTarget.style.opacity = '0.9')}
              onMouseLeave={e => (e.currentTarget.style.opacity = '1')}
              title="Compass Workspace: Click to return to Dashboard"
            >
              <Logo size={36} alt="" />
              <div>
                <h1 style={{ fontSize: '15px', fontWeight: '600', letterSpacing: '-0.2px', color: 'var(--sidebar-active-text)', margin: 0, lineHeight: 1.2 }}>Compass</h1>
                <p style={{ fontSize: '11px', color: 'var(--sidebar-text)', textTransform: 'uppercase', letterSpacing: '0.06em', fontWeight: '500', margin: 0, opacity: 0.8 }}>Workspace</p>
              </div>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              {onCloseMobile && (
                <button
                  id="mobile-drawer-close"
                  className="mobile-close-btn btn-touch-target"
                  onClick={onCloseMobile}
                  title="Close sidebar"
                  aria-label="Close navigation drawer"
                  style={{
                    background: 'transparent',
                    border: '1px solid var(--sidebar-divider)',
                    borderRadius: '6px',
                    color: 'var(--sidebar-text)',
                    cursor: 'pointer',
                    width: '44px',
                    height: '44px',
                    minWidth: '44px',
                    minHeight: '44px',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    flexShrink: 0,
                  }}
                >
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                    <path d="M18 6 6 18" />
                    <path d="m6 6 12 12" />
                  </svg>
                </button>
              )}
              <button
                id="sidebar-collapse-toggle"
                onClick={toggleCollapsed}
                title="Collapse sidebar"
                aria-label="Collapse sidebar"
                style={{
                  background: 'transparent',
                  border: '1px solid var(--sidebar-divider)',
                  borderRadius: '6px',
                  color: 'var(--sidebar-text)',
                  cursor: 'pointer',
                  width: '28px',
                  height: '28px',
                  minWidth: '28px',
                  minHeight: '28px',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  padding: 0,
                  transition: 'all 0.15s ease',
                  flexShrink: 0
                }}
                onMouseEnter={e => {
                  e.currentTarget.style.color = '#ffffff'
                  e.currentTarget.style.background = 'var(--sidebar-hover)'
                }}
                onMouseLeave={e => {
                  e.currentTarget.style.color = 'var(--sidebar-text)'
                  e.currentTarget.style.background = 'transparent'
                }}
              >
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                  <polyline points="15 18 9 12 15 6" />
                </svg>
              </button>
            </div>
          </>
        )}
      </div>

      {/* Navigation */}
      <div style={{ marginBottom: effectivelyCollapsed ? '16px' : '22px' }}>
        {!effectivelyCollapsed && (
          <p style={{ fontSize: '11px', textTransform: 'uppercase', letterSpacing: '0.06em', color: 'var(--sidebar-text)', opacity: 0.75, fontWeight: '600', marginBottom: '8px', padding: '0 4px' }}>
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

          if (effectivelyCollapsed) {
            return (
              <button
                key={item.key}
                id={`sidebar-tab-${item.key}`}
                onClick={() => {
                  onSelectTab(item.key)
                  if (onCloseMobile) onCloseMobile()
                }}
                className={`nav-item-collapsed ${isActive ? 'active' : ''}`}
                title={`${item.label}: ${item.sub}`}
                aria-label={`${item.label}: ${item.sub}`}
                style={{
                  width: '44px',
                  height: '44px',
                  minWidth: '44px',
                  minHeight: '44px',
                  margin: '0 auto 6px',
                  padding: 0,
                  borderRadius: '6px',
                  border: 'none',
                  cursor: 'pointer',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  background: isActive ? 'var(--sidebar-active)' : 'transparent',
                  color: isActive ? '#ffffff' : 'var(--sidebar-text)',
                  transition: 'all 0.15s ease',
                }}
                onMouseEnter={e => {
                  if (!isActive) {
                    e.currentTarget.style.background = 'var(--sidebar-hover)'
                    e.currentTarget.style.color = '#ffffff'
                  }
                }}
                onMouseLeave={e => {
                  if (!isActive) {
                    e.currentTarget.style.background = 'transparent'
                    e.currentTarget.style.color = 'var(--sidebar-text)'
                  }
                }}
              >
                <NavIcon type={item.type} />
              </button>
            )
          }

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
              style={{
                borderRadius: '6px',
                minHeight: '44px',
                padding: '0 10px',
                background: isActive ? 'var(--sidebar-active)' : 'transparent',
                color: isActive ? '#ffffff' : 'var(--sidebar-text)',
                border: 'none',
              }}
            >
              <span className="nav-icon" style={{ color: isActive ? '#ffffff' : 'var(--sidebar-text)' }}>
                <NavIcon type={item.type} />
              </span>
              <span>
                <div style={{ fontSize: '13.5px', fontWeight: isActive ? '600' : '500', color: isActive ? '#ffffff' : 'inherit' }}>
                  {item.label}
                </div>
                <div style={{ fontSize: '11px', opacity: 0.7 }}>{item.sub}</div>
              </span>
            </button>
          )
        })}
      </div>

      {/* Domain Isolation Metrics */}
      <div style={{ marginBottom: 'auto' }}>
        {!effectivelyCollapsed && (
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px', padding: '0 4px' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
              <p style={{ fontSize: '11px', textTransform: 'uppercase', letterSpacing: '0.06em', color: 'var(--sidebar-text)', opacity: 0.75, fontWeight: '600', margin: 0 }}>
                Context Domains
              </p>
              <button
                id="btn-add-domain"
                onClick={() => setShowCreateDomainModal(true)}
                title="Add domain"
                aria-label="Add domain"
                style={{
                  background: 'transparent',
                  border: '1px solid var(--sidebar-divider)',
                  color: 'var(--sidebar-text)',
                  cursor: 'pointer',
                  padding: 0,
                  borderRadius: '6px',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  transition: 'all 0.15s ease',
                  width: '24px',
                  height: '24px',
                  minWidth: '24px',
                  minHeight: '24px',
                }}
                onMouseEnter={e => {
                  e.currentTarget.style.color = '#ffffff'
                  e.currentTarget.style.background = 'var(--sidebar-hover)'
                }}
                onMouseLeave={e => {
                  e.currentTarget.style.color = 'var(--sidebar-text)'
                  e.currentTarget.style.background = 'transparent'
                }}
              >
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                  <path d="M5 12h14" />
                  <path d="M12 5v14" />
                </svg>
              </button>
            </div>
            {activeDomain !== 'all' && (
              <span
                onClick={() => {
                  onSelectDomain('all')
                  if (onCloseMobile) onCloseMobile()
                }}
                style={{ fontSize: '11px', color: 'var(--brand)', cursor: 'pointer', fontWeight: '600', padding: '2px 4px' }}
              >
                Reset
              </span>
            )}
          </div>
        )}

        {displayDomains.map(dom => {
          const isCustom = !baseDomains.some(b => b.key === dom.key)
          const isSelected = activeTab === 'timeline' && activeDomain === dom.key
          const count = domainCounts[dom.key] ?? 0

          if (effectivelyCollapsed) {
            return (
              <div
                key={dom.key}
                id={`sidebar-domain-${dom.key}`}
                onClick={() => {
                  onSelectDomain(dom.key)
                  if (onCloseMobile) onCloseMobile()
                }}
                title={`${dom.label} (${count} tasks)`}
                aria-label={`${dom.label}: ${count} tasks`}
                style={{
                  width: '44px',
                  height: '44px',
                  minWidth: '44px',
                  minHeight: '44px',
                  margin: '0 auto 4px',
                  padding: 0,
                  borderRadius: '6px',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  background: isSelected ? 'var(--sidebar-active)' : 'transparent',
                  border: isSelected ? '1px solid var(--sidebar-divider)' : '1px solid transparent',
                  cursor: 'pointer',
                  position: 'relative',
                  transition: 'all 0.15s ease',
                }}
                onMouseEnter={e => {
                  if (!isSelected) e.currentTarget.style.background = 'var(--sidebar-hover)'
                }}
                onMouseLeave={e => {
                  if (!isSelected) e.currentTarget.style.background = 'transparent'
                }}
              >
                {/* 8px rounded square swatch */}
                <span
                  style={{
                    width: '10px',
                    height: '10px',
                    borderRadius: '2px',
                    background: dom.color,
                  }}
                />
                {count > 0 && (
                  <span
                    style={{
                      position: 'absolute',
                      top: '6px',
                      right: '6px',
                      fontSize: '9px',
                      fontWeight: '600',
                      color: 'var(--sidebar-text)',
                      opacity: 0.85,
                    }}
                  >
                    {count}
                  </span>
                )}
              </div>
            )
          }

          return (
            <div
              key={dom.key}
              id={`sidebar-domain-${dom.key}`}
              onClick={() => {
                onSelectDomain(dom.key)
                if (onCloseMobile) onCloseMobile()
              }}
              title={dom.label}
              style={{
                padding: '0 10px',
                borderRadius: '6px',
                marginBottom: '4px',
                cursor: 'pointer',
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
                background: isSelected ? 'var(--sidebar-active)' : 'transparent',
                transition: 'background 0.15s ease',
                width: '100%',
                boxSizing: 'border-box',
                minHeight: '44px',
              }}
              onMouseEnter={e => {
                if (!isSelected) e.currentTarget.style.background = 'var(--sidebar-hover)'
              }}
              onMouseLeave={e => {
                if (!isSelected) e.currentTarget.style.background = 'transparent'
              }}
            >
              <span style={{ fontSize: '13px', color: isSelected ? '#ffffff' : 'var(--sidebar-text)', fontWeight: isSelected ? '600' : '500', display: 'flex', alignItems: 'center', gap: '8px', minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {/* Small 8px rounded square swatch */}
                <span
                  style={{
                    width: '8px',
                    height: '8px',
                    minWidth: '8px',
                    minHeight: '8px',
                    borderRadius: '2px',
                    background: dom.color,
                    display: 'inline-block',
                    flexShrink: 0,
                  }}
                />
                <span style={{ overflow: 'hidden', textOverflow: 'ellipsis' }}>{dom.label}</span>
              </span>
              <div style={{ display: 'flex', alignItems: 'center', gap: '4px', flexShrink: 0 }}>
                {isCustom && confirmDeleteKey === dom.key ? (
                  <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }} onClick={e => e.stopPropagation()}>
                    <span style={{ fontSize: '10px', color: '#f87171', fontWeight: '600' }}>Del?</span>
                    <button
                      id={`btn-confirm-delete-domain-${dom.key}`}
                      onClick={(e) => {
                        e.stopPropagation()
                        if (onDomainDeleted) onDomainDeleted(dom.key)
                        setConfirmDeleteKey(null)
                      }}
                      style={{ background: '#b91c1c', border: 'none', color: '#fff', borderRadius: '4px', padding: '2px 6px', fontSize: '11px', cursor: 'pointer', fontWeight: '600' }}
                    >
                      Yes
                    </button>
                    <button
                      onClick={(e) => {
                        e.stopPropagation()
                        setConfirmDeleteKey(null)
                      }}
                      style={{ background: 'transparent', border: '1px solid var(--sidebar-divider)', color: 'var(--sidebar-text)', borderRadius: '4px', padding: '2px 6px', fontSize: '11px', cursor: 'pointer' }}
                    >
                      No
                    </button>
                  </div>
                ) : (
                  <>
                    <span style={{ padding: '2px 6px', borderRadius: '4px', fontSize: '11px', fontWeight: '500', background: 'rgba(255, 255, 255, 0.08)', color: 'var(--sidebar-text)' }}>
                      {count}
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
                        style={{ background: 'transparent', border: 'none', color: 'var(--sidebar-text)', cursor: 'pointer', fontSize: '13px', lineHeight: 1, padding: '2px 4px', borderRadius: '4px', display: 'inline-flex', alignItems: 'center', justifyContent: 'center', opacity: 0.6, transition: 'all 0.15s ease' }}
                        onMouseEnter={e => {
                          e.currentTarget.style.color = '#f87171'
                          e.currentTarget.style.opacity = '1'
                        }}
                        onMouseLeave={e => {
                          e.currentTarget.style.color = 'var(--sidebar-text)'
                          e.currentTarget.style.opacity = '0.6'
                        }}
                      >
                        <X size={12} strokeWidth={1.8} />
                      </button>
                    )}
                  </>
                )}
              </div>
            </div>
          )
        })}

        {effectivelyCollapsed && (
          <div style={{ display: 'flex', justifyContent: 'center', margin: '4px 0 6px' }}>
            <button
              id="btn-add-domain-collapsed"
              onClick={() => setShowCreateDomainModal(true)}
              title="Add domain"
              aria-label="Add domain"
              style={{
                background: 'transparent',
                border: '1px dashed var(--sidebar-divider)',
                borderRadius: '6px',
                color: 'var(--sidebar-text)',
                cursor: 'pointer',
                width: '44px',
                height: '44px',
                minWidth: '44px',
                minHeight: '44px',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                transition: 'all 0.15s ease',
              }}
              onMouseEnter={e => {
                e.currentTarget.style.color = '#ffffff'
                e.currentTarget.style.background = 'var(--sidebar-hover)'
              }}
              onMouseLeave={e => {
                e.currentTarget.style.color = 'var(--sidebar-text)'
                e.currentTarget.style.background = 'transparent'
              }}
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                <path d="M5 12h14" />
                <path d="M12 5v14" />
              </svg>
            </button>
          </div>
        )}
      </div>

      {/* Live status card: 8px radius, 1px border */}
      {effectivelyCollapsed ? (
        <div
          id="sidebar-specs-card"
          onClick={() => {
            if (!isOnline && onRetryConnection) {
              onRetryConnection()
            } else if (onOpenTelemetry) {
              onOpenTelemetry()
            }
          }}
          title={isOnline ? `${totalActive} tasks synced: ${backendStatus} (Click for telemetry)` : `Reconnecting: ${backendStatus} (Click to wake up)`}
          aria-label={isOnline ? `${totalActive} tasks synced: ${backendStatus}` : `Reconnecting: ${backendStatus}`}
          style={{
            width: '44px',
            height: '44px',
            minWidth: '44px',
            minHeight: '44px',
            margin: '12px auto 6px',
            borderRadius: '6px',
            background: 'transparent',
            border: '1px solid var(--sidebar-divider)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            cursor: (!isOnline && onRetryConnection) || onOpenTelemetry ? 'pointer' : 'default',
            position: 'relative',
            transition: 'all 0.15s ease',
            flexShrink: 0,
            color: 'var(--sidebar-text)',
          }}
          onMouseEnter={e => e.currentTarget.style.background = 'var(--sidebar-hover)'}
          onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
        >
          <div style={{
            width: '6px',
            height: '6px',
            borderRadius: '50%',
            background: isOnline ? '#1c8a62' : '#f5a623',
            position: 'absolute',
            top: '6px',
            right: '6px',
          }} />
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2" />
          </svg>
        </div>
      ) : (
        <div style={{
          padding: '12px 14px',
          borderRadius: '8px',
          background: 'transparent',
          border: '1px solid var(--sidebar-divider)',
          marginTop: '16px'
        }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '4px' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <div style={{
                width: '7px',
                height: '7px',
                borderRadius: '50%',
                background: isOnline ? '#1c8a62' : '#f5a623',
                flexShrink: 0
              }} />
              <span style={{ fontSize: '12.5px', fontWeight: '600', color: '#ffffff' }}>
                {isOnline ? `${totalActive} tasks synced` : 'Reconnecting'}
              </span>
            </div>
            {!isOnline && onRetryConnection && (
              <button
                id="sidebar-retry-connection-button"
                type="button"
                onClick={(e) => {
                  e.stopPropagation()
                  onRetryConnection()
                }}
                title="Ping backend to wake up now"
                style={{
                  fontSize: '11px',
                  fontWeight: '600',
                  padding: '2px 8px',
                  borderRadius: '6px',
                  background: 'var(--accent)',
                  border: '1px solid transparent',
                  color: 'var(--accent-text)',
                  cursor: 'pointer',
                  transition: 'all 0.15s ease'
                }}
                onMouseEnter={e => e.currentTarget.style.opacity = '0.9'}
                onMouseLeave={e => e.currentTarget.style.opacity = '1'}
              >
                Wake up
              </button>
            )}
          </div>
          <div style={{ fontSize: '11px', color: 'var(--sidebar-text)', opacity: 0.8, paddingLeft: '15px' }}>
            {backendStatus}
          </div>
          {usageBadge && (() => {
            const parsed = parseUsageBadge(usageBadge)
            const fullText = parsed?.isUsage ? parsed.fullText : usageBadge
            const titleTooltip = `Nebius Telemetry: ${fullText} (Click to open telemetry inspection)`
            const ariaLabel = `Nebius Telemetry: ${fullText}. Click to view details.`

            return (
              <div
                id="sidebar-usage-badge"
                className="mono"
                role="button"
                tabIndex={0}
                onClick={() => onOpenTelemetry && onOpenTelemetry()}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault()
                    onOpenTelemetry && onOpenTelemetry()
                  }
                }}
                title={titleTooltip}
                aria-label={ariaLabel}
                style={{
                  fontFamily: 'var(--font-mono, "JetBrains Mono", monospace)',
                  fontVariantNumeric: 'tabular-nums',
                  fontSize: '10.5px',
                  lineHeight: '1.4',
                  color: 'var(--sidebar-text)',
                  padding: '6px 8px',
                  marginTop: '8px',
                  borderRadius: '6px',
                  background: 'var(--sidebar-hover)',
                  border: '1px solid var(--sidebar-divider)',
                  cursor: 'pointer',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  gap: '8px',
                  transition: 'all 0.15s ease',
                  width: '100%',
                  boxSizing: 'border-box',
                }}
                onMouseEnter={e => e.currentTarget.style.color = '#ffffff'}
                onMouseLeave={e => e.currentTarget.style.color = 'var(--sidebar-text)'}
              >
                {parsed?.isUsage ? (
                  <div
                    style={{
                      display: 'flex',
                      flexWrap: 'wrap',
                      alignItems: 'center',
                      gap: '2px 8px',
                      minWidth: 0,
                      flex: 1,
                    }}
                  >
                    <span
                      style={{
                        display: 'inline-flex',
                        alignItems: 'center',
                        gap: '4px',
                        whiteSpace: 'nowrap',
                      }}
                    >
                      <Zap size={11} strokeWidth={1.8} style={{ color: 'var(--accent, #f5a623)' }} aria-hidden="true" />
                      <span>{parsed.calls}</span>
                    </span>
                    <span
                      style={{
                        whiteSpace: 'nowrap',
                        color: 'var(--sidebar-active-text, #ffffff)',
                        fontWeight: '600',
                      }}
                    >
                      {parsed.cost}
                    </span>
                  </div>
                ) : (
                  <span style={{ minWidth: 0, flex: 1, wordBreak: 'break-word' }}>
                    {usageBadge}
                  </span>
                )}
                <svg
                  style={{ flexShrink: 0, opacity: 0.85 }}
                  width="13"
                  height="13"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="1.8"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  aria-hidden="true"
                >
                  <path d="M12 20V10" />
                  <path d="M18 20V4" />
                  <path d="M6 20v-4" />
                </svg>
              </div>
            )
          })()}
        </div>
      )}

      {/* Account / Workspace Switcher: min 44px tap target */}
      {effectivelyCollapsed ? (
        <div
          id="sidebar-account-btn"
          onClick={() => onOpenAuth && onOpenAuth()}
          title={currentUser?.authenticated ? `Signed in as ${currentUser.email}, Click to switch` : 'Sign in / Account'}
          aria-label={currentUser?.authenticated ? `Signed in as ${currentUser.email}` : 'Sign in / Account'}
          style={{
            width: '44px',
            height: '44px',
            minWidth: '44px',
            minHeight: '44px',
            margin: '6px auto 0',
            borderRadius: '6px',
            background: 'transparent',
            border: '1px solid var(--sidebar-divider)',
            cursor: 'pointer',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            transition: 'all 0.15s ease',
            flexShrink: 0,
            color: 'var(--sidebar-text)',
          }}
          onMouseEnter={e => {
            e.currentTarget.style.background = 'var(--sidebar-hover)'
            e.currentTarget.style.color = '#ffffff'
          }}
          onMouseLeave={e => {
            e.currentTarget.style.background = 'transparent'
            e.currentTarget.style.color = 'var(--sidebar-text)'
          }}
        >
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <path d="M19 21v-2a4 4 0 0 0-4-4H9a4 4 0 0 0-4 4v2" />
            <circle cx="12" cy="7" r="4" />
          </svg>
        </div>
      ) : (
        <div
          id="sidebar-account-btn"
          onClick={() => onOpenAuth && onOpenAuth()}
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            padding: '8px 10px',
            minHeight: '44px',
            borderRadius: '6px',
            background: 'transparent',
            border: '1px solid var(--sidebar-divider)',
            cursor: 'pointer',
            marginTop: '8px',
            transition: 'all 0.15s ease'
          }}
          onMouseEnter={e => e.currentTarget.style.background = 'var(--sidebar-hover)'}
          onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
          title="Manage Account & Google Calendar"
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', minWidth: 0 }}>
            <span style={{ color: 'var(--sidebar-text)', display: 'inline-flex', alignItems: 'center' }}>
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                <path d="M19 21v-2a4 4 0 0 0-4-4H9a4 4 0 0 0-4 4v2" />
                <circle cx="12" cy="7" r="4" />
              </svg>
            </span>
            <div style={{ minWidth: 0 }}>
              <div style={{ fontSize: '12px', color: '#ffffff', fontWeight: '500', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {currentUser?.authenticated ? currentUser.email : 'Sign in / Account'}
              </div>
              <div style={{ fontSize: '10.5px', color: 'var(--sidebar-text)', opacity: 0.75 }}>
                {currentUser?.calendar?.connected ? 'Google Calendar Connected' : 'Isolated Workspace'}
              </div>
            </div>
          </div>
          <span style={{ fontSize: '11px', color: 'var(--brand)', fontWeight: '600', flexShrink: 0, paddingLeft: '6px' }}>
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
          {!effectivelyCollapsed && (
        <div style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: "8px", marginTop: "10px", fontSize: "11px", color: "var(--sidebar-text)", opacity: 0.7 }}>
          <button
            type="button"
            id="sidebar-terms-link"
            onClick={() => onSelectTab && onSelectTab("terms")}
            style={{ background: "none", border: "none", color: "inherit", padding: 0, cursor: "pointer", textDecoration: "underline" }}
          >
            Terms
          </button>
          <span>·</span>
          <button
            type="button"
            id="sidebar-privacy-link"
            onClick={() => onSelectTab && onSelectTab("privacy")}
            style={{ background: "none", border: "none", color: "inherit", padding: 0, cursor: "pointer", textDecoration: "underline" }}
          >
            Privacy
          </button>
        </div>
      )}
    </aside>
  )
}
