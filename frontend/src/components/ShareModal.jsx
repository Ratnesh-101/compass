import React, { useState } from 'react'

export default function ShareModal({ isOpen, onClose, conversation }) {
  const [copied, setCopied] = useState(false)

  if (!isOpen || !conversation) return null

  const shareUrl = `${window.location.origin}/?share=${conversation.id}`

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(shareUrl)
      setCopied(true)
      setTimeout(() => setCopied(false), 2500)
    } catch {
      // Fallback
      const input = document.getElementById('share-link-input')
      if (input) {
        input.select()
        document.execCommand('copy')
        setCopied(true)
        setTimeout(() => setCopied(false), 2500)
      }
    }
  }

  const handleOpenLink = () => {
    window.open(shareUrl, '_blank')
  }

  return (
    <div
      onClick={onClose}
      style={{
        position: 'fixed',
        inset: 0,
        background: 'rgba(0, 0, 0, 0.7)',
        backdropFilter: 'blur(4px)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        zIndex: 1100,
        padding: '16px',
      }}
    >
      <div
        onClick={e => e.stopPropagation()}
        style={{
          background: 'var(--bg-card)',
          border: '1px solid var(--border)',
          borderRadius: '16px',
          padding: '24px',
          maxWidth: '460px',
          width: '100%',
          boxShadow: 'var(--shadow-lg), 0 20px 40px rgba(0,0,0,0.6)',
          display: 'flex',
          flexDirection: 'column',
          gap: '16px',
          animation: 'fadeIn 0.15s ease',
        }}
      >
        {/* Header */}
        <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: '12px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            <div style={{
              width: '36px', height: '36px', borderRadius: '10px',
              background: 'linear-gradient(135deg, rgba(59, 130, 246, 0.2) 0%, rgba(37, 99, 235, 0.3) 100%)',
              color: '#3b82f6', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '18px'
            }}>
              🔗
            </div>
            <div>
              <h3 style={{ margin: 0, fontSize: '16px', fontWeight: '800', color: 'var(--text-primary)', letterSpacing: '-0.2px' }}>
                Share link to chat
              </h3>
              <p style={{ margin: '2px 0 0', fontSize: '12px', color: 'var(--text-muted)' }}>
                Anyone with this link will be able to view this chat.
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            style={{
              background: 'none', border: 'none', color: 'var(--text-muted)',
              fontSize: '18px', cursor: 'pointer', padding: '2px 6px', borderRadius: '6px'
            }}
            title="Close"
          >
            ✕
          </button>
        </div>

        {/* Chat Preview Card */}
        <div style={{
          padding: '12px 14px',
          borderRadius: '10px',
          background: 'var(--bg-app)',
          border: '1px solid var(--border)',
          display: 'flex',
          flexDirection: 'column',
          gap: '4px',
        }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <span style={{ fontSize: '13px', fontWeight: '700', color: 'var(--text-primary)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {conversation.title || 'Chat Session'}
            </span>
            <span style={{ fontSize: '11px', color: 'var(--text-muted)', whiteSpace: 'nowrap' }}>
              {conversation.message_count || 0} messages
            </span>
          </div>
          {conversation.preview && (
            <div style={{ fontSize: '11.5px', color: 'var(--text-secondary)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', opacity: 0.85 }}>
              "{conversation.preview}"
            </div>
          )}
        </div>

        {/* Link Input & Copy Button */}
        <div style={{ display: 'flex', gap: '8px' }}>
          <input
            id="share-link-input"
            type="text"
            readOnly
            value={shareUrl}
            onClick={e => e.target.select()}
            style={{
              flex: 1,
              padding: '10px 14px',
              borderRadius: '8px',
              background: 'var(--bg-app)',
              border: '1px solid var(--border)',
              color: 'var(--text-primary)',
              fontSize: '12.5px',
              outline: 'none',
              fontFamily: 'monospace',
            }}
          />
          <button
            id="btn-copy-share-link"
            onClick={handleCopy}
            style={{
              padding: '10px 18px',
              borderRadius: '8px',
              border: 'none',
              background: copied ? '#10b981' : 'linear-gradient(135deg, #3b82f6 0%, #1d4ed8 100%)',
              color: '#ffffff',
              fontSize: '12.5px',
              fontWeight: '700',
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
              whiteSpace: 'nowrap',
              boxShadow: copied ? '0 2px 10px rgba(16, 185, 129, 0.4)' : '0 2px 10px rgba(37, 99, 235, 0.35)',
              transition: 'all 0.2s ease',
            }}
          >
            {copied ? (
              <>
                <span>✓</span>
                <span>Copied!</span>
              </>
            ) : (
              <>
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                  <rect x="9" y="9" width="13" height="13" rx="2" ry="2"/>
                  <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>
                </svg>
                <span>Copy Link</span>
              </>
            )}
          </button>
        </div>

        {/* Footer info & open in new tab */}
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', paddingTop: '4px' }}>
          <span style={{ fontSize: '11px', color: 'var(--text-muted)' }}>
            Link is active and viewable by anyone.
          </span>
          <button
            onClick={handleOpenLink}
            style={{
              background: 'none', border: 'none', color: 'var(--brand)',
              fontSize: '12px', fontWeight: '700', cursor: 'pointer',
              display: 'flex', alignItems: 'center', gap: '4px'
            }}
          >
            <span>Open preview</span>
            <span style={{ fontSize: '11px' }}>↗</span>
          </button>
        </div>
      </div>
    </div>
  )
}
