import React, { useState, useEffect } from 'react'
import { fetchSharedConversation } from '../api/client'

export default function SharedChatView({ shareId, onGoToApp }) {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [copied, setCopied] = useState(false)

  useEffect(() => {
    async function load() {
      setLoading(true)
      try {
        const result = await fetchSharedConversation(shareId)
        if (result && result.messages) {
          setData(result)
        } else {
          setError('Conversation not found or has been deleted.')
        }
      } catch (err) {
        setError('Failed to load shared conversation.')
      } finally {
        setLoading(false)
      }
    }
    load()
  }, [shareId])

  const handleCopyLink = async () => {
    try {
      await navigator.clipboard.writeText(window.location.href)
      setCopied(true)
      setTimeout(() => setCopied(false), 2500)
    } catch {
      // Fallback
    }
  }

  const renderFormattedText = (text) => {
    if (!text) return null
    const lines = text.split('\n')
    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
        {lines.map((line, i) => {
          const trimmed = line.trim()
          if (!trimmed) return <div key={i} style={{ height: '6px' }} />

          // Headings
          if (trimmed.startsWith('### ')) {
            return (
              <h4 key={i} style={{ margin: '8px 0 2px', fontSize: '14px', fontWeight: '800', color: 'var(--text-primary)' }}>
                {trimmed.replace(/^###\s+/, '')}
              </h4>
            )
          }
          if (trimmed.startsWith('## ')) {
            return (
              <h3 key={i} style={{ margin: '10px 0 3px', fontSize: '15px', fontWeight: '800', color: 'var(--text-primary)' }}>
                {trimmed.replace(/^##\s+/, '')}
              </h3>
            )
          }

          // Bullet points
          if (trimmed.startsWith('- ') || trimmed.startsWith('* ')) {
            const content = trimmed.replace(/^[-*]\s+/, '')
            return (
              <div key={i} style={{ display: 'flex', gap: '8px', paddingLeft: '4px' }}>
                <span style={{ color: 'var(--brand)', fontWeight: '700' }}>•</span>
                <span style={{ color: 'var(--text-primary)', lineHeight: '1.5' }}>
                  {formatBoldSegments(content)}
                </span>
              </div>
            )
          }

          // Regular paragraph
          return (
            <p key={i} style={{ margin: '2px 0', lineHeight: '1.6', color: 'var(--text-primary)' }}>
              {formatBoldSegments(line)}
            </p>
          )
        })}
      </div>
    )
  }

  const formatBoldSegments = (str) => {
    if (!str.includes('**')) return str
    const parts = str.split('**')
    return parts.map((part, idx) =>
      idx % 2 === 1 ? <strong key={idx} style={{ color: 'var(--text-primary)' }}>{part}</strong> : part
    )
  }

  return (
    <div style={{
      display: 'flex',
      flexDirection: 'column',
      height: '100vh',
      width: '100vw',
      background: 'var(--bg-app)',
      color: 'var(--text-primary)',
      overflow: 'hidden',
    }}>
      {/* Top Navbar */}
      <header style={{
        height: '60px',
        borderBottom: '1px solid var(--border)',
        background: 'var(--bg-card)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        padding: '0 24px',
        flexShrink: 0,
        boxShadow: 'var(--shadow-sm)',
      }}>
        {/* Brand */}
        <div
          onClick={onGoToApp}
          style={{ display: 'flex', alignItems: 'center', gap: '10px', cursor: 'pointer' }}
          title="Open Compass Workspace"
        >
          <div style={{
            width: '34px', height: '34px', borderRadius: '9px',
            background: 'var(--brand)', display: 'flex', alignItems: 'center',
            justifyContent: 'center', fontSize: '18px', boxShadow: '0 2px 8px rgba(245, 166, 35, 0.3)'
          }}>
            🧭
          </div>
          <div>
            <div style={{ fontSize: '15px', fontWeight: '800', letterSpacing: '-0.3px', color: 'var(--text-primary)' }}>
              Compass
            </div>
            <div style={{ fontSize: '10px', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.08em', fontWeight: '700' }}>
              Shared Chat
            </div>
          </div>
        </div>

        {/* Center: Title */}
        {data && (
          <div style={{
            fontSize: '13.5px',
            fontWeight: '700',
            color: 'var(--text-primary)',
            maxWidth: '450px',
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            whiteSpace: 'nowrap',
            textAlign: 'center',
          }}>
            {data.title || 'Shared Conversation'}
          </div>
        )}

        {/* Right Actions */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
          <button
            onClick={handleCopyLink}
            style={{
              padding: '7px 13px',
              borderRadius: '8px',
              border: '1px solid var(--border)',
              background: 'transparent',
              color: 'var(--text-secondary)',
              fontSize: '12px',
              fontWeight: '600',
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              gap: '6px'
            }}
          >
            {copied ? '✓ Link Copied' : '🔗 Copy Link'}
          </button>

          <button
            onClick={onGoToApp}
            style={{
              padding: '7px 16px',
              borderRadius: '8px',
              border: 'none',
              background: 'linear-gradient(135deg, #3b82f6 0%, #1d4ed8 100%)',
              color: '#ffffff',
              fontSize: '12.5px',
              fontWeight: '700',
              cursor: 'pointer',
              boxShadow: '0 2px 10px rgba(37, 99, 235, 0.35)',
              display: 'flex',
              alignItems: 'center',
              gap: '6px'
            }}
          >
            <span>Open in Compass</span>
            <span>→</span>
          </button>
        </div>
      </header>

      {/* Main Chat Body */}
      <main style={{
        flex: 1,
        overflowY: 'auto',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        padding: '24px 16px 80px',
      }}>
        <div style={{ width: '100%', maxWidth: '780px', display: 'flex', flexDirection: 'column', gap: '18px' }}>
          {loading ? (
            <div style={{ textAlign: 'center', padding: '80px 20px', color: 'var(--text-muted)' }}>
              <div style={{ fontSize: '28px', marginBottom: '12px', animation: 'spin 1.5s infinite linear' }}>🧭</div>
              <div style={{ fontSize: '14px', fontWeight: '600' }}>Loading shared conversation...</div>
            </div>
          ) : error ? (
            <div style={{
              textAlign: 'center', padding: '60px 20px', background: 'var(--bg-card)',
              borderRadius: '16px', border: '1px solid var(--border)', marginTop: '40px'
            }}>
              <div style={{ fontSize: '32px', marginBottom: '12px' }}>🔒</div>
              <h3 style={{ margin: '0 0 8px', fontSize: '17px', fontWeight: '800' }}>Conversation Not Available</h3>
              <p style={{ margin: '0 0 20px', fontSize: '13px', color: 'var(--text-muted)' }}>{error}</p>
              <button
                onClick={onGoToApp}
                style={{
                  padding: '9px 20px', borderRadius: '8px', border: 'none',
                  background: 'var(--brand)', color: '#2a1a00', fontSize: '13px',
                  fontWeight: '700', cursor: 'pointer'
                }}
              >
                Launch Compass Workspace
              </button>
            </div>
          ) : (
            <>
              {/* Conversation Meta Header Card */}
              <div style={{
                padding: '16px 20px',
                borderRadius: '12px',
                background: 'var(--bg-card)',
                border: '1px solid var(--border)',
                marginBottom: '8px',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
              }}>
                <div>
                  <h1 style={{ margin: 0, fontSize: '18px', fontWeight: '800', color: 'var(--text-primary)', letterSpacing: '-0.3px' }}>
                    {data.title || 'Chat Session'}
                  </h1>
                  <p style={{ margin: '4px 0 0', fontSize: '12px', color: 'var(--text-muted)' }}>
                    Created on {new Date(data.started_at || data.last_active_at).toLocaleDateString(undefined, { weekday: 'long', year: 'numeric', month: 'long', day: 'numeric' })} · {data.messages.length} messages
                  </p>
                </div>
                <div style={{
                  padding: '4px 10px',
                  borderRadius: '12px',
                  background: 'rgba(16, 185, 129, 0.12)',
                  color: '#10b981',
                  fontSize: '11px',
                  fontWeight: '700',
                  border: '1px solid rgba(16, 185, 129, 0.25)',
                }}>
                  Public Snapshot
                </div>
              </div>

              {/* Messages Stream */}
              {data.messages.map((msg, idx) => (
                <div
                  key={msg.id || idx}
                  style={{
                    display: 'flex',
                    flexDirection: 'column',
                    alignItems: msg.role === 'user' ? 'flex-end' : 'flex-start',
                    gap: '4px',
                  }}
                >
                  <div style={{
                    fontSize: '11px',
                    fontWeight: '700',
                    color: 'var(--text-muted)',
                    padding: '0 4px',
                  }}>
                    {msg.role === 'user' ? 'You' : 'Compass Assistant'}
                  </div>
                  <div
                    style={{
                      maxWidth: '82%',
                      padding: '14px 18px',
                      borderRadius: '14px',
                      background: msg.role === 'user' ? 'var(--bg-sidebar)' : 'var(--bg-card)',
                      color: msg.role === 'user' ? 'var(--text-on-dark)' : 'var(--text-primary)',
                      border: msg.role === 'user' ? 'none' : '1px solid var(--border)',
                      fontSize: '13.5px',
                      lineHeight: '1.5',
                      boxShadow: 'var(--shadow-sm)',
                    }}
                  >
                    {renderFormattedText(msg.content)}
                  </div>
                </div>
              ))}

              {/* Bottom CTA Banner */}
              <div style={{
                marginTop: '30px',
                padding: '24px',
                borderRadius: '16px',
                background: 'linear-gradient(135deg, var(--bg-card) 0%, var(--bg-card-soft) 100%)',
                border: '1px solid var(--border)',
                display: 'flex',
                flexDirection: 'column',
                alignItems: 'center',
                textAlign: 'center',
                gap: '12px',
                boxShadow: 'var(--shadow-md)',
              }}>
                <div style={{ fontSize: '24px' }}>🧭</div>
                <div>
                  <h3 style={{ margin: 0, fontSize: '16px', fontWeight: '800' }}>
                    Supercharge your productivity with Compass
                  </h3>
                  <p style={{ margin: '4px 0 0', fontSize: '12.5px', color: 'var(--text-muted)', maxWidth: '500px' }}>
                    Multi-agent autonomous scheduling, code memory recall, and unified timeline feeds for high-velocity teams.
                  </p>
                </div>
                <button
                  onClick={onGoToApp}
                  style={{
                    marginTop: '4px',
                    padding: '10px 24px',
                    borderRadius: '10px',
                    border: 'none',
                    background: 'var(--brand)',
                    color: '#2a1a00',
                    fontSize: '13px',
                    fontWeight: '800',
                    cursor: 'pointer',
                    boxShadow: '0 4px 14px rgba(245, 166, 35, 0.3)',
                  }}
                >
                  Start Using Compass Free →
                </button>
              </div>
            </>
          )}
        </div>
      </main>
    </div>
  )
}
