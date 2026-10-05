import React from 'react'

const QUICK_PROMPTS = [
  { icon: '⚠️', text: 'Check my schedule for conflicts between hackathon and coursework' },
  { icon: '🎯', text: 'What should I prioritize today across all projects?' },
  { icon: '🗓️', text: 'Summarize my commitments for this week' },
  { icon: '🔍', text: 'Verify upcoming deadlines against official sources' },
]

export default function ChatInputBar({
  input,
  setInput,
  onSend,
  isInputDisabled,
  isStreaming,
}) {
  const handleSubmit = (e) => {
    e.preventDefault()
    onSend()
  }

  return (
    <div style={{ padding: '16px 28px 22px', background: 'var(--bg-app)', flexShrink: 0 }}>
      {/* Quick prompt suggestions */}
      <div className="quick-prompts-scroll" style={{ display: 'flex', gap: '8px', marginBottom: '12px', overflowX: 'auto', overflowY: 'hidden', paddingBottom: '6px' }}>
        {QUICK_PROMPTS.map((item, idx) => (
          <button
            key={idx}
            type="button"
            onClick={() => onSend(item.text)}
            disabled={isInputDisabled}
            style={{
              padding: '7px 13px',
              borderRadius: '20px',
              background: 'var(--bg-card)',
              border: '1px solid var(--border)',
              color: 'var(--text-secondary)',
              fontSize: '12px',
              fontWeight: '500',
              cursor: isInputDisabled ? 'not-allowed' : 'pointer',
              display: 'inline-flex',
              alignItems: 'center',
              gap: '6px',
              whiteSpace: 'nowrap',
              transition: 'all 0.15s ease',
              boxShadow: 'var(--shadow-sm)',
              flexShrink: 0
            }}
            onMouseEnter={e => {
              if (!isInputDisabled) {
                e.currentTarget.style.borderColor = 'var(--brand)'
                e.currentTarget.style.color = 'var(--text-primary)'
                e.currentTarget.style.background = 'var(--bg-card-soft)'
              }
            }}
            onMouseLeave={e => {
              e.currentTarget.style.borderColor = 'var(--border)'
              e.currentTarget.style.color = 'var(--text-secondary)'
              e.currentTarget.style.background = 'var(--bg-card)'
            }}
          >
            <span>{item.icon}</span>
            <span>{item.text}</span>
          </button>
        ))}
      </div>

      <form onSubmit={handleSubmit} style={{ display: 'flex', gap: '10px' }}>
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder={isStreaming ? 'Streaming response...' : 'Ask me anything, or say "add a task"...'}
          disabled={isInputDisabled}
          style={{
            flex: 1,
            padding: '13px 17px',
            borderRadius: '10px',
            background: isInputDisabled ? 'var(--bg-card-soft)' : 'var(--bg-card)',
            border: '1px solid var(--border)',
            color: isInputDisabled ? 'var(--text-muted)' : 'var(--text-primary)',
            fontSize: '13.5px',
            outline: 'none',
            cursor: isInputDisabled ? 'not-allowed' : 'text'
          }}
        />
        <button
          type="submit"
          disabled={isInputDisabled || !input.trim()}
          style={{
            padding: '0 24px',
            borderRadius: '10px',
            background: 'var(--brand)',
            border: 'none',
            color: '#2a1a00',
            fontWeight: '700',
            fontSize: '13px',
            cursor: (isInputDisabled || !input.trim()) ? 'not-allowed' : 'pointer',
            opacity: (!input.trim() || isInputDisabled) ? 0.5 : 1,
            transition: 'opacity 0.15s ease'
          }}>
          Send
        </button>
      </form>
    </div>
  )
}
