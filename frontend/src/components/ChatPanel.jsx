import React, { useState } from 'react'

export default function ChatPanel({ messages = [], onSendMessage, isTyping = false }) {
  const [input, setInput] = useState('')

  const handleSubmit = (e) => {
    e.preventDefault()
    if (!input.trim()) return
    onSendMessage(input)
    setInput('')
  }

  const handleQuickPrompt = () => {
    const prompt = 'What are my top deliverables across coursework and hackathon before Friday?'
    setInput(prompt)
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', flex: 1, padding: '28px', height: 'calc(100vh - 64px)' }}>
      {/* Message Bubble Stream */}
      <div style={{
        flex: 1,
        overflowY: 'auto',
        display: 'flex',
        flexDirection: 'column',
        gap: '16px',
        marginBottom: '16px',
        paddingRight: '8px'
      }}>
        {messages.map((msg, i) => (
          <div
            key={i}
            style={{
              display: 'flex',
              justifyContent: msg.role === 'user' ? 'flex-end' : 'flex-start'
            }}>
            <div style={{
              maxWidth: '75%',
              padding: '14px 18px',
              borderRadius: '12px',
              background: msg.role === 'user' ? '#3b82f6' : '#1e293b',
              color: '#fff',
              fontSize: '14px',
              lineHeight: '1.6',
              whiteSpace: 'pre-wrap',
              border: msg.role === 'user' ? 'none' : '1px solid #334155',
              boxShadow: '0 2px 4px rgba(0,0,0,0.2)'
            }}>
              {msg.text}
            </div>
          </div>
        ))}

        {isTyping && (
          <div style={{
            color: '#60a5fa',
            fontSize: '13px',
            fontStyle: 'italic',
            display: 'flex',
            alignItems: 'center',
            gap: '8px',
            padding: '8px 0'
          }}>
            <span style={{ animation: 'pulse 1s infinite' }}>⚡</span>
            <span>Routed via Nemotron-3 Nano in 342ms & synthesizing pgvector context...</span>
          </div>
        )}
      </div>

      {/* Suggested Prompt Button Pill */}
      <div style={{ marginBottom: '12px' }}>
        <button
          onClick={handleQuickPrompt}
          style={{
            padding: '8px 14px',
            borderRadius: '20px',
            background: 'rgba(99, 102, 241, 0.1)',
            border: '1px solid rgba(99, 102, 241, 0.3)',
            color: '#a5b4fc',
            fontSize: '12px',
            cursor: 'pointer',
            transition: 'all 0.15s',
            display: 'inline-flex',
            alignItems: 'center',
            gap: '6px'
          }}>
          <span>💡 Quick prompt:</span>
          <strong>"What are my top deliverables across coursework and hackathon before Friday?"</strong>
        </button>
      </div>

      {/* Chat Input Bar */}
      <form onSubmit={handleSubmit} style={{ display: 'flex', gap: '10px' }}>
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Ask Compass to coordinate across hackathons, coursework, and code..."
          style={{
            flex: 1,
            padding: '14px 18px',
            borderRadius: '8px',
            background: '#111827',
            border: '1px solid #374151',
            color: '#fff',
            fontSize: '14px',
            outline: 'none'
          }}
        />
        <button
          type="submit"
          style={{
            padding: '0 24px',
            borderRadius: '8px',
            background: '#6366f1',
            border: 'none',
            color: '#fff',
            fontWeight: '600',
            cursor: 'pointer',
            fontSize: '14px',
            transition: 'background 0.15s'
          }}>
          Send
        </button>
      </form>
    </div>
  )
}
