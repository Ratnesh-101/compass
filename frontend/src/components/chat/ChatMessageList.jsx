import React from 'react'
import EvidenceCard from './EvidenceCard'

function getTimeGreeting() {
  const hour = new Date().getHours()
  if (hour < 12) return 'Good morning'
  if (hour < 18) return 'Good afternoon'
  return 'Good evening'
}

/**
 * Preserves formatting, line breaks, bullet points, and router latency chips
 */
function renderFormattedMessage(text) {
  if (!text) return null
  const lines = text.split('\n')

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '3px' }}>
      {lines.map((line, i) => {
        const trimmed = line.trim()

        // 1. Router Latency Badge Chip (⚡ [Routed via Nemotron-3 Nano in 342ms])
        if (line.includes('Routed via Nemotron-3 Nano') || line.includes('⚡')) {
          return (
            <div key={i} className="router-chip">
              <span style={{ fontSize: '13px' }}>⚡</span>
              <span>{line.replace('⚡', '').trim()}</span>
            </div>
          )
        }

        // 2. Coursework Deliverables Heading
        if (line.includes('Coursework') && (line.includes('📚') || line.includes('CS 61C'))) {
          return (
            <div key={i} style={{ marginTop: '10px', marginBottom: '4px', color: 'var(--coursework-text)', fontWeight: '600', display: 'flex', alignItems: 'center', gap: '8px' }}>
              <span className="badge-coursework" style={{ padding: '2px 8px', borderRadius: '20px', fontSize: '11px', textTransform: 'uppercase' }}>
                Coursework
              </span>
              <span>{line.replace(/^\d+\.\s*/, '').replace('📚', '').trim()}</span>
            </div>
          )
        }

        // 3. Hackathon Deliverables Heading
        if (line.includes('Hackathon') && (line.includes('🚀') || line.includes('Nebius'))) {
          return (
            <div key={i} style={{ marginTop: '10px', marginBottom: '4px', color: 'var(--hackathon-text)', fontWeight: '600', display: 'flex', alignItems: 'center', gap: '8px' }}>
              <span className="badge-hackathon" style={{ padding: '2px 8px', borderRadius: '20px', fontSize: '11px', textTransform: 'uppercase' }}>
                Hackathon
              </span>
              <span>{line.replace(/^\d+\.\s*/, '').replace('🚀', '').trim()}</span>
            </div>
          )
        }

        // 4. Actionable Next Step Callout
        if (line.includes('Next Step:')) {
          return (
            <div key={i} style={{ marginTop: '12px', padding: '10px 14px', borderRadius: '10px', background: 'var(--bg-card-soft)', border: '1px solid var(--border)', color: 'var(--code-text)', fontSize: '12.5px', fontFamily: 'JetBrains Mono, monospace', display: 'flex', alignItems: 'center', gap: '8px' }}>
              <span style={{ color: 'var(--code)' }}>❯</span>
              <span>{line}</span>
            </div>
          )
        }

        // 5. Bullet Points (• or -)
        if (trimmed.startsWith('•') || trimmed.startsWith('-')) {
          return (
            <div key={i} style={{ display: 'flex', alignItems: 'flex-start', gap: '8px', margin: '3px 0 3px 6px', color: 'var(--text-primary)', fontSize: '13.5px' }}>
              <span style={{ color: 'var(--coursework)', fontWeight: '700', lineHeight: '1.4' }}>•</span>
              <span style={{ lineHeight: '1.5' }}>{trimmed.replace(/^[•-]\s*/, '')}</span>
            </div>
          )
        }

        // 6. Empty Lines / Spacing
        if (!trimmed) {
          return <div key={i} style={{ height: '6px' }} />
        }

        // 7. Regular Text Paragraph
        return (
          <p key={i} style={{ margin: '2px 0', lineHeight: '1.6', color: 'var(--text-primary)' }}>
            {line}
          </p>
        )
      })}
    </div>
  )
}

export default function ChatMessageList({
  messages,
  isStreaming,
  streamingText,
  isTyping,
  messagesEndRef,
}) {
  return (
    <div style={{ flex: 1, overflowY: 'auto', display: 'flex', flexDirection: 'column', padding: '24px 28px', minWidth: 0 }}>
      <div className="serif-accent" style={{ fontSize: '15px', color: 'var(--text-secondary)', marginBottom: '18px' }}>
        {getTimeGreeting()}
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
        {messages.map((msg, idx) => (
          <div key={idx} style={{ display: 'flex', gap: '10px', justifyContent: msg.role === 'user' ? 'flex-end' : 'flex-start' }}>
            {msg.role === 'assistant' && (
              <div style={{
                width: '30px', height: '30px', borderRadius: '8px', background: 'var(--bg-sidebar)',
                display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '14px', flexShrink: 0
              }}>
                🧭
              </div>
            )}
            <div style={{
              maxWidth: '75%',
              padding: '13px 17px',
              borderRadius: '14px',
              background: msg.role === 'user' ? 'var(--bg-sidebar)' : 'var(--bg-card)',
              color: msg.role === 'user' ? 'var(--text-on-dark)' : 'var(--text-primary)',
              fontSize: '13.5px',
              lineHeight: '1.5',
              border: msg.role === 'user' ? 'none' : '1px solid var(--border)',
              boxShadow: 'var(--shadow-sm)'
            }}>
              {msg.role === 'user' ? msg.text : renderFormattedMessage(msg.text)}
              {msg.role === 'assistant' && msg.evidence && (
                <EvidenceCard evidence={msg.evidence} />
              )}
            </div>
          </div>
        ))}

        {/* Active Progressive Token Streaming Bubble */}
        {isStreaming && (
          <div style={{ display: 'flex', gap: '10px', justifyContent: 'flex-start' }}>
            <div style={{
              width: '30px', height: '30px', borderRadius: '8px', background: 'var(--bg-sidebar)',
              display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '14px', flexShrink: 0
            }}>
              🧭
            </div>
            <div style={{
              maxWidth: '75%',
              padding: '13px 17px',
              borderRadius: '14px',
              background: 'var(--bg-card)',
              color: 'var(--text-primary)',
              fontSize: '13.5px',
              lineHeight: '1.5',
              border: '1px solid var(--border)',
              boxShadow: 'var(--shadow-md)'
            }}>
              {renderFormattedMessage(streamingText)}
              <span className="streaming-caret" style={{ background: 'var(--coursework)' }} />
            </div>
          </div>
        )}

        {/* Loading Indicator */}
        {isTyping && !isStreaming && (
          <div style={{ color: 'var(--text-muted)', fontSize: '12px', fontStyle: 'italic', display: 'flex', alignItems: 'center', gap: '8px', padding: '6px 12px' }}>
            <span style={{ display: 'inline-block', width: '7px', height: '7px', borderRadius: '50%', background: 'var(--coursework)' }} />
            Thinking...
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>
    </div>
  )
}
