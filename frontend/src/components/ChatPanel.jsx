import React, { useState } from 'react'

export default function ChatPanel({ messages, onSendMessage, isTyping }) {
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
    onSendMessage(prompt)
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', flex: 1, padding: '28px', height: 'calc(100vh - 64px)' }}>
      {/* Message Feed */}
      <div style={{ flex: 1, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: '16px', marginBottom: '16px' }}>
        {messages.map((msg, idx) => (
          <div key={idx} style={{ display: 'flex', justifyContent: msg.role === 'user' ? 'flex-end' : 'flex-start' }}>
            <div style={{ maxWidth: '75%', padding: '14px 18px', borderRadius: '12px', background: msg.role === 'user' ? '#3b82f6' : '#1e293b', color: '#fff', fontSize: '14px', lineHeight: '1.5', whiteSpace: 'pre-wrap', border: msg.role === 'user' ? 'none' : '1px solid #334155' }}>
              {msg.text}
            </div>
          </div>
        ))}
        {isTyping && (
          <div style={{ color: '#94a3b8', fontSize: '13px', fontStyle: 'italic', display: 'flex', alignItems: 'center', gap: '8px' }}>
            <span style={{ display: 'inline-block', width: '8px', height: '8px', borderRadius: '50%', background: '#6366f1' }} />
            ⚡ Nemotron-3 Nano dispatching function calls & synthesizing context...
          </div>
        )}
      </div>

      {/* Demo Script Preset Prompt Pill */}
      <div style={{ marginBottom: '12px' }}>
        <button
          onClick={handleQuickPrompt}
          style={{ padding: '8px 14px', borderRadius: '8px', background: '#1e293b', border: '1px solid #3b82f6', color: '#93c5fd', fontSize: '12px', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '6px' }}>
          💡 Click to test: <strong>"What are my top deliverables across coursework and hackathon before Friday?"</strong>
        </button>
      </div>

      {/* Input Bar */}
      <form onSubmit={handleSubmit} style={{ display: 'flex', gap: '10px' }}>
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Ask Compass across your hackathons, coursework, or repos..."
          style={{ flex: 1, padding: '14px 18px', borderRadius: '8px', background: '#111827', border: '1px solid #374151', color: '#fff', fontSize: '14px', outline: 'none' }}
        />
        <button
          type="submit"
          style={{ padding: '0 24px', borderRadius: '8px', background: '#6366f1', border: 'none', color: '#fff', fontWeight: '600', cursor: 'pointer' }}>
          Send
        </button>
      </form>
    </div>
  )
}
