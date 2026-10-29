import React, { useState, useEffect } from 'react'
import { Link2, X, Check, Copy, ExternalLink } from 'lucide-react'
import { updateConversation } from '../api/client'
import Dialog from './Dialog'

export default function ShareModal({ isOpen, onClose, conversation, onConversationUpdated }) {
  const [copied, setCopied] = useState(false)
  const [shareToken, setShareToken] = useState(conversation?.share_token || null)
  const [isGenerating, setIsGenerating] = useState(false)
  const [isRevoking, setIsRevoking] = useState(false)
  const [error, setError] = useState(null)
  const [showRegenConfirm, setShowRegenConfirm] = useState(false)

  useEffect(() => {
    if (!isOpen || !conversation) return
    setError(null)
    setShowRegenConfirm(false)
    if (conversation.share_token) {
      setShareToken(conversation.share_token)
    } else {
      setShareToken(null)
    }
  }, [isOpen, conversation])

  if (!isOpen || !conversation) return null

  const isAlreadyShared = Boolean(conversation.is_shared)
  const hasVisibleToken = Boolean(shareToken)

  const handleGenerateLink = async () => {
    setIsGenerating(true)
    setError(null)
    setShowRegenConfirm(false)
    try {
      const result = await updateConversation(conversation.id, { is_shared: true })
      if (result && result.share_token) {
        setShareToken(result.share_token)
        if (onConversationUpdated) {
          onConversationUpdated({
            ...conversation,
            is_shared: true,
            share_token: result.share_token,
          })
        }
      } else {
        setError('Failed to generate secure share link. Please try again.')
      }
    } catch {
      setError('Failed to generate secure share link. Please check your connection.')
    } finally {
      setIsGenerating(false)
    }
  }

  const handleRevoke = async () => {
    setIsRevoking(true)
    setError(null)
    try {
      await updateConversation(conversation.id, { is_shared: false })
      setShareToken(null)
      if (onConversationUpdated) {
        onConversationUpdated({
          ...conversation,
          is_shared: false,
          share_token: null,
        })
      }
    } catch {
      setError('Failed to revoke share link. Please try again.')
    } finally {
      setIsRevoking(false)
    }
  }

  const shareUrl = shareToken
    ? `${window.location.origin}/?share=${encodeURIComponent(shareToken)}`
    : ''

  const handleCopy = async () => {
    if (!shareUrl || isGenerating) return
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
    if (shareUrl) {
      window.open(shareUrl, '_blank')
    }
  }

  return (
    <Dialog onClose={onClose}
      onClick={onClose}
      style={{
        position: 'fixed',
        inset: 0,
        background: 'rgba(27, 26, 23, 0.45)',
        backdropFilter: 'blur(3px)',
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
          borderRadius: 'var(--radius-card, 8px)',
          padding: '24px',
          maxWidth: '460px',
          width: '100%',
          boxShadow: '0 8px 30px rgba(0, 0, 0, 0.12)',
          display: 'flex',
          flexDirection: 'column',
          gap: '16px',
        }}
      >
        {/* Header */}
        <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: '12px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            <div style={{
              width: '36px', height: '36px', borderRadius: 'var(--radius-btn, 6px)',
              background: 'var(--bg-card-soft)', border: '1px solid var(--border)',
              color: 'var(--text-primary)', display: 'flex', alignItems: 'center', justifyContent: 'center'
            }}>
              <Link2 size={18} strokeWidth={1.8} />
            </div>
            <div>
              <h3 style={{ margin: 0, fontSize: '16px', fontWeight: '600', color: 'var(--text-primary)', letterSpacing: '-0.2px' }}>
                Share link to chat
              </h3>
              <p style={{ margin: '2px 0 0', fontSize: '13px', color: 'var(--text-muted)' }}>
                Anyone with this secure link will be able to view this chat snapshot.
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            aria-label="Close"
            className="btn-touch-target btn-secondary"
            style={{
              color: 'var(--text-muted)',
              cursor: 'pointer',
              width: '32px',
              height: '32px',
              minHeight: '32px',
              borderRadius: 'var(--radius-btn, 6px)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
            }}
            title="Close"
          >
            <X size={16} strokeWidth={1.8} />
          </button>
        </div>

        {/* Chat Preview Card */}
        <div style={{
          padding: '12px 14px',
          borderRadius: 'var(--radius-card, 8px)',
          background: 'var(--bg-card-soft)',
          border: '1px solid var(--border)',
          display: 'flex',
          flexDirection: 'column',
          gap: '4px',
        }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <span style={{ fontSize: '13px', fontWeight: '600', color: 'var(--text-primary)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {conversation.title || 'Chat Session'}
            </span>
            <span style={{ fontSize: '12px', color: 'var(--text-muted)', whiteSpace: 'nowrap' }}>
              {conversation.message_count || 0} messages
            </span>
          </div>
          {conversation.preview && (
            <div style={{ fontSize: '12px', color: 'var(--text-secondary)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', opacity: 0.85 }}>
              "{conversation.preview}"
            </div>
          )}
        </div>

        {/* Error Notification if generation fails */}
        {error && (
          <div style={{
            fontSize: '12px',
            color: '#ef4444',
            background: 'rgba(239, 68, 68, 0.08)',
            padding: '8px 12px',
            borderRadius: '6px',
            border: '1px solid rgba(239, 68, 68, 0.2)',
          }}>
            {error}
          </div>
        )}

        {/* Shared state controls */}
        {hasVisibleToken ? (
          <>
            {/* Link Input & Copy Button */}
            <div style={{ display: 'flex', gap: '8px' }}>
              <input
                id="share-link-input"
                type="text"
                readOnly
                value={shareUrl}
                placeholder="Share link"
                onClick={e => {
                  if (shareUrl) e.target.select()
                }}
                style={{
                  flex: 1,
                  padding: '10px 14px',
                  borderRadius: 'var(--radius-btn, 6px)',
                  background: 'var(--bg-app)',
                  border: '1px solid var(--border)',
                  color: 'var(--text-primary)',
                  fontSize: '13px',
                  outline: 'none',
                  fontFamily: 'monospace',
                  minHeight: '44px',
                }}
              />
              <button
                id="btn-copy-share-link"
                onClick={handleCopy}
                disabled={!shareUrl}
                className="btn-touch-target btn-primary-amber"
                style={{
                  padding: '10px 18px',
                  borderRadius: 'var(--radius-btn, 6px)',
                  fontSize: '13px',
                  fontWeight: '600',
                  cursor: 'pointer',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '6px',
                  whiteSpace: 'nowrap',
                  minHeight: '44px',
                }}
              >
                {copied ? (
                  <>
                    <Check size={14} strokeWidth={1.8} />
                    <span>Copied!</span>
                  </>
                ) : (
                  <>
                    <Copy size={14} strokeWidth={1.8} />
                    <span>Copy Link</span>
                  </>
                )}
              </button>
            </div>

            {/* Footer info & open in new tab */}
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', paddingTop: '4px' }}>
              <span style={{ fontSize: '12px', color: 'var(--text-muted)' }}>
                Link is active and viewable by anyone with the link.
              </span>
              <button
                onClick={handleOpenLink}
                style={{
                  background: 'none', border: 'none',
                  color: 'var(--accent)',
                  fontSize: '13px', fontWeight: '600',
                  cursor: 'pointer',
                  display: 'flex', alignItems: 'center', gap: '4px',
                  minHeight: '36px',
                }}
              >
                <span>Open preview</span>
                <ExternalLink size={12} strokeWidth={1.8} />
              </button>
            </div>
          </>
        ) : isAlreadyShared ? (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
            <div style={{
              background: 'rgba(34, 197, 94, 0.08)',
              border: '1px solid rgba(34, 197, 94, 0.25)',
              borderRadius: '6px',
              padding: '10px 14px',
              fontSize: '13px',
              color: 'var(--text-primary)',
              display: 'flex',
              alignItems: 'center',
              gap: '8px'
            }}>
              <span style={{ width: '8px', height: '8px', borderRadius: '50%', background: '#22c55e', flexShrink: 0 }} />
              <span>This conversation is currently shared. Active links remain valid until revoked.</span>
            </div>

            <p style={{ margin: 0, fontSize: '12px', color: 'var(--text-muted)', lineHeight: '1.5' }}>
              To protect your privacy, plaintext tokens are not retained in storage. You can create a new link below or revoke access.
            </p>

            {showRegenConfirm ? (
              <div style={{
                background: 'rgba(234, 179, 8, 0.1)',
                border: '1px solid rgba(234, 179, 8, 0.3)',
                borderRadius: '6px',
                padding: '12px',
                display: 'flex',
                flexDirection: 'column',
                gap: '10px',
              }}>
                <span style={{ fontSize: '12px', fontWeight: '600', color: 'var(--text-primary)' }}>
                  ⚠️ Warning: Creating a new link will immediately revoke the existing link. Anyone with the old link will lose access.
                </span>
                <div style={{ display: 'flex', gap: '8px', justifyContent: 'flex-end' }}>
                  <button
                    onClick={() => setShowRegenConfirm(false)}
                    className="btn-touch-target btn-secondary"
                    style={{ padding: '6px 12px', fontSize: '12px', cursor: 'pointer' }}
                  >
                    Cancel
                  </button>
                  <button
                    id="btn-confirm-regen-link"
                    onClick={handleGenerateLink}
                    disabled={isGenerating}
                    className="btn-touch-target btn-primary-amber"
                    style={{ padding: '6px 14px', fontSize: '12px', fontWeight: '600', cursor: 'pointer' }}
                  >
                    {isGenerating ? 'Creating…' : 'Yes, create new link'}
                  </button>
                </div>
              </div>
            ) : (
              <div style={{ display: 'flex', gap: '8px', justifyContent: 'flex-end', paddingTop: '4px' }}>
                <button
                  id="btn-revoke-share"
                  onClick={handleRevoke}
                  disabled={isRevoking}
                  className="btn-touch-target btn-secondary"
                  style={{
                    padding: '8px 14px',
                    fontSize: '12px',
                    color: '#ef4444',
                    borderColor: 'rgba(239, 68, 68, 0.3)',
                    cursor: isRevoking ? 'not-allowed' : 'pointer',
                  }}
                >
                  {isRevoking ? 'Revoking…' : 'Revoke link'}
                </button>
                <button
                  id="btn-create-new-link"
                  onClick={() => setShowRegenConfirm(true)}
                  className="btn-touch-target btn-primary-amber"
                  style={{ padding: '8px 16px', fontSize: '12px', fontWeight: '600', cursor: 'pointer' }}
                >
                  Create new link
                </button>
              </div>
            )}
          </div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
            <p style={{ margin: 0, fontSize: '13px', color: 'var(--text-muted)' }}>
              No active share link. Generate a secure, read-only link to share a snapshot of this chat.
            </p>
            <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
              <button
                id="btn-create-share-link"
                onClick={handleGenerateLink}
                disabled={isGenerating}
                className="btn-touch-target btn-primary-amber"
                style={{
                  padding: '10px 18px',
                  borderRadius: 'var(--radius-btn, 6px)',
                  fontSize: '13px',
                  fontWeight: '600',
                  cursor: isGenerating ? 'not-allowed' : 'pointer',
                }}
              >
                {isGenerating ? 'Generating…' : 'Create share link'}
              </button>
            </div>
          </div>
        )}
      </div>
    </Dialog>
  )
}

