import React from 'react'
import {
  CheckSquare,
  Compass,
  Calendar,
  Sparkles,
  Cpu,
  Layers,
  Activity,
  User,
  ShieldCheck,
  ChevronRight,
  Flame,
  BookOpen,
  Code2,
  Globe,
  Tag,
  Zap,
} from 'lucide-react'

const NAV_ITEMS = [
  { key: 'timeline', icon: CheckSquare, label: 'Timeline & Tasks', sub: 'Executive Task Feed' },
  { key: 'compass', icon: Compass, label: 'Compass', sub: 'Assistant & Agents' },
  { key: 'calendar', icon: Calendar, label: 'Smart Schedule', sub: 'Calendar & Conflict Engine' },
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
}) {
  const isOnline =
    backendStatus.toLowerCase().includes('neon') ||
    backendStatus.toLowerCase().includes('live') ||
    backendStatus.toLowerCase().includes('online')

  const totalActive = Object.values(domainCounts || {}).reduce(
    (sum, n) => sum + (typeof n === 'number' ? n : 0),
    0
  )

  const baseDomains = [
    { key: 'hackathon', label: 'Hackathon', icon: Flame, color: '#f59e0b', bg: 'rgba(245, 158, 11, 0.12)' },
    { key: 'coursework', label: 'Coursework', icon: BookOpen, color: '#3b82f6', bg: 'rgba(59, 130, 246, 0.12)' },
    { key: 'code', label: 'Code & Infra', icon: Code2, color: '#10b981', bg: 'rgba(16, 185, 129, 0.12)' },
    { key: 'general', label: 'General', icon: Globe, color: '#94a3b8', bg: 'rgba(148, 163, 184, 0.12)' },
    { key: 'other', label: 'Other', icon: Tag, color: '#a855f7', bg: 'rgba(168, 85, 247, 0.12)' },
  ]

  const extraDomains = Object.keys(domainCounts || {})
    .filter(k => !baseDomains.some(b => b.key === k) && ((domainCounts[k] || 0) > 0 || activeDomain === k))
    .map(k => ({
      key: k,
      label: k.charAt(0).toUpperCase() + k.slice(1),
      icon: Tag,
      color: '#c084fc',
      bg: 'rgba(192, 132, 252, 0.12)',
    }))

  const displayDomains = [...baseDomains, ...extraDomains]

  return (
    <aside
      style={{
        width: '264px',
        minWidth: '240px',
        maxWidth: '280px',
        flexShrink: 0,
        borderRight: '1px solid #1e293b',
        background: '#0f172a',
        display: 'flex',
        flexDirection: 'column',
        padding: '20px 16px',
        height: '100vh',
        overflowY: 'auto',
      }}
    >
      {/* Brand Header */}
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
          marginBottom: '26px',
          padding: '0 4px',
          cursor: 'pointer',
          userSelect: 'none',
          transition: 'all 0.15s ease',
        }}
        onMouseEnter={e => (e.currentTarget.style.opacity = '0.9')}
        onMouseLeave={e => (e.currentTarget.style.opacity = '1')}
        title="Compass Workspace — Return to Executive Overview"
      >
        <div
          style={{
            width: '38px',
            height: '38px',
            borderRadius: '10px',
            background: 'linear-gradient(135deg, #f59e0b 0%, #d97706 100%)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            color: '#ffffff',
            flexShrink: 0,
            boxShadow: '0 4px 14px rgba(245, 158, 11, 0.3)',
          }}
        >
          <Compass size={22} strokeWidth={2.4} />
        </div>
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
            <h1 style={{ fontSize: '17px', fontWeight: '800', letterSpacing: '-0.4px', color: '#f8fafc', margin: 0 }}>
              Compass
            </h1>
            <span
              style={{
                fontSize: '9.5px',
                fontWeight: '700',
                padding: '1px 6px',
                borderRadius: '4px',
                background: 'rgba(99, 102, 241, 0.25)',
                color: '#a5b4fc',
                letterSpacing: '0.04em',
                textTransform: 'uppercase',
              }}
            >
              MoE
            </span>
          </div>
          <p style={{ fontSize: '11px', color: '#94a3b8', margin: '2px 0 0 0', fontWeight: '500' }}>
            Autonomous AI Platform
          </p>
        </div>
      </div>

      {/* Primary Navigation */}
      <div style={{ marginBottom: '24px' }}>
        <p
          style={{
            fontSize: '10.5px',
            textTransform: 'uppercase',
            letterSpacing: '0.08em',
            color: '#64748b',
            fontWeight: '700',
            marginBottom: '10px',
            padding: '0 6px',
          }}
        >
          Workspace
        </p>

        {NAV_ITEMS.map(item => {
          const Icon = item.icon
          const isActive = activeTab === item.key || (item.key === 'compass' && (activeTab === 'agent' || activeTab === 'planner' || activeTab === 'specialist'))
          return (
            <button
              key={item.key}
              id={`sidebar-tab-${item.key}`}
              onClick={() => onSelectTab(item.key)}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '12px',
                padding: '10px 12px',
                borderRadius: '10px',
                cursor: 'pointer',
                marginBottom: '4px',
                border: 'none',
                width: '100%',
                textAlign: 'left',
                background: isActive ? '#1e293b' : 'transparent',
                color: isActive ? '#f8fafc' : '#94a3b8',
                transition: 'all 0.15s ease',
              }}
              onMouseEnter={e => {
                if (!isActive) {
                  e.currentTarget.style.background = 'rgba(255, 255, 255, 0.04)'
                  e.currentTarget.style.color = '#f1f5f9'
                }
              }}
              onMouseLeave={e => {
                if (!isActive) {
                  e.currentTarget.style.background = 'transparent'
                  e.currentTarget.style.color = '#94a3b8'
                }
              }}
            >
              <div
                style={{
                  width: '32px',
                  height: '32px',
                  borderRadius: '8px',
                  background: isActive ? 'linear-gradient(135deg, #6366f1 0%, #4f46e5 100%)' : 'rgba(255, 255, 255, 0.05)',
                  color: isActive ? '#ffffff' : '#94a3b8',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  flexShrink: 0,
                  boxShadow: isActive ? '0 2px 8px rgba(99, 102, 241, 0.35)' : 'none',
                }}
              >
                <Icon size={16} strokeWidth={isActive ? 2.5 : 2} />
              </div>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: '13px', fontWeight: isActive ? '700' : '600' }}>
                  {item.label}
                </div>
                <div style={{ fontSize: '10.5px', color: isActive ? '#94a3b8' : '#64748b', marginTop: '1px' }}>
                  {item.sub}
                </div>
              </div>
              {isActive && <ChevronRight size={14} color="#6366f1" />}
            </button>
          )
        })}
      </div>

      {/* Domain Isolation Filter List */}
      <div style={{ marginBottom: 'auto' }}>
        <div
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            marginBottom: '10px',
            padding: '0 6px',
          }}
        >
          <p
            style={{
              fontSize: '10.5px',
              textTransform: 'uppercase',
              letterSpacing: '0.08em',
              color: '#64748b',
              fontWeight: '700',
              margin: 0,
            }}
          >
            Context Domains
          </p>
          {activeDomain !== 'all' && (
            <span
              onClick={() => onSelectDomain('all')}
              style={{
                fontSize: '10.5px',
                color: '#f59e0b',
                cursor: 'pointer',
                fontWeight: '700',
              }}
            >
              Reset All
            </span>
          )}
        </div>

        {displayDomains.map(dom => {
          const Icon = dom.icon
          const isSelected = activeDomain === dom.key
          const count = domainCounts[dom.key] ?? 0
          return (
            <div
              key={dom.key}
              onClick={() => onSelectDomain(dom.key)}
              style={{
                padding: '8px 12px',
                borderRadius: '8px',
                marginBottom: '3px',
                cursor: 'pointer',
                display: 'flex',
                justifyContent: 'space-between',
                alignItems: 'center',
                background: isSelected ? '#1e293b' : 'transparent',
                transition: 'background 0.15s ease',
              }}
              onMouseEnter={e => {
                if (!isSelected) e.currentTarget.style.background = 'rgba(255, 255, 255, 0.03)'
              }}
              onMouseLeave={e => {
                if (!isSelected) e.currentTarget.style.background = 'transparent'
              }}
            >
              <span
                style={{
                  fontSize: '12.5px',
                  color: isSelected ? '#f8fafc' : '#94a3b8',
                  fontWeight: isSelected ? '700' : '500',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '9px',
                }}
              >
                <span
                  style={{
                    color: dom.color,
                    display: 'flex',
                    alignItems: 'center',
                  }}
                >
                  <Icon size={14} />
                </span>
                {dom.label}
              </span>
              <span
                style={{
                  padding: '2px 7px',
                  borderRadius: '12px',
                  fontSize: '10.5px',
                  fontWeight: '700',
                  background: isSelected ? dom.bg : 'rgba(255, 255, 255, 0.05)',
                  color: dom.color,
                }}
              >
                {count}
              </span>
            </div>
          )
        })}
      </div>

      {/* Live Backend Connection Card */}
      <div
        style={{
          padding: '12px 14px',
          borderRadius: '12px',
          background: 'rgba(255, 255, 255, 0.03)',
          border: '1px solid rgba(255, 255, 255, 0.06)',
          marginTop: '16px',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '4px' }}>
          <div
            style={{
              width: '7px',
              height: '7px',
              borderRadius: '50%',
              background: isOnline ? '#10b981' : '#f59e0b',
              boxShadow: isOnline ? '0 0 8px rgba(16, 185, 129, 0.6)' : 'none',
              flexShrink: 0,
            }}
          />
          <span style={{ fontSize: '12px', fontWeight: '700', color: '#f1f5f9' }}>
            {isOnline ? `${totalActive} tasks synced` : 'Reconnecting...'}
          </span>
        </div>
        <div style={{ fontSize: '10.5px', color: '#64748b', paddingLeft: '15px' }}>
          {backendStatus}
        </div>

        {usageBadge && (
          <div
            id="sidebar-usage-badge"
            className="mono"
            onClick={() => onOpenTelemetry && onOpenTelemetry()}
            style={{
              fontSize: '10.5px',
              color: '#fbbf24',
              padding: '6px 10px',
              marginTop: '8px',
              borderRadius: '8px',
              background: 'rgba(245, 158, 11, 0.08)',
              border: '1px solid rgba(245, 158, 11, 0.25)',
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
              transition: 'all 0.15s ease',
            }}
            onMouseEnter={e => (e.currentTarget.style.background = 'rgba(245, 158, 11, 0.16)')}
            onMouseLeave={e => (e.currentTarget.style.background = 'rgba(245, 158, 11, 0.08)')}
            title="Inspect live Nebius Token Factory & NVIDIA telemetry"
          >
            <span style={{ display: 'flex', alignItems: 'center', gap: '5px' }}>
              <Zap size={12} color="#fbbf24" />
              <span>{usageBadge}</span>
            </span>
            <Cpu size={12} opacity={0.8} />
          </div>
        )}
      </div>

      {/* User Session & Account Footer */}
      <div
        id="sidebar-account-btn"
        onClick={() => onOpenAuth && onOpenAuth()}
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '10px 12px',
          borderRadius: '10px',
          background: 'rgba(255, 255, 255, 0.03)',
          border: '1px solid rgba(255, 255, 255, 0.07)',
          cursor: 'pointer',
          marginTop: '12px',
          transition: 'all 0.15s ease',
        }}
        onMouseEnter={e => (e.currentTarget.style.background = 'rgba(255, 255, 255, 0.06)')}
        onMouseLeave={e => (e.currentTarget.style.background = 'rgba(255, 255, 255, 0.03)')}
        title="Manage Account, Google Calendar & Workspace Isolation"
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '9px', minWidth: 0 }}>
          <div
            style={{
              width: '28px',
              height: '28px',
              borderRadius: '7px',
              background: '#1e293b',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              color: '#94a3b8',
              flexShrink: 0,
            }}
          >
            <User size={15} />
          </div>
          <div style={{ minWidth: 0 }}>
            <div
              style={{
                fontSize: '12px',
                color: '#f8fafc',
                fontWeight: '600',
                overflow: 'hidden',
                textOverflow: 'ellipsis',
                whiteSpace: 'nowrap',
              }}
            >
              {currentUser?.authenticated ? currentUser.email : 'Guest Session'}
            </div>
            <div style={{ fontSize: '10px', color: '#64748b' }}>
              {currentUser?.calendar?.connected ? 'Google Calendar ✓' : 'Isolated Workspace'}
            </div>
          </div>
        </div>
        <span
          style={{
            fontSize: '11px',
            color: '#f59e0b',
            fontWeight: '700',
            flexShrink: 0,
            paddingLeft: '6px',
          }}
        >
          {currentUser?.authenticated ? 'Switch' : 'Login'}
        </span>
      </div>
    </aside>
  )
}
