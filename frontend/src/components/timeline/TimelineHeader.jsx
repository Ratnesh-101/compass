import React from 'react'
import {
  Plus,
  Sparkles,
  Cpu,
  ShieldCheck,
  AlertTriangle,
  X,
  ArrowLeft,
  Loader2,
  Check,
  BookOpen
} from 'lucide-react'
import DarkModeToggle from '../DarkModeToggle'

export default function TimelineHeader({
  today,
  domainMeta,
  onSelectDomain,
  darkMode,
  toggleDark,
  onOpenTelemetry,
  onVerifyAll,
  verifyingDeadlines,
  onOpenNewTask,
  onOpenAbout,
  verificationSummary,
  onClearVerificationSummary,
}) {
  return (
    <div style={{ marginBottom: '20px' }}>
      {/* Top Bar: Title & Domain info on left, Theme toggle on right */}
      <div style={{
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'flex-start',
        gap: '12px',
        marginBottom: '12px',
        flexWrap: 'wrap'
      }}>
        <div style={{ flex: 1, minWidth: '240px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
            <h2 style={{
              fontSize: '24px',
              fontWeight: '600',
              color: 'var(--text-primary)',
              letterSpacing: '-0.3px',
              margin: 0,
              display: 'flex',
              alignItems: 'center',
              gap: '8px',
              flexWrap: 'wrap'
            }}>
              {domainMeta ? (
                <>
                  <span className="domain-swatch" style={{ background: domainMeta.color, width: '12px', height: '12px', borderRadius: '50%' }} />
                  <span>{domainMeta.label} Domain</span>
                </>
              ) : (
                <span>Timeline Feed</span>
              )}
              <span style={{ color: 'var(--text-secondary)', fontWeight: '400', fontSize: '14px' }}>, {today}</span>
            </h2>

            {domainMeta && onSelectDomain && (
              <button
                type="button"
                id="btn-return-all-domains"
                onClick={() => onSelectDomain('all')}
                className="btn-secondary"
                style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: '5px',
                  padding: '4px 10px',
                  fontSize: '12px',
                  fontWeight: '500',
                  borderRadius: 'var(--radius-btn, 6px)',
                  cursor: 'pointer',
                  minHeight: '32px'
                }}
                title="View all domains"
              >
                <ArrowLeft size={13} strokeWidth={1.8} />
                <span>View all</span>
              </button>
            )}
          </div>
          <p style={{ fontSize: '13px', color: 'var(--text-secondary)', marginTop: '4px', marginBottom: 0 }}>
            {domainMeta
              ? `Deadlines, context, and focus allocation for ${domainMeta.label}`
              : "What's happening across your workspace today"}
          </p>
        </div>

        {toggleDark && (
          <div style={{ flexShrink: 0 }}>
            <DarkModeToggle
              isDarkMode={darkMode}
              onToggleDarkMode={toggleDark}
              id="timeline-theme-toggle"
            />
          </div>
        )}
      </div>

      {/* Toolbar Button Group: clean, student-friendly */}
      <div
        className="timeline-actions-group"
        style={{
          display: 'flex',
          gap: '8px',
          alignItems: 'center',
          flexWrap: 'wrap'
        }}
      >
        <button
          id="btn-add-deadline"
          onClick={onOpenNewTask}
          className="btn-primary-amber"
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: '6px',
            minHeight: '36px',
            padding: '0 14px',
            fontSize: '13px',
            fontWeight: '600',
            borderRadius: 'var(--radius-btn, 6px)',
            cursor: 'pointer',
            flexShrink: 0
          }}
        >
          <Plus size={15} strokeWidth={2} />
          <span>Add deadline</span>
        </button>

        {onOpenAbout && (
          <button
            id="timeline-btn-about-judges"
            type="button"
            onClick={onOpenAbout}
            className="btn-secondary"
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: '6px',
              minHeight: '36px',
              padding: '0 12px',
              fontSize: '12.5px',
              fontWeight: '500',
              borderRadius: 'var(--radius-btn, 6px)',
              cursor: 'pointer',
              flexShrink: 0
            }}
            title="Architecture, AI telemetry, and evaluation resources for judges"
          >
            <BookOpen size={14} strokeWidth={1.8} style={{ color: 'var(--accent)' }} />
            <span>About / for judges</span>
          </button>
        )}
      </div>

      {/* Verification Feedback Banner */}
      {verificationSummary && (
        <div
          style={{
            background: 'var(--bg-card)',
            border: '1px solid var(--border)',
            color: 'var(--text-primary)',
            padding: '10px 14px',
            borderRadius: 'var(--radius-btn, 6px)',
            marginTop: '14px',
            fontSize: '13px',
            display: 'flex',
            justifyContent: 'space-between',
            alignItems: 'center',
            gap: '12px'
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            {verificationSummary.error ? (
              <AlertTriangle size={16} strokeWidth={1.8} style={{ color: '#ef4444', flexShrink: 0 }} />
            ) : (
              <ShieldCheck size={16} strokeWidth={1.8} style={{ color: 'var(--accent, #f5a623)', flexShrink: 0 }} />
            )}
            <div>
              <span style={{ fontWeight: '600' }}>
                {verificationSummary.error ? 'Verification note: ' : 'Schedules verified: '}
              </span>
              <span style={{ color: 'var(--text-secondary)' }}>
                {verificationSummary.error
                  ? verificationSummary.error
                  : `${verificationSummary.total} active deadline(s) checked. ${
                      verificationSummary.drift > 0
                        ? `${verificationSummary.drift} update(s) detected via live web search.`
                        : 'All deadlines confirmed matching official dates.'
                    }`}
              </span>
            </div>
          </div>
          <button
            onClick={onClearVerificationSummary}
            aria-label="Dismiss verification note"
            style={{
              background: 'transparent',
              border: 'none',
              color: 'var(--text-secondary)',
              cursor: 'pointer',
              padding: '4px',
              display: 'inline-flex',
              alignItems: 'center',
              justifyContent: 'center',
              borderRadius: 'var(--radius-btn, 4px)'
            }}
            title="Dismiss verification note"
          >
            <X size={14} strokeWidth={1.8} />
          </button>
        </div>
      )}
    </div>
  )
}
