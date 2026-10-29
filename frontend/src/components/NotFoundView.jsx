import React, { useEffect } from 'react'
import { Compass, Home, Clock, Calendar, MessageSquare, Sun, Moon } from 'lucide-react'

export default function NotFoundView({
  onBack,
  onSelectTab,
  isDarkMode = false,
  onToggleDarkMode,
}) {
  useEffect(() => {
    const originalTitle = document.title
    document.title = 'Compass — Page Not Found (404)'
    return () => {
      document.title = originalTitle
    }
  }, [])

  return (
    <div
      style={{
        minHeight: '100vh',
        background: 'var(--bg-app)',
        color: 'var(--text-primary)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: '32px 20px',
        boxSizing: 'border-box',
      }}
    >
      <div
        style={{
          maxWidth: '560px',
          width: '100%',
          background: 'var(--bg-card)',
          border: '1px solid var(--border)',
          borderRadius: 'var(--radius-card, 12px)',
          padding: '36px 28px',
          textAlign: 'center',
          boxShadow: 'var(--shadow-sm)',
          position: 'relative',
        }}
      >
        {onToggleDarkMode && (
          <button
            type="button"
            onClick={onToggleDarkMode}
            className="btn-secondary"
            aria-label="Toggle dark mode"
            style={{
              position: 'absolute',
              top: '16px',
              right: '16px',
              display: 'inline-flex',
              alignItems: 'center',
              justifyContent: 'center',
              width: '32px',
              height: '32px',
              padding: 0,
              borderRadius: 'var(--radius-btn, 6px)',
              cursor: 'pointer',
            }}
          >
            {isDarkMode ? <Sun size={14} /> : <Moon size={14} />}
          </button>
        )}

        <div
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            justifyContent: 'center',
            width: '64px',
            height: '64px',
            borderRadius: '50%',
            background: 'rgba(245, 166, 35, 0.12)',
            color: 'var(--brand)',
            marginBottom: '16px',
          }}
        >
          <Compass size={32} strokeWidth={1.8} />
        </div>

        <div
          style={{
            fontSize: '13px',
            fontWeight: 700,
            textTransform: 'uppercase',
            letterSpacing: '0.08em',
            color: 'var(--brand)',
            marginBottom: '6px',
          }}
        >
          404 · Destination Unknown
        </div>

        <h1
          style={{
            fontSize: '24px',
            fontWeight: 800,
            margin: '0 0 10px 0',
            letterSpacing: '-0.3px',
            color: 'var(--text-primary)',
          }}
        >
          Lost your bearings?
        </h1>

        <p
          style={{
            fontSize: '14px',
            color: 'var(--text-secondary)',
            margin: '0 0 28px 0',
            lineHeight: 1.5,
          }}
        >
          The page or custom route you requested does not exist or has been relocated. Choose a view below to get back on track.
        </p>

        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(130px, 1fr))',
            gap: '10px',
            marginBottom: '24px',
          }}
        >
          <button
            type="button"
            onClick={() => onSelectTab ? onSelectTab('dashboard') : (onBack && onBack())}
            className="btn-secondary"
            style={{
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              gap: '6px',
              padding: '14px 10px',
              borderRadius: '8px',
              cursor: 'pointer',
              fontSize: '12.5px',
              fontWeight: 600,
            }}
          >
            <Home size={18} strokeWidth={1.8} color="var(--brand)" />
            <span>Dashboard</span>
          </button>

          <button
            type="button"
            onClick={() => onSelectTab ? onSelectTab('timeline') : (onBack && onBack())}
            className="btn-secondary"
            style={{
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              gap: '6px',
              padding: '14px 10px',
              borderRadius: '8px',
              cursor: 'pointer',
              fontSize: '12.5px',
              fontWeight: 600,
            }}
          >
            <Clock size={18} strokeWidth={1.8} color="#2f64c8" />
            <span>Timeline</span>
          </button>

          <button
            type="button"
            onClick={() => onSelectTab ? onSelectTab('compass') : (onBack && onBack())}
            className="btn-secondary"
            style={{
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              gap: '6px',
              padding: '14px 10px',
              borderRadius: '8px',
              cursor: 'pointer',
              fontSize: '12.5px',
              fontWeight: 600,
            }}
          >
            <MessageSquare size={18} strokeWidth={1.8} color="#1c8a62" />
            <span>Compass Chat</span>
          </button>

          <button
            type="button"
            onClick={() => onSelectTab ? onSelectTab('calendar') : (onBack && onBack())}
            className="btn-secondary"
            style={{
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              gap: '6px',
              padding: '14px 10px',
              borderRadius: '8px',
              cursor: 'pointer',
              fontSize: '12.5px',
              fontWeight: 600,
            }}
          >
            <Calendar size={18} strokeWidth={1.8} color="#7e68b5" />
            <span>Schedule</span>
          </button>
        </div>

        <div style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
          <button
            type="button"
            onClick={() => onSelectTab && onSelectTab('terms')}
            style={{ background: 'none', border: 'none', color: 'var(--text-secondary)', cursor: 'pointer', textDecoration: 'underline' }}
          >
            Terms of Service
          </button>
          {' · '}
          <button
            type="button"
            onClick={() => onSelectTab && onSelectTab('privacy')}
            style={{ background: 'none', border: 'none', color: 'var(--text-secondary)', cursor: 'pointer', textDecoration: 'underline' }}
          >
            Privacy Policy
          </button>
        </div>
      </div>
    </div>
  )
}
