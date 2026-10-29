import React from 'react'

const TOAST_STYLE = {
  position: 'fixed',
  top: '12px',
  left: '50%',
  transform: 'translateX(-50%)',
  zIndex: 1200,
  display: 'flex',
  flexDirection: 'column',
  gap: '8px',
  width: 'min(92vw, 460px)',
  pointerEvents: 'none',
}

const ITEM_BASE = {
  pointerEvents: 'auto',
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'space-between',
  gap: '10px',
  padding: '10px 14px',
  borderRadius: '8px',
  fontSize: '13px',
  lineHeight: 1.4,
  background: 'var(--bg-card)',
  color: 'var(--text-primary)',
  border: '1px solid var(--border)',
  boxShadow: 'var(--shadow-lg)',
}

const TYPE_ACCENT = {
  success: '#059669',
  error: '#dc2626',
  info: '#d97706',
}

/**
 * Top-of-screen status messages: the OAuth return outcome and the "service is busy" state.
 */
export default function StatusNotices({ notice, onDismissNotice, serviceBusy }) {
  if (!notice && !serviceBusy) return null
  return (
    <div style={TOAST_STYLE}>
      {serviceBusy && (
        <div id="service-busy-banner" role="status" style={{ ...ITEM_BASE, borderColor: TYPE_ACCENT.info }}>
          <span>Service is busy - retrying shortly.</span>
        </div>
      )}
      {notice && (
        <div
          id="oauth-notice"
          role={notice.type === 'error' ? 'alert' : 'status'}
          style={{ ...ITEM_BASE, borderColor: TYPE_ACCENT[notice.type] || TYPE_ACCENT.info }}
        >
          <span>{notice.text}</span>
          <button
            type="button"
            onClick={onDismissNotice}
            aria-label="Dismiss message"
            style={{
              background: 'transparent',
              border: 'none',
              color: 'var(--text-secondary)',
              cursor: 'pointer',
              fontSize: '16px',
              minWidth: '32px',
              minHeight: '32px',
            }}
          >
            ×
          </button>
        </div>
      )}
    </div>
  )
}
