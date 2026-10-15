import React from 'react'

/**
 * MobileNavBar
 * Fixed bottom navigation bar for mobile viewports (< 768px).
 * Provides one-tap access to primary destinations:
 * 1. Timeline (▦)
 * 2. Compass Assistant (🧭)
 * 3. Schedule (🗓️)
 * 4. More / Context Domains (☰)
 */
export default function MobileNavBar({
  activeTab,
  onSelectTab,
  onOpenMenu,
  _activeDomain = 'all',
}) {
  const isDashboardActive = activeTab === 'dashboard'
  const isTimelineActive = activeTab === 'timeline'
  const isCompassActive = activeTab === 'compass' || activeTab === 'assistant' || activeTab === 'planner' || activeTab === 'agent'
  const isCalendarActive = activeTab === 'calendar'

  return (
    <nav
      id="mobile-bottom-nav"
      className="mobile-nav-bar"
      aria-label="Mobile Navigation"
      style={{
        position: 'fixed',
        bottom: 0,
        left: 0,
        right: 0,
        height: '58px',
        paddingBottom: 'env(safe-area-inset-bottom, 0px)',
        background: 'var(--bg-card)',
        borderTop: '1px solid var(--border)',
        boxShadow: '0 -2px 12px rgba(0, 0, 0, 0.08)',
        zIndex: 850,
        display: 'flex',
        alignItems: 'stretch',
        justifyContent: 'space-around',
        boxSizing: 'content-box',
        userSelect: 'none',
      }}
    >
      {/* 1. Dashboard */}
      <button
        id="mobile-tab-dashboard"
        type="button"
        onClick={() => onSelectTab('dashboard')}
        className={`mobile-nav-item ${isDashboardActive ? 'active' : ''}`}
        aria-label="Dashboard overview"
        aria-current={isDashboardActive ? 'page' : undefined}
        style={{
          flex: 1,
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          background: 'transparent',
          border: 'none',
          cursor: 'pointer',
          padding: '6px 0',
          gap: '3px',
          color: isDashboardActive ? 'var(--brand)' : 'var(--text-muted)',
          transition: 'color 0.15s ease, transform 0.1s ease',
          minHeight: '48px',
        }}
      >
        <span
          style={{
            fontSize: '18px',
            lineHeight: 1,
            display: 'inline-flex',
            alignItems: 'center',
            justifyContent: 'center',
            width: '28px',
            height: '24px',
            borderRadius: '6px',
            background: isDashboardActive ? 'rgba(245, 166, 35, 0.15)' : 'transparent',
          }}
        >
          📊
        </span>
        <span
          style={{
            fontSize: '10.5px',
            fontWeight: isDashboardActive ? '700' : '500',
            letterSpacing: '0.01em',
          }}
        >
          Dashboard
        </span>
      </button>
      {/* 1. Timeline */}
      <button
        id="mobile-tab-timeline"
        type="button"
        onClick={() => onSelectTab('timeline')}
        className={`mobile-nav-item ${isTimelineActive ? 'active' : ''}`}
        aria-label="Timeline feed and tasks"
        aria-current={isTimelineActive ? 'page' : undefined}
        style={{
          flex: 1,
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          background: 'transparent',
          border: 'none',
          cursor: 'pointer',
          padding: '6px 0',
          gap: '3px',
          color: isTimelineActive ? 'var(--brand)' : 'var(--text-muted)',
          transition: 'color 0.15s ease, transform 0.1s ease',
          minHeight: '48px',
        }}
      >
        <span
          style={{
            fontSize: '18px',
            lineHeight: 1,
            display: 'inline-flex',
            alignItems: 'center',
            justifyContent: 'center',
            width: '28px',
            height: '24px',
            borderRadius: '6px',
            background: isTimelineActive ? 'rgba(245, 166, 35, 0.15)' : 'transparent',
          }}
        >
          ▦
        </span>
        <span
          style={{
            fontSize: '10.5px',
            fontWeight: isTimelineActive ? '700' : '500',
            letterSpacing: '0.01em',
          }}
        >
          Timeline
        </span>
      </button>

      {/* 2. Compass Assistant */}
      <button
        id="mobile-tab-compass"
        type="button"
        onClick={() => onSelectTab('compass')}
        className={`mobile-nav-item ${isCompassActive ? 'active' : ''}`}
        aria-label="Compass AI Assistant"
        aria-current={isCompassActive ? 'page' : undefined}
        style={{
          flex: 1,
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          background: 'transparent',
          border: 'none',
          cursor: 'pointer',
          padding: '6px 0',
          gap: '3px',
          color: isCompassActive ? 'var(--brand)' : 'var(--text-muted)',
          transition: 'color 0.15s ease, transform 0.1s ease',
          minHeight: '48px',
        }}
      >
        <span
          style={{
            fontSize: '18px',
            lineHeight: 1,
            display: 'inline-flex',
            alignItems: 'center',
            justifyContent: 'center',
            width: '28px',
            height: '24px',
            borderRadius: '6px',
            background: isCompassActive ? 'rgba(245, 166, 35, 0.15)' : 'transparent',
          }}
        >
          🧭
        </span>
        <span
          style={{
            fontSize: '10.5px',
            fontWeight: isCompassActive ? '700' : '500',
            letterSpacing: '0.01em',
          }}
        >
          Compass
        </span>
      </button>

      {/* 3. Schedule / Calendar */}
      <button
        id="mobile-tab-calendar"
        type="button"
        onClick={() => onSelectTab('calendar')}
        className={`mobile-nav-item ${isCalendarActive ? 'active' : ''}`}
        aria-label="Schedule and calendar"
        aria-current={isCalendarActive ? 'page' : undefined}
        style={{
          flex: 1,
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          background: 'transparent',
          border: 'none',
          cursor: 'pointer',
          padding: '6px 0',
          gap: '3px',
          color: isCalendarActive ? 'var(--brand)' : 'var(--text-muted)',
          transition: 'color 0.15s ease, transform 0.1s ease',
          minHeight: '48px',
        }}
      >
        <span
          style={{
            fontSize: '18px',
            lineHeight: 1,
            display: 'inline-flex',
            alignItems: 'center',
            justifyContent: 'center',
            width: '28px',
            height: '24px',
            borderRadius: '6px',
            background: isCalendarActive ? 'rgba(245, 166, 35, 0.15)' : 'transparent',
          }}
        >
          🗓️
        </span>
        <span
          style={{
            fontSize: '10.5px',
            fontWeight: isCalendarActive ? '700' : '500',
            letterSpacing: '0.01em',
          }}
        >
          Schedule
        </span>
      </button>

      {/* 4. More (Domains, Account, Telemetry) */}
      <button
        id="mobile-tab-more"
        type="button"
        onClick={onOpenMenu}
        className="mobile-nav-item"
        aria-label="More options, domains and workspace settings"
        style={{
          flex: 1,
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          background: 'transparent',
          border: 'none',
          cursor: 'pointer',
          padding: '6px 0',
          gap: '3px',
          color: 'var(--text-muted)',
          transition: 'color 0.15s ease, transform 0.1s ease',
          minHeight: '48px',
        }}
      >
        <span
          style={{
            fontSize: '18px',
            lineHeight: 1,
            display: 'inline-flex',
            alignItems: 'center',
            justifyContent: 'center',
            width: '28px',
            height: '24px',
            borderRadius: '6px',
          }}
        >
          ☰
        </span>
        <span
          style={{
            fontSize: '10.5px',
            fontWeight: '600',
            letterSpacing: '0.01em',
          }}
        >
          More
        </span>
      </button>
    </nav>
  )
}
