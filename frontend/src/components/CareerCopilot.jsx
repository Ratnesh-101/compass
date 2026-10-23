import React, { useState } from 'react'
import InternshipRadar from './InternshipRadar'
import ApplicationCenter from './career/ApplicationCenter'
import DarkModeToggle from './DarkModeToggle'

const ResumeStudio = React.lazy(() => import('./career/ResumeStudio'))

export default function CareerCopilot({ isDarkMode, onToggleDarkMode }) {
  const [activeSubTab, setActiveSubTab] = useState('radar') // 'radar' | 'resumes' | 'applications'
  const [profileRefreshTrigger, setProfileRefreshTrigger] = useState(0)
  const [notification, setNotification] = useState(null)

  const handleNavigateToResumeStudio = () => {
    setActiveSubTab('resumes')
  }

  const handleRefreshComplete = () => {
    setNotification({
      type: 'success',
      message: '✓ Profile saved! Internship matches have been updated.',
    })
    // Auto-dismiss after 4 seconds
    setTimeout(() => {
      setNotification(prev => (prev?.type === 'success' ? null : prev))
    }, 4000)
  }

  const handleRefreshError = () => {
    setNotification({
      type: 'warning',
      message: 'Profile saved, but could not refresh internship recommendations.',
      canRetry: true,
      onRetry: () => {
        setNotification({
          type: 'info',
          message: 'Retrying internship recommendations refresh…',
        })
        setProfileRefreshTrigger(prev => prev + 1)
      },
    })
  }

  const SUB_TABS = [
    { key: 'radar', label: 'Internship Radar', desc: 'Verified discovery & eligibility' },
    { key: 'resumes', label: 'Resume Studio', desc: 'Factual tailoring & ATS export' },
    { key: 'applications', label: 'Application Center', desc: 'Pipelines & batch approvals' },
  ]

  return (
    <div
      id="career-copilot-container"
      style={{
        flex: 1,
        display: 'flex',
        flexDirection: 'column',
        minHeight: 0,
        height: '100%',
        overflowY: 'auto',
        background: 'var(--bg-app)',
        boxSizing: 'border-box',
      }}
    >
      {/* Top Banner Navigation */}
      <div
        style={{
          background: 'var(--bg-card)',
          borderBottom: '1px solid var(--border)',
          padding: '16px 24px',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          flexWrap: 'wrap',
          gap: '12px',
          flexShrink: 0,
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          <div
            style={{
              width: '38px',
              height: '38px',
              borderRadius: '6px',
              background: 'var(--bg-card-soft)',
              border: '1px solid var(--border)',
              color: 'var(--text-primary)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              flexShrink: 0,
            }}
          >
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <circle cx="12" cy="12" r="10" />
              <circle cx="12" cy="12" r="6" />
              <circle cx="12" cy="12" r="2" />
            </svg>
          </div>
          <div>
            <h1 style={{ margin: 0, fontSize: '26px', fontWeight: '600', color: 'var(--text-primary)', letterSpacing: '-0.3px', lineHeight: 1.2 }}>
              Career Copilot
            </h1>
            <p style={{ margin: 0, fontSize: '13px', color: 'var(--text-muted)', lineHeight: 1.4 }}>
              Autonomous discovery, truthful resume tailoring, and authorized application management.
            </p>
          </div>
        </div>

        {/* Action Controls & Dark Mode Toggle */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
          <button
            type="button"
            className="btn-secondary"
            onClick={handleNavigateToResumeStudio}
            title="Manage candidate profile and master resume in Resume Studio"
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '8px',
            }}
          >
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
              <path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z" />
              <circle cx="12" cy="12" r="3" />
            </svg>
            <span>Candidate Profile</span>
          </button>
          <DarkModeToggle
            isDarkMode={Boolean(isDarkMode)}
            onToggleDarkMode={onToggleDarkMode}
            id="career-theme-toggle"
          />
        </div>
      </div>

      {/* Success / Feedback Notification Banner */}
      {notification && (
        <div
          role="status"
          aria-live="polite"
          id="career-copilot-notification"
          style={{
            margin: '12px 24px 0 24px',
            padding: '10px 16px',
            borderRadius: '6px',
            fontSize: '13px',
            fontWeight: 500,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            gap: '12px',
            flexShrink: 0,
            background:
              notification.type === 'warning'
                ? 'var(--bg-card-soft)'
                : notification.type === 'success'
                ? 'var(--bg-card-soft)'
                : 'var(--bg-card-soft)',
            color: 'var(--text-primary)',
            border: '1px solid var(--border)',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <span>
              {notification.type === 'warning' ? '⚠️' : notification.type === 'success' ? '✓' : '🔄'}
            </span>
            <span>{notification.message}</span>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            {notification.canRetry && (
              <button
                type="button"
                onClick={notification.onRetry}
                style={{
                  background: 'var(--bg-card)',
                  border: '1px solid var(--border)',
                  color: 'inherit',
                  padding: '4px 10px',
                  borderRadius: '6px',
                  fontSize: '12px',
                  fontWeight: 600,
                  cursor: 'pointer',
                }}
              >
                Retry
              </button>
            )}
            <button
              type="button"
              onClick={() => setNotification(null)}
              style={{
                background: 'transparent',
                border: 'none',
                color: 'inherit',
                fontSize: '16px',
                cursor: 'pointer',
                padding: '0 4px',
                lineHeight: 1,
              }}
              aria-label="Dismiss notification"
            >
              ×
            </button>
          </div>
        </div>
      )}

      {/* Sub-Tabs Switcher */}
      <nav
        id="career-subtabs-nav"
        className="career-subtab-nav"
        aria-label="Career Copilot Navigation"
      >
        <div className="career-subtab-tray" role="tablist">
          {SUB_TABS.map((tab) => {
            const isActive = activeSubTab === tab.key
            return (
              <button
                key={tab.key}
                role="tab"
                id={`career-subtab-${tab.key}`}
                aria-selected={isActive}
                type="button"
                onClick={() => setActiveSubTab(tab.key)}
                className={`career-subtab-btn ${isActive ? 'active' : ''}`}
                style={{
                  minHeight: '44px',
                  borderRadius: '6px',
                }}
              >
                {tab.key === 'radar' && (
                  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                    <circle cx="12" cy="12" r="10" />
                    <path d="M12 2a14.5 14.5 0 0 0 0 20 14.5 14.5 0 0 0 0-20" />
                    <path d="M2 12h20" />
                  </svg>
                )}
                {tab.key === 'resumes' && (
                  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                    <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                    <polyline points="14 2 14 8 20 8" />
                    <line x1="16" y1="13" x2="8" y2="13" />
                    <line x1="16" y1="17" x2="8" y2="17" />
                    <polyline points="10 9 9 9 8 9" />
                  </svg>
                )}
                {tab.key === 'applications' && (
                  <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                    <rect width="20" height="14" x="2" y="7" rx="2" ry="2" />
                    <path d="M16 21V5a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v16" />
                  </svg>
                )}
                <span>{tab.label}</span>
              </button>
            )
          })}
        </div>
      </nav>

      {/* Main Tab Area */}
      <div style={{ flex: 1, minHeight: 0, padding: activeSubTab === 'radar' ? '0' : '20px 24px' }}>
        {activeSubTab === 'radar' && (
          <InternshipRadar
            refreshTrigger={profileRefreshTrigger}
            onRefreshComplete={handleRefreshComplete}
            onRefreshError={handleRefreshError}
            onNavigateToResumeStudio={handleNavigateToResumeStudio}
            onOpenProfile={handleNavigateToResumeStudio}
          />
        )}
        {activeSubTab === 'resumes' && (
          <React.Suspense fallback={<div style={{ padding: '32px', textAlign: 'center', color: 'var(--text-secondary)' }}>Loading Resume Studio…</div>}>
            <ResumeStudio />
          </React.Suspense>
        )}
        {activeSubTab === 'applications' && <ApplicationCenter />}
      </div>
    </div>
  )
}
